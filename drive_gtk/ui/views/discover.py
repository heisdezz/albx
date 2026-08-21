import json
import os
import threading

from gi.repository import Adw, GLib, Gtk

from core.logger import get_logs
from core.scanner import ScanState, active_scans, walk_directory
from router import get_router

DEFAULT_IGNORES = [
    "temp",
    "cache",
    "raw",
    "backups",
    "archive",
    "node_modules",
    "dist",
    "build",
    "albums",
    "System Volume Information",
    "$RECYCLE.BIN",
]

SETTINGS_DIR = os.path.join(os.path.expanduser("~/.config"), "antigravity_drive_media")
IGNORE_LISTS_FILE = os.path.join(SETTINGS_DIR, "ignore_lists.json")


def escape_markup(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""))


def load_ignore_list(drive_path: str) -> list:
    # Current in-app storage, keyed by drive path.
    try:
        with open(IGNORE_LISTS_FILE, "r") as f:
            data = json.load(f)
            if drive_path in data and isinstance(data[drive_path], list):
                return data[drive_path]
    except Exception:
        pass

    # Legacy: the list used to be stored inside the drive's album dir.
    legacy_file = os.path.join(drive_path, "albums", ".media_library_settings.json")
    if os.path.exists(legacy_file):
        try:
            with open(legacy_file, "r") as f:
                data = json.load(f)
                return data.get("ignoreList", DEFAULT_IGNORES)
        except Exception:
            return DEFAULT_IGNORES
    return DEFAULT_IGNORES


def save_ignore_list(drive_path: str, ignore_list: list) -> None:
    data = {}
    try:
        with open(IGNORE_LISTS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data[drive_path] = ignore_list
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    try:
        with open(IGNORE_LISTS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Settings] Failed to save ignore list: {e}")


class DiscoverView(Gtk.Box):
    def __init__(self, parent_window, drive):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.parent_window = parent_window
        self.drive = drive
        self.ignore_list = load_ignore_list(drive["path"]) if drive else []
        self.scan_state = None

        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(16)
        self.set_margin_bottom(16)

        self.build_ui()
        self.start_log_timer()

    def build_ui(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.append(scroll)

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        layout.set_margin_start(12)
        layout.set_margin_end(12)
        layout.set_margin_top(12)
        layout.set_margin_bottom(24)
        scroll.set_child(layout)

        # Header Section
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label()
        title.set_markup("<span size='xx-large' weight='black'>Media Discovery</span>")
        title.set_halign(Gtk.Align.START)

        path_str = self.drive["path"] if self.drive else "No Drive Loaded"
        subtitle = Gtk.Label(label=f"Scan and catalog media files in: {path_str}")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")

        title_box.append(title)
        title_box.append(subtitle)
        layout.append(title_box)

        # --- GROUP 1: SCAN CONTROLLER ---
        scan_group = Adw.PreferencesGroup()
        scan_group.set_title("Scan Controller")
        scan_group.set_description(
            "Scan directory tree, filter ignored subpaths, and index media into SQLite."
        )

        # Stat Cards Box
        stats_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        stats_grid.set_margin_top(8)
        stats_grid.set_margin_bottom(12)

        # Card 1: Files Scanned
        card1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card1.add_css_class("card")
        card1.set_hexpand(True)

        icon1 = Gtk.Image.new_from_icon_name("folder-saved-search-symbolic")
        icon1.set_pixel_size(28)
        card1.append(icon1)

        card1_txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.scanned_stat_lbl = Gtk.Label()
        self.scanned_stat_lbl.set_markup("<span size='x-large' weight='black'>0</span>")
        self.scanned_stat_lbl.set_halign(Gtk.Align.START)

        lbl1 = Gtk.Label(label="Files Checked")
        lbl1.add_css_class("dim-label")
        lbl1.add_css_class("caption")
        lbl1.set_halign(Gtk.Align.START)

        card1_txt.append(self.scanned_stat_lbl)
        card1_txt.append(lbl1)
        card1.append(card1_txt)
        stats_grid.append(card1)

        # Card 2: Media Cataloged
        card2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card2.add_css_class("card")
        card2.set_hexpand(True)

        icon2 = Gtk.Image.new_from_icon_name("camera-photo-symbolic")
        icon2.set_pixel_size(28)
        card2.append(icon2)

        card2_txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.found_stat_lbl = Gtk.Label()
        self.found_stat_lbl.set_markup(
            "<span size='x-large' weight='black' foreground='#818cf8'>0</span>"
        )
        self.found_stat_lbl.set_halign(Gtk.Align.START)

        lbl2 = Gtk.Label(label="Media Cataloged")
        lbl2.add_css_class("dim-label")
        lbl2.add_css_class("caption")
        lbl2.set_halign(Gtk.Align.START)

        card2_txt.append(self.found_stat_lbl)
        card2_txt.append(lbl2)
        card2.append(card2_txt)
        stats_grid.append(card2)

        scan_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scan_box.append(stats_grid)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_visible(False)
        scan_box.append(self.progress_bar)

        self.status_lbl = Gtk.Label(label="Ready to scan volume.")
        self.status_lbl.set_halign(Gtk.Align.START)
        self.status_lbl.add_css_class("dim-label")
        scan_box.append(self.status_lbl)

        self.action_btn = Gtk.Button(label="Start Scan")
        self.action_btn.add_css_class("suggested-action")
        self.action_btn.set_size_request(-1, 42)
        self.action_btn.connect("clicked", self.on_action_clicked)
        scan_box.append(self.action_btn)

        scan_group.add(scan_box)
        layout.append(scan_group)

        # --- GROUP 2: PATH IGNORE RULES ---
        ignore_group = Adw.PreferencesGroup()
        ignore_group.set_title("Path &amp; Directory Ignorelist")
        ignore_group.set_description(
            "Subfolders or files matching these rules will be skipped during scanning."
        )

        # Entry Row for adding new rules
        self.ignore_entry_row = Adw.EntryRow()
        self.ignore_entry_row.set_title("Add Ignore Rule")
        self.ignore_entry_row.set_show_apply_button(True)
        self.ignore_entry_row.connect("apply", self.on_add_rule_applied)
        ignore_group.add(self.ignore_entry_row)

        # System folder picker button
        pick_btn = Gtk.Button()
        pick_btn.set_icon_name("folder-open-symbolic")
        pick_btn.set_tooltip_text("Pick Folder to Ignore")
        pick_btn.add_css_class("flat")
        pick_btn.connect("clicked", self.on_pick_folder_clicked)
        self.ignore_entry_row.add_suffix(pick_btn)

        # Active Chips Box inside card
        chips_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        chips_card.add_css_class("card")
        chips_card.set_margin_top(8)
        chips_card.set_margin_start(2)
        chips_card.set_margin_end(2)
        chips_card.set_margin_bottom(4)

        chips_title = Gtk.Label(label="Active Ignore Rules:")
        chips_title.set_halign(Gtk.Align.START)
        chips_title.add_css_class("caption")
        chips_title.add_css_class("dim-label")
        chips_card.append(chips_title)

        self.chips_flow = Gtk.FlowBox()
        self.chips_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.chips_flow.set_homogeneous(False)
        self.chips_flow.set_max_children_per_line(30)
        self.chips_flow.set_row_spacing(6)
        self.chips_flow.set_column_spacing(6)
        self.chips_flow.set_margin_top(4)
        self.chips_flow.set_margin_bottom(4)
        chips_card.append(self.chips_flow)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        chips_card.append(sep)

        presets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        presets_box.set_margin_top(2)
        presets_lbl = Gtk.Label(label="Presets:")
        presets_lbl.add_css_class("dim-label")
        presets_lbl.add_css_class("caption")
        presets_box.append(presets_lbl)

        PRESETS = ["temp", "cache", "raw", "backups", "archive"]
        for p in PRESETS:
            p_btn = Gtk.Button(label=f"+ {p}")
            p_btn.add_css_class("flat")
            p_btn.connect("clicked", lambda x, name=p: self.add_ignore_rule(name))
            presets_box.append(p_btn)

        chips_card.append(presets_box)
        ignore_group.add(chips_card)
        layout.append(ignore_group)

        # --- GROUP 3: LIVE SCANNER LOGS ---
        logs_group = Adw.PreferencesGroup()
        logs_group.set_title("Live Scanner Logs")

        logs_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        logs_card.add_css_class("card")

        logs_scroll = Gtk.ScrolledWindow()
        logs_scroll.set_size_request(-1, 150)

        self.logs_text = Gtk.TextView()
        self.logs_text.set_editable(False)
        self.logs_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.logs_text.set_monospace(True)
        self.logs_text.set_margin_start(8)
        self.logs_text.set_margin_top(8)
        self.logs_text.set_margin_bottom(8)
        self.logs_text.set_margin_end(8)

        logs_scroll.set_child(self.logs_text)
        logs_card.append(logs_scroll)
        logs_group.add(logs_card)
        layout.append(logs_group)

        self.render_chips()

    def render_chips(self):
        while True:
            child = self.chips_flow.get_first_child()
            if not child:
                break
            self.chips_flow.remove(child)

        for pattern in self.ignore_list:
            chip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            chip_box.add_css_class("chip")
            chip_box.set_halign(Gtk.Align.START)
            chip_box.set_valign(Gtk.Align.CENTER)

            lbl = Gtk.Label(label=pattern)
            lbl.add_css_class("chip-label")
            chip_box.append(lbl)

            if pattern in DEFAULT_IGNORES:
                chip_box.add_css_class("dim-label")
            else:
                del_btn = Gtk.Button()
                del_btn.set_icon_name("window-close-symbolic")
                del_btn.add_css_class("flat")
                del_btn.add_css_class("chip-close")
                del_btn.set_valign(Gtk.Align.CENTER)
                del_btn.connect("clicked", lambda x, p=pattern: self.remove_ignore_rule(p))
                chip_box.append(del_btn)

            self.chips_flow.append(chip_box)

    def add_ignore_rule(self, pattern):
        if not self.drive:
            return
        pattern = pattern.strip()
        if pattern and pattern not in self.ignore_list:
            self.ignore_list.append(pattern)
            save_ignore_list(self.drive["path"], self.ignore_list)
            self.render_chips()

    def remove_ignore_rule(self, pattern):
        if not self.drive:
            return
        if pattern in DEFAULT_IGNORES:
            return
        if pattern in self.ignore_list:
            self.ignore_list.remove(pattern)
            save_ignore_list(self.drive["path"], self.ignore_list)
            self.render_chips()

    def on_add_rule_applied(self, entry_row):
        text = entry_row.get_text()
        if text:
            self.add_ignore_rule(text)
            entry_row.set_text("")

    def on_pick_folder_clicked(self, btn):
        if not self.drive:
            return
        drive_path = self.drive["path"]

        def on_folder_selected(folder_path):
            if not folder_path:
                return
            rel = os.path.relpath(folder_path, drive_path)
            if rel in (".", ""):
                return
            if rel.startswith(".."):
                # Picked folder is outside the drive; fall back to its name.
                rel = os.path.basename(folder_path)

            entry = rel.replace(os.sep, "/")
            if entry and entry not in self.ignore_list:
                self.ignore_list.append(entry)
                save_ignore_list(drive_path, self.ignore_list)
                self.render_chips()

        self.select_folder_dialog("Select a folder to ignore", on_folder_selected)

    def select_folder_dialog(self, title, callback):
        if hasattr(Gtk, "FileDialog"):
            dialog = Gtk.FileDialog.new()
            dialog.set_title(title)

            def on_finish(source, result):
                try:
                    gfile = source.select_folder_finish(result)
                    path = gfile.get_path()
                    GLib.idle_add(callback, path)
                except Exception:
                    GLib.idle_add(callback, None)

            dialog.select_folder(self.parent_window, None, on_finish)
        else:
            dialog = Gtk.FileChooserNative.new(
                title,
                self.parent_window,
                Gtk.FileChooserAction.SELECT_FOLDER,
                "Select",
                "Cancel"
            )

            def on_response(dialog, response_id):
                if response_id == Gtk.ResponseType.ACCEPT:
                    gfile = dialog.get_file()
                    path = gfile.get_path() if gfile else None
                    GLib.idle_add(callback, path)
                else:
                    GLib.idle_add(callback, None)
                dialog.destroy()

            dialog.connect("response", on_response)
            dialog.show()

    def on_action_clicked(self, btn):
        if not self.drive:
            return
        if self.scan_state and self.scan_state.scanning:
            self.scan_state.scanning = False
            self.status_lbl.set_text("Aborting scan...")
            btn.set_sensitive(False)
        else:
            self.scan_state = ScanState(self.drive["path"])
            active_scans[self.drive["path"]] = self.scan_state

            self.action_btn.set_label("Stop Scan")
            self.action_btn.remove_css_class("suggested-action")
            self.action_btn.add_css_class("destructive-action")
            self.progress_bar.set_visible(True)
            self.progress_bar.pulse()

            self.chips_flow.set_sensitive(False)
            self.ignore_entry_row.set_sensitive(False)

            threading.Thread(target=self.run_scanner, daemon=True).start()

    def run_scanner(self):
        db_path = os.path.join(self.drive["path"], "albums", ".media_library.db")
        albums_dir = os.path.join(self.drive["path"], "albums")
        unknown_dir = os.path.join(albums_dir, "unknown")
        os.makedirs(unknown_dir, exist_ok=True)

        walk_directory(
            drive_path=self.drive["path"],
            start_dir=self.drive["path"],
            db_path=db_path,
            scan_state=self.scan_state,
            ignore_list=self.ignore_list,
            progress_callback=self.on_scan_progress,
        )

        GLib.idle_add(self.on_scan_finished)

    def on_scan_progress(self, scanned, found, current_file):
        self.scanned_stat_lbl.set_markup(
            f"<span size='x-large' weight='black'>{scanned}</span>"
        )
        self.found_stat_lbl.set_markup(
            f"<span size='x-large' weight='black' foreground='#818cf8'>{found}</span>"
        )
        self.status_lbl.set_text(f"Currently indexing: ...{current_file[-35:]}")
        self.progress_bar.pulse()

    def on_scan_finished(self):
        self.action_btn.set_label("Start Scan")
        self.action_btn.remove_css_class("destructive-action")
        self.action_btn.add_css_class("suggested-action")
        self.action_btn.set_sensitive(True)
        self.progress_bar.set_visible(False)
        self.status_lbl.set_text("Scan completed.")

        self.chips_flow.set_sensitive(True)
        self.ignore_entry_row.set_sensitive(True)

        self.scan_state = None
        if self.drive and self.drive["path"] in active_scans:
            del active_scans[self.drive["path"]]

    def start_log_timer(self):
        GLib.timeout_add(1000, self.refresh_logs)

    def refresh_logs(self):
        logs = get_logs()
        relevant_logs = logs[-30:]

        text_lines = []
        for l in relevant_logs:
            ctx = f" ({l['context']})" if l.get("context") else ""
            text_lines.append(f"[{l['level'].upper()}] {l['message']}{ctx}")

        buffer = self.logs_text.get_buffer()
        buffer.set_text("\n".join(text_lines))

        adj = self.logs_text.get_vadjustment()
        if adj:
            adj.set_value(adj.get_upper() - adj.get_page_size())

        return True
