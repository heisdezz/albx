import os
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QSlider, QTextEdit, QScrollArea
)
from PySide6.QtCore import Qt
from ui.theme import get_theme_manager, THEMES
from core.gdrive import test_gdrive_connection, backup_to_gdrive
from core.database import get_db_path

class SettingsView(QWidget):
    def __init__(self, parent_window=None, drive: dict = None):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.drive = drive
        self.theme_manager = get_theme_manager()
        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header Title
        title_box = QVBoxLayout()
        title = QLabel("Application Settings & Theme")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("Customize theme palette, UI translucency/opacity, and cloud backups.")
        subtitle.setObjectName("SubtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(16)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Theme & Visual Customization Card
        theme_card = QFrame()
        theme_card.setObjectName("GlassCard")
        tc_layout = QVBoxLayout(theme_card)
        tc_layout.setContentsMargins(20, 20, 20, 20)

        tc_title = QLabel("🎨 Visual Theme & Glassmorphism")
        tc_title.setObjectName("SectionHeader")
        tc_layout.addWidget(tc_title)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Active Color Theme:"))
        self.theme_combo = QComboBox()
        for name in THEMES.keys():
            self.theme_combo.addItem(name)

        self.theme_combo.setCurrentText(self.theme_manager.current_theme_name)
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        theme_row.addWidget(self.theme_combo)
        tc_layout.addLayout(theme_row)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Window Translucency / Opacity:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(40, 100)
        self.opacity_slider.setValue(int(self.theme_manager.opacity * 100))
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        opacity_row.addWidget(self.opacity_slider)

        self.opacity_lbl = QLabel(f"{int(self.theme_manager.opacity * 100)}%")
        opacity_row.addWidget(self.opacity_lbl)
        tc_layout.addLayout(opacity_row)

        scroll_layout.addWidget(theme_card)

        # Google Drive Service Account Card
        gdrive_card = QFrame()
        gdrive_card.setObjectName("GlassCard")
        gc_layout = QVBoxLayout(gdrive_card)
        gc_layout.setContentsMargins(20, 20, 20, 20)

        gc_title = QLabel("☁️ Google Drive Backup Credentials")
        gc_title.setObjectName("SectionHeader")
        gc_layout.addWidget(gc_title)

        gc_sub = QLabel("Paste Service Account JSON key to enable automatic database snapshot backups.")
        gc_sub.setObjectName("SubtitleLabel")
        gc_layout.addWidget(gc_sub)

        self.json_edit = QTextEdit()
        self.json_edit.setPlaceholderText('{\n  "type": "service_account",\n  "project_id": "..."\n}')
        self.json_edit.setFixedHeight(120)
        gc_layout.addWidget(self.json_edit)

        test_btn = QPushButton("Test GDrive Cloud Backup")
        test_btn.setObjectName("AccentButton")
        test_btn.clicked.connect(self.test_gdrive_backup)
        gc_layout.addWidget(test_btn)

        self.backup_status = QLabel("")
        self.backup_status.setObjectName("SubtitleLabel")
        gc_layout.addWidget(self.backup_status)

        scroll_layout.addWidget(gdrive_card)
        scroll_layout.addStretch()

    def on_theme_changed(self, theme_name: str):
        self.theme_manager.set_theme(theme_name)

    def on_opacity_changed(self, val: int):
        fval = val / 100.0
        self.opacity_lbl.setText(f"{val}%")
        self.theme_manager.set_opacity(fval)

    def test_gdrive_backup(self):
        if not self.drive:
            self.backup_status.setText("⚠️ Please select a drive first.")
            return

        db_path = get_db_path(self.drive["path"])
        if not os.path.exists(db_path):
            self.backup_status.setText("⚠️ No database snapshot to upload.")
            return

        service_json = self.json_edit.toPlainText().strip()
        if not service_json:
            self.backup_status.setText("⚠️ Please provide a valid Service Account JSON.")
            return

        try:
            res = backup_to_gdrive(self.drive["path"], service_json)
            if res.get("success"):
                self.backup_status.setText("✅ Snapshot successfully uploaded to Google Drive!")
            else:
                err = res.get("error", "Upload failed.")
                self.backup_status.setText(f"❌ Upload failed: {err}")
        except Exception as e:
            self.backup_status.setText(f"❌ Backup error: {e}")
