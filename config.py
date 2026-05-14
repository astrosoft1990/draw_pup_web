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

# 产品类型黑名单：与数据目录下产品文件夹名一致（如 ZDR、VEL）。
# 列入此集合的类型不会出现在 /api/products 中，也不会参与列表与绘图。
PRODUCT_TYPE_BLACKLIST = frozenset({"CAR","CS","SS","TVS","VWP","WER"})  # 例如: frozenset({"CR", "ET"})

# 产品代码 -> 中文名（与目录/文件名中的产品代号一致）。未列出的产品仅显示代号。
PRODUCT_NAME_ZH = {
    "CR": "组合反射率",
    "R": "基本反射率",
    "V": "径向速度",
    "SW": "谱宽",
    "ZDR": "差分反射率",
    "PHV": "相关系数",
    "CC": "协相关系数",
    "KDP": "比差分相位",
    "ET": "回波顶高",
    "VIL": "垂直液态水含量",
    "OHP": "一小时降水",
    "STP": "风暴总降水",
    "THP": "三小时降水",
    "HSR": "混合反射率",
    "RZC": "组合反射率因子拼图",
    "PAC": "粒子相态分类",
    "HCL": "粒子相态分类",
    "HC": "粒子相态分类",
    "TREF": "反射率因子",
    "VEL": "径向速度",
    "CAR": "等高面反射率",
    "SRM": "风暴相对径向速度",
    "M":"中气旋",
    "STI":"风暴追踪",
    "HI":"冰雹",
}
