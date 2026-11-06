# 前端与运行说明

本地多市场股票指标验证系统的浏览器界面：K 线 + 自定义指标可视化、Task 调度管理、热生效系统设置。

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

- `GET /` 与任意客户端路由（`/analysis`、`/tasks`、`/settings`）返回 `index.html`
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
| `/analysis` | 图表分析 | 选证券（搜索防抖 300ms）、日/周/月、日期区间（默认最近两年）、添加/编辑/移除指标实例 |
| `/tasks` | Task 管理 | Task 列表、Cron/启停/参数配置、立即执行、运行历史与日志、运行中自动轮询（2s） |
| `/settings` | 系统设置 | 分市场 provider/历史深度/超时/重试/重叠天数、加密现货交易对、全局时区与指标上限 |

### 指标实例

- 同一指标可添加多个实例，每个实例有独立 UUID `instance_id`，参数互不影响。
- 参数表单由后端 `params_schema` 生成（RJSF + AJV），新增后端指标不需要改前端。
- 参数编辑防抖 350ms 后批量提交 `POST /api/v1/indicators/compute`。
- 单个指标失败只在它自己的卡片和图表提示条里显示，K 线与其它指标保持可用。
- 实例删除是本地状态变更，不会触发新的计算请求。

### 图表约定

- Lightweight Charts 5.2：`chart.addSeries(...)`、数字 pane 索引、`createSeriesMarkers(...)`；不使用 v4 API。
- 主图共用 pane 0（蜡烛 + 成交量），每个副图按请求顺序新建 pane；移除指标时先删序列再按最高索引递减删 pane，蜡烛序列始终保留。
- 指标 `null` 值渲染为 whitespace（断开线段），NaN/Infinity、重复或非递增日期、marker 日期不在 K 线内、marker 指向未知序列都在渲染前拒绝并提示。
- 涨跌配色为 `#d84949` / `#008300`，已用 dataviz 校验器确认在浅色与深色背景下 CVD 可分离度（ΔE 8.3）与对比度（≥3:1）达标；工具提示同时给出文字方向说明。
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
- **配置只从前端设置页修改**；保存时带 `expected_revision`，409 会重新拉取最新值并要求用户确认，不会静默覆盖其他页面的修改。
- **自定义指标**：在 `backend/app/indicators/custom/` 新增 `Indicator` 子类并用 `@register_indicator` 注册，重启后端后自动出现在指标选择器里。
- **全量同步安全**：Task 同步按证券粒度提交，单票失败不影响其它证券并记为 `partial`；前复权重叠比对发现变化时整票重新下载并在单事务内替换，下载失败保留旧数据。
- **小样本验收**：先手动运行一次证券列表与日线同步 Task，挑每个市场一只标的核对日/周/月 K 线与两个内置指标，再验证一次设置保存与一次 Task 立即执行及日志。不等待全市场下载完成。

## 已知限制

- 第一版只做图表直观验证：没有回测、绩效统计、分钟线、实时推送。
- 指标代码修改需重启后端生效；前端不支持编辑/执行 Python。
- 上游免费行情源无 SLA；失败会以真实失败呈现，不做替代源伪装或地区绕过。
