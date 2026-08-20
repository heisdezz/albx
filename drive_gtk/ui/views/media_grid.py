"""Media grid view.

Thin re-export of the reusable grid widget and media card from
`ui.widgets.media_grid` / `ui.widgets.media_card`, kept for backwards
compatibility with existing imports.
"""

from ui.widgets.media_card import MediaCard
from ui.widgets.media_grid import MediaGridView

__all__ = ["MediaCard", "MediaGridView"]
