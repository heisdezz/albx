import argparse
import importlib
import os
import sys
import time


def run_server_mode(drive_path=None, port=8080):
    from core.sync_server import start_mobile_sync_server, stop_mobile_sync_server, get_local_ip
    from core.drives import get_connected_drives

    if not drive_path:
        connected = get_connected_drives()
        for d in connected:
            p = d.get("path")
            if p and os.path.exists(os.path.join(p, "albums", ".media_library.db")):
                drive_path = p
                break
        if not drive_path:
            for d in connected:
                if d.get("path") and os.path.exists(d["path"]):
                    drive_path = d["path"]
                    break
        if not drive_path:
            drive_path = os.getcwd()

    res = start_mobile_sync_server(drive_path, port)
    if not res.get("success"):
        print(f"Error starting server: {res.get('error')}")
        sys.exit(1)

    local_ip = res.get("ip", get_local_ip())
    actual_port = res.get("port", port)
    base_url = f"http://{local_ip}:{actual_port}"

    print("=" * 60, flush=True)
    print(" External Drive Media Organizer - Local Sync Server", flush=True)
    print("=" * 60, flush=True)
    print(f" Drive Path    : {drive_path}", flush=True)
    print(f" Server Address: {base_url}/", flush=True)
    print(f" DB Download   : {base_url}/download/db", flush=True)
    print(f" Library Info  : {base_url}/api/info", flush=True)
    print(f" Media Stream  : {base_url}/media/<item_id>", flush=True)
    print(f" Thumbnails    : {base_url}/thumbnail/<item_id>", flush=True)
    print("=" * 60, flush=True)
    print(" Server running in headless mode. Press Ctrl+C to stop.", flush=True)
    print("=" * 60, flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...", flush=True)
        stop_mobile_sync_server()
        print("Server stopped cleanly.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="External Drive Media Organizer")
    parser.add_argument("--server", action="store_true", help="Start standalone local sync server (no GUI)")
    parser.add_argument("--drive", type=str, default=None, help="Target drive path for sync server")
    parser.add_argument("--port", type=int, default=8080, help="Port for local sync server (default: 8080)")
    parser.add_argument("--qt", action="store_true", help="Launch Qt frontend UI")
    parser.add_argument("--gtk", action="store_true", help="Launch GTK 4 frontend UI (default)")

    args, remaining = parser.parse_known_args()

    if args.server:
        run_server_mode(drive_path=args.drive, port=args.port)
        return

    sys.argv = [sys.argv[0]] + remaining

    if args.qt:
        qt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drive_qt")
        if qt_dir not in sys.path:
            sys.path.insert(0, qt_dir)
        mod = importlib.import_module("drive_qt.main")
    else:
        gtk_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drive_gtk")
        if gtk_dir not in sys.path:
            sys.path.insert(0, gtk_dir)
        mod = importlib.import_module("drive_gtk.main")

    mod.main()


if __name__ == "__main__":
    main()

