# 雷达 PUP 产品浏览器

基于 Flask + cinrad 的网页版雷达 L3 PUP 产品浏览器。

- 选择 **站号 / 产品 / 日期** 后，自动列出该组合下所有时次（带仰角的产品还会列出仰角）。
- 主图为 cinrad 渲染出来的 PPI 图，所有 PNG 落盘缓存。
- **方向键导航**：← → 切换时次，↑ ↓ 切换仰角，空格播放/暂停，Home/End 跳到首/末帧。
- **邻近预渲染**：每次切换帧时，后端会按"时间距离 + 仰角距离"的优先级，把附近的帧排进后台渲染队列，所以连续浏览基本是秒切。

## 目录结构

```
draw_pup_web/
├── app.py                  # Flask 入口 + 路由
├── config.py               # 数据根目录、缓存目录等配置
├── draw_pup.py             # 原始 cinrad 调用示例（保留）
├── requirements.txt
├── radar/
│   ├── parser.py           # 文件名解析
│   ├── scanner.py          # 目录扫描 + TTL 缓存
│   ├── renderer.py         # cinrad 渲染 + PNG 落盘缓存
│   └── prerender.py        # 后台预渲染队列（单线程 worker）
├── templates/index.html
└── static/
    ├── css/style.css
    ├── js/app.js
    └── cache/              # 渲染好的 PNG（自动生成）
```

## 安装与启动

```powershell
pip install -r requirements.txt
python app.py
```

默认监听 `http://127.0.0.1:5000`。

> 注：cinrad 在 Windows 上通常需要预先装好 `cartopy` 等依赖。本项目假设你
> 已经能跑通 `draw_pup.py`，环境就绪。

## 数据目录约定

```
<DATA_ROOT>/<year>/<yyyymmdd>/<station>/<product>/<filename>.bin
```

文件名约定（按下划线切分）：

```
Z_RADR_I_<station>_<datetime>_P_DOR_CC_<product>_<resolution>_<range>_<elev>_FMT.bin
  0  1   2    3        4      5  6   7    8          9          10     11
```

`<elev>` 为 `NUL` 时表示无仰角产品（CR/ET/VIL 等）；否则是以 **0.1°** 为单位
的整数（`5` ⇒ 0.5°，`15` ⇒ 1.5°）。

如需调整数据根目录，修改 `config.py` 中的 `DATA_ROOT`。

## REST API

| 路径 | 说明 |
|---|---|
| `GET /api/stations` | 列出所有站号 |
| `GET /api/dates?station=X` | 该站所有可用日期 |
| `GET /api/products?station=X&date=Y` | 该日产品列表 |
| `GET /api/files?station=X&date=Y&product=Z` | 完整帧列表（含时间轴、仰角列表、缓存状态） |
| `GET /api/render?path=...` | 同步渲染单文件，返回 `{ok, url}` |
| `POST /api/prerender` body `{items:[{path, priority}], replace:true}` | 批量提交后台预渲染（默认替换队列） |
| `GET /api/cache-status?path=A&path=B` | 查询若干文件是否已缓存 |

## 工程要点

- **渲染串行化**：matplotlib/cinrad 不是线程安全的，所有渲染（用户请求 +
  后台预渲染）共用一把进程级锁，避免并发崩溃。如要真正并发，可在
  `prerender.py` 中改用 `multiprocessing.Pool`。
- **缓存键**：`{文件名}_{md5(path)[:16]}.png`，相同 bin 文件永远命中同一份
  PNG。
- **预渲染优先级**：`|Δt| * 10 + |Δe| * 30`，时间方向距离权重低于仰角，
  优先把"沿时间轴"的邻近帧渲染好（用户更常按 ← → 浏览）。
- **目录扫描 TTL**：60 秒，避免每次请求都 `listdir` 慢盘 / 网络盘。
- **替换式队列**：用户每次切换帧都会重提一份邻近列表，旧的待渲染条目会
  被丢弃，避免越积越多的过时任务挤占 worker。

## 可能的后续增强

- 多帧导出为 GIF / MP4。
- 同一时刻并排显示多个产品（R + V + CR 三联屏）。
- 鼠标悬停在主图上显示该点经纬度 + 数值。
- 整日批量预渲染（一次性把当日所有时次/仰角排满队列）。
