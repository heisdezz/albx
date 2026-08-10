"""Global media-selection state (port of the React `selection_store.ts`).

The React store copies the `Set` on every change because React needs a new
reference to re-render. Qt doesn't: cards subscribe to signals and mutate only
their own widget, so we mutate the set in place and emit the *changed ids*,
letting each card update just itself (mirroring the store's per-node update
trick without any full-grid refresh).
"""

from PySide6.QtCore import QObject, Signal


class SelectionStore(QObject):
    # Emitted with the set of ids whose selection state just changed.
    selection_changed = Signal(set)
    # Emitted when selection mode is entered/left.
    mode_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self._is_selecting = False
        self._selected: set[int] = set()

    # --- reads ---------------------------------------------------------------

    @property
    def is_selecting(self) -> bool:
        return self._is_selecting

    @property
    def count(self) -> int:
        return len(self._selected)

    def is_selected(self, item_id: int) -> bool:
        return item_id in self._selected

    def selected_ids(self) -> list[int]:
        return list(self._selected)

    # --- mode ----------------------------------------------------------------

    def start(self):
        changed = set(self._selected)
        self._selected.clear()
        self._is_selecting = True
        self.mode_changed.emit(True)
        if changed:
            self.selection_changed.emit(changed)

    def cancel(self):
        changed = set(self._selected)
        self._selected.clear()
        self._is_selecting = False
        self.mode_changed.emit(False)
        if changed:
            self.selection_changed.emit(changed)

    # --- mutations -----------------------------------------------------------

    def toggle(self, item_id: int):
        if item_id in self._selected:
            self._selected.discard(item_id)
        else:
            self._selected.add(item_id)
        self.selection_changed.emit({item_id})

    def clear(self):
        if not self._selected:
            return
        changed = set(self._selected)
        self._selected.clear()
        self.selection_changed.emit(changed)

    def select_many(self, ids):
        to_add = {i for i in ids if i not in self._selected}
        if not to_add:
            return
        self._selected.update(to_add)
        self.selection_changed.emit(to_add)

    def deselect_many(self, ids):
        to_remove = {i for i in ids if i in self._selected}
        if not to_remove:
            return
        self._selected.difference_update(to_remove)
        self.selection_changed.emit(to_remove)


_store: SelectionStore | None = None


def get_selection_store() -> SelectionStore:
    global _store
    if _store is None:
        _store = SelectionStore()
    return _store
