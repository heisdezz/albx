"""Bulk operations on media items: delete from disk + DB, move between albums."""

import os
import shutil

from core.database import get_database_connection, get_db_path, open_readable_db
from core.file_ops import move_file


def _thumb_path(drive_path: str, file_hash: str) -> str:
    return os.path.join(drive_path, "albums", "thumbs", f"{file_hash}.jpg")


def list_albums(drive_path: str) -> list[dict]:
    """Return albums as [{id, name, relative_path}], 'unknown' shown as Unsorted."""
    db_path = get_db_path(drive_path)
    if not os.path.exists(db_path):
        return []
    conn = open_readable_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, relative_path FROM albums ORDER BY name"
        ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "relative_path": r["relative_path"]}
            for r in rows
        ]
    finally:
        conn.close()


def delete_media_items(drive_path: str, ids: list[int]) -> tuple[int, list[str]]:
    """Physically delete the files (and thumbnails) then their DB rows.

    Returns (deleted_count, errors).
    """
    if not ids:
        return 0, []

    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return 0, ["Could not open the media library database."]

    errors: list[str] = []
    select_placeholders = ",".join("?" * len(ids))
    try:
        rows = conn.execute(
            f"SELECT id, current_relative_path, file_hash FROM media_items "
            f"WHERE id IN ({select_placeholders})",
            ids,
        ).fetchall()

        deleted_ids: list[int] = []
        for row in rows:
            full_path = os.path.join(drive_path, row["current_relative_path"])
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
            except OSError as e:
                errors.append(f"{os.path.basename(full_path)}: {e}")
                continue  # keep the DB row if the file couldn't be removed

            if row["file_hash"]:
                thumb = _thumb_path(drive_path, row["file_hash"])
                try:
                    if os.path.exists(thumb):
                        os.remove(thumb)
                except OSError:
                    pass  # a stale thumbnail is harmless

            deleted_ids.append(row["id"])

        # Only remove DB rows for files that were actually deleted from disk.
        if deleted_ids:
            ph = ",".join("?" * len(deleted_ids))
            conn.execute(f"DELETE FROM media_tags WHERE media_id IN ({ph})", deleted_ids)
            conn.execute(f"DELETE FROM media_items WHERE id IN ({ph})", deleted_ids)
            conn.commit()
        return len(deleted_ids), errors
    except Exception as e:
        conn.rollback()
        return 0, [str(e)]
    finally:
        conn.close()


def _unique_relative_path(drive_path: str, rel_path: str) -> str:
    """Append ' (n)' before the extension until the target path is free on disk."""
    if not os.path.exists(os.path.join(drive_path, rel_path)):
        return rel_path
    base, ext = os.path.splitext(rel_path)
    n = 1
    while True:
        candidate = f"{base} ({n}){ext}"
        if not os.path.exists(os.path.join(drive_path, candidate)):
            return candidate
        n += 1


def move_media_items(
    drive_path: str, ids: list[int], target_album_id: int
) -> tuple[int, list[str]]:
    """Move files into the target album's folder and update the DB.

    Returns (moved_count, errors).
    """
    if not ids:
        return 0, []

    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return 0, ["Could not open the media library database."]

    errors: list[str] = []
    moved = 0
    try:
        album = conn.execute(
            "SELECT relative_path FROM albums WHERE id = ?", (target_album_id,)
        ).fetchone()
        if not album:
            return 0, ["Target album not found."]
        album_rel = album["relative_path"]

        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, current_relative_path, album_id FROM media_items "
            f"WHERE id IN ({placeholders})",
            ids,
        ).fetchall()

        for row in rows:
            if row["album_id"] == target_album_id:
                continue  # already in this album

            current_rel = row["current_relative_path"]
            filename = os.path.basename(current_rel)
            target_rel = _unique_relative_path(
                drive_path, os.path.join(album_rel, filename)
            )
            src = os.path.join(drive_path, current_rel)
            dst = os.path.join(drive_path, target_rel)
            try:
                move_file(src, dst)
            except (OSError, FileNotFoundError) as e:
                errors.append(f"{filename}: {e}")
                continue

            conn.execute(
                "UPDATE media_items SET current_relative_path = ?, album_id = ? "
                "WHERE id = ?",
                (target_rel, target_album_id, row["id"]),
            )
            moved += 1

        conn.commit()
        return moved, errors
    except Exception as e:
        conn.rollback()
        return 0, [str(e)]
    finally:
        conn.close()


def create_album(drive_path: str, name: str) -> tuple[bool, str]:
    """Create a new album folder on disk and insert a record into the database.

    Returns (success, error_message).
    """
    if not name:
        return False, "Album name cannot be empty."

    # Check for invalid characters in folder name
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    if any(c in name for c in invalid_chars):
        return False, "Album name contains invalid characters."

    if name.lower() == "unknown":
        return False, "The name 'unknown' is reserved."

    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return False, "Could not open the media library database."

    try:
        cursor = conn.cursor()
        # Check if album already exists in DB
        cursor.execute("SELECT id FROM albums WHERE name = ?", (name,))
        if cursor.fetchone():
            return False, f"An album named '{name}' already exists."

        # Create directory on disk
        album_rel_path = os.path.join("albums", name)
        album_full_path = os.path.join(drive_path, album_rel_path)

        os.makedirs(album_full_path, exist_ok=True)

        # Insert into database
        cursor.execute(
            "INSERT INTO albums (name, relative_path, description) VALUES (?, ?, ?)",
            (name, album_rel_path, f"Custom album: {name}")
        )
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def delete_album(
    drive_path: str, album_id: int, delete_media: bool = False
) -> tuple[bool, str, list[str]]:
    """Delete an album.

    If delete_media is True, all media files inside are permanently deleted from disk.
    If delete_media is False, they are moved to the 'unknown' (Unsorted Media) album.

    Returns (success, error_message, file_errors).
    """
    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return False, "Could not open the media library database.", []

    try:
        cursor = conn.cursor()
        # Check if the album exists and is not 'unknown'
        cursor.execute("SELECT name, relative_path FROM albums WHERE id = ?", (album_id,))
        row = cursor.fetchone()
        if not row:
            return False, "Album not found.", []

        album_name, rel_path = row["name"], row["relative_path"]
        if album_name == "unknown":
            return False, "The default Unsorted Media album cannot be deleted.", []

        # Get unknown album ID
        cursor.execute("SELECT id FROM albums WHERE name = 'unknown'")
        unknown_row = cursor.fetchone()
        if not unknown_row:
            return False, "Default 'unknown' album not found in database.", []
        unknown_album_id = unknown_row[0]

        # Query media items in this album
        cursor.execute("SELECT id FROM media_items WHERE album_id = ?", (album_id,))
        media_ids = [r[0] for r in cursor.fetchall()]

        errors: list[str] = []
        if media_ids:
            if delete_media:
                # Permanently delete files from disk + DB.
                # Must close current conn first as delete_media_items manages its own connection.
                conn.close()
                conn = None
                deleted_count, errors = delete_media_items(drive_path, media_ids)
            else:
                # Move files to unknown album.
                # Must close current conn first as move_media_items manages its own connection.
                conn.close()
                conn = None
                moved_count, errors = move_media_items(drive_path, media_ids, unknown_album_id)

        # Re-open connection to delete the album row
        if not conn:
            conn = get_database_connection(db_path)
            cursor = conn.cursor()

        cursor.execute("DELETE FROM albums WHERE id = ?", (album_id,))
        conn.commit()

        # Remove album folder from disk
        album_full_path = os.path.join(drive_path, rel_path)
        if os.path.exists(album_full_path):
            try:
                if delete_media:
                    shutil.rmtree(album_full_path, ignore_errors=True)
                else:
                    # Clean up empty directory
                    if not os.listdir(album_full_path):
                        os.rmdir(album_full_path)
            except OSError as e:
                print(f"[delete_album] Failed to remove folder: {e}")

        return True, "", errors
    except Exception as e:
        if conn:
            conn.rollback()
        return False, str(e), []
    finally:
        if conn:
            conn.close()
