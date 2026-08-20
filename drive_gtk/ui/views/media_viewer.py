import json
import os
import sqlite3
import subprocess

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
from router import get_router

from core.database import get_database_connection, open_readable_db
from core.thumbnails import set_thumbnails_paused


def escape_markup(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""))


class MediaViewer(Gtk.Box):
    def __init__(self, parent_window, drive, item, album_id=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent_window = parent_window
        self.drive = drive
        self.item = dict(item)
        self.album_id = album_id

        self.video_widget = None
        self._media_stream = None
        self.celluloid_proc = None
        self.fs_window = None

        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(16)
        self.set_margin_bottom(16)

        self.build_ui()
        self.load_item_details()

    def build_ui(self):
        # Navigation Bar
        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        nav_box.add_css_class("topbar")

        back_btn = Gtk.Button()
        back_btn.set_icon_name("go-previous-symbolic")
        back_btn.connect("clicked", self.on_back_clicked)
        nav_box.append(back_btn)

        self.filename_lbl = Gtk.Label()
        self.filename_lbl.set_markup("<b>Media Viewer</b>")
        self.filename_lbl.set_halign(Gtk.Align.START)
        nav_box.append(self.filename_lbl)

        pagination_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pagination_box.set_hexpand(True)
        pagination_box.set_halign(Gtk.Align.END)

        self.prev_btn = Gtk.Button()
        self.prev_btn.set_icon_name("go-previous-symbolic")
        self.prev_btn.connect("clicked", lambda x: self.navigate_to("prev"))

        self.next_btn = Gtk.Button()
        self.next_btn.set_icon_name("go-next-symbolic")
        self.next_btn.connect("clicked", lambda x: self.navigate_to("next"))

        # Fullscreen toggle
        self.fullscreen_btn = Gtk.Button()
        self.fullscreen_btn.set_icon_name("view-fullscreen-symbolic")
        self.fullscreen_btn.set_tooltip_text("Fullscreen player")
        self.fullscreen_btn.connect("clicked", self.on_fullscreen_clicked)

        # Open in Celluloid button
        self.open_external_btn = Gtk.Button()
        self.open_external_btn.set_icon_name("media-playback-start-symbolic")
        self.open_external_btn.set_tooltip_text("Open in Celluloid")
        self.open_external_btn.connect("clicked", self.on_open_in_celluloid)
        self.open_external_btn.set_visible(False)

        pagination_box.append(self.prev_btn)
        pagination_box.append(self.next_btn)
        pagination_box.append(self.fullscreen_btn)
        pagination_box.append(self.open_external_btn)
        nav_box.append(pagination_box)

        self.append(nav_box)

        # --- Responsive 3:1 Layout via Adw.BreakpointBin ---
        # The content_box holds both the media (3 parts) and sidebar (1 part).
        # An Adw.Breakpoint flips the orientation to vertical below 600px.
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.content_box.set_vexpand(True)

        # Left: Media Container (takes 3/4 of horizontal space)
        self.media_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.media_container.add_css_class("card")
        self.media_container.set_valign(Gtk.Align.FILL)
        self.media_container.set_halign(Gtk.Align.FILL)
        self.media_container.set_hexpand(True)
        self.media_container.set_vexpand(True)
        self.content_box.append(self.media_container)

        # Right: File Details & Metadata Sidebar (takes 1/4)
        self.right_scroll = Gtk.ScrolledWindow()
        self.right_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.right_scroll.set_size_request(300, -1)
        self.right_scroll.set_hexpand(False)

        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        right_box.set_margin_start(12)
        right_box.set_margin_end(12)
        right_box.set_margin_top(12)
        right_box.set_margin_bottom(12)
        self.right_scroll.set_child(right_box)
        self.content_box.append(self.right_scroll)

        # Wrap in BreakpointBin for responsive layout
        bp_bin = Adw.BreakpointBin()
        bp_bin.set_child(self.content_box)
        bp_bin.set_hexpand(True)
        bp_bin.set_vexpand(True)

        # Below 600px: stack vertically, sidebar expands horizontally
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 600px"))
        bp.add_setter(self.content_box, "orientation", Gtk.Orientation.VERTICAL)
        bp.add_setter(self.right_scroll, "hexpand", True)
        bp.add_setter(self.right_scroll, "width-request", 0)
        bp_bin.add_breakpoint(bp)

        self.append(bp_bin)

        # Clean up when leaving this view
        self.connect("unrealize", self.on_unrealize)

        # --- SECTION 1: FILE DETAILS ---
        info_group = Adw.PreferencesGroup()
        info_group.set_title("File Details")

        self.details_list = Gtk.ListBox()
        self.details_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.details_list.add_css_class("boxed-list")
        info_group.add(self.details_list)

        right_box.append(info_group)

        # --- SECTION 2: MEDIA TAGS ---
        tags_group = Adw.PreferencesGroup()
        tags_group.set_title("Media Tags")

        tags_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        tags_card.add_css_class("card")

        self.tags_flow = Gtk.FlowBox()
        self.tags_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.tags_flow.set_row_spacing(6)
        self.tags_flow.set_column_spacing(6)
        tags_card.append(self.tags_flow)

        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        tags_card.append(sep1)

        tag_input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.tag_entry = Gtk.Entry()
        self.tag_entry.set_placeholder_text("Add new tag name...")
        self.tag_entry.set_hexpand(True)
        self.tag_entry.connect("activate", self.on_add_tag_activate)

        add_tag_btn = Gtk.Button(label="Add")
        add_tag_btn.add_css_class("suggested-action")
        add_tag_btn.connect(
            "clicked", lambda x: self.on_add_tag_activate(self.tag_entry)
        )
        tag_input_box.append(self.tag_entry)
        tag_input_box.append(add_tag_btn)
        tags_card.append(tag_input_box)

        tags_group.add(tags_card)
        right_box.append(tags_group)

        # --- SECTION 3: EXIF / METADATA JSON ---
        meta_group = Adw.PreferencesGroup()
        meta_group.set_title("EXIF / Metadata JSON")

        meta_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        meta_card.add_css_class("card")

        meta_scroll = Gtk.ScrolledWindow()
        meta_scroll.set_size_request(-1, 140)

        self.meta_text = Gtk.TextView()
        self.meta_text.set_editable(False)
        self.meta_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.meta_text.set_monospace(True)
        self.meta_text.set_margin_start(6)
        self.meta_text.set_margin_top(6)
        self.meta_text.set_margin_bottom(6)
        self.meta_text.set_margin_end(6)

        meta_scroll.set_child(self.meta_text)
        meta_card.append(meta_scroll)
        meta_group.add(meta_card)
        right_box.append(meta_group)

    def cleanup_video(self):
        """Stop embedded video playback and kill any external Celluloid."""
        if self._media_stream is not None:
            try:
                self._media_stream.pause()
            except Exception:
                pass
            self._media_stream = None
        self.video_widget = None
        if self.celluloid_proc is not None:
            try:
                self.celluloid_proc.terminate()
            except Exception as e:
                print(f"[MediaViewer] Error terminating Celluloid: {e}")
            self.celluloid_proc = None
        set_thumbnails_paused(False)

    def load_item_details(self):
        # Tear down fullscreen if active
        if self.fs_window is not None:
            self.exit_fullscreen(reparent=False)
        self.cleanup_video()

        while True:
            child = self.media_container.get_first_child()
            if not child:
                break
            self.media_container.remove(child)

        full_path = os.path.join(self.drive["path"], self.item["current_relative_path"])
        filename = os.path.basename(self.item["current_relative_path"])
        self.current_video_path = full_path

        self.filename_lbl.set_markup(f"<b>{escape_markup(filename)}</b>")

        mime = self.item["mime_type"]
        is_video = mime.startswith("video/")
        self.open_external_btn.set_visible(is_video)
        self.fullscreen_btn.set_visible(True)

        if is_video:
            set_thumbnails_paused(True)
            self.build_video_player(full_path, filename)
        else:
            try:
                picture = Gtk.Picture.new_for_filename(full_path)
                picture.set_size_request(480, 380)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                picture.set_margin_start(8)
                picture.set_margin_end(8)
                picture.set_margin_top(8)
                picture.set_margin_bottom(8)
                self.media_container.append(picture)
            except Exception as e:
                print(f"[MediaViewer] Failed to load image: {e}")
                err_lbl = Gtk.Label(label="Failed to load image file.")
                self.media_container.append(err_lbl)

        # Populate File Details List Rows
        self.populate_details_list(mime)

        # Populate EXIF Metadata
        meta_json = self.item.get("metadata_json")
        buffer = self.meta_text.get_buffer()
        if meta_json:
            try:
                parsed = json.loads(meta_json)
                buffer.set_text(json.dumps(parsed, indent=2))
            except Exception:
                buffer.set_text(meta_json)
        else:
            buffer.set_text("No EXIF metadata recorded.")

        self.load_tags()
        self.query_navigation_neighbors()

    # --- Video Player --------------------------------------------------------

    def build_video_player(self, full_path, filename):
        """Show the video using Gtk.Video's own built-in media controls."""
        video = Gtk.Video()
        video.set_file(Gio.File.new_for_path(full_path))
        video.set_autoplay(True)
        video.set_loop(False)
        video.set_hexpand(True)
        video.set_vexpand(True)
        video.set_margin_start(8)
        video.set_margin_end(8)
        video.set_margin_top(8)
        video.set_margin_bottom(8)
        self.video_widget = video
        self._media_stream = video.get_media_stream()
        self.media_container.append(video)

    # --- Fullscreen -----------------------------------------------------------

    def on_fullscreen_clicked(self, btn):
        # Defer to idle so we never reparent media_container from inside an
        # event handler on a widget that lives *inside* it. The overlay
        # fullscreen button, the click gesture and the key controller are all
        # children of media_container; reparenting it mid-event breaks the
        # in-flight gesture and the toggle silently fails. The top-bar button
        # lives in the header (outside media_container), which is why it
        # already worked.
        GLib.idle_add(self._toggle_fullscreen)

    def _toggle_fullscreen(self):
        if self.fs_window is not None:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()
        return False

    def enter_fullscreen(self):
        """Reparent the media container into a dedicated fullscreen window."""
        if self.fs_window is not None:
            return
        # Detach the media card from the content box
        self.content_box.remove(self.media_container)

        win = Gtk.Window()
        win.set_transient_for(self.parent_window)
        win.set_child(self.media_container)
        win.connect("close-request", self._on_fs_close)

        # Escape / F11 exits fullscreen
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_fs_key)
        win.add_controller(key_ctrl)

        self.fs_window = win
        self.fullscreen_btn.set_icon_name("view-restore-symbolic")
        self.fullscreen_btn.set_tooltip_text("Exit fullscreen")

        # Hide sidebar while fullscreen
        self.right_scroll.set_visible(False)

        win.fullscreen()
        win.present()

    def exit_fullscreen(self, reparent=True):
        """Restore the media container back into the inline layout."""
        if self.fs_window is None:
            return
        win = self.fs_window
        self.fs_window = None

        win.set_child(None)
        if reparent:
            # Re-insert media container as the first child (before sidebar)
            self.content_box.prepend(self.media_container)
        win.destroy()

        self.fullscreen_btn.set_icon_name("view-fullscreen-symbolic")
        self.fullscreen_btn.set_tooltip_text("Fullscreen player")
        self.right_scroll.set_visible(True)

    def _on_fs_close(self, win):
        self.exit_fullscreen()
        return True

    def _on_fs_key(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_F11, Gdk.KEY_f):
            self.exit_fullscreen()
            return True
        return False

    # --- Celluloid External ---------------------------------------------------

    def on_open_in_celluloid(self, btn):
        """Open the current video in Celluloid for full-featured playback."""
        path = getattr(self, "current_video_path", None)
        if not path:
            return
        # Pause the inline player so audio doesn't overlap
        if self._media_stream:
            self._media_stream.pause()
        try:
            self.celluloid_proc = subprocess.Popen(
                ["celluloid", "--new-window", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[MediaViewer] Opened in Celluloid: {os.path.basename(path)}")
        except FileNotFoundError:
            print("[MediaViewer] Celluloid not found, trying xdg-open")
            try:
                subprocess.Popen(
                    ["xdg-open", path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                print(f"[MediaViewer] Failed to open video: {e}")

    # --- Details & Tags -------------------------------------------------------

    def populate_details_list(self, mime):
        while True:
            child = self.details_list.get_first_child()
            if not child:
                break
            self.details_list.remove(child)

        details = [
            ("Current Path", self.item["current_relative_path"], "folder-symbolic"),
            (
                "Original Path",
                self.item["original_relative_path"],
                "document-open-symbolic",
            ),
            (
                "File Size",
                self.format_bytes(self.item["file_size"]),
                "drive-harddisk-symbolic",
            ),
            ("MIME Type", mime, "dialog-information-symbolic"),
            (
                "Import Date",
                str(self.item["created_at"]),
                "preferences-system-time-symbolic",
            ),
        ]

        for title, value, icon_name in details:
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_subtitle(escape_markup(value))
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
            self.details_list.append(row)

    def load_tags(self):
        while True:
            child = self.tags_flow.get_first_child()
            if not child:
                break
            self.tags_flow.remove(child)

        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            return

        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT t.id, t.name, t.color_hex FROM tags t
                JOIN media_tags mt ON t.id = mt.tag_id
                WHERE mt.media_id = ?
                """,
                (self.item["id"],),
            )
            tags = cursor.fetchall()

            for tag in tags:
                tag_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                tag_box.add_css_class("badge")
                tag_box.add_css_class("badge-primary")

                lbl = Gtk.Label(label=tag["name"])
                tag_box.append(lbl)

                del_btn = Gtk.Button()
                del_btn.set_icon_name("window-close-symbolic")
                del_btn.add_css_class("flat")
                del_btn.connect(
                    "clicked", lambda x, t_id=tag["id"]: self.remove_tag(t_id)
                )
                tag_box.append(del_btn)

                self.tags_flow.append(tag_box)

            conn.close()
        except Exception as e:
            print(f"[MediaViewer] Failed to load tags: {e}")

    def remove_tag(self, tag_id):
        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        conn = None
        try:
            conn = get_database_connection(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM media_tags WHERE media_id = ? AND tag_id = ?",
                (self.item["id"], tag_id),
            )
            conn.commit()
            self.load_tags()
        except Exception as e:
            print(f"[MediaViewer] Failed to delete tag: {e}")
        finally:
            if conn:
                conn.close()

    def on_add_tag_activate(self, entry):
        text = entry.get_text().strip()
        if not text:
            return

        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        conn = None
        try:
            conn = get_database_connection(db_path)
            cursor = conn.cursor()

            cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (text,))
            cursor.execute("SELECT id FROM tags WHERE name = ?", (text,))
            tag_id = cursor.fetchone()[0]

            cursor.execute(
                "INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?, ?)",
                (self.item["id"], tag_id),
            )
            conn.commit()

            entry.set_text("")
            self.load_tags()
        except Exception as e:
            print(f"[MediaViewer] Add tag failed: {e}")
        finally:
            if conn:
                conn.close()

    # --- Navigation -----------------------------------------------------------

    def query_navigation_neighbors(self):
        self.prev_id = None
        self.next_id = None

        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            return

        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()

            created_at = self.item["created_at"]
            item_id = self.item["id"]

            album_filter = " AND album_id = ?" if self.album_id is not None else ""
            params = [created_at, created_at, item_id]
            if self.album_id is not None:
                params.append(self.album_id)

            next_q = f"""
                SELECT id FROM media_items
                WHERE (created_at < ? OR (created_at = ? AND id < ?))
                {album_filter}
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            """

            prev_q = f"""
                SELECT id FROM media_items
                WHERE (created_at > ? OR (created_at = ? AND id > ?))
                {album_filter}
                ORDER BY created_at ASC, id ASC
                LIMIT 1
            """

            cursor.execute(next_q, params)
            next_row = cursor.fetchone()
            if next_row:
                self.next_id = next_row["id"]

            cursor.execute(prev_q, params)
            prev_row = cursor.fetchone()
            if prev_row:
                self.prev_id = prev_row["id"]

            self.prev_btn.set_sensitive(self.prev_id is not None)
            self.next_btn.set_sensitive(self.next_id is not None)
            if hasattr(self, "player_prev_btn"):
                self.player_prev_btn.set_sensitive(self.prev_id is not None)
                self.player_next_btn.set_sensitive(self.next_id is not None)

            conn.close()
        except Exception as e:
            print(f"[MediaViewer] Neighbor query failed: {e}")

    def navigate_to(self, direction):
        target_id = self.prev_id if direction == "prev" else self.next_id
        if not target_id:
            return

        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM media_items WHERE id = ?", (target_id,))
            row = cursor.fetchone()
            if row:
                self.item = dict(row)
                self.load_item_details()
            conn.close()
        except Exception as e:
            print(f"[MediaViewer] Navigation load failed: {e}")

    # --- Lifecycle ------------------------------------------------------------

    def on_unrealize(self, widget):
        if self.fs_window is not None:
            self.exit_fullscreen(reparent=False)
        self.cleanup_video()

    def on_back_clicked(self, btn):
        if self.fs_window is not None:
            self.exit_fullscreen(reparent=False)
        self.cleanup_video()
        get_router().back()

    def format_bytes(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        import math

        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
