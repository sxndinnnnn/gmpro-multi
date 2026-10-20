"""Google load amounts are integers: weight x 1000, volume x 100."""
from __future__ import annotations

from typing import Literal

LoadDimension = Literal["weight", "volume"]

SCALE: dict[str, int] = {"weight": 1000, "volume": 100}


def to_units(dimension: LoadDimension, amount: float | None) -> int:
    return int(round((amount or 0) * SCALE[dimension]))


def from_units(dimension: LoadDimension, units: int | float) -> float:
    return round(units / SCALE[dimension], 3)
