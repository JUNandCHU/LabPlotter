from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
import tempfile
from typing import Any, Iterable

from matplotlib import colormaps
from matplotlib.figure import Figure
from matplotlib.patches import Circle
import numpy as np
from PIL import Image, ImageOps

from .models import Spectrum, ZetaMeasurement
from .nmr import parse_bruker_zip, process_bruker_1d
from .parsers import (
    parse_ftir_file,
    parse_generic_with_profile,
    parse_nanodrop_file,
    parse_zetasizer_workbook,
)
from .plotting import PlotOptions, apply_origin_style, figure_png_bytes, font_family_for_text
from .processing import ftir_peak_indices, mean_curve, normalize, process_ftir
from .tem import TEMAnalysisParameters, TEMImageAnalysis, analyze_tem_image


MAX_WEB_UPLOAD_BYTES = 512 * 1024 * 1024


@dataclass
class WebParseResult:
    kind: str
    spectra: list[Spectrum] | None = None
    measurements: list[ZetaMeasurement] | None = None
    tem: TEMImageAnalysis | None = None
    skipped: list[str] | None = None


def _safe_upload_name(filename: str) -> str:
    name = Path(str(filename)).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("The uploaded file does not have a valid name.")
    return name


def parse_uploaded_payload(
    filename: str,
    payload: bytes,
    kind: str,
    *,
    tem_parameters: TEMAnalysisParameters | None = None,
) -> WebParseResult:
    """Parse browser-uploaded bytes through the same scientific core as desktop.

    Instrument parsers remain path based because some of their upstream readers
    require random-access files. The temporary file is private to the request and
    deleted as soon as the parsed, in-memory result has been produced.
    """
    name = _safe_upload_name(filename)
    if len(payload) > MAX_WEB_UPLOAD_BYTES:
        raise ValueError("The upload exceeds the 512 MB web safety limit.")
    with tempfile.TemporaryDirectory(prefix="labplotter-web-") as temporary:
        path = Path(temporary) / name
        path.write_bytes(payload)
        if kind == "FTIR":
            spectrum = parse_ftir_file(path)
            spectrum.source = name
            return WebParseResult(kind, spectra=[spectrum])
        if kind == "NanoDrop":
            spectra = parse_nanodrop_file(path)
            for spectrum in spectra:
                spectrum.source = name
            return WebParseResult(kind, spectra=spectra)
        if kind == "ssNMR":
            spectra, skipped = parse_bruker_zip(path)
            for spectrum in spectra:
                spectrum.source = name
            return WebParseResult(kind, spectra=spectra, skipped=skipped)
        if kind == "ZetaSizer":
            measurements = parse_zetasizer_workbook(path)
            for measurement in measurements:
                measurement.source_file = name
            return WebParseResult(kind, measurements=measurements)
        if kind == "TEM":
            analysis = analyze_tem_image(path, tem_parameters)
            analysis.source_path = name
            analysis.source_name = name
            return WebParseResult(kind, tem=analysis)
    raise ValueError(f"Unsupported web parser: {kind}")


def parse_generic_payload(filename: str, payload: bytes, profile: dict[str, Any]) -> list[Spectrum]:
    name = _safe_upload_name(filename)
    if len(payload) > MAX_WEB_UPLOAD_BYTES:
        raise ValueError("The upload exceeds the 512 MB web safety limit.")
    with tempfile.TemporaryDirectory(prefix="labplotter-web-") as temporary:
        path = Path(temporary) / name
        path.write_bytes(payload)
        spectra = parse_generic_with_profile(path, profile)
    for spectrum in spectra:
        spectrum.source = name
    return spectra


def processed_ftir_spectra(spectra: Iterable[Spectrum], **options: Any) -> list[Spectrum]:
    output: list[Spectrum] = []
    for spectrum in spectra:
        y = process_ftir(spectrum.x, spectrum.y, **options)
        output.append(replace(spectrum, y=y, metadata=dict(spectrum.metadata)))
    return output


def processed_nmr_spectrum(
    spectrum: Spectrum,
    *,
    phase_mode: str = "Automatic phase",
    extra_line_broadening: float = 0.0,
    phase0: float = 0.0,
    phase1: float = 0.0,
    baseline: bool = False,
    normalize_values: bool = False,
) -> Spectrum:
    metadata = spectrum.metadata
    raw_fid = metadata.get("raw_fid")
    acquisition = metadata.get("acquisition")
    processing = metadata.get("processing")
    if raw_fid is None or not isinstance(acquisition, dict) or not isinstance(processing, dict):
        values = np.asarray(spectrum.y, dtype=float)
        if normalize_values:
            values = normalize(values, "Maximum = 1")
        return replace(spectrum, y=values, metadata=dict(metadata))
    x, y = process_bruker_1d(
        raw_fid,
        acquisition,
        processing,
        phase_mode=phase_mode,
        extra_line_broadening=extra_line_broadening,
        phase0=phase0,
        phase1=phase1,
        baseline=baseline,
        normalize=normalize_values,
    )
    return replace(spectrum, x=x, y=y, metadata=dict(metadata))


def _default_colors(count: int) -> list[str]:
    cmap = colormaps["tab20"]
    return [cmap(index % 20) for index in range(max(1, count))]


def _style_legend(axis, options: PlotOptions) -> None:
    if not options.legend:
        legend = axis.get_legend()
        if legend:
            legend.remove()
        return
    handles, labels = axis.get_legend_handles_labels()
    if not handles:
        return
    columns = 2 if len(labels) > 8 else 1
    legend = axis.legend(handles, labels, frameon=False, ncol=columns, fontsize=options.legend_font_size)
    color = options.legend_color or ("#E8E8E8" if options.background == "Dark" else "black")
    for label in legend.get_texts():
        label.set_fontfamily(font_family_for_text(options.legend_font_family or options.font_family, label.get_text()))
        label.set_fontweight("bold" if options.legend_bold else "normal")
        label.set_color(color)


def spectra_figure(
    spectra: Iterable[Spectrum],
    options: PlotOptions,
    *,
    colors: dict[str, str] | None = None,
    mark_ftir_peaks: bool = False,
    peak_troughs: bool = True,
    width: float = 9.0,
    height: float = 5.5,
) -> Figure:
    visible = [spectrum for spectrum in spectra if spectrum.visible]
    figure = Figure(figsize=(width, height), constrained_layout=True)
    axis = figure.add_subplot(111)
    palette = _default_colors(len(visible))
    for index, spectrum in enumerate(visible):
        color = (colors or {}).get(spectrum.uid, palette[index])
        axis.plot(spectrum.x, spectrum.y, label=spectrum.name, color=color, linewidth=options.line_width)
        if mark_ftir_peaks:
            peaks = ftir_peak_indices(spectrum.y, troughs=peak_troughs)
            axis.scatter(spectrum.x[peaks], spectrum.y[peaks], color=color, s=18, zorder=4)
            for peak in peaks:
                axis.annotate(
                    f"{spectrum.x[peak]:.0f}",
                    (spectrum.x[peak], spectrum.y[peak]),
                    xytext=(0, 7),
                    textcoords="offset points",
                    ha="center",
                    fontsize=max(7.0, float(options.tick_font_size or options.font_size) - 3),
                    color=color,
                )
    apply_origin_style(figure, axis, options)
    _style_legend(axis, options)
    return figure


def zetasizer_curve_figure(
    measurements: Iterable[ZetaMeasurement],
    kind: str,
    particles: Iterable[str],
    options: PlotOptions,
    *,
    colors: dict[str, str] | None = None,
    show_replicates: bool = True,
    show_mean: bool = True,
    mark_maximum: bool = False,
) -> Figure:
    selected = list(dict.fromkeys(particles))
    grouped: dict[str, list[ZetaMeasurement]] = {particle: [] for particle in selected}
    for measurement in measurements:
        if measurement.kind == kind and measurement.particle_name in grouped:
            grouped[measurement.particle_name].append(measurement)
    figure = Figure(figsize=(8.5, 5.2), constrained_layout=True)
    axis = figure.add_subplot(111)
    palette = _default_colors(len(selected))
    for index, particle in enumerate(selected):
        records = grouped.get(particle, [])
        if not records:
            continue
        color = (colors or {}).get(particle, palette[index])
        if show_replicates:
            for record in records:
                axis.plot(record.x, record.y, color=color, alpha=0.25, linewidth=max(0.8, options.line_width * 0.65))
        if show_mean:
            grid, mean, _ = mean_curve([(record.x, record.y) for record in records])
            axis.plot(grid, mean, color=color, linewidth=options.line_width, label=particle)
            peak_x, peak_y = float(grid[int(np.nanargmax(mean))]), float(np.nanmax(mean))
        else:
            record = records[0]
            axis.plot(record.x, record.y, color=color, linewidth=options.line_width, label=particle)
            peak = int(np.nanargmax(record.y))
            peak_x, peak_y = float(record.x[peak]), float(record.y[peak])
        if mark_maximum:
            axis.annotate(
                f"{peak_x:.3g}", (peak_x, peak_y), xytext=(0, 8), textcoords="offset points",
                ha="center", color=color, fontsize=max(8.0, float(options.tick_font_size or 12) - 2),
            )
    if kind == "DLS" and all(np.all(record.x > 0) for records in grouped.values() for record in records):
        axis.set_xscale("log")
    apply_origin_style(figure, axis, options)
    _style_legend(axis, options)
    return figure


def zetasizer_peak_summary(measurements: Iterable[ZetaMeasurement], kind: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for measurement in measurements:
        if measurement.kind != kind or not len(measurement.y):
            continue
        peak = int(np.nanargmax(measurement.y))
        grouped.setdefault(measurement.particle_name, []).append(float(measurement.x[peak]))
    output: list[dict[str, Any]] = []
    for particle, values in grouped.items():
        data = np.asarray(values, dtype=float)
        output.append(
            {
                "Particle": particle,
                "n": int(data.size),
                "Mean peak": float(np.mean(data)),
                "SD": float(np.std(data, ddof=1)) if data.size > 1 else 0.0,
                "Values": values,
            }
        )
    return sorted(output, key=lambda row: str(row["Particle"]).casefold())


def zetasizer_summary_figure(
    rows: Iterable[dict[str, Any]],
    options: PlotOptions,
    *,
    colors: dict[str, str] | None = None,
) -> Figure:
    data = list(rows)
    figure = Figure(figsize=(8.5, 5.2), constrained_layout=True)
    axis = figure.add_subplot(111)
    labels = [str(row["Particle"]) for row in data]
    values = [float(row["Mean peak"]) for row in data]
    errors = [float(row["SD"]) for row in data]
    palette = _default_colors(len(data))
    bar_colors = [(colors or {}).get(label, palette[index]) for index, label in enumerate(labels)]
    axis.bar(np.arange(len(data)), values, yerr=errors, capsize=4, color=bar_colors)
    axis.set_xticks(np.arange(len(data)), labels, rotation=35, ha="right")
    apply_origin_style(figure, axis, options)
    return figure


def tem_overlay_figure(payload: bytes, analysis: TEMImageAnalysis) -> Figure:
    with Image.open(BytesIO(payload)) as opened:
        image = np.asarray(ImageOps.exif_transpose(opened).convert("L"))
    figure = Figure(figsize=(8.0, 6.0), constrained_layout=True)
    axis = figure.add_subplot(111)
    axis.imshow(image, cmap="gray", vmin=0, vmax=255)
    for x, y, radius in analysis.centers_px:
        circle = Circle((x, y), radius, fill=False, edgecolor="#00E5FF", linewidth=1.1)
        axis.add_patch(circle)
    axis.set_title(f"{analysis.batch_name} · {analysis.status} · n={analysis.particle_count}")
    axis.set_axis_off()
    return figure


def tem_distribution_figure(analyses: Iterable[TEMImageAnalysis]) -> Figure:
    grouped: dict[str, list[float]] = {}
    for analysis in analyses:
        if analysis.included and analysis.status == "analyzed":
            grouped.setdefault(analysis.batch_name, []).extend(analysis.diameters_nm)
    figure = Figure(figsize=(8.5, 5.2), constrained_layout=True)
    axis = figure.add_subplot(111)
    colors = _default_colors(len(grouped))
    for index, (batch, values) in enumerate(sorted(grouped.items())):
        data = np.asarray(values, dtype=float)
        if not data.size:
            continue
        bins = min(40, max(8, int(np.sqrt(data.size) * 2)))
        axis.hist(data, bins=bins, density=True, histtype="step", linewidth=2.0, color=colors[index], label=f"{batch} (n={len(data)})")
    options = PlotOptions("Particle diameter", "nm", "Density", "", font_family="DejaVu Sans", reverse_x=False)
    apply_origin_style(figure, axis, options)
    _style_legend(axis, options)
    return figure


def figure_svg_bytes(figure: Figure) -> bytes:
    buffer = BytesIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


__all__ = [
    "WebParseResult",
    "figure_png_bytes",
    "figure_svg_bytes",
    "parse_generic_payload",
    "parse_uploaded_payload",
    "processed_ftir_spectra",
    "processed_nmr_spectrum",
    "spectra_figure",
    "tem_distribution_figure",
    "tem_overlay_figure",
    "zetasizer_curve_figure",
    "zetasizer_peak_summary",
    "zetasizer_summary_figure",
]
