import importlib.util
import os
import sys


def _load_backend(directory: str, filename: str, module_name: str):
    # Make imports inside the backend (ui, core, router) resolve correctly.
    if directory not in sys.path:
        sys.path.insert(0, directory)
    path = os.path.join(directory, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    root = os.path.dirname(os.path.abspath(__file__))
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
        mod = _load_backend(os.path.join(root, "drive_qt"), "main.py", "drive_qt.main")
    else:
        mod = _load_backend(os.path.join(root, "drive_gtk"), "main.py", "drive_gtk.main")

    mod.main()


if __name__ == "__main__":
    main()
