import os
import threading

from gi.repository import Adw, GLib, Gtk
from router import get_router

from core.database import assert_writable, open_readable_db
from core.media_ops import (
    _validate_album_name,
    create_album,
    delete_album,
    list_albums,
    merge_albums,
    rename_album,
    validate_album_files,
)
from ui.widgets.media_grid import MoveToAlbumDialog


def escape_markup(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""))


def display_name_for(name: str) -> str:
    return "Unsorted Media" if name == "unknown" else name


class AlbumCard(Gtk.Box):
    def __init__(self, album, drive_path, on_clicked_callback, on_menu_callback=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.album = album
        self.drive_path = drive_path
        self.on_clicked = on_clicked_callback
        self.on_menu = on_menu_callback

        self.add_css_class("card")
        self.set_size_request(200, 220)
        self.set_cursor_from_name("pointer")

        self.build_ui()

    def build_ui(self):
        overlay = Gtk.Overlay()
        overlay.set_size_request(180, 140)

        # Base container for picture or placeholder icon
        self.pic_container = Gtk.Box()
        self.pic_container.set_size_request(180, 140)
        self.pic_container.add_css_class("card")
        self.pic_container.set_halign(Gtk.Align.FILL)
        self.pic_container.set_valign(Gtk.Align.FILL)

        preview = self.album.get("preview_item")
        has_preview = False

        if preview:
            file_hash = preview.get("file_hash")
            thumb_path = os.path.join(
                self.drive_path, "albums", "thumbs", f"{file_hash}.jpg"
            )
            media_path = os.path.join(
                self.drive_path, preview.get("current_relative_path", "")
            )

            load_target = None
            if os.path.exists(thumb_path):
                load_target = thumb_path
            elif os.path.exists(media_path) and preview.get("mime_type", "").startswith(
                "image/"
            ):
                load_target = media_path

            if load_target:
                picture = Gtk.Picture.new_for_filename(load_target)
                picture.set_content_fit(Gtk.ContentFit.COVER)
                self.pic_container.append(picture)
                has_preview = True

        if not has_preview:
            placeholder = Gtk.Image.new_from_icon_name("folder-symbolic")
            placeholder.set_pixel_size(48)
            placeholder.set_halign(Gtk.Align.CENTER)
            placeholder.set_valign(Gtk.Align.CENTER)
            placeholder.set_hexpand(True)
            placeholder.set_vexpand(True)
            self.pic_container.append(placeholder)

        overlay.set_child(self.pic_container)

        # Context Menu Button (top-right overlay)
        if self.album["name"] != "unknown" and self.on_menu:
            menu_btn = Gtk.Button()
            menu_btn.set_icon_name("view-more-symbolic")
            menu_btn.add_css_class("osd")
            menu_btn.add_css_class("circular")
            menu_btn.set_halign(Gtk.Align.END)
            menu_btn.set_valign(Gtk.Align.START)
            menu_btn.set_margin_top(6)
            menu_btn.set_margin_end(6)
            menu_btn.connect("clicked", lambda btn: self.on_menu(btn, self.album))
            overlay.add_overlay(menu_btn)

        self.append(overlay)

        display_name = display_name_for(self.album["name"])
        name_lbl = Gtk.Label()
        name_lbl.set_markup(f"<b>{escape_markup(display_name)}</b>")
        name_lbl.set_halign(Gtk.Align.CENTER)
        name_lbl.set_ellipsize(3)
        self.append(name_lbl)

        count = self.album.get("media_count", 0)
        items_lbl = Gtk.Label(label=f"{count} {'item' if count == 1 else 'items'}")
        items_lbl.add_css_class("caption")
        items_lbl.set_halign(Gtk.Align.CENTER)
        self.append(items_lbl)

        # Click gesture opens the album
        click = Gtk.GestureClick.new()
        click.connect("pressed", self.on_card_pressed)
        self.add_controller(click)

    def on_card_pressed(self, gesture, n_press, x, y):
        # Don't trigger album navigation if the click landed on the context menu button
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if widget and (
            isinstance(widget, Gtk.Button)
            or widget.get_ancestor(Gtk.Button) is not None
        ):
            return
        if self.on_clicked:
            self.on_clicked(self.album)


class AlbumsView(Gtk.Box):
    def __init__(self, parent_window, drive=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.parent_window = parent_window
        self.drive = drive

        self.sort_by = "name"
        self.sort_order = "asc"

        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(24)
        self.set_margin_bottom(24)

        self.build_ui()
        self.load_data()

    def build_ui(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label()
        title.set_markup(
            "<span size='xx-large' weight='black'>Album Directories</span>"
        )
        title.set_halign(Gtk.Align.START)

        subtitle = Gtk.Label(
            label="Organized subfolders traveling with the physical media drive."
        )
        subtitle.add_css_class("dim-label")
        subtitle.set_halign(Gtk.Align.START)

        title_box.append(title)
        title_box.append(subtitle)
        header.append(title_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        # Controls (Search, Sort, Validate All, New Album)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search albums…")
        self.search_entry.connect("search-changed", self.on_search_changed)
        controls.append(self.search_entry)

        self.sort_combo = Gtk.DropDown.new_from_strings(
            ["Name", "Item Count", "Creation Date"]
        )
        self.sort_combo.connect("notify::selected", self.on_sort_changed)
        controls.append(self.sort_combo)

        self.order_btn = Gtk.Button()
        self.order_btn.set_icon_name("view-sort-ascending-symbolic")
        self.order_btn.set_tooltip_text("Toggle Sort Order")
        self.order_btn.connect("clicked", self.on_order_toggled)
        controls.append(self.order_btn)

        validate_all_btn = Gtk.Button(label="Validate All")
        validate_all_btn.set_icon_name("emblem-ok-symbolic")
        validate_all_btn.set_tooltip_text("Check all albums for missing files")
        validate_all_btn.connect("clicked", self.on_validate_all_clicked)
        controls.append(validate_all_btn)

        new_album_btn = Gtk.Button(label="New Album")
        new_album_btn.set_icon_name("list-add-symbolic")
        new_album_btn.add_css_class("suggested-action")
        new_album_btn.connect("clicked", self.on_new_album_clicked)
        controls.append(new_album_btn)

        header.append(controls)

        self.append(header)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(sep)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.flow_box = Gtk.FlowBox()
        self.flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow_box.set_row_spacing(16)
        self.flow_box.set_column_spacing(16)
        self.flow_box.set_max_children_per_line(8)
        self.flow_box.set_min_children_per_line(2)

        scroll.set_child(self.flow_box)
        self.append(scroll)

    # --- sorting -------------------------------------------------------------

    def on_search_changed(self, entry):
        self.load_data()

    def on_sort_changed(self, combo, param):
        idx = combo.get_selected()
        mapping = {0: "name", 1: "items", 2: "date"}
        self.sort_by = mapping.get(idx, "name")
        self.load_data()

    def on_order_toggled(self, btn):
        self.sort_order = "asc" if self.sort_order == "desc" else "desc"
        self.order_btn.set_icon_name(
            "view-sort-ascending-symbolic"
            if self.sort_order == "asc"
            else "view-sort-descending-symbolic"
        )
        self.load_data()

    # --- data ----------------------------------------------------------------

    def load_data(self):
        while True:
            child = self.flow_box.get_first_child()
            if not child:
                break
            self.flow_box.remove(child)

        if not self.drive:
            return

        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            status_page = Adw.StatusPage()
            status_page.set_icon_name("folder-symbolic")
            status_page.set_title("No Albums Initialized")
            status_page.set_description("Scan volume to index album directories.")
            self.flow_box.append(status_page)
            return

        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT a.id, a.name, a.relative_path, a.description, a.created_at,
                       COUNT(m.id) AS media_count
                FROM albums a
                LEFT JOIN media_items m ON m.album_id = a.id
                GROUP BY a.id
            """)
            raw_albums = cursor.fetchall()

            cursor.execute("""
                SELECT album_id, id, file_hash, original_relative_path, current_relative_path, mime_type
                FROM (
                    SELECT album_id, id, file_hash, original_relative_path, current_relative_path, mime_type,
                           ROW_NUMBER() OVER (PARTITION BY album_id ORDER BY created_at DESC, id DESC) AS rn
                    FROM media_items
                )
                WHERE rn = 1
            """)
            previews = {row["album_id"]: dict(row) for row in cursor.fetchall()}

            search_query = self.search_entry.get_text().strip().lower()

            albums = []
            for alb_row in raw_albums:
                album = dict(alb_row)
                album["display_name"] = display_name_for(album["name"])
                if search_query and search_query not in album["display_name"].lower():
                    continue
                album["preview_item"] = previews.get(album["id"])
                albums.append(album)

            desc = self.sort_order == "desc"
            if self.sort_by == "items":
                albums.sort(key=lambda a: a["media_count"], reverse=desc)
            elif self.sort_by == "date":
                albums.sort(key=lambda a: a["created_at"] or "", reverse=desc)
            else:
                albums.sort(
                    key=lambda a: (
                        a["name"] != "unknown",
                        a["display_name"].lower(),
                    ),
                    reverse=desc,
                )

            conn.close()

            for album in albums:
                card = AlbumCard(
                    album,
                    self.drive["path"],
                    self.on_album_clicked,
                    self.on_album_menu_clicked,
                )
                self.flow_box.append(card)

        except Exception as e:
            print(f"[AlbumsView] Error loading albums: {e}")

    # --- album navigation ----------------------------------------------------

    def on_album_clicked(self, album):
        get_router().navigate("/media", {"drive": self.drive, "album_id": album["id"]})

    # --- context menu --------------------------------------------------------

    def on_album_menu_clicked(self, btn, album):
        popover = Gtk.Popover()
        popover.set_parent(btn)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        rename_btn = Gtk.Button(label="Rename…")
        rename_btn.set_halign(Gtk.Align.FILL)
        rename_btn.connect(
            "clicked", lambda b: self._menu_action(popover, self.on_rename_album, album)
        )
        box.append(rename_btn)

        merge_btn = Gtk.Button(label="Merge Into…")
        merge_btn.set_halign(Gtk.Align.FILL)
        merge_btn.connect(
            "clicked", lambda b: self._menu_action(popover, self.on_merge_album, album)
        )
        box.append(merge_btn)

        validate_btn = Gtk.Button(label="Validate Files…")
        validate_btn.set_halign(Gtk.Align.FILL)
        validate_btn.connect(
            "clicked",
            lambda b: self._menu_action(popover, self.on_validate_album, album),
        )
        box.append(validate_btn)

        delete_btn = Gtk.Button(label="Delete…")
        delete_btn.set_halign(Gtk.Align.FILL)
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect(
            "clicked", lambda b: self._menu_action(popover, self.on_delete_album, album)
        )
        box.append(delete_btn)

        popover.set_child(box)
        popover.connect("closed", lambda p: p.unparent())
        popover.popup()

    def _menu_action(self, popover, handler, album):
        popover.popdown()
        handler(album)

    # --- validate ------------------------------------------------------------

    def on_validate_album(self, album):
        if not self.drive:
            return
        album_name = display_name_for(album["name"])

        def run():
            return validate_album_files(self.drive["path"], album["id"])

        def on_done(result):
            total, removed, errors = result
            self.load_data()
            if errors:
                self._alert("Validation Finished with Errors", "\n".join(errors))
            elif removed > 0:
                self._alert(
                    "Validation Complete",
                    f"Validated {total} files in '{album_name}'.\n"
                    f"Removed {removed} missing records from the database.",
                )
            else:
                self._alert(
                    "Validation Complete",
                    f"All {total} files in '{album_name}' exist and are verified.",
                )

        self._run_album_operation(run, on_done)

    def on_validate_all_clicked(self, btn):
        if not self.drive:
            return

        def run():
            return validate_album_files(self.drive["path"], None)

        def on_done(result):
            total, removed, errors = result
            self.load_data()
            if errors:
                self._alert("Validation Finished with Errors", "\n".join(errors))
            elif removed > 0:
                self._alert(
                    "Validation Complete",
                    f"Validated {total} files across all albums.\n"
                    f"Removed {removed} missing records from the database.",
                )
            else:
                self._alert(
                    "Validation Complete",
                    f"All {total} files across all albums exist and are verified.",
                )

        self._run_album_operation(run, on_done)

    # --- rename --------------------------------------------------------------

    def on_rename_album(self, album):
        if not self.drive:
            return
        dialog = Gtk.Window(
            title="Rename Album", modal=True, transient_for=self.parent_window
        )
        dialog.set_default_size(320, 160)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        dialog.set_child(main_box)

        hint = Gtk.Label()
        hint.set_markup(
            f"Rename <b>{escape_markup(display_name_for(album['name']))}</b>:"
        )
        hint.set_halign(Gtk.Align.START)
        main_box.append(hint)

        name_entry = Gtk.Entry()
        name_entry.set_text(album["name"])
        name_entry.set_placeholder_text("Album Name (e.g. Summer_2026)")
        main_box.append(name_entry)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda x: dialog.close())

        rename_btn = Gtk.Button(label="Rename")
        rename_btn.add_css_class("suggested-action")

        def save_rename(x):
            new_name = name_entry.get_text().strip()
            ok, err = _validate_album_name(new_name)
            if not ok:
                self._alert("Invalid Album Name", err)
                return
            success, err = rename_album(self.drive["path"], album["id"], new_name)
            if success:
                dialog.close()
                self.load_data()
            else:
                self._alert("Rename Failed", err)

        rename_btn.connect("clicked", save_rename)

        btn_box.append(cancel_btn)
        btn_box.append(rename_btn)
        main_box.append(btn_box)

        dialog.show()

    # --- merge ---------------------------------------------------------------

    def on_merge_album(self, album):
        if not self.drive:
            return
        all_albums = list_albums(self.drive["path"])
        # Filter out the source album
        candidates = [a for a in all_albums if a["id"] != album["id"]]
        if not candidates:
            self._alert("No Target Albums", "There are no other albums to merge into.")
            return

        def on_target_selected(target):
            if not target:
                return
            target_name = display_name_for(target["name"])
            source_name = display_name_for(album["name"])

            confirm = Gtk.AlertDialog()
            confirm.set_message(f"Merge '{source_name}' into '{target_name}'?")
            confirm.set_detail(
                f"All media items will be moved into '{target_name}'. "
                f"The album '{source_name}' will be removed."
            )
            confirm.set_buttons(["Cancel", "Merge Albums"])
            confirm.set_default_button(0)
            confirm.set_cancel_button(0)
            confirm.choose(
                self.parent_window,
                None,
                lambda d, res: self._on_merge_confirmed(
                    d, res, album["id"], target["id"]
                ),
            )

        dlg = MoveToAlbumDialog(
            parent_window=self.parent_window,
            albums=candidates,
            callback=on_target_selected,
            title=f"Merge '{display_name_for(album['name'])}' into…",
            button_label="Select Target Album",
        )
        dlg.present()

    def _on_merge_confirmed(self, dialog, result, src_id, tgt_id):
        if dialog.choose_finish(result) == 1:
            self._run_album_operation(
                lambda: merge_albums(self.drive["path"], src_id, tgt_id),
                self._finish_album_operation,
            )

    # --- delete --------------------------------------------------------------

    def on_delete_album(self, album):
        if not self.drive:
            return
        choice = Gtk.AlertDialog()
        choice.set_message(f"Delete '{display_name_for(album['name'])}'?")
        choice.set_detail(
            "Keep the media files (they will be moved to Unsorted Media) or "
            "permanently delete them from disk."
        )
        choice.set_buttons(["Keep Media Files", "Delete Files from Disk", "Cancel"])
        choice.set_default_button(2)
        choice.set_cancel_button(2)
        choice.choose(self.parent_window, None, self._on_delete_choice, album)

    def _on_delete_choice(self, dialog, result, album):
        response = dialog.choose_finish(result)
        if response == 0:
            self._run_album_operation(
                lambda: delete_album(self.drive["path"], album["id"], False),
                self._finish_album_operation,
            )
        elif response == 1:
            confirm = Gtk.AlertDialog()
            confirm.set_message("Permanently delete all files?")
            confirm.set_detail(
                "This cannot be undone. Every media file in this album will be "
                "removed from disk, along with its thumbnail."
            )
            confirm.set_buttons(["Cancel", "Delete Permanently"])
            confirm.set_default_button(0)
            confirm.set_cancel_button(0)
            confirm.choose(
                self.parent_window, None, self._on_permanent_delete_confirmed, album
            )

    def _on_permanent_delete_confirmed(self, dialog, result, album):
        response = dialog.choose_finish(result)
        if response == 1:
            self._run_album_operation(
                lambda: delete_album(self.drive["path"], album["id"], True),
                self._finish_album_operation,
            )

    # --- helpers -------------------------------------------------------------

    def _run_album_operation(self, op, on_done):
        def runner():
            try:
                result = op()
            except Exception as e:
                result = (False, str(e), [])
            GLib.idle_add(on_done, result)

        threading.Thread(target=runner, daemon=True).start()

    def _finish_album_operation(self, result):
        _, err, file_errs = result
        self.load_data()
        if err:
            self._alert("Operation Failed", err)
        elif file_errs:
            summary = "\n".join(file_errs[:8])
            if len(file_errs) > 8:
                summary += "\n…"
            self._alert("Completed with errors", summary)

    def _alert(self, message, detail):
        dialog = Gtk.AlertDialog()
        dialog.set_message(message)
        dialog.set_detail(detail)
        dialog.show(self.parent_window)

    def on_new_album_clicked(self, btn):
        if not self.drive:
            return
        dialog = Gtk.Window(
            title="Create New Album", modal=True, transient_for=self.parent_window
        )
        dialog.set_default_size(320, 200)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        dialog.set_child(main_box)

        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text("Album Name (e.g. Summer_2026)")
        main_box.append(name_entry)

        desc_entry = Gtk.Entry()
        desc_entry.set_placeholder_text("Description (optional)")
        main_box.append(desc_entry)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda x: dialog.close())

        create_btn = Gtk.Button(label="Create")
        create_btn.add_css_class("suggested-action")

        def save_album(x):
            name = name_entry.get_text().strip()
            desc = desc_entry.get_text().strip()

            ok, err = _validate_album_name(name)
            if not ok:
                err_dialog = Gtk.AlertDialog()
                err_dialog.set_message("Invalid Album Name")
                err_dialog.set_detail(err)
                err_dialog.show(dialog)
                return

            try:
                assert_writable(self.drive["path"])
                success, err = create_album(self.drive["path"], name, desc)
                if not success:
                    err_dialog = Gtk.AlertDialog()
                    err_dialog.set_message("Create Album Failed")
                    err_dialog.set_detail(err)
                    err_dialog.show(dialog)
                    return

                dialog.close()
                self.load_data()
            except Exception as err:
                print(f"[AlbumsView] Save album failed: {err}")

        create_btn.connect("clicked", save_album)

        btn_box.append(cancel_btn)
        btn_box.append(create_btn)
        main_box.append(btn_box)

        dialog.show()
