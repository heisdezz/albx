import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QProgressBar
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from core.drives import get_connected_drives, mount_block_device, unmount_block_device
from router import get_router

class DriveRow(QFrame):
    drive_selected = Signal(dict)
    refresh_requested = Signal()

    def __init__(self, drive: dict):
        super().__init__()
        self.drive = drive
        self.setObjectName("GlassCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.build_ui()

    def build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(16)

        # Left Column: Drive Icon
        icon_lbl = QLabel("💾" if self.drive.get("type") == "external" else "💽")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 18))
        layout.addWidget(icon_lbl)

        # Drive Info Column: Name, Device, FileSystem
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        drive_name = self.drive.get("label") or self.drive.get("name") or "Storage Volume"
        name_lbl = QLabel(drive_name)
        name_lbl.setStyleSheet("font-weight: 700; font-size: 15px;")
        title_row.addWidget(name_lbl)

        fstype = (self.drive.get("fstype") or "exfat").upper()
        fs_badge = QLabel(fstype)
        fs_badge.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.08); color: #a6adc8; "
            "font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px;"
        )
        title_row.addWidget(fs_badge)

        device_id = self.drive.get("device") or self.drive.get("id") or "/dev/sdX"
        size_str = self.drive.get("size", "")
        sub_lbl = QLabel(f"{device_id} • {size_str}")
        sub_lbl.setObjectName("SubtitleLabel")
        title_row.addWidget(sub_lbl)
        title_row.addStretch()

        info_layout.addLayout(title_row)

        mount_path = self.drive.get("path", "")
        if mount_path:
            path_lbl = QLabel(f"📍 {mount_path}")
            path_lbl.setObjectName("SubtitleLabel")
            path_lbl.setStyleSheet("color: #89b4fa; font-size: 11px;")
            info_layout.addWidget(path_lbl)

        layout.addLayout(info_layout, stretch=2)

        # Usage / Progress Column (if mounted)
        is_mounted = self.drive.get("is_mounted") or self.drive.get("status") == "mounted" or bool(mount_path)

        if is_mounted:
            usage_box = QVBoxLayout()
            usage_box.setSpacing(4)
            pct = self.drive.get("usedPercentage", 0)

            pbar = QProgressBar()
            pbar.setValue(pct)
            pbar.setFixedHeight(12)
            pbar.setFixedWidth(140)
            pbar.setTextVisible(False)
            usage_box.addWidget(pbar)

            usage_lbl = QLabel(f"{pct}% used")
            usage_lbl.setObjectName("SubtitleLabel")
            usage_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            usage_box.addWidget(usage_lbl)
            layout.addLayout(usage_box)

        # Mount Status Pill Badge
        status_lbl = QLabel("MOUNTED" if is_mounted else "UNMOUNTED")
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_lbl.setFixedWidth(85)
        if is_mounted:
            status_lbl.setStyleSheet(
                "background-color: rgba(166, 227, 161, 0.18); color: #a6e3a1; "
                "font-size: 10px; font-weight: 800; padding: 5px 8px; border-radius: 6px;"
            )
        else:
            status_lbl.setStyleSheet(
                "background-color: rgba(243, 139, 168, 0.18); color: #f38ba8; "
                "font-size: 10px; font-weight: 800; padding: 5px 8px; border-radius: 6px;"
            )
        layout.addWidget(status_lbl)

        # Action Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        if is_mounted:
            explore_btn = QPushButton("Explore")
            explore_btn.setObjectName("AccentButton")
            explore_btn.clicked.connect(lambda: self.drive_selected.emit(self.drive))
            btn_box.addWidget(explore_btn)

            unmount_btn = QPushButton("Unmount")
            unmount_btn.setObjectName("DestructiveButton")
            unmount_btn.clicked.connect(self.on_unmount_clicked)
            btn_box.addWidget(unmount_btn)
        else:
            mount_btn = QPushButton("Mount Drive")
            mount_btn.clicked.connect(self.on_mount_clicked)
            btn_box.addWidget(mount_btn)

        layout.addLayout(btn_box)

    def on_mount_clicked(self):
        device_id = self.drive.get("device") or self.drive.get("id")
        if device_id:
            res = mount_block_device(device_id)
            if res.get("success"):
                self.refresh_requested.emit()

    def on_unmount_clicked(self):
        device_id = self.drive.get("device") or self.drive.get("id")
        if device_id:
            res = unmount_block_device(device_id)
            if res.get("success"):
                self.refresh_requested.emit()

class DriveSelectorView(QWidget):
    def __init__(self, parent_window=None):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.build_ui()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        # Header Title Row
        header_box = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Storage Drives Explorer")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("Select a mounted external volume or mount block devices to manage media.")
        subtitle.setObjectName("SubtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_box.addLayout(title_box)
        header_box.addStretch()

        refresh_btn = QPushButton("🔄 Refresh Disks")
        refresh_btn.clicked.connect(self.load_drives)
        header_box.addWidget(refresh_btn)
        main_layout.addLayout(header_box)

        # Scroll Area with Vertical List Layout
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.list_layout = QVBoxLayout(scroll_content)
        self.list_layout.setSpacing(12)
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        self.load_drives()

    def load_drives(self):
        # Clear existing list items
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        drives = get_connected_drives()
        if not drives:
            empty_lbl = QLabel("No external block devices or USB drives detected.")
            empty_lbl.setObjectName("SubtitleLabel")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_layout.addWidget(empty_lbl)
            return

        for drive in drives:
            row_widget = DriveRow(drive)
            row_widget.drive_selected.connect(self.on_drive_selected)
            row_widget.refresh_requested.connect(self.on_drive_state_changed)
            self.list_layout.addWidget(row_widget)

        self.list_layout.addStretch()

        if self.parent_window and hasattr(self.parent_window, 'refresh_sidebar_drives'):
            self.parent_window.refresh_sidebar_drives()

    def on_drive_state_changed(self):
        self.load_drives()
        if self.parent_window and hasattr(self.parent_window, 'refresh_sidebar_drives'):
            self.parent_window.refresh_sidebar_drives()

    def on_drive_selected(self, drive: dict):
        if self.parent_window:
            self.parent_window.set_selected_drive(drive)
        get_router().navigate("/home")
