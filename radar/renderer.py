"""Cinrad rendering + on-disk PNG cache.

Cinrad/matplotlib is not thread-safe. All rendering is serialized through
the prerender queue's single worker, so this module itself uses a coarse
lock as an extra safety net.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import cinrad  # noqa: E402

from .parser import parse_filename

log = logging.getLogger(__name__)

_RENDER_LOCK = threading.Lock()


def cache_file_for(cache_dir: Path, path: str) -> Path:
    """Path to the cached PNG for a given radar bin file.

    Mirrors the source layout:
        cache_dir / <station> / <year> / <date> / <product> / <filename>.png

    Falls back to a flat hashed name under `_misc/` for files whose name
    can't be parsed.
    """
    p = Path(path)
    rf = parse_filename(p)
    if rf is not None:
        year = rf.datetime_utc.strftime("%Y")
        date = rf.datetime_utc.strftime("%Y%m%d")
        return cache_dir / rf.station / year / date / rf.product / (p.stem + ".png")
    h = hashlib.md5(path.encode("utf-8")).hexdigest()[:16]
    return cache_dir / "_misc" / f"{p.stem}_{h}.png"


def render_to_cache(bin_path: str, cache_dir: Path) -> Path:
    """Render a single radar bin file to PNG, cached on disk.

    Returns the path to the cached PNG. If a previous render exists,
    returns it without re-rendering.
    """
    out = cache_file_for(cache_dir, bin_path)
    if out.exists() and out.stat().st_size > 0:
        return out

    src = Path(bin_path)
    if not src.exists():
        raise FileNotFoundError(bin_path)

    with _RENDER_LOCK:
        if out.exists() and out.stat().st_size > 0:
            return out

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.png")
        try:
            f = cinrad.io.read_auto(str(src))
            data = f.get_data()
            fig = cinrad.visualize.PPI(data)
            fig(str(tmp))
            tmp.replace(out)
            return out
        except Exception:
            log.exception("Render failed for %s", bin_path)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise
        finally:
            plt.close("all")


def is_cached(bin_path: str, cache_dir: Path) -> bool:
    p = cache_file_for(cache_dir, bin_path)
    return p.exists() and p.stat().st_size > 0
