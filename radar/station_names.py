"""Lookup of radar station code -> Chinese station name.

The mapping is loaded from a JSON file (see config.STATION_NAMES_FILE).
Accepted JSON shapes for each entry:
    "Z9439": "白山"
    "Z9439": { "name": "白山", "province": "吉林" }

Missing codes gracefully fall back to the bare code.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Iterable, List, Optional

log = logging.getLogger(__name__)


class StationNames:
    def __init__(self, file_path: Path):
        self.file = Path(file_path)
        self._lock = threading.Lock()
        self._map: dict = {}
        self._mtime: float = 0.0
        self._reload_if_changed()

    # ---- public ----
    def name_for(self, code: str) -> Optional[str]:
        self._reload_if_changed()
        return self._map.get(code)

    def label_for(self, code: str) -> str:
        name = self.name_for(code)
        return f"{code}（{name}）" if name else code

    def annotate(self, codes: Iterable[str]) -> List[dict]:
        self._reload_if_changed()
        return [
            {
                "code": c,
                "name": self._map.get(c),
                "label": f"{c}（{self._map[c]}）" if c in self._map else c,
            }
            for c in codes
        ]

    # ---- internal ----
    def _reload_if_changed(self) -> None:
        try:
            mtime = self.file.stat().st_mtime if self.file.exists() else 0.0
        except OSError:
            mtime = 0.0
        if mtime == self._mtime:
            return
        with self._lock:
            if mtime == self._mtime:
                return
            self._mtime = mtime
            self._map = self._load_file()

    def _load_file(self) -> dict:
        if not self.file.exists():
            return {}
        try:
            with open(self.file, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Failed to read station names from %s: %s", self.file, exc)
            return {}
        if not isinstance(data, dict):
            log.warning("station names file %s must be a JSON object", self.file)
            return {}
        out: dict = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, str):
                out[k] = v
            elif isinstance(v, dict):
                name = v.get("name")
                if isinstance(name, str):
                    out[k] = name
        log.info("Loaded %d radar station names from %s", len(out), self.file)
        return out
