from PySide6.QtWidgets import QSlider
from PySide6.QtCore import Qt, Signal

class ClickSeekSlider(QSlider):
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            val = self._value_from_pos(event.position().toPoint())
            self.setValue(val)
            self.setSliderDown(True)
            self.sliderPressed.emit()
            self.sliderMoved.emit(val)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            val = self._value_from_pos(event.position().toPoint())
            self.setValue(val)
            self.sliderMoved.emit(val)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
            self.sliderReleased.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _value_from_pos(self, pos) -> int:
        w = self.width()
        if w <= 0:
            return self.minimum()
        pr = max(0.0, min(1.0, pos.x() / w))
        return int(self.minimum() + pr * (self.maximum() - self.minimum()))
