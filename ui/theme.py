import json
import os
from typing import Dict, Any, List

THEMES: Dict[str, Dict[str, str]] = {
    "Ayu Dark": {
        "name": "Ayu Dark",
        "bg_root": "#0b0e14",
        "bg_base": "#0b0e14",
        "bg_surface": "#131721",
        "bg_surface_solid": "#131721",
        "bg_card": "#181d29",
        "bg_card_hover": "#232939",
        "border": "rgba(255, 255, 255, 0.08)",
        "border_focus": "#ff9900",
        "accent": "#ff9900",
        "accent_hover": "#ffb338",
        "accent_dim": "rgba(255, 153, 0, 0.15)",
        "fg_main": "#b3b1ad",
        "fg_title": "#e6b450",
        "fg_sub": "#626a73",
        "fg_muted": "#4b5263",
        "badge_bg": "rgba(255, 153, 0, 0.2)",
        "badge_fg": "#ffb338",
        "sidebar_bg": "#0f131a",
        "sidebar_item_active": "#262014",
        "sidebar_item_hover": "#1c212c",
        "glass_overlay": "#141822",
    },
    "Catppuccin Mocha": {
        "name": "Catppuccin Mocha",
        "bg_root": "#1e1e2e",
        "bg_base": "#1e1e2e",
        "bg_surface": "#252538",
        "bg_surface_solid": "#313244",
        "bg_card": "#2a2b3d",
        "bg_card_hover": "#36374f",
        "border": "rgba(255, 255, 255, 0.10)",
        "border_focus": "#cba6f7",
        "accent": "#cba6f7",
        "accent_hover": "#f5c2e7",
        "accent_dim": "rgba(203, 166, 247, 0.18)",
        "fg_main": "#cdd6f4",
        "fg_title": "#89b4fa",
        "fg_sub": "#a6adc8",
        "fg_muted": "#6c7086",
        "badge_bg": "rgba(203, 166, 247, 0.2)",
        "badge_fg": "#cba6f7",
        "sidebar_bg": "#181825",
        "sidebar_item_active": "#312742",
        "sidebar_item_hover": "#2c2d40",
        "glass_overlay": "#242436",
    },
    "Catppuccin Macchiato": {
        "name": "Catppuccin Macchiato",
        "bg_root": "#24273a",
        "bg_base": "#24273a",
        "bg_surface": "#2b2d42",
        "bg_surface_solid": "#363a4f",
        "bg_card": "#30344d",
        "bg_card_hover": "#3c405e",
        "border": "rgba(255, 255, 255, 0.10)",
        "border_focus": "#8aadf4",
        "accent": "#8aadf4",
        "accent_hover": "#b7bdf8",
        "accent_dim": "rgba(138, 173, 244, 0.18)",
        "fg_main": "#cad3f5",
        "fg_title": "#f5a97f",
        "fg_sub": "#a5adcb",
        "fg_muted": "#6e738d",
        "badge_bg": "rgba(138, 173, 244, 0.2)",
        "badge_fg": "#8aadf4",
        "sidebar_bg": "#1e2030",
        "sidebar_item_active": "#29324a",
        "sidebar_item_hover": "#323650",
        "glass_overlay": "#2a2d42",
    }
}

CONFIG_PATH = os.path.expanduser("~/.config/antigravity_drive_media/theme.json")

class ThemeManager:
    _instance = None

    def __init__(self):
        self.current_theme_name = "Ayu Dark"
        self.opacity = 1.0  # Translucency disabled app-wide
        self.blur_enabled = False
        self.listeners: List[Any] = []
        self.load_config()

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as f:
                    data = json.load(f)
                    name = data.get("theme", "Ayu Dark")
                    if name in THEMES:
                        self.current_theme_name = name
                    self.opacity = 1.0
                    self.blur_enabled = False
            except Exception:
                pass

    def save_config(self):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump({
                    "theme": self.current_theme_name,
                    "opacity": 1.0,
                    "blur_enabled": False,
                }, f, indent=2)
        except Exception as e:
            print(f"[ThemeManager] Error saving config: {e}")

    def get_theme(self) -> Dict[str, str]:
        return THEMES.get(self.current_theme_name, THEMES["Ayu Dark"])

    def set_theme(self, name: str):
        if name in THEMES:
            self.current_theme_name = name
            self.save_config()
            self.notify_listeners()

    def set_opacity(self, value: float):
        self.opacity = 1.0
        self.save_config()
        self.notify_listeners()

    def subscribe(self, callback):
        self.listeners.append(callback)

    def notify_listeners(self):
        for listener in self.listeners:
            try:
                listener()
            except Exception as e:
                print(f"[ThemeManager] Listener error: {e}")

    def generate_qss(self) -> str:
        t = self.get_theme()
        return f"""
        /* Master QSS Theme Specification - Solid Colors */
        QWidget#MainWindowRoot {{
            background-color: {t['bg_root']};
            color: {t['fg_main']};
            font-family: 'Inter', 'Segoe UI', 'Ubuntu', sans-serif;
            font-size: 13px;
        }}

        QWidget#FramelessHeaderBar {{
            background-color: {t['sidebar_bg']};
            border-bottom: 1px solid {t['border']};
        }}

        QFrame#SidebarFrame {{
            background-color: {t['sidebar_bg']};
            border-right: 1px solid {t['border']};
        }}

        QScrollArea {{
            background: transparent;
            border: none;
        }}

        QScrollBar:vertical {{
            border: none;
            background: transparent;
            width: 8px;
            margin: 0px;
        }}

        QScrollBar::handle:vertical {{
            background: {t['fg_muted']};
            min-height: 24px;
            border-radius: 4px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {t['accent']};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        QScrollBar:horizontal {{
            border: none;
            background: transparent;
            height: 8px;
            margin: 0px;
        }}

        QScrollBar::handle:horizontal {{
            background: {t['fg_muted']};
            min-width: 24px;
            border-radius: 4px;
        }}

        QPushButton {{
            background-color: {t['bg_card']};
            color: {t['fg_main']};
            border: 1px solid {t['border']};
            border-radius: 6px;
            padding: 7px 14px;
            font-weight: 600;
        }}

        QPushButton:hover {{
            background-color: {t['bg_card_hover']};
            border-color: {t['accent']};
            color: #ffffff;
        }}

        QPushButton:pressed {{
            background-color: {t['accent_dim']};
        }}

        QPushButton#AccentButton {{
            background-color: {t['accent']};
            color: #0b0e14;
            border: none;
        }}

        QPushButton#AccentButton:hover {{
            background-color: {t['accent_hover']};
        }}

        QPushButton#DestructiveButton {{
            background-color: rgba(243, 139, 168, 0.2);
            color: #f38ba8;
            border: 1px solid rgba(243, 139, 168, 0.4);
        }}

        QPushButton#DestructiveButton:hover {{
            background-color: rgba(243, 139, 168, 0.4);
        }}

        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {t['bg_surface_solid']};
            color: {t['fg_main']};
            border: 1px solid {t['border']};
            border-radius: 6px;
            padding: 6px 10px;
            selection-background-color: {t['accent']};
            selection-color: #000000;
        }}

        QLineEdit:focus, QTextEdit:focus {{
            border: 1px solid {t['border_focus']};
        }}

        QFrame#GlassCard {{
            background-color: {t['bg_card']};
            border: 1px solid {t['border']};
            border-radius: 10px;
        }}

        QFrame#GlassCard:hover {{
            border-color: {t['accent_dim']};
        }}

        QLabel {{
            color: {t['fg_main']};
        }}

        QLabel#TitleLabel {{
            color: {t['fg_title']};
            font-size: 20px;
            font-weight: 800;
        }}

        QLabel#SubtitleLabel {{
            color: {t['fg_sub']};
            font-size: 12px;
        }}

        QLabel#SectionHeader {{
            color: {t['fg_title']};
            font-size: 15px;
            font-weight: 700;
        }}

        QListWidget {{
            background-color: transparent;
            border: none;
            outline: none;
        }}

        QListWidget::item {{
            padding: 9px 12px;
            border-radius: 6px;
            color: {t['fg_main']};
            font-weight: 600;
        }}

        QListWidget::item:hover {{
            background-color: {t['sidebar_item_hover']};
            color: #ffffff;
        }}

        QListWidget::item:selected {{
            background-color: {t['sidebar_item_active']};
            color: {t['accent']};
            font-weight: 700;
        }}

        QComboBox {{
            background-color: {t['bg_surface_solid']};
            color: {t['fg_main']};
            border: 1px solid {t['border']};
            border-radius: 6px;
            padding: 5px 10px;
        }}

        QComboBox:hover {{
            border-color: {t['accent']};
        }}

        QComboBox QAbstractItemView {{
            background-color: {t['bg_surface_solid']};
            color: {t['fg_main']};
            border: 1px solid {t['border']};
            selection-background-color: {t['sidebar_item_active']};
            selection-color: {t['accent']};
        }}

        QProgressBar {{
            background-color: {t['bg_surface_solid']};
            border: 1px solid {t['border']};
            border-radius: 6px;
            text-align: center;
            color: {t['fg_main']};
            font-weight: bold;
        }}

        QProgressBar::chunk {{
            background-color: {t['accent']};
            border-radius: 5px;
        }}

        QCheckBox {{
            color: {t['fg_main']};
            spacing: 6px;
        }}

        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid {t['border']};
            border-radius: 4px;
            background-color: {t['bg_surface_solid']};
        }}

        QCheckBox::indicator:checked {{
            background-color: {t['accent']};
            border-color: {t['accent']};
        }}
        """

def get_theme_manager() -> ThemeManager:
    return ThemeManager.instance()
