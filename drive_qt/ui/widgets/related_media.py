"""Related media section for the media viewer.

A responsive grid of :class:`MediaCard`s listing other files from the same
album as the item currently being viewed. It sizes itself to its full
content (all related rows visible) - the host page is expected to scroll,
so it must not be height-constrained.

Usage::

    related = RelatedMedia(drive=drive, item=item, limit=30)
    viewer_layout.addWidget(related)

Clicking a card navigates to the viewer for that item (and emits
:attr:`RelatedMedia.item_clicked`).
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.database import get_db_path, open_readable_db
from router import get_router
from ui.theme import get_theme_manager
from ui.widgets.media_card import MediaCard
from ui.widgets.media_grid import GridContent


class RelatedMedia(QWidget):
    item_clicked = Signal(dict)

    CARD_TARGET_W = 190  # preferred card width
    CARD_MIN_W = 140
    CARD_MAX_W = 220
    GRID_SPACING = 12

    def __init__(
        self, drive: dict = None, item: dict = None, parent=None, limit: int = 30
    ):
        super().__init__(parent)
        self.drive = drive
        self.item = item or {}
        self.limit = limit
        self.cards = []
        self._last_reflow = None

        self.build_ui()
        self.load_related()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        theme = get_theme_manager().get_theme()

        header = QHBoxLayout()
        header.setSpacing(8)

        title_lbl = QLabel("🗂 Related Media")
        title_lbl.setObjectName("SectionHeader")
        header.addWidget(title_lbl)

        self.count_badge = QLabel("")
        self.count_badge.setStyleSheet(
            f"background-color: {theme['badge_bg']}; color: {theme['badge_fg']}; "
            "font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 8px;"
        )
        header.addWidget(self.count_badge)
        header.addStretch()
        layout.addLayout(header)

        self.content = GridContent()
        self.content.resized.connect(self.reflow_grid)
        self.grid_layout = QGridLayout(self.content)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(self.GRID_SPACING)
        layout.addWidget(self.content)

    def load_related(self):
        self.cards.clear()
        self._last_reflow = None
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.drive:
            self._set_empty("No related media found.")
            return

        drive_path = self.drive.get("path")
        item_id = self.item.get("id")
        if not drive_path or not item_id:
            self._set_empty("No related media found.")
            return

        db_path = get_db_path(drive_path)
        if not os.path.exists(db_path):
            self._set_empty("No media library found.")
            return

        conn = open_readable_db(db_path)
        if not conn:
            return

        try:
            cursor = conn.cursor()
            # Other files in the same album as the item being viewed.
            cursor.execute(
                """
                SELECT id, current_relative_path, mime_type, file_size,
                       created_at, file_hash
                FROM media_items
                WHERE album_id = (SELECT album_id FROM media_items WHERE id = ?)
                  AND id != ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (item_id, item_id, self.limit),
            )
            rows = cursor.fetchall()
        except Exception as e:
            print(f"[RelatedMedia] Error querying DB: {e}")
            rows = []
        finally:
            conn.close()

        if not rows:
            self._set_empty("No related media found in this album.")
            return

        self.count_badge.setText(str(len(rows)))

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
            card.card_clicked.connect(self.open_item)
            self.cards.append(card)

        self.reflow_grid()

    def _set_empty(self, message: str):
        self.count_badge.setText("")
        lbl = QLabel(message)
        lbl.setObjectName("SubtitleLabel")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid_layout.addWidget(lbl, 0, 0)

    def open_item(self, item: dict):
        self.item_clicked.emit(item)
        get_router().navigate("/viewer", {"item": item})

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # GridContent.resized is the primary reflow driver; this is a cheap
        # safety net for the case where the view resizes before content
        # catches up.
        self.reflow_grid()

    def reflow_grid(self):
        if not self.cards:
            return

        avail_w = self.content.width()
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
