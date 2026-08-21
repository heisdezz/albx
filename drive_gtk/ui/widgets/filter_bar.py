"""Reusable filter bar widget for the GTK UI.

Owns the media filters (search, type, sort, order) plus the selection-mode
controls (select toggle + select all). Hosts stay decoupled from the widget
internals and are notified through callbacks.
"""

from gi.repository import Gtk


class FilterBar(Gtk.Box):
    def __init__(
        self,
        on_filters_changed=None,
        on_select_toggled=None,
        on_select_all=None,
        on_validate=None,
    ):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.on_filters_changed = on_filters_changed
        self.on_select_toggled = on_select_toggled
        self.on_select_all = on_select_all
        self.on_validate = on_validate

        self.search_query = ""
        self.filter_type = "all"
        self.sort_by = "date"
        self.sort_order = "desc"
        self.select_mode = False

        self.build_ui()

    def build_ui(self):
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search media files...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.append(self.search_entry)

        self.type_combo = Gtk.ComboBoxText()
        self.type_combo.append("all", "All Media")
        self.type_combo.append("images", "Images Only")
        self.type_combo.append("videos", "Videos Only")
        self.type_combo.set_active_id("all")
        self.type_combo.connect("changed", self._on_type_changed)
        self.append(self.type_combo)

        self.sort_combo = Gtk.ComboBoxText()
        self.sort_combo.append("date", "Sort: Date Added")
        self.sort_combo.append("name", "Sort: Name")
        self.sort_combo.append("size", "Sort: Size")
        self.sort_combo.set_active_id("date")
        self.sort_combo.connect("changed", self._on_sort_changed)
        self.append(self.sort_combo)

        self.order_btn = Gtk.Button()
        self.order_btn.set_icon_name("media-playlist-consecutive-symbolic")
        self.order_btn.connect("clicked", self._on_order_toggled)
        self.append(self.order_btn)

        if self.on_validate is not None:
            self.validate_btn = Gtk.Button(label="Validate")
            self.validate_btn.set_tooltip_text(
                "Verify files exist on disk and remove missing entries from DB"
            )
            self.validate_btn.connect("clicked", self._on_validate_clicked)
            self.append(self.validate_btn)

        self.select_btn = Gtk.ToggleButton(label="Select")
        self.select_btn.connect("toggled", self._on_select_toggled)
        self.append(self.select_btn)

        self.select_all_btn = Gtk.Button(label="Select All")
        self.select_all_btn.add_css_class("suggested-action")
        self.select_all_btn.set_visible(False)
        self.select_all_btn.connect("clicked", self._on_select_all_clicked)
        self.append(self.select_all_btn)

    # --- filters -------------------------------------------------------------

    def _on_search_changed(self, entry):
        self.search_query = entry.get_text().strip()
        self._notify_filters_changed()

    def _on_type_changed(self, combo):
        self.filter_type = combo.get_active_id()
        self._notify_filters_changed()

    def _on_sort_changed(self, combo):
        self.sort_by = combo.get_active_id()
        self._notify_filters_changed()

    def _on_order_toggled(self, btn):
        self.sort_order = "asc" if self.sort_order == "desc" else "desc"
        self._notify_filters_changed()

    def _notify_filters_changed(self):
        if self.on_filters_changed:
            self.on_filters_changed()

    # --- selection -----------------------------------------------------------

    def _on_select_toggled(self, btn):
        self.select_mode = btn.get_active()
        self.select_btn.set_label("Cancel" if self.select_mode else "Select")
        if self.select_mode:
            self.select_btn.add_css_class("suggested-action")
        else:
            self.select_btn.remove_css_class("suggested-action")
        self.select_all_btn.set_visible(self.select_mode)
        if self.on_select_toggled:
            self.on_select_toggled(self.select_mode)

    def _on_select_all_clicked(self, btn):
        if self.on_select_all:
            self.on_select_all()

    def _on_validate_clicked(self, btn):
        if self.on_validate:
            self.on_validate()

    def set_select_mode(self, active):
        """Programmatically enter/exit selection mode (e.g. after a batch op)."""
        if self.select_btn.get_active() != active:
            self.select_btn.set_active(active)

    def exit_select_mode(self):
        self.set_select_mode(False)

    def set_select_all_label(self, text):
        self.select_all_btn.set_label(text)
