import sys
import os

drive_gtk_dir = os.path.dirname(os.path.abspath(__file__))
if drive_gtk_dir not in sys.path:
    sys.path.insert(0, drive_gtk_dir)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
from ui.gui import MainWindow


def on_activate(app: Adw.Application) -> None:
    win = MainWindow(app)
    win.present()


def main() -> None:
    app = Adw.Application(application_id="com.antigravity.drivemediaorganizer")
    app.connect("activate", on_activate)
    app.run(sys.argv)


if __name__ == "__main__":
    main()
