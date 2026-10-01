"""Named curve colors shared by every desktop plot, before artists are drawn."""
from dataclasses import dataclass
from typing import Callable

from matplotlib.colors import is_color_like, to_hex


@dataclass
class CurveColor:
    key: str
    label: str
    default: str
    colors: dict
    storage_key: str
    changed: Callable | None = None

    @property
    def color(self):
        value = self.colors.get(self.storage_key, self.default)
        return to_hex(value if is_color_like(value) else self.default).upper()

    def set(self, value):
        if value is None:
            self.colors.pop(self.storage_key, None)
        else:
            # Validate before changing any stored setting.
            self.colors[self.storage_key] = to_hex(value).upper()
        if self.changed is not None:
            self.changed()


def begin_curve_colors(axis, colors=None):
    axis._labplotter_color_series = {}
    axis._labplotter_curve_colors = colors if colors is not None else {}


def curve_color(axis, key, label, default, colors=None, storage_key=None, changed=None):
    """Register one stable data identity, returning its current drawing color.

    Associated labels, bands and mean/median lines reuse the returned color;
    they never become accidental, separately editable data curves.
    """
    if not hasattr(axis, "_labplotter_color_series"):
        begin_curve_colors(axis)
    if colors is None:
        colors = axis._labplotter_curve_colors
    entry = CurveColor(str(key), str(label), default, colors,
                       str(key) if storage_key is None else storage_key, changed)
    axis._labplotter_color_series[entry.key] = entry
    return entry.color
