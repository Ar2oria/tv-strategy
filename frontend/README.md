# 前端与运行说明

本地多市场股票指标验证系统的浏览器界面：K 线 + 自定义指标可视化、Task 调度管理、热生效数据源配置。

## 环境要求

- Node.js **>= 22.12.0**（`package.json` 的 `engines` 已声明）
- 后端服务运行在同一主机的 `127.0.0.1:8000`（开发模式通过 Vite 代理）

## 开发启动

```bash
# 终端 1：后端（仓库根目录）
backend/.venv/bin/python -m uvicorn app.main:app \
  --app-dir backend --host 127.0.0.1 --port 8000 --workers 1

# 终端 2：前端
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
```

开发模式只允许本地 Vite 代理；后端 `allowed_origins` 默认包含 5173 端口。

## 生产构建与单端口运行

```bash
cd frontend
npm run build        # 产物在 frontend/dist
```

后端启动时会自动挂载 `frontend/dist`（若存在），因此同一个 origin 同时提供 API 与页面：

- `GET /` 与任意客户端路由（`/analysis`、`/tasks`、`/settings/data-sources`）返回 `index.html`
- `GET /assets/*` 返回带哈希的静态资源
- `/api/**` 的 404 始终是 JSON envelope，不会被改写成 `index.html`

挂载目录解析顺序（`AppSettings.resolved_frontend_dist`）：

1. 显式传入的 `frontend_dist`（测试/嵌入用）
2. 环境变量 `STOCK_LAB_FRONTEND_DIST`
3. 仓库相对的 `frontend/dist`——**不依赖进程 CWD**

目录不存在或缺少 `index.html` 时不挂载，保留纯 API 行为。设置 `serve_frontend=False` 可完全关闭静态服务。

## 界面结构

| 路由 | 页面 | 说明 |
|---|---|---|
| `/analysis` | 图表分析 | 图内证券搜索（防抖 300ms）、日/周/月、添加/编辑/移除指标实例、无限左滑加载更早历史 |
| `/tasks` | Task 管理 | Task 列表、Cron/启停/参数配置、立即执行、运行历史与日志；仅活动标签中的活动运行每 2 秒轮询 |
| `/settings/data-sources` | 数据源配置 | 各市场 provider 与请求超时（0–300 秒，不含 0）；每个 Group 默认只读，组内编辑后保存 |
| `/blank` | 空白工作台 | 关闭最后一个标签后的空状态 |

`/settings` 重定向到 `/settings/data-sources`，“系统设置”菜单可展开也可折叠。左侧菜单通过顶部多标签打开页面：同一路径只保留一个标签，重复打开只激活，query/hash 不改变标签身份；非活动页面保持挂载但隐藏。关闭活动标签会激活相邻标签，关闭最后一个标签进入 `/blank`；关闭最后一个分析标签时重置分析会话。隐藏 Task 标签暂停运行历史轮询，重新激活后恢复。

数据源页没有页面底部的统一保存/放弃按钮。每个市场 Group 默认只读，点击组内“编辑”后才允许修改，并在组内显示“放弃”“保存”。保存以最新服务端文档为基准只替换当前 Group，其他 Group 的未保存编辑会保留且不会进入该次 PUT；保存成功后可继续使用新 revision 编辑其他 Group，409 只复位当前保存 Group。

日线 Task 的历史深度、重叠天数、并发数和复权方式均在 Task 自己的动态参数表单中编辑：股票默认 10 年、加密默认全部历史，重叠默认 45 天，并发默认 1（范围 1–8），复权默认 `auto`。Provider 请求始终只尝试一次，不提供自动重试配置。

加密日线 Task 额外维护 `spot_pairs`（`{exchange, symbol}` 默认现货目录）与 `symbols`（本次执行的 canonical ID 临时筛选）。只从 Task `spot_pairs` 注册目录，不读取市场配置兜底；`symbols` 为空时执行全部 `spot_pairs`，两者都为空时不会调用 Provider。旧 `markets.crypto.symbols` 会迁移为 Task `spot_pairs`，Task 显式空数组优先。

页面内容区不再重复显示“Task 管理”“数据源配置”等页面标题。顶部使用连续底边、active 表面和上方圆角的深色原生 Tab，路由与页面缓存行为不变。Task Drawer 与输入、Select 使用 `#202634` 背景，参数面板和数组项仅浅一级为 `#262e40`，边框为中性蓝灰 `#344054`；表单为单栏左对齐 RJSF，最高 640px 响应式宽度，保存与关闭由 RJSF SubmitButton 模板在同一水平操作区渲染。`universe_codes`、`symbols` 等字符串数组使用固定 72px 高度的单个输入框，按英文逗号分隔并自动 trim/忽略空项；`spot_pairs` 等对象数组仍使用逐行编辑，窄屏下对象字段与工具按钮分行并移除多层 gutter，避免输入被压缩。Task/历史表格在卡片内部滚动，移动端不会撑出整页。

### 指标实例

- 同一指标可添加多个实例，每个实例有独立 UUID `instance_id`，参数互不影响。
- 参数表单由后端 `params_schema` 生成（RJSF + AJV），新增后端指标不需要改前端。
- 参数编辑防抖 350ms 后批量提交 `POST /api/v1/indicators/compute`。
- 单个指标失败只在它自己的卡片和图表提示条里显示，K 线与其它指标保持可用。
- 实例删除是本地状态变更，不会触发新的计算请求。
- 切换到 Task／设置页再返回时，证券、日／周／月、指标实例与显隐状态由 `AnalysisSessionProvider` 保留；K 线与计算结果按需重新获取，不缓存大型历史数组或临时弹窗状态。

### 图表约定

- Lightweight Charts 5.2：`chart.addSeries(...)`、数字 pane 索引、`createSeriesMarkers(...)`；不使用 v4 API。
- 证券、日/周/月与「添加指标」控件位于图表边框内的顶部工具栏；未选证券、空库、加载中和请求失败时工具栏仍保持可用。
- 画布保留响应式基础高度；主图指标不增加固定高度。副图不超过 2 个时按各自 `pane.height` 扩展，超过 2 个后总高度固定为恰好 2 个副图时的高度，所有副图统一按前两个平均高度的 `0.8^(n-2)` 缩小并取整，主图使用剩余空间。
- OHLC、涨幅（`C/O-1`）、振幅（`H/L-1`）、成交量、主图指标以及隐藏/失败卡片位于正常文档流的主图信息区；副图指标卡片放在对应副图顶部，并为卡片预留 40px，避免遮挡该副图曲线；副图缩小到 40px 以下时卡片按比例缩放，避免相邻卡片重叠。
- 日／周／月切换时保留最近一次有效副图布局，加载状态不会先把副图高度归零；隐藏或删除仍收回对应副图空间。
- 主图共用 pane 0（蜡烛 + 成交量），每个副图按请求顺序新建 pane；移除指标时先删序列再按最高索引递减删 pane，蜡烛序列始终保留。
- 主图右侧显示 K 线价格坐标；副图使用独立可见价格轴、40px 顶部卡片空间与 10% 下边距，主图蜡烛/成交量专用边距不会泄漏到 RSI 等副图。
- 主图与副图之间的 1px 分隔线使用 `#5f6b7d`（对深色背景对比度 3.31:1），悬停为 `#2962ff`；容器 resize 与结构更新后通过 `setStretchFactor` 按实际可用高度精确分配各 pane，避免多个副图互相挤压。
- 指标 `null` 值渲染为 whitespace（断开线段），NaN/Infinity、重复或非递增日期、marker 日期不在 K 线内、marker 指向未知序列都在渲染前拒绝并提示。
- 应用仅使用深色主题，品牌与三个功能入口位于左侧栏；图表表面为 `#131722`，涨跌配色为 `#f23645` / `#089981`，已通过 dataviz 在亮暗背景下的 CVD 分离度（ΔE 11.1）与对比度（≥3:1）校验；工具提示同时给出文字方向说明。
- 图表外有隐藏的「图表数据摘要」区域（K 线数量、每个指标的点数与标记数），供屏幕阅读器与 E2E 断言使用，不使用测试专用后端行为。

## 测试

```bash
cd frontend
npm test                 # Vitest 单元/组件测试
npm run test:coverage    # V8 覆盖率，四项阈值均 ≥80%
npm run build            # tsc --noEmit && vite build
npm run e2e              # Playwright（会先 build，再 vite preview）
```

- 单元测试默认不访问公网；`src/api` 的测试全部使用 `fetch` 桩。
- E2E 用 `e2e/fixtures.ts` 的确定性路由桩，不连接真实后端或行情源。
- 首次运行 E2E 需要 `npx playwright install chromium`。

## 运维要点

- **只跑一个 Uvicorn worker**：调度器与内存限流按单进程设计，多 worker 会重复触发 Task。
- **数据源配置从前端设置页修改**；保存时带 `expected_revision`，409 会重新拉取最新值并要求用户确认，不会静默覆盖其他页面的修改。历史、重叠、并发、复权及加密现货目录请在对应日线 Task 的参数表单中修改，不要写回市场配置。
- **自定义指标**：在 `backend/app/indicators/custom/` 新增 `Indicator` 子类并用 `@register_indicator` 注册，重启后端后自动出现在指标选择器里。
- **全量同步安全**：Task 同步按证券粒度提交，单票失败不影响其它证券并记为 `partial`；前复权重叠比对发现变化时整票重新下载并在单事务内替换，下载失败保留旧数据。
- **小样本验收**：先手动运行一次证券列表与日线同步 Task，挑每个市场一只标的核对日/周/月 K 线与两个内置指标，再验证一次设置保存与一次 Task 立即执行及日志。不等待全市场下载完成。

## 已知限制

- 第一版只做图表直观验证：没有回测、绩效统计、分钟线、实时推送。
- 指标代码修改需重启后端生效；前端不支持编辑/执行 Python。
- 上游免费行情源无 SLA；失败会以真实失败呈现，不做替代源伪装或地区绕过。
