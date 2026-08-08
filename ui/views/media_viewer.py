import os
import sqlite3

from PySide6.QtCore import QEvent, Qt, QTime, QUrl
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
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

from router import get_router
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
        self.audio_output = None
        self.video_widget = None
        self.ctrl_card = None
        self.fs_window = None
        self.is_seeking = False
        self.is_fullscreen = False

        # Image state
        self.current_pixmap = None
        self.zoom_factor = 1.0
        self.rotation_angle = 0

        self.build_ui()
        self.load_media_content()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Navigation Header Bar
        nav_row = QHBoxLayout()
        nav_row.setSpacing(12)

        back_btn = QPushButton("◀ Back to Gallery")
        back_btn.clicked.connect(self.on_back_clicked)
        nav_row.addWidget(back_btn)

        filename = os.path.basename(
            self.item.get("current_relative_path", "Media Viewer")
        )
        icon_str = "🎥 " if self.is_video else "🖼️ "
        self.title_lbl = QLabel(f"{icon_str}{filename}")
        self.title_lbl.setObjectName("TitleLabel")
        self.title_lbl.setToolTip(filename)
        nav_row.addWidget(self.title_lbl)
        nav_row.addStretch()

        layout.addLayout(nav_row)

        # Main Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        # Left Column: Viewer + Control Bar
        self.viewer_container = QFrame()
        self.viewer_container.setObjectName("GlassCard")
        vc_layout = QVBoxLayout(self.viewer_container)
        self.vc_layout = vc_layout
        vc_layout.setContentsMargins(12, 12, 12, 12)
        vc_layout.setSpacing(8)

        self.status_lbl = QLabel()
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setObjectName("SubtitleLabel")
        vc_layout.addWidget(self.status_lbl)
        self.status_lbl.hide()

        if self.is_video:
            self.video_widget = QVideoWidget()
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

            self.seek_slider = QSlider(Qt.Orientation.Horizontal)
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
            self.fs_btn = QPushButton("⛶ Fullscreen")
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

        splitter.addWidget(self.viewer_container)

        # Right Column: Rich Metadata Sidebar
        self.sidebar = MetadataSidebar(self.item)
        splitter.addWidget(self.sidebar)
        splitter.setSizes([750, 300])

    def load_media_content(self):
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
            try:
                self.media_player = QMediaPlayer()
                self.audio_output = QAudioOutput()
                self.media_player.setAudioOutput(self.audio_output)
                self.media_player.setVideoOutput(self.video_widget)

                self.media_player.positionChanged.connect(self.on_position_changed)
                self.media_player.durationChanged.connect(self.on_duration_changed)

                self.media_player.setSource(QUrl.fromLocalFile(full_path))
                self.audio_output.setVolume(self.vol_slider.value() / 100.0)
                self.media_player.play()
                self.play_btn.setText("⏸ Pause")
            except Exception as e:
                self.show_error(f"Failed to play video: {e}")
        else:
            pixmap = QPixmap(full_path)
            if not pixmap.isNull():
                self.current_pixmap = pixmap
                self.update_image_display()
            else:
                self.show_error("Failed to load image contents.")

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

    def toggle_play_pause(self):
        if not self.media_player:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_btn.setText("▶ Play")
        else:
            self.media_player.play()
            self.play_btn.setText("⏸ Pause")

    def toggle_mute(self):
        if not self.audio_output:
            return
        is_muted = self.audio_output.isMuted()
        self.audio_output.setMuted(not is_muted)
        self.mute_btn.setText("🔇" if not is_muted else "🔊")

    def on_volume_changed(self, value: int):
        if self.audio_output:
            self.audio_output.setVolume(value / 100.0)

    def on_speed_changed(self, speed_str: str):
        if self.media_player:
            try:
                rate = float(speed_str.replace("x", ""))
                self.media_player.setPlaybackRate(rate)
            except ValueError:
                pass

    def on_duration_changed(self, duration_ms: int):
        self.seek_slider.setRange(0, duration_ms)
        self.update_time_label()

    def on_position_changed(self, position_ms: int):
        if not self.is_seeking:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(position_ms)
            self.seek_slider.blockSignals(False)
            self.update_time_label()

    def on_seek_pressed(self):
        self.is_seeking = True

    def on_seek_moved(self, pos: int):
        self.update_time_label(override_pos=pos)

    def on_seek_released(self):
        if self.media_player:
            self.media_player.setPosition(self.seek_slider.value())
        self.is_seeking = False

    def update_time_label(self, override_pos: int = None):
        if not self.media_player:
            return
        pos = override_pos if override_pos is not None else self.media_player.position()
        dur = self.media_player.duration()
        self.time_lbl.setText(f"{format_time(pos)} / {format_time(dur)}")

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        if not self.video_widget or not self.ctrl_card or self.is_fullscreen:
            return

        self.fs_window = QWidget()
        self.fs_window.setStyleSheet("background-color: #0b0e14;")
        fs_layout = QVBoxLayout(self.fs_window)
        fs_layout.setContentsMargins(12, 12, 12, 12)
        fs_layout.setSpacing(8)

        # Move the video surface + control bar into a dedicated fullscreen
        # window so only the player UI goes fullscreen (not the whole app).
        self.vc_layout.removeWidget(self.video_widget)
        self.vc_layout.removeWidget(self.ctrl_card)
        self.video_widget.setParent(self.fs_window)
        self.ctrl_card.setParent(self.fs_window)

        fs_layout.addWidget(self.video_widget, 1)
        fs_layout.addWidget(self.ctrl_card)

        self.fs_window.installEventFilter(self)
        self.fs_window.showFullScreen()
        self.fs_window.setFocus()
        self.video_widget.setFocus()
        self.fs_btn.setText("⛶ Exit Fullscreen")
        self.is_fullscreen = True

    def _exit_fullscreen(self):
        if not self.fs_window:
            return

        fs_layout = self.fs_window.layout()
        fs_layout.removeWidget(self.video_widget)
        fs_layout.removeWidget(self.ctrl_card)

        self.video_widget.setParent(self.viewer_container)
        self.ctrl_card.setParent(self.viewer_container)
        self.vc_layout.insertWidget(1, self.video_widget, 1)
        self.vc_layout.addWidget(self.ctrl_card)
        self.video_widget.show()
        self.ctrl_card.show()

        self.fs_window.removeEventFilter(self)
        self.fs_window.close()
        self.fs_window.deleteLater()
        self.fs_window = None
        self.fs_btn.setText("⛶ Fullscreen")
        self.is_fullscreen = False

    def eventFilter(self, obj, event):
        # Esc exits fullscreen; double-clicking the video toggles it.
        if obj is self.video_widget and event.type() == QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton:
                self.toggle_fullscreen()
                return True
        if (
            self.is_fullscreen
            and obj in (self.video_widget, self.fs_window)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self.toggle_fullscreen()
            return True
        return super().eventFilter(obj, event)

    def stop_playback(self):
        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                # Intentionally keep the source set so the Play button can
                # resume; clearing it here would make play a no-op.
            except Exception as e:
                print(f"[MediaViewer] Error stopping player: {e}")
        if hasattr(self, "play_btn"):
            self.play_btn.setText("▶ Play")

    def on_back_clicked(self):
        self.stop_playback()
        get_router().back()

    def hideEvent(self, event):
        self._exit_fullscreen()
        self.stop_playback()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._exit_fullscreen()
        self.stop_playback()
        super().closeEvent(event)
