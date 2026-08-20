import argparse
import importlib
import os
import sys
import time


def prompt_select_drive() -> str:
    """Interactively prompt user to select, mount, or refresh drives in CLI server mode."""
    from core.drives import get_connected_drives, mount_block_device

    while True:
        drives = get_connected_drives()
        print("\n" + "=" * 60, flush=True)
        print(" Available Storage Drives & Devices", flush=True)
        print("=" * 60, flush=True)

        if not drives:
            print(" No removable block devices detected.", flush=True)
        else:
            for idx, d in enumerate(drives, start=1):
                label = d.get("label") or "No Label"
                size = d.get("size") or "Unknown size"
                fstype = d.get("fstype") or "unknown"
                dev_id = d.get("id") or d.get("device") or ""
                is_mounted = d.get("is_mounted", False)
                path = d.get("path") or ""

                has_db = False
                if is_mounted and path and os.path.exists(os.path.join(path, "albums", ".media_library.db")):
                    has_db = True

                status_str = f"Mounted at {path}" if is_mounted else "Unmounted"
                db_str = " (Has Library DB)" if has_db else ""
                print(f" [{idx}] {dev_id} ({size}, {fstype}, {label}) - [{status_str}]{db_str}", flush=True)

        cwd_idx = len(drives) + 1
        print(f" [{cwd_idx}] Current Directory: {os.getcwd()}", flush=True)
        print("-" * 60, flush=True)
        print(" Options:", flush=True)
        print("   [1-N]      : Select drive / directory", flush=True)
        print("   [m <num>]  : Mount an unmounted partition (e.g. 'm 2')", flush=True)
        print("   [r]        : Refresh drive list (after plugging in drive)", flush=True)
        print("   [p <path>] : Specify a custom directory path", flush=True)
        print("   [q]        : Quit", flush=True)
        print("=" * 60, flush=True)

        if not sys.stdin.isatty():
            print("Non-interactive shell detected. Falling back to current directory.", flush=True)
            return os.getcwd()

        try:
            choice = input("Enter selection: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...", flush=True)
            sys.exit(0)

        if not choice:
            continue

        choice_lower = choice.lower()
        if choice_lower in ("q", "quit", "exit"):
            print("Exiting.", flush=True)
            sys.exit(0)

        if choice_lower in ("r", "refresh"):
            print("Refreshing drive list...", flush=True)
            continue

        if choice_lower.startswith("p "):
            custom_p = choice[2:].strip()
            if os.path.exists(custom_p) and os.path.isdir(custom_p):
                return os.path.abspath(custom_p)
            else:
                print(f"Error: Directory '{custom_p}' does not exist.", flush=True)
                continue

        if choice_lower.startswith("m "):
            parts = choice.split()
            if len(parts) >= 2 and parts[1].isdigit():
                m_idx = int(parts[1]) - 1
                if 0 <= m_idx < len(drives):
                    dev = drives[m_idx]
                    dev_id = dev.get("id") or dev.get("device")
                    print(f"Mounting {dev_id}...", flush=True)
                    res = mount_block_device(dev_id)
                    if res.get("success"):
                        print(f"Successfully mounted at: {res.get('mountPath')}", flush=True)
                    else:
                        print(f"Failed to mount: {res.get('error')}", flush=True)
                else:
                    print("Invalid drive number.", flush=True)
            continue

        if choice.isdigit():
            val = int(choice)
            if val == cwd_idx:
                return os.getcwd()
            if 1 <= val <= len(drives):
                dev = drives[val - 1]
                if dev.get("is_mounted") and dev.get("path"):
                    return dev["path"]
                else:
                    dev_id = dev.get("id") or dev.get("device")
                    print(f"Drive is unmounted. Attempting to mount {dev_id}...", flush=True)
                    res = mount_block_device(dev_id)
                    if res.get("success") and res.get("mountPath"):
                        print(f"Mounted at {res.get('mountPath')}", flush=True)
                        return res["mountPath"]
                    else:
                        print(f"Mount failed: {res.get('error')}. Please mount manually or choose another option.", flush=True)
                        continue

        print("Invalid command or choice. Try again.", flush=True)


def run_server_mode(drive_path=None, port=8080):
    from core.sync_server import start_mobile_sync_server, stop_mobile_sync_server, get_local_ip
    from core.drives import get_connected_drives

    if drive_path and not os.path.exists(drive_path):
        print(f"Warning: Specified drive path '{drive_path}' does not exist.", flush=True)
        drive_path = None

    if not drive_path:
        # Check if any mounted drive has an existing database
        connected = get_connected_drives()
        for d in connected:
            p = d.get("path")
            if p and os.path.exists(os.path.join(p, "albums", ".media_library.db")):
                drive_path = p
                break

        # If no mounted drive with DB found, prompt user interactively
        if not drive_path:
            has_mounted = any(d.get("is_mounted") and d.get("path") for d in connected)
            if not has_mounted or len(connected) > 1:
                drive_path = prompt_select_drive()
            elif has_mounted:
                for d in connected:
                    if d.get("path") and os.path.exists(d["path"]):
                        drive_path = d["path"]
                        break

        if not drive_path:
            drive_path = os.getcwd()

    res = start_mobile_sync_server(drive_path, port)
    if not res.get("success"):
        print(f"Error starting server: {res.get('error')}", flush=True)
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

