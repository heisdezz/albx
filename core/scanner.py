import hashlib
import mimetypes
import os
import sqlite3
from typing import Callable, Dict, List, Optional

from core.database import get_database_connection
from core.file_ops import move_file
from core.logger import add_log
from core.thumbnails import queue_background_thumbnail


class ScanState:
    def __init__(self, root_path: str):
        self.root_path = root_path
        self.scanning = True
        self.files_scanned = 0
        self.media_found = 0
        self.current_file = ""


active_scans: Dict[str, ScanState] = {}

VALID_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".heic",
    ".tiff",
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",
    ".flv",
    ".m4v",
    ".wmv",
}


def calculate_sha256(file_path: str, chunk_size: int = 65536) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            sha.update(data)
    return sha.hexdigest()


def is_ignored(rel_path: str, ignore_list: List[str]) -> bool:
    normalized = rel_path.replace("\\", "/").lower().strip("/")
    segments = normalized.split("/")

    for pattern in ignore_list:
        p = pattern.lower().strip().replace("\\", "/").strip("/")
        if not p:
            continue
        if "/" not in p:
            if p in segments:
                return True
        else:
            p_segments = p.split("/")
            p_len = len(p_segments)
            for i in range(len(segments) - p_len + 1):
                if segments[i : i + p_len] == p_segments:
                    return True
    return False


def walk_directory(
    drive_path: str,
    start_dir: str,
    db_path: str,
    scan_state: ScanState,
    ignore_list: List[str],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    add_log("info", f"Starting media scanner on root path: {start_dir}", start_dir)

    albums_dir = os.path.join(drive_path, "albums")
    unknown_dir = os.path.join(albums_dir, "unknown")
    os.makedirs(unknown_dir, exist_ok=True)
    os.makedirs(os.path.join(albums_dir, "thumbs"), exist_ok=True)

    conn = get_database_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM albums WHERE name = 'unknown'")
    row = cursor.fetchone()
    if row:
        unknown_album_id = row[0]
    else:
        cursor.execute(
            "INSERT INTO albums (name, relative_path, description) VALUES ('unknown', 'albums/unknown', 'Default album for unsorted media')"
        )
        conn.commit()
        unknown_album_id = cursor.lastrowid

    album_cache: Dict[str, tuple[int, str]] = {
        "": (unknown_album_id, unknown_dir),
        ".": (unknown_album_id, unknown_dir),
        "unknown": (unknown_album_id, unknown_dir),
    }

    cursor.execute("SELECT id, name, relative_path FROM albums")
    for r in cursor.fetchall():
        alb_id, alb_name, alb_rel = r[0], r[1], r[2]
        full_dir = os.path.join(drive_path, alb_rel)
        album_cache[alb_name] = (alb_id, full_dir)
        album_cache[alb_rel] = (alb_id, full_dir)
        if alb_rel.startswith("albums/"):
            sub = alb_rel[len("albums/") :].strip("/")
            if sub:
                album_cache[sub] = (alb_id, full_dir)

    def get_or_create_album(subfolder_path: str) -> tuple[int, str]:
        clean_sub = subfolder_path.replace("\\", "/").strip("/")
        if not clean_sub or clean_sub.lower() in (".", "unknown"):
            return unknown_album_id, unknown_dir

        if clean_sub.startswith("albums/"):
            clean_sub = clean_sub[len("albums/") :].strip("/")
            if not clean_sub or clean_sub.lower() == "unknown":
                return unknown_album_id, unknown_dir

        if clean_sub in album_cache:
            return album_cache[clean_sub]

        album_name = clean_sub
        album_rel = f"albums/{clean_sub}"
        target_dir = os.path.join(drive_path, "albums", clean_sub)
        os.makedirs(target_dir, exist_ok=True)

        cursor.execute(
            "SELECT id FROM albums WHERE name = ? OR relative_path = ?",
            (album_name, album_rel),
        )
        existing = cursor.fetchone()
        if existing:
            alb_id = existing[0]
        else:
            cursor.execute(
                "INSERT INTO albums (name, relative_path, description) VALUES (?, ?, ?)",
                (album_name, album_rel, f"Album: {album_name}"),
            )
            conn.commit()
            alb_id = cursor.lastrowid
            add_log("info", f"Created album '{album_name}'", album_rel)

        album_cache[clean_sub] = (alb_id, target_dir)
        album_cache[album_name] = (alb_id, target_dir)
        album_cache[album_rel] = (alb_id, target_dir)
        return alb_id, target_dir

    stack = [start_dir]

    while stack and scan_state.scanning:
        current_dir = stack.pop()

        try:
            entries = os.scandir(current_dir)
        except OSError as err:
            add_log(
                "warn", f"Could not read directory {current_dir}: {err}", current_dir
            )
            continue

        for entry in entries:
            if not scan_state.scanning:
                break

            rel_entry_path = os.path.relpath(entry.path, drive_path).replace("\\", "/")

            if is_ignored(rel_entry_path, ignore_list):
                continue

            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
            elif entry.is_file(follow_symlinks=False):
                scan_state.files_scanned += 1
                scan_state.current_file = rel_entry_path

                if progress_callback:
                    progress_callback(
                        scan_state.files_scanned,
                        scan_state.media_found,
                        scan_state.current_file,
                    )

                ext = os.path.splitext(entry.name)[1].lower()
                if ext not in VALID_EXTENSIONS:
                    continue

                file_hash = calculate_sha256(entry.path)

                cursor.execute(
                    "SELECT id, current_relative_path FROM media_items WHERE file_hash = ?",
                    (file_hash,),
                )
                existing = cursor.fetchone()

                if existing:
                    add_log(
                        "info",
                        f"Skipping existing media file with hash: {file_hash[:8]}",
                        rel_entry_path,
                    )
                    continue

                rel_dir = (
                    os.path.relpath(current_dir, drive_path)
                    .replace("\\", "/")
                    .strip("/")
                )
                album_id, target_album_dir = get_or_create_album(rel_dir)

                filename = entry.name
                base_name, ext_name = os.path.splitext(filename)
                target_dest_path = os.path.join(target_album_dir, filename)

                if os.path.abspath(entry.path) != os.path.abspath(
                    target_dest_path
                ) and os.path.exists(target_dest_path):
                    counter = 1
                    while os.path.exists(
                        os.path.join(
                            target_album_dir, f"{base_name}_{counter}{ext_name}"
                        )
                    ):
                        counter += 1
                    target_dest_path = os.path.join(
                        target_album_dir, f"{base_name}_{counter}{ext_name}"
                    )

                dest_relative_path = os.path.relpath(
                    target_dest_path, drive_path
                ).replace("\\", "/")
                file_size = entry.stat().st_size
                mime_type = (
                    mimetypes.guess_type(entry.path)[0]
                    or f"application/{ext.lstrip('.')}"
                )

                if os.path.abspath(entry.path) != os.path.abspath(target_dest_path):
                    move_file(entry.path, target_dest_path)

                cursor.execute(
                    """
                    INSERT INTO media_items (
                        file_hash, original_relative_path, current_relative_path,
                        file_size, mime_type, album_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_hash,
                        rel_entry_path,
                        dest_relative_path,
                        file_size,
                        mime_type,
                        album_id,
                    ),
                )
                conn.commit()

                scan_state.media_found += 1
                add_log(
                    "info",
                    f"Indexed new media item #{scan_state.media_found}",
                    dest_relative_path,
                )

                thumb_target = os.path.join(albums_dir, "thumbs", f"{file_hash}.jpg")
                queue_background_thumbnail(target_dest_path, thumb_target)

    # Clean up empty source directories left behind by moved files
    if scan_state.scanning and os.path.exists(start_dir):
        for root, dirs, files in os.walk(start_dir, topdown=False):
            if root == drive_path or root == start_dir:
                continue
            rel_root = os.path.relpath(root, drive_path).replace("\\", "/")
            if is_ignored(rel_root, ignore_list):
                continue
            if rel_root == "albums" or rel_root.startswith("albums/"):
                continue
            try:
                os.rmdir(root)
            except OSError:
                pass

    conn.close()
    add_log(
        "info",
        f"Scan finished. Total checked: {scan_state.files_scanned}, cataloged: {scan_state.media_found}",
    )
