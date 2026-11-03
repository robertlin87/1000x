# 项目交接文档（2026-11-03）

接手开发前必读。**逻辑规则与里程碑的唯一权威来源是 [docs/PLAN.md](PLAN.md)**（已批准实施计划），本文件只记录 PLAN 之外的增量：当前进度、已实现代码的设计决策、环境坑、下一步任务。运行命令见 [README](../README.md)。

## 项目是什么

币圈 Telegram 私密信号群 → 自动解析报单 → Bybit 永续合约全自动跟单。用户用自己的 TG 账号（userbot）登录监听私密群，被踢出群即失效（群资格即授权）。主触发 = 交易所挂单价格成交；群消息（新消息 + 原帖编辑）作为备份核对与人为操作指令通道。

## 当前进度

- **M1 完成**：双通道监听 + 三类解析器 + SQLite 统一事件层 + dry-run 管线
- **M2 完成 + 交易链路真实跑通**（主网极小单 ~5U）：风控 `validate()`、精度、`BybitAdapter`、`OrderManager`、`PositionTracker`、`TriggerRouter`、接线全部实现并真实验证（开仓附 SL、挂 n 档 TP reduce-only、移动止损、撤单平仓）
- **产品化完成**（2026-11-03）：GUI 配置向导 + 打包 exe + 代理自动检测，详见下文「产品化架构」
- **尚未接真实信号**：`config.yaml` 当前 `dry_run: false`（真实下单）+ `trial_min_qty: true`（试运行最小手数×TP档数）
- **通知规则确认并实现（2026-11-04）**：紧凑通知 hedge/close = 指令执行、tp_hit/all_tp = 纯信息；全平后残留挂单必撤（close_all + Watchdog 轮询）。真实样例回放验证：TP2 紧凑通知与编辑通道正确幂等去重
- **交易所现状**：INJ 试运行仓位仍在（2.7 张 + SL 6.782 + 4 档 TP），等用户决定保留或平掉；PUMP 已平无残留
- 单测 **74 个全过**

## 环境（必读，踩过的坑）

- **本机有两个 Python（3.12 与 3.15），PATH 重启后会漂移** → 一律用 `.venv`（固定 3.12）：`./.venv/Scripts/python.exe ...`。3.15 无 ccxt 依赖（cryptography→cffi）的预编译 wheel
- **网络（TG + Bybit）**：大陆直连超时/被墙。**Python 不走 Windows 系统代理**，必须走代理。**已实现自动检测（见 `proxy.py`）**：读注册表 `HKCU\...\Internet Settings` 的 `ProxyServer`，动态拿端口，不写死（用户 VPN 重启端口会变，曾从 7897 变 17890）。`config.yaml` 里 `telegram.proxy.enabled` 与 `exchanges.proxy.enabled` 均为 `false`（= 自动检测）
- **Telethon 1.45 代理写法**：proxy_type 直接用字符串 `"http"/"socks5"`（旧版 `telethon.network.connection.common.ProxyTypes` 路径已移除）；代理建立需 `python-socks`（已加进 pyproject 依赖）
- **Telethon 心跳 60s vs 代理空闲超时**：默认 keepalive ping 间隔 60s，而本地代理对空闲长连接约 60s 超时，两者撞车导致每 60s 断连刷 `Server closed the connection`。已在 `telegram_userbot.py` 用 `_patch_keepalive_interval()` monkey-patch 把 ping 间隔降到 30s
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
- `TriggerRouter.on_signal`：新报单→风控→进场（`trial_min_qty=true` 时 qty = 最小手数 × TP档数，见 `risk.precision.calc_min_qty`）；`on_event`：close/all_tp/hedge_exit→全平、move_sl/hedge→移损、tp_hit→备份核对（补单逻辑 TODO）
- `main.run()`：`dry_run=true` 用 NoopAdapter，否则 `factory.get_adapter` 接真实 Bybit

### 产品化架构（新增，2026-11-03）

- **`proxy.py`**：`resolve_proxy(cfg_proxy, default_type)` → `(type, addr, port)` 或 None（直连）。优先级：config 显式 enabled → Windows 系统代理（winreg，读 ProxyServer 不依赖 ProxyEnable 开关）→ None。TG 用 `default_type="socks5"`（长连接），Bybit 用 `"http"`（ccxt/requests 短连接）
- **`paths.py`**：外部目录。`getattr(sys, "frozen", False)` 区分打包/开发：打包后写 `%APPDATA%/autotrade/`（config/session/data/logs），开发用项目根。`main.run()` 已接入（config/db/session 路径）
- **`signal_source/telegram_userbot.py`**：`login()` 改为可注入 `prompt` 回调（`Callable[[str], str]`，默认 input），返回 me；`check_authorized()` 新增；`_build_proxy()` 走 `resolve_proxy`
- **`gui/` 包**（Tkinter/ttk，无新运行时依赖）：
  - `wizard.py`：5 步配置向导（欢迎→TG 登录→选群→交易所→保存自检），收集配置写 YAML
  - `dialogs.py`：`GuiPrompter`（跨线程弹窗：后台线程 prompt() → queue → 主线程 `root.after` 轮询弹窗）、`choose_chat` 群选择
  - `runner.py`：运行窗口（后台线程 `asyncio.run(main.run())` + 日志 Handler → queue → 主线程滚动显示）
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

### 无状态架构（与用户确认 2026-11-04，取代本地持仓表方案）

**交易所为唯一事实源，不维护本地持仓状态（重启零成本）**：

- 风控持仓列表：`TriggerRouter.on_signal` 实时 `fetch_all_positions()` 查交易所（反向信号/并发上限以此为准）
- 看护对账：Watchdog 无状态全量查询（`fetch_all_positions` + `fetch_open_orders`），不依赖 PositionTracker
- `PositionTracker` 类保留但管线不再使用（未来 GUI 展示可作缓存）；orders/positions 两张 DB 表不写入，审计靠日志
- 符号格式统一：`BybitAdapter.from_ccxt_symbol`（`INJ/USDT:USDT` ↔ `INJUSDT`，含 PUMP↔PUMPFUN 反向别名），否则风控/看护的 symbol 比对会错
- `ExchangeAdapter` 新增抽象方法 `fetch_all_positions()`；`signals`/`signal_ops` 表照旧（幂等去重核心，与持仓状态无关）
- M3 reconciler 因此大幅缩水：只剩 signal_ops 未处理事件重放

## 下一步任务

1. **INJ 试运行仓位处置**：等用户决定保留（有 SL+TP 保护）或手动平掉
2. **git 整理**：V 1.0 之后大量改动未提交（含 staged/unstaged 混合），`.codebuddy/` 需 gitignore
3. **tp_hit 备份核对补单**：编辑通道 tp_hit 行目前只通知；动作前查交易所实态的补单逻辑待真实数据细化
4. **主触发（价格）实盘验证**：TP 档成交、SL 触发、末档 TP 成交 → Watchdog 撤残留挂单
5. 真实回推通知（Notifier 接 TelegramClient）
6. 产品化端到端验证：`dist/autotrade/autotrade.exe` 向导全流程
7. （缩水版）M3：signal_ops 未处理事件重放（持仓对账已被无状态架构替代）

## 验证

- 单测：`.venv\Scripts\python -m unittest discover -s tests`（**63 个**）
- 应用（GUI）：`.venv\Scripts\python run_app.py`（首次进向导，已配置直接监听）
- 打包：`.venv\Scripts\python -m PyInstaller autotrade.spec --noconfirm`（产物 `dist/autotrade/`）
- 回放：`.venv\Scripts\python scripts\replay.py --input data/messages.jsonl`
- Bybit 自检（只读/真实极小单自动清理）：`.venv\Scripts\python scripts\selfcheck.py [--readonly]`
