import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.database import get_db_path, open_readable_db
from core.drives import get_connected_drives, mount_block_device
from router import get_router
from ui.widgets.media_grid import MediaGridView


class DashAlbumCard(QFrame):
    def __init__(self, album: dict, drive_path: str):
        super().__init__()
        self.album = album
        self.drive_path = drive_path
        self.setObjectName("GlassCard")
        self.setFixedHeight(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.build_ui()

    def build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        icon_box = QLabel("📁")
        icon_box.setStyleSheet("font-size: 28px;")
        layout.addWidget(icon_box)

        info_box = QVBoxLayout()
        info_box.setSpacing(2)

        name = self.album.get("name", "Album")
        if name == "unknown":
            name = "Unsorted Media"

        title = QLabel(name)
        title.setStyleSheet("font-weight: 700; font-size: 13px;")
        info_box.addWidget(title)

        cnt = self.album.get("media_count", 0)
        sub = QLabel(f"{cnt} items cataloged")
        sub.setObjectName("SubtitleLabel")
        info_box.addWidget(sub)

        layout.addLayout(info_box, 1)

        arrow = QLabel("➔")
        arrow.setStyleSheet("color: #89b4fa; font-weight: bold;")
        layout.addWidget(arrow)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            get_router().navigate("/albums")


class DashboardView(QWidget):
    def __init__(self, parent_window=None, drive: dict = None):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.drive = drive
        self.media_grid = None  # created by render_active_dashboard
        self.build_ui()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setSpacing(20)
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        self.render_view()

    def render_view(self):
        # Clear existing layout
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # CASE 1: No drive selected
        if not self.drive:
            self.render_welcome_screen()
            return

        # CASE 2: Selected drive is unmounted
        is_mounted = bool(
            self.drive.get("is_mounted")
            or self.drive.get("status") == "mounted"
            or self.drive.get("path")
        )
        if not is_mounted:
            self.render_unmounted_screen()
            return

        # CASE 3: Active Mounted Drive
        self.render_active_dashboard()

    def render_welcome_screen(self):
        # Hero Welcome Card
        hero_card = QFrame()
        hero_card.setObjectName("GlassCard")
        hero_card.setStyleSheet(
            "background: linear-gradient(135deg, rgba(255,153,0,0.12) 0%, rgba(19,23,33,1) 100%); "
            "border: 1px solid rgba(255, 153, 0, 0.3); border-radius: 16px;"
        )
        hc_layout = QVBoxLayout(hero_card)
        hc_layout.setContentsMargins(28, 28, 28, 28)
        hc_layout.setSpacing(12)

        welcome_lbl = QLabel("Welcome to Antigravity Drive")
        welcome_lbl.setObjectName("TitleLabel")
        welcome_lbl.setStyleSheet("font-size: 26px; font-weight: 900; color: #ff9900;")
        hc_layout.addWidget(welcome_lbl)

        desc_lbl = QLabel(
            "An ultra-fast media library & photo explorer powered by Python & PySide6 (Qt 6). "
            "Connect and select a storage volume to automatically catalog, preview, and search your photo albums."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 13px; color: #b3b1ad; line-height: 1.5;")
        hc_layout.addWidget(desc_lbl)

        self.content_layout.addWidget(hero_card)

        # Drive Selection Section
        sec_header = QLabel("SELECT A CONNECTED STORAGE VOLUME")
        sec_header.setObjectName("SectionHeader")
        self.content_layout.addWidget(sec_header)

        drives = get_connected_drives()
        if not drives:
            empty_card = QFrame()
            empty_card.setObjectName("GlassCard")
            ec_layout = QVBoxLayout(empty_card)
            ec_layout.setContentsMargins(32, 32, 32, 32)
            ec_layout.setSpacing(8)
            ec_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            e_icon = QLabel("💾")
            e_icon.setStyleSheet("font-size: 36px;")
            e_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ec_layout.addWidget(e_icon)

            e_title = QLabel("No External Drives Connected")
            e_title.setStyleSheet("font-size: 15px; font-weight: 700;")
            e_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ec_layout.addWidget(e_title)

            e_sub = QLabel(
                "Plug in a USB drive or external hard drive to explore media libraries."
            )
            e_sub.setObjectName("SubtitleLabel")
            e_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ec_layout.addWidget(e_sub)

            self.content_layout.addWidget(empty_card)
        else:
            grid = QGridLayout()
            grid.setSpacing(14)
            r, c = 0, 0
            for drv in drives:
                d_card = self.create_drive_select_card(drv)
                grid.addWidget(d_card, r, c)
                c += 1
                if c >= 2:
                    c = 0
                    r += 1
            self.content_layout.addLayout(grid)

        self.content_layout.addStretch()

    def create_drive_select_card(self, drv: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("GlassCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        is_mounted = bool(
            drv.get("is_mounted") or drv.get("status") == "mounted" or drv.get("path")
        )

        header_row = QHBoxLayout()
        icon_lbl = QLabel("💾" if drv.get("type") == "external" else "💽")
        icon_lbl.setStyleSheet("font-size: 20px;")
        header_row.addWidget(icon_lbl)

        info_box = QVBoxLayout()
        name = drv.get("label") or drv.get("name") or "Storage Volume"
        title = QLabel(name)
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        info_box.addWidget(title)

        dev_lbl = QLabel(f"{drv.get('device', '')} • {drv.get('size', '')}")
        dev_lbl.setObjectName("SubtitleLabel")
        info_box.addWidget(dev_lbl)
        header_row.addLayout(info_box, 1)

        status_badge = QLabel("MOUNTED" if is_mounted else "UNMOUNTED")
        status_badge.setStyleSheet(
            "background-color: rgba(166, 227, 161, 0.2); color: #a6e3a1; font-size: 9px; font-weight: 800; padding: 3px 6px; border-radius: 4px;"
            if is_mounted
            else "background-color: rgba(243, 139, 168, 0.2); color: #f38ba8; font-size: 9px; font-weight: 800; padding: 3px 6px; border-radius: 4px;"
        )
        header_row.addWidget(status_badge)
        layout.addLayout(header_row)

        if is_mounted:
            select_btn = QPushButton("Select & Explore")
            select_btn.setObjectName("AccentButton")
            select_btn.clicked.connect(lambda: self.select_drive_and_load(drv))
            layout.addWidget(select_btn)
        else:
            mount_btn = QPushButton("Mount Drive")
            mount_btn.clicked.connect(
                lambda: self.mount_and_refresh(drv.get("device") or drv.get("id"))
            )
            layout.addWidget(mount_btn)

        return card

    def select_drive_and_load(self, drv: dict):
        if self.parent_window:
            self.parent_window.set_selected_drive(drv)
        self.drive = drv
        self.render_view()

    def mount_and_refresh(self, device_id: str):
        if device_id:
            res = mount_block_device(device_id)
            if res.get("success"):
                if self.parent_window:
                    self.parent_window.refresh_sidebar_drives()
                self.render_view()

    def render_unmounted_screen(self):
        card = QFrame()
        card.setObjectName("GlassCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("⚠️")
        icon.setStyleSheet("font-size: 42px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        name = self.drive.get("label") or self.drive.get("name") or "Storage Volume"
        title = QLabel(f"{name} is Currently Unmounted")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel(
            "This storage volume needs to be mounted before you can inspect cataloged media."
        )
        sub.setObjectName("SubtitleLabel")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        mount_btn = QPushButton("Mount Drive")
        mount_btn.setObjectName("AccentButton")
        mount_btn.setFixedWidth(160)
        mount_btn.clicked.connect(
            lambda: self.mount_and_refresh(
                self.drive.get("device") or self.drive.get("id")
            )
        )
        layout.addWidget(mount_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.content_layout.addWidget(card)

    def render_active_dashboard(self):
        drive_path = self.drive.get("path", "")
        db_path = get_db_path(drive_path)

        # Header Panel
        hdr_card = QFrame()
        hdr_card.setObjectName("GlassCard")
        hc_layout = QHBoxLayout(hdr_card)
        hc_layout.setContentsMargins(20, 16, 20, 16)
        hc_layout.setSpacing(16)

        icon_box = QLabel("💾" if self.drive.get("type") == "external" else "💽")
        icon_box.setStyleSheet("font-size: 28px;")
        hc_layout.addWidget(icon_box)

        title_box = QVBoxLayout()
        name = self.drive.get("label") or self.drive.get("name") or "Drive"
        title = QLabel(name)
        title.setObjectName("TitleLabel")
        title_box.addWidget(title)

        sub = QLabel(f"{drive_path} • {self.drive.get('size', '')} Total Capacity")
        sub.setObjectName("SubtitleLabel")
        title_box.addWidget(sub)
        hc_layout.addLayout(title_box, 1)

        # Actions Row
        actions_box = QHBoxLayout()
        actions_box.setSpacing(8)

        scan_btn = QPushButton("🔍 Scan Volume")
        scan_btn.clicked.connect(lambda: get_router().navigate("/scan"))
        actions_box.addWidget(scan_btn)

        ref_btn = QPushButton("🔄 Refresh")
        ref_btn.clicked.connect(self.render_view)
        actions_box.addWidget(ref_btn)

        hc_layout.addLayout(actions_box)
        self.content_layout.addWidget(hdr_card)

        # Metrics Panel
        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(14)

        # Query Database Stats
        tot_items = 0
        tot_albums = 0
        tot_bytes = 0
        media_rows = []
        album_rows = []

        if os.path.exists(db_path):
            conn = open_readable_db(db_path)
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM media_items")
                    tot_items = cursor.fetchone()[0]

                    cursor.execute("SELECT COUNT(*) FROM albums")
                    tot_albums = cursor.fetchone()[0]

                    cursor.execute("SELECT SUM(file_size) FROM media_items")
                    tot_bytes = cursor.fetchone()[0] or 0

                    cursor.execute(
                        "SELECT id, current_relative_path, mime_type, file_size, created_at, file_hash FROM media_items ORDER BY created_at DESC LIMIT 8"
                    )
                    media_rows = cursor.fetchall()

                    cursor.execute("""
                        SELECT id, name, relative_path, created_at, media_count
                        FROM albums
                        ORDER BY created_at DESC LIMIT 4
                    """)
                    album_rows = cursor.fetchall()
                except Exception as e:
                    print(f"[Dashboard] DB query error: {e}")
                finally:
                    conn.close()

        # Metric 1: Total Media Items
        c1 = self.create_metric_card(
            "🖼️ Total Media Items", f"{tot_items:,} items", "#89b4fa"
        )
        metrics_grid.addWidget(c1, 0, 0)

        # Metric 2: Total Albums
        c2 = self.create_metric_card(
            "📁 Total Albums", f"{tot_albums} albums", "#cba6f7"
        )
        metrics_grid.addWidget(c2, 0, 1)

        # Metric 3: Storage Capacity Usage
        c3 = QFrame()
        c3.setObjectName("GlassCard")
        c3_layout = QVBoxLayout(c3)
        c3_layout.setContentsMargins(14, 14, 14, 14)
        c3_layout.setSpacing(6)

        c3_title = QLabel("📦 Storage Used")
        c3_title.setObjectName("SubtitleLabel")
        c3_layout.addWidget(c3_title)

        pct = self.drive.get("usedPercentage", 0)
        pbar = QProgressBar()
        pbar.setValue(pct)
        pbar.setFixedHeight(14)
        c3_layout.addWidget(pbar)

        c3_sub = QLabel(f"{pct}% filled of {self.drive.get('size', '')}")
        c3_sub.setObjectName("SubtitleLabel")
        c3_layout.addWidget(c3_sub)
        metrics_grid.addWidget(c3, 0, 2)

        self.content_layout.addLayout(metrics_grid)

        # Section: Recently Added Media
        recent_hdr = QHBoxLayout()
        recent_title = QLabel("RECENTLY ADDED MEDIA")
        recent_title.setObjectName("SectionHeader")
        recent_hdr.addWidget(recent_title)
        recent_hdr.addStretch()

        view_all_m = QPushButton("View All Media ➔")
        view_all_m.clicked.connect(lambda: get_router().navigate("/media"))
        recent_hdr.addWidget(view_all_m)
        self.content_layout.addLayout(recent_hdr)

        if not media_rows:
            empty_m = QFrame()
            empty_m.setObjectName("GlassCard")
            em_layout = QVBoxLayout(empty_m)
            em_layout.setContentsMargins(24, 24, 24, 24)
            em_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em_layout.setSpacing(8)

            lbl = QLabel("No Media Items Cataloged")
            lbl.setStyleSheet("font-weight: 700;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em_layout.addWidget(lbl)

            sub = QLabel(
                "Run a Discovery Scan to automatically index media files into your library."
            )
            sub.setObjectName("SubtitleLabel")
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em_layout.addWidget(sub)

            scan_btn2 = QPushButton("Start Discovery Scan")
            scan_btn2.setObjectName("AccentButton")
            scan_btn2.clicked.connect(lambda: get_router().navigate("/scan"))
            em_layout.addWidget(scan_btn2, alignment=Qt.AlignmentFlag.AlignCenter)

            self.content_layout.addWidget(empty_m)
        else:
            # Reusable, self-sizing grid (flat mode) - the dashboard's own
            # scroll area handles overflow.
            self.media_grid = MediaGridView(
                drive=self.drive,
                filter_type="ALL",
                page_size=8,
                show_filter_bar=False,
                scrollable=False,
            )
            self.content_layout.addWidget(self.media_grid)

        # Section: Recent Albums
        albums_hdr = QHBoxLayout()
        albums_title = QLabel("RECENT ALBUMS")
        albums_title.setObjectName("SectionHeader")
        albums_hdr.addWidget(albums_title)
        albums_hdr.addStretch()

        view_all_a = QPushButton("View All Albums ➔")
        view_all_a.clicked.connect(lambda: get_router().navigate("/albums"))
        albums_hdr.addWidget(view_all_a)
        self.content_layout.addLayout(albums_hdr)

        if not album_rows:
            empty_a = QFrame()
            empty_a.setObjectName("GlassCard")
            ea_layout = QVBoxLayout(empty_a)
            ea_layout.setContentsMargins(24, 24, 24, 24)
            ea_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            lbl = QLabel("No Album Collections Found")
            lbl.setStyleSheet("font-weight: 700;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ea_layout.addWidget(lbl)
            self.content_layout.addWidget(empty_a)
        else:
            a_grid = QGridLayout()
            a_grid.setSpacing(12)
            ar, ac = 0, 0
            for a_row in album_rows:
                album_dict = {
                    "id": a_row[0],
                    "name": a_row[1],
                    "relative_path": a_row[2],
                    "created_at": a_row[3],
                    "media_count": a_row[4],
                }
                acard = DashAlbumCard(album_dict, drive_path)
                a_grid.addWidget(acard, ar, ac)
                ac += 1
                if ac >= 2:
                    ac = 0
                    ar += 1
            self.content_layout.addLayout(a_grid)

    def create_metric_card(
        self, title_text: str, value_text: str, color_hex: str
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("GlassCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)

        lbl = QLabel(title_text)
        lbl.setObjectName("SubtitleLabel")

        val = QLabel(value_text)
        val.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {color_hex};")

        layout.addWidget(lbl)
        layout.addWidget(val)
        return card
