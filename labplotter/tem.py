from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage as ndi

from .config import tem_database_path, tem_images_dir


TIFF_SUFFIXES = {".tif", ".tiff"}
_MAGNIFICATION_PATTERN = re.compile(r"(?i)(?:^|[_\-\s])(\d+(?:\.\d+)?)\s*[x×](?:[_\-\s]|$)")
_FRAME_SUFFIX_PATTERN = re.compile(
    r"(?i)(?:[_\-\s])\d+(?:\.\d+)?\s*[x×](?:[_\-\s])\d+(?:\(\d+\))?$"
)
_TRAILING_FRAME_PATTERN = re.compile(r"(?:[_\-\s])\d+(?:\(\d+\))?$")
_NICE_SCALE_NM = np.asarray((10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000), dtype=float)


@dataclass
class TEMAnalysisParameters:
    minimum_diameter_nm: float = 50.0
    maximum_diameter_nm: float = 1000.0
    minimum_center_distance_nm: float = 75.0
    threshold_factor: float = 1.0
    exclude_border_particles: bool = True
    annotation_crop_fraction: float = 0.84
    force_analyze_blank: bool = False

    def normalized(self) -> "TEMAnalysisParameters":
        minimum = max(1.0, float(self.minimum_diameter_nm))
        maximum = max(minimum + 1.0, float(self.maximum_diameter_nm))
        separation = max(1.0, float(self.minimum_center_distance_nm))
        factor = min(1.5, max(0.5, float(self.threshold_factor)))
        crop = min(0.95, max(0.50, float(self.annotation_crop_fraction)))
        return TEMAnalysisParameters(
            minimum,
            maximum,
            separation,
            factor,
            bool(self.exclude_border_particles),
            crop,
            bool(self.force_analyze_blank),
        )


@dataclass
class TEMFileIdentity:
    batch_name: str
    magnification: float | None
    frame: str


@dataclass
class ScaleCalibration:
    scale_nm: float | None
    bar_pixels: float | None
    nm_per_pixel: float | None
    bar_y: int | None
    source: str
    confidence: float


@dataclass
class BlankMetrics:
    is_blank: bool
    score: float
    mean: float
    standard_deviation: float
    entropy: float
    edge_density: float


@dataclass
class TEMImageAnalysis:
    source_path: str
    source_name: str
    checksum: str
    batch_name: str
    magnification: float | None
    frame: str
    width: int
    height: int
    status: str
    included: bool
    calibration: ScaleCalibration
    blank: BlankMetrics
    parameters: TEMAnalysisParameters
    diameters_nm: list[float] = field(default_factory=list)
    centers_px: list[tuple[float, float, float]] = field(default_factory=list)
    threshold: float | None = None
    foreground_fraction: float | None = None
    analysis_bottom: int | None = None
    warning: str = ""

    @property
    def particle_count(self) -> int:
        return len(self.diameters_nm)


def parse_tem_filename(path: str | Path) -> TEMFileIdentity:
    stem = Path(path).stem
    magnification_match = _MAGNIFICATION_PATTERN.search(stem)
    magnification = float(magnification_match.group(1)) if magnification_match else None
    frame_match = _TRAILING_FRAME_PATTERN.search(stem)
    frame = frame_match.group(0).lstrip("_- ") if frame_match else ""
    batch = _FRAME_SUFFIX_PATTERN.sub("", stem)
    if batch == stem and magnification_match:
        batch = stem[: magnification_match.start()].rstrip("_- ")
    if not batch:
        batch = stem
    return TEMFileIdentity(batch, magnification, frame)


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_tem_grayscale(path: str | Path) -> np.ndarray:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode in {"I", "I;16", "I;16B", "I;16L", "F"}:
            values = np.asarray(image, dtype=float)
            finite = values[np.isfinite(values)]
            if not finite.size:
                return np.zeros(values.shape, dtype=np.uint8)
            low, high = np.percentile(finite, (0.1, 99.9))
            if high <= low:
                return np.zeros(values.shape, dtype=np.uint8)
            return np.clip((values - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)
        return np.asarray(image.convert("L"), dtype=np.uint8)


def _longest_true_run(values: np.ndarray) -> tuple[int, int]:
    transitions = np.diff(np.pad(np.asarray(values, dtype=np.int8), (1, 1)))
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    if not len(starts):
        return 0, 0
    lengths = ends - starts
    best = int(np.argmax(lengths))
    return int(starts[best]), int(lengths[best])


def detect_scale_bar(image: np.ndarray, magnification: float | None = None) -> ScaleCalibration:
    """Find the bright horizontal scale bar and infer its printed value.

    Hitachi H-D2300/Gatan TIFF exports used by the initial TEM workflow do not
    store a usable pixel calibration in their TIFF tags. Their filename
    magnification and printed bar are therefore combined: the detected bar
    length is converted with the instrument's approximately 100,000/mag
    nm-per-pixel relationship and snapped to the nearest conventional scale
    label. Every inferred value remains editable in the review UI.
    """
    height, width = image.shape
    bottom = image[int(height * 0.62) :, : int(width * 0.72)]
    if not bottom.size:
        return ScaleCalibration(None, None, None, None, "not detected", 0.0)
    cutoff = max(230, int(image.max()) - 3)
    best_length, best_x, best_y = 0, 0, 0
    for local_y, row in enumerate(bottom >= cutoff):
        start, length = _longest_true_run(row)
        if length > best_length:
            best_length, best_x, best_y = length, start, local_y + int(height * 0.62)
    if best_length < max(18, int(width * 0.025)) or best_length > int(width * 0.80):
        return ScaleCalibration(None, None, None, None, "not detected", 0.0)

    bar_pixels = float(best_length)
    if magnification and magnification > 0:
        expected_nm_per_pixel = 100000.0 / float(magnification)
        estimated_label = bar_pixels * expected_nm_per_pixel
        distance = np.abs(np.log(_NICE_SCALE_NM / max(estimated_label, 1e-9)))
        scale_nm = float(_NICE_SCALE_NM[int(np.argmin(distance))])
        nm_per_pixel = scale_nm / bar_pixels
        relative_error = abs(nm_per_pixel - expected_nm_per_pixel) / expected_nm_per_pixel
        confidence = max(0.0, 1.0 - relative_error / 0.20)
        return ScaleCalibration(
            scale_nm,
            bar_pixels,
            nm_per_pixel,
            int(best_y),
            "scale bar + filename magnification",
            float(confidence),
        )
    return ScaleCalibration(None, bar_pixels, None, int(best_y), "scale bar; value required", 0.35)


def blank_metrics(image: np.ndarray, crop_fraction: float = 0.84) -> BlankMetrics:
    crop = np.asarray(image[: max(8, int(image.shape[0] * crop_fraction))], dtype=np.uint8)
    mean = float(np.mean(crop))
    deviation = float(np.std(crop))
    counts = np.bincount(crop.ravel(), minlength=256).astype(float)
    probability = counts[counts > 0] / max(1.0, counts.sum())
    entropy = float(-np.sum(probability * np.log2(probability)) / 8.0)
    gradient_x = ndi.sobel(crop.astype(float), axis=1, mode="reflect")
    gradient_y = ndi.sobel(crop.astype(float), axis=0, mode="reflect")
    gradient = np.hypot(gradient_x, gradient_y)
    edge_density = float(np.mean(gradient > 20.0))
    information = min(1.0, deviation / 35.0) * 0.45 + min(1.0, entropy / 0.55) * 0.45 + min(1.0, edge_density / 0.12) * 0.10
    score = float(np.clip(1.0 - information, 0.0, 1.0))
    is_blank = bool((deviation < 8.0 and entropy < 0.15) or (mean < 8.0 and edge_density < 0.01))
    return BlankMetrics(is_blank, score, mean, deviation, entropy, edge_density)


def otsu_threshold(image: np.ndarray) -> float:
    values = np.clip(np.asarray(image, dtype=np.uint8), 0, 255)
    histogram = np.bincount(values.ravel(), minlength=256).astype(float)
    probability = histogram / max(1.0, histogram.sum())
    weight = np.cumsum(probability)
    mean = np.cumsum(probability * np.arange(256))
    total_mean = mean[-1]
    denominator = weight * (1.0 - weight)
    variance = (total_mean * weight - mean) ** 2 / np.maximum(denominator, 1e-12)
    variance[(weight <= 0) | (weight >= 1)] = -1.0
    return float(np.argmax(variance))


def _remove_small_components(mask: np.ndarray, minimum_pixels: int) -> np.ndarray:
    labels, count = ndi.label(mask)
    if not count:
        return np.zeros_like(mask, dtype=bool)
    sizes = np.bincount(labels.ravel())
    keep = sizes >= max(2, int(minimum_pixels))
    keep[0] = False
    return keep[labels]


def _particle_centers_and_diameters(
    image: np.ndarray,
    nm_per_pixel: float,
    parameters: TEMAnalysisParameters,
) -> tuple[list[tuple[float, float, float]], list[float], float, float]:
    parameters = parameters.normalized()
    smoothed = ndi.gaussian_filter(image.astype(float), sigma=max(0.55, min(1.4, 1.2 / nm_per_pixel)))
    threshold = float(np.clip(otsu_threshold(smoothed.astype(np.uint8)) * parameters.threshold_factor, 1.0, 254.0))
    mask = smoothed <= threshold
    mask = ndi.binary_opening(mask, structure=np.ones((3, 3), dtype=bool), iterations=1)
    mask = ndi.binary_closing(mask, structure=np.ones((3, 3), dtype=bool), iterations=1)
    minimum_radius_px = parameters.minimum_diameter_nm / (2.0 * nm_per_pixel)
    minimum_area = max(4, int(math.pi * max(1.0, minimum_radius_px * 0.35) ** 2))
    mask = _remove_small_components(mask, minimum_area)
    foreground_fraction = float(np.mean(mask))
    if not np.any(mask):
        return [], [], threshold, foreground_fraction

    distance = ndi.distance_transform_edt(mask)
    separation_px = max(3, int(round(parameters.minimum_center_distance_nm / nm_per_pixel)))
    if separation_px % 2 == 0:
        separation_px += 1
    local_maximum = distance == ndi.maximum_filter(distance, size=separation_px, mode="constant")
    local_maximum &= distance * nm_per_pixel >= parameters.minimum_diameter_nm / 2.0
    peak_labels, peak_count = ndi.label(local_maximum)
    if not peak_count:
        return [], [], threshold, foreground_fraction

    centers = ndi.center_of_mass(distance, peak_labels, range(1, peak_count + 1))
    output_centers: list[tuple[float, float, float]] = []
    diameters: list[float] = []
    height, width = image.shape
    for y, x in centers:
        if not np.isfinite(x) or not np.isfinite(y):
            continue
        radius_px = float(distance[int(round(y)), int(round(x))])
        diameter_nm = 2.0 * radius_px * nm_per_pixel
        if not (parameters.minimum_diameter_nm <= diameter_nm <= parameters.maximum_diameter_nm):
            continue
        if parameters.exclude_border_particles and (
            x - radius_px <= 1 or y - radius_px <= 1 or x + radius_px >= width - 2 or y + radius_px >= height - 2
        ):
            continue
        output_centers.append((float(x), float(y), radius_px))
        diameters.append(float(diameter_nm))
    return output_centers, diameters, threshold, foreground_fraction


def analyze_tem_image(
    path: str | Path,
    parameters: TEMAnalysisParameters | None = None,
    *,
    batch_name: str | None = None,
    scale_nm: float | None = None,
    bar_pixels: float | None = None,
    checksum: str | None = None,
) -> TEMImageAnalysis:
    path = Path(path)
    if path.suffix.casefold() not in TIFF_SUFFIXES:
        raise ValueError(f"Unsupported TEM image: {path.suffix}")
    parameters = (parameters or TEMAnalysisParameters()).normalized()
    image = load_tem_grayscale(path)
    height, width = image.shape
    identity = parse_tem_filename(path)
    calibration = detect_scale_bar(image, identity.magnification)
    if scale_nm is not None and bar_pixels is not None and float(scale_nm) > 0 and float(bar_pixels) > 0:
        calibration = ScaleCalibration(
            float(scale_nm),
            float(bar_pixels),
            float(scale_nm) / float(bar_pixels),
            calibration.bar_y,
            "manual",
            1.0,
        )
    blank = blank_metrics(image, parameters.annotation_crop_fraction)
    common = {
        "source_path": str(path.resolve()),
        "source_name": path.name,
        "checksum": checksum or sha256_file(path),
        "batch_name": str(batch_name or identity.batch_name),
        "magnification": identity.magnification,
        "frame": identity.frame,
        "width": int(width),
        "height": int(height),
        "calibration": calibration,
        "blank": blank,
        "parameters": parameters,
    }
    if blank.is_blank and not parameters.force_analyze_blank:
        return TEMImageAnalysis(**common, status="blank", included=False, warning="Blank field automatically skipped.")
    if calibration.nm_per_pixel is None:
        return TEMImageAnalysis(
            **common,
            status="needs_scale",
            included=False,
            warning="Enter the printed scale value and detected bar length, then reanalyze.",
        )

    analysis_bottom = max(32, int(height * parameters.annotation_crop_fraction))
    if calibration.bar_y is not None:
        analysis_bottom = min(analysis_bottom, max(32, int(calibration.bar_y) - 45))
    analysis_image = image[:analysis_bottom]
    centers, diameters, threshold, foreground = _particle_centers_and_diameters(
        analysis_image,
        calibration.nm_per_pixel,
        parameters,
    )
    warning = ""
    if foreground < 0.02 or foreground > 0.90:
        warning = "Segmentation coverage is unusual; review the overlay and adjust the threshold."
    elif foreground > 0.65:
        warning = "Particle overlap is high; merged regions can overestimate diameter. Review the overlay and consider a higher magnification or stricter maximum diameter."
    elif len(diameters) < 3:
        warning = "Few particles were detected; review the overlay and analysis settings."
    return TEMImageAnalysis(
        **common,
        status="analyzed",
        included=True,
        diameters_nm=diameters,
        centers_px=centers,
        threshold=threshold,
        foreground_fraction=foreground,
        analysis_bottom=analysis_bottom,
        warning=warning,
    )


class TEMLibrary:
    SCHEMA_GENERATION = 1

    def __init__(self, path: str | Path | None = None, image_directory: str | Path | None = None):
        self.path = Path(path) if path else tem_database_path()
        self.image_directory = Path(image_directory) if image_directory else tem_images_dir()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.image_directory.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self.connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tem_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checksum TEXT NOT NULL UNIQUE,
                    batch_name TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    magnification REAL,
                    frame TEXT NOT NULL DEFAULT '',
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    included INTEGER NOT NULL DEFAULT 1,
                    scale_nm REAL,
                    bar_pixels REAL,
                    nm_per_pixel REAL,
                    calibration_source TEXT NOT NULL DEFAULT '',
                    calibration_confidence REAL NOT NULL DEFAULT 0,
                    blank_json TEXT NOT NULL DEFAULT '{}',
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    diameters_json TEXT NOT NULL DEFAULT '[]',
                    centers_json TEXT NOT NULL DEFAULT '[]',
                    threshold REAL,
                    foreground_fraction REAL,
                    analysis_bottom INTEGER,
                    warning TEXT NOT NULL DEFAULT '',
                    imported_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tem_batch ON tem_images(batch_name);
                """
            )
            connection.execute(f"PRAGMA user_version={self.SCHEMA_GENERATION}")
            connection.commit()

    def checksum_exists(self, checksum: str) -> dict[str, Any] | None:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM tem_images WHERE checksum=?", (str(checksum),)).fetchone()
        return self._decode(row) if row else None

    def store(self, analysis: TEMImageAnalysis) -> int:
        source = Path(analysis.source_path)
        suffix = source.suffix.casefold() if source.suffix.casefold() in TIFF_SUFFIXES else ".tif"
        stored = self.image_directory / f"{analysis.checksum}{suffix}"
        if not stored.exists():
            shutil.copy2(source, stored)
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO tem_images(
                    checksum,batch_name,source_name,stored_path,magnification,frame,width,height,
                    status,included,scale_nm,bar_pixels,nm_per_pixel,calibration_source,
                    calibration_confidence,blank_json,parameters_json,diameters_json,centers_json,
                    threshold,foreground_fraction,analysis_bottom,warning,imported_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(checksum) DO UPDATE SET
                    batch_name=excluded.batch_name,status=excluded.status,included=excluded.included,
                    scale_nm=excluded.scale_nm,bar_pixels=excluded.bar_pixels,nm_per_pixel=excluded.nm_per_pixel,
                    calibration_source=excluded.calibration_source,
                    calibration_confidence=excluded.calibration_confidence,
                    blank_json=excluded.blank_json,parameters_json=excluded.parameters_json,
                    diameters_json=excluded.diameters_json,centers_json=excluded.centers_json,
                    threshold=excluded.threshold,foreground_fraction=excluded.foreground_fraction,
                    analysis_bottom=excluded.analysis_bottom,warning=excluded.warning,updated_at=excluded.updated_at
                """,
                (
                    analysis.checksum,
                    analysis.batch_name,
                    analysis.source_name,
                    str(stored),
                    analysis.magnification,
                    analysis.frame,
                    analysis.width,
                    analysis.height,
                    analysis.status,
                    int(analysis.included),
                    analysis.calibration.scale_nm,
                    analysis.calibration.bar_pixels,
                    analysis.calibration.nm_per_pixel,
                    analysis.calibration.source,
                    analysis.calibration.confidence,
                    json.dumps(asdict(analysis.blank)),
                    json.dumps(asdict(analysis.parameters)),
                    json.dumps(analysis.diameters_nm),
                    json.dumps(analysis.centers_px),
                    analysis.threshold,
                    analysis.foreground_fraction,
                    analysis.analysis_bottom,
                    analysis.warning,
                    now,
                    now,
                ),
            )
            connection.commit()
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = connection.execute("SELECT id FROM tem_images WHERE checksum=?", (analysis.checksum,)).fetchone()
            return int(row[0])

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        item = dict(row)
        item["included"] = bool(item["included"])
        item["blank"] = BlankMetrics(**json.loads(item.pop("blank_json")))
        item["parameters"] = TEMAnalysisParameters(**json.loads(item.pop("parameters_json")))
        item["diameters_nm"] = [float(value) for value in json.loads(item.pop("diameters_json"))]
        item["centers_px"] = [tuple(float(value) for value in center) for center in json.loads(item.pop("centers_json"))]
        item["particle_count"] = len(item["diameters_nm"])
        return item

    def images(self, image_ids: Iterable[int] | None = None) -> list[dict[str, Any]]:
        parameters: list[Any] = []
        where = ""
        if image_ids is not None:
            identifiers = [int(value) for value in image_ids]
            if not identifiers:
                return []
            marks = ",".join("?" for _ in identifiers)
            where = f"WHERE id IN ({marks})"
            parameters.extend(identifiers)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM tem_images {where} ORDER BY batch_name COLLATE NOCASE, magnification, source_name COLLATE NOCASE",
                parameters,
            ).fetchall()
        return [self._decode(row) for row in rows]

    def batch_names(self) -> list[str]:
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT DISTINCT batch_name FROM tem_images ORDER BY batch_name COLLATE NOCASE").fetchall()
        return [str(row[0]) for row in rows]

    def batch_summary(self, batch_names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        allowed = set(str(value) for value in batch_names) if batch_names is not None else None
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in self.images():
            if allowed is not None and item["batch_name"] not in allowed:
                continue
            grouped.setdefault(item["batch_name"], []).append(item)
        output = []
        for batch, items in grouped.items():
            included = [item for item in items if item["included"] and item["status"] == "analyzed"]
            diameters = np.asarray([value for item in included for value in item["diameters_nm"]], dtype=float)
            image_means = np.asarray(
                [np.mean(item["diameters_nm"]) for item in included if item["diameters_nm"]],
                dtype=float,
            )
            output.append(
                {
                    "batch_name": batch,
                    "image_count": len(items),
                    "included_images": len(included),
                    "blank_images": sum(item["status"] == "blank" for item in items),
                    "particle_count": int(diameters.size),
                    "mean_nm": float(np.mean(diameters)) if diameters.size else None,
                    "median_nm": float(np.median(diameters)) if diameters.size else None,
                    "sd_nm": float(np.std(diameters, ddof=1)) if diameters.size > 1 else 0.0 if diameters.size else None,
                    "image_mean_nm": float(np.mean(image_means)) if image_means.size else None,
                    "image_sd_nm": float(np.std(image_means, ddof=1)) if image_means.size > 1 else 0.0 if image_means.size else None,
                }
            )
        return sorted(output, key=lambda item: item["batch_name"].casefold())

    def set_included(self, image_ids: Iterable[int], included: bool) -> int:
        identifiers = [int(value) for value in image_ids]
        if not identifiers:
            return 0
        marks = ",".join("?" for _ in identifiers)
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                f"UPDATE tem_images SET included=?, updated_at=? WHERE id IN ({marks})",
                (int(bool(included)), datetime.now(timezone.utc).isoformat(), *identifiers),
            )
            connection.commit()
            return int(cursor.rowcount)

    def rename_batch(self, old_name: str, new_name: str) -> int:
        value = str(new_name).strip()
        if not value:
            return 0
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                "UPDATE tem_images SET batch_name=?, updated_at=? WHERE batch_name=?",
                (value, datetime.now(timezone.utc).isoformat(), str(old_name)),
            )
            connection.commit()
            return int(cursor.rowcount)

    def delete_images(self, image_ids: Iterable[int]) -> int:
        identifiers = [int(value) for value in image_ids]
        if not identifiers:
            return 0
        records = self.images(identifiers)
        marks = ",".join("?" for _ in identifiers)
        with closing(self.connect()) as connection:
            cursor = connection.execute(f"DELETE FROM tem_images WHERE id IN ({marks})", identifiers)
            connection.commit()
        for record in records:
            stored = Path(record["stored_path"])
            with closing(self.connect()) as connection:
                remaining = connection.execute("SELECT 1 FROM tem_images WHERE stored_path=? LIMIT 1", (str(stored),)).fetchone()
            if not remaining:
                try:
                    stored.unlink()
                except OSError:
                    pass
        return int(cursor.rowcount)

    def reanalyze(
        self,
        image_id: int,
        parameters: TEMAnalysisParameters,
        *,
        batch_name: str | None = None,
        scale_nm: float | None = None,
        bar_pixels: float | None = None,
    ) -> dict[str, Any]:
        records = self.images([int(image_id)])
        if not records:
            raise KeyError(f"TEM image {image_id} is not present.")
        record = records[0]
        analysis = analyze_tem_image(
            record["stored_path"],
            parameters,
            batch_name=batch_name or record["batch_name"],
            scale_nm=scale_nm,
            bar_pixels=bar_pixels,
            checksum=record["checksum"],
        )
        self.store(analysis)
        return self.images([int(image_id)])[0]


def import_tem_paths(
    paths: Iterable[str | Path],
    library: TEMLibrary,
    parameters: TEMAnalysisParameters | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    files = [Path(path) for path in paths]
    result: dict[str, Any] = {"imported": [], "duplicates": [], "blank": [], "needs_scale": [], "errors": []}
    for index, path in enumerate(files, start=1):
        if progress_callback:
            progress_callback(index, len(files), path.name)
        try:
            checksum = sha256_file(path)
            duplicate = library.checksum_exists(checksum)
            if duplicate:
                result["duplicates"].append({"path": str(path), "existing": duplicate})
                continue
            analysis = analyze_tem_image(path, parameters, checksum=checksum)
            image_id = library.store(analysis)
            result["imported"].append(image_id)
            if analysis.status == "blank":
                result["blank"].append(image_id)
            elif analysis.status == "needs_scale":
                result["needs_scale"].append(image_id)
        except Exception as exc:
            result["errors"].append(f"{path.name}: {exc}")
    return result
