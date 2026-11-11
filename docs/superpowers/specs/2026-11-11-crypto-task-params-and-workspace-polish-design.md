# 加密交易对 Task 化与工作台表单视觉整理设计

日期：2026-11-11

## 目标与已确认决策

用户已确认以下完整行为：

1. 删除各页面内容区顶部的页面标题，例如“Task 管理”“数据源配置”；卡片标题、运行历史标题和业务内容保留。
2. 顶部页面入口改为连接的深色 Tab 外观，但继续使用原生 `button role="tab"` 和现有 Workspace 页面缓存，不改回会卸载内容的 AntD Tabs，也不改变路由 key、关闭和 `/blank` 语义。
3. 市场级数据源配置彻底删除 `symbols`，前后端只保留 provider 与请求超时；不再存在市场级加密现货交易对。
4. 旧 `markets.crypto.symbols` 在模型校验前迁入 `market.sync_crypto_daily.params.spot_pairs`。Task 已显式包含 `spot_pairs`（包括空数组）时优先；迁移不修改输入、不改变 schema_version 或 revision。
5. 加密 Task 同时具有两个不同语义的参数：
   - `spot_pairs`：结构化现货目录项 `{exchange, symbol}`；
   - `symbols`：本次执行临时筛选的规范证券 ID，例如 `BINANCE:BTC/USDT`。
6. 执行时只从 Task `spot_pairs` 注册/更新本地 Instrument 目录，绝不读取市场配置兜底。`symbols` 为空时选择全部 `spot_pairs`；两者都为空时不访问 Provider，并以“未选择证券”失败。
7. `spot_pairs` 为空但 `symbols` 非空时，只允许选择本地目录中已经存在的 active 规范证券；未知或 inactive 项仍按明确失败项处理。部分可解析与部分失败沿用 mixed-result 语义。
8. Task 配置表单统一为单栏左对齐，并改善 Drawer、字段、输入控件、数组/嵌套字段、说明文字和边框的深色配色与可读性。

## 非目标

- 不新增交易所、Provider、行情类型或自动下载。
- 不改变股票/指数复权、历史、重叠、并发、取消清理和单次请求语义。
- 不把所有市场的手动 `symbols` 改为结构化对象；只有 crypto 新增 `spot_pairs`。
- 不改变标签 pathname 身份、页面保持挂载、隐藏 Task 暂停轮询、关闭最后 Analysis 重置会话的现有行为。
- 不自动 commit/push；默认测试不访问公网。

## 后端模型与迁移

### 市场配置

`MarketSettings` 仅包含：

- `provider`
- `request_timeout_seconds`

删除 `symbols`。`migrate_legacy_settings_document` 在 Pydantic 校验前读取旧 `markets.crypto.symbols`，并写入 crypto daily Task 的 `params.spot_pairs`；随后从市场文档剥离 `symbols` 以及此前已废弃的字段。若 `tasks` 整体缺失，沿用现有行为创建所需 Task 项。若 Task params 已有 `spot_pairs` 键，即使值是空数组，也不覆盖。

新安装默认配置不再把交易对放在市场文档。原默认加密交易对移到默认 `market.sync_crypto_daily.params.spot_pairs`，Task 继续默认 disabled，不会因启动自动执行。

### Crypto Task 参数

新增 `CryptoDailySyncParams(DailySyncParams)`：

```python
spot_pairs: tuple[CryptoSymbol, ...] = ()
```

`CryptoDailySyncTask.params_model` 指向该子类，A／港／美 Task 的 schema 不出现 `spot_pairs`。复用现有 `CryptoSymbol` 校验：交易所枚举、精确大写 `BASE/QUOTE`、禁止空白、衍生品格式和额外字段。RJSF 继续从后端 descriptor 动态生成数组对象表单，不创建专用前端页面。

`run_daily_sync` 仍接收共同的 `DailySyncParams` 契约；只有 crypto 分支要求并读取 `CryptoDailySyncParams.spot_pairs`。市场 `MarketSettings` 快照仍提供 Provider 选择、timeout 等运行配置，但不再提供证券目录。

### 选择与失败语义

- crypto 执行先用 `spot_pairs` upsert 本地目录。
- 未提供 `universe_codes` 和 `symbols` 时，默认选择 upsert 后的 `spot_pairs`。
- 两个字段都为空时，沿用现有 `DEFAULT_UNIVERSE_ERROR`，在 Provider 访问前失败。
- 显式 `symbols` 继续走 canonical ID 查目录、active 校验、去重、失败隔离和原顺序结果聚合。
- `spot_pairs` 本身不是显式 `symbols` 之外的隐藏筛选条件；它只负责建立默认目录。显式选择已存在的本地证券不因为它未列入本次 `spot_pairs` 而被拒绝。
- 迁移、参数、配置快照与运行历史均保留完整结构。

## 前端数据源与 Task 表单

### 数据源配置

- 删除 `MarketSettings.symbols` 类型、运行时 decoder 输出、draft/save payload 和交易对编辑 UI。
- decoder 对外部旧响应进行边界校验，并在进入 draft 前剥离 retired `symbols`；保存整文档时仍保留未修改的 timezone/indicators/tasks，但 markets 只回传 provider/timeout。
- 删除仅为旧交易对表单服务的 helper 与测试，保留 Provider 标签和市场标签。

### 单栏左对齐 RJSF

利用已安装 `@rjsf/antd` 的原生能力：

```tsx
formContext={{ labelAlign: "left", colSpan: 24 }}
```

`ObjectFieldTemplate` 因此不再把普通字段拆成左右两列，Object/Array 标题统一左对齐；FieldTemplate 继续采用 24-span label/control。`SchemaForm` 增加可选 `formContext` 透传，TaskConfigDrawer 提供上述常量，避免全局改变指标编辑器的布局。

Task Drawer 使用作用域 class 和深色 token，不改其他 Drawer：

- 内容/Header 背景使用 `#131722` 或相邻 surface；
- 主文字 `#d1d4dc`，辅助文字 `#9598a1`；
- 边框 `#2a2e39`，输入背景使用略深 surface；
- fieldset、数组项、嵌套对象使用一致间距和边框；
- Input/InputNumber/Select/Button/Switch、错误与帮助文字均保持可读对比度；
- label、控件、数组添加/删除按钮不出现黑字黑底或白块突兀混用。

实施者布局取舍（不改变用户行为）：当前两列 RJSF 会把内容挤出 Drawer，因此 Drawer 采用最高 640px、`max-width: 100vw` 的响应式宽度；所有 schema 字段改为单栏后，桌面与移动宽度都不得出现横向溢出。

## 页面标题与 Tab

删除 TasksPage、SettingsPage 的页面级 `Typography.Title`，不删除卡片、历史、Drawer 等业务标题。

WorkspaceTabsBar 保持原生按钮和现有 ARIA：

- 外层 `role="tablist"` 使用连续底边；
- 每个 tab 使用上方圆角、统一高度、边框和 active 表面；
- active 使用 `#2962ff` 指示和 `#ffffff` 文字，inactive 使用 `#9598a1`；
- 关闭按钮仍暴露 `aria-label="关闭 <title>"`；
- 只改变视觉 class/CSS，不改变 hook、缓存 ReactNode、navigate、closeTab 或 Provider 生命周期。

## 测试与验收

采用 RED→GREEN：

1. **后端迁移**：旧 crypto symbols 迁入 `spot_pairs`，显式空数组优先，无 tasks 时可创建，revision/schema/输入不可变；新模型拒绝市场 symbols。
2. **参数 schema**：仅 crypto descriptor 出现结构化 `spot_pairs`，默认目录从市场移至 Task；非法 pair 在边界拒绝。
3. **执行**：仅使用 Task pairs；空 pairs+空 symbols 时 Provider 零调用；显式 symbols 可解析本地 active，未知项失败；默认选择、混合结果和单次请求不回归。
4. **前端设置/API**：draft 和 PUT 不含市场 symbols，页面不显示交易对编辑。
5. **表单**：Task RJSF 使用 `labelAlign=left` 与 `colSpan=24`；spot_pairs 数组对象可添加、编辑、删除并提交；标签和输入在浏览器中没有对齐/对比度异常。
6. **工作台**：页面 heading 消失但 Tab 保留，重复激活、关闭、状态保留和 `/blank` 全量回归。
7. 后端 pytest+coverage、前端 Vitest+coverage、TypeScript/Vite build、完整 Playwright、真实本地页面与控制台检查，最后独立 code review。

## 追加交互决策（用户后续明确）

1. Task Drawer 的深色背景需要提亮，保存配置与关闭必须水平排列。通过 RJSF `ButtonTemplates.SubmitButton` 公共模板在表单内部渲染自定义操作区，不使用绝对定位或外部 form 属性；默认 SchemaForm 的提交行为不变。
2. “系统设置”菜单必须可以展开也可以折叠，openKeys 由用户操作控制，初始展开只是默认状态。
3. 数据源页移除页面底部的保存/放弃按钮，改为每个市场 Group 默认只读并提供组内“编辑”。编辑后只启用该 Group 的 provider/timeout（及未来字段），并显示组内“放弃”“保存”。
4. Group 保存以服务端最新整文档为基础，只替换当前 Group，不能把其他 Group 的未保存本地修改一并提交。保存成功后提升 revision、关闭当前 Group 编辑态，同时保留其他 Group 的未保存编辑；随后可继续用新 revision 保存其他 Group。
5. 409 时重新加载最新服务端文档并复位当前保存 Group 的值，其他 Group 的未保存编辑仍保留；429/其他错误在当前 Group 内展示。
6. 实施者配色取舍：Task Drawer、输入和 Select surface 使用 `#202634`，参数面板与数组项仅浅一级使用 `#262e40`，主文字 `#e6e9f0`，辅助文字 `#a6adbd`，边框使用中性蓝灰 `#344054`，保持统一的深色工作台视觉，不使用白色参数面板或浅色输入背景。
7. 简单字符串数组（当前为 `universe_codes`、`symbols`）使用固定 72px 高度的单个输入框，按英文逗号分隔、trim 并忽略空项；输入过程中保留用户正在输入的逗号，失焦后规范化显示。对象数组（如 `spot_pairs`）继续使用逐行添加/删除。

## 运行约束

- 保持 `main` 就地工作，不自动 commit/push，不修改研究目录。
- 默认测试全部离线；在线测试仍需 `STOCK_LAB_ONLINE=1` 和有界临时样本。
- 真实本地验收若修改配置，必须恢复原文件；后端始终一个 Uvicorn worker。
