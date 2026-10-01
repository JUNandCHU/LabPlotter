"""Dispatch supported C/H ASCII layouts without guessing from file names."""
from pathlib import Path
import re

from .hnmr import HNMRSpectrum, parse_hnmr_text
from .models import Spectrum
from .nmr import parse_topspin_ascii


def parse_nmr_ascii(path: str | Path) -> HNMRSpectrum | Spectrum:
    """Keep complex data in the H workspace and four-column data in C.

    Recognize the H header before parsing so damaged complex exports retain
    their real error (e.g. SIZE mismatch), instead of falling back to C.
    Neither a file's name nor the currently selected tab determines its type.
    """
    path = Path(path)
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    rows = (line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#"))
    first = next(rows, "")
    table = re.split(r"[,;\s]+", first.lower()) == ["ppm", "real", "imag"]
    top_spin = all(re.search(rf"\b{key}\s*=", text) for key in ("LEFT", "RIGHT", "SIZE"))
    if top_spin or table:
        return parse_hnmr_text(text, path.stem, str(path))
    return parse_topspin_ascii(path)
