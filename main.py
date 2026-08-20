import importlib
import sys
import os


def main():
    backend = "gtk"
    filtered = []
    for arg in sys.argv[1:]:
        if arg == "--qt":
            backend = "qt"
        elif arg == "--gtk":
            backend = "gtk"
        else:
            filtered.append(arg)
    sys.argv = [sys.argv[0]] + filtered

    if backend == "qt":
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
