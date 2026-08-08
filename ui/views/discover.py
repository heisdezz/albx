import os
import json
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QProgressBar, QTextEdit, QLineEdit, QScrollArea, QGridLayout
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from core.scanner import ScanState, active_scans, walk_directory
from core.logger import get_logs
from core.database import get_db_path

def load_ignore_list(drive_path: str) -> list:
    settings_file = os.path.join(drive_path, "albums", ".media_library_settings.json")
    default_ignores = ["temp", "cache", "raw", "backups", "archive", "node_modules", "dist", "build"]
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                data = json.load(f)
                return data.get("ignoreList", default_ignores)
        except Exception:
            return default_ignores
    return default_ignores

def save_ignore_list(drive_path: str, ignore_list: list) -> None:
    settings_file = os.path.join(drive_path, "albums", ".media_library_settings.json")
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)
    try:
        with open(settings_file, "w") as f:
            json.dump({"ignoreList": ignore_list}, f, indent=2)
    except Exception as e:
        print(f"[Settings] Failed to save ignore list: {e}")

class ScanWorker(QThread):
    progress = Signal(int, int, str)
    finished_scan = Signal()

    def __init__(self, drive_path: str, db_path: str, scan_state: ScanState, ignore_list: list):
        super().__init__()
        self.drive_path = drive_path
        self.db_path = db_path
        self.scan_state = scan_state
        self.ignore_list = ignore_list

    def run(self):
        walk_directory(
            drive_path=self.drive_path,
            start_dir=self.drive_path,
            db_path=self.db_path,
            scan_state=self.scan_state,
            ignore_list=self.ignore_list,
            progress_callback=lambda f_scanned, m_found, cur_file: self.progress.emit(f_scanned, m_found, cur_file)
        )
        self.finished_scan.emit()

class DiscoverView(QWidget):
    def __init__(self, parent_window=None, drive: dict = None):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.drive = drive
        self.ignore_list = load_ignore_list(drive["path"]) if drive else []
        self.scan_worker = None
        self.scan_state = None

        self.build_ui()

        # Log timer
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(1000)
        self.log_timer.timeout.connect(self.update_logs)
        self.log_timer.start()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header Title
        title_box = QVBoxLayout()
        title = QLabel("Media Discovery & Catalog Scanner")
        title.setObjectName("TitleLabel")

        path_str = self.drive.get("path", "No Drive Loaded") if self.drive else "No Drive Loaded"
        subtitle = QLabel(f"Scan directory tree, filter ignored paths, and index media into SQLite database: {path_str}")
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

        # Controller Card
        ctrl_card = QFrame()
        ctrl_card.setObjectName("GlassCard")
        cc_layout = QVBoxLayout(ctrl_card)
        cc_layout.setContentsMargins(20, 20, 20, 20)

        # Stats Grid
        stats_grid = QGridLayout()
        stats_grid.setSpacing(16)

        self.scanned_lbl = QLabel("0")
        self.scanned_lbl.setStyleSheet("font-size: 20px; font-weight: 800;")
        stats_grid.addWidget(QLabel("Files Processed:"), 0, 0)
        stats_grid.addWidget(self.scanned_lbl, 0, 1)

        self.found_lbl = QLabel("0")
        self.found_lbl.setStyleSheet("font-size: 20px; font-weight: 800; color: #a6e3a1;")
        stats_grid.addWidget(QLabel("Media Cataloged:"), 0, 2)
        stats_grid.addWidget(self.found_lbl, 0, 3)

        cc_layout.addLayout(stats_grid)

        # Progress Bar & Current File Label
        self.cur_file_lbl = QLabel("Idle")
        self.cur_file_lbl.setObjectName("SubtitleLabel")
        cc_layout.addWidget(self.cur_file_lbl)

        self.pbar = QProgressBar()
        self.pbar.setValue(0)
        cc_layout.addWidget(self.pbar)

        # Action Buttons
        btn_box = QHBoxLayout()
        self.start_btn = QPushButton("🚀 Start Discovery Scan")
        self.start_btn.setObjectName("AccentButton")
        self.start_btn.clicked.connect(self.on_start_scan)
        btn_box.addWidget(self.start_btn)

        self.stop_btn = QPushButton("🛑 Cancel Scan")
        self.stop_btn.setObjectName("DestructiveButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.on_stop_scan)
        btn_box.addWidget(self.stop_btn)

        cc_layout.addLayout(btn_box)
        scroll_layout.addWidget(ctrl_card)

        # Ignore List Card
        ignore_card = QFrame()
        ignore_card.setObjectName("GlassCard")
        ic_layout = QVBoxLayout(ignore_card)
        ic_layout.setContentsMargins(20, 20, 20, 20)

        ic_title = QLabel("Ignored Folders & Patterns")
        ic_title.setObjectName("SectionHeader")
        ic_layout.addWidget(ic_title)

        add_box = QHBoxLayout()
        self.ignore_input = QLineEdit()
        self.ignore_input.setPlaceholderText("Add pattern (e.g. node_modules, temp, raw)...")
        self.ignore_input.returnPressed.connect(self.add_ignore_rule)
        add_box.addWidget(self.ignore_input)

        add_btn = QPushButton("Add Filter")
        add_btn.clicked.connect(self.add_ignore_rule)
        add_box.addWidget(add_btn)
        ic_layout.addLayout(add_box)

        self.tags_layout = QHBoxLayout()
        self.render_ignore_tags()
        ic_layout.addLayout(self.tags_layout)

        scroll_layout.addWidget(ignore_card)

        # Activity Log Card
        log_card = QFrame()
        log_card.setObjectName("GlassCard")
        lc_layout = QVBoxLayout(log_card)
        lc_layout.setContentsMargins(20, 20, 20, 20)

        lc_title = QLabel("Live Activity Log Stream")
        lc_title.setObjectName("SectionHeader")
        lc_layout.addWidget(lc_title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: monospace; font-size: 11px;")
        lc_layout.addWidget(self.log_text)

        scroll_layout.addWidget(log_card)

    def render_ignore_tags(self):
        # Clear tags
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for pattern in self.ignore_list:
            btn = QPushButton(f"❌ {pattern}")
            btn.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.08); font-size: 11px; padding: 4px 8px; border-radius: 4px;"
            )
            btn.clicked.connect(lambda p=pattern: self.remove_ignore_rule(p))
            self.tags_layout.addWidget(btn)
        self.tags_layout.addStretch()

    def add_ignore_rule(self):
        text = self.ignore_input.text().strip()
        if text and text not in self.ignore_list:
            self.ignore_list.append(text)
            self.ignore_input.clear()
            if self.drive:
                save_ignore_list(self.drive["path"], self.ignore_list)
            self.render_ignore_tags()

    def remove_ignore_rule(self, pattern: str):
        if pattern in self.ignore_list:
            self.ignore_list.remove(pattern)
            if self.drive:
                save_ignore_list(self.drive["path"], self.ignore_list)
            self.render_ignore_tags()

    def on_start_scan(self):
        if not self.drive:
            return

        drive_path = self.drive["path"]
        db_path = get_db_path(drive_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.scan_state = ScanState(root_path=drive_path)
        active_scans[drive_path] = self.scan_state

        self.scan_worker = ScanWorker(
            drive_path=drive_path,
            db_path=db_path,
            scan_state=self.scan_state,
            ignore_list=self.ignore_list
        )
        self.scan_worker.progress.connect(self.on_scan_progress)
        self.scan_worker.finished_scan.connect(self.on_scan_finished)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.pbar.setValue(10)
        self.scan_worker.start()

    def on_scan_progress(self, files_scanned: int, media_found: int, cur_file: str):
        self.scanned_lbl.setText(f"{files_scanned:,}")
        self.found_lbl.setText(f"{media_found:,}")
        self.cur_file_lbl.setText(f"Scanning: {cur_file}")

    def on_scan_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pbar.setValue(100)
        self.cur_file_lbl.setText("Scan completed successfully!")

    def on_stop_scan(self):
        if self.scan_state:
            self.scan_state.scanning = False
        if self.scan_worker:
            self.scan_worker.terminate()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.cur_file_lbl.setText("Scan cancelled.")

    def update_logs(self):
        logs = get_logs(limit=25)
        text = "\n".join([f"[{l['timestamp']}] [{l['level'].upper()}] {l['message']}" for l in logs])
        self.log_text.setText(text)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
