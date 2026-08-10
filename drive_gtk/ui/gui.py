import os
from gi.repository import Gtk, Gdk, GLib, Adw
from core.drives import get_connected_drives, mount_block_device
from router import get_router

from ui.views.drive_selector import DriveSelectorView
from ui.views.dashboard import DashboardView
from ui.views.discover import DiscoverView
from ui.views.media_grid import MediaGridView
from ui.views.albums import AlbumsView
from ui.views.settings import SettingsView
from ui.views.media_viewer import MediaViewer

def escape_markup(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""))

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Antigravity Drive Media Organizer")
        self.set_default_size(1050, 700)
        
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        
        self.selected_drive = None
        self.active_sidebar_row_id = "/drives"
        
        self.load_styles()
        self.build_ui()
        
        get_router().subscribe(self.on_route_changed)
        get_router().navigate("/drives")
        
    def load_styles(self):
        css_provider = Gtk.CssProvider()
        css_path = os.path.join(os.path.dirname(__file__), "style.css")
        if os.path.exists(css_path):
            try:
                css_provider.load_from_path(css_path)
                Gtk.StyleContext.add_provider_for_display(
                    Gdk.Display.get_default(),
                    css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
            except Exception as e:
                print(f"[GUI] Failed to load style.css: {e}")
                
    def build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_content(main_box)
        
        self.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.sidebar_box.set_hexpand(False)
        self.sidebar_box.set_size_request(190, -1)
        self.sidebar_box.add_css_class("sidebar")
        main_box.append(self.sidebar_box)
        
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_box.set_margin_start(12)
        title_box.set_margin_top(12)
        title_box.set_margin_bottom(8)
        
        logo = Gtk.Image.new_from_icon_name("media-optical-symbolic")
        logo.set_pixel_size(18)
        title_lbl = Gtk.Label()
        title_lbl.set_markup("<span size='medium' weight='black' foreground='#818cf8'>Antigravity Drive</span>")
        
        title_box.append(logo)
        title_box.append(title_lbl)
        self.sidebar_box.append(title_box)
        
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)
        
        sidebar_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar_scroll.set_child(sidebar_content)
        self.sidebar_box.append(sidebar_scroll)
        
        self.menu_list = Gtk.ListBox()
        self.menu_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.menu_list.connect("row-activated", self.on_menu_row_activated)
        sidebar_content.append(self.menu_list)
        
        self.rows = {}
        self.add_menu_row("/drives", "Explorer", "drive-harddisk-symbolic", True)
        self.add_menu_row("/home", "Dashboard", "user-home-symbolic", False)
        self.add_menu_row("/media", "Media Gallery", "camera-photo-symbolic", False)
        self.add_menu_row("/scan", "Discover Scan", "system-search-symbolic", False)
        self.add_menu_row("/albums", "Album Folders", "folder-symbolic", False)
        self.add_menu_row("/settings", "Settings", "preferences-system-symbolic", False)
        
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_start(12)
        sep.set_margin_end(12)
        sidebar_content.append(sep)
        
        drives_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        drives_hdr.set_margin_start(12)
        drives_hdr.set_margin_end(12)
        
        drives_lbl = Gtk.Label()
        drives_lbl.set_markup("<span size='x-small' weight='bold' foreground='#94a3b8'>DRIVES</span>")
        drives_lbl.set_halign(Gtk.Align.START)
        drives_hdr.append(drives_lbl)
        
        refresh_drives_btn = Gtk.Button()
        refresh_drives_btn.set_icon_name("view-refresh-symbolic")
        refresh_drives_btn.add_css_class("flat")
        refresh_drives_btn.set_halign(Gtk.Align.END)
        refresh_drives_btn.set_hexpand(True)
        refresh_drives_btn.connect("clicked", lambda x: self.refresh_sidebar_drives())
        drives_hdr.append(refresh_drives_btn)
        
        sidebar_content.append(drives_hdr)
        
        self.drives_list = Gtk.ListBox()
        self.drives_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.drives_list.connect("row-activated", self.on_drive_row_activated)
        sidebar_content.append(self.drives_list)
        
        self.sidebar_footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sidebar_footer.set_margin_bottom(12)
        self.sidebar_footer.set_margin_start(10)
        self.sidebar_footer.set_margin_end(10)
        self.sidebar_box.append(self.sidebar_footer)
        
        self.drive_status_lbl = Gtk.Label(label="No volume loaded")
        self.drive_status_lbl.add_css_class("dim-label")
        self.drive_status_lbl.add_css_class("caption")
        self.drive_status_lbl.set_halign(Gtk.Align.START)
        self.sidebar_footer.append(self.drive_status_lbl)
        
        self.disconnect_btn = Gtk.Button(label="Disconnect")
        self.disconnect_btn.add_css_class("destructive-action")
        self.disconnect_btn.set_visible(False)
        self.disconnect_btn.connect("clicked", self.on_disconnect_clicked)
        self.sidebar_footer.append(self.disconnect_btn)
        
        right_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right_container.set_hexpand(True)
        right_container.set_vexpand(True)
        
        self.header_bar = Adw.HeaderBar()
        right_container.append(self.header_bar)
        
        self.view_stack = Gtk.Stack()
        self.view_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.view_stack.set_transition_duration(180)
        self.view_stack.set_hexpand(True)
        self.view_stack.set_vexpand(True)
        right_container.append(self.view_stack)
        
        main_box.append(right_container)
        
        self.drive_selector = DriveSelectorView(self)
        self.view_stack.add_named(self.drive_selector, "drives")
        self.view_stack.set_visible_child_name("drives")
        
        self.update_menu_sensitivities()
        self.refresh_sidebar_drives()
        
    def add_menu_row(self, route_path, label, icon_name, sensitive):
        row = Gtk.ListBoxRow()
        row.set_sensitive(sensitive)
        row.route_path = route_path
        
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("sidebar-row")
        
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(16)
        lbl = Gtk.Label(label=label)
        lbl.set_halign(Gtk.Align.START)
        
        box.append(icon)
        box.append(lbl)
        row.set_child(box)
        
        self.menu_list.append(row)
        self.rows[route_path] = row
        
    def refresh_sidebar_drives(self):
        while True:
            child = self.drives_list.get_first_child()
            if not child:
                break
            self.drives_list.remove(child)
            
        drives = get_connected_drives()
        
        if not drives:
            empty_lbl = Gtk.Label(label="No drives")
            empty_lbl.add_css_class("dim-label")
            empty_lbl.add_css_class("caption")
            empty_lbl.set_margin_start(12)
            self.drives_list.append(empty_lbl)
            return
            
        for drive in drives:
            row = Gtk.ListBoxRow()
            row.drive_data = drive
            
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.add_css_class("sidebar-row")
            
            is_mounted = drive["status"] == "mounted"
            dot_color = "#10b981" if is_mounted else "#f59e0b"
            dot = Gtk.Label()
            dot.set_markup(f"<span foreground='{dot_color}'>●</span>")
            box.append(dot)
            
            icon_name = "drive-harddisk-usb-symbolic" if drive["type"] == "external" else "drive-harddisk-symbolic"
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(14)
            box.append(icon)
            
            name_lbl = Gtk.Label()
            name_lbl.set_markup(f"<b>{escape_markup(drive['name'])}</b>")
            name_lbl.set_halign(Gtk.Align.START)
            name_lbl.set_hexpand(True)
            name_lbl.set_ellipsize(3)
            box.append(name_lbl)
            
            row.set_child(box)
            self.drives_list.append(row)

    def on_drive_row_activated(self, listbox, row):
        if not row or not hasattr(row, "drive_data"):
            return
            
        drive = row.drive_data
        if drive["status"] == "mounted":
            self.set_active_drive(drive)
            get_router().navigate("/home", {"drive": drive})
        else:
            res = mount_block_device(drive["id"])
            if res["success"]:
                self.refresh_sidebar_drives()
                drive["status"] = "mounted"
                drive["path"] = res.get("mountPath", "")
                self.set_active_drive(drive)
                get_router().navigate("/home", {"drive": drive})
            else:
                dialog = Gtk.AlertDialog.new()
                dialog.set_message("Mount Failed")
                dialog.set_detail(res.get("error", "Failed to mount partition."))
                dialog.show(self)

    def set_active_drive(self, drive):
        self.selected_drive = drive
        self.update_menu_sensitivities()
        self.drive_status_lbl.set_markup(f"Active Volume:\n<b>{escape_markup(drive['name'])}</b>")
        self.disconnect_btn.set_visible(True)

    def update_menu_sensitivities(self):
        has_drive = self.selected_drive is not None
        for path, row in self.rows.items():
            if path != "/drives":
                row.set_sensitive(has_drive)

    def select_menu_row(self, route_path):
        row = self.rows.get(route_path)
        if row:
            self.menu_list.select_row(row)
            for path, r in self.rows.items():
                box = r.get_child()
                if path == route_path:
                    box.add_css_class("active")
                else:
                    box.remove_css_class("active")

    def on_menu_row_activated(self, listbox, row):
        if not row or not row.get_sensitive():
            return
        route_path = row.route_path
        get_router().navigate(route_path, {"drive": self.selected_drive})

    def on_route_changed(self, route_state):
        path = route_state["path"]
        params = route_state["params"]
        
        if "drive" in params and params["drive"]:
            self.set_active_drive(params["drive"])
            
        if path in self.rows:
            self.select_menu_row(path)
            
        if path in ["/drives", "/"]:
            self.switch_to_view(self.drive_selector, "drives")
        elif path == "/home":
            dashboard = DashboardView(self, self.selected_drive)
            self.switch_to_view(dashboard, "home")
        elif path == "/media":
            album_id = params.get("album_id")
            media_grid = MediaGridView(self, self.selected_drive, album_id)
            self.switch_to_view(media_grid, "media")
        elif path == "/media_detail":
            item = params["item"]
            album_id = params.get("album_id")
            viewer = MediaViewer(self, self.selected_drive, item, album_id)
            self.switch_to_view(viewer, "media_detail")
        elif path == "/scan":
            discover = DiscoverView(self, self.selected_drive)
            self.switch_to_view(discover, "scan")
        elif path == "/albums":
            albums = AlbumsView(self, self.selected_drive)
            self.switch_to_view(albums, "albums")
        elif path == "/settings":
            settings = SettingsView(self, self.selected_drive)
            self.switch_to_view(settings, "settings")

    def switch_to_view(self, widget, name="view"):
        child = self.view_stack.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            if child != self.drive_selector:
                self.view_stack.remove(child)
            child = next_child
            
        if widget != self.drive_selector:
            self.view_stack.add_named(widget, name)
        self.view_stack.set_visible_child(widget)

    def on_disconnect_clicked(self, btn):
        from core.scanner import active_scans
        if self.selected_drive and self.selected_drive["path"] in active_scans:
            state = active_scans[self.selected_drive["path"]]
            if state.scanning:
                dialog = Gtk.AlertDialog.new()
                dialog.set_message("Scanner Active")
                dialog.set_detail("Please stop the active folder scan before disconnecting.")
                dialog.show(self)
                return

        self.selected_drive = None
        self.update_menu_sensitivities()
        
        self.drive_status_lbl.set_text("No volume loaded")
        self.disconnect_btn.set_visible(False)
        
        self.drive_selector.refresh_list()
        self.refresh_sidebar_drives()
        get_router().navigate("/drives")
