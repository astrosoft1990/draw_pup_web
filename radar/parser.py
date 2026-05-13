"""Radar filename parsing.

Filename pattern (split by underscore):
    Z_RADR_I_<station>_<datetime>_P_DOR_CC_<product>_<resolution>_<range>_<elevation>_FMT.bin
    idx: 0 1   2  3        4      5  6   7    8          9          10        11

`elevation` is "NUL" for products without elevation (CR/ET/VIL/...),
otherwise an integer in 0.1 degree units (5 -> 0.5 deg, 15 -> 1.5 deg).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


def _leading_int(s: str) -> Optional[int]:
    """Extract the leading integer from a string like '300X300' or '400'."""
    if not s:
        return None
    digits = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


@dataclass(frozen=True)
class RadarFile:
    path: Path
    station: str
    datetime_utc: datetime
    product: str
    resolution: str
    range_km: str
    elevation_raw: Optional[int]  # None when NUL

    @property
    def time_str(self) -> str:
        return self.datetime_utc.strftime("%H%M%S")

    @property
    def time_label(self) -> str:
        return self.datetime_utc.strftime("%H:%M:%S")

    @property
    def elevation_deg(self) -> Optional[float]:
        if self.elevation_raw is None:
            return None
        return round(self.elevation_raw / 10.0, 1)

    @property
    def elevation_label(self) -> str:
        if self.elevation_deg is None:
            return "-"
        return f"{self.elevation_deg:.1f}°"

    @property
    def range_km_int(self) -> Optional[int]:
        return _leading_int(self.range_km)

    @property
    def resolution_int(self) -> Optional[int]:
        """Grid points per side ('300X300' -> 300, '300' -> 300)."""
        return _leading_int(self.resolution)

    @property
    def quality_key(self) -> tuple:
        """Sort key for picking the highest-resolution variant.

        Lower tuple = better. Strategy:
          1. Smaller detection range (km) -> finer ground resolution per cell.
          2. Larger grid resolution -> finer cell.
          3. Path string as deterministic tiebreaker.
        """
        rng = self.range_km_int if self.range_km_int is not None else 10 ** 9
        res = self.resolution_int if self.resolution_int is not None else 0
        return (rng, -res, str(self.path))

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "station": self.station,
            "time": self.time_str,
            "time_label": self.time_label,
            "datetime": self.datetime_utc.strftime("%Y%m%d%H%M%S"),
            "product": self.product,
            "resolution": self.resolution,
            "range_km": self.range_km,
            "range_km_int": self.range_km_int,
            "elevation_raw": self.elevation_raw,
            "elevation_deg": self.elevation_deg,
            "elevation_label": self.elevation_label,
        }


def parse_filename(path: Path) -> Optional[RadarFile]:
    """Parse a single radar bin file path. Return None on failure."""
    name = path.name
    if not name.endswith(".bin"):
        return None

    parts = name.split("_")
    # Need at least up to elevation field
    if len(parts) < 12:
        return None

    try:
        station = parts[3]
        dt_str = parts[4]
        product = parts[8]
        resolution = parts[9]
        range_km = parts[10]
        elev_field = parts[11]

        dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")

        if elev_field.upper() == "NUL":
            elevation_raw: Optional[int] = None
        else:
            try:
                elevation_raw = int(elev_field)
            except ValueError:
                elevation_raw = None

        return RadarFile(
            path=path,
            station=station,
            datetime_utc=dt,
            product=product,
            resolution=resolution,
            range_km=range_km,
            elevation_raw=elevation_raw,
        )
    except (ValueError, IndexError):
        return None
