from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame
)
from PySide6.QtCore import Qt, Signal
from ui.widgets.search_bar import SearchBarWidget

class FilterBarWidget(QFrame):
    filter_changed = Signal(dict)

    def __init__(
        self,
        filter_type: str = "ALL",
        sort_by: str = "date",
        sort_order: str = "desc",
        search_query: str = "",
        parent=None
    ):
        super().__init__(parent)
        self.filter_type = filter_type.upper()
        self.sort_by = sort_by
        self.sort_order = sort_order.lower()
        self.search_query = search_query
        self.total_items = 0

        self.setObjectName("GlassCard")
        self.build_ui()

    def build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Left Section: Segmented Filter Buttons + Sort Dropdown + Reset
        left_box = QHBoxLayout()
        left_box.setSpacing(8)

        # Segmented Filter Type Buttons
        self.filter_container = QFrame()
        self.filter_container.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.3); border-radius: 8px; padding: 2px;"
        )
        fc_layout = QHBoxLayout(self.filter_container)
        fc_layout.setContentsMargins(4, 4, 4, 4)
        fc_layout.setSpacing(4)

        self.all_btn = QPushButton("田 All")
        self.all_btn.clicked.connect(lambda: self.set_filter_type("ALL"))
        fc_layout.addWidget(self.all_btn)

        self.img_btn = QPushButton("🖼️ Photos")
        self.img_btn.clicked.connect(lambda: self.set_filter_type("IMAGE"))
        fc_layout.addWidget(self.img_btn)

        self.vid_btn = QPushButton("🎥 Videos")
        self.vid_btn.clicked.connect(lambda: self.set_filter_type("VIDEO"))
        fc_layout.addWidget(self.vid_btn)

        left_box.addWidget(self.filter_container)

        # Sort Dropdown
        left_box.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Date Added", "date")
        self.sort_combo.addItem("File Name", "name")
        self.sort_combo.addItem("File Size", "size")
        self.sort_combo.setFixedWidth(120)
        self.sort_combo.currentIndexChanged.connect(self.on_sort_by_changed)
        left_box.addWidget(self.sort_combo)

        # Sort Order Toggle
        self.sort_btn = QPushButton("DESC ↓")
        self.sort_btn.setFixedWidth(80)
        self.sort_btn.clicked.connect(self.toggle_sort_order)
        left_box.addWidget(self.sort_btn)

        # Reset Button
        self.reset_btn = QPushButton("🔄 Reset")
        self.reset_btn.setObjectName("DestructiveButton")
        self.reset_btn.clicked.connect(self.reset_all)
        self.reset_btn.hide()
        left_box.addWidget(self.reset_btn)

        layout.addLayout(left_box)
        layout.addStretch()

        # Right Section: Items Count Badge + SearchBarWidget
        right_box = QHBoxLayout()
        right_box.setSpacing(10)

        self.count_badge = QLabel("0 items")
        self.count_badge.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.08); color: #cdd6f4; "
            "font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px;"
        )
        right_box.addWidget(self.count_badge)

        self.search_widget = SearchBarWidget(placeholder="Search media files... (Esc to clear)", delay_ms=500)
        self.search_widget.setFixedWidth(280)
        self.search_widget.search_triggered.connect(self.on_search_triggered)
        right_box.addWidget(self.search_widget)

        layout.addLayout(right_box)

        # Pre-select matching item in sort_combo
        self.sort_combo.blockSignals(True)
        for i in range(self.sort_combo.count()):
            if self.sort_combo.itemData(i) == self.sort_by:
                self.sort_combo.setCurrentIndex(i)
                break
        self.sort_combo.blockSignals(False)

        # Pre-populate sort order button
        self.sort_btn.setText("ASC ↑" if self.sort_order == "asc" else "DESC ↓")

        # Pre-populate search query text
        if hasattr(self, "search_widget"):
            self.search_widget.input.blockSignals(True)
            self.search_widget.setText(self.search_query)
            self.search_widget.input.blockSignals(False)

        self.update_button_styles()

    def set_filter_type(self, ftype: str):
        self.filter_type = ftype.upper()
        self.update_button_styles()
        self.notify_change()

    def on_sort_by_changed(self, idx: int):
        self.sort_by = self.sort_combo.currentData()
        self.notify_change()

    def toggle_sort_order(self):
        self.sort_order = "asc" if self.sort_order == "desc" else "desc"
        self.sort_btn.setText("ASC ↑" if self.sort_order == "asc" else "DESC ↓")
        self.notify_change()

    def on_search_triggered(self, query: str):
        self.search_query = query
        self.notify_change()

    def set_total_items(self, count: int):
        self.total_items = count
        self.count_badge.setText(f"{count:,} items")

    def reset_all(self):
        self.filter_type = "ALL"
        self.sort_by = "date"
        self.sort_order = "desc"
        self.search_query = ""

        self.search_widget.clear()
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.blockSignals(False)

        self.sort_btn.setText("DESC ↓")
        self.update_button_styles()
        self.notify_change()

    def update_button_styles(self):
        active_style = "background-color: #ff9900; color: #0b0e14; font-weight: 800; border: none;"
        normal_style = "background-color: transparent; color: #b3b1ad; border: none;"

        self.all_btn.setStyleSheet(active_style if self.filter_type == "ALL" else normal_style)
        self.img_btn.setStyleSheet(active_style if self.filter_type == "IMAGE" else normal_style)
        self.vid_btn.setStyleSheet(active_style if self.filter_type == "VIDEO" else normal_style)

        is_filtered = (
            self.filter_type != "ALL" or
            bool(self.search_query) or
            self.sort_by != "date" or
            self.sort_order != "desc"
        )
        self.reset_btn.setVisible(is_filtered)

    def notify_change(self):
        self.update_button_styles()
        self.filter_changed.emit({
            "filter_type": self.filter_type,
            "sort_by": self.sort_by,
            "sort_order": self.sort_order,
            "search_query": self.search_query,
        })
