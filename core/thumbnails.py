import os
import signal
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Set
from PIL import Image
from core.logger import add_log

in_flight_pids: Set[int] = set()
pids_lock = threading.Lock()

thumbnails_paused = False
pause_lock = threading.Lock()

executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ThumbnailWorker")

def set_thumbnails_paused(paused: bool) -> None:
    global thumbnails_paused
    with pause_lock:
        thumbnails_paused = paused
        
    action_sig = signal.SIGSTOP if paused else signal.SIGCONT
    action_str = "PAUSING (SIGSTOP)" if paused else "RESUMING (SIGCONT)"
    
    with pids_lock:
        for pid in list(in_flight_pids):
            try:
                os.kill(pid, action_sig)
                add_log("info", f"Sent {action_str} to ffmpeg thumbnail process", f"PID: {pid}")
            except OSError as err:
                print(f"[Thumbnails] Signal {action_sig} failed for PID {pid}: {err}")


def generate_image_thumbnail(src_path: str, thumb_path: str, max_dim: int = 400) -> bool:
    try:
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
        with Image.open(src_path) as img:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(thumb_path, "JPEG", quality=85)
        return True
    except Exception as err:
        add_log("warn", f"PIL image thumbnail generation failed: {err}", src_path)
        return False


def generate_video_thumbnail(src_path: str, thumb_path: str) -> bool:
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", "00:00:01",
        "-i", src_path,
        "-vframes", "1",
        "-vf", "scale=400:-1",
        thumb_path
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        
        with pids_lock:
            in_flight_pids.add(proc.pid)
            
        with pause_lock:
            if thumbnails_paused:
                try:
                    os.kill(proc.pid, signal.SIGSTOP)
                except OSError:
                    pass

        code = proc.wait()

        with pids_lock:
            in_flight_pids.discard(proc.pid)

        return code == 0 and os.path.exists(thumb_path)
    except Exception as err:
        add_log("warn", f"FFmpeg video thumbnail extraction failed: {err}", src_path)
        return False


def get_or_generate_thumbnail(full_media_path: str, thumb_path: str) -> bool:
    if os.path.exists(thumb_path):
        return True
        
    ext = os.path.splitext(full_media_path)[1].lower()
    is_video = ext in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".wmv"}
    
    if is_video:
        return generate_video_thumbnail(full_media_path, thumb_path)
    else:
        return generate_image_thumbnail(full_media_path, thumb_path)


def queue_background_thumbnail(full_media_path: str, thumb_path: str) -> None:
    executor.submit(get_or_generate_thumbnail, full_media_path, thumb_path)
