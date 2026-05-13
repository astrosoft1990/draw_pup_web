"""Directory scanner with simple TTL cache.

Directory layout:
    DATA_ROOT / <year> / <yyyymmdd> / <station> / <product> / <files>.bin
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .parser import RadarFile, parse_filename


class TTLCache:
    """Tiny thread-safe TTL cache keyed by arbitrary hashable keys."""

    def __init__(self, ttl: float):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._store: Dict[tuple, Tuple[float, object]] = {}

    def get(self, key: tuple):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.time() - ts > self._ttl:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: tuple, value: object):
        with self._lock:
            self._store[key] = (time.time(), value)


class RadarScanner:
    def __init__(self, root: Path, ttl: float = 60.0):
        self.root = Path(root)
        self.cache = TTLCache(ttl)

    # ---- helpers ------------------------------------------------------
    def _list_dirs(self, path: Path) -> List[str]:
        if not path.exists() or not path.is_dir():
            return []
        try:
            return sorted([p.name for p in path.iterdir() if p.is_dir()])
        except OSError:
            return []

    # ---- public API ---------------------------------------------------
    def list_stations(self) -> List[str]:
        """Union of station folders across all year/date directories."""
        key = ("stations",)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        stations: set = set()
        for year_dir in self._iter_subdirs(self.root):
            for date_dir in self._iter_subdirs(year_dir):
                for station_dir in self._iter_subdirs(date_dir):
                    stations.add(station_dir.name)
        result = sorted(stations)   
        self.cache.set(key, result)
        return result

    def list_dates(self, station: str) -> List[str]:
        """All dates (yyyymmdd) for which the station has data."""
        key = ("dates", station)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        dates: List[str] = []
        for year_dir in self._iter_subdirs(self.root):
            for date_dir in self._iter_subdirs(year_dir):
                if (date_dir / station).is_dir():
                    dates.append(date_dir.name)
        result = sorted(dates)
        self.cache.set(key, result)
        return result

    def list_products(self, station: str, date: str) -> List[str]:
        """Products available for given station+date."""
        key = ("products", station, date)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        product_dir = self._product_dir_parent(station, date)
        result = self._list_dirs(product_dir) if product_dir else []
        self.cache.set(key, result)
        return result

    def list_files(self, station: str, date: str, product: str) -> List[RadarFile]:
        """All radar files for a (station, date, product) tuple.

        When multiple files share the same (time, elevation) but differ in
        detection range / grid resolution, only the highest-resolution
        variant is kept (smallest range first, then largest grid).
        """
        key = ("files", station, date, product)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        product_dir = self._product_dir(station, date, product)
        raw_files: List[RadarFile] = []
        if product_dir and product_dir.is_dir():
            try:
                for p in product_dir.iterdir():
                    if not p.is_file():
                        continue
                    rf = parse_filename(p)
                    if rf is not None:
                        raw_files.append(rf)
            except OSError:
                pass

        # Dedup by (time, elevation) keeping the best quality variant.
        best: dict = {}
        for rf in raw_files:
            k = (rf.datetime_utc, rf.elevation_raw)
            cur = best.get(k)
            if cur is None or rf.quality_key < cur.quality_key:
                best[k] = rf

        files = sorted(best.values(), key=lambda r: (r.datetime_utc, r.elevation_raw or -1))
        self.cache.set(key, files)
        return files

    # ---- path helpers -------------------------------------------------
    def _iter_subdirs(self, path: Path):
        if not path.exists() or not path.is_dir():
            return
        try:
            for p in path.iterdir():
                if p.is_dir():
                    yield p
        except OSError:
            return

    def _product_dir_parent(self, station: str, date: str) -> Optional[Path]:
        year = date[:4]
        p = self.root / year / date / station
        return p if p.is_dir() else None

    def _product_dir(self, station: str, date: str, product: str) -> Optional[Path]:
        parent = self._product_dir_parent(station, date)
        if parent is None:
            return None
        p = parent / product
        return p if p.is_dir() else None
