"""Reusable floating paginator widget.

A compact first/prev/next/last pill that can be overlaid on a scroll area
viewport (the host view positions it). It hides itself when there is only
one page, so it stays out of the way when there is nothing to paginate.

Usage::

    pager = FloatingPaginator()
    pager.setParent(some_scroll_area.viewport())  # floats over content
    pager.page_changed.connect(on_page)
    pager.update_pagination(current_page, total_pages)
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class FloatingPaginator(QFrame):
    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = 1
        self.total_pages = 1

        self.setStyleSheet(
            "QFrame { background-color: #131721; border: 1px solid rgba(255, 255, 255, 0.12); "
            "border-radius: 18px; padding: 4px 10px; }"
            "QPushButton { background-color: #181d29; border: 1px solid rgba(255, 255, 255, 0.08); "
            "border-radius: 12px; padding: 4px 10px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background-color: #232939; border-color: #ff9900; color: #ffffff; }"
            "QPushButton:disabled { opacity: 0.4; color: #4b5263; border-color: transparent; }"
        )
        self.build_ui()

    def build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self.first_btn = QPushButton("⏮")
        self.first_btn.setFixedSize(28, 28)
        self.first_btn.clicked.connect(lambda: self.go_to_page(1))
        layout.addWidget(self.first_btn)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedSize(28, 28)
        self.prev_btn.clicked.connect(lambda: self.go_to_page(self.current_page - 1))
        layout.addWidget(self.prev_btn)

        self.page_lbl = QLabel("Page 1 of 1")
        self.page_lbl.setStyleSheet(
            "font-size: 11px; font-weight: 800; color: #ff9900; padding: 0 8px;"
        )
        self.page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.page_lbl)

        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedSize(28, 28)
        self.next_btn.clicked.connect(lambda: self.go_to_page(self.current_page + 1))
        layout.addWidget(self.next_btn)

        self.last_btn = QPushButton("⏭")
        self.last_btn.setFixedSize(28, 28)
        self.last_btn.clicked.connect(lambda: self.go_to_page(self.total_pages))
        layout.addWidget(self.last_btn)

    def update_pagination(self, current_page: int, total_pages: int):
        self.current_page = current_page
        self.total_pages = max(1, total_pages)

        self.page_lbl.setText(f"Page {self.current_page} of {self.total_pages}")
        self.first_btn.setEnabled(self.current_page > 1)
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < self.total_pages)
        self.last_btn.setEnabled(self.current_page < self.total_pages)

        # Nothing to paginate -> stay out of the way.
        self.setVisible(self.total_pages > 1)

    def go_to_page(self, page: int):
        target = max(1, min(page, self.total_pages))
        if target != self.current_page:
            self.current_page = target
            self.page_changed.emit(self.current_page)
