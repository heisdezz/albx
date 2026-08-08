import os
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from core.database import open_readable_db, get_db_path
from ui.widgets.search_bar import SearchBarWidget
from router import get_router

class AlbumCard(QFrame):
    def __init__(self, name: str, count: int, cover_path: str = None):
        super().__init__()
        self.name = name
        self.count = count
        self.cover_path = cover_path
        self.setObjectName("GlassCard")
        self.setFixedSize(220, 200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.img_lbl = QLabel()
        self.img_lbl.setFixedHeight(120)
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setStyleSheet("background-color: rgba(0, 0, 0, 0.3); border-radius: 8px;")

        if self.cover_path and os.path.exists(self.cover_path):
            pix = QPixmap(self.cover_path)
            if not pix.isNull():
                self.img_lbl.setPixmap(pix.scaled(200, 120, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            else:
                self.img_lbl.setText("📁")
                self.img_lbl.setStyleSheet("font-size: 36px;")
        else:
            self.img_lbl.setText("📁")
            self.img_lbl.setStyleSheet("font-size: 36px;")

        layout.addWidget(self.img_lbl)

        title = QLabel(self.name)
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(f"{self.count} items")
        subtitle.setObjectName("SubtitleLabel")
        layout.addWidget(subtitle)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            get_router().navigate("/media", {"album": self.name})

class AlbumsView(QWidget):
    def __init__(self, parent_window=None, drive: dict = None):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.drive = drive
        self.search_term = ""
        self.build_ui()
        self.load_albums()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        hdr_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Album Collections")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("Browse cataloged media grouped into album subfolders.")
        subtitle.setObjectName("SubtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hdr_row.addLayout(title_box, 1)

        self.search_bar = SearchBarWidget("🔍 Search albums...", delay_ms=500)
        self.search_bar.setFixedWidth(280)
        self.search_bar.search_triggered.connect(self.on_search_changed)
        hdr_row.addWidget(self.search_bar)
        layout.addLayout(hdr_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        self.grid_layout = QGridLayout(scroll_content)
        self.grid_layout.setSpacing(16)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

    def on_search_changed(self, text: str):
        self.search_term = text.lower()
        self.load_albums()

    def load_albums(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.drive:
            empty = QLabel("No drive loaded.")
            empty.setObjectName("SubtitleLabel")
            self.grid_layout.addWidget(empty, 0, 0)
            return

        drive_path = self.drive.get("path")
        db_path = get_db_path(drive_path)
        if not os.path.exists(db_path):
            empty = QLabel("No media database found.")
            empty.setObjectName("SubtitleLabel")
            self.grid_layout.addWidget(empty, 0, 0)
            return

        conn = open_readable_db(db_path)
        if not conn:
            return

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT current_relative_path FROM media_items")
            rows = cursor.fetchall()

            albums = {}
            for r in rows:
                rel = r[0].replace("\\", "/")
                parts = rel.split("/")
                album_name = parts[0] if len(parts) > 1 else "Uncategorized"
                albums[album_name] = albums.get(album_name, 0) + 1

            r, c = 0, 0
            for name, count in albums.items():
                if self.search_term and self.search_term not in name.lower():
                    continue
                card = AlbumCard(name, count)
                self.grid_layout.addWidget(card, r, c)
                c += 1
                if c >= 4:
                    c = 0
                    r += 1
        except Exception as e:
            print(f"[AlbumsView] Error: {e}")
        finally:
            conn.close()
