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

log = logging.getLogger(__name__)

_RENDER_LOCK = threading.Lock()


def cache_key_for(path: str) -> str:
    """Stable cache key from absolute file path."""
    h = hashlib.md5(path.encode("utf-8")).hexdigest()[:16]
    name = Path(path).stem
    return f"{name}_{h}"


def cache_file_for(cache_dir: Path, path: str) -> Path:
    return cache_dir / f"{cache_key_for(path)}.png"


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
