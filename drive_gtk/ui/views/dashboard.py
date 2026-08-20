import os

from gi.repository import Adw, GLib, Gtk
from router import get_router

from core.database import open_readable_db
from core.scanner import active_scans
from ui.widgets.media_card import MediaCard


def escape_markup(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""))


class DashboardView(Gtk.Box):
    """
    Stats / home dashboard — mirrors the original index.tsx.
    Shows: drive header, stat cards (total media, total albums, storage used),
    recently added media thumbnails, and recent albums list.
    """

    def __init__(self, parent_window, drive):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.parent_window = parent_window
        self.drive = drive

        self.total_media = 0
        self.total_albums = 0
        self.recent_media = []
        self.recent_albums = []

        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(16)
        self.set_margin_bottom(16)

        self.build_ui()
        if self.drive:
            self.load_data()

    def build_ui(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.append(scroll)

        # Full-width layout (no clamp) so the dashboard uses all available space.
        self.layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.layout.set_margin_start(8)
        self.layout.set_margin_end(8)
        self.layout.set_margin_top(8)
        self.layout.set_margin_bottom(24)
        scroll.set_child(self.layout)

        # --- DRIVE HEADER PANEL ---
        header_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        header_card.add_css_class("card")

        icon_box = Gtk.Box()
        icon_box.set_size_request(48, 48)
        icon_box.set_valign(Gtk.Align.CENTER)
        drive_icon_name = (
            "drive-harddisk-usb-symbolic"
            if (self.drive or {}).get("type") == "external"
            else "drive-harddisk-symbolic"
        )
        drive_icon = Gtk.Image.new_from_icon_name(drive_icon_name)
        drive_icon.set_pixel_size(28)
        icon_box.append(drive_icon)
        header_card.append(icon_box)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)

        drive_name = (self.drive or {}).get("name", "No Drive")
        drive_path = (self.drive or {}).get("path", "")
        drive_size = (self.drive or {}).get("size", "")

        name_lbl = Gtk.Label()
        name_lbl.set_markup(
            f"<span size='x-large' weight='black'>{escape_markup(drive_name)}</span>"
        )
        name_lbl.set_halign(Gtk.Align.START)
        info_box.append(name_lbl)

        path_lbl = Gtk.Label(label=f"{drive_path} · {drive_size} Total")
        path_lbl.set_halign(Gtk.Align.START)
        path_lbl.add_css_class("dim-label")
        path_lbl.add_css_class("caption")
        info_box.append(path_lbl)

        header_card.append(info_box)

        # Scan status / action buttons
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_box.set_valign(Gtk.Align.CENTER)

        self.scan_status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6
        )
        self.scan_status_box.set_visible(False)
        scan_spinner = Gtk.Spinner()
        scan_spinner.start()
        self.scan_status_box.append(scan_spinner)
        self.scan_status_lbl = Gtk.Label(label="Indexing...")
        self.scan_status_lbl.add_css_class("caption")
        self.scan_status_box.append(self.scan_status_lbl)
        action_box.append(self.scan_status_box)

        scan_btn = Gtk.Button(label="Scan Volume")
        scan_btn.set_icon_name("system-search-symbolic")
        scan_btn.add_css_class("flat")
        scan_btn.connect(
            "clicked", lambda b: get_router().navigate("/scan", {"drive": self.drive})
        )
        action_box.append(scan_btn)

        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.add_css_class("flat")
        refresh_btn.set_tooltip_text("Refresh dashboard")
        refresh_btn.connect("clicked", lambda b: self.load_data())
        action_box.append(refresh_btn)

        header_card.append(action_box)
        self.layout.append(header_card)

        # --- STATS CARDS (3 columns) ---
        stats_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        # Card 1: Total Media
        self.media_stat_card = self._make_stat_card(
            "camera-photo-symbolic", "Total Media Items", "0"
        )
        stats_grid.append(self.media_stat_card["outer"])

        # Card 2: Total Albums
        self.albums_stat_card = self._make_stat_card(
            "folder-symbolic", "Total Albums", "0"
        )
        stats_grid.append(self.albums_stat_card["outer"])

        # Card 3: Storage Used
        storage_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        storage_card.add_css_class("card")
        storage_card.add_css_class("stat-card")
        storage_card.set_hexpand(True)

        storage_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        storage_title = Gtk.Label(label="Storage Used")
        storage_title.add_css_class("caption")
        storage_title.add_css_class("dim-label")
        storage_title.set_halign(Gtk.Align.START)
        storage_title.set_hexpand(True)
        storage_hdr.append(storage_title)

        used_pct = (self.drive or {}).get("usedPercentage", 0)
        self.storage_pct_lbl = Gtk.Label(label=f"{used_pct}%")
        self.storage_pct_lbl.add_css_class("caption")
        storage_hdr.append(self.storage_pct_lbl)
        storage_card.append(storage_hdr)

        self.storage_bar = Gtk.ProgressBar()
        self.storage_bar.set_fraction(used_pct / 100.0 if used_pct else 0)
        storage_card.append(self.storage_bar)

        capacity_lbl = Gtk.Label(label=f"{drive_size} total capacity")
        capacity_lbl.add_css_class("caption")
        capacity_lbl.add_css_class("dim-label")
        capacity_lbl.set_halign(Gtk.Align.START)
        storage_card.append(capacity_lbl)

        stats_grid.append(storage_card)
        self.layout.append(stats_grid)

        # --- RECENTLY ADDED MEDIA ---
        media_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        media_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        media_hdr_lbl = Gtk.Label()
        media_hdr_lbl.set_markup("<span weight='bold'>Recently Added Media</span>")
        media_hdr_lbl.set_halign(Gtk.Align.START)
        media_hdr_lbl.set_hexpand(True)
        media_hdr.append(media_hdr_lbl)

        view_all_btn = Gtk.Button(label="View All Media →")
        view_all_btn.add_css_class("flat")
        view_all_btn.connect(
            "clicked", lambda b: get_router().navigate("/media", {"drive": self.drive})
        )
        media_hdr.append(view_all_btn)
        media_section.append(media_hdr)

        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        media_section.append(sep1)

        self.recent_media_flow = Gtk.FlowBox()
        self.recent_media_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.recent_media_flow.set_row_spacing(10)
        self.recent_media_flow.set_column_spacing(10)
        self.recent_media_flow.set_max_children_per_line(8)
        self.recent_media_flow.set_min_children_per_line(3)
        self.recent_media_flow.connect(
            "child-activated", self._on_recent_media_activated
        )
        media_section.append(self.recent_media_flow)

        self.no_media_status = Adw.StatusPage()
        self.no_media_status.set_icon_name("camera-photo-symbolic")
        self.no_media_status.set_title("No Media Found")
        self.no_media_status.set_description(
            "This volume has not been scanned yet. Use Discover Scan to index files."
        )
        self.no_media_status.set_visible(False)
        media_section.append(self.no_media_status)

        self.layout.append(media_section)

        # --- RECENT ALBUMS ---
        albums_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        albums_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        albums_hdr_lbl = Gtk.Label()
        albums_hdr_lbl.set_markup("<span weight='bold'>Recent Albums</span>")
        albums_hdr_lbl.set_halign(Gtk.Align.START)
        albums_hdr_lbl.set_hexpand(True)
        albums_hdr.append(albums_hdr_lbl)

        view_albums_btn = Gtk.Button(label="View All Albums →")
        view_albums_btn.add_css_class("flat")
        view_albums_btn.connect(
            "clicked", lambda b: get_router().navigate("/albums", {"drive": self.drive})
        )
        albums_hdr.append(view_albums_btn)
        albums_section.append(albums_hdr)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        albums_section.append(sep2)

        self.albums_list = Gtk.ListBox()
        self.albums_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.albums_list.add_css_class("boxed-list")
        albums_section.append(self.albums_list)

        self.no_albums_status = Adw.StatusPage()
        self.no_albums_status.set_icon_name("folder-symbolic")
        self.no_albums_status.set_title("No Albums Found")
        self.no_albums_status.set_description(
            "Scanning will auto-group media into album folders."
        )
        self.no_albums_status.set_visible(False)
        albums_section.append(self.no_albums_status)

        self.layout.append(albums_section)

    def _make_stat_card(self, icon_name, title, value):
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        outer.add_css_class("card")
        outer.add_css_class("stat-card")
        outer.set_hexpand(True)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(28)
        outer.append(icon)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_lbl = Gtk.Label(label=title)
        title_lbl.add_css_class("caption")
        title_lbl.add_css_class("dim-label")
        title_lbl.set_halign(Gtk.Align.START)
        text_box.append(title_lbl)

        value_lbl = Gtk.Label()
        value_lbl.set_markup(f"<span size='x-large' weight='black'>{value}</span>")
        value_lbl.set_halign(Gtk.Align.START)
        text_box.append(value_lbl)

        outer.append(text_box)
        return {"outer": outer, "value_lbl": value_lbl}

    def load_data(self):
        if not self.drive:
            return

        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        if not os.path.exists(db_path):
            self.no_media_status.set_visible(True)
            self.no_albums_status.set_visible(True)
            return

        # Check scan status
        drive_path = self.drive["path"]
        if drive_path in active_scans and active_scans[drive_path].scanning:
            self.scan_status_box.set_visible(True)
            state = active_scans[drive_path]
            self.scan_status_lbl.set_text(f"Found {state.found_count} items...")
        else:
            self.scan_status_box.set_visible(False)

        try:
            conn = open_readable_db(db_path)
            cursor = conn.cursor()

            # Total media
            cursor.execute("SELECT count(*) as cnt FROM media_items")
            self.total_media = cursor.fetchone()["cnt"]
            self.media_stat_card["value_lbl"].set_markup(
                f"<span size='x-large' weight='black'>{self.total_media}</span>"
            )

            # Total albums
            cursor.execute("SELECT count(*) as cnt FROM albums")
            self.total_albums = cursor.fetchone()["cnt"]
            self.albums_stat_card["value_lbl"].set_markup(
                f"<span size='x-large' weight='black'>{self.total_albums}</span>"
            )

            # Recent 8 media items
            cursor.execute("""
                SELECT * FROM media_items
                ORDER BY created_at DESC
                LIMIT 8
            """)
            self.recent_media = [dict(r) for r in cursor.fetchall()]

            # Recent 4 albums with media count
            cursor.execute("""
                SELECT a.*, count(m.id) as media_count
                FROM albums a
                LEFT JOIN media_items m ON m.album_id = a.id
                GROUP BY a.id
                ORDER BY a.created_at DESC
                LIMIT 4
            """)
            self.recent_albums = [dict(r) for r in cursor.fetchall()]

            conn.close()
        except Exception as e:
            print(f"[Dashboard] Failed to load data: {e}")

        self._render_recent_media()
        self._render_recent_albums()

    def _render_recent_media(self):
        # Clear
        while True:
            child = self.recent_media_flow.get_first_child()
            if not child:
                break
            self.recent_media_flow.remove(child)

        if not self.recent_media:
            self.no_media_status.set_visible(True)
            self.recent_media_flow.set_visible(False)
            return

        self.no_media_status.set_visible(False)
        self.recent_media_flow.set_visible(True)

        for item in self.recent_media:
            card = MediaCard(item, self.drive["path"], lambda item_id, selected: None)
            self.recent_media_flow.append(card)

    def _on_recent_media_activated(self, flowbox, child):
        card = child.get_child()
        if card and hasattr(card, "item"):
            get_router().navigate(
                "/media_detail", {"item": card.item, "drive": self.drive}
            )

    def _render_recent_albums(self):
        while True:
            child = self.albums_list.get_first_child()
            if not child:
                break
            self.albums_list.remove(child)

        if not self.recent_albums:
            self.no_albums_status.set_visible(True)
            self.albums_list.set_visible(False)
            return

        self.no_albums_status.set_visible(False)
        self.albums_list.set_visible(True)

        for album in self.recent_albums:
            display_name = (
                "Unsorted Media" if album["name"] == "unknown" else album["name"]
            )
            media_count = album.get("media_count", 0)
            created = str(album.get("created_at", ""))[:10]

            row = Adw.ActionRow()
            row.set_title(display_name)
            row.set_subtitle(
                f"{media_count} item{'s' if media_count != 1 else ''} · Created {created}"
            )
            row.add_prefix(Gtk.Image.new_from_icon_name("folder-symbolic"))

            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.add_css_class("dim-label")
            row.add_suffix(arrow)
            row.set_activatable(True)

            self.albums_list.append(row)
