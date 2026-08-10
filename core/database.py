import os
import shutil
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

BACKUP_KEEP = 5

def get_db_path(drive_path: str) -> str:
    dot_db = os.path.join(drive_path, "albums", ".media_library.db")
    plain_db = os.path.join(drive_path, "albums", "media_library.db")
    if os.path.exists(plain_db) and not os.path.exists(dot_db):
        return plain_db
    return dot_db

def initialize_database(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    
    # 1. media_items table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT NOT NULL,
            original_relative_path TEXT UNIQUE NOT NULL,
            current_relative_path TEXT UNIQUE NOT NULL,
            file_size INTEGER NOT NULL,
            mime_type TEXT NOT NULL,
            duration_seconds INTEGER DEFAULT NULL,
            metadata_json TEXT,
            album_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. albums table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            relative_path TEXT UNIQUE NOT NULL,
            description TEXT,
            media_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. tags table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            color_hex TEXT NOT NULL DEFAULT '#3B82F6',
            category TEXT DEFAULT 'General'
        );
    """)

    # 4. media_tags table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_tags (
            media_id INTEGER,
            tag_id INTEGER,
            PRIMARY KEY (media_id, tag_id)
        );
    """)

    # Schema migration: Check if media_count exists in albums
    cursor.execute("PRAGMA table_info(albums);")
    columns = [info[1] for info in cursor.fetchall()]
    if "media_count" not in columns:
        cursor.execute("ALTER TABLE albums ADD COLUMN media_count INTEGER DEFAULT 0;")
        # Populate media_count value for existing rows
        cursor.execute("""
            UPDATE albums SET media_count = (
                SELECT COUNT(*) FROM media_items WHERE album_id = albums.id
            );
        """)

    # SQLite Triggers to keep media_count up to date automatically
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS after_media_insert
        AFTER INSERT ON media_items
        BEGIN
            UPDATE albums SET media_count = media_count + 1 WHERE id = NEW.album_id;
        END;
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS after_media_delete
        AFTER DELETE ON media_items
        BEGIN
            UPDATE albums SET media_count = MAX(0, media_count - 1) WHERE id = OLD.album_id;
        END;
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS after_media_update
        AFTER UPDATE OF album_id ON media_items
        WHEN OLD.album_id != NEW.album_id
        BEGIN
            UPDATE albums SET media_count = MAX(0, media_count - 1) WHERE id = OLD.album_id;
            UPDATE albums SET media_count = media_count + 1 WHERE id = NEW.album_id;
        END;
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_album_created ON media_items(album_id, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_created ON media_items(created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_mime ON media_items(mime_type);")

    cursor.execute("""
        INSERT OR IGNORE INTO albums (name, relative_path, description)
        VALUES ('unknown', 'albums/unknown', 'Default album for unsorted media');
    """)

    cursor.execute("SELECT id FROM albums WHERE name = 'unknown'")
    row = cursor.fetchone()
    if row:
        unknown_album_id = row[0]
        cursor.execute("UPDATE media_items SET album_id = ? WHERE album_id IS NULL", (unknown_album_id,))

    conn.commit()


def open_library_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    
    cursor = conn.cursor()
    cursor.execute("PRAGMA busy_timeout = 5000;")
    cursor.execute("PRAGMA journal_mode = DELETE;")
    cursor.execute("PRAGMA synchronous = FULL;")
    
    return conn


def open_readable_db(db_path: str) -> sqlite3.Connection:
    # Safely verify / run database schema migrations in write mode first
    try:
        if os.path.exists(db_path) and os.access(os.path.dirname(db_path), os.W_OK):
            conn_w = get_database_connection(db_path)
            if conn_w:
                conn_w.close()
    except Exception as e:
        print(f"[Database] Migration verify check failed (possibly read-only volume): {e}")

    db_uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def backup_dir_for(db_path: str) -> str:
    return os.path.join(os.path.dirname(db_path), ".backups")


def is_corruption_error(exception: Exception) -> bool:
    msg = str(exception).lower()
    return (
        "malformed" in msg or 
        "corrupt" in msg or 
        "disk image" in msg or 
        "not a database" in msg
    )


def create_backup(db_path: str) -> Optional[str]:
    if not os.path.exists(db_path):
        return None
        
    backup_dir = backup_dir_for(db_path)
    os.makedirs(backup_dir, exist_ok=True)
    
    stamp = datetime.now().isoformat().replace(":", "-").replace(".", "-")
    backup_path = os.path.join(backup_dir, f"media_library-{stamp}.db")
    
    conn = None
    try:
        conn = open_readable_db(db_path)
        escaped_path = backup_path.replace("'", "''")
        conn.execute(f"VACUUM INTO '{escaped_path}'")
    except Exception as e:
        print(f"[Backup] Failed to vacuum into backup file: {e}")
        return None
    finally:
        if conn:
            conn.close()

    try:
        all_backups = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith("media_library-") and f.endswith(".db")
        ])
        if len(all_backups) > BACKUP_KEEP:
            for old_file in all_backups[:-BACKUP_KEEP]:
                try:
                    os.remove(os.path.join(backup_dir, old_file))
                except OSError as err:
                    print(f"[Backup] Pruning failed for {old_file}: {err}")
    except Exception as rot_err:
        print(f"[Backup] Rotation query failed: {rot_err}")

    print(f"[Backup] Created database backup at: {backup_path}")
    return backup_path


def latest_valid_backup(db_path: str) -> Optional[str]:
    backup_dir = backup_dir_for(db_path)
    if not os.path.exists(backup_dir):
        return None
        
    try:
        backups = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith("media_library-") and f.endswith(".db")
        ], reverse=True)
    except Exception:
        return None

    for name in backups:
        candidate = os.path.join(backup_dir, name)
        conn = None
        try:
            conn = open_readable_db(candidate)
            conn.execute("SELECT count(*) FROM media_items").fetchone()
            return candidate
        except Exception:
            print(f"[Backup] Skipping unreadable backup candidate: {name}")
        finally:
            if conn:
                conn.close()
    return None


def get_database_connection(db_path: str) -> sqlite3.Connection:
    conn = None
    try:
        conn = open_library_db(db_path)
        initialize_database(conn)
        conn.execute("SELECT count(*) FROM media_items").fetchone()
        return conn
    except Exception as err:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
            conn = None

        if not is_corruption_error(err):
            raise err

        print(f"[Database] SQLite database malformed or corrupted: {err}. Attempting recovery...")

        for suffix in ["", "-wal", "-shm", "-journal"]:
            p = f"{db_path}{suffix}"
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError as unlink_err:
                print(f"[Database] Failed to delete file {p}: {unlink_err}")

        backup = latest_valid_backup(db_path)
        if backup:
            try:
                shutil.copyfile(backup, db_path)
                conn = open_library_db(db_path)
                initialize_database(conn)
                conn.execute("SELECT count(*) FROM media_items").fetchone()
                print(f"[Database] Recovered database from backup: {backup}")
                return conn
            except Exception as restore_err:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
                print(f"[Database] Restore from backup failed: {restore_err}. Recreating empty DB.")
                try:
                    if os.path.exists(db_path):
                        os.remove(db_path)
                except OSError:
                    pass

        print("[Database] Recreating empty media library database.")
        try:
            conn = open_library_db(db_path)
            initialize_database(conn)
            return conn
        except Exception as recreate_err:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            raise recreate_err


def friendly_fs_error(exception: Exception) -> str:
    if not hasattr(exception, "errno"):
        return str(exception)
        
    err_code = exception.errno
    import errno
    if err_code == errno.EROFS:
        return "This drive is mounted read-only. Remount the drive with write access and try again."
    elif err_code in [errno.EACCES, errno.EPERM]:
        return "Permission denied writing to this drive. Check mount options or directory ownership."
    elif err_code == errno.ENOSPC:
        return "The drive is full. Free up some space to build the media library."
    else:
        return str(exception)


def assert_writable(directory: str) -> None:
    probe = os.path.join(directory, f".write_test_{os.getpid()}_{int(datetime.now().timestamp())}")
    try:
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
    except Exception as err:
        friendly_msg = friendly_fs_error(err)
        raise PermissionError(friendly_msg) from err
