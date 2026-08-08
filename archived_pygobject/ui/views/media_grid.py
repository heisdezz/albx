import os
import sqlite3
import threading
from gi.repository import Gtk, Gdk, GLib, Adw
from core.database import open_readable_db, get_database_connection
from core.thumbnails import get_or_generate_thumbnail
from router import get_router
from ui.views.settings import get_page_size, PAGE_SIZE_OPTIONS

class MediaCard(Gtk.Box):
    def __init__(self, item, drive_path, on_clicked_callback, on_selection_changed):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.item = item
        self.drive_path = drive_path
        self.on_clicked = on_clicked_callback
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
            "media-playback-start-symbolic" if self.is_video else "image-x-generic-symbolic"
        )
        badge_icon.set_pixel_size(10)
        type_badge.append(badge_icon)
        type_badge.append(Gtk.Label(label="VIDEO" if self.is_video else "IMAGE"))
        overlay.add_overlay(type_badge)

        # --- Selection checkbox (top-left) ---
        self.checkbox = Gtk.CheckButton()
        self.checkbox.add_css_class("card-check")
        self.checkbox.set_halign(Gtk.Align.START)
        self.checkbox.set_valign(Gtk.Align.START)
        self.checkbox.set_margin_top(8)
        self.checkbox.set_margin_start(8)
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

        click_gesture = Gtk.GestureClick()
        click_gesture.connect("released", self.on_card_clicked)
        self.add_controller(click_gesture)

    def load_thumbnail_async(self):
        file_hash = self.item["file_hash"]
        current_relative_path = self.item["current_relative_path"]

        thumb_path = os.path.join(self.drive_path, "albums", "thumbs", f"{file_hash}.jpg")
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

    def on_card_clicked(self, gesture, n_press, x, y):
        self.on_clicked(self.item)

class MediaGridView(Gtk.Box):
    def __init__(self, parent_window, drive, filter_album_id=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent_window = parent_window
        self.drive = drive
        self.filter_album_id = filter_album_id
        
        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        
        self.current_page = 0
        self.page_size = get_page_size(drive["path"]) if drive else 24
        self.total_count = 0
        self.search_query = ""
        self.filter_type = "all"
        self.sort_by = "date"
        self.sort_order = "desc"
        self.selected_ids = set()
        
        self.build_ui()
        if self.drive:
            self.load_data()
            
    def build_ui(self):
        filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search media files...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self.on_search_changed)
        filter_bar.append(self.search_entry)
        
        self.type_combo = Gtk.ComboBoxText()
        self.type_combo.append("all", "All Media")
        self.type_combo.append("images", "Images Only")
        self.type_combo.append("videos", "Videos Only")
        self.type_combo.set_active_id("all")
        self.type_combo.connect("changed", self.on_type_changed)
        filter_bar.append(self.type_combo)
        
        self.sort_combo = Gtk.ComboBoxText()
        self.sort_combo.append("date", "Sort: Date Added")
        self.sort_combo.append("name", "Sort: Name")
        self.sort_combo.append("size", "Sort: Size")
        self.sort_combo.set_active_id("date")
        self.sort_combo.connect("changed", self.on_sort_changed)
        filter_bar.append(self.sort_combo)
        
        self.order_btn = Gtk.Button()
        self.order_btn.set_icon_name("media-playlist-consecutive-symbolic")
        self.order_btn.connect("clicked", self.on_order_toggled)
        filter_bar.append(self.order_btn)
        
        self.append(filter_bar)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        
        self.flow_box = Gtk.FlowBox()
        self.flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow_box.set_row_spacing(12)
        self.flow_box.set_column_spacing(12)
        self.flow_box.set_max_children_per_line(8)
        self.flow_box.set_min_children_per_line(3)
        self.flow_box.set_margin_top(8)
        self.flow_box.set_margin_bottom(8)
        self.flow_box.connect("child-activated", self.on_flowbox_child_activated)
        
        scroll.set_child(self.flow_box)
        self.append(scroll)
        
        self.batch_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.batch_actions.add_css_class("card")
        self.batch_actions.set_visible(False)
        self.batch_actions.set_margin_top(8)
        
        self.selection_lbl = Gtk.Label(label="Selected: 0 items")
        self.selection_lbl.set_halign(Gtk.Align.START)
        self.batch_actions.append(self.selection_lbl)
        
        self.album_combo = Gtk.ComboBoxText()
        self.album_combo.set_hexpand(True)
        self.batch_actions.append(self.album_combo)
        
        move_btn = Gtk.Button(label="Move Selected")
        move_btn.add_css_class("suggested-action")
        move_btn.connect("clicked", self.on_batch_move)
        self.batch_actions.append(move_btn)
        
        delete_btn = Gtk.Button(label="Delete Selected")
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self.on_batch_delete)
        self.batch_actions.append(delete_btn)
        
        self.append(self.batch_actions)
        
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer.set_margin_top(8)
        
        self.prev_btn = Gtk.Button()
        self.prev_btn.set_icon_name("go-previous-symbolic")
        self.prev_btn.connect("clicked", self.on_prev_page)
        
        self.page_lbl = Gtk.Label(label="Page 1 of 1")
        self.page_lbl.set_hexpand(True)
        
        # Page size selector
        ps_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        ps_lbl = Gtk.Label(label="Per page:")
        ps_lbl.add_css_class("dim-label")
        ps_lbl.add_css_class("caption")
        ps_box.append(ps_lbl)
        
        self.page_size_combo = Gtk.ComboBoxText()
        for opt in PAGE_SIZE_OPTIONS:
            self.page_size_combo.append(str(opt), str(opt))
        self.page_size_combo.set_active_id(str(self.page_size))
        self.page_size_combo.connect("changed", self.on_page_size_changed)
        ps_box.append(self.page_size_combo)
        
        self.next_btn = Gtk.Button()
        self.next_btn.set_icon_name("go-next-symbolic")
        self.next_btn.connect("clicked", self.on_next_page)
        
        footer.append(self.prev_btn)
        footer.append(self.page_lbl)
        footer.append(ps_box)
        footer.append(self.next_btn)
        self.append(footer)
        
        if self.drive:
            self.populate_albums_dropdown()
            
    def on_flowbox_child_activated(self, flowbox, child):
        card = child.get_child()
        if card and hasattr(card, "item"):
            self.open_item(card.item)

    def open_item(self, item):
        get_router().navigate("/media_detail", {"item": item, "drive": self.drive, "album_id": self.filter_album_id})
            
    def populate_albums_dropdown(self):
        if not self.drive:
            return
        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            return
            
        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM albums ORDER BY name ASC")
            albums = cursor.fetchall()
            
            self.album_combo.remove_all()
            for alb in albums:
                display_name = "Unsorted Media" if alb["name"] == "unknown" else alb["name"]
                self.album_combo.append(str(alb["id"]), display_name)
            self.album_combo.set_active(0)
            conn.close()
        except Exception as e:
            print(f"[MediaGrid] Error loading albums dropdown: {e}")

    def load_data(self):
        while True:
            child = self.flow_box.get_first_child()
            if not child:
                break
            self.flow_box.remove(child)
            
        if not self.drive:
            self.page_lbl.set_text("No volume loaded.")
            return
            
        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            status_page = Adw.StatusPage()
            status_page.set_icon_name("system-search-symbolic")
            status_page.set_title("No Catalog Found")
            status_page.set_description("Scan this storage volume in Discover Scan to view media.")
            self.flow_box.append(status_page)
            self.page_lbl.set_text("Scaffold database first.")
            return
            
        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()
            
            sql = """
                SELECT m.*, a.name AS album_name, a.relative_path AS album_relative_path
                FROM media_items m
                LEFT JOIN albums a ON m.album_id = a.id
                WHERE 1=1
            """
            count_sql = "SELECT count(*) as count FROM media_items m WHERE 1=1"
            params = []
            
            if self.filter_album_id is not None:
                sql += " AND m.album_id = ?"
                count_sql += " AND m.album_id = ?"
                params.append(self.filter_album_id)
                
            if self.search_query:
                term = f"%{self.search_query}%"
                sql += " AND (m.original_relative_path LIKE ? OR m.current_relative_path LIKE ?)"
                count_sql += " AND (m.original_relative_path LIKE ? OR m.current_relative_path LIKE ?)"
                params.extend([term, term])
                
            if self.filter_type == "images":
                sql += " AND m.mime_type LIKE 'image/%'"
                count_sql += " AND m.mime_type LIKE 'image/%'"
            elif self.filter_type == "videos":
                sql += " AND m.mime_type LIKE 'video/%'"
                count_sql += " AND m.mime_type LIKE 'video/%'"
                
            cursor.execute(count_sql, params)
            self.total_count = cursor.fetchone()["count"]
            
            order_col = "m.created_at"
            if self.sort_by == "name":
                order_col = "m.original_relative_path"
            elif self.sort_by == "size":
                order_col = "m.file_size"
                
            direction = "ASC" if self.sort_order == "asc" else "DESC"
            sql += f" ORDER BY {order_col} {direction} LIMIT ? OFFSET ?"
            params.extend([self.page_size, self.current_page * self.page_size])
            
            cursor.execute(sql, params)
            items = cursor.fetchall()
            
            for item in items:
                card = MediaCard(item, self.drive["path"], self.open_item, self.on_card_selection_changed)
                if item["id"] in self.selected_ids:
                    card.checkbox.set_active(True)
                self.flow_box.append(card)
                
            total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
            self.page_lbl.set_text(f"Page {self.current_page + 1} of {total_pages} (Total: {self.total_count})")
            
            self.prev_btn.set_sensitive(self.current_page > 0)
            self.next_btn.set_sensitive(self.current_page < total_pages - 1)
            
            conn.close()
        except Exception as e:
            print(f"[MediaGrid] SQL Query failed: {e}")
            self.page_lbl.set_text("Query error: database connection locked.")
            
    def on_search_changed(self, entry):
        self.search_query = entry.get_text().strip()
        self.current_page = 0
        self.load_data()
        
    def on_type_changed(self, combo):
        self.filter_type = combo.get_active_id()
        self.current_page = 0
        self.load_data()
        
    def on_sort_changed(self, combo):
        self.sort_by = combo.get_active_id()
        self.current_page = 0
        self.load_data()
        
    def on_order_toggled(self, btn):
        self.sort_order = "asc" if self.sort_order == "desc" else "desc"
        self.current_page = 0
        self.load_data()

    def on_page_size_changed(self, combo):
        val = combo.get_active_id()
        if val:
            self.page_size = int(val)
            self.current_page = 0
            self.load_data()
        
    def on_prev_page(self, btn):
        if self.current_page > 0:
            self.current_page -= 1
            self.load_data()
            
    def on_next_page(self, btn):
        total_pages = (self.total_count + self.page_size - 1) // self.page_size
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.load_data()
            
    def on_card_selection_changed(self, item_id, is_selected):
        if is_selected:
            self.selected_ids.add(item_id)
        else:
            self.selected_ids.discard(item_id)
            
        count = len(self.selected_ids)
        self.selection_lbl.set_text(f"Selected: {count} items")
        self.batch_actions.set_visible(count > 0)
        
    def on_batch_move(self, btn):
        target_album_id_str = self.album_combo.get_active_id()
        if not target_album_id_str or not self.selected_ids or not self.drive:
            return
            
        target_album_id = int(target_album_id_str)
        media_ids = list(self.selected_ids)
        
        def run_move():
            db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
            conn = None
            try:
                conn = get_database_connection(db_path)
                cursor = conn.cursor()
                
                cursor.execute("SELECT name, relative_path FROM albums WHERE id = ?", (target_album_id,))
                alb = cursor.fetchone()
                if not alb:
                    return
                
                dest_dir = os.path.join(self.drive["path"], "albums", alb["name"])
                os.makedirs(dest_dir, exist_ok=True)
                
                for m_id in media_ids:
                    cursor.execute("SELECT current_relative_path, mime_type FROM media_items WHERE id = ?", (m_id,))
                    item = cursor.fetchone()
                    if not item:
                        continue
                        
                    src_full = os.path.join(self.drive["path"], item["current_relative_path"])
                    if not os.path.exists(src_full):
                        cursor.execute("UPDATE media_items SET album_id = ? WHERE id = ?", (target_album_id, m_id))
                        continue
                        
                    filename = os.path.basename(item["current_relative_path"])
                    base, ext = os.path.splitext(filename)
                    
                    target_full = os.path.join(dest_dir, filename)
                    if os.path.exists(target_full):
                        counter = 1
                        while os.path.exists(os.path.join(dest_dir, f"{base}_{counter}{ext}")):
                            counter += 1
                        target_full = os.path.join(dest_dir, f"{base}_{counter}{ext}")
                        
                    if os.path.abspath(src_full) == os.path.abspath(target_full):
                        cursor.execute("UPDATE media_items SET album_id = ? WHERE id = ?", (target_album_id, m_id))
                        continue
                        
                    from core.file_ops import move_file
                    move_file(src_full, target_full)
                    new_rel = os.path.relpath(target_full, self.drive["path"])
                    
                    cursor.execute(
                        "UPDATE media_items SET album_id = ?, current_relative_path = ? WHERE id = ?",
                        (target_album_id, new_rel, m_id)
                    )
                
                conn.commit()
            except Exception as e:
                print(f"[BatchMove] Move failed: {e}")
            finally:
                if conn:
                    conn.close()
                    
            def on_finished():
                self.selected_ids.clear()
                self.batch_actions.set_visible(False)
                self.load_data()
                self.populate_albums_dropdown()
                
            GLib.idle_add(on_finished)
            
        threading.Thread(target=run_move, daemon=True).start()
        
    def on_batch_delete(self, btn):
        if not self.selected_ids or not self.drive:
            return
            
        media_ids = list(self.selected_ids)
        
        def run_delete():
            db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
            conn = None
            try:
                conn = get_database_connection(db_path)
                cursor = conn.cursor()
                
                for m_id in media_ids:
                    cursor.execute("SELECT current_relative_path, file_hash FROM media_items WHERE id = ?", (m_id,))
                    item = cursor.fetchone()
                    if not item:
                        continue
                        
                    orig_path = os.path.join(self.drive["path"], item["current_relative_path"])
                    if os.path.exists(orig_path):
                        try:
                            os.remove(orig_path)
                        except OSError:
                            pass
                            
                    thumb_path = os.path.join(self.drive["path"], "albums", "thumbs", f"{item['file_hash']}.jpg")
                    if os.path.exists(thumb_path):
                        try:
                            os.remove(thumb_path)
                        except OSError:
                            pass
                            
                    cursor.execute("DELETE FROM media_items WHERE id = ?", (m_id,))
                
                conn.commit()
            except Exception as e:
                print(f"[BatchDelete] Delete failed: {e}")
            finally:
                if conn:
                    conn.close()
                    
            def on_finished():
                self.selected_ids.clear()
                self.batch_actions.set_visible(False)
                self.load_data()
                self.populate_albums_dropdown()
                
            GLib.idle_add(on_finished)
            
        threading.Thread(target=run_delete, daemon=True).start()
