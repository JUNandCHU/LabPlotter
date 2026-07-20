from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np


@dataclass
class Spectrum:
    name: str
    x: np.ndarray
    y: np.ndarray
    source: str = ""
    visible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    uid: str = field(default_factory=lambda: uuid4().hex)

    def clean(self) -> "Spectrum":
        x = np.asarray(self.x, dtype=float)
        y = np.asarray(self.y, dtype=float)
        keep = np.isfinite(x) & np.isfinite(y)
        x, y = x[keep], y[keep]
        order = np.argsort(x)
        self.x, self.y = x[order], y[order]
        return self


@dataclass
class ZetaMeasurement:
    particle_name: str
    kind: str
    replicate: int
    x: np.ndarray
    y: np.ndarray
    source_file: str
    sheet_name: str
    cell_number: str = ""
    result_png: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def source_basename(self) -> str:
        return Path(self.source_file).name

