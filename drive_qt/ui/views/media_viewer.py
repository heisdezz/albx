"""Media viewer page.

Navigation bar on top, then a splitter with the player and the metadata
sidebar - the same layout as before the related-media section was added
(that widget still exists in `ui.widgets.related_media`, just unused).

Fullscreen is player-only: the app chrome (window title bar, sidebar) and
the viewer's own chrome (nav bar, metadata sidebar) are hidden and the
window is shown fullscreen. The video surface is never reparented, which
would crash the Wayland/xdg-shell protocol.
"""

import os

import mpv
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.database import get_db_path, open_readable_db
from router import get_router
from ui.widgets.clickable_slider import ClickSeekSlider
from ui.widgets.metadata_sidebar import MetadataSidebar


def format_time(ms: int) -> str:
    total_seconds = max(0, ms // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    hours = minutes // 60
    minutes = minutes % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class MediaViewer(QWidget):
    def __init__(self, parent_window=None, drive: dict = None, item: dict = None):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.drive = drive
        self.item = item or {}
        self.is_video = self.item.get("mime_type", "").startswith("video/")

        self.media_player = None
        self.video_widget = None
        self.ctrl_card = None
        self.is_seeking = False
        self._pending_path = None
        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(200)
        self._pos_timer.timeout.connect(self._poll_player_state)

        # Image state
        self.current_pixmap = None
        self.zoom_factor = 1.0
        self.rotation_angle = 0

        self._viewer_fullscreen = False

        self.build_ui()
        self.load_media()
        self._update_nav_state()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Navigation header
        self.nav_bar = QWidget()
        nav_row = QHBoxLayout(self.nav_bar)
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(12)

        back_btn = QPushButton("◀ Back to Gallery")
        back_btn.clicked.connect(self.on_back_clicked)
        nav_row.addWidget(back_btn)

        # Album navigation: previous / next item in the same album.
        self.prev_btn = QPushButton("◀ Prev")
        self.prev_btn.setEnabled(False)
        self.prev_btn.setToolTip("Previous item in album")
        self.prev_btn.clicked.connect(self._go_prev)
        nav_row.addWidget(self.prev_btn)

        self.next_btn = QPushButton("Next ▶")
        self.next_btn.setEnabled(False)
        self.next_btn.setToolTip("Next item in album")
        self.next_btn.clicked.connect(self._go_next)
        nav_row.addWidget(self.next_btn)

        filename = os.path.basename(
            self.item.get("current_relative_path", "Media Viewer")
        )
        icon_str = "🎥 " if self.is_video else "🖼️ "
        self.title_lbl = QLabel(f"{icon_str}{filename}")
        self.title_lbl.setObjectName("TitleLabel")
        self.title_lbl.setToolTip(filename)
        nav_row.addWidget(self.title_lbl)
        nav_row.addStretch()

        layout.addWidget(self.nav_bar)

        # Main Splitter: player + file details sidebar
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.player_card = QFrame()
        self.player_card.setObjectName("GlassCard")
        card_layout = QVBoxLayout(self.player_card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)
        # The player surface is swapped out wholesale when navigating between
        # items, so the card keeps one permanent layout.
        self.player_surface = QWidget()
        card_layout.addWidget(self.player_surface)
        self._build_player_ui(self.player_surface)
        splitter.addWidget(self.player_card)

        self.sidebar = MetadataSidebar(self.item)
        splitter.addWidget(self.sidebar)
        splitter.setSizes([750, 300])

        layout.addWidget(splitter, 1)

    def _build_player_ui(self, surface: QWidget):
        # Margins live on the card's permanent layout; this surface owns only
        # the player widgets so it can be swapped when the item changes.
        vc_layout = QVBoxLayout(surface)
        vc_layout.setContentsMargins(0, 0, 0, 0)
        vc_layout.setSpacing(8)

        self.status_lbl = QLabel()
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setObjectName("SubtitleLabel")
        vc_layout.addWidget(self.status_lbl)
        self.status_lbl.hide()

        if self.is_video:
            self.video_widget = QWidget()
            self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            self.video_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.video_widget.setMinimumHeight(320)
            self.video_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.video_widget.installEventFilter(self)
            vc_layout.addWidget(self.video_widget, 1)

            # Player Control Bar Container
            self.ctrl_card = QFrame()
            self.ctrl_card.setStyleSheet(
                "background-color: rgba(0, 0, 0, 0.4); border-radius: 8px; padding: 6px;"
            )
            ctrl_layout = QVBoxLayout(self.ctrl_card)
            ctrl_layout.setContentsMargins(10, 8, 10, 8)
            ctrl_layout.setSpacing(8)

            # Row 1: Seek Slider + Timestamp Label
            seek_row = QHBoxLayout()
            seek_row.setSpacing(10)

            self.seek_slider = ClickSeekSlider(Qt.Orientation.Horizontal)
            self.seek_slider.setRange(0, 100)
            self.seek_slider.sliderPressed.connect(self.on_seek_pressed)
            self.seek_slider.sliderReleased.connect(self.on_seek_released)
            self.seek_slider.sliderMoved.connect(self.on_seek_moved)
            seek_row.addWidget(self.seek_slider, 1)

            self.time_lbl = QLabel("00:00 / 00:00")
            self.time_lbl.setStyleSheet(
                "font-family: monospace; font-size: 12px; font-weight: 700; color: #cdd6f4;"
            )
            seek_row.addWidget(self.time_lbl)

            ctrl_layout.addLayout(seek_row)

            # Row 2: Play/Pause, Stop, Volume, Speed, Fullscreen
            action_row = QHBoxLayout()
            action_row.setSpacing(8)

            self.play_btn = QPushButton("▶ Play")
            self.play_btn.setFixedWidth(80)
            self.play_btn.clicked.connect(self.toggle_play_pause)
            action_row.addWidget(self.play_btn)

            stop_btn = QPushButton("⏹")
            stop_btn.setFixedWidth(36)
            stop_btn.setToolTip("Stop Playback")
            stop_btn.clicked.connect(self.stop_playback)
            action_row.addWidget(stop_btn)

            # Mute + Volume Slider
            self.mute_btn = QPushButton("🔊")
            self.mute_btn.setFixedWidth(36)
            self.mute_btn.clicked.connect(self.toggle_mute)
            action_row.addWidget(self.mute_btn)

            self.vol_slider = QSlider(Qt.Orientation.Horizontal)
            self.vol_slider.setRange(0, 100)
            self.vol_slider.setValue(80)
            self.vol_slider.setFixedWidth(100)
            self.vol_slider.valueChanged.connect(self.on_volume_changed)
            action_row.addWidget(self.vol_slider)

            action_row.addStretch()

            # Speed ComboBox
            action_row.addWidget(QLabel("Speed:"))
            self.speed_combo = QComboBox()
            self.speed_combo.addItems(["0.5x", "1.0x", "1.25x", "1.5x", "2.0x"])
            self.speed_combo.setCurrentText("1.0x")
            self.speed_combo.currentTextChanged.connect(self.on_speed_changed)
            action_row.addWidget(self.speed_combo)

            # Fullscreen Toggle Button
            self.fs_btn = QPushButton("📺 Fullscreen")
            self.fs_btn.clicked.connect(self.toggle_fullscreen)
            action_row.addWidget(self.fs_btn)

            ctrl_layout.addLayout(action_row)
            vc_layout.addWidget(self.ctrl_card)

        else:
            # Image Scroll Display Area
            img_scroll = QScrollArea()
            img_scroll.setWidgetResizable(True)
            img_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_scroll.setStyleSheet("background: transparent; border: none;")

            self.image_lbl = QLabel()
            self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_lbl.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            img_scroll.setWidget(self.image_lbl)

            vc_layout.addWidget(img_scroll, 1)

            # Image Action Control Bar
            img_ctrl = QHBoxLayout()
            img_ctrl.setSpacing(8)

            zoom_in_btn = QPushButton("🔍+ Zoom In")
            zoom_in_btn.clicked.connect(self.zoom_in)
            img_ctrl.addWidget(zoom_in_btn)

            zoom_out_btn = QPushButton("🔍- Zoom Out")
            zoom_out_btn.clicked.connect(self.zoom_out)
            img_ctrl.addWidget(zoom_out_btn)

            reset_btn = QPushButton("🎯 Fit Screen")
            reset_btn.clicked.connect(self.reset_image)
            img_ctrl.addWidget(reset_btn)

            rotate_btn = QPushButton("🔄 Rotate 90°")
            rotate_btn.clicked.connect(self.rotate_image)
            img_ctrl.addWidget(rotate_btn)

            img_ctrl.addStretch()
            vc_layout.addLayout(img_ctrl)

    def load_media(self):
        drive_path = self.drive.get("path", "") if self.drive else ""
        rel_path = self.item.get("current_relative_path", "")

        if not drive_path or not rel_path:
            self.show_error("No drive volume or file path provided.")
            return

        full_path = os.path.join(drive_path, rel_path)

        if not os.path.exists(full_path):
            self.show_error(f"⚠️ File not found: {rel_path}")
            return

        if self.is_video:
            self._pending_path = full_path
            self._start_mpv()
        else:
            pixmap = QPixmap(full_path)
            if not pixmap.isNull():
                self.current_pixmap = pixmap
                self.update_image_display()
            else:
                self.show_error("Failed to load image contents.")

    # --- mpv-based video playback ---------------------------------------------
    #
    # QtMultimedia's bundled FFmpeg ships no software AV1 decoder and this
    # GPU (Broadwell VAAPI) can't hardware-decode AV1/HEVC, so those files
    # never play through QMediaPlayer. mpv (python-mpv + system libmpv)
    # decodes everything: VAAPI hardware decode where the driver supports it
    # (H.264 etc.) and automatic software fallback otherwise.

    def _current_speed(self) -> float:
        try:
            return float(self.speed_combo.currentText().replace("x", ""))
        except ValueError, AttributeError:
            return 1.0

    def _start_mpv(self):
        """Create the embedded mpv player and start the pending file."""
        path = getattr(self, "_pending_path", None)
        if not path or self.media_player is not None:
            return

        # On Wayland the mpv ``wid`` must be a mapped native window, so wait
        # until the video widget is actually visible before grabbing it.
        if not self.video_widget.isVisible():
            attempts = getattr(self, "_mpv_start_attempts", 0)
            if attempts >= 50:  # ~5s ceiling
                self.show_error("Video output not ready.")
                return
            self._mpv_start_attempts = attempts + 1
            QTimer.singleShot(100, self._start_mpv)
            return
        self._mpv_start_attempts = 0

        try:
            wid = int(self.video_widget.winId())
        except Exception as e:
            self.show_error(f"Video output not ready: {e}")
            return

        if wid == 0:
            self.show_error("Video output not ready.")
            return

        try:
            self.media_player = mpv.MPV(
                wid=str(wid),
                vo="libmpv",
                hwdec="auto-safe",  # VAAPI where possible, software fallback otherwise
                keep_open="yes",  # hold the last frame instead of quitting at EOF
                osc=False,
                input_default_bindings=False,
                input_vo_keyboard=False,
                ytdl=False,
                volume=self.vol_slider.value(),
                speed=self._current_speed(),
            )
        except Exception as e:
            self.show_error(f"Failed to start video player: {e}")
            return

        self._pos_timer.start()
        self.media_player.play(path)
        self.play_btn.setText("⏸ Pause")

    def _teardown_player(self):
        """Release the mpv player and stop the position poller.

        Must run before the video widget is destroyed (navigation, window
        close), otherwise mpv keeps rendering into a stale window and can
        crash on Wayland.
        """
        self._pos_timer.stop()
        self._pending_path = None  # cancels any in-flight _start_mpv retry
        player = getattr(self, "media_player", None)
        if player is not None:
            try:
                player.terminate()
            except Exception:
                pass
            self.media_player = None

    def _poll_player_state(self):
        """Poll mpv properties to update the seek bar and labels.

        mpv property observers fire on its own thread, so we poll from the Qt
        GUI thread on a short timer instead - simpler and thread-safe.
        """
        player = getattr(self, "media_player", None)
        if player is None:
            return
        try:
            pos_s = player.time_pos
            dur_s = player.duration
        except Exception:
            return
        if dur_s:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setRange(0, int(dur_s * 1000))
            if pos_s is not None and not self.is_seeking:
                self.seek_slider.setValue(int(pos_s * 1000))
            self.seek_slider.blockSignals(False)
        self.update_time_label(
            override_pos=int(pos_s * 1000) if pos_s is not None else None
        )

    # --- album navigation ----------------------------------------------------

    def _find_neighbor(self, direction: str) -> dict | None:
        """Return the previous/next item in the same album, or None.

        Ordering matches the gallery grid: ``created_at DESC, id DESC``.
        """
        drive_path = self.drive.get("path", "") if self.drive else ""
        item_id = self.item.get("id")
        created_at = self.item.get("created_at")
        if not drive_path or not item_id or created_at is None:
            return None

        db_path = get_db_path(drive_path)
        if not os.path.exists(db_path):
            return None

        conn = open_readable_db(db_path)
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            if direction == "next":
                condition = "(created_at < ? OR (created_at = ? AND id < ?))"
                order = "ORDER BY created_at DESC, id DESC"
            else:
                condition = "(created_at > ? OR (created_at = ? AND id > ?))"
                order = "ORDER BY created_at ASC, id ASC"

            query = f"""
                SELECT id, current_relative_path, mime_type, file_size,
                       created_at, file_hash
                FROM media_items
                WHERE album_id = (SELECT album_id FROM media_items WHERE id = ?)
                  AND {condition}
                {order}
                LIMIT 1
            """
            cursor.execute(query, (item_id, created_at, created_at, item_id))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "current_relative_path": row[1],
                "mime_type": row[2],
                "file_size": row[3],
                "created_at": row[4],
                "file_hash": row[5] if len(row) > 5 else None,
            }
        except Exception as e:
            print(f"[MediaViewer] Error querying neighbor: {e}")
            return None
        finally:
            conn.close()

    def _update_nav_state(self):
        """Enable/disable prev/next based on whether album neighbors exist."""
        if not hasattr(self, "prev_btn"):
            return
        self.prev_btn.setEnabled(self._find_neighbor("prev") is not None)
        self.next_btn.setEnabled(self._find_neighbor("next") is not None)

    def _go_prev(self):
        self._navigate_to("prev")

    def _go_next(self):
        self._navigate_to("next")

    def _navigate_to(self, direction: str):
        neighbor = self._find_neighbor(direction)
        if neighbor:
            self._load_item(neighbor)

    def _load_item(self, item: dict):
        """Swap the viewer to a different item in place.

        Mirrors the web app: next/prev updates the same page instead of
        recreating the view, so the media player is torn down and rebuilt
        sequentially - avoiding crashes from destroying a playing
        QMediaPlayer while a new one starts.
        """
        # Stop and release the current media resources first.
        self.stop_playback()
        self._teardown_player()

        self.item = item
        self.is_video = item.get("mime_type", "").startswith("video/")

        # Swap the player surface (video/image UI is type-dependent).
        old_surface = self.player_surface
        self.player_surface = QWidget()
        self.player_card.layout().replaceWidget(old_surface, self.player_surface)
        old_surface.deleteLater()
        self._build_player_ui(self.player_surface)

        # Rebuild the metadata sidebar for the new item.
        splitter = self.sidebar.parentWidget()
        index = splitter.indexOf(self.sidebar)
        new_sidebar = MetadataSidebar(self.item)
        splitter.replaceWidget(index, new_sidebar)
        self.sidebar.deleteLater()
        self.sidebar = new_sidebar

        # Update the header title.
        filename = os.path.basename(
            self.item.get("current_relative_path", "Media Viewer")
        )
        icon_str = "🎥 " if self.is_video else "🖼️ "
        self.title_lbl.setText(f"{icon_str}{filename}")
        self.title_lbl.setToolTip(filename)

        self.load_media()
        self._update_nav_state()

    # --- image controls ------------------------------------------------------

    def update_image_display(self):
        if not self.current_pixmap or not hasattr(self, "image_lbl"):
            return

        transform = QTransform().rotate(self.rotation_angle)
        rotated = self.current_pixmap.transformed(
            transform, Qt.TransformationMode.SmoothTransformation
        )

        target_w = int(750 * self.zoom_factor)
        target_h = int(600 * self.zoom_factor)

        scaled = rotated.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_lbl.setPixmap(scaled)

    def zoom_in(self):
        self.zoom_factor = min(3.0, self.zoom_factor + 0.25)
        self.update_image_display()

    def zoom_out(self):
        self.zoom_factor = max(0.25, self.zoom_factor - 0.25)
        self.update_image_display()

    def reset_image(self):
        self.zoom_factor = 1.0
        self.rotation_angle = 0
        self.update_image_display()

    def rotate_image(self):
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self.update_image_display()

    def show_error(self, message: str):
        self.status_lbl.setText(message)
        self.status_lbl.show()

    # --- video transport -----------------------------------------------------

    def toggle_play_pause(self):
        player = getattr(self, "media_player", None)
        if not player:
            return
        if player.pause:
            # If we're parked on the last frame after EOF, restart from the
            # beginning instead of resuming at the very end.
            if player.eof_reached:
                player.time_pos = 0
            player.pause = False
            self.play_btn.setText("⏸ Pause")
        else:
            player.pause = True
            self.play_btn.setText("▶ Play")

    def toggle_mute(self):
        player = getattr(self, "media_player", None)
        if not player:
            return
        player.mute = not player.mute
        self.mute_btn.setText("🔇" if player.mute else "🔊")

    def on_volume_changed(self, value: int):
        player = getattr(self, "media_player", None)
        if player:
            player.volume = value

    def on_speed_changed(self, speed_str: str):
        player = getattr(self, "media_player", None)
        if player:
            try:
                rate = float(speed_str.replace("x", ""))
                player.speed = rate
            except ValueError:
                pass

    def on_seek_pressed(self):
        self.is_seeking = True

    def on_seek_moved(self, pos: int):
        self.update_time_label(override_pos=pos)

    def on_seek_released(self):
        player = getattr(self, "media_player", None)
        if player:
            player.time_pos = self.seek_slider.value() / 1000.0
        self.is_seeking = False

    def update_time_label(self, override_pos: int = None):
        player = getattr(self, "media_player", None)
        if not player:
            return
        try:
            pos = (
                override_pos
                if override_pos is not None
                else int((player.time_pos or 0) * 1000)
            )
            dur = int((player.duration or 0) * 1000)
        except Exception:
            return
        self.time_lbl.setText(f"{format_time(pos)} / {format_time(dur)}")

    # --- fullscreen (player-only: hide the surrounding chrome) ----------------

    def toggle_fullscreen(self):
        if not hasattr(self, "fs_btn"):
            return
        if self._viewer_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        if self._viewer_fullscreen:
            return
        window = self.window()
        if hasattr(window, "title_bar"):
            window.title_bar.hide()
        if hasattr(window, "sidebar_frame"):
            window.sidebar_frame.hide()
        self.nav_bar.hide()
        self.sidebar.hide()
        window.showFullScreen()
        self._viewer_fullscreen = True
        self.fs_btn.setText("📺 Exit Fullscreen")
        self.setFocus()

    def _exit_fullscreen(self):
        if not self._viewer_fullscreen:
            return
        window = self.window()
        if hasattr(window, "title_bar"):
            window.title_bar.show()
        if hasattr(window, "sidebar_frame"):
            window.sidebar_frame.show()
        self.nav_bar.show()
        self.sidebar.show()
        window.showNormal()
        self._viewer_fullscreen = False
        self.fs_btn.setText("📺 Fullscreen")

    def eventFilter(self, obj, event):
        # Esc exits fullscreen; double-clicking the video toggles it.
        if obj is self.video_widget and event.type() == QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton:
                self.toggle_fullscreen()
                return True
        if (
            self._viewer_fullscreen
            and obj is self.video_widget
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self.toggle_fullscreen()
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if self._viewer_fullscreen and event.key() == Qt.Key.Key_Escape:
            self.toggle_fullscreen()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Left and self.prev_btn.isEnabled():
            self._go_prev()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right and self.next_btn.isEnabled():
            self._go_next()
            event.accept()
            return
        super().keyPressEvent(event)

    def stop_playback(self):
        player = getattr(self, "media_player", None)
        if player is not None:
            try:
                # Pause in place so the Play button can resume; the player is
                # fully released by _teardown_player on navigation/close.
                player.pause = True
            except Exception as e:
                print(f"[MediaViewer] Error pausing player: {e}")
        play_btn = getattr(self, "play_btn", None)
        if play_btn is not None:
            try:
                play_btn.setText("▶ Play")
            except RuntimeError:
                pass

    def on_back_clicked(self):
        self.stop_playback()
        get_router().back()

    def hideEvent(self, event):
        # Restore the chrome + window state if we leave while fullscreen.
        if self._viewer_fullscreen:
            self.toggle_fullscreen()
        self._teardown_player()
        super().hideEvent(event)

    def closeEvent(self, event):
        if self._viewer_fullscreen:
            self.toggle_fullscreen()
        self._teardown_player()
        super().closeEvent(event)
