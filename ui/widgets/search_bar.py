from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton
from PySide6.QtCore import Qt, QTimer, Signal

class SearchBarWidget(QWidget):
    search_triggered = Signal(str)

    def __init__(self, placeholder: str = "Search...", delay_ms: int = 500, parent=None):
        super().__init__(parent)
        self.delay_ms = delay_ms

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._emit_search)

        self.build_ui(placeholder)

    def build_ui(self, placeholder: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(self._on_text_changed)
        self.input.returnPressed.connect(self._on_submit)
        layout.addWidget(self.input, 1)

        self.search_btn = QPushButton("🔍")
        self.search_btn.setFixedSize(36, 34)
        self.search_btn.setObjectName("AccentButton")
        self.search_btn.setToolTip("Submit Search")
        self.search_btn.clicked.connect(self._on_submit)
        layout.addWidget(self.search_btn)

    def _on_text_changed(self, text: str):
        self.timer.start(self.delay_ms)

    def _on_submit(self):
        self.timer.stop()
        self._emit_search()

    def _emit_search(self):
        self.search_triggered.emit(self.input.text().strip())

    def text(self) -> str:
        return self.input.text().strip()

    def setText(self, text: str):
        self.input.setText(text)

    def clear(self):
        self.input.clear()
        self._on_submit()
