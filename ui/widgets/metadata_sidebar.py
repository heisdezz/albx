import os
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt

class MetadataSidebar(QFrame):
    def __init__(self, item: dict = None, parent=None):
        super().__init__(parent)
        self.item = item or {}
        self.setObjectName("GlassCard")
        self.setFixedWidth(300)
        self.build_ui()

    def build_ui(self):
        # Scroll area with horizontal scrollbar always disabled
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("background: transparent; border: none;")

        scroll_content = QWidget()
        # Enforce maximum width on the content to prevent horizontal expansion
        scroll_content.setMaximumWidth(280)
        
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Section Header
        header_box = QVBoxLayout()
        m_title = QLabel("📋 Media Metadata")
        m_title.setObjectName("SectionHeader")
        m_sub = QLabel("Detailed file properties & volume inspection")
        m_sub.setObjectName("SubtitleLabel")
        header_box.addWidget(m_title)
        header_box.addWidget(m_sub)
        layout.addLayout(header_box)

        # Card 1: File Overview
        file_card, fc_layout = self.create_sidebar_card("📄 File Overview")
        rel_path = self.item.get("current_relative_path", "-")
        fname = os.path.basename(rel_path)
        
        # Enforce wrapping/eliding on filename
        fc_layout.addWidget(self.create_meta_row("Filename", fname, bold=True))
        fc_layout.addWidget(self.create_meta_row("Relative Path", rel_path))
        layout.addWidget(file_card)

        # Card 2: Format & Specs
        specs_card, sc_layout = self.create_sidebar_card("📐 Specifications")
        mime = self.item.get("mime_type", "unknown")
        sc_layout.addWidget(self.create_meta_row("MIME Type", mime, badge=True))

        size_bytes = self.item.get("file_size", 0) or 0
        if size_bytes > (1024 * 1024 * 1024):
            size_str = f"{size_bytes / (1024**3):.2f} GB"
        else:
            size_str = f"{size_bytes / (1024**2):.2f} MB"
        sc_layout.addWidget(self.create_meta_row("File Size", f"{size_str} ({size_bytes:,} B)"))

        created = self.item.get("created_at", "-")
        sc_layout.addWidget(self.create_meta_row("Indexed Date", created))
        layout.addWidget(specs_card)

        # Card 3: Storage Hash & Tags
        hash_card, hc_layout = self.create_sidebar_card("🏷️ Integrity & Hash")
        file_hash = self.item.get("file_hash") or "Not calculated"
        # Truncate sha256 to fit sidebar nicely
        hc_layout.addWidget(self.create_meta_row("SHA-256", file_hash))
        layout.addWidget(hash_card)

        layout.addStretch()
        scroll.setWidget(scroll_content)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

    def create_sidebar_card(self, title_text: str):
        card = QFrame()
        card.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.25); border-radius: 8px; padding: 8px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        lbl = QLabel(title_text)
        lbl.setStyleSheet("font-weight: 700; font-size: 12px; color: #89b4fa;")
        layout.addWidget(lbl)
        return card, layout

    def create_meta_row(self, label: str, value: str, bold: bool = False, badge: bool = False) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)

        lbl = QLabel(label.upper())
        lbl.setStyleSheet("font-size: 9px; font-weight: 800; color: #6c7086;")
        layout.addWidget(lbl)

        # Use selectable and word wrap enabled label to ensure copy-pasteability and wrapping
        val_lbl = QLabel()
        val_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        # Word wrapping long lines containing underscores or paths can fail to break correctly.
        # We can format the value with space breaks or simple eliding if the filename or path is too long.
        text_value = str(value)
        val_lbl.setText(text_value)
        val_lbl.setWordWrap(True)
        
        # Set max width to force word wrapping in layouts
        val_lbl.setMaximumWidth(250)

        if badge:
            val_lbl.setStyleSheet(
                "background-color: rgba(203, 166, 247, 0.2); color: #cba6f7; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px;"
            )
        elif bold:
            val_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #cdd6f4;")
        else:
            val_lbl.setStyleSheet("font-size: 11px; color: #a6adc8;")

        layout.addWidget(val_lbl)
        return container
