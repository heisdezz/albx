import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QListWidget, QListWidgetItem, QComboBox
)
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont
from ui.theme import get_theme_manager, THEMES
from router import get_router
from core.drives import get_connected_drives

from ui.views.drive_selector import DriveSelectorView
from ui.views.dashboard import DashboardView
from ui.views.discover import DiscoverView
from ui.views.media_grid import MediaGridView
from ui.views.albums import AlbumsView
from ui.views.media_viewer import MediaViewer
from ui.views.settings import SettingsView

class FramelessTitleBar(QFrame):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.setObjectName("FramelessHeaderBar")
        self.setFixedHeight(42)
        self.drag_position = QPoint()

        self.build_ui()

    def build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(10)

        # Icon + Title
        logo_lbl = QLabel("🛸")
        logo_lbl.setFont(QFont("Segoe UI Emoji", 14))
        layout.addWidget(logo_lbl)

        title_lbl = QLabel("Antigravity Drive")
        title_lbl.setStyleSheet("font-weight: 800; font-size: 14px; color: #ff9900;")
        layout.addWidget(title_lbl)

        vbadge = QLabel("v1.0")
        vbadge.setStyleSheet(
            "background-color: rgba(255, 153, 0, 0.18); color: #ff9900; "
            "font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 4px;"
        )
        layout.addWidget(vbadge)

        layout.addStretch()

        # Theme Selector Shortcut
        self.theme_combo = QComboBox()
        self.theme_combo.setFixedWidth(150)
        for tname in THEMES.keys():
            self.theme_combo.addItem(tname)

        tm = get_theme_manager()
        self.theme_combo.setCurrentText(tm.current_theme_name)
        self.theme_combo.currentTextChanged.connect(lambda name: tm.set_theme(name))
        layout.addWidget(self.theme_combo)

        # Window Controls
        min_btn = QPushButton("➖")
        min_btn.setFixedSize(28, 28)
        min_btn.setStyleSheet("border: none; font-size: 11px;")
        min_btn.clicked.connect(self.parent_window.showMinimized)
        layout.addWidget(min_btn)

        max_btn = QPushButton("⬜")
        max_btn.setFixedSize(28, 28)
        max_btn.setStyleSheet("border: none; font-size: 10px;")
        max_btn.clicked.connect(self.toggle_maximize)
        layout.addWidget(max_btn)

        close_btn = QPushButton("❌")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("border: none; font-size: 11px;")
        close_btn.clicked.connect(self.parent_window.close)
        layout.addWidget(close_btn)

    def toggle_maximize(self):
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
        else:
            self.parent_window.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

class MainWindow(QMainWindow):
    BORDER_MARGIN = 6

    def __init__(self):
        super().__init__()
        self.selected_drive = None
        self.theme_manager = get_theme_manager()

        self.setWindowTitle("Antigravity Drive Media Organizer")
        self.setMinimumSize(900, 600)
        self.resize(1150, 740)

        # Window attributes & mouse tracking for frameless border resize
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.setMouseTracking(True)
        self.resizing = False
        self.resize_edge = None
        self.drag_start_pos = QPoint()
        self.drag_start_geo = None

        self.build_ui()
        self.theme_manager.subscribe(self.apply_theme)
        self.apply_theme()

        get_router().route_changed.connect(self.on_route_changed)
        get_router().navigate("/drives")

    def build_ui(self):
        # Root Central Widget
        self.root_widget = QWidget()
        self.root_widget.setObjectName("MainWindowRoot")
        self.root_widget.setMouseTracking(True)
        self.setCentralWidget(self.root_widget)

        root_layout = QVBoxLayout(self.root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Titlebar
        self.title_bar = FramelessTitleBar(self)
        root_layout.addWidget(self.title_bar)

        # Main Body Row (Sidebar + Stacked View Container)
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        root_layout.addLayout(body_layout)

        # Non-scrolling Clean Sidebar Frame
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setObjectName("SidebarFrame")
        self.sidebar_frame.setFixedWidth(230)

        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(14)

        # Section 1: Main Menu
        sidebar_layout.addWidget(self.create_section_label("NAVIGATE"))
        self.menu_list = QListWidget()
        self.menu_list.setFixedHeight(180)
        self.menu_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.menu_list.setWordWrap(True)
        self.menu_list.itemClicked.connect(self.on_menu_item_clicked)

        self.add_menu_item("💾 Drives Explorer", "/drives")
        self.add_menu_item("📊 Dashboard Overview", "/home")
        self.add_menu_item("📸 Media Gallery", "/media")
        self.add_menu_item("🔍 Discover & Catalog", "/scan")
        self.add_menu_item("📁 Album Folders", "/albums")
        sidebar_layout.addWidget(self.menu_list)

        # Section 2: Preferences
        sidebar_layout.addWidget(self.create_section_label("PREFERENCES"))
        self.pref_list = QListWidget()
        self.pref_list.setFixedHeight(40)
        self.pref_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pref_list.setWordWrap(True)
        self.pref_list.itemClicked.connect(self.on_menu_item_clicked)
        self.add_pref_item("⚙️ App Settings", "/settings")
        sidebar_layout.addWidget(self.pref_list)

        # Section 3: Connected Volumes (Pills & Icons & Active State)
        vol_hdr = QHBoxLayout()
        vol_lbl = self.create_section_label("CONNECTED VOLUMES")
        vol_hdr.addWidget(vol_lbl)
        vol_hdr.addStretch()

        ref_btn = QPushButton("🔄")
        ref_btn.setFixedSize(22, 22)
        ref_btn.setStyleSheet("border: none; font-size: 11px;")
        ref_btn.setToolTip("Refresh Detected Disks")
        ref_btn.clicked.connect(lambda: self.refresh_sidebar_drives())
        vol_hdr.addWidget(ref_btn)
        sidebar_layout.addLayout(vol_hdr)

        self.drives_list = QListWidget()
        self.drives_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.drives_list.setWordWrap(True)
        self.drives_list.itemClicked.connect(self.on_sidebar_drive_clicked)
        sidebar_layout.addWidget(self.drives_list, 1)

        body_layout.addWidget(self.sidebar_frame)

        self.refresh_sidebar_drives()

        # View Stack Container
        self.view_stack = QStackedWidget()
        body_layout.addWidget(self.view_stack)

    def create_section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 10px; font-weight: 800; color: #6c7086; letter-spacing: 1px;")
        return lbl

    def add_menu_item(self, text: str, route_path: str):
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, route_path)
        self.menu_list.addItem(item)

    def add_pref_item(self, text: str, route_path: str):
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, route_path)
        self.pref_list.addItem(item)

    def on_menu_item_clicked(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            get_router().navigate(path)

    def refresh_sidebar_drives(self):
        if not hasattr(self, 'drives_list'):
            return
        self.drives_list.clear()
        drives = get_connected_drives()
        for drv in drives:
            name = drv.get("label") or drv.get("name") or "Drive"
            is_mounted = bool(drv.get("is_mounted") or drv.get("status") == "mounted" or drv.get("path"))
            status = "🟢" if is_mounted else "🔴"
            icon = "💾" if drv.get("type") == "external" else "💽"
            fstype = (drv.get("fstype") or "exfat").upper()

            is_active = self.selected_drive and (
                self.selected_drive.get("id") == drv.get("id") or 
                self.selected_drive.get("path") == drv.get("path")
            )
            active_str = " ★ ACTIVE" if is_active else ""

            item = QListWidgetItem(f"{icon} {status} {name} [{fstype}]{active_str}")
            item.setData(Qt.ItemDataRole.UserRole, drv)
            if is_active:
                item.setSelected(True)
            self.drives_list.addItem(item)

    def on_sidebar_drive_clicked(self, item: QListWidgetItem):
        drv = item.data(Qt.ItemDataRole.UserRole)
        if drv:
            is_mounted = drv.get("is_mounted") or drv.get("status") == "mounted" or drv.get("path")
            if is_mounted:
                self.set_selected_drive(drv)
                get_router().navigate("/home")
            else:
                get_router().navigate("/drives")

    def set_selected_drive(self, drive: dict):
        self.selected_drive = drive
        self.refresh_sidebar_drives()

    def on_disconnect(self):
        self.set_selected_drive(None)
        get_router().navigate("/drives")

    def apply_theme(self):
        qss = self.theme_manager.generate_qss()
        self.setStyleSheet(qss)
        self.setWindowOpacity(1.0)
        if hasattr(self, 'title_bar'):
            self.title_bar.theme_combo.blockSignals(True)
            self.title_bar.theme_combo.setCurrentText(self.theme_manager.current_theme_name)
            self.title_bar.theme_combo.blockSignals(False)

    def on_route_changed(self, route_state: dict):
        path = route_state.get("path", "/drives")
        params = route_state.get("params", {})

        # Select corresponding sidebar item
        for i in range(self.menu_list.count()):
            item = self.menu_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self.menu_list.setCurrentItem(item)
                self.pref_list.clearSelection()
                break

        for i in range(self.pref_list.count()):
            item = self.pref_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self.pref_list.setCurrentItem(item)
                self.menu_list.clearSelection()
                break

        # Stop playback on current active widget before switching
        current_w = self.view_stack.currentWidget()
        if current_w:
            if hasattr(current_w, "stop_playback"):
                try:
                    current_w.stop_playback()
                except Exception:
                    pass

        # Instantiate View
        if path == "/drives":
            view = DriveSelectorView(self)
        elif path == "/home":
            view = DashboardView(self, self.selected_drive)
        elif path == "/scan":
            view = DiscoverView(self, self.selected_drive)
        elif path == "/media":
            filter_type = params.get("filter", "ALL")
            album_name = params.get("album", None)
            view = MediaGridView(
                self, self.selected_drive, filter_type, album_name=album_name
            )
        elif path == "/albums":
            view = AlbumsView(self, self.selected_drive)
        elif path == "/viewer":
            item_data = params.get("item", {})
            view = MediaViewer(self, self.selected_drive, item_data)
        elif path == "/settings":
            view = SettingsView(self, self.selected_drive)
        else:
            view = DriveSelectorView(self)

        self.view_stack.addWidget(view)
        self.view_stack.setCurrentWidget(view)

        # Remove old widgets from stack to free resources
        if current_w and current_w != view:
            self.view_stack.removeWidget(current_w)
            current_w.deleteLater()

    # --- Frameless Window Resizer Implementation ---
    def get_resize_edge(self, pos: QPoint):
        if self.isMaximized():
            return None
        w = self.width()
        h = self.height()
        m = self.BORDER_MARGIN

        left = pos.x() <= m
        right = pos.x() >= w - m
        top = pos.y() <= m
        bottom = pos.y() >= h - m

        if top and left: return "top_left"
        if top and right: return "top_right"
        if bottom and left: return "bottom_left"
        if bottom and right: return "bottom_right"
        if left: return "left"
        if right: return "right"
        if top: return "top"
        if bottom: return "bottom"
        return None

    def update_resize_cursor(self, edge):
        if edge in ("top_left", "bottom_right"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ("top_right", "bottom_left"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edge in ("left", "right"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ("top", "bottom"):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self.get_resize_edge(event.position().toPoint())
            if edge:
                self.resizing = True
                self.resize_edge = edge
                self.drag_start_pos = event.globalPosition().toPoint()
                self.drag_start_geo = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        gpos = event.globalPosition().toPoint()

        if self.resizing and self.drag_start_geo:
            diff = gpos - self.drag_start_pos
            geo = self.drag_start_geo
            x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
            edge = self.resize_edge

            if "right" in edge:
                w = max(self.minimumWidth(), w + diff.x())
            if "bottom" in edge:
                h = max(self.minimumHeight(), h + diff.y())
            if "left" in edge:
                new_w = max(self.minimumWidth(), w - diff.x())
                x += (w - new_w)
                w = new_w
            if "top" in edge:
                new_h = max(self.minimumHeight(), h - diff.y())
                y += (h - new_h)
                h = new_h

            self.setGeometry(x, y, w, h)
            event.accept()
            return
        else:
            edge = self.get_resize_edge(pos)
            self.update_resize_cursor(edge)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.resizing = False
        self.resize_edge = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)
