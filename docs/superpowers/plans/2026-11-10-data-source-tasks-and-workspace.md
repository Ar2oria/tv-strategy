# 数据源参数、Task 同步参数与多标签工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将市场数据源配置与日线 Task 同步参数分离，移除自动重试，并用保留页面状态的多标签工作台承载分析、Task 和数据源设置。

**Architecture:** 后端在读取旧配置时把历史、重叠和并发值迁入对应日线 Task，再用不可变 Task 同步选项驱动单次下载和有界并发。前端保留 RJSF 动态表单与数据源热更新，AppShell 缓存各路由首次创建的 outlet，通过 pathname 标签复用页面实例，关闭最后标签进入 `/blank`。

**Tech Stack:** Python 3.13、Pydantic、FastAPI、asyncio、SQLite、React 19、TypeScript、React Router、Ant Design、Lightweight Charts、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-11-10-data-source-tasks-and-workspace-design.md`

## Global Constraints

- `MarketSettings` 仅保留 `provider`、`symbols`、`request_timeout_seconds`；`schema_version=1` 和现有 revision 不因读取迁移而增加。
- `request_timeout_seconds` 继续支持前端按市场编辑，范围为正数且不超过 300 秒。
- `max_retries` 废弃；所有 provider 调用最多尝试一次，限流与不可用仍返回真实错误。
- 日线 Task 新增 `history_years`、`overlap_days`、`concurrency`、`adjustment`；股票默认 10 年，加密默认全部历史，重叠默认 45 天，并发默认 1（1–8），复权默认 `auto`。
- 旧市场值只迁入未显式设置同名参数的对应日线 Task；Task 已有值优先。
- 数据源页面只保留 provider、timeout 和加密货币交易对；子路由为 `/settings/data-sources`。
- 标签仅以 `location.pathname` 为 key，页面保持挂载；关闭最后一个标签进入 `/blank`，并重置分析会话。
- 保持不可变配置快照与状态更新，复用现有 RJSF、ProviderRegistry 和 ResizeObserver，不引入新状态管理库。
- 沿用当前 `main` 工作区，不自动 commit/push，不修改用户的 `python_validation/`、`reports/`、`tests/`、`volatility_markers/` 研究目录。

## Review Focus

- 旧市场自定义历史／重叠值与 Task 已有参数冲突时，必须保留 Task 值——Task 1 的迁移优先级测试。
- 限流、不可用或带 Retry-After 的响应只能调用 provider 一次——Task 2 的单次请求测试。
- `adjustment=auto` 对普通股票、指数、加密现货的解析，以及显式 `qfq/none` 的元数据校验——Task 3 的复权矩阵测试。
- 并发大于 1 时的实际上限、单票失败隔离和原证券顺序汇总——Task 4 的并发测试。
- 同一路径重复打开不重建页面，关闭活动标签与最后一个标签后不得自动重开首页——Task 6 的 Workspace 测试。
- 已移除设置字段不能通过运行时 decoder 或被前端整文档保存带回——Task 5 的 API 与保存测试。

---

### Task 1: 精简市场配置并迁移旧值

**Files:**
- Modify: `backend/app/config/models.py`
- Modify: `backend/app/config/store.py`
- Create: `backend/app/config/migrations.py`
- Test: `backend/tests/config/test_market_schema.py`
- Test: `backend/tests/config/test_store.py`

**Interfaces:**
- Consumes: 当前 `Settings`、`MarketSettings`、TaskSettings 与 JSON 配置。
- Produces: `migrate_legacy_settings_document(document: dict) -> dict`，在模型校验前返回精简且已迁移 Task params 的新字典；不修改输入对象。

- [ ] **Step 1: 写配置模型与迁移失败测试**

覆盖：删除字段被模型拒绝；旧市场 `history_years=4`、`overlap_days=90`、`concurrency=2` 迁入对应日线 Task；Task 已有值优先；`max_retries` 不迁移；revision 和 `schema_version=1` 不变；输入字典未被修改。

- [ ] **Step 2: 运行测试确认失败**

Run: `backend/.venv/bin/python -m pytest backend/tests/config/test_market_schema.py backend/tests/config/test_store.py -q`
Expected: FAIL，旧字段仍存在且没有迁移函数。

- [ ] **Step 3: 实现精简模型和纯迁移函数**

`MarketSettings` 仅保留 provider、symbols、timeout。`migrations.py` 按固定市场到 Task 映射复制缺失的历史、重叠、并发参数，再删除市场废弃字段；`ConfigService._read_settings` 在 `Settings.model_validate` 前调用它。

- [ ] **Step 4: 运行迁移与配置测试确认通过**

Run: 同 Step 2。
Expected: 全部 PASS，旧文件可读取且新保存结构不含废弃字段。

- [ ] **Step 5: 检查本任务差异并记录，不提交**

Run: `git diff --check && git diff -- backend/app/config backend/tests/config`
Expected: 仅包含精简模型、读取迁移和对应测试，无空白错误或提交。

---

### Task 2: 删除自动重试

**Files:**
- Modify: `backend/app/services/bar_sync_service.py`
- Modify: `backend/app/providers/retry.py`（仅在失去诊断用途时删除）
- Test: `backend/tests/services/test_bar_sync_service.py`
- Test: `backend/tests/providers/test_retry_and_content_type.py`

**Interfaces:**
- Consumes: Task 1 的精简 `MarketSettings`，只含 provider/symbols/timeout。
- Produces: `BarSyncService._fetch(...)` 单次调用语义；ProviderRateLimited/Retry-After 仅作为诊断，不触发等待或第二次调用。

- [ ] **Step 1: 把重试测试改为单次调用测试**

对 `ProviderUnavailable`、`ProviderRateLimited` 和带 Retry-After 的错误断言 provider 调用次数恰好为 1， sleep 不再被调用；非重试错误行为不变。

- [ ] **Step 2: 运行测试确认旧逻辑失败**

Run: `backend/.venv/bin/python -m pytest backend/tests/services/test_bar_sync_service.py backend/tests/providers/test_retry_and_content_type.py -q`
Expected: FAIL，旧实现仍按 max_retries 多次调用。

- [ ] **Step 3: 实现单次 `_fetch`**

删除重试循环、指数退避常量、 `_retry_delay` 和仅为重试注入的 sleep 参数；每次只执行一次 provider.fetch_daily 并做原有数据校验。诊断字段可保留，但不用于调度。

- [ ] **Step 4: 运行单次调用测试**

Run: 同 Step 2。
Expected: 全部 PASS，所有错误路径最多一次 provider 调用。

- [ ] **Step 5: 全后端回归并记录，不提交**

Run: `backend/.venv/bin/python -m pytest backend -q`
Expected: 全部通过；若有仍依赖重试的测试或调用点，先按同一语义修正再完成。

---

### Task 3: 将历史、重叠和复权纳入 Task 参数

**Files:**
- Modify: `backend/app/tasks/builtin/sync_daily.py`
- Modify: `backend/app/services/bar_sync_service.py`
- Test: `backend/tests/tasks/test_market_sync_tasks.py`
- Test: `backend/tests/services/test_bar_sync_service.py`
- Test: `backend/tests/tasks/test_registry.py`

**Interfaces:**
- Consumes: Task 2 的单次 `_fetch`。
- Produces: `DailySyncParams(history_years, overlap_days, concurrency, adjustment)`；`BarSyncOptions(history_years, overlap_days, adjustment)` 不可变对象；`auto` 对普通股票解析为 qfq，对指数/加密现货解析为 none。

- [ ] **Step 1: 写参数默认值、边界和复权矩阵失败测试**

覆盖空参数默认股票 10 年／加密全部、45 天、1 并发、auto；history_years 正整数或 null；overlap 1–366；concurrency 1–8；显式 qfq/none；非法 adjustment 被拒绝；schema 出现在四个 Task descriptor 中。

- [ ] **Step 2: 运行测试确认失败**

Run: `backend/.venv/bin/python -m pytest backend/tests/tasks/test_registry.py backend/tests/tasks/test_market_sync_tasks.py backend/tests/services/test_bar_sync_service.py -q`
Expected: FAIL，新字段和选项对象尚不存在。

- [ ] **Step 3: 实现参数模型与同步选项传递**

扩展 `DailySyncParams`，用不可变 `BarSyncOptions` 向服务传值；历史、重叠和复权不再从 MarketSettings 读取。空 Task params 使用市场默认值，配置快照和运行历史保留完整参数。

- [ ] **Step 4: 运行参数与复权测试**

Run: 同 Step 2。
Expected: 全部 PASS，四个 Task 使用同一套动态 schema。

- [ ] **Step 5: 检查接口差异并记录，不提交**

Run: `git diff --check && git diff -- backend/app/tasks/builtin/sync_daily.py backend/app/services/bar_sync_service.py`
Expected: 参数和选项签名一致，无旧 MarketSettings 字段读取。

---

### Task 4: 为日线 Task 增加有界并发

**Files:**
- Modify: `backend/app/tasks/builtin/sync_daily.py`
- Create: `backend/tests/tasks/test_daily_sync_concurrency.py`

**Interfaces:**
- Consumes: Task 3 的 `DailySyncParams.concurrency` 与同步选项。
- Produces: 单 Task 内 `asyncio.Semaphore(concurrency)` 有界执行，完成顺序记录日志、原证券顺序聚合结果。

- [ ] **Step 1: 写并发上限、失败隔离和结果顺序测试**

用受控 provider 记录同时活跃下载数：concurrency=3 时峰值不超过 3；一票限流不影响其他票成功；默认 1 保持顺序；最终 details 按原证券顺序汇总，进度最终为 100。

- [ ] **Step 2: 运行测试确认失败**

Run: `backend/.venv/bin/python -m pytest backend/tests/tasks/test_daily_sync_concurrency.py -q`
Expected: FAIL，当前为逐票串行，无法验证 Semaphore 行为。

- [ ] **Step 3: 实现 Semaphore 限流与不可变结果聚合**

为每个证券创建受 Semaphore 控制的协程，按完成顺序写日志和进度，将结果连同原索引聚合，避免共享可变计数器；每票仍独立事务和缓存失效。

- [ ] **Step 4: 运行并发与全部市场同步测试**

Run: `backend/.venv/bin/python -m pytest backend/tests/tasks/test_daily_sync_concurrency.py backend/tests/tasks/test_market_sync_tasks.py backend/tests/tasks/test_market_sync_final.py -q`
Expected: 全部 PASS，无跨票事务或重复统计。

- [ ] **Step 5: 全后端回归并记录，不提交**

Run: `backend/.venv/bin/python -m pytest backend -q`
Expected: 全部通过，无重试和并发相关遗留失败。

---

### Task 5: 精简前端数据源配置并加入子路由

**Files:**
- Modify: `frontend/src/types/settings.ts`
- Modify: `frontend/src/api/decoders/settings.ts`
- Modify: `frontend/src/features/settings/MarketSettingsForm.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/router.tsx`
- Test: `frontend/src/features/settings/SettingsPage.test.tsx`
- Test: `frontend/src/api/endpoints.test.ts`

**Interfaces:**
- Consumes: Task 1 的精简后端 Settings DTO 和 Task 3 的动态 Task params schema。
- Produces: 仅 provider/timeout/crypto symbols 的前端 MarketSettings 与 `/settings/data-sources` 页面；`/settings` 重定向到该路由。

- [ ] **Step 1: 写 decoder、页面和路由失败测试**

断言旧 history_years/overlap_days/concurrency/max_retries 不进入 draft 或保存 payload；每市场可编辑 provider/timeout；加密交易对可编辑；全局时区和指标上限不再展示；`/settings` 与 `/settings/data-sources` 均展示“数据源配置”。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run src/features/settings/SettingsPage.test.tsx src/api/endpoints.test.ts src/App.test.tsx`
Expected: FAIL，旧字段和全局卡片仍存在，子路由未定义。

- [ ] **Step 3: 精简类型、decoder 和表单并添加路由**

移除旧字段，保留全文档中未修改的 timezone/indicators/tasks 字段以便后端兼容；SettingsPage 标题改为“数据源配置”，添加 `/settings/data-sources` 与 `/settings` 重定向。

- [ ] **Step 4: 运行设置与 API 测试**

Run: 同 Step 2。
Expected: 全部 PASS，保存只发送精简市场字段，未修改的全局文档部分保持不变。

- [ ] **Step 5: 检查前端差异并记录，不提交**

Run: `git diff --check && git diff -- frontend/src/types/settings.ts frontend/src/api/decoders/settings.ts frontend/src/features/settings frontend/src/router.tsx`
Expected: 类型、decoder、表单和路由一致，无废弃字段。

---

### Task 6: 实现保留页面状态的多标签工作台

**Files:**
- Create: `frontend/src/features/workspace/useWorkspaceTabs.ts`
- Create: `frontend/src/features/workspace/Workspace.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/features/analysis/AnalysisSession.tsx`（如需要重置接口）
- Test: `frontend/src/App.test.tsx`
- Create: `frontend/src/features/workspace/useWorkspaceTabs.test.tsx`
- Test: `frontend/e2e/analysis.spec.ts`
- Create: `frontend/e2e/workspace.spec.ts`

**Interfaces:**
- Consumes: Task 5 的路由、现有 AnalysisSessionProvider、useOutlet、各页面组件和 React Router 导航。
- Produces: `WorkspaceTab { key: pathname, title, content: ReactNode }`；重复 key 只激活；关闭活动标签选择相邻项，最后关闭进入 `/blank`；分析 Provider 在最后分析标签关闭后重置。

- [ ] **Step 1: 写标签状态与浏览器失败测试**

单元覆盖首次追加、重复激活不追加、关闭活动/非活动标签、最后关闭 `/blank`、query/hash 不改变 key、Provider 重置。E2E 覆盖分析状态保留、Task 标签保留、关闭后状态卸载、直接 URL 和前进后退。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend test -- --run src/App.test.tsx src/features/workspace/useWorkspaceTabs.test.tsx && npm --prefix frontend run e2e -- --grep 'workspace tabs'`
Expected: FAIL，当前 Outlet 切换卸载页面且没有空白工作台。

- [ ] **Step 3: 实现 Workspace 和标签管理**

AppShell 使用 `useOutlet` 缓存首次页面内容；Workspace 自行渲染标签按钮与隐藏的页面 section，不使用会卸载内容的 Tabs children。菜单“系统设置”下提供“数据源配置”；最后分析标签关闭时通过 Provider key 重置会话。

- [ ] **Step 4: 运行单元与 Workspace E2E 测试**

Run: 同 Step 2。
Expected: 全部 PASS；隐藏时 0 尺寸被忽略，重新显示后图表 resize 正常，Task 轮询仅在对应标签卸载后停止。

- [ ] **Step 5: 全前端回归并记录，不提交**

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run e2e`
Expected: 全部通过，无既有分析、Task 或设置回归。

---

### Task 7: 文档、全量门禁与独立审查

**Files:**
- Modify: `frontend/README.md`
- Modify: `backend/README.md`
- Modify: `docs/superpowers/HANDOFF-2026-11-06.md`（仅追加本轮说明，不改写历史记录）

**Interfaces:**
- Consumes: Tasks 1–6 的实现与测试证据。
- Produces: 可复现的配置迁移说明、启动方式、Task 参数说明和多标签使用说明。

- [ ] **Step 1: 更新文档**

记录旧值迁移优先级、单次请求、Task 参数默认值、并发/复权、数据源子路由、标签关闭与 `/blank` 行为；不自动提交。

- [ ] **Step 2: 运行后端完整门禁**

Run: `backend/.venv/bin/python -m pytest backend --cov=app --cov-report=term-missing -q`
Expected: 全部通过，覆盖率不低于 80%。

- [ ] **Step 3: 运行前端完整门禁**

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run test:coverage && npm --prefix frontend run build && npm --prefix frontend run e2e`
Expected: 全部通过，覆盖率各项不低于 80%，TypeScript 与 Vite 构建成功。

- [ ] **Step 4: 真实本地验收**

保持后端 `127.0.0.1:8000`、前端 `127.0.0.1:5173`，验证数据源编辑、Task 参数、单次限流失败、重复打开、状态保留、关闭最后标签和浏览器控制台。

- [ ] **Step 5: 独立审查与最后差异检查**

调用 code-reviewer 检查完整 diff；Critical/Important 先写失败测试再修复并重跑门禁。最后运行 `git diff --check` 与 `git status --short`，不 commit/push。
