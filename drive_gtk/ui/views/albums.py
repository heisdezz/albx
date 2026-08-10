import os
import sqlite3
from gi.repository import Gtk, Gdk, GLib, Adw
from core.database import open_readable_db, get_database_connection, assert_writable
from router import get_router

def escape_markup(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""))

class AlbumCard(Gtk.Box):
    def __init__(self, album, drive_path, on_clicked_callback):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.album = album
        self.drive_path = drive_path
        self.on_clicked = on_clicked_callback
        
        self.add_css_class("media-card")
        self.set_size_request(140, 160)
        self.build_ui()
        
    def build_ui(self):
        img = Gtk.Image()
        img.set_pixel_size(96)
        img.set_size_request(130, 96)
        img.set_valign(Gtk.Align.CENTER)
        img.set_halign(Gtk.Align.CENTER)
        
        preview = self.album.get("preview_item")
        if preview and os.path.exists(os.path.join(self.drive_path, "albums", "thumbs", f"{preview['file_hash']}.jpg")):
            thumb_path = os.path.join(self.drive_path, "albums", "thumbs", f"{preview['file_hash']}.jpg")
            img.set_from_file(thumb_path)
        else:
            img.set_from_icon_name("folder-symbolic")
            
        self.append(img)
        
        display_name = "Unsorted Media" if self.album["name"] == "unknown" else self.album["name"]
        name_lbl = Gtk.Label()
        name_lbl.set_markup(f"<b>{escape_markup(display_name)}</b>")
        name_lbl.set_halign(Gtk.Align.CENTER)
        name_lbl.set_ellipsize(3)
        self.append(name_lbl)
        
        count_lbl = Gtk.Label(label=f"{self.album['media_count']} items")
        count_lbl.add_css_class("dim-label")
        count_lbl.set_halign(Gtk.Align.CENTER)
        self.append(count_lbl)
        
        click_gesture = Gtk.GestureClick()
        click_gesture.connect("released", lambda gesture, n, x, y: self.on_clicked(self.album))
        self.add_controller(click_gesture)

class AlbumsView(Gtk.Box):
    def __init__(self, parent_window, drive):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.parent_window = parent_window
        self.drive = drive
        
        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        
        self.build_ui()
        if self.drive:
            self.load_data()
        
    def build_ui(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label()
        title.set_markup("<span size='xx-large' weight='black'>Album Directories</span>")
        title.set_halign(Gtk.Align.START)
        
        subtitle = Gtk.Label(label="Organized subfolders traveling with the physical media drive.")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        
        title_box.append(title)
        title_box.append(subtitle)
        header.append(title_box)
        
        create_btn = Gtk.Button(label="New Album")
        create_btn.add_css_class("suggested-action")
        create_btn.set_valign(Gtk.Align.CENTER)
        create_btn.set_halign(Gtk.Align.END)
        create_btn.set_hexpand(True)
        create_btn.connect("clicked", self.on_new_album_clicked)
        header.append(create_btn)
        
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
                ORDER BY a.name ASC
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
            
            for alb_row in raw_albums:
                album = dict(alb_row)
                album["preview_item"] = previews.get(album["id"])
                
                card = AlbumCard(album, self.drive["path"], self.on_card_clicked)
                self.flow_box.append(card)
                
            conn.close()
        except Exception as e:
            print(f"[AlbumsView] Load failed: {e}")
            
    def on_card_clicked(self, album):
        get_router().navigate("/media", {"drive": self.drive, "album_id": album["id"]})
        
    def on_new_album_clicked(self, btn):
        if not self.drive:
            return
        dialog = Gtk.Window(title="Create New Album", modal=True, transient_for=self.parent_window)
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
            
            if not name or "/" in name or "\\" in name or ".." in name:
                err_dialog = Gtk.AlertDialog.new()
                err_dialog.set_message("Invalid Album Name")
                err_dialog.set_detail("Name cannot contain slashes or relative path segments.")
                err_dialog.show(dialog)
                return
                
            db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
            conn = None
            try:
                assert_writable(self.drive["path"])
                conn = get_database_connection(db_path)
                cursor = conn.cursor()
                
                cursor.execute("SELECT id FROM albums WHERE name = ?", (name,))
                if cursor.fetchone():
                    err_dialog = Gtk.AlertDialog.new()
                    err_dialog.set_message("Album Already Exists")
                    err_dialog.set_detail(f"An album folder named '{name}' is already defined.")
                    err_dialog.show(dialog)
                    return
                    
                cursor.execute(
                    "INSERT INTO albums (name, relative_path, description) VALUES (?, ?, ?)",
                    (name, f"albums/{name}", desc or None)
                )
                conn.commit()
                
                album_path = os.path.join(self.drive["path"], "albums", name)
                os.makedirs(album_path, exist_ok=True)
                
                dialog.close()
                self.load_data()
            except Exception as err:
                print(f"[AlbumsView] Save album failed: {err}")
            finally:
                if conn:
                    conn.close()
                    
        create_btn.connect("clicked", save_album)
        
        btn_box.append(cancel_btn)
        btn_box.append(create_btn)
        main_box.append(btn_box)
        
        dialog.show()
