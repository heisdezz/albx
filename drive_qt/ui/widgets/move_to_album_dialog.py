from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox
from PySide6.QtCore import Qt

class MoveToAlbumDialog(QDialog):
    def __init__(self, albums: list[dict], parent=None):
        super().__init__(parent)
        self.albums = albums
        self.selected_album = None
        
        self.setWindowTitle("Move to Album")
        self.setFixedSize(360, 450)
        self.setStyleSheet(
            "QDialog { background-color: #131721; color: #cdd6f4; }"
            "QLabel { color: #cdd6f4; }"
        )
        self.build_ui()
        
    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        title = QLabel("📁 Move Selected Items")
        title.setStyleSheet("font-size: 15px; font-weight: 800; color: #ff9900;")
        layout.addWidget(title)
        
        # Search input to filter albums
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search albums...")
        self.search_input.textChanged.connect(self.filter_albums)
        self.search_input.setStyleSheet(
            "QLineEdit { background-color: #181d29; border: 1px solid rgba(255, 255, 255, 0.08); "
            "border-radius: 8px; padding: 6px 10px; color: #cdd6f4; }"
            "QLineEdit:focus { border-color: #ff9900; }"
        )
        layout.addWidget(self.search_input)
        
        # List of albums
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: #181d29; border: 1px solid rgba(255, 255, 255, 0.08); "
            "border-radius: 8px; padding: 6px; color: #cdd6f4; outline: none; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 4px; color: #cdd6f4; }"
            "QListWidget::item:hover { background-color: rgba(255, 255, 255, 0.05); }"
            "QListWidget::item:selected { background-color: rgba(255, 153, 0, 0.18); color: #ff9900; font-weight: bold; }"
        )
        self.list_widget.itemDoubleClicked.connect(self.on_confirm)
        layout.addWidget(self.list_widget, 1)
        
        self.populate_list()
        
        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background-color: #181d29; border: 1px solid rgba(255, 255, 255, 0.08); "
            "border-radius: 8px; padding: 8px 14px; font-weight: bold; color: #cdd6f4; }"
            "QPushButton:hover { background-color: #232939; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        self.confirm_btn = QPushButton("Move Items")
        self.confirm_btn.setStyleSheet(
            "QPushButton { background-color: #ff9900; border: none; border-radius: 8px; "
            "padding: 8px 14px; font-weight: bold; color: #0b0e14; }"
            "QPushButton:hover { background-color: #ffb338; }"
        )
        self.confirm_btn.clicked.connect(self.on_confirm)
        btn_layout.addWidget(self.confirm_btn)
        
        layout.addLayout(btn_layout)

    def populate_list(self):
        self.list_widget.clear()
        search_term = self.search_input.text().lower()
        for a in self.albums:
            name = "Unsorted Media" if a["name"] == "unknown" else a["name"]
            if search_term and search_term not in name.lower():
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, a)
            self.list_widget.addItem(item)

    def filter_albums(self, text: str):
        self.populate_list()

    def on_confirm(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "No Selection", "Please select a target album.")
            return
        self.selected_album = selected_item.data(Qt.ItemDataRole.UserRole)
        self.accept()
