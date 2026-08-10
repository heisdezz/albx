import os
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QComboBox, QInputDialog, QMessageBox, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, Signal, QPoint, QRect
from PySide6.QtGui import QPixmap
from core.database import open_readable_db, get_db_path
from core.media_ops import create_album, delete_album
from ui.widgets.search_bar import SearchBarWidget
from ui.theme import get_theme_manager
from router import get_router

class AlbumCard(QFrame):
    def __init__(self, album_id: int, name: str, count: int, cover_path: str = None, parent_view=None):
        super().__init__()
        self.album_id = album_id
        self.name = name
        self.count = count
        self.cover_path = cover_path
        self.parent_view = parent_view
        self.selected = False
        self.setObjectName("GlassCard")
        self.setFixedSize(220, 200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)

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

        # Enforce name translation for "unknown" default album
        display_name = "Unsorted Media" if self.name == "unknown" else self.name
        title = QLabel(display_name)
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(f"{self.count} items")
        subtitle.setObjectName("SubtitleLabel")
        layout.addWidget(subtitle)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.parent_view and self.parent_view.is_selecting:
                if self.name == "unknown":
                    return # default album cannot be selected/deleted
                self.toggle_selection()
            else:
                get_router().navigate("/media", {"album": self.name})

    def toggle_selection(self):
        self.set_selected(not self.selected)
        if self.parent_view:
            self.parent_view.on_card_selection_toggled(self.album_id, self.selected)

    def set_selected(self, selected: bool):
        self.selected = selected
        t = get_theme_manager().get_theme()
        if selected:
            accent = t.get("accent", "#ff9900")
            accent_dim = t.get("accent_dim", "rgba(255, 153, 0, 0.15)")
            self.setStyleSheet(
                f"QFrame#GlassCard {{ border: 2px solid {accent}; background-color: {accent_dim}; }}"
            )
        else:
            self.setStyleSheet("")

    def update_select_mode(self, is_selecting: bool):
        if self.name == "unknown":
            if is_selecting:
                self.opacity_effect.setOpacity(0.5)
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.opacity_effect.setOpacity(1.0)
                self.setCursor(Qt.CursorShape.PointingHandCursor)

class AlbumFilterBar(QFrame):
    filter_changed = Signal(dict)
    create_clicked = Signal()
    delete_clicked = Signal()
    selection_mode_changed = Signal(bool)
    select_all_clicked = Signal()
    clear_selection_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self.sort_by = "name"
        self.sort_order = "asc"
        self.search_query = ""
        self.is_selecting = False
        self.build_ui()

    def build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Left Section: Sort Dropdown + Direction Toggle + Select Mode Toggle + Actions
        left_box = QHBoxLayout()
        left_box.setSpacing(8)

        left_box.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Name", "name")
        self.sort_combo.addItem("Size (Items)", "size")
        self.sort_combo.addItem("Date Created", "date")
        self.sort_combo.setFixedWidth(120)
        self.sort_combo.currentIndexChanged.connect(self.on_sort_changed)
        left_box.addWidget(self.sort_combo)

        self.sort_btn = QPushButton("ASC ↑")
        self.sort_btn.setFixedWidth(80)
        self.sort_btn.clicked.connect(self.toggle_sort_order)
        left_box.addWidget(self.sort_btn)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setStyleSheet("color: rgba(255, 255, 255, 0.1);")
        left_box.addWidget(sep)

        # Select Mode Toggle Button
        self.select_btn = QPushButton("☑ Select Mode")
        self.select_btn.clicked.connect(self.toggle_selection_mode)
        left_box.addWidget(self.select_btn)

        # Bulk Actions
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all_clicked.emit)
        self.select_all_btn.hide()
        left_box.addWidget(self.select_all_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_selection_clicked.emit)
        self.clear_btn.hide()
        left_box.addWidget(self.clear_btn)

        self.delete_btn = QPushButton("🗑 Delete")
        self.delete_btn.setObjectName("DestructiveButton")
        self.delete_btn.clicked.connect(self.delete_clicked.emit)
        self.delete_btn.setEnabled(False)
        self.delete_btn.hide()
        left_box.addWidget(self.delete_btn)

        layout.addLayout(left_box)
        layout.addStretch()

        # Right Section: Create Album Button + SearchBarWidget
        right_box = QHBoxLayout()
        right_box.setSpacing(10)

        self.create_btn = QPushButton("➕ Create Album")
        self.create_btn.setObjectName("AccentButton")
        self.create_btn.clicked.connect(self.create_clicked.emit)
        right_box.addWidget(self.create_btn)

        self.search_widget = SearchBarWidget(placeholder="Search albums...", delay_ms=400)
        self.search_widget.setFixedWidth(240)
        self.search_widget.search_triggered.connect(self.on_search_triggered)
        right_box.addWidget(self.search_widget)

        layout.addLayout(right_box)

    def on_sort_changed(self, idx: int):
        self.sort_by = self.sort_combo.currentData()
        self.notify_change()

    def toggle_sort_order(self):
        self.sort_order = "desc" if self.sort_order == "asc" else "asc"
        self.sort_btn.setText("DESC ↓" if self.sort_order == "desc" else "ASC ↑")
        self.notify_change()

    def on_search_triggered(self, query: str):
        self.search_query = query.strip()
        self.notify_change()

    def toggle_selection_mode(self):
        self.is_selecting = not self.is_selecting
        self.select_btn.setText("Cancel" if self.is_selecting else "☑ Select Mode")
        
        # Style changes based on active selection mode
        t = get_theme_manager().get_theme()
        accent = t.get("accent", "#ff9900")
        if self.is_selecting:
            self.select_btn.setStyleSheet(
                f"background-color: rgba(255, 153, 0, 0.15); color: {accent}; border-color: {accent};"
            )
        else:
            self.select_btn.setStyleSheet("")

        self.select_all_btn.setVisible(self.is_selecting)
        self.clear_btn.setVisible(self.is_selecting)
        self.delete_btn.setVisible(self.is_selecting)
        self.create_btn.setVisible(not self.is_selecting)
        self.selection_mode_changed.emit(self.is_selecting)

    def set_selected_count(self, count: int):
        self.delete_btn.setText(f"🗑 Delete ({count})")
        self.delete_btn.setEnabled(count > 0)

    def exit_selection_mode(self):
        if self.is_selecting:
            self.toggle_selection_mode()

    def notify_change(self):
        self.filter_changed.emit({
            "sort_by": self.sort_by,
            "sort_order": self.sort_order,
            "search_query": self.search_query
        })

class AlbumsView(QWidget):
    def __init__(self, parent_window=None, drive: dict = None):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.drive = drive
        self.search_term = ""
        self.sort_by = "name"
        self.sort_order = "asc"
        self.is_selecting = False
        self.selected_albums = set()
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
        layout.addLayout(hdr_row)

        # Add custom Filter Bar
        self.filter_bar = AlbumFilterBar(self)
        self.filter_bar.filter_changed.connect(self.on_filter_changed)
        self.filter_bar.create_clicked.connect(self.on_create_album_clicked)
        self.filter_bar.delete_clicked.connect(self.on_delete_selected_clicked)
        self.filter_bar.selection_mode_changed.connect(self.on_selection_mode_changed)
        self.filter_bar.select_all_clicked.connect(self.on_select_all_clicked)
        self.filter_bar.clear_selection_clicked.connect(self.on_clear_selection_clicked)
        layout.addWidget(self.filter_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        self.grid_layout = QGridLayout(scroll_content)
        self.grid_layout.setSpacing(16)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

      # Stop active view selection on navigation
    def stop_playback(self):
        if self.filter_bar:
            self.filter_bar.exit_selection_mode()

    def on_filter_changed(self, filter_data: dict):
        self.search_term = filter_data["search_query"].lower()
        self.sort_by = filter_data["sort_by"]
        self.sort_order = filter_data["sort_order"]
        self.load_albums()

    def on_selection_mode_changed(self, is_selecting: bool):
        self.is_selecting = is_selecting
        self.selected_albums.clear()
        self.filter_bar.set_selected_count(0)

        # Update existing cards in grid
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), AlbumCard):
                card = item.widget()
                card.set_selected(False)
                card.update_select_mode(is_selecting)

    def on_card_selection_toggled(self, album_id: int, is_selected: bool):
        if is_selected:
            self.selected_albums.add(album_id)
        else:
            self.selected_albums.discard(album_id)
        self.filter_bar.set_selected_count(len(self.selected_albums))

    def on_select_all_clicked(self):
        self.selected_albums.clear()
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), AlbumCard):
                card = item.widget()
                if card.name != "unknown":
                    card.set_selected(True)
                    self.selected_albums.add(card.album_id)
        self.filter_bar.set_selected_count(len(self.selected_albums))

    def on_clear_selection_clicked(self):
        self.selected_albums.clear()
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), AlbumCard):
                card = item.widget()
                card.set_selected(False)
        self.filter_bar.set_selected_count(0)

    def on_create_album_clicked(self):
        if not self.drive:
            QMessageBox.warning(self, "No Drive", "Please load a drive first.")
            return

        name, ok = QInputDialog.getText(
            self, "Create Album", "Enter new album name:"
        )
        if ok and name.strip():
            success, err = create_album(self.drive.get("path"), name.strip())
            if success:
                self.load_albums()
            else:
                QMessageBox.warning(self, "Error Creating Album", err)

    def on_delete_selected_clicked(self):
        if not self.selected_albums or not self.drive:
            return

        # Premium custom dialog to let user choose Keep vs Delete media items
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Albums")
        msg.setText(f"Delete {len(self.selected_albums)} selected album(s)?")
        msg.setInformativeText(
            "Choose whether to keep the media files (they will be moved to Unsorted Media) "
            "or permanently delete the files from disk."
        )

        keep_btn = msg.addButton("Keep Media Files", QMessageBox.ButtonRole.YesRole)
        delete_btn = msg.addButton("Delete Files from Disk", QMessageBox.ButtonRole.RejectRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(cancel_btn)

        msg.exec()

        if msg.clickedButton() == keep_btn:
            delete_media = False
        elif msg.clickedButton() == delete_btn:
            confirm = QMessageBox.question(
                self,
                "Confirm Permanent Deletion",
                "Are you absolutely sure you want to permanently delete all files in the selected albums from disk?\n\nThis action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            delete_media = True
        else:
            return

        drive_path = self.drive.get("path")
        success_count = 0
        all_errors = []

        # Copy list of IDs to prevent mutation during deletion / view reload
        album_ids = list(self.selected_albums)

        for album_id in album_ids:
            success, err, file_errs = delete_album(drive_path, album_id, delete_media)
            if success:
                success_count += 1
              # Remove from selected set once successfully deleted
                self.selected_albums.discard(album_id)
            else:
                all_errors.append(f"Album ID {album_id}: {err}")
            if file_errs:
                all_errors.extend(file_errs)

        self.filter_bar.exit_selection_mode()
        self.load_albums()

        if all_errors:
            QMessageBox.warning(
                self,
                "Deletion completed with errors",
                f"Successfully deleted {success_count} album(s).\n\n"
                + "\n".join(all_errors[:8])
                + ("\n…" if len(all_errors) > 8 else "")
            )

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

            # Query the latest image/video for each album to use as cover thumbnail
            preview_query = """
                SELECT album_id, file_hash, current_relative_path
                FROM (
                    SELECT album_id, file_hash, current_relative_path,
                           ROW_NUMBER() OVER (PARTITION BY album_id ORDER BY created_at DESC, id DESC) AS rn
                    FROM media_items
                )
                WHERE rn = 1
            """
            cursor.execute(preview_query)
            previews = {row[0]: (row[1], row[2]) for row in cursor.fetchall() if row[0] is not None}

            # Query all albums with pre-calculated media_count (instantaneous!) and created_at
            query = """
                SELECT id, name, relative_path, media_count, created_at
                FROM albums
            """
            cursor.execute(query)
            rows = cursor.fetchall()

            albums_list = []
            for row in rows:
                album_id, name, rel_path, count, created_at = row
                
                # Verify and map search query
                display_name = "Unsorted Media" if name == "unknown" else name
                if self.search_term and self.search_term not in display_name.lower():
                    continue
                    
                albums_list.append({
                    "id": album_id,
                    "name": name,
                    "display_name": display_name,
                    "relative_path": rel_path,
                    "media_count": count,
                    "created_at": created_at
                })

            # Sort in Python
            is_desc = (self.sort_order == "desc")
            if self.sort_by == "name":
                albums_list.sort(key=lambda x: x["display_name"].lower(), reverse=is_desc)
            elif self.sort_by == "size":
                albums_list.sort(key=lambda x: x["media_count"], reverse=is_desc)
            elif self.sort_by == "date":
                albums_list.sort(key=lambda x: x["created_at"] or "", reverse=is_desc)

            r, c = 0, 0
            for a in albums_list:
                album_id = a["id"]
                name = a["name"]
                count = a["media_count"]

                cover_path = None
                if album_id in previews:
                    file_hash, curr_rel = previews[album_id]
                    # Check for generated thumbnail
                    thumb_p = os.path.join(drive_path, "albums", "thumbs", f"{file_hash}.jpg")
                    if os.path.exists(thumb_p):
                        cover_path = thumb_p
                    else:
                        # Fallback to actual media path if it's an image
                        full_p = os.path.join(drive_path, curr_rel)
                        if os.path.exists(full_p) and curr_rel.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                            cover_path = full_p

                card = AlbumCard(album_id, name, count, cover_path, self)
                card.update_select_mode(self.is_selecting)
                if album_id in self.selected_albums:
                    card.set_selected(True)

                self.grid_layout.addWidget(card, r, c)
                c += 1
                if c >= 4:
                    c = 0
                    r += 1
        except Exception as e:
            print(f"[AlbumsView] Error: {e}")
        finally:
            conn.close()
