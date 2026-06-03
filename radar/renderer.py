"""Cinrad rendering + on-disk PNG cache.

Cinrad/matplotlib is not thread-safe. All rendering is serialized through
the prerender queue's single worker, so this module itself uses a coarse
lock as an extra safety net.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import cinrad  # noqa: E402
import cartopy.crs as ccrs  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from matplotlib.font_manager import FontProperties, findfont  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from cinrad.visualize.utils import add_shp  # noqa: E402

from .parser import parse_filename

log = logging.getLogger(__name__)

_RENDER_LOCK = threading.Lock()
_CJK_FONT_CANDIDATES = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "WenQuanYi Micro Hei",
]


def _pick_cjk_font() -> FontProperties | None:
    for family in _CJK_FONT_CANDIDATES:
        try:
            fp = FontProperties(family=family)
            findfont(fp, fallback_to_default=False)
            return fp
        except Exception:
            continue
    return None


def _safe_attr_float(attrs: dict, key: str, default: float = 0.0) -> float:
    v = attrs.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _format_scan_time(attrs: dict) -> tuple[str, str]:
    raw = attrs.get("scan_time")
    if raw is None:
        return "-", "-"
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text[:19], fmt)
            return dt.strftime("%Y.%m.%d"), dt.strftime("%H:%M")
        except ValueError:
            continue
    return text, "-"


def _fixed_site_extent(
    site_lon: float,
    site_lat: float,
    radius_km: float = 200.0,
) -> list[float]:
    """Build fixed map extent around site center with radius in kilometers."""
    lat_deg = radius_km / 111.0
    cos_lat = max(0.15, abs(np.cos(np.deg2rad(site_lat))))
    lon_deg = radius_km / (111.0 * cos_lat)
    return [
        site_lon - lon_deg,
        site_lon + lon_deg,
        site_lat - lat_deg,
        site_lat + lat_deg,
    ]


def _render_hi_style(data, out_file: Path, src_path: Path) -> None:
    """Render HI product in a black-theme style close to common PPI output."""
    attrs = getattr(data, "attrs", {}) or {}

    fig = plt.figure(figsize=(10, 8), facecolor="black")
    ax = fig.add_axes([0.05, 0.06, 0.78, 0.88], projection=ccrs.PlateCarree())
    ax.set_facecolor("black")

    lon_arr = np.asarray(data["longitude"].values if "longitude" in data else [], dtype=float)
    lat_arr = np.asarray(data["latitude"].values if "latitude" in data else [], dtype=float)
    hail_pos = np.asarray(
        data["hail_possibility"].values if "hail_possibility" in data else [],
        dtype=float,
    )
    hail_size = np.asarray(data["hail_size"].values if "hail_size" in data else [], dtype=float)

    valid = (
        np.isfinite(lon_arr)
        & np.isfinite(lat_arr)
        & np.isfinite(hail_pos)
        & (hail_pos >= 20.0)
    ) if lon_arr.size and lat_arr.size and hail_pos.size else np.zeros(0, dtype=bool)
    if hail_size.size == hail_pos.size:
        valid = valid & np.isfinite(hail_size)

    norm = Normalize(vmin=20, vmax=100)
    cmap = plt.get_cmap("turbo")
    mappable = ScalarMappable(norm=norm, cmap=cmap)
    cjk_fp = _pick_cjk_font()
    max_prob = 0.0
    fallback_lon = float(np.nanmean(lon_arr)) if lon_arr.size else 0.0
    fallback_lat = float(np.nanmean(lat_arr)) if lat_arr.size else 0.0
    site_lon = _safe_attr_float(attrs, "site_longitude", fallback_lon)
    site_lat = _safe_attr_float(attrs, "site_latitude", fallback_lat)
    extent = _fixed_site_extent(site_lon, site_lat, radius_km=200.0)
    ax.set_extent(extent, crs=ccrs.PlateCarree())

    if valid.size and np.any(valid):
        lon = lon_arr[valid]
        lat = lat_arr[valid]
        hp = hail_pos[valid]
        hs = hail_size[valid] if hail_size.size == hail_pos.size else np.zeros_like(hp)

        max_prob = float(np.max(hp))
        colors = cmap(norm(hp))

        cls_1 = (hs >= 0.01) & (hs < 0.5)
        cls_2 = (hs >= 0.5) & (hs < 1.0)
        cls_3 = (hs >= 1.0) & (hs < 2.5)
        cls_4 = (hs >= 2.5)

        if np.any(cls_1):
            ax.scatter(
                lon[cls_1],
                lat[cls_1],
                marker="^",
                s=70,
                facecolors="none",
                edgecolors=colors[cls_1],
                linewidths=1.3,
                transform=ccrs.PlateCarree(),
                zorder=5,
            )
        if np.any(cls_2):
            mappable = ax.scatter(
                lon[cls_2],
                lat[cls_2],
                marker="^",
                s=82,
                c=hp[cls_2],
                cmap=cmap,
                norm=norm,
                linewidths=0.6,
                edgecolors="white",
                transform=ccrs.PlateCarree(),
                zorder=5,
            )
        if np.any(cls_3):
            mappable = ax.scatter(
                lon[cls_3],
                lat[cls_3],
                marker="^",
                s=90,
                c=hp[cls_3],
                cmap=cmap,
                norm=norm,
                linewidths=0.6,
                edgecolors="white",
                transform=ccrs.PlateCarree(),
                zorder=5,
            )
            ax.scatter(
                lon[cls_3],
                lat[cls_3],
                s=95,
                marker="x",
                c="#ffd400",
                linewidths=1.6,
                transform=ccrs.PlateCarree(),
                zorder=6,
            )
        if np.any(cls_4):
            mappable = ax.scatter(
                lon[cls_4],
                lat[cls_4],
                marker="^",
                s=100,
                c=hp[cls_4],
                cmap=cmap,
                norm=norm,
                linewidths=0.8,
                edgecolors="white",
                transform=ccrs.PlateCarree(),
                zorder=5,
            )
            ax.scatter(
                lon[cls_4],
                lat[cls_4],
                s=110,
                marker="x",
                c="#ff3b3b",
                linewidths=1.8,
                transform=ccrs.PlateCarree(),
                zorder=6,
            )

    else:
        ax.text(
            site_lon,
            site_lat,
            "No HI Targets",
            color="white",
            fontsize=13,
            ha="center",
            va="center",
            alpha=0.85,
            transform=ccrs.PlateCarree(),
            zorder=7,
        )

    add_shp(
        ax,
        ccrs.PlateCarree(),
        coastline=False,
        style="black",
        extent=ax.get_extent(ccrs.PlateCarree()),
    )
    ax.gridlines(draw_labels=False, color="#3a3a3a", linestyle="--", linewidth=0.5, alpha=0.45)
    ax.set_xticks([])
    ax.set_yticks([])
    if "geo" in ax.spines:
        ax.spines["geo"].set_color("#707070")
        ax.spines["geo"].set_linewidth(0.8)

    cbar = fig.colorbar(mappable, ax=ax, fraction=0.046, pad=0.05)
    if cjk_fp is not None:
        cbar.set_label("冰雹概率(%)", color="white", fontproperties=cjk_fp)
    else:
        cbar.set_label("冰雹概率(%)", color="white")
    cbar.ax.tick_params(colors="white")
    cbar.outline.set_edgecolor("white")

    legend_handles = [
        Line2D(
            [],
            [],
            marker="^",
            markersize=8,
            markerfacecolor="none",
            markeredgecolor="white",
            linestyle="None",
            label="0.1-5 mm：空心三角",
        ),
        Line2D(
            [],
            [],
            marker="^",
            markersize=8,
            markerfacecolor="#37f563",
            markeredgecolor="white",
            linestyle="None",
            label="5-10 mm：实心三角",
        ),
        Line2D(
            [],
            [],
            marker="^",
            markersize=8,
            markerfacecolor="#f6f242",
            markeredgecolor="white",
            markeredgewidth=0.8,
            linestyle="None",
            label="10-25 mm：三角 + 黄X",
        ),
        Line2D(
            [],
            [],
            marker="^",
            markersize=8,
            markerfacecolor="#ff8a1f",
            markeredgecolor="white",
            markeredgewidth=0.8,
            linestyle="None",
            label="25-100 mm：三角 + 红X",
        ),
    ]
    legend = ax.legend(
        handles=legend_handles,
        loc="lower left",
        frameon=True,
        fontsize=9,
        facecolor="black",
        edgecolor="#aaaaaa",
        labelcolor="white",
    )
    for text in legend.get_texts():
        text.set_color("white")
        if cjk_fp is not None:
            text.set_fontproperties(cjk_fp)

    rf = parse_filename(src_path)
    date_text, time_text = _format_scan_time(attrs)
    site_code = attrs.get("site_code", rf.station if rf else "Unknown")
    task = attrs.get("task", "Unknown")
    elev = rf.elevation_deg if rf else 0.0
    title = "Hail Index"
    info_lines = [
        title,
        f"Date: {date_text}",
        f"Time: {time_text}",
        f"RDA: {site_code}",
        f"Task: {task}",
        f"Elev: {elev:.2f}deg" if isinstance(elev, float) else f"Elev: {elev}",
        f"Max: {max_prob:.1f}%",
    ]
    fig.text(
        0.86,
        0.93,
        "\n".join(info_lines),
        color="white",
        fontsize=11,
        ha="left",
        va="top",
    )
    fig.savefig(str(out_file), facecolor=fig.get_facecolor())


def _render_m_style(data, out_file: Path, src_path: Path) -> None:
    """Render M product using circle markers colored by meso_mxrv (m/s)."""
    attrs = getattr(data, "attrs", {}) or {}

    fig = plt.figure(figsize=(10, 8), facecolor="black")
    ax = fig.add_axes([0.05, 0.06, 0.78, 0.88], projection=ccrs.PlateCarree())
    ax.set_facecolor("black")

    lon_arr = np.asarray(data["longitude"].values if "longitude" in data else [], dtype=float)
    lat_arr = np.asarray(data["latitude"].values if "latitude" in data else [], dtype=float)
    mxrv = np.asarray(data["meso_mxrv"].values if "meso_mxrv" in data else [], dtype=float)

    valid = (
        np.isfinite(lon_arr)
        & np.isfinite(lat_arr)
        & np.isfinite(mxrv)
    ) if lon_arr.size and lat_arr.size and mxrv.size else np.zeros(0, dtype=bool)

    cjk_fp = _pick_cjk_font()
    max_mxrv = 0.0
    norm = Normalize(vmin=0, vmax=100)
    cmap = plt.get_cmap("YlOrRd")
    mappable = ScalarMappable(norm=norm, cmap=cmap)

    fallback_lon = float(np.nanmean(lon_arr)) if lon_arr.size else 0.0
    fallback_lat = float(np.nanmean(lat_arr)) if lat_arr.size else 0.0
    site_lon = _safe_attr_float(attrs, "site_longitude", fallback_lon)
    site_lat = _safe_attr_float(attrs, "site_latitude", fallback_lat)
    extent = _fixed_site_extent(site_lon, site_lat, radius_km=200.0)
    ax.set_extent(extent, crs=ccrs.PlateCarree())

    if valid.size and np.any(valid):
        lon = lon_arr[valid]
        lat = lat_arr[valid]
        rv = mxrv[valid]
        max_mxrv = float(np.max(rv))
        mappable = ax.scatter(
            lon,
            lat,
            marker="o",
            s=95,
            c=rv,
            cmap=cmap,
            norm=norm,
            linewidths=1.0,
            edgecolors="white",
            alpha=0.95,
            transform=ccrs.PlateCarree(),
            zorder=6,
        )
    else:
        ax.text(
            site_lon,
            site_lat,
            "No M Targets",
            color="white",
            fontsize=13,
            ha="center",
            va="center",
            alpha=0.85,
            transform=ccrs.PlateCarree(),
            zorder=7,
        )

    add_shp(
        ax,
        ccrs.PlateCarree(),
        coastline=False,
        style="black",
        extent=ax.get_extent(ccrs.PlateCarree()),
    )
    ax.gridlines(draw_labels=False, color="#3a3a3a", linestyle="--", linewidth=0.5, alpha=0.45)
    ax.set_xticks([])
    ax.set_yticks([])
    if "geo" in ax.spines:
        ax.spines["geo"].set_color("#707070")
        ax.spines["geo"].set_linewidth(0.8)

    cbar = fig.colorbar(mappable, ax=ax, fraction=0.046, pad=0.05)
    if cjk_fp is not None:
        cbar.set_label("最大旋转速度(m/s)", color="white", fontproperties=cjk_fp)
    else:
        cbar.set_label("最大旋转速度(m/s)", color="white")
    cbar.ax.tick_params(colors="white")
    cbar.outline.set_edgecolor("white")

    legend = ax.legend(
        handles=[
            Line2D(
                [],
                [],
                marker="o",
                markersize=8,
                markerfacecolor="#ff8c00",
                markeredgecolor="white",
                linestyle="None",
                label="中尺度旋转点（颜色表示强度）",
            ),
        ],
        loc="lower left",
        frameon=True,
        fontsize=9,
        facecolor="black",
        edgecolor="#aaaaaa",
        labelcolor="white",
    )
    for text in legend.get_texts():
        text.set_color("white")
        if cjk_fp is not None:
            text.set_fontproperties(cjk_fp)

    rf = parse_filename(src_path)
    date_text, time_text = _format_scan_time(attrs)
    site_code = attrs.get("site_code", rf.station if rf else "Unknown")
    task = attrs.get("task", "Unknown")
    elev = rf.elevation_deg if rf else 0.0
    title = "Mesocyclone"
    info_lines = [
        title,
        f"Date: {date_text}",
        f"Time: {time_text}",
        f"RDA: {site_code}",
        f"Task: {task}",
        f"Elev: {elev:.2f}deg" if isinstance(elev, float) else f"Elev: {elev}",
        f"Max: {max_mxrv:.1f}m/s",
    ]
    fig.text(
        0.86,
        0.93,
        "\n".join(info_lines),
        color="white",
        fontsize=11,
        ha="left",
        va="top",
    )
    fig.savefig(str(out_file), facecolor=fig.get_facecolor())


def _to_float(value, default: float = np.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_lonlat_points(raw_points) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not isinstance(raw_points, (list, tuple)):
        return points
    for p in raw_points:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        lon = _to_float(p[0], np.nan)
        lat = _to_float(p[1], np.nan)
        if np.isfinite(lon) and np.isfinite(lat):
            points.append((lon, lat))
    return points


def _render_sti_style(data, out_file: Path, src_path: Path) -> None:
    """Render STI product with history/forecast tracks for all storms."""
    attrs = {}
    storms = []
    if isinstance(data, dict):
        attrs = data.get("attrs") or {}
        storms = data.get("data") or []

    fig = plt.figure(figsize=(10, 8), facecolor="black")
    ax = fig.add_axes([0.05, 0.06, 0.78, 0.88], projection=ccrs.PlateCarree())
    ax.set_facecolor("black")

    cjk_fp = _pick_cjk_font()
    norm = Normalize(vmin=0, vmax=70)
    cmap = plt.get_cmap("turbo")
    mappable = ScalarMappable(norm=norm, cmap=cmap)

    all_lons = []
    all_lats = []
    max_ref_global = 0.0
    for storm in storms:
        if not isinstance(storm, dict):
            continue
        cur = _as_lonlat_points([storm.get("current_position")])
        his = _as_lonlat_points(storm.get("history_position"))
        fct = _as_lonlat_points(storm.get("forecast_position"))
        pts = cur + his + fct
        for lon, lat in pts:
            all_lons.append(lon)
            all_lats.append(lat)
        max_ref_global = max(max_ref_global, _to_float(storm.get("max_ref"), 0.0))

    fallback_lon = float(np.mean(all_lons)) if all_lons else 0.0
    fallback_lat = float(np.mean(all_lats)) if all_lats else 0.0
    site_lon = _safe_attr_float(attrs, "site_longitude", fallback_lon)
    site_lat = _safe_attr_float(attrs, "site_latitude", fallback_lat)
    extent = _fixed_site_extent(site_lon, site_lat, radius_km=200.0)
    ax.set_extent(extent, crs=ccrs.PlateCarree())

    plotted_count = 0
    for storm in storms:
        if not isinstance(storm, dict):
            continue

        ref = _to_float(storm.get("max_ref"), 0.0)
        ref_clip = float(np.clip(ref, 0.0, 70.0))
        color = cmap(norm(ref_clip))

        cur = _as_lonlat_points([storm.get("current_position")])
        his = _as_lonlat_points(storm.get("history_position"))
        fct = _as_lonlat_points(storm.get("forecast_position"))
        cur_pt = cur[0] if cur else None

        if cur_pt is None and not his and not fct:
            continue

        plotted_count += 1

        # 历史路径：实线连接；历史点与当前位置用实心圆。
        if his and cur_pt is not None:
            hx = [p[0] for p in his] + [cur_pt[0]]
            hy = [p[1] for p in his] + [cur_pt[1]]
            ax.plot(
                hx,
                hy,
                linestyle="-",
                linewidth=1.6,
                color=color,
                alpha=0.95,
                transform=ccrs.PlateCarree(),
                zorder=5,
            )
        elif len(his) >= 2:
            ax.plot(
                [p[0] for p in his],
                [p[1] for p in his],
                linestyle="-",
                linewidth=1.6,
                color=color,
                alpha=0.95,
                transform=ccrs.PlateCarree(),
                zorder=5,
            )

        if his:
            ax.scatter(
                [p[0] for p in his],
                [p[1] for p in his],
                marker="o",
                s=42,
                c=[ref_clip] * len(his),
                cmap=cmap,
                norm=norm,
                edgecolors="white",
                linewidths=0.6,
                transform=ccrs.PlateCarree(),
                zorder=6,
            )

        if cur_pt is not None:
            mappable = ax.scatter(
                [cur_pt[0]],
                [cur_pt[1]],
                marker="o",
                s=80,
                c=[ref_clip],
                cmap=cmap,
                norm=norm,
                edgecolors="white",
                linewidths=1.0,
                transform=ccrs.PlateCarree(),
                zorder=7,
            )

        # 未来路径：虚线；未来点为空心圆。
        if fct:
            if cur_pt is not None:
                f_line = [cur_pt] + fct
            else:
                f_line = fct
            if len(f_line) >= 2:
                ax.plot(
                    [p[0] for p in f_line],
                    [p[1] for p in f_line],
                    linestyle="--",
                    linewidth=1.5,
                    color=color,
                    alpha=0.95,
                    transform=ccrs.PlateCarree(),
                    zorder=5,
                )
            ax.scatter(
                [p[0] for p in fct],
                [p[1] for p in fct],
                marker="o",
                s=52,
                facecolors="none",
                edgecolors=[color],
                linewidths=1.4,
                transform=ccrs.PlateCarree(),
                zorder=7,
            )

    if plotted_count == 0:
        ax.text(
            site_lon,
            site_lat,
            "No STI Targets",
            color="white",
            fontsize=13,
            ha="center",
            va="center",
            alpha=0.85,
            transform=ccrs.PlateCarree(),
            zorder=7,
        )

    add_shp(
        ax,
        ccrs.PlateCarree(),
        coastline=False,
        style="black",
        extent=ax.get_extent(ccrs.PlateCarree()),
    )
    ax.gridlines(draw_labels=False, color="#3a3a3a", linestyle="--", linewidth=0.5, alpha=0.45)
    ax.set_xticks([])
    ax.set_yticks([])
    if "geo" in ax.spines:
        ax.spines["geo"].set_color("#707070")
        ax.spines["geo"].set_linewidth(0.8)

    cbar = fig.colorbar(mappable, ax=ax, fraction=0.046, pad=0.05)
    if cjk_fp is not None:
        cbar.set_label("最大反射率(dBZ)", color="white", fontproperties=cjk_fp)
    else:
        cbar.set_label("最大反射率(dBZ)", color="white")
    cbar.ax.tick_params(colors="white")
    cbar.outline.set_edgecolor("white")

    legend = ax.legend(
        handles=[
            Line2D([], [], marker="o", markersize=7, markerfacecolor="#ff8c00", markeredgecolor="white", linestyle="None", label="历史/当前位置（实心圆）"),
            Line2D([], [], marker="o", markersize=7, markerfacecolor="none", markeredgecolor="#ff8c00", linestyle="None", label="预测位置（空心圆）"),
            Line2D([], [], color="#ff8c00", linestyle="-", linewidth=1.6, label="历史路径（实线）"),
            Line2D([], [], color="#ff8c00", linestyle="--", linewidth=1.6, label="未来路径（虚线）"),
        ],
        loc="lower left",
        frameon=True,
        fontsize=9,
        facecolor="black",
        edgecolor="#aaaaaa",
        labelcolor="white",
    )
    for text in legend.get_texts():
        text.set_color("white")
        if cjk_fp is not None:
            text.set_fontproperties(cjk_fp)

    rf = parse_filename(src_path)
    date_text, time_text = _format_scan_time(attrs)
    site_code = attrs.get("site_code", rf.station if rf else "Unknown")
    task = attrs.get("task", "Unknown")
    elev = rf.elevation_deg if rf else 0.0
    sti_count = int(_to_float(attrs.get("sti_count"), plotted_count))
    info_lines = [
        "Storm Track Info",
        f"Date: {date_text}",
        f"Time: {time_text}",
        f"RDA: {site_code}",
        f"Task: {task}",
        f"Elev: {elev:.2f}deg" if isinstance(elev, float) else f"Elev: {elev}",
        f"Count: {sti_count}",
        f"Max: {max_ref_global:.1f}dBZ",
    ]
    fig.text(
        0.86,
        0.93,
        "\n".join(info_lines),
        color="white",
        fontsize=11,
        ha="left",
        va="top",
    )
    fig.savefig(str(out_file), facecolor=fig.get_facecolor())


def _get_vwp_colors(rms_values: np.ndarray) -> list[str]:
    """Map RMS values to VWP barb colors."""
    color_map = [
        (0, "#00FF00"),
        (2, "#FFFF00"),
        (4, "#FF0000"),
        (6, "#00EFFF"),
        (8, "#FF7BFF"),
        (10, "#FFFFFF"),
    ]
    colors: list[str] = []
    for value in rms_values:
        color = color_map[0][1]
        if np.isfinite(value):
            for threshold, candidate in color_map:
                if value > threshold:
                    color = candidate
        colors.append(color)
    return colors


def _render_vwp_style(data, out_file: Path, src_path: Path) -> None:
    """Render VWP product using time-height wind barbs."""
    attrs = getattr(data, "attrs", {}) or {}
    cjk_fp = _pick_cjk_font()

    height_raw = np.asarray(getattr(data, "height", []), dtype=float)
    times_raw = np.asarray(getattr(data, "times", []), dtype=float)
    wind_direction = np.asarray(data["wind_direction"].values if "wind_direction" in data else [], dtype=float)
    wind_speed = np.asarray(data["wind_speed"].values if "wind_speed" in data else [], dtype=float)
    rms = np.asarray(data["rms"].values if "rms" in data else [], dtype=float)

    fig, ax = plt.subplots(1, 1, figsize=(12, 15))
    fig.patch.set_facecolor("black")
    ax.set_facecolor("black")

    if (
        height_raw.size == 0
        or times_raw.size == 0
        or wind_direction.size == 0
        or wind_speed.size == 0
        or rms.size == 0
    ):
        ax.text(0.5, 0.5, "No VWP Data", color="white", fontsize=14, ha="center", va="center", transform=ax.transAxes)
    else:
        height = np.round(height_raw / 1000.0, 1)
        nums = np.arange(1, len(height) + 1, dtype=int)

        times = [datetime.utcfromtimestamp(float(t)).strftime("%H:%M") for t in times_raw]
        u = -wind_speed * np.sin(np.radians(wind_direction))
        v = -wind_speed * np.cos(np.radians(wind_direction))

        max_t = min(len(times), u.shape[0], v.shape[0], rms.shape[0])
        for i in range(max_t):
            colors = _get_vwp_colors(np.asarray(rms[i], dtype=float))
            x = [times[i] for _ in range(len(nums))]
            ax.barbs(
                x,
                nums,
                u[i],
                v[i],
                rounding=False,
                barb_increments=dict(half=2, full=4, flag=20),
                sizes=dict(emptybarb=0.01, spacing=0.23, height=0.5, width=0.25),
                color=colors,
            )

        ax.set_ylim(0.5, len(nums) + 0.5)
        ax.set_yticks(nums)
        ax.set_yticklabels([f"{h:.1f}" for h in height], color="white")
        ax.grid(True, which="both", axis="y", linestyle="--", alpha=0.4)

    ax.set_xlabel("Time(UTC)", color="white")
    if cjk_fp is not None:
        ax.set_ylabel("高度(km)", color="white", fontproperties=cjk_fp)
    else:
        ax.set_ylabel("高度(km)", color="white")
    ax.tick_params(colors="white")

    rf = parse_filename(src_path)
    date_text, time_text = _format_scan_time(attrs)
    site_code = attrs.get("site_code", rf.station if rf else "Unknown")
    task = attrs.get("task", "Unknown")
    info_lines = [
        "Vertical Wind Profile",
        f"Date: {date_text}",
        f"Time: {time_text}",
        f"RDA: {site_code}",
        f"Task: {task}",
    ]
    fig.text(
        0.80,
        0.97,
        "\n".join(info_lines),
        color="white",
        fontsize=11,
        ha="left",
        va="top",
    )

    plt.tight_layout(rect=[0.03, 0.03, 0.78, 0.98])
    fig.savefig(str(out_file), facecolor=fig.get_facecolor())


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
            rf = parse_filename(src)
            if rf is not None and rf.product == "HI":
                _render_hi_style(data, tmp, src)
            elif rf is not None and rf.product == "M":
                _render_m_style(data, tmp, src)
            elif rf is not None and rf.product == "STI":
                _render_sti_style(data, tmp, src)
            elif rf is not None and rf.product == "VWP":
                _render_vwp_style(data, tmp, src)
            else:
                fig = cinrad.visualize.PPI(data, style="black")
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
