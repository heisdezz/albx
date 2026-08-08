import math
import os

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.database import get_db_path, open_readable_db
from router import get_router
from ui.widgets.filter_bar import FilterBarWidget
from ui.widgets.media_card import MediaCard
from ui.widgets.paginator import FloatingPaginator


class GridContent(QWidget):
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class MediaGridView(QWidget):
    CARD_TARGET_W = 200
    CARD_MIN_W = 140
    CARD_MAX_W = 240
    GRID_SPACING = 14

    def __init__(
        self, parent_window=None, drive: dict = None, filter_type: str = "ALL"
    ):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.drive = drive
        self.current_filter = filter_type
        self.sort_by = "date"
        self.sort_order = "desc"
        self.search_term = ""

        self.page = 1
        self.page_size = 40
        self.total_count = 0
        self.total_pages = 1

        self.cards = []
        self._last_reflow = None

        self.build_ui()
        self.load_media()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # Reusable Filter Bar Widget
        self.filter_bar = FilterBarWidget(
            filter_type=self.current_filter,
            sort_by=self.sort_by,
            sort_order=self.sort_order,
        )
        self.filter_bar.filter_changed.connect(self.on_filter_bar_changed)
        main_layout.addWidget(self.filter_bar)

        # Grid Scroll Container Box
        grid_container = QWidget()
        gc_layout = QVBoxLayout(grid_container)
        gc_layout.setContentsMargins(0, 0, 0, 0)
        gc_layout.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.scroll_content = GridContent()
        self.scroll_content.resized.connect(self.reflow_grid)
        self.grid_layout = QGridLayout(self.scroll_content)
        # Bottom margin keeps the last row clear of the floating paginator.
        self.grid_layout.setContentsMargins(0, 0, 0, 72)
        self.grid_layout.setSpacing(self.GRID_SPACING)
        self.scroll.setWidget(self.scroll_content)
        gc_layout.addWidget(self.scroll, 1)

        # Floating paginator - overlaid on the scroll viewport (bottom-center).
        self.paginator = FloatingPaginator()
        self.paginator.setParent(self.scroll.viewport())
        self.paginator.page_changed.connect(self.on_page_changed)
        self.scroll.viewport().installEventFilter(self)
        self.paginator.hide()

        main_layout.addWidget(grid_container, 1)

    def on_filter_bar_changed(self, data: dict):
        self.current_filter = data.get("filter_type", "ALL")
        self.sort_by = data.get("sort_by", "date")
        self.sort_order = data.get("sort_order", "desc")
        self.search_term = data.get("search_query", "")

        self.page = 1
        self.load_media()

    def on_page_changed(self, new_page: int):
        self.page = new_page
        self.load_media()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow_grid()

    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._position_paginator()
        return super().eventFilter(obj, event)

    def _position_paginator(self):
        if not hasattr(self, "paginator") or not self.paginator.isVisible():
            return
        viewport = self.scroll.viewport()
        hint = self.paginator.sizeHint()
        x = max(0, (viewport.width() - hint.width()) // 2)
        y = max(0, viewport.height() - hint.height() - 16)
        self.paginator.setGeometry(x, y, hint.width(), hint.height())
        self.paginator.raise_()

    def reflow_grid(self):
        if not self.cards:
            return

        avail_w = self.scroll.viewport().width()
        spacing = self.GRID_SPACING

        cols = max(1, round(avail_w / (self.CARD_TARGET_W + spacing)))
        while cols > 1 and (avail_w - (cols - 1) * spacing) // cols < self.CARD_MIN_W:
            cols -= 1

        if cols == 1:
            card_w = min(max(avail_w, 1), self.CARD_MAX_W)
        else:
            card_w = min((avail_w - (cols - 1) * spacing) // cols, self.CARD_MAX_W)

        card_h = max(int(card_w * MediaCard.HEIGHT_RATIO), MediaCard.MIN_H)

        key = (cols, card_w, card_h)
        if key == self._last_reflow:
            return
        self._last_reflow = key

        for i, card in enumerate(self.cards):
            card.setFixedSize(card_w, card_h)
            row, col = divmod(i, cols)
            self.grid_layout.addWidget(card, row, col)

    def load_media(self):
        self.cards.clear()
        self._last_reflow = None
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.drive:
            empty_lbl = QLabel("No active drive loaded.")
            empty_lbl.setObjectName("SubtitleLabel")
            self.grid_layout.addWidget(empty_lbl, 0, 0)
            self.filter_bar.set_total_items(0)
            self.paginator.update_pagination(1, 1)
            return

        drive_path = self.drive.get("path")
        db_path = get_db_path(drive_path)
        if not os.path.exists(db_path):
            empty_lbl = QLabel(
                "No media library found. Please run a Discovery Scan first."
            )
            empty_lbl.setObjectName("SubtitleLabel")
            self.grid_layout.addWidget(empty_lbl, 0, 0)
            self.filter_bar.set_total_items(0)
            self.paginator.update_pagination(1, 1)
            return

        conn = open_readable_db(db_path)
        if not conn:
            return

        try:
            cursor = conn.cursor()
            base_where = " WHERE 1=1"
            params = []

            if self.current_filter == "IMAGE":
                base_where += " AND mime_type LIKE 'image/%'"
            elif self.current_filter == "VIDEO":
                base_where += " AND mime_type LIKE 'video/%'"

            if self.search_term:
                base_where += " AND current_relative_path LIKE ?"
                params.append(f"%{self.search_term}%")

            # Query Total Count
            count_sql = f"SELECT COUNT(*) FROM media_items{base_where}"
            cursor.execute(count_sql, params)
            self.total_count = cursor.fetchone()[0]

            self.total_pages = max(1, math.ceil(self.total_count / self.page_size))
            self.page = max(1, min(self.page, self.total_pages))

            self.filter_bar.set_total_items(self.total_count)
            self.paginator.update_pagination(self.page, self.total_pages)
            self._position_paginator()

            if self.total_count == 0:
                empty_lbl = QLabel("No media items found matching filter criteria.")
                empty_lbl.setObjectName("SubtitleLabel")
                self.grid_layout.addWidget(empty_lbl, 0, 0)
                return

            # Determine Sort Column
            sort_col = "created_at"
            if self.sort_by == "name":
                sort_col = "current_relative_path"
            elif self.sort_by == "size":
                sort_col = "file_size"

            sort_direction = "DESC" if self.sort_order == "desc" else "ASC"

            offset = (self.page - 1) * self.page_size
            query_sql = f"SELECT id, current_relative_path, mime_type, file_size, created_at, file_hash FROM media_items{base_where} ORDER BY {sort_col} {sort_direction} LIMIT {self.page_size} OFFSET {offset}"

            cursor.execute(query_sql, params)
            rows = cursor.fetchall()

            for row in rows:
                item_dict = {
                    "id": row[0],
                    "current_relative_path": row[1],
                    "mime_type": row[2],
                    "file_size": row[3],
                    "created_at": row[4],
                    "file_hash": row[5] if len(row) > 5 else None,
                }
                card = MediaCard(item_dict, drive_path)
                card.card_clicked.connect(self.open_viewer)
                self.cards.append(card)

            self.reflow_grid()

        except Exception as e:
            print(f"[MediaGrid] Error querying DB: {e}")
        finally:
            conn.close()

    def open_viewer(self, item: dict):
        get_router().navigate("/viewer", {"item": item})
