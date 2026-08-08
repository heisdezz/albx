import datetime
import threading
from typing import List, Dict, Any, Optional

app_logs: List[Dict[str, Any]] = []
logs_lock = threading.Lock()

def add_log(level: str, message: str, context: Optional[str] = None) -> None:
    timestamp = datetime.datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "level": level,
        "message": message,
        "context": context
    }
    with logs_lock:
        app_logs.append(log_entry)
        if len(app_logs) > 500:
            app_logs.pop(0)
            
    ctx_str = f" | {context}" if context else ""
    print(f"[{level.upper()}] {timestamp} - {message}{ctx_str}")

def get_logs(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    with logs_lock:
        logs = list(app_logs)
        if limit is not None and limit > 0:
            return logs[-limit:]
        return logs
