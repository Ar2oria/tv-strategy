# 加密交易对 Task 化与工作台表单视觉整理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将加密现货目录和手动筛选完全归入 crypto Task，移除市场级交易对，并完成无页面重复标题、深色 Tab 和可读的单栏 Task 参数表单。

**Architecture:** 先用 `CryptoDailySyncParams.spot_pairs` 切换执行语义，再精简 MarketSettings 并在读取旧文档时迁移目录。前端继续复用动态 RJSF，通过 `formContext` 强制单栏左对齐；Workspace 只调整原生 Tab 外观，不改变页面缓存和 Provider 生命周期。

**Tech Stack:** Python 3.13、Pydantic、FastAPI、asyncio、React 19、TypeScript、RJSF/AntD 6、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-11-11-crypto-task-params-and-workspace-polish-design.md`

## Global Constraints

- `MarketSettings` 最终只含 `provider`、`request_timeout_seconds`；不得从市场配置读取交易对兜底。
- 仅 `market.sync_crypto_daily` 新增 `spot_pairs: tuple[CryptoSymbol, ...]`；现有 `symbols` 保留为 canonical ID 临时筛选。
- `spot_pairs` 与 `symbols` 都为空时 Provider 调用数必须为 0；显式空 `spot_pairs` 在迁移和 run override 中均优先。
- 迁移保持输入不可变、`schema_version=1` 和 revision 不变；Task 已有 `spot_pairs` 键（包括 `[]`）优先。
- 标签继续使用原生 `button role="tab"`、pathname key 和缓存页面，不引入 AntD Tabs，不改变 `/blank` 和分析会话重置。
- RJSF Task 表单使用 `labelAlign="left"`、`colSpan=24`；Drawer 最大 640px 且不超过 100vw，桌面和移动端无横向溢出。
- 沿用当前 `main` 工作区，不自动 commit/push，不修改研究目录；默认测试离线，后端一个 Uvicorn worker。

## Review Focus

- 显式 `spot_pairs=[]` 覆盖默认目录且 symbols 为空时不得访问 Provider——Task 1 空目录测试。
- 旧市场有交易对、Task 显式 `spot_pairs=[]` 时不得被迁移重新填充——Task 2 优先级测试。
- 旧 API 的 `markets.*.symbols` 不得经 decoder/draft/整文档 PUT 带回——Task 3 边界测试。
- 数组对象、nullable anyOf 与窄屏不得造成标签混排或 Drawer 横向溢出——Task 4 组件/E2E。
- 视觉调整不得重挂载其他页面或改变关闭标签行为——Task 5 全量 Workspace 回归。

---

### Task 1: 将 crypto 目录和执行选择切换到 Task 参数

**Files:**
- Modify: `backend/app/tasks/builtin/sync_daily.py`
- Test: `backend/tests/tasks/test_market_sync_tasks.py`
- Test: `backend/tests/tasks/test_registry.py`
- Test: `backend/tests/config/test_crypto_symbol_validation.py`

**Interfaces:**
- Consumes: 现有 `DailySyncParams`、`CryptoSymbol`、`run_daily_sync`、InstrumentRepository 和 ProviderRegistry。
- Produces: `CryptoDailySyncParams(DailySyncParams).spot_pairs: tuple[CryptoSymbol, ...]`；`CryptoDailySyncTask.params_model` 指向子类；执行只从 Task params 获取目录。

- [ ] **Step 1: 写 schema、执行和空目录失败测试**

覆盖：仅 crypto descriptor 出现 `spot_pairs`；Task spot_pairs 注册两个交易所的证券而市场 symbols 被忽略；空 spot_pairs+空 symbols 即使旧市场有交易对也抛出 `DEFAULT_UNIVERSE_ERROR` 且同步调用为 0；spot_pairs 为空时显式 symbols 只选择本地 active canonical ID，未知项失败且不访问 Provider；非法 pair 由 `CryptoDailySyncParams` 拒绝。

- [ ] **Step 2: 运行测试确认旧实现失败**

Run: `backend/.venv/bin/python -m pytest backend/tests/tasks/test_registry.py backend/tests/tasks/test_market_sync_tasks.py backend/tests/config/test_crypto_symbol_validation.py -q`
Expected: FAIL，`CryptoDailySyncParams` 不存在且执行仍读取 `config.symbols`。

- [ ] **Step 3: 实现子类参数和 Task-only 目录选择**

新增 `CryptoDailySyncParams` 并覆盖 crypto Task 的 `params_model`。`_upsert_crypto_catalog` 改从 crypto params 获取 `spot_pairs`；`run_daily_sync` 的 crypto 分支校验子类，股票分支不使用该字段。保留 canonical symbols 查库、去重、失败隔离和原顺序结果聚合。

- [ ] **Step 4: 运行 Task 参数和市场执行测试**

Run: 同 Step 2，并加 `backend/tests/tasks/test_daily_sync_concurrency.py backend/tests/tasks/test_market_sync_final.py`。
Expected: 全部 PASS；空目录 Provider 零调用，其他市场 schema 与执行不变。

- [ ] **Step 5: 检查接口差异并记录，不提交**

Run: `git diff --check && git diff -- backend/app/tasks/builtin/sync_daily.py backend/tests/tasks backend/tests/config/test_crypto_symbol_validation.py`
Expected: 无空白错误，无市场 symbols 执行读取。

---

### Task 2: 删除市场 symbols 并迁移旧配置和默认目录

**Files:**
- Modify: `backend/app/config/models.py`
- Modify: `backend/app/config/migrations.py`
- Modify: `backend/app/config/defaults.py`
- Test: `backend/tests/config/test_market_schema.py`
- Test: `backend/tests/config/test_store.py`
- Test: `backend/tests/config/test_crypto_symbol_validation.py`

**Interfaces:**
- Consumes: Task 1 的 `CryptoDailySyncParams.spot_pairs`。
- Produces: 仅 provider/timeout 的 `MarketSettings`；旧 `markets.crypto.symbols` → `market.sync_crypto_daily.params.spot_pairs` 的不可变迁移；默认 pairs 位于 crypto Task。

- [ ] **Step 1: 写模型、默认值和迁移失败测试**

覆盖：MarketSettings 不再接受 symbols；默认 markets 无 symbols 而 crypto Task 保留 BTC/ETH 默认目录；旧 crypto pairs 迁入缺失的 spot_pairs；Task 显式空数组优先；无 tasks 时可创建；输入、schema_version、revision 不变；保存后市场无 symbols。

- [ ] **Step 2: 运行配置测试确认失败**

Run: `backend/.venv/bin/python -m pytest backend/tests/config backend/tests/tasks/test_registry.py -q`
Expected: FAIL，市场仍有 symbols，迁移和默认 Task 尚无 spot_pairs。

- [ ] **Step 3: 精简模型、迁移和默认配置**

从 MarketSettings 删除 symbols 及非 crypto symbols 专项校验；保留共享 `CryptoSymbol` 供 Task/provider 使用。迁移只复制到缺失的 `spot_pairs` 键后剥离市场 symbols。`default_settings` 将现有 BTC/ETH 移入 crypto Task params，其他 Task 默认不变。

- [ ] **Step 4: 运行完整后端回归**

Run: `backend/.venv/bin/python -m pytest backend -q`
Expected: 全部 PASS；旧文件可读取，新保存结构无市场 symbols，单次请求/并发/取消语义不回归。

- [ ] **Step 5: 检查迁移差异并记录，不提交**

Run: `git diff --check && git diff -- backend/app/config backend/tests/config`
Expected: 仅模型、默认目录、迁移和测试变更，无 revision 自动增加。

---

### Task 3: 删除前端数据源交易对编辑与 payload

**Files:**
- Modify: `frontend/src/types/settings.ts`
- Modify: `frontend/src/api/decoders/settings.ts`
- Modify: `frontend/src/features/settings/MarketSettingsForm.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/settings/marketOptions.ts`
- Test: `frontend/src/features/settings/SettingsPage.test.tsx`
- Test: `frontend/src/features/settings/marketOptions.test.ts`
- Test: `frontend/src/api/endpoints.test.ts`

**Interfaces:**
- Consumes: Task 2 的精简 MarketSettings DTO；Task 的 spot_pairs 继续由整文档 tasks 字段原样保留。
- Produces: 前端 markets 仅 provider/timeout；页面无交易对控件，draft 和 PUT 无市场 symbols。

- [ ] **Step 1: 写 decoder、保存和页面失败测试**

输入包含旧 crypto symbols 时 draft 不包含该键，PUT markets 不包含 symbols，tasks 中 spot_pairs 原样保留；页面仍可编辑四个 provider/timeout，但不显示“现货交易对”“添加交易对”或相关输入。

- [ ] **Step 2: 运行设置/API 测试确认失败**

Run: `npm --prefix frontend test -- --run src/features/settings/SettingsPage.test.tsx src/features/settings/marketOptions.test.ts src/api/endpoints.test.ts`
Expected: FAIL，类型、表单和 decoder 仍支持市场 symbols。

- [ ] **Step 3: 删除类型、UI 和无用 helper**

保留 market/provider 标签与 Object.entries 所需能力，删除 CryptoSymbol 市场类型、交易对编辑、exchange helper 和 retired decoder 输出；保持不可变 draft 更新及 revision/conflict 行为。

- [ ] **Step 4: 运行设置、API 与 App 路由测试**

Run: 同 Step 2，并加 `src/App.test.tsx`。
Expected: 全部 PASS，PUT 不带市场 symbols，Task params 不被整文档保存丢棄。

- [ ] **Step 5: 检查差异并记录，不提交**

Run: `git diff --check && git diff -- frontend/src/types/settings.ts frontend/src/api/decoders/settings.ts frontend/src/features/settings frontend/src/api/endpoints.test.ts`
Expected: 无交易对表单或市场 symbols 输出。

---

### Task 4: 实现可读的单栏深色 Task 参数表单

**Files:**
- Modify: `frontend/src/components/SchemaForm.tsx`
- Modify: `frontend/src/features/tasks/TaskConfigDrawer.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/components/SchemaForm.test.tsx`
- Test: `frontend/src/features/tasks/TaskConfigDrawer.test.tsx`
- Test: `frontend/e2e/tasks-settings.spec.ts`
- Test: `frontend/e2e/fixtures.ts`

**Interfaces:**
- Consumes: Task 1 的 crypto spot_pairs JSON Schema 和现有 RJSF validator。
- Produces: `SchemaForm` 可选 `formContext` 透传；Task Drawer 使用 `{labelAlign:"left", colSpan:24}`、640px 响应式宽度和作用域深色样式。

- [ ] **Step 1: 写布局、数组提交和浏览器视觉失败测试**

组件覆盖两个普通字段不再出现 `.ant-col-12`，Object/Array 标题左对齐，spot_pairs 数组对象可编辑并进入保存 payload。E2E 使用 crypto descriptor：检查单栏、label 左对齐、深色背景/文字、640px/100vw 上限和移动端无横向溢出；断言 Array 操作后提交结构正确。

- [ ] **Step 2: 运行组件与聚焦 E2E 确认失败**

Run: `npm --prefix frontend test -- --run src/components/SchemaForm.test.tsx src/features/tasks/TaskConfigDrawer.test.tsx && npm --prefix frontend run e2e -- --grep 'single-column dark form'`
Expected: FAIL，formContext 未传且默认两列/样式不符合断言。

- [ ] **Step 3: 透传 formContext 并添加作用域样式**

保持 SchemaForm 默认调用不变，仅 TaskConfigDrawer 传单栏左对齐 context。Drawer 使用 `size={640}` 和 `max-width:100vw`；新增 `task-config-drawer`/`task-schema-form` 作用域 class，统一 fieldset、数组项、Input/InputNumber/Select/Button、帮助/错误文字的深色 token 和间距。

- [ ] **Step 4: 运行表单组件、Task 页面和聚焦 E2E**

Run: 同 Step 2，并加 `src/features/tasks/TasksPage.test.tsx`。
Expected: 全部 PASS；提交结构、Cron/409、表单验证和移动端无横向溢出正常。

- [ ] **Step 5: 浏览器截图检查并记录，不提交**

检查桌面 crypto 数组表单与 375px 窄屏截图，确认文字可读、无裁切；`git diff --check` 通过。

---

### Task 5: 删除页面重复标题并应用真正的 Tab 外观

**Files:**
- Modify: `frontend/src/features/tasks/TasksPage.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceTabsBar.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/App.test.tsx`
- Test: `frontend/src/features/settings/SettingsPage.test.tsx`
- Test: `frontend/src/features/tasks/TasksPage.test.tsx`
- Test: `frontend/e2e/workspace.spec.ts`

**Interfaces:**
- Consumes: 现有 WorkspaceTab、WorkspaceTabsBar 和页面缓存。
- Produces: 无页面级重复标题；带连续底边、active 表面/指示和上方圆角的原生 Tab。

- [ ] **Step 1: 写标题和 Tab 外观失败测试**

断言页面不存在 `heading` 角色“Task 管理”“数据源配置”，但 `tab`、侧栏链接和业务标题保留；E2E 检查 tablist 连续底边、active tab class/上方圆角，且关闭按钮 accessible name 不变。

- [ ] **Step 2: 运行聚焦测试确认失败**

Run: `npm --prefix frontend test -- --run src/App.test.tsx src/features/settings/SettingsPage.test.tsx src/features/tasks/TasksPage.test.tsx && npm --prefix frontend run e2e -- --grep 'workspace tabs|tab appearance'`
Expected: FAIL，页面标题仍存在且当前 Tab 为独立按钮外观。

- [ ] **Step 3: 删除标题并添加纯视觉 Tab class/CSS**

不修改 useWorkspaceTabs、Workspace、workspacePages 或 Provider。保留 `role=tablist/tab`、`aria-selected`、navigate/closeTab 和所有业务内容。

- [ ] **Step 4: 运行前端单测和完整浏览器回归**

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run e2e`
Expected: 全部 PASS；重复激活、状态保留、Analysis 重置、关闭最后标签和 `/blank` 不回归。

- [ ] **Step 5: 检查视觉与差异，不提交**

截图确认无重复页面标题、active/inactive Tab 清晰；`git diff --check` 通过。

---

### Task 6: 文档、全量门禁与独立审查

**Files:**
- Modify: `backend/README.md`
- Modify: `frontend/README.md`
- Modify: `docs/superpowers/HANDOFF-2026-11-11.md`（追加本轮，不改写既有记录）

**Interfaces:**
- Consumes: Tasks 1–5 的实现与证据。
- Produces: 可复现的 Task spot_pairs/symbols、空目录、迁移和 UI 使用说明。

- [ ] **Step 1: 更新文档**

说明市场仅 provider/timeout、旧 pairs 迁移及空数组优先、两个 Task 参数的区别、空目录零 Provider、默认目录位置、单栏深色表单和 Tab 外观。

- [ ] **Step 2: 运行后端完整门禁**

Run: `backend/.venv/bin/python -m pytest backend --cov=app --cov-report=term-missing -q`
Expected: 全部通过，总覆盖率不低于 80%。

- [ ] **Step 3: 运行前端完整门禁**

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run test:coverage && npm --prefix frontend run build && npm --prefix frontend run e2e`
Expected: 全部通过，四项覆盖率不低于 80%，构建成功。

- [ ] **Step 4: 真实本地验收**

验证旧配置迁移后的 crypto Task 表单、空目录不执行、数据源无交易对、单栏深色/移动端无溢出、Tab 与状态保留、控制台无错误；不触发公网下载。若编辑真实配置，先备份并在停止后端后恢复原文件，随后一个 worker 重启。

- [ ] **Step 5: 独立审查与最后差异检查**

调用 code-reviewer 审查本计划文件及完整相关 diff；Critical/Important 先写失败测试再修复并重跑门禁。最后 `git diff --check` 和 `git status --short`，不 commit/push。

---

### Task 7: 提亮 Task 操作区并实现可折叠菜单与 Group 独立编辑

**Files:**
- Modify: `frontend/src/components/SchemaForm.tsx`
- Modify: `frontend/src/features/tasks/TaskConfigDrawer.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/settings/MarketSettingsForm.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/components/SchemaForm.test.tsx`
- Test: `frontend/src/features/tasks/TaskConfigDrawer.test.tsx`
- Test: `frontend/src/App.test.tsx`
- Test: `frontend/src/features/settings/SettingsPage.test.tsx`
- Test: `frontend/e2e/tasks-settings.spec.ts`
- Test: `frontend/e2e/workspace.spec.ts`

**Interfaces:**
- Consumes: Task 4 的 SchemaForm formContext、Task 5 的菜单/页面结构、现有 useSettingsSave 与整文档 revision。
- Produces: SchemaForm 可选 `ButtonTemplates.SubmitButton/actions` 水平操作区；可折叠系统菜单；Group 只读→编辑→独立保存/放弃的状态与保存合并规则。

- [ ] **Step 1: 写颜色、水平操作区、菜单折叠和 Group 保存失败测试**

Task 测试断言新 surface、保存/关闭同一 `.schema-form-actions` 且原生 form 提交正常；菜单第二次点击折叠。设置测试断言默认全部只读、无页底按钮，A/B 两组分别编辑后，保存 A 的 PUT 只改变 A，B 的本地未保存值保留且不进入该 PUT；随后保存 B 使用新 revision；放弃只复位当前 Group；409/429 在组内显示。

- [ ] **Step 2: 运行组件和聚焦 E2E 确认失败**

Run: `npm --prefix frontend test -- --run src/components/SchemaForm.test.tsx src/features/tasks/TaskConfigDrawer.test.tsx src/App.test.tsx src/features/settings/SettingsPage.test.tsx && npm --prefix frontend run e2e -- --grep 'single-column dark form|group editing|settings menu'`
Expected: FAIL，当前颜色、按钮布局、菜单 openKeys 和页底整文档保存不符合新行为。

- [ ] **Step 3: 实现自定义操作区、菜单状态和 Group 编辑/保存**

SchemaForm 以 `ButtonTemplates.SubmitButton` 在表单内部提供原生 submit 与自定义操作区，Task 使用提亮 token。App 以受控 openKeys 支持折叠。SettingsPage 以最新服务端文档只替换当前 Group；成功保留其他 Group 本地编辑并使用新 revision，409 只复位当前保存 Group。移除页底按钮，组内默认只读并在编辑时展示保存/放弃。

- [ ] **Step 4: 运行完整前端回归**

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run test:coverage && npm --prefix frontend run build && npm --prefix frontend run e2e`
Expected: 全部 PASS，覆盖率四项 ≥80%；Group 保存、冲突、Tab 状态与 Task 数组提交不回归。

- [ ] **Step 5: 真实视觉验收与独立审查**

检查 Task 提亮和水平操作区、菜单折叠、A/B Group 独立编辑的桌面与移动端页面及控制台。调用 code-reviewer 审查本计划全部相关 diff；Critical/Important 先 RED→GREEN 修复并重跑门禁。最后 `git diff --check` 与 `git status --short`，不 commit/push。
