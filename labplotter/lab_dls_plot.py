"""Lab DLS rendering and movable mean labels shared by desktop and web."""
from __future__ import annotations

from dataclasses import dataclass

from matplotlib.figure import Figure
from matplotlib.ticker import LogLocator, FuncFormatter
import numpy as np

from .lab_dls import distribution_statistics, representative_curve
from .plotting import PlotOptions, SERIES_PALETTE, apply_origin_style, font_family_for_text


@dataclass
class DLSStyle:
    show_lines: bool = True
    show_labels: bool = True
    line_style: str = "--"
    line_width: float = 1.2
    font_size: float = 10.0
    font_family: str = "Arial"
    bold: bool = False
    color: str = ""  # blank follows the curve
    alpha: float = 0.85
    decimals: int = 2
    log_x: bool = True


def dls_plot_options():
    return PlotOptions("Radius", "nm", "Intensity", "%", x_min=0.01, x_max=1_000_000,
                       y_min=0, y_max=20, tick_font_size=10, x_font_size=12, y_font_size=12,
                       legend_font_size=9)


def plot_series(particles, overlay=False, all_measurements=False, average=False):
    curves, errors = [], []
    representative = average or (overlay and not all_measurements)
    for pi, p in enumerate(particles):
        if representative:
            try:
                measurements = [representative_curve(p)]
            except ValueError as exc:
                errors.append(f"{p.name}: {exc}")
                continue
        else:
            measurements = p.measurements
        for mi, m in enumerate(measurements):
            if m.excluded or m.hidden:
                continue
            label = p.name if representative else (f"{p.name} / {m.name}" if overlay else m.name)
            key = f"{p.uid}:{'mean' if representative else m.name}"
            curves.append((key, label, m, SERIES_PALETTE[(pi if overlay else mi) % len(SERIES_PALETTE)],
                           ("-", "--", "-.", ":")[mi % 4] if overlay and all_measurements else "-"))
    return curves, errors


def draw_dls(axis, options, curves, style, positions=None, colors=None):
    positions, colors = positions or {}, colors or {}
    if style.log_x and any(v is not None and (not np.isfinite(v) or v <= 0) for v in (options.x_min, options.x_max)):
        raise ValueError("Logarithmic radius bounds must be finite and positive.")
    if options.x_min is not None and options.x_max is not None and options.x_min >= options.x_max:
        raise ValueError("X minimum must be less than X maximum.")
    if options.y_min is not None and options.y_max is not None and options.y_min >= options.y_max:
        raise ValueError("Y minimum must be less than Y maximum.")
    if style.log_x:
        axis.set_xscale("log")
        axis.xaxis.set_major_locator(LogLocator(base=10, numticks=6))
        axis.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    axis.set_xlim(options.x_min if options.x_min is not None else 0.01,
                  options.x_max if options.x_max is not None else 1_000_000)
    # Set limits before placing labels in axes coordinates, including zoomed views.
    axis.set_ylim(options.y_min if options.y_min is not None else 0,
                  options.y_max if options.y_max is not None else max([20, *[float(c[2].intensity.max()) * 1.1 for c in curves]]))
    labels = {}
    for index, (key, label, m, default_color, line_style) in enumerate(curves):
        color = colors.get(key, default_color)
        axis.plot(m.radius, m.intensity, color=color, linewidth=options.line_width, linestyle=line_style, label=label)
        mean = distribution_statistics(m)["mean_radius"]
        if mean is None:
            continue
        annotation_color = style.color or color
        if style.show_lines:
            line = axis.axvline(mean, color=annotation_color, linestyle=style.line_style,
                               linewidth=style.line_width, alpha=style.alpha, label="_mean_radius")
            line.set_gid("lab-dls-mean-line")
        if style.show_labels:
            left, right = axis.get_xlim()
            if min(left, right) <= mean <= max(left, right):
                fraction = ((np.log(mean) - np.log(left)) / (np.log(right) - np.log(left)) if style.log_x
                            else (mean-left)/(right-left))
                if options.reverse_x:
                    fraction = 1 - fraction
                # Distinct default rows; users can drag each label thereafter.
                xy = positions.get(key, (float(np.clip(fraction, .17, .83)), .94 - .13 * (index % 6)))
                text = f"{label}\nmean R = {mean:.{style.decimals}f} nm"
                artist = axis.text(*xy, text, transform=axis.transAxes, ha="center", va="top",
                                   fontsize=style.font_size, fontfamily=font_family_for_text(style.font_family, text),
                                   fontweight="bold" if style.bold else "normal", color=annotation_color,
                                   alpha=style.alpha, clip_on=True, zorder=8)
                artist.set_gid("lab-dls-mean-label")
                artist.set_in_layout(False)
                labels[key] = artist
    return labels


def dls_figure(curves, options=None, style=None, positions=None, colors=None):
    figure = Figure(figsize=(8.5, 6.2), dpi=100)
    axis = figure.add_subplot(111)
    options, style = options or dls_plot_options(), style or DLSStyle()
    draw_dls(axis, options, curves, style, positions, colors)
    apply_origin_style(figure, axis, options)
    if options.legend and curves:
        axis.legend(loc="upper right", fontsize=options.legend_font_size, frameon=False)
    figure.tight_layout()
    # Export the same frame shown on the desktop, including positioned labels.
    figure._labplotter_export_current_view = True
    return figure


class MeanLabelDrag:
    """Keep label positions in axes fractions so refresh/copy/resize agree."""
    def __init__(self, pane, positions=None, on_change=None):
        self.pane = pane
        self.positions = positions if positions is not None else {}
        self.on_change = on_change
        self.artists = {}
        self.dragging = None
        self.connections = [pane.canvas.mpl_connect(event, method) for event, method in
                            (("button_press_event", self.press), ("motion_notify_event", self.motion),
                             ("button_release_event", self.release))]

    def set_artists(self, artists):
        self.artists = artists
        self.dragging = None

    def press(self, event):
        if event.button != 1 or event.inaxes is not self.pane.axis or self.pane.toolbar.mode or self.pane._pending_annotation:
            return
        editor = getattr(self.pane, "legend_editor", None)
        if editor is not None and editor.contains(event):
            return
        for key, artist in reversed(list(self.artists.items())):
            if artist.contains(event)[0]:
                point = self.pane.axis.transAxes.inverted().transform((event.x, event.y))
                self.dragging = (key, np.asarray(artist.get_position()) - point)
                break

    def motion(self, event):
        if self.dragging is None or event.x is None or event.y is None:
            return
        key, offset = self.dragging
        point = self.pane.axis.transAxes.inverted().transform((event.x, event.y)) + offset
        point = tuple(float(v) for v in np.clip(point, .015, .985))
        self.artists[key].set_position(point)
        self.positions[key] = point
        self.pane.canvas.draw_idle()

    def release(self, event):
        if self.dragging is not None:
            self.motion(event)
            self.dragging = None
            if self.on_change:
                self.on_change(self.positions)

    def reset(self):
        self.positions.clear()
        if self.on_change:
            self.on_change(self.positions)
        self.pane.refresh()
