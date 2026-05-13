"""Application configuration."""
from pathlib import Path

DATA_ROOT = Path(r"O:\DATA\RADA\DOR\L3\PUP_ROSE2")

BASE_DIR = Path(__file__).resolve().parent

# CACHE_DIR may live on a UNC / network share. It is exposed to the web
# through the dedicated /cache/<path> route (see app.py), NOT through
# Flask's built-in /static/ handler, so it does not need to be inside the
# project tree.
CACHE_DIR = Path(r"\\10.93.132.65\ftpserv\bfth\qxt\radar_img_cache")
try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
except OSError as _exc:
    import logging
    logging.getLogger(__name__).warning(
        "Could not create CACHE_DIR %s at startup: %s", CACHE_DIR, _exc
    )

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INDEX_CACHE_FILE = DATA_DIR / "index.json"
INDEX_CACHE_TTL_SECONDS = 3600  # 1 hour

STATION_NAMES_FILE = DATA_DIR / "stations.json"

DIR_SCAN_TTL_SECONDS = 60

PRERENDER_WORKERS = 1
PRERENDER_QUEUE_MAX = 200

RENDER_DPI = 120
