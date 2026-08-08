import os
import hashlib
import sqlite3
import mimetypes
from typing import List, Dict, Callable, Optional
from core.database import get_database_connection
from core.file_ops import move_file
from core.thumbnails import queue_background_thumbnail
from core.logger import add_log

class ScanState:
    def __init__(self, root_path: str):
        self.root_path = root_path
        self.scanning = True
        self.files_scanned = 0
        self.media_found = 0
        self.current_file = ""

active_scans: Dict[str, ScanState] = {}

VALID_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff",
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".wmv"
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
    normalized = rel_path.replace("\\", "/").lower()
    segments = normalized.split("/")
    
    for pattern in ignore_list:
        p = pattern.lower().strip()
        if not p:
            continue
        if p in segments or any(p in seg for seg in segments):
            return True
    return False

def walk_directory(
    drive_path: str,
    start_dir: str,
    db_path: str,
    scan_state: ScanState,
    ignore_list: List[str],
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> None:
    add_log("info", f"Starting media scanner on root path: {start_dir}", start_dir)
    
    albums_dir = os.path.join(drive_path, "albums")
    unknown_dir = os.path.join(albums_dir, "unknown")
    os.makedirs(unknown_dir, exist_ok=True)
    
    conn = get_database_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM albums WHERE name = 'unknown'")
    unknown_album_id = cursor.fetchone()[0]
    
    stack = [start_dir]
    
    while stack and scan_state.scanning:
        current_dir = stack.pop()
        
        try:
            entries = os.scandir(current_dir)
        except OSError as err:
            add_log("warn", f"Could not read directory {current_dir}: {err}", current_dir)
            continue
            
        for entry in entries:
            if not scan_state.scanning:
                break
                
            rel_entry_path = os.path.relpath(entry.path, drive_path)
            
            if is_ignored(rel_entry_path, ignore_list):
                continue
                
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
            elif entry.is_file(follow_symlinks=False):
                scan_state.files_scanned += 1
                scan_state.current_file = rel_entry_path
                
                if progress_callback:
                    progress_callback(scan_state.files_scanned, scan_state.media_found, scan_state.current_file)
                    
                ext = os.path.splitext(entry.name)[1].lower()
                if ext not in VALID_EXTENSIONS:
                    continue
                    
                file_hash = calculate_sha256(entry.path)
                
                cursor.execute("SELECT id, current_relative_path FROM media_items WHERE file_hash = ?", (file_hash,))
                existing = cursor.fetchone()
                
                if existing:
                    add_log("info", f"Skipping existing media file with hash: {file_hash[:8]}", rel_entry_path)
                    continue
                    
                filename = entry.name
                base_name, ext_name = os.path.splitext(filename)
                target_dest_path = os.path.join(unknown_dir, filename)
                
                if os.path.exists(target_dest_path):
                    counter = 1
                    while os.path.exists(os.path.join(unknown_dir, f"{base_name}_{counter}{ext_name}")):
                        counter += 1
                    target_dest_path = os.path.join(unknown_dir, f"{base_name}_{counter}{ext_name}")
                    
                dest_relative_path = os.path.relpath(target_dest_path, drive_path)
                file_size = entry.stat().st_size
                mime_type = mimetypes.guess_type(entry.path)[0] or f"application/{ext.lstrip('.')}"
                
                move_file(entry.path, target_dest_path)
                
                cursor.execute(
                    """
                    INSERT INTO media_items (
                        file_hash, original_relative_path, current_relative_path,
                        file_size, mime_type, album_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (file_hash, rel_entry_path, dest_relative_path, file_size, mime_type, unknown_album_id)
                )
                conn.commit()
                
                scan_state.media_found += 1
                add_log("info", f"Indexed new media item #{scan_state.media_found}", dest_relative_path)
                
                thumb_target = os.path.join(albums_dir, "thumbs", f"{file_hash}.jpg")
                queue_background_thumbnail(target_dest_path, thumb_target)
                
    conn.close()
    add_log("info", f"Scan finished. Total checked: {scan_state.files_scanned}, cataloged: {scan_state.media_found}")
