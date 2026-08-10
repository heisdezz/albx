import sys

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
