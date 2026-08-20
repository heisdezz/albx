"""Smoke test for the MediaViewer video player UI.

Builds the real widget tree on the running display, exercises the playback
handlers with a fake stream, then tears down.
Run with: python tests/smoke_media_viewer.py
"""

import os
import sys
import tempfile

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "drive_gtk"))

from ui.views.media_viewer import MediaViewer  # noqa: E402

Gtk.init()


def make_view(parent):
    item = {
        "id": 1,
        "current_relative_path": "videos/test.mp4",
        "original_relative_path": "videos/test.mp4",
        "file_size": 12345,
        "mime_type": "video/mp4",
        "created_at": "2026-01-01 00:00:00",
        "metadata_json": None,
    }
    drive = {"path": tempfile.gettempdir(), "name": "smoke-drive"}
    return MediaViewer(parent, drive, item)


win = Gtk.Window()
win.set_default_size(1000, 700)
view = make_view(win)
win.set_child(view)
win.present()

# Walk the tree to make sure everything is buildable.
assert view.video_widget is not None, "video widget missing"
assert view.controls is not None, "controls missing"
assert view.player_overlay is not None, "overlay missing"
assert view.seek_scale is not None and view.play_btn is not None

# Exercise pure helpers
assert MediaViewer.format_time(0) == "00:00"
assert MediaViewer.format_time(65_000_000) == "01:05"
assert MediaViewer.format_time(3_721_000_000) == "1:02:01"
assert MediaViewer.format_time(-1) == "--:--"
assert view._volume_icon_name(1.0, False) == "audio-volume-high-symbolic"
assert view._volume_icon_name(0.5, False) == "audio-volume-medium-symbolic"
assert view._volume_icon_name(0.2, False) == "audio-volume-low-symbolic"
assert view._volume_icon_name(0.0, False) == "audio-volume-muted-symbolic"
assert view._volume_icon_name(1.0, True) == "audio-volume-muted-symbolic"


# Exercise control visibility + playback handlers with a fake stream.
class FakeStream:
    def __init__(self):
        self._playing = True
        self._volume = 0.7
        self._muted = False
        self._pos = 10_000_000

    def get_playing(self):
        return self._playing

    def get_ended(self):
        return False

    def get_timestamp(self):
        return self._pos

    def get_duration(self):
        return 100_000_000

    def is_seekable(self):
        return True

    def get_volume(self):
        return self._volume

    def get_muted(self):
        return self._muted

    def play(self):
        self._playing = True

    def pause(self):
        self._playing = False

    def seek(self, pos):
        self._pos = int(pos)

    def set_volume(self, v):
        self._volume = v

    def set_muted(self, m):
        self._muted = m

    def stream_unprepared(self):
        pass


fs = FakeStream()
view.video_widget.get_media_stream = lambda: fs
view.on_play_pause()
assert fs._playing is False, "pause failed"
view.on_play_pause()
assert fs._playing is True, "play failed"
view.on_seek_change(view.seek_scale, None, 42_000_000)
assert fs._pos == 42_000_000, "seek failed"
view.on_volume_change(view.volume_scale, None, 30)
assert abs(fs._volume - 0.3) < 1e-9, "volume failed"
view.on_mute_clicked()
assert fs._muted is True, "mute failed"
view._seek_relative(-5_000_000)
assert fs._pos == 37_000_000, f"relative seek failed: {fs._pos}"
view._change_volume(0.2)
assert abs(fs._volume - 0.5) < 1e-9, "volume delta failed"
view._update_play_icon()
view._update_volume_ui()
view._update_time_label()
assert "00:37" in view.time_lbl.get_text() and "01:40" in view.time_lbl.get_text(), (
    view.time_lbl.get_text()
)

# Simulate key presses (space, Left, Right, m, Up, Down, n, p, f)
handler = view._on_player_key
assert handler(None, 0x20, 0, 0) is True  # space
assert handler(None, 0xFF51, 0, 0) is True  # Left
assert handler(None, 0xFF53, 0, 0) is True  # Right
assert handler(None, 0xFF52, 0, 0) is True  # Up
assert handler(None, 0xFF54, 0, 0) is True  # Down
assert handler(None, 0x6D, 0, 0) is True  # m
assert handler(None, 0x66, 0, 0) is True  # f
assert handler(None, 0xFFFFFFFF, 0, 0) is False  # unknown

# Hover-reveal logic: controls hide while playing, stay visible while paused
fs._playing = True
view._show_controls()
assert view.controls.get_visible() is True
view._hide_controls_now()
assert view.controls.get_visible() is False

fs._playing = False
view._show_controls()
assert view.controls.get_visible() is True
view._hide_controls_now()
assert view.controls.get_visible() is True  # paused -> keep controls

print("SMOKE_OK")
view.cleanup_video()
win.destroy()
