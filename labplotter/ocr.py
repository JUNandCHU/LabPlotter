from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
import threading

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


OCR_COLUMNS = ("Name", "Mean", "Standard Deviation", "RSD", "Minimum", "Maximum")
_ENGINE = None
_ENGINE_LOCK = threading.Lock()


@dataclass
class OCRTable:
    columns: tuple[str, ...]
    rows: list[list[str]]
    confidence: list[list[float | None]]
    raw_lines: list[str]
    engine: str


@dataclass
class _Token:
    text: str
    score: float
    center_x: float
    center_y: float
    height: float


def _preprocess_and_columns(image_bytes: bytes, scale: int = 4) -> tuple[Image.Image, list[float] | None]:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    gray = np.asarray(image.convert("L"))
    height, width = gray.shape

    row_dark = np.sum(gray < 245, axis=1)
    row_index = np.arange(height)
    useful_rows = np.flatnonzero((row_dark > 10) & (row_index > 2) & (row_index < height - 3))
    bottom = min(height, int(useful_rows.max()) + 7) if useful_rows.size else height

    column_sample = gray[3 : max(4, bottom - 3)]
    col_dark = np.sum(column_sample < 245, axis=0)
    line_pixels = np.flatnonzero(col_dark > column_sample.shape[0] * 0.65)
    groups: list[list[int]] = []
    for pixel in line_pixels:
        if not groups or pixel > groups[-1][-1] + 1:
            groups.append([int(pixel)])
        else:
            groups[-1].append(int(pixel))
    vertical_lines = [float(np.mean(group)) for group in groups]
    vertical_lines = [value for value in vertical_lines if value > 2 and value < width - 10]
    table_lines = vertical_lines[-7:] if len(vertical_lines) >= 7 else []
    column_centers = [((left + right_edge) / 2.0) * scale for left, right_edge in zip(table_lines, table_lines[1:])] if len(table_lines) == 7 else None

    # Keep the original canvas. Its white margin helps the detector avoid merging
    # the first text cell with the adjacent numeric Mean cell.
    cropped = image.convert("L")
    cropped = ImageOps.autocontrast(cropped)
    cropped = cropped.resize((cropped.width * scale, cropped.height * scale), Image.Resampling.LANCZOS)
    cropped = ImageEnhance.Contrast(cropped).enhance(1.5)
    return cropped.filter(ImageFilter.SHARPEN).convert("RGB"), column_centers


def preprocess_table_image(image_bytes: bytes, scale: int = 4) -> Image.Image:
    """Crop unused white space and enlarge the small embedded ZetaSizer table."""
    return _preprocess_and_columns(image_bytes, scale)[0]


def _rapidocr_engine():
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            from rapidocr import RapidOCR

            _ENGINE = RapidOCR()
    return _ENGINE


def _cluster_tokens(tokens: list[_Token]) -> list[list[_Token]]:
    if not tokens:
        return []
    threshold = max(8.0, float(np.median([token.height for token in tokens])) * 0.65)
    rows: list[list[_Token]] = []
    for token in sorted(tokens, key=lambda item: (item.center_y, item.center_x)):
        if not rows:
            rows.append([token])
            continue
        center = float(np.mean([item.center_y for item in rows[-1]]))
        if abs(token.center_y - center) <= threshold:
            rows[-1].append(token)
        else:
            rows.append([token])
    for row in rows:
        row.sort(key=lambda item: item.center_x)
    return rows


def _table_from_tokens(tokens: list[_Token], engine: str = "RapidOCR", column_centers: list[float] | None = None) -> OCRTable:
    clusters = _cluster_tokens(tokens)
    if not clusters:
        return OCRTable(OCR_COLUMNS, [], [], [], engine)

    header_words = ("name", "mean", "standard", "rsd", "minimum", "maximum")
    header_index = max(
        range(len(clusters)),
        key=lambda index: sum(any(word in token.text.casefold() for token in clusters[index]) for word in header_words),
    )
    header = clusters[header_index]
    centers = list(column_centers or ())
    if len(centers) != len(OCR_COLUMNS):
        centers = [token.center_x for token in header]
        if len(centers) >= len(OCR_COLUMNS):
            centers = centers[: len(OCR_COLUMNS)]
        elif len(centers) >= 2:
            centers = np.linspace(min(centers), max(centers), len(OCR_COLUMNS)).tolist()
        else:
            maximum = max(token.center_x for token in tokens)
            centers = np.linspace(maximum * 0.08, maximum * 0.92, len(OCR_COLUMNS)).tolist()

    values: list[list[str]] = []
    confidence: list[list[float | None]] = []
    raw_lines: list[str] = []
    for cluster in clusters[header_index + 1 :]:
        cells: list[list[_Token]] = [[] for _ in OCR_COLUMNS]
        for token in cluster:
            column = int(np.argmin([abs(token.center_x - center) for center in centers]))
            cells[column].append(token)
        row = [" ".join(token.text for token in cell).strip() for cell in cells]
        if not any(row):
            continue
        values.append(row)
        confidence.append([
            float(np.mean([token.score for token in cell])) if cell else None
            for cell in cells
        ])
        raw_lines.append("\t".join(row))
    return OCRTable(OCR_COLUMNS, values, confidence, raw_lines, engine)


def run_table_ocr(image_bytes: bytes) -> OCRTable:
    image, column_centers = _preprocess_and_columns(image_bytes)
    result = _rapidocr_engine()(np.asarray(image))
    text_value = getattr(result, "txts", None)
    box_value = getattr(result, "boxes", None)
    score_value = getattr(result, "scores", None)
    texts = tuple(text_value) if text_value is not None else ()
    boxes = tuple(box_value) if box_value is not None else ()
    scores = tuple(score_value) if score_value is not None else ()
    tokens: list[_Token] = []
    for text, box, score in zip(texts, boxes, scores):
        points = np.asarray(box, dtype=float)
        tokens.append(
            _Token(
                str(text).strip(),
                float(score),
                float(np.mean(points[:, 0])),
                float(np.mean(points[:, 1])),
                float(np.max(points[:, 1]) - np.min(points[:, 1])),
            )
        )
    try:
        engine = f"RapidOCR {version('rapidocr')}"
    except PackageNotFoundError:
        engine = "RapidOCR"
    return _table_from_tokens(tokens, engine, column_centers)
