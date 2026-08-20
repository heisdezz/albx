import os
import re
import json
import socket
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from core.database import get_db_path, open_readable_db, create_backup
from core.thumbnails import get_or_generate_thumbnail

def get_local_ip() -> str:
    """Discover the primary LAN/Wi-Fi IP address of the local machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

def format_bytes(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    import math
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread for concurrent access."""
    daemon_threads = True
    allow_reuse_address = True

MEDIA_ROUTE_RE = re.compile(r"^/(?:api/)?media/(\d+)$")
THUMB_ROUTE_RE = re.compile(r"^/(?:api/)?thumbnail/(\d+)$")

class SyncRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler providing endpoints for mobile sync, media streaming & thumbnails."""
    
    server: "ThreadedSyncHTTPServer"  # Type annotation for parent server

    def log_message(self, format: str, *args: Any) -> None:
        """Custom minimal logging to avoid cluttering stderr."""
        print(f"[MobileSyncServer] {self.address_string()} - {format % args}")

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Accept-Ranges, Content-Length")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_HEAD(self) -> None:
        self._dispatch(is_head=True)

    def do_GET(self) -> None:
        self._dispatch(is_head=False)

    def _dispatch(self, is_head: bool = False) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if not path:
            path = "/"

        media_match = MEDIA_ROUTE_RE.match(path)
        if media_match:
            item_id = int(media_match.group(1))
            self._handle_media_stream(item_id, is_head=is_head)
            return

        thumb_match = THUMB_ROUTE_RE.match(path)
        if thumb_match:
            item_id = int(thumb_match.group(1))
            self._handle_thumbnail_stream(item_id, is_head=is_head)
            return

        if path in ("/", "/api/info"):
            self._handle_info(is_head=is_head)
        elif path in ("/download/db", "/api/db/download"):
            self._handle_db_download(is_head=is_head)
        elif path in ("/api/db/stats"):
            self._handle_info(is_head=is_head)
        else:
            self._send_json({"error": "Not Found", "code": 404}, status=404, is_head=is_head)

    def _send_json(self, data: Dict[str, Any], status: int = 200, is_head: bool = False) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not is_head:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _handle_info(self, is_head: bool = False) -> None:
        drive_path = getattr(self.server, "drive_path", "")
        if not drive_path or not os.path.exists(drive_path):
            self._send_json({
                "status": "online",
                "server": "Media Library Mobile Sync Server",
                "error": "No active drive path selected",
                "download_url": None
            }, is_head=is_head)
            return

        db_path = get_db_path(drive_path)
        db_exists = os.path.exists(db_path)
        db_size = os.path.getsize(db_path) if db_exists else 0
        
        stats = {
            "total_items": 0,
            "images": 0,
            "videos": 0,
            "albums": 0,
            "tags": 0,
            "db_size_bytes": db_size,
            "db_size_formatted": format_bytes(db_size),
            "db_exists": db_exists
        }

        if db_exists:
            try:
                conn = open_readable_db(db_path)
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) FROM media_items")
                stats["total_items"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM media_items WHERE mime_type LIKE 'image/%'")
                stats["images"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM media_items WHERE mime_type LIKE 'video/%'")
                stats["videos"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM albums")
                stats["albums"] = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM tags")
                stats["tags"] = cursor.fetchone()[0]

                conn.close()
            except Exception as e:
                print(f"[MobileSyncServer] Error querying DB stats: {e}")

        host_ip = getattr(self.server, "host_ip", get_local_ip())
        port = getattr(self.server, "port", 8080)
        download_url = f"http://{host_ip}:{port}/download/db"

        response = {
            "status": "online",
            "server": "Media Library Mobile Sync Server",
            "drive_name": os.path.basename(os.path.normpath(drive_path)),
            "drive_path": drive_path,
            "download_url": download_url,
            "server_ip": host_ip,
            "server_port": port,
            "stats": stats
        }
        self._send_json(response, is_head=is_head)

    def _handle_db_download(self, is_head: bool = False) -> None:
        drive_path = getattr(self.server, "drive_path", "")
        if not drive_path:
            self._send_json({"error": "No active drive path selected", "code": 400}, status=400, is_head=is_head)
            return

        db_path = get_db_path(drive_path)
        if not os.path.exists(db_path):
            self._send_json({"error": "Database file does not exist yet. Please scan first.", "code": 404}, status=404, is_head=is_head)
            return

        # Create an exFAT-safe vacuumed snapshot backup for download
        snapshot_path = create_backup(db_path)
        download_target = snapshot_path if (snapshot_path and os.path.exists(snapshot_path)) else db_path

        try:
            file_size = os.path.getsize(download_target)
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/x-sqlite3")
            self.send_header("Content-Disposition", 'attachment; filename="media_library.db"')
            self.send_header("Content-Length", str(file_size))
            self.end_headers()

            if not is_head:
                with open(download_target, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
                print(f"[MobileSyncServer] Successfully streamed database snapshot ({format_bytes(file_size)}) to {self.address_string()}")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print(f"[MobileSyncServer] Download transfer interrupted: {e}")

    def _handle_media_stream(self, item_id: int, is_head: bool = False) -> None:
        """Stream a media item by ID with full HTTP Range request seeking support."""
        drive_path = getattr(self.server, "drive_path", "")
        if not drive_path:
            self._send_json({"error": "No active drive path selected", "code": 400}, status=400, is_head=is_head)
            return

        db_path = get_db_path(drive_path)
        if not os.path.exists(db_path):
            self._send_json({"error": "Database not found", "code": 404}, status=404, is_head=is_head)
            return

        conn = None
        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT current_relative_path, mime_type, file_size FROM media_items WHERE id = ?",
                (item_id,)
            )
            row = cursor.fetchone()
        except Exception as e:
            self._send_json({"error": f"Database query error: {str(e)}", "code": 500}, status=500, is_head=is_head)
            return
        finally:
            if conn:
                conn.close()

        if not row:
            self._send_json({"error": "Media item not found", "code": 404}, status=404, is_head=is_head)
            return

        rel_path = row["current_relative_path"]
        mime_type = row["mime_type"] or "application/octet-stream"

        # Security check: ensure resolved path is within drive_path
        target_abs = os.path.realpath(os.path.join(drive_path, rel_path))
        real_drive = os.path.realpath(drive_path)
        if not (target_abs == real_drive or target_abs.startswith(real_drive + os.sep)):
            self._send_json({"error": "Access forbidden: path traversal detected", "code": 403}, status=403, is_head=is_head)
            return

        if not os.path.exists(target_abs) or not os.path.isfile(target_abs):
            self._send_json({"error": "Media file not found on disk", "code": 404}, status=404, is_head=is_head)
            return

        try:
            total_size = os.path.getsize(target_abs)
        except OSError:
            self._send_json({"error": "Cannot read media file", "code": 500}, status=500, is_head=is_head)
            return

        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            # Parse Range: bytes=START-END
            range_spec = range_header[6:].strip()
            try:
                if "-" in range_spec:
                    start_str, end_str = range_spec.split("-", 1)
                    if start_str and end_str:
                        start = int(start_str)
                        end = min(int(end_str), total_size - 1)
                    elif start_str:
                        start = int(start_str)
                        end = total_size - 1
                    elif end_str:
                        suffix_len = int(end_str)
                        start = max(0, total_size - suffix_len)
                        end = total_size - 1
                    else:
                        start = 0
                        end = total_size - 1
                else:
                    start = int(range_spec)
                    end = total_size - 1
            except ValueError:
                start, end = 0, total_size - 1

            if start < 0 or start >= total_size or end < start:
                self.send_response(416)
                self._send_cors_headers()
                self.send_header("Content-Range", f"bytes */{total_size}")
                self.end_headers()
                return

            content_length = end - start + 1
            self.send_response(206)
            self._send_cors_headers()
            self.send_header("Content-Type", mime_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
            self.send_header("Content-Length", str(content_length))
            self.end_headers()

            if not is_head:
                try:
                    with open(target_abs, "rb") as f:
                        f.seek(start)
                        remaining = content_length
                        while remaining > 0:
                            chunk_size = min(65536, remaining)
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as e:
                    print(f"[MobileSyncServer] Range stream error for item {item_id}: {e}")
        else:
            # Standard 200 OK stream
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", mime_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(total_size))
            self.end_headers()

            if not is_head:
                try:
                    with open(target_abs, "rb") as f:
                        while chunk := f.read(65536):
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as e:
                    print(f"[MobileSyncServer] Media stream error for item {item_id}: {e}")

    def _handle_thumbnail_stream(self, item_id: int, is_head: bool = False) -> None:
        """Serve or generate a thumbnail JPEG for the given media item ID."""
        drive_path = getattr(self.server, "drive_path", "")
        if not drive_path:
            self._send_json({"error": "No active drive path selected", "code": 400}, status=400, is_head=is_head)
            return

        db_path = get_db_path(drive_path)
        if not os.path.exists(db_path):
            self._send_json({"error": "Database not found", "code": 404}, status=404, is_head=is_head)
            return

        conn = None
        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT current_relative_path, mime_type, file_hash FROM media_items WHERE id = ?",
                (item_id,)
            )
            row = cursor.fetchone()
        except Exception as e:
            self._send_json({"error": f"Database query error: {str(e)}", "code": 500}, status=500, is_head=is_head)
            return
        finally:
            if conn:
                conn.close()

        if not row:
            self._send_json({"error": "Media item not found", "code": 404}, status=404, is_head=is_head)
            return

        rel_path = row["current_relative_path"]
        file_hash = row["file_hash"]
        abs_media_path = os.path.realpath(os.path.join(drive_path, rel_path))
        real_drive = os.path.realpath(drive_path)
        if not (abs_media_path == real_drive or abs_media_path.startswith(real_drive + os.sep)):
            self._send_json({"error": "Access forbidden: path traversal detected", "code": 403}, status=403, is_head=is_head)
            return

        thumb_path = os.path.join(drive_path, "albums", "thumbs", f"{file_hash}.jpg")

        # Generate thumbnail synchronously if missing
        if not os.path.exists(thumb_path):
            if not os.path.exists(abs_media_path):
                self._send_json({"error": "Media source file missing on disk", "code": 404}, status=404, is_head=is_head)
                return
            success = get_or_generate_thumbnail(abs_media_path, thumb_path)
            if not success or not os.path.exists(thumb_path):
                self._send_json({"error": "Thumbnail generation failed", "code": 500}, status=500, is_head=is_head)
                return

        try:
            thumb_size = os.path.getsize(thumb_path)
        except OSError:
            self._send_json({"error": "Cannot read thumbnail", "code": 500}, status=500, is_head=is_head)
            return

        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(thumb_size))
        self.end_headers()

        if not is_head:
            try:
                with open(thumb_path, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                print(f"[MobileSyncServer] Thumbnail stream error for item {item_id}: {e}")

class ThreadedSyncHTTPServer(ThreadedHTTPServer):
    drive_path: str = ""
    host_ip: str = "0.0.0.0"
    port: int = 8080

class SyncServerManager:
    _instance: Optional["SyncServerManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.server: Optional[ThreadedSyncHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.drive_path: str = ""
        self.port: int = 8080
        self.host_ip: str = get_local_ip()
        self.is_running: bool = False
        self.started_at: Optional[str] = None

    @classmethod
    def get_instance(cls) -> "SyncServerManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = SyncServerManager()
            return cls._instance

    def start(self, drive_path: str, port: int = 8080) -> Dict[str, Any]:
        with self._lock:
            if self.is_running:
                if self.port == port and self.drive_path == drive_path:
                    return self.get_status()
                # Stop existing server before re-binding
                self._stop_unlocked()

            self.drive_path = drive_path
            self.port = port
            self.host_ip = get_local_ip()

            try:
                self.server = ThreadedSyncHTTPServer(("0.0.0.0", port), SyncRequestHandler)
                self.server.drive_path = drive_path
                self.server.host_ip = self.host_ip
                self.server.port = port

                self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
                self.server_thread.start()

                self.is_running = True
                self.started_at = datetime.now().isoformat()
                print(f"[MobileSyncServer] Started on http://{self.host_ip}:{port}/ for drive '{drive_path}'")
                return self.get_status()
            except Exception as e:
                self.is_running = False
                self.server = None
                print(f"[MobileSyncServer] Failed to start server on port {port}: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "is_running": False
                }

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            return self._stop_unlocked()

    def _stop_unlocked(self) -> Dict[str, Any]:
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                print(f"[MobileSyncServer] Exception during server shutdown: {e}")
        self.server = None
        self.server_thread = None
        self.is_running = False
        self.started_at = None
        print("[MobileSyncServer] Server stopped successfully.")
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        url = f"http://{self.host_ip}:{self.port}/download/db" if self.is_running else None
        info_url = f"http://{self.host_ip}:{self.port}/" if self.is_running else None
        return {
            "success": True,
            "is_running": self.is_running,
            "ip": self.host_ip,
            "port": self.port,
            "drive_path": self.drive_path,
            "download_url": url,
            "info_url": info_url,
            "started_at": self.started_at
        }

# Module-level convenience functions
def get_sync_server_manager() -> SyncServerManager:
    return SyncServerManager.get_instance()

def start_mobile_sync_server(drive_path: str, port: int = 8080) -> Dict[str, Any]:
    return get_sync_server_manager().start(drive_path, port)

def stop_mobile_sync_server() -> Dict[str, Any]:
    return get_sync_server_manager().stop()

def get_mobile_sync_status() -> Dict[str, Any]:
    return get_sync_server_manager().get_status()
