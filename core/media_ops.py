"""Bulk operations on media items: delete from disk + DB, move between albums."""

import os
import shutil
import sqlite3

from core.database import get_database_connection, get_db_path
from core.file_ops import move_file


def delete_media_items(drive_path: str, ids: list[int]) -> tuple[int, list[str]]:
    """Delete media files from disk and remove their records from the DB.

    Uses a transaction: if the DB update fails, rolled back. Returns (deleted_count,
    errors).
    """
    if not ids:
        return 0, []

    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return 0, ["Could not open the media library database."]

    errors = []
    deleted = 0

    try:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, current_relative_path, file_hash FROM media_items "
            f"WHERE id IN ({placeholders})",
            ids,
        ).fetchall()

        for row in rows:
            # Delete the media file itself
            full_path = os.path.join(drive_path, row["current_relative_path"])
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except OSError as e:
                    errors.append(f"{row['current_relative_path']}: {e}")

            # Delete the thumbnail if it exists
            thumb_path = os.path.join(
                drive_path, "albums", "thumbs", f"{row['file_hash']}.jpg"
            )
            if os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except OSError:
                    pass

        # Delete database records
        conn.execute(
            f"DELETE FROM media_items WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()
        deleted = len(rows)
        return deleted, errors
    except Exception as e:
        conn.rollback()
        return 0, [str(e)]
    finally:
        conn.close()


def list_albums(drive_path: str) -> list[dict]:
    """Return all albums for the drive as a list of dicts with id, name, relative_path."""
    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, relative_path FROM albums ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _unique_relative_path(drive_path: str, target_rel: str) -> str:
    """If target_rel already exists on disk, append _1, _2, etc. before the extension."""
    full = os.path.join(drive_path, target_rel)
    if not os.path.exists(full):
        return target_rel

    base, ext = os.path.splitext(target_rel)
    counter = 1
    while os.path.exists(os.path.join(drive_path, f"{base}_{counter}{ext}")):
        counter += 1
    return f"{base}_{counter}{ext}"


def move_media_items(
    drive_path: str, ids: list[int], target_album_id: int
) -> tuple[int, list[str]]:
    """Move media files to a new album directory on disk and update the DB.

    Returns (moved_count, errors).
    """
    if not ids:
        return 0, []

    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return 0, ["Could not open the media library database."]

    errors = []
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


def _validate_album_name(name: str) -> tuple[bool, str]:
    """Validate an album folder name. Returns (ok, error_message)."""
    if not name or not name.strip():
        return False, "Album name cannot be empty."

    cleaned = name.strip().replace("\\", "/")
    if cleaned.startswith("/") or cleaned.endswith("/"):
        return False, "Album name cannot start or end with a slash."

    segments = cleaned.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        return False, "Album name cannot contain empty or relative path segments."

    invalid_chars = [":", "*", "?", '"', "<", ">", "|"]
    if any(c in cleaned for c in invalid_chars):
        return False, "Album name contains invalid characters."

    if cleaned.lower() == "unknown":
        return False, "The name 'unknown' is reserved."

    return True, ""


def create_album(drive_path: str, name: str, description: str = "") -> tuple[bool, str]:
    """Create a new album folder on disk and insert a record into the database.

    Returns (success, error_message).
    """
    ok, err = _validate_album_name(name)
    if not ok:
        return False, err

    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return False, "Could not open the media library database."

    try:
        cursor = conn.cursor()
        cleaned_name = name.strip().replace("\\", "/")
        album_rel_path = os.path.join("albums", cleaned_name).replace("\\", "/")

        # Check if album already exists in DB
        cursor.execute(
            "SELECT id FROM albums WHERE name = ? OR relative_path = ?",
            (cleaned_name, album_rel_path),
        )
        if cursor.fetchone():
            return False, f"An album named '{cleaned_name}' already exists."

        # Create directory on disk
        album_full_path = os.path.join(drive_path, album_rel_path)
        os.makedirs(album_full_path, exist_ok=True)

        # Insert into database
        desc = description if description else f"Custom album: {cleaned_name}"
        cursor.execute(
            "INSERT INTO albums (name, relative_path, description) VALUES (?, ?, ?)",
            (cleaned_name, album_rel_path, desc),
        )
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def rename_album(drive_path: str, album_id: int, new_name: str) -> tuple[bool, str]:
    """Rename an album folder on disk and rewrite the affected media paths.

    Returns (success, error_message).
    """
    new_name = new_name.strip()
    ok, err = _validate_album_name(new_name)
    if not ok:
        return False, err

    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return False, "Could not open the media library database."

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, relative_path FROM albums WHERE id = ?", (album_id,)
        )
        row = cursor.fetchone()
        if not row:
            return False, "Album not found."
        old_name, old_rel = row["name"], row["relative_path"]

        cleaned_new = new_name.replace("\\", "/")
        new_rel = os.path.join("albums", cleaned_new).replace("\\", "/")

        if old_name == cleaned_new:
            return True, ""

        cursor.execute(
            "SELECT id FROM albums WHERE name = ? OR relative_path = ?",
            (cleaned_new, new_rel),
        )
        if cursor.fetchone():
            return False, f"An album named '{cleaned_new}' already exists."

        old_full = os.path.join(drive_path, old_rel)
        new_full = os.path.join(drive_path, new_rel)

        if os.path.exists(old_full):
            if os.path.exists(new_full):
                return (
                    False,
                    f"A folder named '{cleaned_new}' already exists on the drive.",
                )
            os.makedirs(os.path.dirname(new_full), exist_ok=True)
            os.rename(old_full, new_full)

        # Rewrite media paths that live under the old album folder.
        old_prefix = old_rel.rstrip("/\\") + "/"
        for mrow in cursor.execute(
            "SELECT id, current_relative_path FROM media_items WHERE album_id = ?",
            (album_id,),
        ).fetchall():
            rel = mrow["current_relative_path"].replace("\\", "/")
            if rel.startswith(old_prefix):
                sub = rel[len(old_prefix) :]
                new_item_rel = f"{new_rel}/{sub}".replace("\\", "/")
                cursor.execute(
                    "UPDATE media_items SET current_relative_path = ? WHERE id = ?",
                    (new_item_rel, mrow["id"]),
                )

        cursor.execute(
            "UPDATE albums SET name = ?, relative_path = ? WHERE id = ?",
            (cleaned_new, new_rel, album_id),
        )
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def merge_albums(
    drive_path: str, source_album_id: int, target_album_id: int
) -> tuple[bool, str, list[str]]:
    """Move all media from the source album into the target album, then remove it.

    The source album folder is removed once its media have been moved out.
    Returns (success, error_message, file_errors).
    """
    if source_album_id == target_album_id:
        return False, "Cannot merge an album into itself.", []

    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return False, "Could not open the media library database.", []

    try:
        cursor = conn.cursor()

        src = cursor.execute(
            "SELECT name, relative_path FROM albums WHERE id = ?", (source_album_id,)
        ).fetchone()
        tgt = cursor.execute(
            "SELECT name, relative_path FROM albums WHERE id = ?", (target_album_id,)
        ).fetchone()

        if not src or not tgt:
            return False, "One of the albums was not found.", []

        src_name, src_rel = src["name"], src["relative_path"]
        tgt_rel = tgt["relative_path"]

        if src_name == "unknown":
            return False, "The default 'Unsorted Media' album cannot be merged.", []

        # Find all media in source album
        media_rows = cursor.execute(
            "SELECT id, current_relative_path FROM media_items WHERE album_id = ?",
            (source_album_id,),
        ).fetchall()

        file_errors = []
        for m in media_rows:
            filename = os.path.basename(m["current_relative_path"])
            target_rel = _unique_relative_path(
                drive_path, os.path.join(tgt_rel, filename)
            )
            src_file = os.path.join(drive_path, m["current_relative_path"])
            dst_file = os.path.join(drive_path, target_rel)

            try:
                move_file(src_file, dst_file)
            except (OSError, FileNotFoundError) as e:
                file_errors.append(f"{filename}: {e}")
                continue

            cursor.execute(
                "UPDATE media_items SET current_relative_path = ?, album_id = ? "
                "WHERE id = ?",
                (target_rel, target_album_id, m["id"]),
            )

        # Remove source album record
        cursor.execute("DELETE FROM albums WHERE id = ?", (source_album_id,))
        conn.commit()

        # Remove empty source album folder from disk if empty
        src_full = os.path.join(drive_path, src_rel)
        if os.path.exists(src_full):
            try:
                os.rmdir(src_full)
            except OSError:
                # Folder still holds stray (uncatalogued) files: leave it be.
                pass

        return True, "", file_errors
    except Exception as e:
        conn.rollback()
        return False, str(e), []
    finally:
        conn.close()


def delete_album(
    drive_path: str, album_id: int, delete_media: bool
) -> tuple[bool, str]:
    """Delete an album.

    If delete_media=True, all media items and files inside the album are deleted.
    If delete_media=False, media items are moved to the 'unknown' album and kept on disk.
    The default 'unknown' album cannot be deleted.
    Returns (success, error_message).
    """
    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return False, "Could not open the media library database."

    try:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT name, relative_path FROM albums WHERE id = ?", (album_id,)
        ).fetchone()
        if not row:
            return False, "Album not found."

        name, rel_path = row["name"], row["relative_path"]
        if name == "unknown":
            return False, "The default 'Unsorted Media' album cannot be deleted."

        media_rows = cursor.execute(
            "SELECT id, current_relative_path, file_hash FROM media_items WHERE album_id = ?",
            (album_id,),
        ).fetchall()
        media_ids = [m["id"] for m in media_rows]

        if delete_media:
            # Delete media files and thumbnails from disk
            for m in media_rows:
                full_path = os.path.join(drive_path, m["current_relative_path"])
                if os.path.exists(full_path):
                    try:
                        os.remove(full_path)
                    except OSError:
                        pass
                thumb_path = os.path.join(
                    drive_path, "albums", "thumbs", f"{m['file_hash']}.jpg"
                )
                if os.path.exists(thumb_path):
                    try:
                        os.remove(thumb_path)
                    except OSError:
                        pass

            if media_ids:
                placeholders = ",".join("?" * len(media_ids))
                cursor.execute(
                    f"DELETE FROM media_items WHERE id IN ({placeholders})",
                    media_ids,
                )
        else:
            # Reassign media items to 'unknown' album, keep files where they are
            unknown_row = cursor.execute(
                "SELECT id FROM albums WHERE name = 'unknown'"
            ).fetchone()
            unknown_id = unknown_row["id"] if unknown_row else None
            if unknown_id and media_ids:
                placeholders = ",".join("?" * len(media_ids))
                cursor.execute(
                    f"UPDATE media_items SET album_id = ? WHERE id IN ({placeholders})",
                    [unknown_id] + media_ids,
                )

        # Delete album record
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

        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def validate_album_files(
    drive_path: str, album_id: int | None = None
) -> tuple[int, int, list[str]]:
    """Verify that all media_items in an album (or all albums if album_id is None)

    actually exist on disk. Missing files have their DB records removed.
    Returns (total_checked, missing_removed, errors).
    """
    db_path = get_db_path(drive_path)
    conn = get_database_connection(db_path)
    if not conn:
        return 0, 0, ["Could not open the media library database."]

    try:
        cursor = conn.cursor()
        if album_id is not None:
            rows = cursor.execute(
                "SELECT id, current_relative_path FROM media_items WHERE album_id = ?",
                (album_id,),
            ).fetchall()
        else:
            rows = cursor.execute(
                "SELECT id, current_relative_path FROM media_items"
            ).fetchall()

        total_checked = len(rows)
        missing_ids = []
        errors = []

        for row in rows:
            full_path = os.path.join(drive_path, row["current_relative_path"])
            if not os.path.exists(full_path):
                missing_ids.append(row["id"])

        if missing_ids:
            placeholders = ",".join("?" * len(missing_ids))
            cursor.execute(
                f"DELETE FROM media_items WHERE id IN ({placeholders})",
                missing_ids,
            )
            conn.commit()

        return total_checked, len(missing_ids), errors
    except Exception as e:
        conn.rollback()
        return 0, 0, [str(e)]
    finally:
        conn.close()
