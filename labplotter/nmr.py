from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from scipy.optimize import minimize

from .i18n import tr
from .models import Spectrum
from .processing import linear_endpoints_baseline


MAX_ARCHIVE_ENTRIES = 10_000
MAX_FID_BYTES = 512 * 1024 * 1024


def parse_jcamp_parameters(data: bytes) -> dict[str, Any]:
    """Read scalar Bruker JCAMP-DX parameters needed for 1D processing."""
    output: dict[str, Any] = {}
    text = data.decode("latin-1", errors="replace")
    for line in text.splitlines():
        match = re.match(r"##\$([^=]+)=\s*(.*)", line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2).strip()
        if raw.startswith("("):
            output[key] = raw
            continue
        if raw.startswith("<") and raw.endswith(">"):
            output[key] = raw[1:-1].strip()
            continue
        try:
            value = float(raw) if any(char in raw for char in ".eE") else int(raw)
        except ValueError:
            value = raw
        output[key] = value
    return output


def _number(parameters: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(parameters.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _read_complex_fid(data: bytes, acquisition: dict[str, Any]) -> np.ndarray:
    data_type = int(_number(acquisition, "DTYPA", 0))
    byte_order = "<" if int(_number(acquisition, "BYTORDA", 0)) == 0 else ">"
    if data_type == 0:
        dtype = np.dtype(byte_order + "i4")
    elif data_type == 2:
        dtype = np.dtype(byte_order + "f8")
    else:
        raise ValueError(tr("Unsupported Bruker acquisition data type: {type}", type=data_type))
    count = min(int(_number(acquisition, "TD", len(data) // dtype.itemsize)), len(data) // dtype.itemsize)
    count -= count % 2
    if count < 8:
        raise ValueError(tr("The Bruker FID does not contain enough complex points."))
    raw = np.frombuffer(data, dtype=dtype, count=count).astype(float)
    scale = 2.0 ** int(_number(acquisition, "NC", 0))
    return (raw[0::2] + 1j * raw[1::2]) * scale


def _remove_group_delay(fid: np.ndarray, group_delay: float) -> np.ndarray:
    delay = max(0.0, min(float(group_delay), max(0.0, len(fid) - 8.0)))
    if delay <= 0:
        return fid.copy()
    frequencies = np.fft.fftfreq(len(fid))
    advanced = np.fft.ifft(np.fft.fft(fid) * np.exp(2j * np.pi * frequencies * delay))
    valid = max(8, len(fid) - int(np.ceil(delay)) - 2)
    return advanced[:valid]


def _automatic_phase(
    spectrum: np.ndarray,
    fraction: np.ndarray,
    ppm: np.ndarray,
    nucleus: str,
    initial: tuple[float, float],
) -> tuple[float, float]:
    if nucleus == "13C":
        region = (ppm >= -50.0) & (ppm <= 300.0)
    elif nucleus == "1H":
        region = (ppm >= -20.0) & (ppm <= 50.0)
    else:
        lower, upper = np.quantile(ppm, (0.1, 0.9))
        region = (ppm >= lower) & (ppm <= upper)
    indices = np.flatnonzero(region)
    if len(indices) < 32:
        indices = np.arange(len(ppm))
    stride = max(1, len(indices) // 4096)
    indices = indices[::stride]
    selected, selected_fraction = spectrum[indices], fraction[indices]

    def objective(phase: np.ndarray) -> float:
        values = np.real(selected * np.exp(1j * np.deg2rad(phase[0] + phase[1] * (selected_fraction - 0.5))))
        derivative = np.abs(np.diff(values))
        probabilities = derivative / (float(np.sum(derivative)) + 1e-12)
        entropy = -float(np.sum(probabilities * np.log(probabilities + 1e-12)))
        negative = np.minimum(values, 0.0)
        negative_penalty = float(np.sum(negative * negative)) / (float(np.sum(values * values)) + 1e-12)
        return entropy + 20.0 * negative_penalty

    starts = (initial, (0.0, 0.0), (180.0, 0.0))
    results = [
        minimize(objective, start, method="Nelder-Mead", options={"maxiter": 600, "xatol": 0.05, "fatol": 1e-6})
        for start in starts
    ]
    best = min(results, key=lambda result: float(result.fun))
    return float(best.x[0]), float(best.x[1])


def process_bruker_1d(
    raw_fid: np.ndarray,
    acquisition: dict[str, Any],
    processing: dict[str, Any],
    *,
    use_saved_window: bool = True,
    use_saved_phase: bool = True,
    phase_mode: str | None = "Automatic phase",
    extra_line_broadening: float = 0.0,
    phase0: float = 0.0,
    phase1: float = 0.0,
    baseline: bool = False,
    normalize: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Process a Bruker 1D raw FID using the parameters stored in its ZIP export."""
    fid = _remove_group_delay(np.asarray(raw_fid, dtype=complex), _number(acquisition, "GRPDLY", 0.0))
    spectral_width_hz = max(1e-12, _number(acquisition, "SW_h", _number(processing, "SW_p", 1.0)))
    saved_lb = _number(processing, "LB", 0.0) if use_saved_window and int(_number(processing, "WDW", 0)) == 1 else 0.0
    line_broadening = max(0.0, saved_lb + float(extra_line_broadening))
    if line_broadening:
        time_axis = np.arange(len(fid), dtype=float) / spectral_width_hz
        fid = fid * np.exp(-np.pi * line_broadening * time_axis)

    size = max(len(fid), int(_number(processing, "SI", 2 ** int(np.ceil(np.log2(len(fid)))))))
    spectrum = np.fft.fftshift(np.fft.ifft(fid, size)) * size
    fraction = np.arange(size, dtype=float) / max(1, size - 1)

    frequency_mhz = _number(processing, "SF", _number(acquisition, "SFO1", 1.0))
    width_hz = _number(processing, "SW_p", spectral_width_hz)
    if "OFFSET" in processing and frequency_mhz:
        high_ppm = _number(processing, "OFFSET", 0.0)
    else:
        center_ppm = _number(acquisition, "O1", 0.0) / max(_number(acquisition, "SFO1", frequency_mhz), 1e-12)
        high_ppm = center_ppm + width_hz / max(frequency_mhz, 1e-12) / 2.0
    ppm = high_ppm - fraction * width_hz / max(frequency_mhz, 1e-12)

    saved_p0 = -_number(processing, "PHC0", 0.0) if use_saved_phase else 0.0
    saved_p1 = -_number(processing, "PHC1", 0.0) if use_saved_phase else 0.0
    mode = phase_mode or ("Saved TopSpin phase" if use_saved_phase else "No phase correction")
    nucleus = str(processing.get("AXNUC") or acquisition.get("NUC1") or "").strip("<>")
    if mode == "Magnitude (phase independent)":
        values = np.abs(spectrum)
    else:
        if mode == "Automatic phase":
            base_p0, base_p1 = _automatic_phase(spectrum, fraction, ppm, nucleus, (saved_p0, saved_p1))
        elif mode == "Saved TopSpin phase":
            base_p0, base_p1 = saved_p0, saved_p1
        else:
            base_p0, base_p1 = 0.0, 0.0
        phase_degrees = base_p0 + float(phase0) + (base_p1 + float(phase1)) * (fraction - 0.5)
        values = np.real(spectrum * np.exp(1j * np.deg2rad(phase_degrees)))

    order = np.argsort(ppm)
    ppm, values = ppm[order], values[order]
    if baseline:
        values = values - linear_endpoints_baseline(ppm, values, edge_fraction=0.05)
    if normalize:
        if nucleus == "13C":
            normalization_region = (ppm >= -50.0) & (ppm <= 300.0)
        elif nucleus == "1H":
            normalization_region = (ppm >= -20.0) & (ppm <= 50.0)
        else:
            normalization_region = np.ones(len(ppm), dtype=bool)
        maximum = float(np.nanmax(np.abs(values[normalization_region])))
        if maximum:
            values = values / maximum
    return ppm, values


def parse_bruker_zip(path: str | Path) -> tuple[list[Spectrum], list[str]]:
    """Import supported 1D Bruker FIDs directly from a TopSpin ZIP archive."""
    path = Path(path)
    spectra: list[Spectrum] = []
    skipped: list[str] = []
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(tr("This is not a readable Bruker ZIP archive: {error}", error=exc)) from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise ValueError(tr("The ZIP archive contains too many entries."))
        names = {info.filename for info in infos}
        acquisition_files = sorted(
            (name for name in names if PurePosixPath(name).name == "acqus"),
            key=lambda value: tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in PurePosixPath(value).parts),
        )
        if not acquisition_files:
            raise ValueError(tr("No Bruker acqus files were found in the ZIP archive."))
        for acqus_name in acquisition_files:
            base = acqus_name[: -len("acqus")]
            experiment = PurePosixPath(base.rstrip("/")).name
            fid_name, ser_name = base + "fid", base + "ser"
            if fid_name not in names:
                if ser_name in names:
                    skipped.append(tr("Experiment {experiment}: pseudo-2D/2D ser data", experiment=experiment))
                continue
            info = archive.getinfo(fid_name)
            if info.file_size > MAX_FID_BYTES:
                skipped.append(tr("Experiment {experiment}: FID is larger than the safety limit", experiment=experiment))
                continue
            acquisition = parse_jcamp_parameters(archive.read(acqus_name))
            procs_candidates = sorted(name for name in names if name.startswith(base + "pdata/") and PurePosixPath(name).name == "procs")
            processing = parse_jcamp_parameters(archive.read(procs_candidates[0])) if procs_candidates else {}
            try:
                raw_fid = _read_complex_fid(archive.read(fid_name), acquisition)
                ppm, values = process_bruker_1d(raw_fid, acquisition, processing)
            except Exception as exc:
                skipped.append(tr("Experiment {experiment}: {error}", experiment=experiment, error=exc))
                continue
            title_name = procs_candidates[0].rsplit("/", 1)[0] + "/title" if procs_candidates else ""
            title = archive.read(title_name).decode("utf-8", errors="replace").strip() if title_name in names else ""
            nucleus = str(processing.get("AXNUC") or acquisition.get("NUC1") or "Unknown").strip("<>")
            pulse_program = str(acquisition.get("PULPROG") or "unknown").strip("<>")
            mas_hz = _number(acquisition, "MASR", 0.0)
            mas_text = f" · {mas_hz / 1000:g} kHz MAS" if mas_hz else ""
            name = f"{path.stem} · exp {experiment} · {nucleus} {pulse_program}{mas_text}"
            metadata = {
                "kind": "ssnmr",
                "experiment": experiment,
                "nucleus": nucleus,
                "pulse_program": pulse_program,
                "title": title,
                "mas_hz": mas_hz,
                "ns": int(_number(acquisition, "NS", 0)),
                "raw_fid": raw_fid,
                "acquisition": acquisition,
                "processing": processing,
            }
            spectra.append(Spectrum(name, ppm, values, str(path), metadata=metadata).clean())
        if not spectra:
            detail = "; ".join(skipped) if skipped else tr("No supported one-dimensional FIDs were found.")
            raise ValueError(detail)
        carbon_present = any(spectrum.metadata.get("nucleus") == "13C" for spectrum in spectra)
        if carbon_present:
            for spectrum in spectra:
                spectrum.visible = spectrum.metadata.get("nucleus") == "13C"
    return spectra, skipped
