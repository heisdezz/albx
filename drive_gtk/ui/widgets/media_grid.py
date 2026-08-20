"""Reusable media grid widget for the GTK UI.

A filterable, sortable, searchable, paginated grid of :class:`MediaCard`s
with a selection mode and batch move/delete actions. Used as the standalone
media view and embedable elsewhere.
"""

import os
import sqlite3
import threading

from gi.repository import Adw, GLib, Gtk
from router import get_router

from core.database import get_database_connection, open_readable_db
from ui.views.settings import PAGE_SIZE_OPTIONS, get_page_size
from ui.widgets.filter_bar import FilterBar
from ui.widgets.media_card import MediaCard


class MoveToAlbumDialog(Gtk.Window):
    def __init__(self, parent_window, albums, callback, title="Move Selected Items", button_label="Move Items"):
        super().__init__(
            transient_for=parent_window,
            modal=True,
            title=title,
            destroy_with_parent=True,
        )
        self.set_default_size(360, 450)
        self.albums = albums
        self.callback = callback
        self.dialog_title = title
        self.button_label = button_label
        self.selected_album = None
        self.build_ui()

    def build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        self.set_child(main_box)

        # Title
        title_lbl = Gtk.Label()
        title_lbl.set_markup(f"<span size='large' weight='black' foreground='#818cf8'>📁 {self.dialog_title}</span>")
        title_lbl.set_halign(Gtk.Align.START)
        main_box.append(title_lbl)

        # Search Bar
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search albums...")
        self.search_entry.connect("search-changed", self.on_search_changed)
        main_box.append(self.search_entry)

        # ScrolledWindow for the list of albums
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        main_box.append(scroll)

        # ListBox to list the albums
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect("row-activated", self.on_row_activated)
        scroll.set_child(self.list_box)

        self.populate_list()

        # Action Buttons (Cancel / Confirm)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_box.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda x: self.close())
        btn_box.append(cancel_btn)

        self.confirm_btn = Gtk.Button(label=self.button_label)
        self.confirm_btn.add_css_class("suggested-action")
        self.confirm_btn.connect("clicked", self.on_confirm_clicked)
        btn_box.append(self.confirm_btn)

        main_box.append(btn_box)

    def populate_list(self):
        # Clear existing rows
        while True:
            row = self.list_box.get_first_child()
            if not row:
                break
            self.list_box.remove(row)

        search_term = self.search_entry.get_text().lower().strip()

        for a in self.albums:
            display_name = "Unsorted Media" if a["name"] == "unknown" else a["name"]
            if search_term and search_term not in display_name.lower():
                continue

            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)

            icon = Gtk.Image.new_from_icon_name("folder-symbolic")
            row_box.append(icon)

            lbl = Gtk.Label(label=display_name)
            lbl.set_halign(Gtk.Align.START)
            row_box.append(lbl)

            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            # Store album data on the row
            row.album_data = a

            self.list_box.append(row)

    def on_search_changed(self, entry):
        self.populate_list()

    def on_row_activated(self, listbox, row):
        if row and hasattr(row, "album_data"):
            self.selected_album = row.album_data
            self.on_confirm_clicked(None)

    def on_confirm_clicked(self, btn):
        selected_row = self.list_box.get_selected_row()
        if selected_row and hasattr(selected_row, "album_data"):
            self.selected_album = selected_row.album_data
            self.close()
            # Trigger callback with selected album data
            self.callback(self.selected_album)
        else:
            dialog = Gtk.AlertDialog()
            dialog.set_message("No Selection")
            dialog.set_detail("Please select a target album to move files to.")
            dialog.show(self)


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
        self.select_mode = False
        self.selected_ids = set()
        self.card_by_id = {}

        self.filter_bar = FilterBar(
            on_filters_changed=self.on_filters_changed,
            on_select_toggled=self.on_select_mode_changed,
            on_select_all=self.on_select_all,
        )

        self.build_ui()
        if self.drive:
            self.load_data()

    def build_ui(self):
        self.append(self.filter_bar)

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

        # Add drag gesture for drag-selection
        self.drag_gesture = Gtk.GestureDrag.new()
        self.drag_gesture.connect("drag-begin", self.on_drag_begin)
        self.drag_gesture.connect("drag-update", self.on_drag_update)
        self.drag_gesture.connect("drag-end", self.on_drag_end)
        self.flow_box.add_controller(self.drag_gesture)

        self.batch_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.batch_actions.add_css_class("card")
        self.batch_actions.set_visible(False)
        self.batch_actions.set_margin_top(8)

        self.selection_lbl = Gtk.Label(label="Selected: 0 items")
        self.selection_lbl.set_halign(Gtk.Align.START)
        self.selection_lbl.set_hexpand(True)
        self.batch_actions.append(self.selection_lbl)

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

    # --- card activation -----------------------------------------------------

    def on_flowbox_child_activated(self, flowbox, child):
        card = child.get_child()
        if card and hasattr(card, "item"):
            self.on_card_activated(card.item)

    def on_card_activated(self, item):
        if self.select_mode:
            self.toggle_item_selection(item["id"])
        else:
            self.open_item(item)

    def open_item(self, item):
        get_router().navigate(
            "/media_detail",
            {"item": item, "drive": self.drive, "album_id": self.filter_album_id},
        )

    # --- selection -----------------------------------------------------------

    def toggle_item_selection(self, item_id):
        if item_id in self.selected_ids:
            self.selected_ids.discard(item_id)
            selected = False
        else:
            self.selected_ids.add(item_id)
            selected = True
        card = self.card_by_id.get(item_id)
        if card:
            card.set_selected(selected)
        self.update_selection_ui()
        self.update_select_all_label()

    def on_select_mode_changed(self, active):
        self.select_mode = active
        self.selected_ids.clear()
        for card in self.visible_cards():
            card.set_select_mode(active)
        self.update_selection_ui()
        self.update_select_all_label()

    def on_select_all(self):
        ids = [card.item["id"] for card in self.visible_cards()]
        if not ids:
            return
        if all(i in self.selected_ids for i in ids):
            self.selected_ids.difference_update(ids)
        else:
            self.selected_ids.update(ids)
        for card in self.visible_cards():
            card.set_selected(card.item["id"] in self.selected_ids)
        self.update_selection_ui()
        self.update_select_all_label()

    def visible_cards(self):
        cards = []
        child = self.flow_box.get_first_child()
        while child is not None:
            # Flow box children are always GtkFlowBoxChild wrappers; guard
            # anyway so non-card children (e.g. the status page) are skipped.
            get_child = getattr(child, "get_child", None)
            card = get_child() if get_child else None
            if card is not None and hasattr(card, "item"):
                cards.append(card)
            child = child.get_next_sibling()
        return cards

    def update_select_all_label(self):
        ids = [card.item["id"] for card in self.visible_cards()]
        all_selected = bool(ids) and all(i in self.selected_ids for i in ids)
        self.filter_bar.set_select_all_label(
            "Deselect All" if all_selected else "Select All"
        )

    def update_selection_ui(self):
        count = len(self.selected_ids)
        self.selection_lbl.set_text(f"Selected: {count} items")
        self.batch_actions.set_visible(self.select_mode and count > 0)

    # --- filters -------------------------------------------------------------

    def on_filters_changed(self):
        self.current_page = 0
        self.load_data()

    # --- data ----------------------------------------------------------------

    def load_data(self):
        while True:
            child = self.flow_box.get_first_child()
            if not child:
                break
            self.flow_box.remove(child)
        self.card_by_id.clear()

        if not self.drive:
            self.page_lbl.set_text("No volume loaded.")
            return

        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            status_page = Adw.StatusPage()
            status_page.set_icon_name("system-search-symbolic")
            status_page.set_title("No Catalog Found")
            status_page.set_description(
                "Scan this storage volume in Discover Scan to view media."
            )
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

            if self.filter_bar.search_query:
                term = f"%{self.filter_bar.search_query}%"
                sql += " AND (m.original_relative_path LIKE ? OR m.current_relative_path LIKE ?)"
                count_sql += " AND (m.original_relative_path LIKE ? OR m.current_relative_path LIKE ?)"
                params.extend([term, term])

            if self.filter_bar.filter_type == "images":
                sql += " AND m.mime_type LIKE 'image/%'"
                count_sql += " AND m.mime_type LIKE 'image/%'"
            elif self.filter_bar.filter_type == "videos":
                sql += " AND m.mime_type LIKE 'video/%'"
                count_sql += " AND m.mime_type LIKE 'video/%'"

            cursor.execute(count_sql, params)
            self.total_count = cursor.fetchone()["count"]

            order_col = "m.created_at"
            if self.filter_bar.sort_by == "name":
                order_col = "m.original_relative_path"
            elif self.filter_bar.sort_by == "size":
                order_col = "m.file_size"

            direction = "ASC" if self.filter_bar.sort_order == "asc" else "DESC"
            sql += f" ORDER BY {order_col} {direction} LIMIT ? OFFSET ?"
            params.extend([self.page_size, self.current_page * self.page_size])

            cursor.execute(sql, params)
            items = cursor.fetchall()

            for item in items:
                card = MediaCard(
                    item, self.drive["path"], self.on_card_selection_changed
                )
                self.card_by_id[item["id"]] = card
                card.set_select_mode(self.select_mode)
                card.set_selected(item["id"] in self.selected_ids)
                self.flow_box.append(card)

            total_pages = max(
                1, (self.total_count + self.page_size - 1) // self.page_size
            )
            self.page_lbl.set_text(
                f"Page {self.current_page + 1} of {total_pages} (Total: {self.total_count})"
            )

            self.prev_btn.set_sensitive(self.current_page > 0)
            self.next_btn.set_sensitive(self.current_page < total_pages - 1)

            conn.close()
        except Exception as e:
            print(f"[MediaGrid] SQL Query failed: {e}")
            self.page_lbl.set_text("Query error: database connection locked.")

        self.update_select_all_label()

    # --- pagination ----------------------------------------------------------

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
        self.update_selection_ui()
        self.update_select_all_label()

    # --- drag selection gestures ---------------------------------------------

    def on_drag_begin(self, gesture, start_x, start_y):
        self.drag_start_x = start_x
        self.drag_start_y = start_y
        self.drag_initial_selected = set(self.selected_ids)
        self.drag_in_progress = False

    def on_drag_update(self, gesture, offset_x, offset_y):
        if not self.drive:
            return

        # Use a threshold (e.g. 8 pixels) to distinguish drag from click
        if not self.drag_in_progress:
            if abs(offset_x) > 8 or abs(offset_y) > 8:
                self.drag_in_progress = True
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                if not self.select_mode:
                    self.filter_bar.set_select_mode(True)
            else:
                return

        cur_x = self.drag_start_x + offset_x
        cur_y = self.drag_start_y + offset_y

        x_min = min(self.drag_start_x, cur_x)
        x_max = max(self.drag_start_x, cur_x)
        y_min = min(self.drag_start_y, cur_y)
        y_max = max(self.drag_start_y, cur_y)

        # Check intersection for each child of FlowBox
        child = self.flow_box.get_first_child()
        while child is not None:
            if hasattr(child, "get_child"):
                card = child.get_child()
                if card and hasattr(card, "item"):
                    item_id = card.item["id"]
                    alloc = child.get_allocation()

                    # Check if alloc bounds intersect drag selection rectangle
                    ax_min = alloc.x
                    ax_max = alloc.x + alloc.width
                    ay_min = alloc.y
                    ay_max = alloc.y + alloc.height

                    intersects = not (ax_max < x_min or ax_min > x_max or ay_max < y_min or ay_min > y_max)

                    if intersects:
                        if item_id not in self.selected_ids:
                            self.selected_ids.add(item_id)
                            card.set_selected(True)
                    else:
                        # Restore original state
                        if item_id in self.drag_initial_selected:
                            if item_id not in self.selected_ids:
                                self.selected_ids.add(item_id)
                                card.set_selected(True)
                        else:
                            if item_id in self.selected_ids:
                                self.selected_ids.discard(item_id)
                                card.set_selected(False)
            child = child.get_next_sibling()

        self.update_selection_ui()
        self.update_select_all_label()

    def on_drag_end(self, gesture, offset_x, offset_y):
        self.drag_in_progress = False
        self.drag_initial_selected = None

    # --- batch actions -------------------------------------------------------

    def on_batch_move(self, btn):
        if not self.selected_ids or not self.drive:
            return

        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            return

        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, relative_path FROM albums ORDER BY name ASC")
            rows = cursor.fetchall()
            conn.close()

            albums = [{"id": r[0], "name": r[1], "relative_path": r[2]} for r in rows]
        except Exception as e:
            print(f"[MediaGrid] Error loading albums for dialog: {e}")
            return

        def on_album_selected(target_album):
            if not target_album:
                return
            self.run_batch_move(target_album["id"])

        dialog = MoveToAlbumDialog(self.parent_window, albums, on_album_selected)
        dialog.show()

    def run_batch_move(self, target_album_id):
        media_ids = list(self.selected_ids)

        def run_move():
            db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
            conn = None
            try:
                conn = get_database_connection(db_path)
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT name, relative_path FROM albums WHERE id = ?",
                    (target_album_id,),
                )
                alb = cursor.fetchone()
                if not alb:
                    return

                dest_dir = os.path.join(self.drive["path"], "albums", alb["name"])
                os.makedirs(dest_dir, exist_ok=True)

                for m_id in media_ids:
                    cursor.execute(
                        "SELECT current_relative_path, mime_type FROM media_items WHERE id = ?",
                        (m_id,),
                    )
                    item = cursor.fetchone()
                    if not item:
                        continue

                    src_full = os.path.join(
                        self.drive["path"], item["current_relative_path"]
                    )
                    if not os.path.exists(src_full):
                        cursor.execute(
                            "UPDATE media_items SET album_id = ? WHERE id = ?",
                            (target_album_id, m_id),
                        )
                        continue

                    filename = os.path.basename(item["current_relative_path"])
                    base, ext = os.path.splitext(filename)

                    target_full = os.path.join(dest_dir, filename)
                    if os.path.exists(target_full):
                        counter = 1
                        while os.path.exists(
                            os.path.join(dest_dir, f"{base}_{counter}{ext}")
                        ):
                            counter += 1
                        target_full = os.path.join(dest_dir, f"{base}_{counter}{ext}")

                    if os.path.abspath(src_full) == os.path.abspath(target_full):
                        cursor.execute(
                            "UPDATE media_items SET album_id = ? WHERE id = ?",
                            (target_album_id, m_id),
                        )
                        continue

                    from core.file_ops import move_file

                    move_file(src_full, target_full)
                    new_rel = os.path.relpath(target_full, self.drive["path"])

                    cursor.execute(
                        "UPDATE media_items SET album_id = ?, current_relative_path = ? WHERE id = ?",
                        (target_album_id, new_rel, m_id),
                    )

                conn.commit()
            except Exception as e:
                print(f"[BatchMove] Move failed: {e}")
            finally:
                if conn:
                    conn.close()

            def on_finished():
                self.filter_bar.exit_select_mode()
                self.load_data()

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
                    cursor.execute(
                        "SELECT current_relative_path, file_hash FROM media_items WHERE id = ?",
                        (m_id,),
                    )
                    item = cursor.fetchone()
                    if not item:
                        continue

                    orig_path = os.path.join(
                        self.drive["path"], item["current_relative_path"]
                    )
                    if os.path.exists(orig_path):
                        try:
                            os.remove(orig_path)
                        except OSError:
                            pass

                    thumb_path = os.path.join(
                        self.drive["path"],
                        "albums",
                        "thumbs",
                        f"{item['file_hash']}.jpg",
                    )
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
                self.filter_bar.exit_select_mode()
                self.load_data()

            GLib.idle_add(on_finished)

        threading.Thread(target=run_delete, daemon=True).start()
