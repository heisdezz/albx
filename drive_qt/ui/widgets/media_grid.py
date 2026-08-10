"""Reusable media grid widget.

A filterable, sortable, searchable, paginated grid of :class:`MediaCard`s. It
can be used either as a standalone scrollable view (with the filter bar and a
floating paginator overlaid on the scroll viewport) or as a flat, self-sizing
section inside a host that manages its own scrolling (no inner scroll area,
no paginator).

Usage (standalone view, as in the media route)::

    grid = MediaGridView(drive=drive, filter_type="ALL")
    grid.item_clicked.connect(on_item)   # optional extra handler

Usage (embedded section, e.g. a dashboard)::

    grid = MediaGridView(
        drive=drive, page_size=8, show_filter_bar=False, scrollable=False
    )
    host_layout.addWidget(grid)

Clicking a card emits :attr:`MediaGridView.item_clicked`; by default the
widget then navigates to the viewer through the router, or a custom handler
can be supplied via `on_item_clicked`.
"""

import math
import os

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, QPoint, QRect
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.database import get_db_path, open_readable_db
from core.media_ops import delete_media_items, list_albums, move_media_items
from router import get_router
from ui.selection_store import get_selection_store
from ui.widgets.filter_bar import FilterBarWidget
from ui.widgets.media_card import MediaCard
from ui.widgets.move_to_album_dialog import MoveToAlbumDialog
from ui.widgets.paginator import FloatingPaginator


class GridContent(QWidget):
    """Scroll content that emits a signal whenever it is resized.

    With `setWidgetResizable(True)` the scroll area keeps this widget's width
    in sync with the viewport, so this is the most reliable resize hook: the
    outer view can miss resize events entirely (for example when the vertical
    scrollbar appears/disappears and only the viewport width changes), while
    the content widget is resized every time.
    """

    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class MediaGridView(QWidget):
    CARD_TARGET_W = 200  # preferred card width
    CARD_MIN_W = 140
    CARD_MAX_W = 240
    GRID_SPACING = 14
    # Bottom padding inside the grid so the floating paginator never covers
    # the last row (scrollable mode only).
    BOTTOM_PADDING = 72

    item_clicked = Signal(dict)

    # Class-level cache variables to persist state across instances
    _cached_drive_path = None
    _cached_filter_type = "ALL"
    _cached_sort_by = "date"
    _cached_sort_order = "desc"
    _cached_search_term = ""
    _cached_page = 1

    def __init__(
        self,
        parent=None,
        drive: dict = None,
        filter_type: str = "ALL",
        page_size: int = 40,
        show_filter_bar: bool = True,
        scrollable: bool = True,
        on_item_clicked=None,
        album_name: str = None,
    ):
        super().__init__(parent)
        self.parent_window = parent
        self.drive = drive

        # Check if the drive changed to reset cache
        drive_path = drive.get("path") if drive else None
        if drive_path != MediaGridView._cached_drive_path:
            MediaGridView._cached_drive_path = drive_path
            MediaGridView._cached_filter_type = "ALL"
            MediaGridView._cached_sort_by = "date"
            MediaGridView._cached_sort_order = "desc"
            MediaGridView._cached_search_term = ""
            MediaGridView._cached_page = 1

        # If a non-default filter_type was explicitly requested (e.g. via sidebar/Dashboard), update cache
        if filter_type != "ALL":
            MediaGridView._cached_filter_type = filter_type
            MediaGridView._cached_page = 1
            MediaGridView._cached_search_term = ""

        self.current_filter = MediaGridView._cached_filter_type
        self.album_filter = album_name
        self.sort_by = MediaGridView._cached_sort_by
        self.sort_order = MediaGridView._cached_sort_order
        self.search_term = MediaGridView._cached_search_term
        self.page = MediaGridView._cached_page

        self.page_size = page_size
        self.total_count = 0
        self.total_pages = 1

        self.cards = []
        self._last_reflow = None

        self.show_filter_bar = show_filter_bar
        self.scrollable = scrollable
        self.filter_bar = None
        self.scroll = None
        self.paginator = None
        self.action_bar = None
        self.select_btn = None
        self.select_all_btn = None
        self._on_item_clicked = on_item_clicked

        self.build_ui()
        self.load_media()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        if self.scrollable:
            # Standalone view: own padding around the whole grid.
            main_layout.setContentsMargins(20, 20, 20, 20)
            main_layout.setSpacing(14)
        else:
            # Embedded section: the host layout owns spacing/margins.
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)

        # Top action row: album filter (when active) + selection controls.
        self.album_header_container = QWidget()
        ah_layout = QHBoxLayout(self.album_header_container)
        ah_layout.setContentsMargins(0, 0, 0, 0)
        ah_layout.setSpacing(10)

        self.album_lbl = QLabel()
        self.album_lbl.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #ff9900;"
        )
        ah_layout.addWidget(self.album_lbl)

        self.clear_album_btn = QPushButton("✕ Clear Album Filter")
        self.clear_album_btn.setStyleSheet(
            "font-size: 10px; font-weight: bold; padding: 4px 8px;"
        )
        self.clear_album_btn.clicked.connect(self.clear_album_filter)
        ah_layout.addWidget(self.clear_album_btn)

        ah_layout.addStretch(1)

        # Selection controls (standalone view only) - same line as the album
        # filter, so the toolbar stays one row instead of two.
        if self.scrollable:
            self.select_all_btn = QPushButton("Select All")
            self.select_all_btn.clicked.connect(self._toggle_select_all)
            self.select_all_btn.hide()
            ah_layout.addWidget(self.select_all_btn)

            self.select_btn = QPushButton("Select Items")
            self.select_btn.clicked.connect(self._toggle_selection_mode)
            ah_layout.addWidget(self.select_btn)

        main_layout.addWidget(self.album_header_container)

        if not self.album_filter:
            # No album filter: hide only the album side (selection stays).
            self.album_lbl.hide()
            self.clear_album_btn.hide()
            if not self.scrollable:
                # Embedded mode has no selection controls; nothing left.
                self.album_header_container.hide()
        else:
            display_name = (
                "Unsorted Media"
                if self.album_filter == "unknown"
                else self.album_filter
            )
            self.album_lbl.setText(f"📂 Album: {display_name}")

        if self.show_filter_bar:
            self.filter_bar = FilterBarWidget(
                filter_type=self.current_filter,
                sort_by=self.sort_by,
                sort_order=self.sort_order,
                search_query=self.search_term,
            )
            self.filter_bar.filter_changed.connect(self.on_filter_bar_changed)
            main_layout.addWidget(self.filter_bar)

        self.scroll_content = GridContent()
        self.scroll_content.resized.connect(self.reflow_grid)
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setContentsMargins(
            0, 0, 0, self.BOTTOM_PADDING if self.scrollable else 0
        )
        self.grid_layout.setSpacing(self.GRID_SPACING)

        if self.scrollable:
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.scroll.setWidget(self.scroll_content)
            main_layout.addWidget(self.scroll, 1)
            self.scroll.verticalScrollBar().valueChanged.connect(self.lazy_load_visible_cards)

            # Floating paginator - overlaid on the scroll viewport (bottom-center).
            self.paginator = FloatingPaginator()
            self.paginator.setParent(self.scroll.viewport())
            self.paginator.page_changed.connect(self.on_page_changed)
            self.scroll.viewport().installEventFilter(self)
            self.paginator.installEventFilter(self)
            self.paginator.hide()

            # Floating selection action bar (bottom-center of the viewport).
            self._build_action_bar()

            store = get_selection_store()
            store.mode_changed.connect(self._on_selection_mode_changed)
            store.selection_changed.connect(self._on_selection_changed)
        else:
            # Flat mode: no inner scroll area; the host's layout sizes us to
            # our content via sizeHint.
            main_layout.addWidget(self.scroll_content)

    def _build_action_bar(self):
        self.action_bar = QFrame(self.scroll.viewport())
        self.action_bar.setObjectName("SelectionActionBar")
        self.action_bar.setStyleSheet(
            "QFrame#SelectionActionBar {"
            "  background-color: #131721;"
            "  border: 1px solid rgba(255, 255, 255, 0.12);"
            "  border-radius: 18px;"
            "}"
            "QPushButton {"
            "  background-color: #181d29; border: 1px solid rgba(255,255,255,0.08);"
            "  border-radius: 12px; padding: 6px 12px; font-weight: bold; font-size: 11px;"
            "}"
            "QPushButton:hover { background-color: #232939; border-color: #ff9900;"
            "  color: #ffffff; }"
            "QPushButton#DangerBtn { background-color: rgba(243,139,168,0.18);"
            "  border-color: rgba(243,139,168,0.4); color: #f38ba8; }"
            "QPushButton#DangerBtn:hover { background-color: rgba(243,139,168,0.34);"
            "  color: #ffffff; }"
        )
        bar = QHBoxLayout(self.action_bar)
        bar.setContentsMargins(14, 8, 14, 8)
        bar.setSpacing(8)

        self.count_lbl = QLabel("0 items selected")
        self.count_lbl.setStyleSheet(
            "font-size: 12px; font-weight: 800; color: #ff9900; padding: 0 6px;"
        )
        bar.addWidget(self.count_lbl)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: get_selection_store().clear())
        bar.addWidget(clear_btn)

        move_btn = QPushButton("📁 Move to Album")
        move_btn.clicked.connect(self._on_move_clicked)
        bar.addWidget(move_btn)

        delete_btn = QPushButton("🗑 Delete")
        delete_btn.setObjectName("DangerBtn")
        delete_btn.clicked.connect(self._on_delete_clicked)
        bar.addWidget(delete_btn)

        self.action_bar.hide()

    def on_filter_bar_changed(self, data: dict):
        self.current_filter = data.get("filter_type", "ALL")
        self.sort_by = data.get("sort_by", "date")
        self.sort_order = data.get("sort_order", "desc")
        self.search_term = data.get("search_query", "")
        self.page = 1

        # Save to class-level cache
        MediaGridView._cached_filter_type = self.current_filter
        MediaGridView._cached_sort_by = self.sort_by
        MediaGridView._cached_sort_order = self.sort_order
        MediaGridView._cached_search_term = self.search_term
        MediaGridView._cached_page = self.page

        self.load_media()

    def on_page_changed(self, new_page: int):
        self.page = new_page
        MediaGridView._cached_page = self.page
        self.load_media()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The GridContent.resized signal is the primary reflow driver (it fires
        # whenever the available width changes); this is a cheap safety net for
        # the case where the view is resized before the content catches up.
        self.reflow_grid()

    def showEvent(self, event):
        super().showEvent(event)
        # The viewport is laid out by the time show completes; place the
        # paginator before first paint so it doesn't start at (0, 0).
        QTimer.singleShot(0, self._position_paginator)

    def eventFilter(self, obj, event):
        if (
            self.scroll is not None
            and obj is self.scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._position_paginator()
            self._position_action_bar()
        elif (
            self.paginator is not None
            and obj is self.paginator
            and event.type() == QEvent.Type.Show
        ):
            # The pill just became visible (e.g. first navigation) - position
            # it once the layout has settled.
            QTimer.singleShot(0, self._position_paginator)
        return super().eventFilter(obj, event)

    def _position_paginator(self):
        if self.paginator is None or not self.paginator.isVisible():
            return
        viewport = self.scroll.viewport()
        hint = self.paginator.sizeHint()
        x = max(0, (viewport.width() - hint.width()) // 2)
        y = max(0, viewport.height() - hint.height() - 16)
        self.paginator.setGeometry(x, y, hint.width(), hint.height())
        self.paginator.raise_()

    def _update_pagination(self):
        if self.paginator is not None:
            self.paginator.update_pagination(self.page, self.total_pages)
            self._position_paginator()

    # --- selection -----------------------------------------------------------

    def _current_ids(self) -> list[int]:
        return [c.item_id for c in self.cards if c.item_id is not None]

    def _toggle_selection_mode(self):
        store = get_selection_store()
        if store.is_selecting:
            store.cancel()
        else:
            store.start()

    def _toggle_select_all(self):
        store = get_selection_store()
        ids = self._current_ids()
        if ids and all(store.is_selected(i) for i in ids):
            store.deselect_many(ids)
        else:
            store.select_many(ids)

    def _on_selection_mode_changed(self, selecting: bool):
        if self.select_btn is not None:
            self.select_btn.setText("Cancel" if selecting else "Select Items")
        if self.select_all_btn is not None:
            self.select_all_btn.setVisible(selecting)
        # Hide the paginator while selecting so it doesn't clash with the
        # action bar (both live bottom-center); restore it on exit.
        if selecting:
            if self.paginator is not None:
                self.paginator.hide()
        else:
            self._update_pagination()
        self._update_select_all_label()
        self._update_action_bar()

    def _on_selection_changed(self, _changed_ids: set):
        self._update_select_all_label()
        self._update_action_bar()

    def _update_select_all_label(self):
        if self.select_all_btn is None:
            return
        store = get_selection_store()
        ids = self._current_ids()
        all_selected = bool(ids) and all(store.is_selected(i) for i in ids)
        self.select_all_btn.setText("Deselect All" if all_selected else "Select All")

    def _update_action_bar(self):
        if self.action_bar is None:
            return
        store = get_selection_store()
        count = store.count
        visible = store.is_selecting and count > 0
        if visible:
            self.count_lbl.setText(f"{count} item{'s' if count != 1 else ''} selected")
            self.action_bar.show()
            self._position_action_bar()
        else:
            self.action_bar.hide()

    def _position_action_bar(self):
        if self.action_bar is None or not self.action_bar.isVisible():
            return
        viewport = self.scroll.viewport()
        hint = self.action_bar.sizeHint()
        x = max(0, (viewport.width() - hint.width()) // 2)
        y = max(0, viewport.height() - hint.height() - 16)
        self.action_bar.setGeometry(x, y, hint.width(), hint.height())
        self.action_bar.raise_()

    def _on_delete_clicked(self):
        store = get_selection_store()
        ids = store.selected_ids()
        if not ids or not self.drive:
            return
        n = len(ids)
        confirm = QMessageBox.question(
            self,
            "Delete media",
            f"Permanently delete {n} selected file{'s' if n != 1 else ''} "
            "from disk and the library?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        deleted, errors = delete_media_items(self.drive.get("path"), ids)
        store.cancel()
        self.load_media()
        if errors:
            QMessageBox.warning(
                self,
                "Delete completed with errors",
                f"Deleted {deleted} file(s).\n\n"
                + "\n".join(errors[:8])
                + ("\n…" if len(errors) > 8 else ""),
            )

    def _on_move_clicked(self):
        store = get_selection_store()
        ids = store.selected_ids()
        if not ids or not self.drive:
            return

        albums = list_albums(self.drive.get("path"))
        if not albums:
            QMessageBox.information(self, "Move to album", "No albums are available.")
            return

        dialog = MoveToAlbumDialog(albums, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_album:
            target = dialog.selected_album
            moved, errors = move_media_items(self.drive.get("path"), ids, target["id"])
            store.cancel()
            self.load_media()
            if errors:
                QMessageBox.warning(
                    self,
                    "Move completed with errors",
                    f"Moved {moved} file(s).\n\n"
                    + "\n".join(errors[:8])
                    + ("\n…" if len(errors) > 8 else ""),
                )

    def hideEvent(self, event):
        # Leaving the view exits selection mode so other views (e.g. the
        # dashboard grid) never inherit an active selection.
        if self.scrollable:
            get_selection_store().cancel()
        super().hideEvent(event)

    def reflow_grid(self):
        if not self.cards:
            return

        avail_w = self.scroll_content.width()
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

        QTimer.singleShot(50, self.lazy_load_visible_cards)

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
            if self.filter_bar is not None:
                self.filter_bar.set_total_items(0)
            self._update_pagination()
            return

        drive_path = self.drive.get("path")
        db_path = get_db_path(drive_path)
        if not os.path.exists(db_path):
            empty_lbl = QLabel(
                "No media library found. Please run a Discovery Scan first."
            )
            empty_lbl.setObjectName("SubtitleLabel")
            self.grid_layout.addWidget(empty_lbl, 0, 0)
            if self.filter_bar is not None:
                self.filter_bar.set_total_items(0)
            self._update_pagination()
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

            if hasattr(self, "album_filter") and self.album_filter:
                base_where += " AND album_id = (SELECT id FROM albums WHERE name = ?)"
                params.append(self.album_filter)

            # Query Total Count
            count_sql = f"SELECT COUNT(*) FROM media_items{base_where}"
            cursor.execute(count_sql, params)
            self.total_count = cursor.fetchone()[0]

            self.total_pages = max(1, math.ceil(self.total_count / self.page_size))
            self.page = max(1, min(self.page, self.total_pages))

            if self.filter_bar is not None:
                self.filter_bar.set_total_items(self.total_count)
            self._update_pagination()

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
            self._update_select_all_label()
            QTimer.singleShot(50, self.lazy_load_visible_cards)

        except Exception as e:
            print(f"[MediaGrid] Error querying DB: {e}")
        finally:
            conn.close()

    def open_viewer(self, item: dict):
        self.item_clicked.emit(item)
        if self._on_item_clicked is not None:
            self._on_item_clicked(item)
        else:
            get_router().navigate("/viewer", {"item": item})

    def clear_album_filter(self):
        self.album_filter = None
        if hasattr(self, "album_lbl"):
            self.album_lbl.hide()
        if hasattr(self, "clear_album_btn"):
            self.clear_album_btn.hide()
        if not self.scrollable and hasattr(self, "album_header_container"):
            self.album_header_container.hide()
        self.page = 1
        MediaGridView._cached_page = 1
        self.load_media()

    def lazy_load_visible_cards(self):
        if not self.scrollable or not self.scroll:
            # If not scrollable (e.g. flat dashboard), load all cards immediately
            for card in self.cards:
                card.load_thumbnail()
            return

        viewport = self.scroll.viewport()
        viewport_rect = viewport.rect()

        for card in self.cards:
            if card.thumbnail_loaded or card.thumbnail_loading:
                continue

            # Map card's top-left corner to viewport coordinates
            card_pos = card.mapTo(viewport, QPoint(0, 0))
            card_rect = QRect(card_pos, card.size())

            # If card intersects with viewport, trigger its load_thumbnail
            if viewport_rect.intersects(card_rect):
                card.load_thumbnail()
