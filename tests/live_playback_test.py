"""Live playback test: plays a real 3s video through the new player UI.

Waits for the real GStreamer stream to prepare, then verifies duration,
seeking and pause behavior against the live pipeline.
Run with: python tests/live_playback_test.py
"""

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "drive_gtk"))

from ui.views.media_viewer import MediaViewer  # noqa: E402

VIDEO = "/tmp/smoke_test.mp4"
assert os.path.exists(VIDEO), "generate a video first (see live_playback notes)"

results = {}


def on_activate(app):
    item = {
        "id": 1,
        "current_relative_path": os.path.basename(VIDEO),
        "original_relative_path": os.path.basename(VIDEO),
        "file_size": os.path.getsize(VIDEO),
        "mime_type": "video/mp4",
        "created_at": "2026-01-01 00:00:00",
        "metadata_json": None,
    }
    drive = {"path": "/tmp", "name": "live-test"}

    win = Gtk.Window()
    win.set_default_size(900, 620)
    view = MediaViewer(win, drive, item)
    win.set_child(view)
    app.add_window(win)
    win.present()

    def on_prepared(stream, pspec):
        if not stream.is_prepared():
            return
        stream.disconnect(results["prepared_handler"])
        dur = stream.get_duration()
        results["duration_us"] = dur
        print(f"duration: {dur} us = {dur / 1e6:.2f}s")
        assert dur > 0, "duration should be positive"
        ok = stream.seek(1_000_000)
        print("seek(1s) ->", ok)
        results["seeked"] = True
        stream.pause()
        GLib.timeout_add(500, on_paused_check)
        return False

    def on_paused_check():
        stream = view._stream()
        pos = stream.get_timestamp()
        results["pos_after_pause"] = pos
        print(f"position after pause: {pos} us")
        assert pos == 1_000_000, f"seek did not land at 1s: {pos}"
        assert not stream.get_playing(), "should be paused"
        assert stream.is_seekable(), "should be seekable"
        results["checks_ok"] = True
        assert view.play_btn.get_icon_name() == "media-playback-start-symbolic", (
            "play icon should reset on pause"
        )
        assert view.controls.get_visible(), "controls should stay visible while paused"
        GLib.timeout_add(100, finish)
        return False

    def finish():
        view.cleanup_video()
        win.destroy()
        app.quit()
        return False

    def watchdog():
        print("WATCHDOG: stream never prepared within 10s")
        results["timeout"] = True
        view.cleanup_video()
        win.destroy()
        app.quit()
        return False

    results["prepared_handler"] = view._stream().connect(
        "notify::prepared", on_prepared
    )
    GLib.timeout_add(10000, watchdog)


app = Gtk.Application.new("test.liveplayback", 0)
app.connect("activate", on_activate)
app.run(None)

assert not results.get("timeout"), "watchdog fired"
assert results.get("duration_us", 0) > 0, "duration never became valid"
assert results.get("seeked"), "seek failed"
assert results.get("checks_ok"), f"checks failed: {results}"
print("LIVE_PLAYBACK_OK", results)
