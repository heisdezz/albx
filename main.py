import importlib
import sys


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
        mod = importlib.import_module("drive_qt.main")
    else:
        mod = importlib.import_module("drive_gtk.main")

    mod.main()


if __name__ == "__main__":
    main()
