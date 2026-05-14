"""Flask app exposing radar PUP product browser."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

import config
from radar.index_cache import IndexCache
from radar.prerender import get_queue
from radar.renderer import (
    cache_file_for,
    is_cached,
    render_to_cache,
)
from radar.parser import parse_filename
from radar.scanner import RadarScanner
from radar.station_names import StationNames

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = Flask(__name__)
scanner = RadarScanner(config.DATA_ROOT, ttl=config.DIR_SCAN_TTL_SECONDS)
queue = get_queue(config.CACHE_DIR, max_items=config.PRERENDER_QUEUE_MAX)
index_cache = IndexCache(
    config.DATA_ROOT,
    config.INDEX_CACHE_FILE,
    ttl_seconds=config.INDEX_CACHE_TTL_SECONDS,
)
index_cache.warm_up()

station_names = StationNames(config.STATION_NAMES_FILE)


# ---------------------------------------------------------------------------
# Security: only allow paths inside DATA_ROOT
# ---------------------------------------------------------------------------
_DATA_ROOT_ABS = os.path.abspath(str(config.DATA_ROOT))
_IS_WINDOWS = os.name == "nt"


def _is_under_root(abs_path: str) -> bool:
    """Case-aware prefix check (case-insensitive on Windows)."""
    a = abs_path
    r = _DATA_ROOT_ABS
    if _IS_WINDOWS:
        a = a.lower()
        r = r.lower()
    return a == r or a.startswith(r + os.sep)


def _validate_path(raw: str) -> Path:
    if not raw:
        abort(400, "path is required")
    try:
        abs_path = os.path.abspath(raw)
    except (OSError, ValueError) as exc:
        app.logger.warning("validate_path: cannot abspath %r (%s)", raw, exc)
        abort(400, "invalid path")
    if not _is_under_root(abs_path):
        app.logger.warning(
            "validate_path: path outside data root: %r vs %r", abs_path, _DATA_ROOT_ABS
        )
        abort(403, "path outside data root")
    p = Path(abs_path)
    if not p.is_file():
        app.logger.warning("validate_path: file not found: %r", abs_path)
        abort(404, "file not found")
    return p


def _safe_abs_inside_root(raw: str) -> str | None:
    """Return absolute path if it lies under DATA_ROOT, otherwise None."""
    if not raw:
        return None
    try:
        abs_path = os.path.abspath(raw)
    except (OSError, ValueError):
        return None
    if not _is_under_root(abs_path):
        return None
    return abs_path


def _public_url_for_cache(bin_path: str) -> str:
    cache = cache_file_for(config.CACHE_DIR, bin_path)
    rel = cache.relative_to(config.CACHE_DIR).as_posix()
    return f"/cache/{rel}"


def _product_type_blocked(product: str) -> bool:
    return product in config.PRODUCT_TYPE_BLACKLIST


def _product_option(code: str) -> dict:
    """Shape for /api/products items: code, label (shown in select), optional name (tooltip)."""
    zh = config.PRODUCT_NAME_ZH.get(code)
    if zh:
        return {"code": code, "label": f"{code} {zh}", "name": zh}
    return {"code": code, "label": code}


# ---------------------------------------------------------------------------
# Pages & cache serving
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.get("/cache/<path:relpath>")
def serve_cache(relpath: str):
    """Serve a rendered PNG out of CACHE_DIR (which may be on a UNC share).

    `send_from_directory` performs path-traversal protection: any `..` or
    absolute components in `relpath` will be rejected.
    """
    return send_from_directory(
        str(config.CACHE_DIR),
        relpath,
        max_age=3600,
    )


# ---------------------------------------------------------------------------
# Metadata APIs
# ---------------------------------------------------------------------------
def _index_meta() -> dict:
    return {
        "refreshing": index_cache.is_refreshing(),
        "loaded": index_cache.is_loaded(),
        "updated_at": index_cache.updated_at(),
    }


@app.get("/api/stations")
def api_stations():
    codes = index_cache.stations()
    return jsonify({"stations": station_names.annotate(codes), **_index_meta()})


@app.get("/api/dates")
def api_dates():
    station = request.args.get("station", "").strip()
    if not station:
        abort(400, "station is required")
    return jsonify({"dates": index_cache.dates(station), **_index_meta()})


@app.post("/api/refresh-index")
def api_refresh_index():
    started = index_cache.trigger_refresh(force=True)
    return jsonify({"ok": True, "started": started, **_index_meta()})


@app.get("/api/products")
def api_products():
    station = request.args.get("station", "").strip()
    date = request.args.get("date", "").strip()
    if not (station and date):
        abort(400, "station and date are required")
    products = [
        _product_option(p)
        for p in scanner.list_products(station, date)
        if not _product_type_blocked(p)
    ]
    return jsonify({"products": products})


@app.get("/api/files")
def api_files():
    """Return a structured file list for one (station, date, product).

    Response shape:
        {
            "times": ["000317", ...],
            "time_labels": ["00:03:17", ...],
            "elevations": [0.5, 1.5, 2.4, ...] or [],
            "elevation_raws": [5, 15, 24, ...] or [],
            "frames": [
                {"time": "000317", "elevation_raw": 5, "path": "...",
                 "time_label": "00:03:17", "elevation_label": "0.5°",
                 "cached": false},
                ...
            ]
        }

    Query:
        include_cached=1  # optional, include per-frame cache existence check
    """
    station = request.args.get("station", "").strip()
    date = request.args.get("date", "").strip()
    product = request.args.get("product", "").strip()
    if not (station and date and product):
        abort(400, "station, date and product are required")
    if _product_type_blocked(product):
        abort(404, "product type is blocked")

    files = scanner.list_files(station, date, product)
    include_cached = request.args.get("include_cached", "").strip() in {"1", "true", "yes"}

    times: list = []
    time_labels: dict = {}
    elev_raws: set = set()
    elev_has_real = False

    frames = []
    for rf in files:
        if rf.time_str not in time_labels:
            times.append(rf.time_str)
            time_labels[rf.time_str] = rf.time_label
        if rf.elevation_raw is not None:
            elev_raws.add(rf.elevation_raw)
            elev_has_real = True

        # NOTE:
        # Checking cache existence for every frame can be very expensive on
        # network shares (thousands of stat calls). Default to False and let
        # the frontend poll /api/cache-status progressively.
        cached = is_cached(str(rf.path), config.CACHE_DIR) if include_cached else False
        frames.append({
            **rf.to_dict(),
            "cached": cached,
        })

    times.sort()
    if elev_has_real:
        elev_sorted = sorted(elev_raws)
        elevations = [round(e / 10.0, 1) for e in elev_sorted]
        elevation_raws = elev_sorted
    else:
        elevations = []
        elevation_raws = []

    return jsonify({
        "times": times,
        "time_labels": [time_labels[t] for t in times],
        "elevations": elevations,
        "elevation_raws": elevation_raws,
        "frames": frames,
    })


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
@app.get("/api/render")
def api_render():
    raw = request.args.get("path", "")
    if not raw:
        abort(400, "path is required")
    p = _validate_path(raw)
    rf_meta = parse_filename(p)
    if rf_meta is not None and _product_type_blocked(rf_meta.product):
        abort(403, "product type is blocked")

    try:
        render_to_cache(str(p), config.CACHE_DIR)
    except FileNotFoundError:
        abort(404, "file not found")
    except Exception as exc:
        app.logger.exception("render failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "url": _public_url_for_cache(str(p))})


@app.post("/api/prerender")
def api_prerender():
    """Submit a list of paths to be prerendered in the background.

    Body: {"items": [{"path": "...", "priority": 10}, ...]}
    Lower priority number = rendered sooner.
    """
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    replace = bool(data.get("replace", True))

    cleaned = []
    for it in items:
        if not isinstance(it, dict):
            continue
        raw = it.get("path")
        abs_path = _safe_abs_inside_root(raw)
        if abs_path is None:
            continue
        prf = parse_filename(Path(abs_path))
        if prf is not None and _product_type_blocked(prf.product):
            continue
        priority = int(it.get("priority", 100))
        cleaned.append((abs_path, priority))

    if replace:
        submitted = queue.replace_all(cleaned)
    else:
        submitted = 0
        for p, pri in cleaned:
            queue.submit(p, priority=pri)
            submitted += 1
    return jsonify({"ok": True, "submitted": submitted})


@app.get("/api/cache-status")
def api_cache_status():
    """Quick check of which paths are already rendered. POST-ish via GET array."""
    raws = request.args.getlist("path")
    result = {}
    for raw in raws:
        abs_path = _safe_abs_inside_root(raw)
        if abs_path is None:
            continue
        result[raw] = is_cached(abs_path, config.CACHE_DIR)
    return jsonify({"cached": result})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
