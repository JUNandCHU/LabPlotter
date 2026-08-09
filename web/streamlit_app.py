from __future__ import annotations

import csv
import hashlib
from io import StringIO
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import streamlit as st

from labplotter import __version__
from labplotter.models import Spectrum, ZetaMeasurement
from labplotter.plotting import PlotOptions, figure_png_bytes
from labplotter.tem import TEMAnalysisParameters, TEMImageAnalysis
from labplotter.web import (
    figure_svg_bytes,
    parse_generic_payload,
    parse_uploaded_payload,
    processed_ftir_spectra,
    processed_nmr_spectrum,
    spectra_figure,
    tem_distribution_figure,
    tem_overlay_figure,
    zetasizer_curve_figure,
    zetasizer_peak_summary,
    zetasizer_summary_figure,
)


st.set_page_config(page_title="LabPlotter Web", page_icon="🪶", layout="wide")


KO = {
    "Scientific data plotting in your browser": "브라우저에서 사용하는 과학 데이터 플로팅",
    "Language": "언어",
    "About": "안내",
    "The web edition reuses the same parsing, processing, NMR, ZetaSizer, and TEM analysis core as the Windows edition.": "웹 버전은 Windows 버전과 동일한 파싱, 전처리, NMR, ZetaSizer 및 TEM 분석 코어를 사용합니다.",
    "Uploaded files are processed only for this browser session. Download your results before closing the page.": "업로드 파일은 현재 브라우저 세션에서만 처리됩니다. 페이지를 닫기 전에 결과를 다운로드하세요.",
    "Contact and feedback": "연락 및 피드백",
    "Jun Min Moon · moonkeving@gmail.com": "Jun Min Moon · moonkeving@gmail.com",
    "Files": "파일",
    "No usable data were found in the uploaded files.": "업로드 파일에서 사용할 수 있는 데이터를 찾지 못했습니다.",
    "Series": "데이터 목록",
    "Visible series": "표시할 데이터",
    "Series colors": "데이터 색상",
    "Plot settings": "그래프 설정",
    "X-axis name": "X축 이름",
    "X-axis unit": "X축 단위",
    "Y-axis name": "Y축 이름",
    "Y-axis unit": "Y축 단위",
    "Font size": "글꼴 크기",
    "Line width": "선 굵기",
    "Frame width": "프레임 굵기",
    "Tick width": "눈금 굵기",
    "Tick length": "눈금 길이",
    "Reverse X": "X축 반전",
    "Legend": "범례",
    "Dark background": "어두운 배경",
    "Axis limits (leave blank for automatic)": "축 범위(자동은 빈칸)",
    "X minimum": "X 최솟값",
    "X maximum": "X 최댓값",
    "Y minimum": "Y 최솟값",
    "Y maximum": "Y 최댓값",
    "Tick spacing (0 = automatic)": "눈금 간격(0 = 자동)",
    "X spacing": "X 간격",
    "Y spacing": "Y 간격",
    "Download PNG": "PNG 다운로드",
    "Download SVG": "SVG 다운로드",
    "Baseline correction": "베이스라인 보정",
    "Baseline method": "베이스라인 방식",
    "Spectrum orientation": "스펙트럼 방향",
    "Smoothness λ": "평활도 λ",
    "Asymmetry p": "비대칭도 p",
    "Polynomial order": "다항식 차수",
    "Normalization": "정규화",
    "Normalization mode": "정규화 방식",
    "Mark notable peaks": "주요 피크 표시",
    "Ignore blank sheets": "Blank 시트 제외",
    "NMR processing": "NMR 전처리",
    "Phase mode": "위상 방식",
    "Extra line broadening (Hz)": "추가 선폭 증가(Hz)",
    "Zero-order phase (°)": "0차 위상(°)",
    "First-order phase (°)": "1차 위상(°)",
    "Linear baseline": "선형 베이스라인",
    "Normalize maximum": "최댓값 정규화",
    "Skipped experiments": "건너뛴 실험",
    "Particles": "입자",
    "Show replicates": "반복 측정 표시",
    "Show mean curve": "평균 곡선 표시",
    "Mark distribution maximum": "분포 최댓값 표시",
    "DLS distributions": "DLS 분포",
    "Zeta distributions": "제타 전위 분포",
    "DLS peak comparison": "DLS 피크 비교",
    "Zeta peak comparison": "제타 피크 비교",
    "The lower charts summarize each raw distribution's maximum. They are not OCR-derived Z-average or mean zeta-potential values.": "아래 그래프는 각 raw 분포의 최댓값을 요약합니다. OCR 기반 Z-average 또는 평균 제타 전위 값은 아닙니다.",
    "Analysis parameters": "분석 설정",
    "Minimum diameter (nm)": "최소 직경(nm)",
    "Maximum diameter (nm)": "최대 직경(nm)",
    "Minimum center distance (nm)": "최소 중심 거리(nm)",
    "Threshold factor": "임계값 계수",
    "Exclude border particles": "가장자리 입자 제외",
    "Force analysis of blank fields": "빈 화면도 강제 분석",
    "TEM review": "TEM 검토",
    "Batch summary": "배치 요약",
    "Particle-size distributions": "입자 크기 분포",
    "Download particle CSV": "입자 CSV 다운로드",
    "Custom format": "사용자 형식",
    "Upload one spreadsheet and describe its X/Y columns.": "스프레드시트 하나를 올리고 X/Y 열을 지정하세요.",
    "Sheet name (optional)": "시트 이름(선택)",
    "X column": "X 열",
    "Y columns (comma separated)": "Y 열(쉼표로 구분)",
    "Data start row": "데이터 시작 행",
    "Header row": "제목 행",
    "Apply mapping": "매핑 적용",
    "Processing uploaded files…": "업로드 파일 처리 중…",
    "File error": "파일 오류",
    "Web limitations": "웹 버전 제한",
    "Persistent local libraries, Windows clipboard export, editable OCR review, and .labpatch updates remain desktop-only in 0.8.1.": "지속형 로컬 라이브러리, Windows 클립보드 내보내기, OCR 결과 직접 수정 및 .labpatch 업데이트는 0.8.1에서 데스크톱 전용입니다.",
}


def t(text: str) -> str:
    return KO.get(text, text) if st.session_state.get("language", "English") == "한국어" else text


def _float_or_none(value: str) -> float | None:
    try:
        return float(value) if str(value).strip() else None
    except ValueError:
        return None


def _parse_cached(filename: str, payload: bytes, kind: str, tem_values: tuple[Any, ...] | None = None):
    cache = st.session_state.setdefault("_parsed_uploads", {})
    key = (kind, filename, hashlib.sha256(payload).hexdigest(), tem_values)
    if key in cache:
        return cache[key]
    parameters = TEMAnalysisParameters(*tem_values) if tem_values else None
    result = parse_uploaded_payload(filename, payload, kind, tem_parameters=parameters)
    if len(cache) >= 96:
        cache.clear()
    cache[key] = result
    return result


def _generic_cached(filename: str, payload: bytes, profile_items: tuple[tuple[str, Any], ...]):
    cache = st.session_state.setdefault("_generic_uploads", {})
    key = (filename, hashlib.sha256(payload).hexdigest(), profile_items)
    if key in cache:
        return cache[key]
    profile = dict(profile_items)
    profile["y_columns"] = list(profile["y_columns"])
    result = parse_generic_payload(filename, payload, profile)
    if len(cache) >= 32:
        cache.clear()
    cache[key] = result
    return result


def _process_nmr_cached(spectrum: Spectrum, **options: Any) -> Spectrum:
    cache = st.session_state.setdefault("_processed_nmr", {})
    key = (spectrum.uid, tuple(sorted(options.items())))
    if key not in cache:
        if len(cache) >= 64:
            cache.clear()
        cache[key] = processed_nmr_spectrum(spectrum, **options)
    return cache[key]


def _parse_many(uploaded_files, kind: str, tem_values: tuple[Any, ...] | None = None):
    results, errors = [], []
    if not uploaded_files:
        return results, errors
    progress = st.progress(0.0, text=t("Processing uploaded files…"))
    for index, uploaded in enumerate(uploaded_files, start=1):
        try:
            results.append(_parse_cached(uploaded.name, uploaded.getvalue(), kind, tem_values))
        except Exception as exc:
            errors.append(f"{uploaded.name}: {exc}")
        progress.progress(index / len(uploaded_files), text=f"{index}/{len(uploaded_files)} · {uploaded.name}")
    progress.empty()
    return results, errors


def _spectrum_selector(spectra: list[Spectrum], prefix: str) -> list[Spectrum]:
    labels = {spectrum.uid: spectrum.name for spectrum in spectra}
    defaults = [spectrum.uid for spectrum in spectra if spectrum.visible]
    selected = st.multiselect(
        t("Visible series"),
        list(labels),
        default=defaults,
        format_func=lambda uid: labels[uid],
        key=f"{prefix}-visible",
    )
    chosen = set(selected)
    return [Spectrum(
        spectrum.name, spectrum.x, spectrum.y, spectrum.source, spectrum.uid in chosen,
        dict(spectrum.metadata), spectrum.uid,
    ) for spectrum in spectra]


def _series_colors(items: list[tuple[str, str]], prefix: str) -> dict[str, str]:
    defaults = ("#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD", "#8C564B", "#E377C2", "#7F7F7F")
    result: dict[str, str] = {}
    with st.expander(t("Series colors"), expanded=False):
        columns = st.columns(2)
        for index, (uid, label) in enumerate(items):
            with columns[index % 2]:
                result[uid] = st.color_picker(label, defaults[index % len(defaults)], key=f"{prefix}-color-{uid}")
    return result


def _plot_options(prefix: str, defaults: dict[str, Any]) -> PlotOptions:
    with st.expander(t("Plot settings"), expanded=False):
        first = st.columns(4)
        x_label = first[0].text_input(t("X-axis name"), defaults.get("x_label", "X"), key=f"{prefix}-xlabel")
        x_unit = first[1].text_input(t("X-axis unit"), defaults.get("x_unit", ""), key=f"{prefix}-xunit")
        y_label = first[2].text_input(t("Y-axis name"), defaults.get("y_label", "Y"), key=f"{prefix}-ylabel")
        y_unit = first[3].text_input(t("Y-axis unit"), defaults.get("y_unit", ""), key=f"{prefix}-yunit")
        second = st.columns(4)
        font_size = second[0].number_input(t("Font size"), 7.0, 36.0, float(defaults.get("font_size", 12.0)), 1.0, key=f"{prefix}-font")
        line_width = second[1].number_input(t("Line width"), 0.5, 8.0, float(defaults.get("line_width", 2.0)), 0.25, key=f"{prefix}-line")
        spine_width = second[2].number_input(t("Frame width"), 0.5, 6.0, float(defaults.get("spine_width", 1.5)), 0.25, key=f"{prefix}-spine")
        tick_width = second[3].number_input(t("Tick width"), 0.5, 6.0, float(defaults.get("tick_width", 1.5)), 0.25, key=f"{prefix}-tickwidth")
        third = st.columns(4)
        tick_length = third[0].number_input(t("Tick length"), 1.0, 20.0, float(defaults.get("tick_length", 6.0)), 0.5, key=f"{prefix}-ticklength")
        reverse_x = third[1].checkbox(t("Reverse X"), bool(defaults.get("reverse_x", False)), key=f"{prefix}-reverse")
        legend = third[2].checkbox(t("Legend"), bool(defaults.get("legend", True)), key=f"{prefix}-legend")
        dark = third[3].checkbox(t("Dark background"), False, key=f"{prefix}-dark")
        st.caption(t("Axis limits (leave blank for automatic)"))
        limits = st.columns(4)
        x_min = _float_or_none(limits[0].text_input(t("X minimum"), "", key=f"{prefix}-xmin"))
        x_max = _float_or_none(limits[1].text_input(t("X maximum"), "", key=f"{prefix}-xmax"))
        y_min = _float_or_none(limits[2].text_input(t("Y minimum"), "", key=f"{prefix}-ymin"))
        y_max = _float_or_none(limits[3].text_input(t("Y maximum"), "", key=f"{prefix}-ymax"))
        st.caption(t("Tick spacing (0 = automatic)"))
        ticks = st.columns(2)
        x_tick = ticks[0].number_input(t("X spacing"), min_value=0.0, value=0.0, key=f"{prefix}-xtick") or None
        y_tick = ticks[1].number_input(t("Y spacing"), min_value=0.0, value=0.0, key=f"{prefix}-ytick") or None
    return PlotOptions(
        x_label=x_label, x_unit=x_unit, y_label=y_label, y_unit=y_unit,
        font_family="DejaVu Sans",
        font_size=font_size, line_width=line_width, spine_width=spine_width,
        tick_width=tick_width, tick_length=tick_length, reverse_x=reverse_x,
        legend=legend, background="Dark" if dark else "White", x_min=x_min,
        x_max=x_max, y_min=y_min, y_max=y_max, x_tick=x_tick, y_tick=y_tick,
    )


def _show_figure(figure, prefix: str) -> None:
    st.pyplot(figure, width="stretch")
    png = figure_png_bytes(figure)
    svg = figure_svg_bytes(figure)
    buttons = st.columns(2)
    buttons[0].download_button(t("Download PNG"), png, f"LabPlotter_{prefix}.png", "image/png", key=f"{prefix}-png")
    buttons[1].download_button(t("Download SVG"), svg, f"LabPlotter_{prefix}.svg", "image/svg+xml", key=f"{prefix}-svg")


def _errors(errors: list[str]) -> None:
    for error in errors:
        st.error(f"{t('File error')}: {error}")


def ftir_page() -> None:
    uploaded = st.file_uploader(t("Files"), type=["csv", "txt", "tsv", "xlsx", "xlsm"], accept_multiple_files=True, key="ftir-files")
    results, errors = _parse_many(uploaded, "FTIR")
    _errors(errors)
    spectra = [spectrum for result in results for spectrum in (result.spectra or [])]
    if not spectra:
        st.info(t("No usable data were found in the uploaded files."))
        return
    spectra = _spectrum_selector(spectra, "ftir")
    with st.expander(t("Baseline correction"), expanded=True):
        controls = st.columns(4)
        baseline = controls[0].checkbox(t("Baseline correction"), False, key="ftir-baseline")
        method = controls[1].selectbox(t("Baseline method"), [
            "Linear endpoints (diagonal)", "Rubberband (convex hull)", "Modified polynomial (ModPoly)",
            "AsLS (asymmetric least squares)", "arPLS (asymmetrically reweighted PLS)", "airPLS (adaptive reweighted PLS)",
        ], key="ftir-method")
        orientation = controls[2].selectbox(t("Spectrum orientation"), ["Transmittance (downward bands)", "Absorbance (upward bands)"], key="ftir-orientation")
        normalization_enabled = controls[3].checkbox(t("Normalization"), False, key="ftir-normalize")
        parameters = st.columns(4)
        lam = parameters[0].number_input(t("Smoothness λ"), 1e2, 1e12, 1e8, format="%.1e", key="ftir-lam")
        p_value = parameters[1].number_input(t("Asymmetry p"), 0.0001, 0.5, 0.01, format="%.4f", key="ftir-p")
        poly_order = parameters[2].number_input(t("Polynomial order"), 1, 8, 2, key="ftir-poly")
        normalization_mode = parameters[3].selectbox(t("Normalization mode"), ["Min-max (0–1)", "Maximum = 1", "Vector (L2)"], key="ftir-normmode")
        mark_peaks = st.checkbox(t("Mark notable peaks"), False, key="ftir-peaks")
    processed = processed_ftir_spectra(
        spectra, baseline_enabled=baseline, baseline_method=method, orientation=orientation,
        lam=lam, p=p_value, poly_order=poly_order, normalization_enabled=normalization_enabled,
        normalization_mode=normalization_mode,
    )
    colors = _series_colors([(item.uid, item.name) for item in processed if item.visible], "ftir")
    y_label = "Transmittance" if orientation.startswith("Transmittance") else "Absorbance"
    y_unit = "" if normalization_enabled else "%" if orientation.startswith("Transmittance") else "a.u."
    options = _plot_options("ftir", {"x_label": "Wavenumber", "x_unit": "cm^-1", "y_label": y_label, "y_unit": y_unit, "reverse_x": True})
    _show_figure(spectra_figure(processed, options, colors=colors, mark_ftir_peaks=mark_peaks, peak_troughs=orientation.startswith("Transmittance")), "FTIR")


def nanodrop_page() -> None:
    uploaded = st.file_uploader(t("Files"), type=["xml", "xlsx", "xlsm"], accept_multiple_files=True, key="nano-files")
    results, errors = _parse_many(uploaded, "NanoDrop")
    _errors(errors)
    spectra = [spectrum for result in results for spectrum in (result.spectra or [])]
    if not spectra:
        st.info(t("No usable data were found in the uploaded files."))
        return
    ignore_blank = st.checkbox(t("Ignore blank sheets"), True, key="nano-ignoreblank")
    if ignore_blank:
        spectra = [spectrum for spectrum in spectra if not spectrum.metadata.get("blank")]
    spectra = _spectrum_selector(spectra, "nano")
    colors = _series_colors([(item.uid, item.name) for item in spectra if item.visible], "nano")
    options = _plot_options("nano", {"x_label": "Wavelength", "x_unit": "nm", "y_label": "Absorbance", "y_unit": "a.u."})
    _show_figure(spectra_figure(spectra, options, colors=colors), "NanoDrop")


def nmr_page() -> None:
    uploaded = st.file_uploader(t("Files"), type=["zip"], accept_multiple_files=True, key="nmr-files")
    results, errors = _parse_many(uploaded, "ssNMR")
    _errors(errors)
    spectra = [spectrum for result in results for spectrum in (result.spectra or [])]
    skipped = [message for result in results for message in (result.skipped or [])]
    if skipped:
        with st.expander(t("Skipped experiments")):
            st.write("\n".join(f"- {message}" for message in skipped))
    if not spectra:
        st.info(t("No usable data were found in the uploaded files."))
        return
    spectra = _spectrum_selector(spectra, "nmr")
    with st.expander(t("NMR processing"), expanded=True):
        columns = st.columns(3)
        phase_mode = columns[0].selectbox(t("Phase mode"), ["Automatic phase", "Saved TopSpin phase", "Magnitude (phase independent)", "No phase correction"], key="nmr-phase")
        line_broadening = columns[1].number_input(t("Extra line broadening (Hz)"), 0.0, 1000.0, 0.0, 1.0, key="nmr-lb")
        baseline = columns[2].checkbox(t("Linear baseline"), False, key="nmr-baseline")
        columns = st.columns(3)
        phase0 = columns[0].number_input(t("Zero-order phase (°)"), -360.0, 360.0, 0.0, 1.0, key="nmr-p0")
        phase1 = columns[1].number_input(t("First-order phase (°)"), -720.0, 720.0, 0.0, 1.0, key="nmr-p1")
        normalize_values = columns[2].checkbox(t("Normalize maximum"), True, key="nmr-normalize")
    processed = [_process_nmr_cached(
        item, phase_mode=phase_mode, extra_line_broadening=line_broadening,
        phase0=phase0, phase1=phase1, baseline=baseline, normalize_values=normalize_values,
    ) for item in spectra]
    colors = _series_colors([(item.uid, item.name) for item in processed if item.visible], "nmr")
    options = _plot_options("nmr", {"x_label": "Chemical shift", "x_unit": "ppm", "y_label": "Intensity", "y_unit": "a.u.", "reverse_x": True})
    _show_figure(spectra_figure(processed, options, colors=colors), "ssNMR")


def zeta_page() -> None:
    uploaded = st.file_uploader(t("Files"), type=["xlsx", "xlsm"], accept_multiple_files=True, key="zeta-files")
    results, errors = _parse_many(uploaded, "ZetaSizer")
    _errors(errors)
    measurements = [measurement for result in results for measurement in (result.measurements or [])]
    if not measurements:
        st.info(t("No usable data were found in the uploaded files."))
        return
    all_particles = sorted({item.particle_name for item in measurements}, key=str.casefold)
    particles = st.multiselect(t("Particles"), all_particles, default=all_particles, key="zeta-particles")
    colors = _series_colors([(name, name) for name in particles], "zeta")
    controls = st.columns(3)
    show_replicates = controls[0].checkbox(t("Show replicates"), True, key="zeta-reps")
    show_mean = controls[1].checkbox(t("Show mean curve"), True, key="zeta-mean")
    mark_maximum = controls[2].checkbox(t("Mark distribution maximum"), len(particles) == 1, key="zeta-max")
    left, right = st.columns(2)
    with left:
        st.subheader(t("DLS distributions"))
        dls_options = _plot_options("zeta-dls", {"x_label": "Particle diameter", "x_unit": "nm", "y_label": "Intensity", "y_unit": "%"})
        dls_figure = zetasizer_curve_figure(measurements, "DLS", particles, dls_options, colors=colors, show_replicates=show_replicates, show_mean=show_mean, mark_maximum=mark_maximum)
        _show_figure(dls_figure, "ZetaSizer_DLS")
    with right:
        st.subheader(t("Zeta distributions"))
        zeta_options = _plot_options("zeta-zeta", {"x_label": "Zeta potential", "x_unit": "mV", "y_label": "Total counts", "y_unit": "kcps"})
        zeta_figure = zetasizer_curve_figure(measurements, "Zeta", particles, zeta_options, colors=colors, show_replicates=show_replicates, show_mean=show_mean, mark_maximum=mark_maximum)
        _show_figure(zeta_figure, "ZetaSizer_Zeta")
    st.caption(t("The lower charts summarize each raw distribution's maximum. They are not OCR-derived Z-average or mean zeta-potential values."))
    left, right = st.columns(2)
    with left:
        st.subheader(t("DLS peak comparison"))
        rows = [row for row in zetasizer_peak_summary(measurements, "DLS") if row["Particle"] in particles]
        summary_options = _plot_options("zeta-dls-summary", {"x_label": "Batch", "x_unit": "", "y_label": "DLS intensity peak", "y_unit": "nm", "legend": False})
        _show_figure(zetasizer_summary_figure(rows, summary_options, colors=colors), "ZetaSizer_DLS_peaks")
        st.dataframe([{key: value for key, value in row.items() if key != "Values"} for row in rows], width="stretch")
    with right:
        st.subheader(t("Zeta peak comparison"))
        rows = [row for row in zetasizer_peak_summary(measurements, "Zeta") if row["Particle"] in particles]
        summary_options = _plot_options("zeta-zeta-summary", {"x_label": "Batch", "x_unit": "", "y_label": "Maximum-count zeta potential", "y_unit": "mV", "legend": False})
        _show_figure(zetasizer_summary_figure(rows, summary_options, colors=colors), "ZetaSizer_Zeta_peaks")
        st.dataframe([{key: value for key, value in row.items() if key != "Values"} for row in rows], width="stretch")


def _tem_csv(analyses: list[TEMImageAnalysis]) -> bytes:
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(["batch", "source", "magnification", "status", "particle_index", "diameter_nm"])
    for analysis in analyses:
        for index, diameter in enumerate(analysis.diameters_nm, start=1):
            writer.writerow([analysis.batch_name, analysis.source_name, analysis.magnification or "", analysis.status, index, diameter])
    return stream.getvalue().encode("utf-8-sig")


def tem_page() -> None:
    with st.expander(t("Analysis parameters"), expanded=True):
        columns = st.columns(4)
        minimum = columns[0].number_input(t("Minimum diameter (nm)"), 1.0, 100000.0, 50.0, key="tem-min")
        maximum = columns[1].number_input(t("Maximum diameter (nm)"), 2.0, 100000.0, 1000.0, key="tem-max")
        separation = columns[2].number_input(t("Minimum center distance (nm)"), 1.0, 100000.0, 75.0, key="tem-separation")
        threshold = columns[3].number_input(t("Threshold factor"), 0.5, 1.5, 1.0, 0.05, key="tem-threshold")
        columns = st.columns(2)
        exclude_border = columns[0].checkbox(t("Exclude border particles"), True, key="tem-border")
        force_blank = columns[1].checkbox(t("Force analysis of blank fields"), False, key="tem-blank")
    tem_values = (minimum, maximum, separation, threshold, exclude_border, 0.84, force_blank)
    uploaded = st.file_uploader(t("Files"), type=["tif", "tiff"], accept_multiple_files=True, key="tem-files")
    results, errors = _parse_many(uploaded, "TEM", tem_values)
    _errors(errors)
    analyses = [result.tem for result in results if result.tem is not None]
    if not analyses:
        st.info(t("No usable data were found in the uploaded files."))
        return
    st.subheader(t("TEM review"))
    payload_by_name = {item.name: item.getvalue() for item in uploaded}
    for analysis in analyses:
        with st.expander(f"{analysis.source_name} · {analysis.status} · n={analysis.particle_count}", expanded=len(analyses) == 1):
            left, right = st.columns([2, 1])
            with left:
                st.pyplot(tem_overlay_figure(payload_by_name[analysis.source_name], analysis), width="stretch")
            with right:
                st.json({
                    "batch": analysis.batch_name,
                    "magnification": analysis.magnification,
                    "status": analysis.status,
                    "included": analysis.included,
                    "particles": analysis.particle_count,
                    "scale_nm": analysis.calibration.scale_nm,
                    "nm_per_pixel": analysis.calibration.nm_per_pixel,
                    "calibration_confidence": analysis.calibration.confidence,
                    "blank_score": analysis.blank.score,
                    "warning": analysis.warning,
                })
    grouped: dict[str, list[TEMImageAnalysis]] = {}
    for analysis in analyses:
        grouped.setdefault(analysis.batch_name, []).append(analysis)
    summaries = []
    for batch, records in sorted(grouped.items()):
        diameters = np.asarray([value for record in records if record.included and record.status == "analyzed" for value in record.diameters_nm], dtype=float)
        summaries.append({
            "Batch": batch, "Images": len(records), "Included images": sum(record.included and record.status == "analyzed" for record in records),
            "Blank images": sum(record.status == "blank" for record in records), "Particles": int(diameters.size),
            "Mean (nm)": float(np.mean(diameters)) if diameters.size else None,
            "Median (nm)": float(np.median(diameters)) if diameters.size else None,
            "SD (nm)": float(np.std(diameters, ddof=1)) if diameters.size > 1 else 0.0 if diameters.size else None,
        })
    st.subheader(t("Batch summary"))
    st.dataframe(summaries, width="stretch")
    st.subheader(t("Particle-size distributions"))
    _show_figure(tem_distribution_figure(analyses), "TEM_distribution")
    st.download_button(t("Download particle CSV"), _tem_csv(analyses), "LabPlotter_TEM_particles.csv", "text/csv")


def custom_page() -> None:
    st.write(t("Upload one spreadsheet and describe its X/Y columns."))
    uploaded = st.file_uploader(t("Files"), type=["csv", "tsv", "txt", "xlsx", "xlsm", "xml"], accept_multiple_files=False, key="custom-file")
    columns = st.columns(5)
    sheet = columns[0].text_input(t("Sheet name (optional)"), key="custom-sheet")
    x_column = columns[1].text_input(t("X column"), "A", key="custom-x")
    y_text = columns[2].text_input(t("Y columns (comma separated)"), "B", key="custom-y")
    start = columns[3].number_input(t("Data start row"), 1, 100000, 2, key="custom-start")
    header = columns[4].number_input(t("Header row"), 1, 100000, 1, key="custom-header")
    if not uploaded:
        return
    profile = {
        "name": "Web custom mapping", "sheet": sheet or None, "x_column": x_column,
        "y_columns": tuple(value.strip() for value in y_text.split(",") if value.strip()),
        "data_start_row": int(start), "header_row": int(header),
    }
    try:
        spectra = _generic_cached(uploaded.name, uploaded.getvalue(), tuple(profile.items()))
    except Exception as exc:
        st.error(f"{t('File error')}: {exc}")
        return
    spectra = _spectrum_selector(spectra, "custom")
    colors = _series_colors([(item.uid, item.name) for item in spectra if item.visible], "custom")
    options = _plot_options("custom", {"x_label": "X", "x_unit": "", "y_label": "Y", "y_unit": ""})
    _show_figure(spectra_figure(spectra, options, colors=colors), "Custom")


def main() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stTabs"] button {font-size: 1.02rem; font-weight: 650; padding-left: 1.25rem; padding-right: 1.25rem;}
        div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {height: 4px;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    left, right = st.columns([5, 1])
    with left:
        st.title(f"LabPlotter Web {__version__}")
        st.caption(t("Scientific data plotting in your browser"))
    with right:
        st.selectbox(t("Language"), ["English", "한국어"], key="language")
    with st.expander(t("About"), expanded=False):
        st.write(t("The web edition reuses the same parsing, processing, NMR, ZetaSizer, and TEM analysis core as the Windows edition."))
        st.info(t("Uploaded files are processed only for this browser session. Download your results before closing the page."))
        st.warning(t("Persistent local libraries, Windows clipboard export, editable OCR review, and .labpatch updates remain desktop-only in 0.8.1."))
        st.markdown(f"**{t('Contact and feedback')}**  \n{t('Jun Min Moon · moonkeving@gmail.com')}")
    tabs = st.tabs(["FTIR", "NanoDrop UV–Vis", "ssNMR", "ZetaSizer", "TEM", t("Custom format")])
    pages = (ftir_page, nanodrop_page, nmr_page, zeta_page, tem_page, custom_page)
    for tab, page in zip(tabs, pages):
        with tab:
            page()


if __name__ == "__main__":
    main()
