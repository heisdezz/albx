import os
import json
import threading
from gi.repository import Gtk, GLib, Adw
from core.gdrive import test_gdrive_connection, backup_to_gdrive
from core.database import create_backup, backup_dir_for
from ui.views.discover import load_ignore_list, save_ignore_list

DEFAULT_PAGE_SIZE = 24
PAGE_SIZE_OPTIONS = [12, 24, 48, 96]

def load_app_settings(drive_path: str) -> dict:
    """Load settings from the drive's settings JSON."""
    settings_file = os.path.join(drive_path, "albums", ".media_library_settings.json")
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def get_page_size(drive_path: str) -> int:
    """Read the saved items-per-page from settings, fallback to 24."""
    data = load_app_settings(drive_path)
    return data.get("itemsPerPage", DEFAULT_PAGE_SIZE)

def escape_markup(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""))

class SettingsView(Gtk.Box):
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
            self.load_settings()
            self.load_backups_list()
        
    def build_ui(self):
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label()
        title.set_markup("<span size='xx-large' weight='black'>System Settings</span>")
        title.set_halign(Gtk.Align.START)
        
        subtitle = Gtk.Label(label="Manage Google Drive cloud backups, credentials, and local snapshots.")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        
        title_box.append(title)
        title_box.append(subtitle)
        self.append(title_box)
        
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(sep)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        
        clamp = Adw.Clamp()
        clamp.set_maximum_size(800)
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        layout.set_margin_start(8)
        layout.set_margin_end(8)
        layout.set_margin_top(8)
        layout.set_margin_bottom(24)
        clamp.set_child(layout)
        scroll.set_child(clamp)
        self.append(scroll)
        
        # DISPLAY PREFERENCES PANEL
        display_group = Adw.PreferencesGroup()
        display_group.set_title("Display Preferences")
        display_group.set_description("Configure default gallery and pagination settings.")
        
        page_size_row = Adw.ActionRow()
        page_size_row.set_title("Items Per Page")
        page_size_row.set_subtitle("Default number of media items shown per page in the gallery.")
        page_size_row.add_prefix(Gtk.Image.new_from_icon_name("view-grid-symbolic"))
        
        self.page_size_combo = Gtk.ComboBoxText()
        for opt in PAGE_SIZE_OPTIONS:
            self.page_size_combo.append(str(opt), str(opt))
        self.page_size_combo.set_valign(Gtk.Align.CENTER)
        self.page_size_combo.connect("changed", self.on_page_size_changed)
        page_size_row.add_suffix(self.page_size_combo)
        
        display_group.add(page_size_row)
        layout.append(display_group)
        
        # GOOGLE DRIVE PANEL
        gdrive_group = Adw.PreferencesGroup()
        gdrive_group.set_title("Google Drive Configuration")
        gdrive_group.set_description("Upload SQLite catalog database snapshots to the cloud using a Google Service Account.")
        
        json_lbl = Gtk.Label(label="Service Account credentials JSON:")
        json_lbl.set_halign(Gtk.Align.START)
        
        json_scroll = Gtk.ScrolledWindow()
        json_scroll.set_size_request(-1, 110)
        
        self.json_text = Gtk.TextView()
        self.json_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        json_scroll.set_child(self.json_text)
        
        folder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        folder_lbl = Gtk.Label(label="Google Drive Folder ID (optional):")
        self.folder_entry = Gtk.Entry()
        self.folder_entry.set_placeholder_text("e.g. 1uK98vHjh...")
        self.folder_entry.set_hexpand(True)
        folder_box.append(folder_lbl)
        folder_box.append(self.folder_entry)
        
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        save_btn = Gtk.Button(label="Save Configurations")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self.on_save_settings_clicked)
        
        test_btn = Gtk.Button(label="Test Connection")
        test_btn.connect("clicked", self.on_test_connection_clicked)
        
        backup_btn = Gtk.Button(label="Cloud Backup Now")
        backup_btn.connect("clicked", self.on_cloud_backup_clicked)
        
        btn_box.append(save_btn)
        btn_box.append(test_btn)
        btn_box.append(backup_btn)
        
        self.status_lbl = Gtk.Label(label="")
        self.status_lbl.set_halign(Gtk.Align.START)
        
        gdrive_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        gdrive_box.append(json_lbl)
        gdrive_box.append(json_scroll)
        gdrive_box.append(folder_box)
        gdrive_box.append(btn_box)
        gdrive_box.append(self.status_lbl)
        
        gdrive_group.add(gdrive_box)
        layout.append(gdrive_group)
        
        # LOCAL BACKUPS PANEL
        local_group = Adw.PreferencesGroup()
        local_group.set_title("Local Snapshot Backups")
        
        create_local_btn = Gtk.Button(label="Create Snapshot")
        create_local_btn.connect("clicked", self.on_create_local_clicked)
        local_group.set_header_suffix(create_local_btn)
        
        self.backups_list = Gtk.ListBox()
        self.backups_list.set_selection_mode(Gtk.SelectionMode.NONE)
        
        local_group.add(self.backups_list)
        layout.append(local_group)
        
    def load_settings(self):
        if not self.drive:
            return
        settings_file = os.path.join(self.drive["path"], "albums", ".media_library_settings.json")
        if not os.path.exists(settings_file):
            self.page_size_combo.set_active_id(str(DEFAULT_PAGE_SIZE))
            return
            
        try:
            with open(settings_file, "r") as f:
                data = json.load(f)
                
            service_account = data.get("serviceAccountJson", "")
            if isinstance(service_account, dict):
                service_account = json.dumps(service_account, indent=2)
                
            buffer = self.json_text.get_buffer()
            buffer.set_text(service_account)
            
            self.folder_entry.set_text(data.get("gdriveFolderId", ""))
            
            saved_ps = str(data.get("itemsPerPage", DEFAULT_PAGE_SIZE))
            self.page_size_combo.set_active_id(saved_ps)
        except Exception as e:
            print(f"[Settings] Failed to load settings: {e}")

    def on_page_size_changed(self, combo):
        """Persist the new items-per-page choice immediately."""
        if not self.drive:
            return
        val = combo.get_active_id()
        if not val:
            return
        self._save_setting("itemsPerPage", int(val))

    def _save_setting(self, key, value):
        """Merge a single key into the settings JSON without overwriting others."""
        settings_file = os.path.join(self.drive["path"], "albums", ".media_library_settings.json")
        os.makedirs(os.path.dirname(settings_file), exist_ok=True)
        data = {}
        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r") as f:
                    data = json.load(f)
            except Exception:
                pass
        data[key] = value
        try:
            with open(settings_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Settings] Failed to save setting {key}: {e}")

    def on_save_settings_clicked(self, btn):
        if not self.drive:
            return
        buffer = self.json_text.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        sa_json = buffer.get_text(start, end, True).strip()
        
        folder_id = self.folder_entry.get_text().strip()
        ignores = load_ignore_list(self.drive["path"])
        
        settings_file = os.path.join(self.drive["path"], "albums", ".media_library_settings.json")
        try:
            sa_data = json.loads(sa_json) if sa_json else ""
        except Exception:
            sa_data = sa_json

        # Read existing settings to preserve other fields (e.g. itemsPerPage)
        existing = {}
        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r") as f:
                    existing = json.load(f)
            except Exception:
                pass

        existing.update({
            "ignoreList": ignores,
            "serviceAccountJson": sa_data,
            "gdriveFolderId": folder_id
        })
            
        try:
            with open(settings_file, "w") as f:
                json.dump(existing, f, indent=2)
            self.status_lbl.set_markup("<span foreground='#10b981'>✓ Configurations saved.</span>")
        except Exception as e:
            self.status_lbl.set_markup(f"<span foreground='#ef4444'>✗ Save failed: {escape_markup(str(e))}</span>")

    def on_test_connection_clicked(self, btn):
        buffer = self.json_text.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        sa_json = buffer.get_text(start, end, True).strip()
        folder_id = self.folder_entry.get_text().strip()
        
        if not sa_json:
            self.status_lbl.set_markup("<span foreground='#ef4444'>✗ Missing Service Account JSON.</span>")
            return
            
        self.status_lbl.set_text("Testing Google Drive connection...")
        btn.set_sensitive(False)
        
        def run():
            res = test_gdrive_connection(sa_json, folder_id or None)
            def done():
                btn.set_sensitive(True)
                if res["success"]:
                    self.status_lbl.set_markup("<span foreground='#10b981'>✓ Connection successful!</span>")
                else:
                    self.status_lbl.set_markup(f"<span foreground='#ef4444'>✗ Connection failed: {escape_markup(res.get('error', 'Unknown'))}</span>")
            GLib.idle_add(done)
            
        threading.Thread(target=run, daemon=True).start()

    def on_cloud_backup_clicked(self, btn):
        if not self.drive:
            return
        buffer = self.json_text.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        sa_json = buffer.get_text(start, end, True).strip()
        folder_id = self.folder_entry.get_text().strip()
        
        if not sa_json:
            self.status_lbl.set_markup("<span foreground='#ef4444'>✗ Missing Service Account JSON.</span>")
            return
            
        self.status_lbl.set_text("Uploading database backups to Google Drive...")
        btn.set_sensitive(False)
        
        def run():
            res = backup_to_gdrive(self.drive["path"], sa_json, folder_id or None)
            def done():
                btn.set_sensitive(True)
                if res["success"]:
                    success_files = [r["filename"] for r in res.get("uploadResults", []) if r["success"]]
                    files_str = ", ".join(success_files)
                    self.status_lbl.set_markup(f"<span foreground='#10b981'>✓ Backup completed! Uploaded: {escape_markup(files_str)}</span>")
                else:
                    self.status_lbl.set_markup(f"<span foreground='#ef4444'>✗ Backup failed: {escape_markup(res.get('error', 'Unknown'))}</span>")
            GLib.idle_add(done)
            
        threading.Thread(target=run, daemon=True).start()

    def load_backups_list(self):
        while True:
            child = self.backups_list.get_first_child()
            if not child:
                break
            self.backups_list.remove(child)
            
        if not self.drive:
            return
            
        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        backup_dir = backup_dir_for(db_path)
        if not os.path.exists(backup_dir):
            empty_lbl = Gtk.Label(label="No local snapshots generated yet.")
            empty_lbl.add_css_class("dim-label")
            empty_lbl.set_margin_top(12)
            self.backups_list.append(empty_lbl)
            return
            
        try:
            backups = sorted([
                f for f in os.listdir(backup_dir)
                if f.startswith("media_library-") and f.endswith(".db")
            ], reverse=True)
            
            if not backups:
                empty_lbl = Gtk.Label(label="No local snapshots generated yet.")
                empty_lbl.add_css_class("dim-label")
                self.backups_list.append(empty_lbl)
                return
                
            for name in backups:
                row = Adw.ActionRow()
                row.set_title(escape_markup(name))
                
                full_p = os.path.join(backup_dir, name)
                size_str = self.format_bytes(os.path.getsize(full_p))
                mtime = os.path.getmtime(full_p)
                mtime_str = GLib.DateTime.new_from_unix_local(int(mtime)).format("%Y-%m-%d %H:%M:%S")
                
                row.set_subtitle(f"Size: {size_str} · Created: {mtime_str}")
                row.add_prefix(Gtk.Image.new_from_icon_name("document-save-symbolic"))
                self.backups_list.append(row)
        except Exception as e:
            print(f"[Settings] Failed to list local backups: {e}")

    def on_create_local_clicked(self, btn):
        if not self.drive:
            return
        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            self.status_lbl.set_markup("<span foreground='#ef4444'>✗ Database file must exist to create snapshots. Scan first.</span>")
            return
            
        btn.set_sensitive(False)
        def run():
            res = create_backup(db_path)
            def done():
                btn.set_sensitive(True)
                if res:
                    self.status_lbl.set_markup("<span foreground='#10b981'>✓ Local snapshot database created.</span>")
                    self.load_backups_list()
                else:
                    self.status_lbl.set_markup("<span foreground='#ef4444'>✗ Snapshot creation failed.</span>")
            GLib.idle_add(done)
            
        threading.Thread(target=run, daemon=True).start()

    def format_bytes(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        import math
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
