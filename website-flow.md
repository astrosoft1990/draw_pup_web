# 网站流程图

## 用户浏览与渲染流程

```mermaid
flowchart TD
  A[用户打开首页 /] --> B[Flask 渲染 templates/index.html]
  B --> C[加载 static/js/app.js]
  C --> D[初始化页面与绑定事件]
  D --> E[请求 GET /api/stations]
  E --> F{是否有站点}
  F -- 无且索引刷新中 --> E2[3 秒后轮询站点]
  E2 --> E
  F -- 无 --> X[显示无站点/错误状态]
  F -- 有 --> G[用户选择站点]
  G --> H[请求 GET /api/dates?station]
  H --> I{是否有日期}
  I -- 无且索引刷新中 --> H2[3 秒后轮询日期]
  H2 --> H
  I -- 无 --> X2[显示该站点无日期]
  I -- 有 --> J[设置日期范围并默认选最新日期]
  J --> K[请求 GET /api/products?station&date]
  K --> L[填充产品下拉框]
  L --> M[用户选择产品]
  M --> N[请求 GET /api/files?station&date&product]
  N --> O{是否有帧文件}
  O -- 无 --> X3[显示无可用文件]
  O -- 有 --> P[构建时间轴 times]
  P --> Q[构建仰角列表 elevations]
  Q --> R[构建帧矩阵 matrix time/elevation -> file]
  R --> S[显示当前帧]
  S --> T[请求 GET /api/render?path]
  T --> U[后端校验 path 是否在 DATA_ROOT 内]
  U --> V{缓存 PNG 是否存在}
  V -- 不存在 --> W[cinrad/matplotlib 渲染 bin 为 PNG]
  V -- 存在 --> Y[返回缓存图片 URL]
  W --> Y
  Y --> Z[前端显示雷达图]
  Z --> AA[提交邻近帧 POST /api/prerender]
  AA --> AB[后台预渲染队列按优先级渲染]
  AB --> AC[前端轮询 GET /api/cache-status]
  AC --> AD[标记时间轴/仰角按钮缓存状态]
  Z --> AE{用户操作}
  AE -- 点击时间轴/方向键左右 --> S
  AE -- 点击仰角/方向键上下 --> S
  AE -- 播放/空格 --> AF[每 350ms 切换下一时间帧]
  AF --> S
  AE -- Home/End --> AG[跳到首帧/末帧]
  AG --> S
  M --> AH[启动产品文件自动刷新]
  AH --> AI[每 5 分钟重新请求 /api/files]
  AI --> AJ{文件列表是否变化}
  AJ -- 否 --> AH
  AJ -- 是 --> AK[重建时间轴/仰角/矩阵并跳到最新帧]
  AK --> S
```

## 流程说明

1. 用户打开首页 `/`，Flask 返回 `templates/index.html`，浏览器加载 `static/js/app.js`。
2. 前端依次请求站点、日期、产品和文件列表 API，形成可浏览的时间轴、仰角列表和帧矩阵。
3. 用户选择或切换帧时，前端请求 `/api/render?path=...`，后端校验路径并把 bin 文件渲染为缓存 PNG。
4. 前端显示 `/cache/<png>` 图片，同时提交邻近帧到 `/api/prerender` 做后台预渲染。
5. 播放、键盘切换、时间轴点击和仰角切换都会回到“选择当前帧 -> 渲染/读取缓存 -> 显示图片”的循环。
6. 选择产品后，前端每 5 分钟刷新一次文件列表；发现新文件时自动重建列表并跳到最新帧。
