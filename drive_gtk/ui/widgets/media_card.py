"""Reusable media card widget for the GTK UI.

A self-contained card that renders a media item's thumbnail (loaded
async), a type badge, a selection checkbox, and a hover info overlay
(filename / size / date). Clicking the card invokes the supplied callback
with the item dict.
"""

import os
import threading

from gi.repository import GLib, Gtk

from core.thumbnails import get_or_generate_thumbnail


class MediaCard(Gtk.Box):
    def __init__(self, item, drive_path, on_selection_changed):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.item = item
        self.drive_path = drive_path
        self.on_selection_changed = on_selection_changed
        self.is_video = self.item["mime_type"].startswith("video/")

        self.add_css_class("media-card")
        self.set_size_request(190, 190)
        self.build_ui()

    def build_ui(self):
        filename = os.path.basename(self.item["current_relative_path"])

        overlay = Gtk.Overlay()
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)

        # --- Base layer: placeholder (icon + name), shown until/if no thumb ---
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        placeholder.add_css_class("card-placeholder")
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)

        icon = Gtk.Image()
        icon.set_from_icon_name(
            "video-x-generic-symbolic" if self.is_video else "image-x-generic-symbolic"
        )
        icon.set_pixel_size(36)
        icon.add_css_class("dim-label")
        placeholder.append(icon)

        ph_name = Gtk.Label(label=filename)
        ph_name.set_ellipsize(3)
        ph_name.set_max_width_chars(16)
        ph_name.add_css_class("caption")
        ph_name.add_css_class("dim-label")
        placeholder.append(ph_name)
        overlay.set_child(placeholder)

        # --- Thumbnail (object-cover); empty until async load, then covers ---
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.picture.add_css_class("card-thumb")
        overlay.add_overlay(self.picture)
        self.load_thumbnail_async()

        # --- Type badge (top-right): VIDEO / IMAGE ---
        type_badge = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        type_badge.add_css_class("type-badge")
        type_badge.set_halign(Gtk.Align.END)
        type_badge.set_valign(Gtk.Align.START)
        type_badge.set_margin_top(10)
        type_badge.set_margin_end(10)
        badge_icon = Gtk.Image()
        badge_icon.set_from_icon_name(
            "media-playback-start-symbolic"
            if self.is_video
            else "image-x-generic-symbolic"
        )
        badge_icon.set_pixel_size(10)
        type_badge.append(badge_icon)
        type_badge.append(Gtk.Label(label="VIDEO" if self.is_video else "IMAGE"))
        overlay.add_overlay(type_badge)

        # --- Selection checkbox (top-left); indicator only, shown in select mode ---
        self.checkbox = Gtk.CheckButton()
        self.checkbox.add_css_class("card-check")
        self.checkbox.set_halign(Gtk.Align.START)
        self.checkbox.set_valign(Gtk.Align.START)
        self.checkbox.set_margin_top(8)
        self.checkbox.set_margin_start(8)
        # Insensitive so clicks pass through to the card (selection is driven
        # by card activation), and hidden until selection mode is active.
        self.checkbox.set_sensitive(False)
        self.checkbox.set_visible(False)
        self.checkbox.connect("toggled", self.on_checkbox_toggled)
        overlay.add_overlay(self.checkbox)

        # --- Bottom gradient info overlay (revealed on hover via CSS) ---
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.add_css_class("card-info")
        info.set_valign(Gtk.Align.END)
        info.set_hexpand(True)

        name_lbl = Gtk.Label(label=filename)
        name_lbl.set_halign(Gtk.Align.START)
        name_lbl.set_ellipsize(3)
        name_lbl.set_tooltip_text(filename)
        name_lbl.add_css_class("card-info-name")
        info.append(name_lbl)

        meta_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        size_lbl = Gtk.Label(label=self.format_size(self.item["file_size"]))
        size_lbl.set_halign(Gtk.Align.START)
        size_lbl.set_hexpand(True)
        size_lbl.add_css_class("card-info-meta")
        date_lbl = Gtk.Label(label=self.format_date(self.item["created_at"]))
        date_lbl.set_halign(Gtk.Align.END)
        date_lbl.add_css_class("card-info-meta")
        meta_row.append(size_lbl)
        meta_row.append(date_lbl)
        info.append(meta_row)
        overlay.add_overlay(info)

        self.append(overlay)

    def load_thumbnail_async(self):
        file_hash = self.item["file_hash"]
        current_relative_path = self.item["current_relative_path"]

        thumb_path = os.path.join(
            self.drive_path, "albums", "thumbs", f"{file_hash}.jpg"
        )
        full_media_path = os.path.join(self.drive_path, current_relative_path)

        def worker():
            success = get_or_generate_thumbnail(full_media_path, thumb_path)
            if success and os.path.exists(thumb_path):
                GLib.idle_add(self.picture.set_filename, thumb_path)

        threading.Thread(target=worker, daemon=True).start()

    def format_size(self, size_bytes):
        return f"{size_bytes / 1024 / 1024:.2f} MB"

    def format_date(self, created_at):
        s = str(created_at)
        # Show just the date portion of an ISO-ish timestamp.
        return s.split("T")[0].split(" ")[0] if s else ""

    def on_checkbox_toggled(self, check):
        selected = check.get_active()
        if selected:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")
        self.on_selection_changed(self.item["id"], selected)

    def set_selected(self, selected):
        """Sync the visual selection state (CSS class + checkbox indicator)."""
        if selected:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")
        self.checkbox.set_active(selected)

    def set_select_mode(self, active):
        """Show the checkbox indicator only while selection mode is active."""
        self.checkbox.set_visible(active)
        if not active:
            self.set_selected(False)
