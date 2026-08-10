"""Reusable media card widget.

A self-contained, theme-aware card that renders a media thumbnail with a
type chip, a hover info overlay (filename / size / date), and hover
animations (image zoom, shadow elevation, overlay fade). Clicking the card
emits :attr:`MediaCard.card_clicked` with the item dict.

Usage::

    card = MediaCard(item_dict, drive_path)
    card.setFixedSize(160, 160)  # callers control the size
    card.card_clicked.connect(on_click)

Used by the media grid view and the dashboard.
"""

import hashlib
import os
from datetime import datetime

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QSize,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.thumbnails import get_or_generate_thumbnail
from ui.selection_store import get_selection_store
from ui.theme import get_theme_manager


class ThumbnailLoader(QThread):
    loaded = Signal(str)

    def __init__(self, item: dict, drive_path: str):
        super().__init__()
        self.item = item
        self.drive_path = drive_path

    def run(self):
        rel_path = self.item.get("current_relative_path", "")
        if not rel_path or not self.drive_path:
            return

        full_media_path = os.path.join(self.drive_path, rel_path)
        if not os.path.exists(full_media_path):
            return

        thumb_dir = os.path.join(self.drive_path, "albums", "thumbs")
        file_hash = (
            self.item.get("file_hash") or hashlib.md5(rel_path.encode()).hexdigest()
        )
        thumb_path = os.path.join(thumb_dir, f"{file_hash}.jpg")

        success = get_or_generate_thumbnail(full_media_path, thumb_path)
        if success and os.path.exists(thumb_path):
            self.loaded.emit(thumb_path)


class MediaCard(QFrame):
    card_clicked = Signal(dict)

    MIN_W = 140
    MIN_H = 140
    HEIGHT_RATIO = 1.0  # aspect-square, matching the React card

    # Hover animation tuning (mirrors the React card's transitions)
    ZOOM_FACTOR = 1.06
    SHADOW_BLUR_REST = 16
    SHADOW_BLUR_HOVER = 34
    SHADOW_OFF_REST = QPointF(0, 3)
    SHADOW_OFF_HOVER = QPointF(0, 8)

    _loaders = set()

    def __init__(self, item: dict, drive_path: str):
        super().__init__()
        self.item = item
        self.item_id = item.get("id")
        self.drive_path = drive_path
        self.is_video = item.get("mime_type", "").startswith("video/")
        self.setObjectName("GlassCard")
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._zoom = 1.0
        self._hovered = False
        self._selected = False
        self._full_pixmap = QPixmap()
        self._scaled_for = QSize(0, 0)
        self.thumbnail_loaded = False
        self.thumbnail_loading = False

        theme = get_theme_manager().get_theme()

        # Per-type accent (React uses secondary for video, info for image).
        self.type_color = theme["accent"] if self.is_video else theme["fg_title"]

        # rounded-2xl corners, overriding the flatter global GlassCard radius.
        # A 2px accent border marks the selected state (React's ring-primary).
        self._style_base = (
            "QFrame#GlassCard {"
            f"  background-color: {theme['bg_card']};"
            f"  border: 1px solid {theme['border']};"
            "  border-radius: 16px;"
            "}"
            "QFrame#GlassCard:hover {"
            f"  border-color: {theme['accent_dim']};"
            "}"
        )
        self._style_selected = (
            "QFrame#GlassCard {"
            f"  background-color: {theme['bg_card']};"
            f"  border: 2px solid {theme['accent']};"
            "  border-radius: 16px;"
            "}"
        )
        self.setStyleSheet(self._style_base)

        self._build_shadow()
        self._build_children(theme)
        self._build_animations()
        # self.load_thumbnail() is deferred and called on-demand by the scroll area viewport

        # Subscribe to global selection state. Qt auto-disconnects these when
        # the card is destroyed (on page change), so no manual cleanup needed.
        store = get_selection_store()
        store.mode_changed.connect(self._on_selection_mode_changed)
        store.selection_changed.connect(self._on_selection_changed)
        self.check_lbl.setVisible(store.is_selecting)
        self._refresh_selected()

    def _build_shadow(self):
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(self.SHADOW_BLUR_REST)
        self._shadow.setOffset(self.SHADOW_OFF_REST)
        self._shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(self._shadow)

    def _build_children(self, t):
        self._theme = t
        filename = os.path.basename(self.item.get("current_relative_path", "file"))
        self._filename = filename

        # Full-bleed thumbnail (1px inset so the card border stays visible)
        self.img_lbl = QLabel(self)
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setStyleSheet(
            f"background-color: {t['bg_base']}; border-radius: 15px;"
        )
        self._transparent_for_mouse(self.img_lbl)

        # Placeholder shown until the thumbnail loads (or on error): a tinted
        # round icon over the filename, matching the React fallback.
        self.placeholder = QFrame(self)
        ph_layout = QVBoxLayout(self.placeholder)
        ph_layout.setContentsMargins(12, 12, 12, 12)
        ph_layout.setSpacing(10)
        ph_layout.addStretch(1)

        circle = QLabel("▶" if self.is_video else "🖼", self.placeholder)
        circle.setFixedSize(64, 64)
        circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        circle.setStyleSheet(
            "QLabel {"
            f"  background-color: {self._tint(self.type_color, 0.14)};"
            f"  color: {self.type_color};"
            "  border-radius: 32px;"
            "  font-size: 26px;"
            "  border: none;"
            "}"
        )
        ph_icon_row = QHBoxLayout()
        ph_icon_row.addStretch(1)
        ph_icon_row.addWidget(circle)
        ph_icon_row.addStretch(1)
        ph_layout.addLayout(ph_icon_row)

        ph_name = QLabel(filename, self.placeholder)
        self.ph_name = ph_name
        ph_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_name.setStyleSheet(
            f"color: {t['fg_sub']}; font-family: monospace; font-size: 10px; border: none;"
        )
        ph_layout.addWidget(ph_name)
        ph_layout.addStretch(1)
        self._transparent_for_mouse(self.placeholder)

        # Hover info overlay - gradient band at the bottom (fades in on hover)
        self.overlay = QFrame(self)
        ov_layout = QVBoxLayout(self.overlay)
        ov_layout.setContentsMargins(0, 0, 0, 0)
        ov_layout.setSpacing(0)
        ov_layout.addStretch(1)

        band = QFrame(self.overlay)
        band.setObjectName("CardInfoBand")
        band.setMinimumHeight(96)
        band.setStyleSheet(
            "QFrame#CardInfoBand {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "    stop:0 rgba(0,0,0,0), stop:0.35 rgba(0,0,0,0.28),"
            f"    stop:0.75 rgba(0,0,0,0.72), stop:1 {t['glass_overlay']});"
            "  border: none;"
            "  border-bottom-left-radius: 15px;"
            "  border-bottom-right-radius: 15px;"
            "}"
        )
        band_layout = QVBoxLayout(band)
        band_layout.setContentsMargins(12, 8, 12, 11)
        band_layout.setSpacing(3)
        band_layout.addStretch(1)

        self.name_lbl = QLabel(filename, band)
        self.name_lbl.setStyleSheet(
            f"color: {t['fg_main']}; font-size: 11px; font-weight: 800; border: none;"
        )

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        size_lbl = QLabel(self._format_size(self.item.get("file_size")), band)
        size_lbl.setStyleSheet(
            f"color: {t['fg_sub']}; font-size: 9px; font-weight: 600; border: none;"
        )
        meta_row.addWidget(size_lbl)
        meta_row.addStretch(1)
        date_lbl = QLabel(self._format_date(self.item.get("created_at")), band)
        date_lbl.setStyleSheet(
            f"color: {t['fg_sub']}; font-size: 9px; font-weight: 600; border: none;"
        )
        meta_row.addWidget(date_lbl)

        band_layout.addWidget(self.name_lbl)
        band_layout.addLayout(meta_row)
        ov_layout.addWidget(band)
        self._transparent_for_mouse(self.overlay)

        self._overlay_effect = QGraphicsOpacityEffect(self.overlay)
        self._overlay_effect.setOpacity(0.0)
        self.overlay.setGraphicsEffect(self._overlay_effect)

        # Media-type chip, top-right (always visible)
        self.badge = QFrame(self)
        self.badge.setObjectName("MediaTypeBadge")
        self.badge.setStyleSheet(
            "QFrame#MediaTypeBadge {"
            f"  background-color: {t['bg_card']};"
            f"  border: 1px solid {t['border']};"
            "  border-radius: 6px;"
            "}"
        )
        badge_layout = QHBoxLayout(self.badge)
        badge_layout.setContentsMargins(7, 3, 7, 3)
        badge_layout.setSpacing(4)

        icon_lbl = QLabel("▶" if self.is_video else "🖼", self.badge)
        icon_lbl.setStyleSheet(
            f"color: {self.type_color}; font-size: 9px; font-weight: 800;"
            " border: none; background: transparent;"
        )
        badge_layout.addWidget(icon_lbl)

        text_lbl = QLabel("VIDEO" if self.is_video else "IMAGE", self.badge)
        text_lbl.setStyleSheet(
            f"color: {t['fg_main']}; font-size: 8px; font-weight: 800;"
            " border: none; background: transparent;"
        )
        badge_layout.addWidget(text_lbl)
        self._transparent_for_mouse(self.badge)

        # Selection checkbox, top-left (only visible in selection mode).
        self.check_lbl = QLabel(self)
        self.check_lbl.setFixedSize(22, 22)
        self.check_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_check_style(t)
        self.check_lbl.hide()
        self._transparent_for_mouse(self.check_lbl)

    def _apply_check_style(self, t):
        if self._selected:
            self.check_lbl.setText("✓")
            self.check_lbl.setStyleSheet(
                "QLabel {"
                f"  background-color: {t['accent']};"
                f"  color: {t['bg_root']};"
                f"  border: 2px solid {t['accent']};"
                "  border-radius: 6px; font-size: 13px; font-weight: 900;"
                "}"
            )
        else:
            self.check_lbl.setText("")
            self.check_lbl.setStyleSheet(
                "QLabel {"
                "  background-color: rgba(0, 0, 0, 0.5);"
                f"  border: 2px solid {t['fg_sub']};"
                "  border-radius: 6px;"
                "}"
            )

    @staticmethod
    def _tint(color: str, alpha: float) -> str:
        """Return `color` (a #rrggbb hex) as an rgba() string with `alpha`."""
        c = color.strip()
        if c.startswith("#") and len(c) == 7:
            r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
            return f"rgba({r}, {g}, {b}, {alpha})"
        return c

    @staticmethod
    def _transparent_for_mouse(widget: QWidget):
        """Let mouse events pass through decorative children to the card."""
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        for child in widget.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def _build_animations(self):
        easing = QEasingCurve.Type.OutCubic

        self._zoom_anim = QPropertyAnimation(self, b"zoom", self)
        self._zoom_anim.setDuration(250)
        self._zoom_anim.setEasingCurve(easing)

        self._shadow_blur_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._shadow_blur_anim.setDuration(220)
        self._shadow_blur_anim.setEasingCurve(easing)

        self._shadow_off_anim = QPropertyAnimation(self._shadow, b"offset", self)
        self._shadow_off_anim.setDuration(220)
        self._shadow_off_anim.setEasingCurve(easing)

        self._overlay_anim = QPropertyAnimation(self._overlay_effect, b"opacity", self)
        self._overlay_anim.setDuration(180)
        self._overlay_anim.setEasingCurve(easing)

    # --- hover state ---------------------------------------------------------

    def enterEvent(self, event):
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_hovered(False)
        super().leaveEvent(event)

    def _set_hovered(self, hovered: bool):
        if hovered == self._hovered:
            return
        self._hovered = hovered

        self._run_anim(
            self._zoom_anim, self._zoom, self.ZOOM_FACTOR if hovered else 1.0
        )
        self._run_anim(
            self._shadow_blur_anim,
            self._shadow.blurRadius(),
            self.SHADOW_BLUR_HOVER if hovered else self.SHADOW_BLUR_REST,
        )
        self._run_anim(
            self._shadow_off_anim,
            self._shadow.offset(),
            self.SHADOW_OFF_HOVER if hovered else self.SHADOW_OFF_REST,
        )
        self._run_anim(
            self._overlay_anim,
            self._overlay_effect.opacity(),
            1.0 if hovered else 0.0,
        )

    @staticmethod
    def _run_anim(anim, start, end):
        anim.stop()
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    # --- animated zoom property ----------------------------------------------

    def _get_zoom(self):
        return self._zoom

    def _set_zoom(self, value):
        self._zoom = value
        self._apply_pixmap()

    zoom = Property(float, _get_zoom, _set_zoom)

    # --- events ---------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        store = get_selection_store()
        if store.is_selecting:
            if self.item_id is not None:
                store.toggle(self.item_id)
        else:
            self.card_clicked.emit(self.item)

    # --- selection ------------------------------------------------------------

    def _on_selection_mode_changed(self, selecting: bool):
        self.check_lbl.setVisible(selecting)
        self._refresh_selected()

    def _on_selection_changed(self, changed_ids: set):
        # Only repaint when this card's own id was affected (per-node update).
        if self.item_id in changed_ids:
            self._refresh_selected()

    def _refresh_selected(self):
        selected = get_selection_store().is_selected(self.item_id)
        if selected == self._selected:
            return
        self._selected = selected
        self.setStyleSheet(self._style_selected if selected else self._style_base)
        self._apply_check_style(self._theme)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        inner_w, inner_h = max(0, w - 2), max(0, h - 2)
        self.img_lbl.setGeometry(1, 1, inner_w, inner_h)
        self.placeholder.setGeometry(1, 1, inner_w, inner_h)
        self.overlay.setGeometry(1, 1, inner_w, inner_h)

        # Elide long filenames (single-token names can't word-wrap) to fit.
        self.name_lbl.setText(
            QFontMetrics(self.name_lbl.font()).elidedText(
                self._filename, Qt.TextElideMode.ElideRight, max(0, inner_w - 24)
            )
        )
        self.ph_name.setText(
            QFontMetrics(self.ph_name.font()).elidedText(
                self._filename, Qt.TextElideMode.ElideMiddle, max(0, inner_w - 32)
            )
        )

        badge_size = self.badge.sizeHint()
        self.badge.setGeometry(
            max(1, w - badge_size.width() - 10),
            10,
            badge_size.width(),
            badge_size.height(),
        )
        self.check_lbl.move(10, 10)
        self._apply_pixmap()

    # --- thumbnail ------------------------------------------------------------

    def load_thumbnail(self):
        if self.thumbnail_loaded or self.thumbnail_loading:
            return

        rel_path = self.item.get("current_relative_path", "")
        if not rel_path or not self.drive_path:
            return

        thumb_dir = os.path.join(self.drive_path, "albums", "thumbs")
        file_hash = (
            self.item.get("file_hash") or hashlib.md5(rel_path.encode()).hexdigest()
        )
        thumb_path = os.path.join(thumb_dir, f"{file_hash}.jpg")

        if os.path.exists(thumb_path):
            self.on_thumb_loaded(thumb_path)
        else:
            self.thumbnail_loading = True
            loader = ThumbnailLoader(self.item, self.drive_path)
            self.loader = loader
            # Keep the thread alive until it finishes even if the card is deleted
            # mid-load (prevents "QThread destroyed while running" on page changes).
            MediaCard._loaders.add(loader)
            loader.finished.connect(self._on_loader_finished)
            loader.finished.connect(lambda: MediaCard._loaders.discard(loader))
            loader.loaded.connect(self.on_thumb_loaded)
            loader.start()

    def _on_loader_finished(self):
        self.thumbnail_loading = False

    def on_thumb_loaded(self, path: str):
        self.thumbnail_loaded = True
        self.thumbnail_loading = False
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self._full_pixmap = pixmap
            self._scaled_for = QSize(0, 0)
            self.placeholder.hide()
            self._apply_pixmap()

    def _apply_pixmap(self):
        """Scale + center-crop the thumbnail to the current label size.

        The label target is scaled by `self._zoom`, so the hover animation
        zooms the image in while keeping it cropped to the tile (the React
        card's `group-hover:scale-105`).
        """
        if self._full_pixmap.isNull():
            return

        size = self.img_lbl.size()
        if size.width() < 2 or size.height() < 2:
            return
        target = QSize(int(size.width() * self._zoom), int(size.height() * self._zoom))
        if target == self._scaled_for:
            return
        self._scaled_for = target

        scaled = self._full_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

        if scaled.size() == size:
            final = scaled
        else:
            # Center-crop the overflowing edges so the image always fills the tile.
            final = QPixmap(size)
            final.fill(Qt.GlobalColor.transparent)
            painter = QPainter(final)
            painter.drawPixmap(
                (size.width() - scaled.width()) // 2,
                (size.height() - scaled.height()) // 2,
                scaled,
            )
            painter.end()

        self.img_lbl.setPixmap(final)

    # --- metadata helpers -----------------------------------------------------

    @staticmethod
    def _format_size(size) -> str:
        try:
            return f"{float(size) / (1024 * 1024):.2f} MB"
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _format_date(value) -> str:
        if value is None or value == "":
            return ""
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(float(value)).strftime("%b %d, %Y")
            text = str(value).strip()
            if not text:
                return ""
            return datetime.fromisoformat(text).strftime("%b %d, %Y")
        except (ValueError, TypeError, OverflowError, OSError):
            return str(value)
