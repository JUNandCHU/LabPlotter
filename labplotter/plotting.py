from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
import re
from uuid import uuid4

from matplotlib.figure import Figure
from matplotlib import font_manager
from matplotlib.ticker import MultipleLocator
from matplotlib.transforms import Bbox
import math


# Shared by desktop curves, bars, TEM distributions, and the web edition.
SERIES_PALETTE = (
    "#000000", "#C00000", "#002060", "#A49F9F", "#006C31", "#401F68", "#B87018",
    "#17BECF", "#E377C2", "#8C564B", "#BCBD22", "#1F77B4", "#FF7F0E", "#2CA02C",
)


def validate_figure_ratio(width, height) -> tuple[float, float]:
    width, height = float(width), float(height)
    if not all(math.isfinite(v) and v > 0 for v in (width, height)) or not 0.1 <= width / height <= 10:
        raise ValueError("Graph width and height must be positive; width/height must be between 0.1 and 10.")
    return width, height


def figure_size_for_ratio(size, ratio):
    if ratio is None:
        return tuple(size)
    width, height = validate_figure_ratio(*ratio)
    scale = max(size) / max(width, height)
    return width * scale, height * scale


@dataclass
class PlotOptions:
    x_label: str = "X"
    x_unit: str = ""
    y_label: str = "Y"
    y_unit: str = ""
    font_family: str = "Arial"
    font_size: float = 12.0
    label_bold: bool = True
    tick_font_family: str | None = None
    tick_font_size: float | None = None
    tick_bold: bool = True
    tick_color: str = ""
    x_font_family: str | None = None
    x_font_size: float | None = None
    x_bold: bool = True
    x_color: str = ""
    y_font_family: str | None = None
    y_font_size: float | None = None
    y_bold: bool = True
    y_color: str = ""
    legend_font_family: str | None = None
    legend_font_size: float | None = None
    legend_bold: bool = False
    legend_color: str = ""
    line_width: float = 2.0
    tick_width: float = 1.5
    tick_length: float = 6.0
    spine_width: float = 1.5
    reverse_x: bool = False
    legend: bool = True
    background: str = "White"
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    x_tick: float | None = None
    y_tick: float | None = None
    # Whole figure (including labels), not the numerical X/Y axis scale.
    figure_ratio: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        self.tick_font_family = self.tick_font_family or self.font_family
        self.x_font_family = self.x_font_family or self.font_family
        self.y_font_family = self.y_font_family or self.font_family
        self.legend_font_family = self.legend_font_family or self.font_family
        self.tick_font_size = self.tick_font_size or self.font_size
        self.x_font_size = self.x_font_size or self.font_size + 1
        self.y_font_size = self.y_font_size or self.font_size + 1
        self.legend_font_size = self.legend_font_size or max(8.0, self.font_size - 1)
        self.tick_bold = bool(self.label_bold if self.tick_bold is True else self.tick_bold)
        self.x_bold = bool(self.label_bold if self.x_bold is True else self.x_bold)
        self.y_bold = bool(self.label_bold if self.y_bold is True else self.y_bold)

    @staticmethod
    def axis_label(name: str, unit: str) -> str:
        name, unit = name.strip(), unit.strip()
        normalized = unit.replace("⁻", "-").translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
        match = re.fullmatch(r"([A-Za-zµμ]+)\s*\^?\s*(-\d+)", normalized)
        if match:
            unit = rf"{match.group(1)}$^{{{match.group(2)}}}$"
        return f"{name} ({unit})" if name and unit else name or unit


@dataclass
class AnnotationSpec:
    kind: str
    coordinates: tuple[float, float, float, float]
    line_style: str = "Solid"
    color: str = "#C62828"
    line_width: float = 2.0
    uid: str = field(default_factory=lambda: uuid4().hex)


_KOREAN_FONT_CANDIDATES = (
    "Malgun Gothic",
    "맑은 고딕",
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "AppleGothic",
    "NanumGothic",
)


@lru_cache(maxsize=1)
def _installed_font_names() -> frozenset[str]:
    return frozenset(item.name for item in font_manager.fontManager.ttflist)


def font_family_for_text(requested: str, text: str) -> str:
    """Use an installed Hangul-capable family when a label contains Korean."""
    if not re.search(r"[\uac00-\ud7a3]", text):
        return requested
    installed = _installed_font_names()
    for family in _KOREAN_FONT_CANDIDATES:
        if family in installed:
            return family
    return requested


def apply_origin_style(figure: Figure, axis, options: PlotOptions) -> None:
    figure._labplotter_ratio = options.figure_ratio
    if options.figure_ratio is not None:
        figure.set_size_inches(*figure_size_for_ratio(figure.get_size_inches(), options.figure_ratio), forward=False)
    dark = options.background == "Dark"
    face = "#333333" if dark else "white"
    ink = "#E8E8E8" if dark else "black"
    tick_color = options.tick_color or ink
    x_color = options.x_color or ink
    y_color = options.y_color or ink
    figure.patch.set_facecolor(face)
    axis.set_facecolor(face)
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(options.spine_width)
        spine.set_color(ink)
    axis.tick_params(
        axis="x", which="major", bottom=True, top=False, labelbottom=True,
        direction="in", width=options.tick_width, length=options.tick_length,
        labelsize=options.tick_font_size, colors=tick_color,
    )
    axis.tick_params(
        axis="y", which="major", left=True, right=False, labelleft=True,
        direction="in", width=options.tick_width, length=options.tick_length,
        labelsize=options.tick_font_size, colors=tick_color,
    )
    x_text = PlotOptions.axis_label(options.x_label, options.x_unit)
    y_text = PlotOptions.axis_label(options.y_label, options.y_unit)
    axis.set_xlabel(
        x_text,
        fontsize=options.x_font_size,
        fontweight="bold" if options.x_bold else "normal",
        fontfamily=font_family_for_text(options.x_font_family or options.font_family, x_text),
        color=x_color,
    )
    axis.set_ylabel(
        y_text,
        fontsize=options.y_font_size,
        fontweight="bold" if options.y_bold else "normal",
        fontfamily=font_family_for_text(options.y_font_family or options.font_family, y_text),
        color=y_color,
    )
    for label in axis.get_xticklabels() + axis.get_yticklabels():
        label.set_fontfamily(options.tick_font_family or options.font_family)
        label.set_fontweight("bold" if options.tick_bold else "normal")
        label.set_color(tick_color)
    axis.grid(False)
    if options.x_min is not None or options.x_max is not None:
        current = axis.get_xlim()
        axis.set_xlim(options.x_min if options.x_min is not None else current[0], options.x_max if options.x_max is not None else current[1])
    if options.y_min is not None or options.y_max is not None:
        current = axis.get_ylim()
        axis.set_ylim(options.y_min if options.y_min is not None else current[0], options.y_max if options.y_max is not None else current[1])
    if options.x_tick and options.x_tick > 0 and axis.get_xscale() == "linear":
        axis.xaxis.set_major_locator(MultipleLocator(options.x_tick))
    if options.y_tick and options.y_tick > 0 and axis.get_yscale() == "linear":
        axis.yaxis.set_major_locator(MultipleLocator(options.y_tick))
    if options.reverse_x:
        left, right = axis.get_xlim()
        if left < right:
            axis.set_xlim(right, left)


def figure_export_bbox(figure: Figure):
    # Tight cropping would silently change a requested square/rectangular ratio.
    if getattr(figure, "_labplotter_ratio", None) is not None:
        return Bbox.from_bounds(0, 0, *figure.get_size_inches())
    return "tight"


def save_plot_figure(figure: Figure, destination, **kwargs) -> None:
    size = figure.get_size_inches().copy()
    positions = [(axis, axis.get_position().frozen(), axis.get_in_layout()) for axis in figure.axes]
    try:
        ratio = getattr(figure, "_labplotter_ratio", None)
        if ratio is not None:
            figure.set_size_inches(*figure_size_for_ratio(size, ratio), forward=False)
            if figure.get_layout_engine() is None:
                figure.tight_layout()
        figure.savefig(destination, bbox_inches=figure_export_bbox(figure), **kwargs)
    finally:
        figure.set_size_inches(size, forward=False)
        for axis, position, in_layout in positions:
            axis.set_position(position)
            axis.set_in_layout(in_layout)


def figure_png_bytes(figure: Figure, dpi: int = 300, transparent: bool = False) -> bytes:
    buffer = BytesIO()
    save_plot_figure(figure, buffer, format="png", dpi=dpi, transparent=transparent)
    return buffer.getvalue()
