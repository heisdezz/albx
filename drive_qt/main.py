import locale
import os
import sys

from PySide6.QtWidgets import QApplication

from ui.window import MainWindow


def main():
    # The embedded mpv player needs a real X11 window id (mpv's ``wid``
    # embedding can't work on Wayland - mpv opens its own wl_display, so a
    # wl_surface id from Qt's connection is meaningless there and the video
    # output silently fails, leaving audio only). Route Qt through XWayland
    # when the session is Wayland so winId() yields an X11 window mpv can
    # render into. Also sidesteps the wl_subsurface/wayland protocol crashes.
    if (
        os.environ.get("WAYLAND_DISPLAY")
        and os.environ.get("DISPLAY")
        and not os.environ.get("QT_QPA_PLATFORM")
    ):
        os.environ["QT_QPA_PLATFORM"] = "xcb"

    # Qt (and its FFmpeg multimedia backend) requires a C numeric locale:
    # with e.g. comma decimal separators it mis-parses numbers and can
    # segfault. Keep the rest of the locale intact.
    #
    # Qt reads the locale from the environment during QApplication
    # construction (initLocale() calls setlocale(LC_ALL, "")), so a plain
    # setlocale() before that would be undone by the env vars. Force the
    # env var first, then re-assert after construction as a belt-and-braces.
    os.environ["LC_NUMERIC"] = "C"
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
    except locale.Error:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("Antigravity Drive Media Organizer")
    app.setOrganizationName("Antigravity")

    # After QApplication, Qt has applied the environment locale again via
    # setlocale(LC_ALL, ""); re-assert the C numeric locale so number parsing
    # never sees comma decimals (SIGSEGV in the media/ffmpeg path).
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
    except locale.Error:
        pass

    win = MainWindow()
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
