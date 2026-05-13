"""Persistent on-disk index of stations + per-station date list.

The data tree (DATA_ROOT/<year>/<yyyymmdd>/<station>/<product>) lives on a slow
network share, so we cache the top-level structure on disk and only rescan once
per `ttl_seconds`. The cache is refreshed in a background thread: callers always
get the current snapshot immediately, even on cold start (which simply returns
an empty snapshot until the first scan finishes).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)


class IndexCache:
    SCHEMA = 1

    def __init__(self, root: Path, file_path: Path, ttl_seconds: float = 3600.0):
        self.root = Path(root)
        self.file = Path(file_path)
        self.ttl = float(ttl_seconds)

        self._data: Optional[dict] = None
        self._data_lock = threading.Lock()
        self._refresh_lock = threading.Lock()  # held while a refresh is in flight
        self._refresh_running = threading.Event()

        self._load_from_disk()

    # ------------------------------------------------------------------ API
    def stations(self) -> List[str]:
        return list(self._snapshot().get("stations", []))

    def dates(self, station: str) -> List[str]:
        return list(self._snapshot().get("dates_by_station", {}).get(station, []))

    def is_loaded(self) -> bool:
        with self._data_lock:
            return self._data is not None

    def is_refreshing(self) -> bool:
        return self._refresh_running.is_set()

    def updated_at(self) -> float:
        with self._data_lock:
            if not self._data:
                return 0.0
            return float(self._data.get("updated_at", 0.0))

    def trigger_refresh(self, force: bool = False) -> bool:
        """Spawn a background refresh thread. No-op if one is already running
        (unless `force` and no scan is in progress)."""
        if self._refresh_running.is_set():
            return False
        t = threading.Thread(
            target=self._run_refresh, kwargs={"force": force},
            daemon=True, name="index-refresh",
        )
        t.start()
        return True

    def warm_up(self) -> None:
        """Called at app startup. Triggers refresh if cache is missing or stale."""
        with self._data_lock:
            data = self._data
        if data is None or self._is_stale(data):
            self.trigger_refresh()

    # ----------------------------------------------------------- internals
    def _snapshot(self) -> dict:
        """Return current data; trigger async refresh if stale or absent."""
        with self._data_lock:
            data = self._data
        if data is None or self._is_stale(data):
            self.trigger_refresh()
        return data or {}

    def _is_stale(self, data: dict) -> bool:
        return (time.time() - data.get("updated_at", 0.0)) > self.ttl

    def _load_from_disk(self) -> None:
        if not self.file.exists():
            return
        try:
            with open(self.file, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Failed to load index cache %s: %s", self.file, exc)
            return
        if not isinstance(data, dict) or data.get("schema") != self.SCHEMA:
            log.info("Index cache schema mismatch, ignoring on-disk file")
            return
        with self._data_lock:
            self._data = data
        log.info(
            "Loaded index cache: %d stations, age %.0fs",
            len(data.get("stations", [])),
            max(0.0, time.time() - data.get("updated_at", 0.0)),
        )

    def _run_refresh(self, force: bool = False) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return
        self._refresh_running.set()
        try:
            log.info("Index cache refresh started (force=%s)", force)
            t0 = time.time()
            new_data = self._scan()
            self._write_atomic(new_data)
            with self._data_lock:
                self._data = new_data
            log.info(
                "Index cache refreshed in %.1fs: %d stations, %d (station,date) pairs",
                time.time() - t0,
                len(new_data["stations"]),
                sum(len(v) for v in new_data["dates_by_station"].values()),
            )
        except Exception:
            log.exception("Index cache refresh failed")
        finally:
            self._refresh_running.clear()
            self._refresh_lock.release()

    def _scan(self) -> dict:
        stations: set = set()
        dates_by_station: dict = defaultdict(set)
        if self.root.is_dir():
            for year_dir in self._iter_subdirs(self.root):
                for date_dir in self._iter_subdirs(year_dir):
                    for st_dir in self._iter_subdirs(date_dir):
                        stations.add(st_dir.name)
                        dates_by_station[st_dir.name].add(date_dir.name)
        return {
            "schema": self.SCHEMA,
            "updated_at": time.time(),
            "stations": sorted(stations),
            "dates_by_station": {s: sorted(ds) for s, ds in dates_by_station.items()},
        }

    def _iter_subdirs(self, path: Path):
        try:
            for p in path.iterdir():
                if p.is_dir():
                    yield p
        except OSError:
            return

    def _write_atomic(self, data: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.file)
