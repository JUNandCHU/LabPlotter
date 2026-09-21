"""Click-to-edit legends shared by every desktop PlotPane.

Geometry uses axes fractions, so copy/export at a different DPI retains it.
Editing decorations are artists which deliberately never render in savefig.
"""
from __future__ import annotations

import math

from matplotlib.legend import Legend
from matplotlib.patches import Rectangle


class SizedLegend(Legend):
    """A legend with a user-sized frame and naturally sized, readable text."""
    def _size_box(self, renderer):
        pad = 2 * self.borderpad * renderer.points_to_pixels(self._fontsize)
        box = self._legend_box
        box.set_width(self.get_bbox_to_anchor().width - pad)
        box.set_height(None)
        natural = box.get_bbox(renderer).height
        box.set_height(max(natural, self.get_bbox_to_anchor().height) - pad)

    def draw(self, renderer):
        self._size_box(renderer)
        super().draw(renderer)

    def get_window_extent(self, renderer=None):
        renderer = renderer or self.get_figure()._get_renderer()
        self._size_box(renderer)
        return super().get_window_extent(renderer)


def resize_legend(axis, handles, labels, kwargs, position, size, style_text):
    """Reflow into columns without shrinking fonts or clipping any entry."""
    renderer = axis.figure.canvas.get_renderer()
    width, height = size[0] * axis.bbox.width, size[1] * axis.bbox.height
    options = {**kwargs, "loc": "lower left", "borderaxespad": 0}
    options.pop("ncol", None)
    candidates = []
    for columns in range(1, len(labels) + 1):
        probe = Legend(axis, handles, labels, ncols=columns, **options)
        style_text(probe)
        bounds = probe.get_window_extent(renderer)
        # Prefer the requested aspect, with a penalty for overflowing content.
        score = abs(math.log((bounds.width / bounds.height) / (width / height)))
        score += 4 * max(0, math.log(bounds.width / width))
        score += 4 * max(0, math.log(bounds.height / height))
        candidates.append((score, columns, bounds.width, bounds.height))
    _, columns, min_width, min_height = min(candidates)
    size = (max(width, min_width) / axis.bbox.width,
            max(height, min_height) / axis.bbox.height)
    legend = SizedLegend(axis, handles, labels, ncols=columns, mode="expand",
                         bbox_to_anchor=(*position, *size), bbox_transform=axis.transAxes, **options)
    style_text(legend)
    # Match Axes.legend's ownership/removal contract.
    axis.legend_ = legend
    legend._remove_method = axis._remove_legend
    return legend, size


class _EditRectangle(Rectangle):
    def draw(self, renderer):
        if not self.figure.canvas.is_saving():
            self.set_bounds(*self.editor.decoration_bounds(renderer)[self.index])
            super().draw(renderer)


class LegendEditor:
    def __init__(self, pane):
        self.pane = pane
        self.artist = None
        self.active = False
        self.dragging = None
        self.decorations = []
        for name, handler in (("button_press_event", self.press), ("motion_notify_event", self.motion),
                              ("button_release_event", self.release), ("key_press_event", self.key),
                              ("draw_event", self.drawn)):
            pane.canvas.mpl_connect(name, handler)

    def attach(self, artist):
        self.artist = artist
        self._remove_decorations()
        if artist is None:
            self.active = False
            self.dragging = None
        self._update_decorations()

    def _remove_decorations(self):
        for item in self.decorations:
            try:
                item.remove()
            except ValueError:
                pass  # Axes.clear already removed it.
        self.decorations = []

    def bounds(self, renderer=None):
        if self.artist is None or not self.artist.get_visible():
            return None
        return self.artist.get_window_extent(renderer or self.pane.canvas.get_renderer())

    def contains(self, event):
        bounds = self.bounds()
        return bounds is not None and event.x is not None and event.y is not None and bounds.padded(8 if self.active else 0).contains(event.x, event.y)

    def decoration_bounds(self, renderer=None):
        bounds = self.bounds(renderer)
        axis = self.pane.axis
        points = axis.transAxes.inverted().transform(bounds.get_points())
        x0, y0 = points[0]; x1, y1 = points[1]
        dx, dy = 7 / axis.bbox.width, 7 / axis.bbox.height
        boxes = [(x0, y0, x1-x0, y1-y0)]
        boxes += [(x-dx/2, y-dy/2, dx, dy) for x,y in ((x0,y0),(x0,y1),(x1,y0),(x1,y1))]
        return boxes

    def _update_decorations(self):
        if not self.active or self.artist is None:
            self._remove_decorations()
            return
        axis = self.pane.axis
        boxes = self.decoration_bounds()
        if not self.decorations:
            for i in range(5):
                item = _EditRectangle((0,0), 1, 1, transform=axis.transAxes,
                    facecolor="none" if i==0 else "white", edgecolor="#1674D1",
                    linewidth=1.2, clip_on=False, zorder=1000)
                item.set_in_layout(False)
                item.editor, item.index = self, i
                axis.add_artist(item)
                self.decorations.append(item)
        for item, box in zip(self.decorations, boxes):
            item.set_bounds(*box)

    def drawn(self, _event):
        if not self.pane.canvas.is_saving():
            self._update_decorations()

    def deactivate(self):
        self.active = False
        self.dragging = None
        self._remove_decorations()
        self.pane.canvas.draw_idle()

    def press(self, event):
        if event.button != 1:
            return
        if self.pane.toolbar.mode or self.pane._pending_annotation:
            self.deactivate()
            return
        if not self.contains(event):
            self.deactivate()
            return
        self.pane.canvas.get_tk_widget().focus_set()
        if not self.active:
            # Freeze automatic "best" placement before adding edit handles;
            # otherwise Matplotlib treats those handles as obstacles and the
            # legend jumps to another corner on the very next draw.
            bounds = self.bounds()
            self.pane.legend_position = tuple(float(v) for v in
                self.pane.axis.transAxes.inverted().transform((bounds.x0, bounds.y0)))
            self.active = True
            self.pane._create_legend()
            self.pane.canvas.draw_idle()
            return  # First click unlocks; a later drag edits.
        bounds = self.bounds()
        corner = None
        for ix,x in enumerate((bounds.x0,bounds.x1)):
            for iy,y in enumerate((bounds.y0,bounds.y1)):
                if abs(event.x-x)<=9 and abs(event.y-y)<=9:
                    corner = (ix,iy)
        self.dragging = (event.x, event.y, bounds.frozen(), corner)

    def motion(self, event):
        if self.dragging is None or event.x is None or event.y is None:
            return
        px,py,bounds,corner = self.dragging
        dx,dy = event.x-px, event.y-py
        if corner is None:
            x0,y0,x1,y1 = bounds.x0+dx,bounds.y0+dy,bounds.x1+dx,bounds.y1+dy
        else:
            ix,iy = corner
            x0 = min(bounds.x0+dx,bounds.x1-30) if ix==0 else bounds.x0
            x1 = max(bounds.x1+dx,bounds.x0+30) if ix==1 else bounds.x1
            y0 = min(bounds.y0+dy,bounds.y1-20) if iy==0 else bounds.y0
            y1 = max(bounds.y1+dy,bounds.y0+20) if iy==1 else bounds.y1
        axis = self.pane.axis
        start,end = axis.transAxes.inverted().transform(((x0,y0),(x1,y1)))
        self.pane.legend_position = tuple(float(v) for v in start)
        if corner is not None:
            self.pane.legend_size = tuple(float(v) for v in end-start)
        self.pane._create_legend()
        self._update_decorations()
        self.pane.canvas.draw_idle()

    def release(self, _event):
        if self.dragging is not None:
            self.dragging = None
            callback = self.pane.legend_position_changed
            if callback is not None:
                callback(self.pane.legend_position)

    def key(self, event):
        if event.key == "escape":
            self.deactivate()
