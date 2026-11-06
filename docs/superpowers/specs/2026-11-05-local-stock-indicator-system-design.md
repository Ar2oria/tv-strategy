# 本地多市场股票指标验证系统：设计与实施计划

## Context

用户希望快速编写自己的技术指标，并在本地历史 K 线上直观检查指标曲线和信号，而不是仅做行情展示。本计划创建一个全新的前后端系统，不以当前仓库的 `python_validation/`、`volatility_markers/` 等现有实现为基础，也不修改这些目录。

第一版只解决图表直观验证，不包含模拟交易、收益统计或完整回测系统。

## 已确认需求与边界

- 后端 Python 指标子类：唯一名称、参数 schema、统一计算入口；新增/修改代码后重启后端生效。
- 前端自动展示指标及参数表单，提交股票、周期、范围、指标名称和参数；一个请求可计算当前启用的多个指标。
- 指标结果支持主图叠加曲线、逐 K 线标记和下方独立副图；默认样式加单点覆盖。
- 首批示例同时覆盖主图信号标记和副图振荡指标。
- Task 也是后端 Python 子类：唯一名称、统一 `run` 入口、参数 schema；每个 Task 类仅有一个任务配置和一条 Cron，不做多实例。
- 前端可配置 Cron、启停、下次执行时间、任务参数，支持立即执行以及执行历史和日志。
- 标准五段 Crontab；手动与调度执行共用同一运行器。
- 市场范围：A 股沪深300、科创板、创业板；港股恒生科技；美股纳斯达克100和 SOXX 成分股；加密货币主流币加自选。纳斯达克范围明确为纳斯达克100。
- 日线为基础数据；周线和月线由日线聚合；按各 Task 的 Cron 增量更新，不做分钟线或行情流推送。
- 首次历史深度按市场配置；图表和指标只使用前复权行情（加密货币无复权）。
- 配置只从 frontend 设置页修改，后端校验后写回 JSON 并热应用；不监听外部文件改动。
- SQLite 保存行情、证券元数据和任务执行记录；JSON 保存系统配置、Task 参数和调度。
- 技术栈由助手选择；本地单用户使用。
- 数据源官方公开 API 优先；覆盖不足时允许 AKShare、yfinance 等成熟 SDK 作为备用，不直接以脆弱网页解析作为首选。

## 推荐架构

后端选择 **Python 3.12+ + FastAPI + SQLAlchemy 2 + SQLite + APScheduler 3.11.x + croniter**；前端选择 **React + TypeScript + Vite + TradingView Lightweight Charts 5.2**。Lightweight Charts 已原生支持多 pane 和 `createSeriesMarkers`，符合主图、副图与逐点标记需求，无需自研 canvas 渲染。`croniter` 负责标准 Crontab 语义，APScheduler 负责按下一次时间触发，避免 APScheduler 3.x 的星期编号差异。

在仓库根目录新增独立的 `backend/`、`frontend/`、`config/` 和 `data/`；后端使用自己的 `pyproject.toml`，避免覆盖现有根目录文件。服务默认仅绑定 `127.0.0.1`，不增加登录和远程访问能力。

### 后端模块

- `backend/app/main.py`：应用组装、启动时注册指标和 Task、关闭时清理调度器。
- `backend/app/api/`：`instruments`、`bars`、`indicators`、`tasks`、`settings` 路由；统一响应 envelope 和异常映射。
- `backend/app/config/`：Pydantic 配置 schema、原子 JSON 写入、运行时热应用订阅。
- `backend/app/db/`：engine、session、Alembic migration；SQLite 开启 WAL 和外键。
- `backend/app/models/` + `repositories/`：证券、板块成员、日线、Task 运行与日志的数据访问。
- `backend/app/providers/`：统一 `MarketDataProvider` 接口及按市场实现的适配器；统一返回规范化、不可变的行情 DTO，不让第三方字段泄漏到指标层。
- `backend/app/indicators/base.py`：冻结的参数模型、`Indicator` 抽象基类、输出模型和注册装饰器。
- `backend/app/indicators/builtin/`：`DonchianBreakoutIndicator` 在主图标记突破前 N 日高/低点，`RSIIndicator` 在副图展示 RSI、30/70 参考线及逐点颜色；启动时扫描内置及 custom 模块，装饰器自动注册，用户新增文件并重启即可，无需再改前端或中央清单。
- `backend/app/tasks/base.py` + `registry.py`：唯一名称、参数模型、唯一 `run(context, params)` 入口、模块扫描和重复注册检查；新增 Task 文件同样在重启后自动出现。
- `backend/app/tasks/builtin/`：各市场证券/日线同步、历史清理任务；不同市场需要不同 Cron 时定义独立 Task 子类，不引入任务多实例。
- `backend/app/services/`：行情查询与周/月聚合、指标批量计算、Task 运行、配置应用。

### 数据与配置边界

核心表：`instruments`、`universe_memberships`、`daily_bars`、`task_runs`、`task_logs`。日线以证券和交易日唯一，增量 upsert；保存来源和更新时间。周/月不重复落库，按实际最后交易日聚合，避免 holiday 导致标记无法对齐。

前复权历史会在新公司行为后整体变化，不能只追加新 bar。增量同步默认带一个重叠窗口并比较同日期价格；若重叠数据出现超容差变化，或 provider/复权配置改变，则重新下载该证券配置范围内的完整历史，下载成功后在单事务中替换，失败保留旧数据并记录错误。全量刷新也先下载再替换，避免网络失败清空已有行情。

`config/settings.json` 包含 schema 版本、配置 revision、各市场 provider 与历史年限（股票默认10年，加密默认尽力获取交易对可用历史）、请求超时/重试/并发、调度时区、每个 Task 的参数/Cron/启停。运行状态和历史不写 JSON。设置和 Task 配置更新使用同一进程锁及 expected revision，防止两个页面互相覆盖。更新先验证完整新配置，再临时文件写入并原子替换，成功后通知调度器等组件；若应用失败则恢复旧文件和旧运行状态并返回可读错误。正在运行的 Task 保持启动时的配置快照。服务端口等不能热更新的字段不放入可热更新设置页。可选 API secret 使用环境变量引用，前端不回显明文。

## 指标协议

每个指标子类声明：`name`、显示名、说明、Pydantic 参数模型、默认输出样式，以及统一 `calculate(context, bars, params)`。输入和结果使用新对象，计算不得修改输入。第一版利用日频单票数据量较小的特点，计算时读取该证券截至结束日期的全部已存历史，再裁剪到可见范围；这样 MA/RSI 和周/月指标自动获得足够 warmup，不让每个指标另写历史长度逻辑。

版本化响应按指标实例返回：

- `panes`：`main` 或新建 pane，含稳定 ID、标题、高度和价格刻度。
- `series`：`line`、`area`、`histogram` 等，含默认样式和 `{time, value, color?}` 数据。
- `markers`：`time`、`aboveBar/belowBar/inBar`、箭头/圆形/方形、颜色、文字和 tooltip；可逐点覆盖默认样式。
- `reference_lines`：副图水平线，例如 30/70。
- 每个指标独立返回 warnings/error，一个指标失败不清空 K 线或其他指标。

后端验证时间存在、排序、有限数值、样式枚举和输出大小。前端按协议通用渲染，新增指标无需新增 React 组件。

## API 与实例标识

统一 envelope：`success`、`data`、可空 `error` 和分页/元信息 `meta`。主要接口：

- `GET /api/v1/universes`、`GET /api/v1/instruments`：市场、股票池和搜索。
- `GET /api/v1/bars`：证券、日/周/月、开始/结束日期和上限。
- `GET /api/v1/indicators`：唯一名称、说明、参数 JSON Schema 和默认参数。
- `POST /api/v1/indicators/compute`：`instrument_id/timeframe/start/end` 加 `indicators[{instance_id,name,params}]`，返回对应的结果列表。
- `GET /api/v1/tasks`、`GET/PUT /api/v1/tasks/{name}/config`、`POST /api/v1/tasks/{name}/runs`、`GET /api/v1/tasks/{name}/runs`、`GET /api/v1/task-runs/{id}/logs`。
- `GET/PUT /api/v1/settings`：读取脱敏配置、校验并热保存。

前端可为同一指标类添加多个不同参数的 `instance_id`；Task 不允许多实例。后端用 instance ID 为 pane/series ID 加命名空间，主图共用 pane 0，新副图按请求顺序排列。marker 可指向主图 candle series 或本指标内的 series。日/周/月统一使用 ISO 日期，缺失数值用 null 并转换为 Lightweight Charts whitespace；marker 时间必须真实存在于返回 K 线。tooltip 和标题均为纯文本。

## Task 与调度

APScheduler 与手动执行都调用同一个 `TaskRunner`。调度器用 `croniter` 在配置时区计算下一次时间，注册一次性 `DateTrigger`，触发后再算下一次；这样保留标准 Crontab 的星期日编号以及 day-of-month/day-of-week 语义，配置变化时取消旧安排并重算。同一 Task 默认禁止重入，重叠触发记录为 skipped。手动执行立即创建 run 并返回 ID，前端轮询状态。记录 queued/running/success/partial/failed/skipped/interrupted、开始结束时间、参数快照、处理进度、异常摘要和结构化日志；配置日志保留期。每个证券独立保存：单票请求的完整范围下载成功后才事务写入，失败不留下半截初始历史；部分证券失败记为 partial，其他证券继续，后续运行对缺数证券全量、已同步证券增量重试。首版用这一逐证券语义续跑，不引入额外任务队列或复杂批次游标。内置同步 Task 默认停用，首次由用户手动运行，避免启动即抓取全市场。启动时发现重复 Task 名称、无效 Cron 或参数错误应明确报错，不静默跳过。

## 前端页面

1. **图表分析**：市场/板块/股票搜索，日/周/月切换，时间范围，K 线；侧栏列出可用指标并自动生成参数表单；已启用指标可编辑、删除和刷新。主图与副图共享时间轴，pane 可调整高度，标记和提示与对应 bar 对齐。
2. **Task 管理**：注册 Task 列表、说明、参数表单、Cron、启停、下次/上次运行、立即执行；运行历史及日志详情。
3. **系统设置**：分市场 provider、历史深度、请求策略、调度时区等；保存成功后立即应用并显示结果。

默认中文界面；加载、空数据、部分指标失败、provider 失败和配置校验失败均有可见状态。股票日线按交易所日期显示，加密货币按 UTC；内部保留市场、交易所、币种和时区元数据。

## 数据源选择

采用统一 `MarketDataProvider` 接口，成分列表和 OHLCV 可由不同适配器提供。官方公开 API 优先，成熟 SDK 作为覆盖补充；不承诺免费源有 SLA，不绕过地区限制。每次同步记录实际来源，避免将不同交易所或复权口径拼成一条序列。

### 加密货币（调研已确认）

- 主源 Binance 现货，备用 OKX 现货；业务层依赖自有 provider 接口，下接 CCXT 适配器。
- 使用公共现货 OHLCV，不需要交易权限或 API key；默认 BTC/USDT、ETH/USDT，可配置其他现货交易对。
- 自有有界分页、重试、共享限速和本地缓存，不依赖 CCXT 标为实验性的自动分页。429/418 遵守响应等待时间，剔除未完结日 K。
- 内部统一 UTC；OKX 老历史使用 `history-candles`，周/月仍由本地日线聚合。实际最早历史按交易对探测。
- 官方依据：[CCXT OHLCV](https://docs.ccxt.com/docs/manual#ohlcv-candlestick-charts)、[Binance K线](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#klinecandlestick-data)、[OKX 历史K线](https://www.okx.com/docs-v5/en#rest-api-market-data-get-candlesticks-history)。

### A 股与港股

- A 股主源：AKShare `stock_zh_a_hist`（东方财富上游，明确 `adjust="qfq"`）；备用 BaoStock `query_history_k_data_plus`（`adjustflag=2`）。指数日线使用 `index_zh_a_hist`，指数本身不做复权。
- 港股主源：AKShare `stock_hk_hist` 的前复权日线；备用 AKShare 新浪接口或 yfinance。备用源复权语义不同或不明时不得混入已有序列，必须全量替换并记录来源。
- 沪深300当前成分使用中证官方 XLS/AKShare 读取器；科创板和创业板按用户确认覆盖**整个板块的当前上市股票**，不是科创50或创业板指成分。
- HSTECH 指数日线用 AKShare 东财接口，备用 Yahoo `HSTECH.HK`；指数成交量为空时保持空值，不当作真实零成交。当前成分低频读取恒指官方 factsheet PDF 的完整 constituents 表，校验股票代码、表头和声明的成分数量；解析失败保留上一份名单并报告错误，不硬编码当前30只的未来数量。
- AKShare/BaoStock 均无稳定性 SLA；默认串行低频、增量缓存、有界重试。BaoStock 禁止并发并遵守官方每日额度。上游限流值未确认时不硬编码 QPS。
- 依据：[AKShare A股日线](https://akshare.akfamily.xyz/data/stock/stock_quote.html#stock-zh-a-hist)、[BaoStock K线](https://www.baostock.com/mainContent?file=stockKData.md)、[AKShare 港股日线](https://akshare.akfamily.xyz/data/stock/stock_quote.html#stock-hk-hist)、[中证300名单](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/000300cons.xls)、[HSTECH 官方页](https://www.hsi.com.hk/eng/indexes/all-indexes/hstech)及[官方成分 factsheet](https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/factsheets/hsteche.pdf)。

### 美股

- OHLCV 主源：yfinance/Yahoo，`auto_adjust=True` 同时调整 OHLC，覆盖纳斯达克100、SOXX ETF及其美国全市场成分（含 NYSE 和 ADR）。这与东财 qfq 不保证算法一致，因此来源切换时全量替换，不拼接。
- SOXX 当前成分：iShares 官方 `latest-holdings.csv`，只保留 `Asset Class == Equity`，排除现金、期货和抵押品行；只保存当前快照，不假装有历史成分。
- 纳斯达克100当前名单使用 Invesco QQQ 官方页面实际调用的持仓 JSON：`https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/holdings/fund?idType=ticker&interval=monthly&productType=ETF`。已核实响应含 `effectiveDate`、`ticker`、`securityTypeCode`；保留 COM/ADR/DRNY 等已验证股票类型，剔除现金、期货、抵押品，Alphabet 两类证券分别保留。名单数量以解析和交叉校验为准，不硬编码100家公司或101只证券；指数行情用 Yahoo `^NDX`。
- 免费源限流未知时按动态响应退避并低频缓存；yfinance 非 Yahoo 官方背书且无 SLA。
- 依据：[yfinance 复权](https://ranaroussi.github.io/yfinance/advanced/price_adjustment.html)、[iShares SOXX](https://www.ishares.com/us/products/239705/ishares-semiconductor-etf)、[SOXX 官方持仓CSV](https://www.ishares.com/us/products/239705/ishares-semiconductor-etf/latest-holdings.csv)。

已核实的图表依据：Lightweight Charts 5.0 引入 multi-pane，当前官方文档为 5.2；v5 使用 `chart.addSeries(...)` 和 `createSeriesMarkers(...)`。官方资料：
- https://tradingview.github.io/lightweight-charts/docs/panes
- https://tradingview.github.io/lightweight-charts/docs/release-notes
- https://tradingview.github.io/lightweight-charts/tutorials/how_to/series-markers
- https://tradingview.github.io/lightweight-charts/docs/api/functions/createSeriesMarkers

## 运行与安全约束

- 仅运行一个 Uvicorn worker，避免调度重复和内存锁失效；重启时将上次遗留的 running 记录标为 interrupted，不自动补跑停机期间的 Cron。
- 所有请求用 Pydantic 校验，限制 bar 数、指标数、返回点数和请求体大小；所有路由使用本地内存限流，对计算、立即执行和设置写入使用更严格额度。
- SQLAlchemy 参数化访问；指标 tooltip 只接受纯文本，样式使用枚举和受控字段，前端不用 `dangerouslySetInnerHTML`。
- 远程 CSV/XLS/PDF/JSON 按不可信数据处理：限制大小、检查内容类型和 schema，失败保留旧数据；不执行下载内容。
- 生产模式由 FastAPI 提供前端静态文件以保持同源，开发模式仅允许本地 Vite 代理；默认不开放远程访问。

## 实施顺序

1. 按 TDD 建后端骨架、配置 schema、数据库 migration、统一错误和 API envelope。
2. 实现 provider 接口及主数据源，先用小样本契约测试固定字段、复权、分页和异常，再实现证券/日线同步 Task。
3. 实现行情查询、增量 upsert、周/月聚合和 TaskRunner/APScheduler。
4. 实现指标注册、参数 schema、计算协议、warmup 和两个示例指标。
5. 实现前端三个页面及通用图表渲染，接入真实 API。
6. 完成设置热应用、Task 历史和日志、错误状态与使用文档。
7. 运行单元、集成和 E2E 测试及安全/代码审查，再验收完整流程。

## 验证

- 后端 pytest + coverage：配置原子更新和回滚、注册唯一性、标准 Cron 的星期日及日期组合语义、禁止重入、provider 契约、增量同步、重叠窗口发现复权变化后全量替换且失败不删旧数据、周/月聚合、历史 warmup、指标输出 schema，目标覆盖率至少 80%。
- API 集成测试使用临时 SQLite 和固定 provider fixture，不依赖公网；另提供显式标记的在线 smoke test，不作为默认测试。
- 前端 Vitest/Testing Library 测参数表单、协议转换和错误状态；图表适配测试确保 marker 时间对应实际 bar，覆盖率目标同样至少 80%。
- Playwright E2E：选择股票与周期→添加主图信号和副图指标→修改参数→检查结果；配置 Task Cron→立即执行→查看历史日志；修改设置→无需重启验证生效。
- **首版在线验收以每个市场的小样本为准**：执行真实同步、核对若干 bar 并验证完整页面，不等待整个科创板/创业板等全量下载；用 fixture 测试全量任务在第 N 只证券中断后的续跑、partial 状态和去重，实际全量同步由用户之后后台运行。

## 非目标

回测与绩效统计、分钟线、实时行情流、网页编辑/执行 Python、指标代码热重载、多用户认证、远程部署、历史成分股快照、自动交易。
