# Task 修复、分市场代理与网络测试设计

日期：2026-11-12
状态：用户已批准实施；网络测试占用行为按最新反馈调整

## 1. 目标与背景

修复以下主动执行问题，并提升运行日志的可诊断性：

- `Synchronize market universes` 的美股 Universe 因上游实际返回 `text/plain`，被单一 Content-Type 白名单拒绝。
- `Synchronize US daily bars` 因本地没有美股 Universe 会员而在下载前失败。
- `Synchronize crypto daily bars` 的 Binance 现货请求被 CCXT 初始化时访问期货市场接口的失败阻断。
- `Synchronize A-share daily bars` 的东方财富限流被误记为通用 `ProviderUnavailable`，日志缺少可操作详情。
- Task 历史日志只显示通用消息，INFO/ERROR 没有明显不同的标签样式。

同时，在数据源配置页为 A 股、港股、美股、加密货币增加可选代理和手动网络测试。代理必须用于正式同步 Task，不得只用于测试按钮。

## 2. 已确认的用户行为

- 每个市场都可配置代理；未配置代理时直连。
- 代理支持 SOCKS；实现按 `http`、`https`、`socks5`、`socks5h` 四种 URL scheme 设计。
- “网络测试”只在对应市场处于**非编辑状态**时可点击；编辑时禁用。
- AKShare 数据源正在被其他调用使用时，正式 Task 排队等待，不因占用而失败；锁覆盖代理设置和完整请求。网络测试**不等待**，占用时立即返回专门的 `ProviderBusy` / “数据源正在使用中，请稍后重试”提示。
- 测试使用**已保存**的数据源和代理，不使用未保存草稿。
- 点击后打开弹窗，默认填入该市场的代表 Symbol/交易对，允许修改。
- 默认标的：A 股 `600519.SH`、港股 `0700.HK`、美股 `AAPL`、加密货币 `BTC/USDT`。
- 开始测试后，使用当前已保存 Provider + 代理实际获取最新可用价格。
- 弹窗展示连通状态、耗时、最新价、价格日期；失败时展示安全的错误类型和具体详情。
- “最新价格”定义为现有 Provider 返回的**最新一根可用日线的收盘价**，不是新增实时 tick 数据通道。
- 数据源与请求超时在同一行水平对齐；代理设置单独一行。

## 3. 非目标与约束

- 不新增实时行情、历史成分股或新的市场。
- 不自动切换 Provider，不把上游失败伪装成成功。
- 不恢复自动重试；公共上游真实限流仍可能使批量 Task 返回 partial/failed，但必须准确识别并支持后续断点续跑。
- 不修改全局 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 等环境变量；不同市场并发执行时不得串用代理。
- 不在日志、API 错误或测试结果中泄露代理 URL、凭证、上游响应正文或堆栈；脱敏 URL 正则同时覆盖 HTTP/HTTPS 与 SOCKS5/SOCKS5h。
- 网络测试不写数据库、不改配置、不创建 Task run。
- 保留现有不可变配置、热更新和单 Uvicorn worker 架构。

## 4. Task 与 Provider 修复

### 4.1 Universe Content-Type

扩展有界 HTTP 下载器，使调用方可以声明一个非空 Content-Type 白名单，而不是只允许单个值。

- Invesco 接受 `application/json` 和其当前实际返回的 `text/plain`。
- iShares 接受 `text/csv` 和其当前实际返回的 `text/plain`。
- 仍拒绝 HTML 等意外类型；响应大小限制、状态检查、JSON/CSV 结构校验全部保留。
- 添加真实响应形态的离线 fixture 回归，证明正文解析并未被放宽。

### 4.2 Binance 现货初始化

使用本机 CCXT 4.4.50 源码已确认的 `options.fetchMarkets = ["spot"]`，阻止 Binance `load_markets()` 访问 `dapi`/`fapi` 等非现货接口。

- 只加载现货市场，保持现有 OHLCV 分页和完整性校验。
- 离线测试断言构造参数，并用真实小样本验证现货初始化及最新日线。
- OKX 继续保持现货行为，不做无关重写。

### 4.3 A 股限流与空目录

- 将 AKShare `Push2RateLimitError` 明确映射为 `ProviderRateLimited`，保留“东方财富临时限流、稍后断点续跑”的安全详情。
- 其他 AKShare/CCXT 异常至少暴露 Provider、操作和异常类别；原始文本只能经现有脱敏器处理。
- 默认 Universe 没有解析出任何标的时，日线 Task 返回包含 `No instruments selected... Run Synchronize market universes first` 的明确失败结果和 ERROR 日志，不再由 TaskRunner 转成无详情的通用异常。保持 Task 职责分离，不在日线 Task 内隐式下载或改写 Universe；全新环境按 Universe → Daily 顺序主动执行。
- 不为消除 partial 而盲目重试或切换数据源；代理和准确限流信息用于处理真实网络问题。

## 5. 代理配置与传输

### 5.1 配置模型

每个 `MarketSettings` 新增可选 `proxy_url`，缺省为 `null`，因此旧配置无需填写即可迁移读取。

校验规则：

- 去除首尾空白；空字符串归一为 `null`。
- 仅允许 `http`、`https`、`socks5`、`socks5h`。
- 必须有有效 hostname 和 port；不允许 query/fragment。
- 不允许 URL userinfo（`username:password@host`）；首版面向本机或无需认证的代理，避免把凭证明文写入 `settings.json` 或带入日志。
- Provider Registry 热更新时，按市场创建独立 Provider 实例和不可变代理快照。

### 5.2 传输实现与已确认的库限制

- **自有 `httpx` 下载器：**每次创建独立 Client，显式代理时设置 `proxy=...`；始终 `trust_env=False`，确保未配置市场代理时是真正直连，而不是继承终端环境代理。覆盖 HSTECH、Invesco、iShares。
- **CCXT：**每个 exchange 实例设置 `proxies={"http": ..., "https": ...}`，完整请求后关闭 exchange；现货初始化修复继续生效。
- **AKShare：**当前版本的 `ProxyContext` 是进程全局单例，不是 thread-local。所有应用内 AKShare OHLCV/Universe/网络测试调用共用一个 SDK 锁，锁内设置本 Provider 的代理并包住**完整同步 SDK 调用**。无代理调用也进入同一锁，使用 requests 可识别的 protocol→None 映射阻止环境代理合并，确保直连并防止与有代理调用交叉。
- **yfinance：**当前版本的 `YfData` session/proxy 同样是进程全局单例。所有 Yahoo 调用使用另一个 SDK 专用锁，锁内执行 `yf.set_config(...)` 和完整 `Ticker.history`；每次调用都设置自己的代理，包括 None。
- **锁与超时：**锁必须位于同步 Provider wrapper 内。`asyncio.wait_for` 的合作式超时不能终止 worker，因此不能在 worker 仍在访问 SDK 时提前释放锁。
- **串行化取舍：**AKShare 的串行等待是用户明确选择的本期行为；yfinance 因相同的全局状态限制采用独立的等待锁。正式 Task 的 AKShare 之间、Yahoo 之间请求分别排队，不返回“数据源占用”错误；不同 SDK、CCXT、httpx 仍可并行。网络测试通过同一把锁的 `acquire(blocking=False)` 探测占用，失败时立即释放调用并返回 `ProviderBusy`，不得排队。本期不引入进程池生命周期和额外 IPC 复杂度。
- **BaoStock：**使用私有 raw TCP socket，HTTP/HTTPS 代理不适用，也没有安全的实例级 SOCKS 接口。`provider=baostock` 且 `proxy_url != null` 在配置校验时明确拒绝；无代理 BaoStock 保持现有行为。前端在该组合下显示“BaoStock 不支持代理”提示，后端仍是最终校验边界。
- 代理配置同时覆盖日线 Provider 与该市场拥有的 Universe Provider。
- 不修改 `os.environ`，不 monkey-patch socket/request 全局函数。
- 在 manifest 中将 `httpx` 改为 `httpx[socks]`，并显式声明 `requests[socks]`，分别提供 `socksio` 和 `PySocks`；yfinance 的 curl_cffi 使用其原生 SOCKS 能力。

## 6. 网络测试 API

新增 `POST /api/v1/settings/markets/{market}/network-test`，请求体仅包含 `symbol`。

- 服务端读取当前已保存配置和对应 Provider Registry 快照；客户端不能提交代理地址或 Provider，避免把接口变成任意网络代理。
- 按市场校验并构造 Instrument：股票/ETF Symbol 或加密裸交易对；加密货币使用已保存 Provider 决定 exchange。
- 以单调时钟测量耗时，使用现有超时边界执行一次有界日线请求，回溯窗口只用于拿到最新一根可用日线。这里刻意复用正式同步的 `fetch_daily` 路径，确保测试覆盖同一 OHLCV Provider、代理和初始化流程，而不是另选一个更简单的实时报价接口。
- 返回统一 envelope，data 中包含：`market`、`provider`、`symbol`、`connected`、`latency_ms`、`price`、`price_date`、`currency`、`error_type`、`detail`。
- 已处理的 Provider 故障以 HTTP 200 + `connected=false` 返回，使弹窗能稳定展示测试结果；请求成功但没有日线时同样为 `connected=false`、`error_type=NoDataAvailable`，因为本测试要求实际拿到价格。AKShare/Yahoo 锁被占用时立即返回 `connected=false`、`error_type=ProviderBusy` 和“数据源正在使用中，请稍后重试”，不等待。输入错误仍返回 422，内部异常仍走统一 500。
- 网络测试归入 compute rate-limit bucket。
- 测试结果不持久化。

## 7. 前端设置页与弹窗

### 7.1 Group 布局

第一行水平对齐“数据源”和“请求超时”；第二行单独展示“代理设置”：

```text
数据源 [Select]        请求超时（秒） [InputNumber]
代理设置 [Proxy URL Input........................]
[网络测试]
```

- 网络测试按钮始终显示；只读时可用，编辑或保存 pending 时明确禁用。
- 编辑时代理输入可编辑，并保留现有保存/放弃和各 Group 独立草稿行为。
- 保存仍只提交当前 Group 的不可变更新，其他 Group 草稿不受影响。
- `SettingsPage` 继续负责现有保存管线；Modal 与测试 mutation 由 `MarketSettingsForm`/独立子组件拥有，测试不得发出 settings PUT 或增加 revision。

### 7.2 NetworkTestModal

按市场保存当前输入、测试 pending 和最近一次结果。

- 打开时使用默认 Symbol/交易对；允许修改，空值或格式错误时禁止开始测试。
- 开始测试后按钮 loading，避免重复提交；关闭弹窗时取消视图更新，不中断已发出的服务端请求。
- 成功展示绿色连通状态、耗时、最新价、币种和价格日期。
- 失败展示红色连通状态、耗时、错误类型和脱敏详情；`ProviderBusy` 使用独立的警告提示“数据源正在使用中，请稍后重试”，不显示为上游不可用，也不等待。
- 再打开同一市场时重置为默认标的和空结果，避免过期结果被误认为当前状态。
- Modal 使用独立 `rootClassName`，确保 portaled 输入、按钮和结果状态沿用现有深色主题，而不依赖 `.market-group` 的 DOM 后代关系。

## 8. Task 历史日志

- 日志级别使用独立 Tag：INFO 为蓝色 processing，ERROR 为红色 error；其他级别使用可扩展映射。
- 消息列在通用消息下方展示白名单上下文：`symbol` 或 `universe_code`、`error_type`、`detail`；成功日志可展示 `bar_count`。
- 不直接渲染整个 context JSON，不展示代理、配置快照或未知字段。
- 后端改进结构化 detail，前端负责清晰呈现，二者缺一不可。

## 9. 测试与验收

遵循 RED → GREEN → REFACTOR：

1. Content-Type 多值白名单、真实 text/plain fixture、HTML 拒绝。
2. Binance 不加载非现货市场；AKShare 限流类型与安全 detail；空 Universe 明确日志。
3. 代理 URL 校验、旧配置默认 null、不同市场 Provider 代理隔离、无全局环境变量变化。
4. 网络测试四种市场的成功/空数据/限流/超时/非法 Symbol、耗时与统一响应、无持久化。
5. 前端 Group 布局、编辑状态按钮禁用、弹窗默认值与编辑、成功/失败结果、API decoder。
6. Task 日志上下文展示和 INFO/ERROR Tag 样式。
7. 后端全量 pytest + coverage、前端全量 Vitest + coverage、TypeScript/Vite build、Playwright 关键流程。
8. 有界真实验证：Invesco/SOXX Universe、Binance BTC/USDT、网络测试最新价；A 股公共上游若仍限流，保留真实失败证据，不伪造成功。

## 10. 调研结论与验收边界

- 已根据本机安装版本源码确认 AKShare/yfinance 的全局代理状态、CCXT/httpx 的实例代理能力，以及 BaoStock 的 raw TCP 限制。
- SOCKS 依赖通过 `httpx[socks]` 与 `requests[socks]` 显式安装；离线测试覆盖四种 scheme，真实 SOCKS 验收取决于本机是否提供可用代理，不虚构代理成功记录。
- GitHub CLI 复用检索因本机未登录而不可用；实施以项目现有模式和上述主库源码为依据，不引入未经审查的新框架。
- 公共数据源可用性不属于可控 SLA。代码修复消除确定的适配错误，准确呈现真实限流/网络失败，并保证失败时已有数据不被破坏。
