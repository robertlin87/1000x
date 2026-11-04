# 项目交接文档（2026-11-04）

接手开发前必读。**逻辑规则与里程碑的唯一权威来源是 [docs/PLAN.md](PLAN.md)**（已批准实施计划），本文件只记录 PLAN 之外的增量：当前进度、已实现代码的设计决策、环境坑、下一步任务。运行命令见 [README](../README.md)。

## 项目是什么

币圈 Telegram 私密信号群 → 自动解析报单 → 交易所永续合约全自动跟单。用户用自己的 TG 账号（userbot）登录监听私密群，被踢出群即失效（群资格即授权）。主触发 = 交易所挂单价格成交；群消息（新消息 + 原帖编辑）作为备份核对与人为操作指令通道。

**产品名（2026-11-04 定调）**：软件显示名 =「加密林教头VIP跟单助手」（GUI 窗口标题/欢迎语/报告标题）；**所有文件/文件夹/路径必须英文**（用户明确要求：exe 名 autotrade、报告文件 autotrade-report-*.txt、temp 目录）。

## 当前进度（2026-11-04）

- **M1/M2 完成**：双通道监听 + 模板解析（含訂單修改/千分位价格）+ 幂等事件层 + 风控 + Bybit 执行层真实验证（主网极小单）
- **六家交易所适配完成开发**（Bybit 生产 / Binance / Bitget / Gate / Deepcoin / Bitunix 手写 REST）——**除 Bybit 外待用户逐家实测**，详见「多交易所接入」
- **用户问题报告功能完成**：日志落盘 temp + 每日清理 + 一键导出报告（去重/脱敏），详见「用户问题报告」
- **下单倍数 + 手数上下限**（取代 trial_min_qty，向导已改）——用户 2026-11-04 确认的规则
- **信号群锁定**：「加密林教頭 VIP群」固定，向导登录后自动验群资格
- **代理探测式自动检测**（2026-11-04 最终版）：注册表旧值失效自动扫常见端口找活端口，VPN 换端口零配置
- 单测 **101 个全过**；GitHub 已发布 V1.0（53cabaf），本次交接将提交 V1.1
- 交易所现状：INJ 试运行仓位仍在（2.7 张 + SL 6.782 + 4 档 TP），等用户决定保留或平掉

## 环境（必读，踩过的坑）

- **本机有两个 Python（3.12 与 3.15），PATH 重启后会漂移** → 一律用 `.venv`（固定 3.12）：`./.venv/Scripts/python.exe ...`。3.15 无 ccxt 依赖（cryptography→cffi）的预编译 wheel
- **网络（TG + 交易所）**：大陆直连超时/被墙。**Python 不走 Windows 系统代理**，必须走代理。**已实现探测式自动检测（见 `proxy.py`，2026-11-04 最终版）**：注册表 `ProxyServer` 的端口先探测存活（用户 VPN 重启会换端口，注册表值会过期），死了自动扫常见端口（7897/7890/10808/10809/17890）找活端口；全不活则直连。**用户换代理/IP/端口零配置，勿再写死端口**。`config.yaml` 里 `telegram.proxy.enabled` 与 `exchanges.proxy.enabled` 均为 `false`（= 自动检测）
- **Telethon 1.45 代理写法**：proxy_type 直接用字符串 `"http"/"socks5"`（旧版 `telethon.network.connection.common.ProxyTypes` 路径已移除）；代理建立需 `python-socks`（已加进 pyproject 依赖）
- **Telethon 心跳 60s vs 代理空闲超时**：默认 keepalive ping 间隔 60s，而本地代理对空闲长连接约 60s 超时，两者撞车导致每 60s 断连刷 `Server closed the connection`。已在 `telegram_userbot.py` 用 `_patch_keepalive_interval()` monkey-patch 把 ping 间隔降到 30s
- **Telethon 单循环铁律（2026-11-04 踩坑）**：同一个 TelegramClient 实例**禁止跨事件循环复用**——第二次 `asyncio.run()` 用同一 client 会报 `the asyncio event loop must not change after connection`。GUI 里登录+验群必须写进一个 async 函数、一次 `asyncio.run` 完成（wizard.py 已按此实现，勿改回两个 asyncio.run）
- **exe 数据目录**：打包版一切数据（config/session/temp 日志/data 库）在 `%APPDATA%\autotrade\`，**不是源码文件夹**；exe 的日志在 `%APPDATA%\autotrade\temp\`。改代码后必须重新 `PyInstaller autotrade.spec --noconfirm`（打包前要确认用户已关闭正在运行的 exe，否则文件锁报 PermissionError）
- **Bybit API key 必须「读写（Read-Write）」**：只读能查余额/持仓，但 `set_leverage` 返回 `10005`
- **充值进「资金账户」**，合约交易要「统一交易账户」→ 需在 Bybit 手动划转，否则 `fetch_equity=0`
- `config/config.yaml`（项目根）含真实 key，**不入库、不进打包产物**；`autotrade_session.session` = TG 账号完全控制权，勿删勿外传
- `start_listen.bat` / `start_run.bat` / `install.bat` 必须纯 ASCII（cmd 用 GBK 读）；终端中文 `sys.stdout.reconfigure(utf-8)`
- `data/messages.jsonl` 真实采集（勿污染）；`data/replay*.db` 测试产物可删

## 代码设计决策（PLAN 之外的增量，改代码前先读）

### M1 解析层

- 解析器模板驱动，加载 `config/templates/*.yaml`；`op_lines.yaml` 多 `ops_header` 字段（OpParser 独立切「操作記錄」段）
- **幂等键** `op_line_hash` = sha1(`action_type|tp_index|price`)，unknown 行按原文；编辑行与新消息通知跨通道同一事件只触发一次
- `EntryParser.validate()` 只返回告警不硬拒（硬 reject 在风控层）
- `upsert_signal` 用 `INSERT OR IGNORE` + rowcount 判新旧

### M2 执行层 + Bybit ccxt 特有坑（真实验证，务必保留）

- **symbol 映射**：ccxt 里 Bybit USDT 永续是 `BASE/USDT:USDT`（不是 `BASEUSDT`），`BybitAdapter.to_ccxt_symbol()` 转换；币不存在 `fetch_market` 抛 ValueError → 跳过告警
- **现货名 vs 永续名不一致**：`_SYMBOL_ALIASES` 映射表（如 `PUMP` 现货 → `PUMPFUN` 永续），遇到报单币在 Bybit 永续找不到时先查这里加映射
- **contractSize 实测 = 1.0**（多数山寨币），`fetch_market` 动态读
- **随单附 SL 用 `params["stopLoss"]`（attached），不用 `stopLossPrice`**：后者走 trigger-order 分支，`triggerDirection` 方向错（Bybit 报 `110092 expect Rising`）
- **移动止损走 trading-stop 端点**：ccxt bybit 无 `set_stop_loss`，改持仓 SL 用 `create_order(..., params={"stopLossPrice": x, "tradingStopEndpoint": True, "accountType": "UNIFIED"})`（`/v5/position/trading-stop`）
- **`set_leverage` 幂等**：杠杆已是目标值报 `110043 leverage not modified`，已捕获忽略
- **统一账户参数**：set_leverage/下单/查持仓挂单带 `accountType=UNIFIED`、`category=linear`
- **fetch_equity**：从 UNIFIED 账户 `info.result.list[0].totalEquity` 取（coin 列表可能为空）
- `OrderManager.enter`：set_leverage → 开仓附 SL → 挂 n 档 TP reduce-only（前 n-1 档 floor、末档=剩余）；`close_all` 市价全平 + `cancel_all_for_symbol`
- `TriggerRouter.on_signal`：新报单→风控→进场；**手数规则（2026-11-04 用户确认）**：
  - **下单倍数** `risk.order_multiplier`（默认 1.0，向导可选 0.25/0.5/1/2/3/5）= 报单「控仓 x%」的 R 值缩放：`qty = floor(equity × R×倍数 ÷ |进場−止損| ÷ 合约倍数)`
  - **下限**：算出手数 < 交易所最低手数（amount.min 与 min_cost 折算取大者）→ 按最低手数 × TP档数 交易（保证每档能以最小手数出场）
  - **上限**：算出手数 > 交易所最高手数（amount.max）→ 按最高手数交易
  - 已取代旧的 trial_min_qty 试运行逻辑（配置与向导均已移除）
- `TriggerRouter.on_event`：close/all_tp/sl_hit/hedge_exit→全平+撤单、move_sl/hedge→移损、modify→跟随修改、tp_hit→纯信息（补单逻辑 TODO）
- `main.run()`：`dry_run=true` 用 NoopAdapter，否则 `factory.get_adapter` 接真实 Bybit

### 用户问题报告（2026-11-04 完成）

粉丝测试期报错收集：日志落盘 + 一键导出报告。

- **日志落盘**：`logfile.py` 的 `install_file_logging()` 挂 root logger → `temp/autotrade.log`（RotatingFileHandler 1MB×3）；调用点 main.run() 与 listen.py 开头（幂等可重复调）
- **每日清理**：`paths.cleanup_temp_dir()` 启动时删除 temp 内修改时间非今天的文件（用户规则：旧日志问题解决后无意义、用户不会自己删；跨天不重启则下次启动清）
- **报告**：`report.py` `collect_report()` 三段式（头部版本/系统/交易所名 → 错误摘要按 logger+消息前80字符聚合去重带次数 → 最近100行上下文），全篇密钥脱敏（config 的 apiKey/secret/passphrase/api_hash → ***）；`write_report_file()` 写 `temp/autotrade-问题报告-时间戳.txt`
- **入口**：GUI 运行窗口「导出问题报告」按钮（生成后自动打开 temp 文件夹）；CLI `scripts/report.py`
- **崩溃兜底**：`app.py` 挂 sys.excepthook/threading.excepthook 把未捕获异常写进日志
- 原始日志不去重（审计），去重只发生在报告层

### 多交易所接入（2026-11-04 完成开发，待用户逐家实测）

六家交易所：Bybit（生产）/ Binance / Bitget / Gate / Deepcoin / Bitunix。

- **字段规则**：Binance/Gate/Bitunix = apiKey+secret；Bitget/Deepcoin = 还要 passphrase（ccxt 的 password 参数）；Bitunix ccxt 4.5.91 无支持 → 手写 REST（bitunix_rest.py，端点/签名为官方 demo 版，**需实测确认字段**）
- **向导动态表单**：`exchange/schemas.py` 的 `EXCHANGE_SCHEMAS`（字段+注意事项文案）驱动 `gui/wizard.py` 动态渲染；无 testnet（用户明确：面向真实用户）
- **OrderManager 分支**：`capabilities.supports_attached_sl`——attached（仅 Bybit）随单附 SL；非 attached（其余 5 家）开仓后 `attach_sl_tp` 挂独立 SL 触发单（reduce-only，数量=当前持仓）
- **非 attached 的移动止损**：撤旧触发单 + 按新价重挂（各家无改 SL 端点）
- **自检**：`scripts/selfcheck.py --exchange <name> [--readonly] [--symbol]` 走生产同款 OrderManager 全路径（开仓→挂TP→移损→全平清理）
- **待用户实测确认的点**（代码有「实测」注释标记）：各家 TP/SL 触发单参数（stopPrice/triggerPrice）、set_leverage 模式（Binance 暂 CROSS）、Deepcoin set_leverage 支持性、Bitunix 全部端点字段名、Gate 单向持仓前提
- 风险：未过 selfcheck 的所不进 factory 白名单（工厂抛错拦截）；币种在目标所不存在 → fetch_market ValueError 跳过告警（已有兜底）

### 产品化架构（新增，2026-11-03）

- **`proxy.py`**：`resolve_proxy(cfg_proxy, default_type)` → `(type, addr, port)` 或 None（直连）。优先级：config 显式 enabled → **探测式**系统代理（注册表 ProxyServer 端口存活即用，死了扫常见端口，全死直连）。TG 用 `default_type="socks5"`（长连接），交易所用 `"http"`（ccxt/requests 短连接）
- **`paths.py`**：外部目录。`getattr(sys, "frozen", False)` 区分打包/开发：打包后写 `%APPDATA%/autotrade/`（config/session/data/logs/temp），开发用项目根；`temp_dir()` + `cleanup_temp_dir()`（每日清理）已接入启动流程
- **`signal_source/telegram_userbot.py`**：`login()` 可注入 `prompt` 回调（`Callable[[str], str]`，默认 input），返回 me，连接 30s 超时（超时给中文提示）；`check_authorized()` / `check_group_access()` 新增；信号群锁定（constants）
- **`gui/` 包**（Tkinter/ttk，无新运行时依赖）：
  - `wizard.py`：4 步配置向导（欢迎→TG 登录+固定群验证→交易所（6 家动态表单）→风控与保存（下单倍数下拉）），收集配置写 YAML；**登录与验群在同一次 asyncio.run 内完成**（Telethon 单循环铁律）
  - `dialogs.py`：`GuiPrompter`（跨线程弹窗：后台线程 prompt() → queue → 主线程 `root.after` 轮询弹窗）；群选择已删除（群锁定）
  - `runner.py`：运行窗口（后台线程 `asyncio.run(main.run())` + 日志 Handler → queue → 主线程滚动显示）；顶部「重新配置」「导出问题报告」按钮
- **`app.py`**：入口。`paths.config_path()` 不存在 → 进向导；存在 → 直接 `RunnerWindow`
- **打包**：`run_app.py`（入口）+ `autotrade.spec`（onedir，`collect_all` ccxt/telethon/ruamel.yaml/aiosqlite）。产物 `dist/autotrade/`（autotrade.exe + _internal）。**分发要发整个文件夹（打 zip），不能只发 exe**
- **源码部署**：`install.bat`（检测 Python → venv → pip install -e . → 启动）
- **Tkinter 与 asyncio 集成要点**：GUI 主线程不得 await；asyncio 操作放后台线程，结果经 queue 回传，主线程 `root.after(100, poll)` 轮询

### 通知规则（与用户确认 2026-11-04，改动前先读）

- 紧凑通知全集（2026-11-04 用户确认）：`🔒 套保（SL → X）`→ amend SL 指令；`🟥 已平倉`（可带分析师文字、可无 📌 前缀）→ 全平+撤单指令；`❌ 止損 ➜ X` → 全平场景（SL 已触发，撤残留挂单）；`✅ 全部止盈` → 全平场景（撤残留挂单）；`🎯 TPn 達成 ➜ X` → 纯信息（TP1-3 部分平仓不撤单）；`✏️ 訂單修改` → **跟随逐项修改**（见下）
- **✏️ 訂單修改**（指令，2026-11-04 用户确认"分析师改什么我们改什么"）：紧凑通知头部后是「· 進場 X · TPn X · 止損 X」字段串；编辑通道是多行块（修改行后跟无 → 前缀的字段行）。`OrderManager.apply_modify` 只动变化项：某档 TP 变 → 撤旧档挂单按新价重挂（数量=原档）；SL 变 → amend；进場变 → 仅记录。安全守卫：旧挂单已不在（该档已成交）→ 跳过重挂；新价越过现价（会立即成交）→ 跳过。幂等键 `modify_hash` 按内容+时间戳归一（每次修改是独立事件，同一次修改两通道去重）。修改后 signals 表 tps/sl/entry 同步为最新值
- **千分位价格**：所有价格正则支持逗号（SNDK `1,358.97`），转换时 strip；进場/TP/SL/通知/操作行全链路
- 编辑通道 op_lines 同样有 sl_hit 行模板（`❌ 止損 ➜ X`），与通知通道语义哈希去重
- **全平后残留挂单必撤**（止損/末档 TP/全部止盈/手工平仓）；**TP1-3 部分平仓不撤单**
- `OrderManager.close_all`：无持仓但有 reduce-only 残留挂单时也撤
- `execution/watchdog.py`（兜底，事件通道为主）：每 30s（risk.watchdog_interval_sec）无状态全量查询——无持仓+有 reduce-only 残留 → 撤单（覆盖 TG 断线/程序重启错过通知）；**只有非 reduce-only 挂单 = 进场限价单还在等，不撤**
- `NoticeEvent` 新增 tp_index/price 字段；幂等哈希 `op_line_hash(action|tp_index|price)`，紧凑通知与编辑通道跨通道去重

### 信号群锁定（2026-11-04 用户业务要求）

信号群**固定为「加密林教頭 VIP群」**（`src/autotrade/constants.py` 的
GROUP_CHAT_ID/GROUP_CHAT_TITLE），不允许用户自定义——防止软件被用于监听
其他群。实现：

- `TelegramUserbotSource` 构造函数**不再接受** chat_title/chat_id 参数，内部
  固定用 constants；配置 yaml 里即使写 chat_id 也被忽略
- GUI 向导删除「选择群聊」步骤，登录后自动验证账号是否已加入锁定群
  （`check_group_access()`，CHANNEL_PRIVATE = 未加入/被踢，群资格即授权）；
  保存时再次验证，不通过禁止保存
- `dialogs.py` 的 choose_chat 已删除；`list_dialogs` 保留（仅开发用 `listen.py --list`）
- 注意：仓库公开，懂代码的人可自行改 constants 绕过——这是产品级约束，非防破解

### 无状态架构（与用户确认 2026-11-04，取代本地持仓表方案）

**交易所为唯一事实源，不维护本地持仓状态（重启零成本）**：

- 风控持仓列表：`TriggerRouter.on_signal` 实时 `fetch_all_positions()` 查交易所（反向信号/并发上限以此为准）
- 看护对账：Watchdog 无状态全量查询（`fetch_all_positions` + `fetch_open_orders`），不依赖 PositionTracker
- `PositionTracker` 类保留但管线不再使用（未来 GUI 展示可作缓存）；orders/positions 两张 DB 表不写入，审计靠日志
- 符号格式统一：`BybitAdapter.from_ccxt_symbol`（`INJ/USDT:USDT` ↔ `INJUSDT`，含 PUMP↔PUMPFUN 反向别名），否则风控/看护的 symbol 比对会错
- `ExchangeAdapter` 新增抽象方法 `fetch_all_positions()`；`signals`/`signal_ops` 表照旧（幂等去重核心，与持仓状态无关）
- M3 reconciler 因此大幅缩水：只剩 signal_ops 未处理事件重放

## 下一步任务

1. **五家新交易所逐家实测**：用户会逐个测试（`scripts/selfcheck.py --exchange <name>` 只读 → 真实小单全路径），报错按实际响应修 adapter 字段（代码有「实测」注释标记）
2. **INJ 试运行仓位处置**：等用户决定保留（有 SL+TP 保护）或手动平掉
3. **tp_hit 备份核对补单**：编辑通道 tp_hit 行目前只通知；动作前查交易所实态的补单逻辑待真实数据细化
4. 真实回推通知（Notifier 接 TelegramClient）
5. （缩水版）M3：signal_ops 未处理事件重放（持仓对账已被无状态架构替代）
6. **暂缓事项（用户明确说不做，勿主动再提）**：AI 兜底解析、确定性下单复核、orders/positions/events 落库

## 验证

- 单测：`.venv\Scripts\python -m unittest discover -s tests`（**101 个**）
- 应用（GUI）：`.venv\Scripts\python run_app.py`（首次进向导，已配置直接监听）
- 打包：`.venv\Scripts\python -m PyInstaller autotrade.spec --noconfirm`（产物 `dist/autotrade/autotrade.exe`；**打包前确认用户已关闭运行中的 exe**）
- 回放：`.venv\Scripts\python scripts\replay.py --input data/messages.jsonl`
- 交易所自检：`.venv\Scripts\python scripts\selfcheck.py --exchange <name> [--readonly] [--symbol]`
- 问题报告：`.venv\Scripts\python scripts\report.py`
