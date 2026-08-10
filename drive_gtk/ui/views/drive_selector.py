import os
from gi.repository import Gtk, Gdk, GLib, Adw
from core.drives import get_connected_drives, mount_block_device, user_mounted_drives
from router import get_router

def escape_markup(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""))

class DriveSelectorView(Gtk.Box):
    def __init__(self, parent_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.parent_window = parent_window
        
        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        
        self.build_ui()
        
    def build_ui(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label()
        title.set_markup("<span size='xx-large' weight='black'>Storage Explorer</span>")
        title.set_halign(Gtk.Align.START)
        
        subtitle = Gtk.Label(label="Connect and select a storage volume to organize your media library.")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        
        title_box.append(title)
        title_box.append(subtitle)
        header.append(title_box)
        
        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.set_halign(Gtk.Align.END)
        refresh_btn.set_hexpand(True)
        refresh_btn.connect("clicked", lambda x: self.refresh_list())
        header.append(refresh_btn)
        
        self.append(header)
        
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(sep)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.list_group = Adw.PreferencesGroup()
        self.list_group.set_title("Detected Storage Volumes")
        
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        self.list_group.add(self.list_box)
        
        scroll.set_child(self.list_group)
        self.append(scroll)
        
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer.set_margin_top(16)
        
        custom_btn = Gtk.Button(label="Open Custom Folder...")
        custom_btn.add_css_class("suggested-action")
        custom_btn.connect("clicked", self.on_custom_folder_clicked)
        
        footer.append(custom_btn)
        self.append(footer)
        
        self.refresh_list()
        
    def refresh_list(self):
        while True:
            child = self.list_box.get_first_child()
            if not child:
                break
            self.list_box.remove(child)

        drives = get_connected_drives()
        
        if not drives:
            status_page = Adw.StatusPage()
            status_page.set_icon_name("drive-harddisk-symbolic")
            status_page.set_title("No storage volumes found")
            status_page.set_description("Plug in an external USB drive or open a custom media directory.")
            self.list_box.append(status_page)
            return
            
        for drive in drives:
            row = Adw.ActionRow()
            row.set_title(escape_markup(drive["name"]))
            
            sub_txt = f"{drive['path'] or 'Unmounted'} · {drive['size']}"
            if drive["status"] == "mounted" and drive["usedPercentage"] > 0:
                sub_txt += f" ({drive['usedPercentage']}% used)"
            row.set_subtitle(escape_markup(sub_txt))
            
            icon_name = "drive-harddisk-usb-symbolic" if drive["type"] == "external" else "drive-harddisk-symbolic"
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
            
            action_btn = Gtk.Button()
            action_btn.set_valign(Gtk.Align.CENTER)
            
            if drive["status"] == "mounted":
                action_btn.set_label("Select")
                action_btn.add_css_class("suggested-action")
                action_btn.connect("clicked", lambda x, d=drive: self.select_drive(d))
            else:
                action_btn.set_label("Mount")
                action_btn.connect("clicked", lambda x, d=drive: self.mount_drive(d))
                
            row.add_suffix(action_btn)
            self.list_box.append(row)

    def select_drive(self, drive):
        get_router().navigate("/media", {"drive": drive})

    def mount_drive(self, drive):
        res = mount_block_device(drive["id"])
        if res["success"]:
            drive["status"] = "mounted"
            drive["path"] = res.get("mountPath", "")
            self.refresh_list()
            self.select_drive(drive)
        else:
            dialog = Gtk.AlertDialog.new()
            dialog.set_message("Mount Failed")
            dialog.set_detail(res.get("error", "Unknown error"))
            dialog.show(self.parent_window)

    def on_custom_folder_clicked(self, btn):
        def on_folder_selected(folder_path):
            if not folder_path:
                return
                
            name = os.path.basename(folder_path) or folder_path
            new_drive = {
                "id": f"user-{int(GLib.DateTime.new_now_local().to_unix())}",
                "name": f"{name} (Folder)",
                "type": "internal",
                "size": "Custom Folder",
                "usedPercentage": 0,
                "status": "mounted",
                "path": folder_path
            }
            if not any(d["path"] == folder_path for d in user_mounted_drives):
                user_mounted_drives.append(new_drive)
                
            self.refresh_list()
            self.select_drive(new_drive)

        self.select_folder_dialog("Choose Media Folder", on_folder_selected)
        
    def select_folder_dialog(self, title, callback):
        if hasattr(Gtk, "FileDialog"):
            dialog = Gtk.FileDialog.new()
            dialog.set_title(title)
            
            def on_finish(source, result):
                try:
                    gfile = source.select_folder_finish(result)
                    path = gfile.get_path()
                    GLib.idle_add(callback, path)
                except Exception:
                    GLib.idle_add(callback, None)
                    
            dialog.select_folder(self.parent_window, None, on_finish)
        else:
            dialog = Gtk.FileChooserNative.new(
                title,
                self.parent_window,
                Gtk.FileChooserAction.SELECT_FOLDER,
                "Select",
                "Cancel"
            )
            
            def on_response(dialog, response_id):
                if response_id == Gtk.ResponseType.ACCEPT:
                    gfile = dialog.get_file()
                    path = gfile.get_path() if gfile else None
                    GLib.idle_add(callback, path)
                else:
                    GLib.idle_add(callback, None)
                dialog.destroy()
                
            dialog.connect("response", on_response)
            dialog.show()
