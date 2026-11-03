# 实施计划（备份）

> 本文件为已批准实施计划的备份副本（批准日期 2026-10-31）。

# Telegram 信号自动跟单机器人 — 实施计划

## Context

用户运营币圈 Telegram 私密信号群，交易员以统一格式发布永续合约报单（进场价/现价或挂单/杠杆/保证金%/TP1-4/SL/分析师），单笔风控 ≤ equity 2%。要做成产品：软件监听群消息全自动跟单；VIP 用自己的 TG 账号进群即可用，被踢出群即失效（**群资格即授权**）。仓库 e:\VibeCoding 为空（greenfield）。

## 可行性结论（已完成 GitHub 调研）

完全可行。参考项目：[amirphl/Telegram-Trading-Bot](https://github.com/amirphl/Telegram-Trading-Bot)（Telethon+CCXT 信号跟单，最接近）、[adiel098/Telegram-AutoTrade-Bot](https://github.com/adiel098/Telegram-AutoTrade-Bot)（TG→Binance 自动交易）、[aradotso/binance-futures-signal-bot](https://www.claudepluginhub.com/skills/aradotso-aradotso-trending-skills-37/binance-futures-signal-bot)、[DePacifier/BitgetLiveTrader](https://github.com/DePacifier/BitgetLiveTrader)、[ngzhenghui94/CryptoTrading](https://raw.githubusercontent.com/ngzhenghui94/CryptoTrading/refs/heads/main/README.md)。授权门槛（getChatMember 校验成员）是 Telegram 生态标准做法。

**前提：群必须是私密群**——私密群被踢后失去全部消息访问权（CHANNEL_PRIVATE），授权严格成立；公开群被踢者仍可轮询历史，授权被绕过。

## 已确认决策

- **交易所四家全做**（Bitget/Bybit/Deepcoin/Bitunix），ccxt 统一引擎，MVP 先 Bybit；Bitunix 实测 ccxt 不支持则手写 REST 接同一接口
- **品种**：永续合约；**分析师白名单配置，默认全部**（已见 Lazycat、Trader X）
- **授权架构 A 先做**（每个 VIP 自己的 TG 账号 userbot 监听，被踢即失效），signal_source 抽象层预留 B（官方 Bot + getChatMember + API 推送）
- **触发模型（用户明确）**：
  - **主触发 = 报单价位**：进场即在交易所挂 SL + TP1-4 reduce-only 限价单，价格碰到自动出场，不依赖后续消息
  - **操作記錄/操作通知 = 安全冗余备份**：核对"该出场的是否已出场"，没出场就补出场一次
  - **人为操作 = 指令（两类）**：① 移动保本/套保 → 跟着 amend SL；② 手工平仓 → 跟着全平剩余 + 撤该 symbol 挂单。任一通道（新消息或编辑）出现即执行
- **TP 分批均分**：n 档各 1/n；手数精度不能均分时前 n-1 档向下取整，末档平掉全部剩余；SL 或最终 TP 触发 → 平剩余 + 撤销该 symbol 全部挂单
- **手数公式（用户指定）**：`张数 = equity × R% ÷ |建仓价 − 止损价| ÷ 合约倍数`。R% = 报单"控仓维持 x% 风控"的 x；**合约倍数 = 各交易所每张合约的币数**（内部变量，从市场信息取，ccxt `market['contractSize']`，各所不同）；向下取整。保证金额%（报单中）作为上限复算校验。
- **双通道监听**：手工操作时群会**同时**发一条紧凑新消息（如 `📌訂單 188 GIGGLEUSDT 做多 🟥 已平倉`）**并**编辑原报单追加操作記錄行。两条通道都监听，互为备份，统一事件层幂等去重。

## 真实报单样例（已收 7 条 → tests/fixtures/messages/）

报单：订单216 LITUSDT 做多 / 213 ATOMUSDT 做多 / 196 C98USDT 做空 / 359 DUSKUSDT 做多 / 353 ASTERUSDT 做多 / 188 GIGGLEUSDT 做多 / 187 SYNUSDT 做空。

**报单字段**：訂單ID、币种、📈做多/📉做空、進場价+現價/掛單、槓桿、保證金%（`≤x%` 或 `x%（上限）`）、TP1-4、SL、風控行（止損距離% → 控倉%）、分析師。消息随进展被原帖编辑，追加「操作記錄」行（带时间戳）。

**操作記錄行类型**（编辑通道）：

| 行 | 类型 | 动作 |
|---|---|---|
| `🎯 TPn 達成 ➜ 价` | 记录 | 核对该档 TP 单已成交；未成交 → 市价补平该档 |
| `✅ 全部止盈` | 记录 | 仓位尚在 → 全平剩余 + 撤该 symbol 挂单 |
| `🔒 自動移損 ➜ 价（TPn 後）` | 指令 | amend SL 至该价 |
| `🔒 套保（SL → 進場價 X）` | 指令 | amend SL 至 X（放保本单） |
| `🔒 套保出場 ➜ 价` | 记录 | 保本单被扫出场；核对仓位，尚在则补平 |
| `🟥 已平倉` / `平仓` 字样 | 记录+指令 | 手工平仓：全平剩余 + 撤该 symbol 挂单 |
| `💬 …`（分析师备注） | 备注 | 忽略，仅落库 |

**紧凑新消息**（新消息通道，与编辑同时出现）：`📌訂單 (\d+) ([A-Z0-9]+)USDT (做多|做空) 🟥 已平倉`（可带 `💬` 备注行）。手工平仓/手工保本等操作均以此双通道出现；套保类紧凑消息变体待采样，模板可扩展。

**手数公式验证**（订单216）：equity=1000 → 1000×2% ÷ |3.042−2.962| = 250 LIT 币 ≈ 250 张（合约倍数为 1 时）。保证金额复算：2% ÷ (2.63%×10) = 7.6% ✓ 与报单 ≤7.61% 吻合。

## 技术栈

Python 3.11+（本机 3.15 满足）；Telethon；ccxt；SQLite（aiosqlite）；PyYAML；pyinstaller 打包。**多交易所统一引擎**：下单/改单/平仓逻辑写一遍，换所换配置（passphrase、IP 白名单、TP/SL 挂法、精度与合约倍数）。

## 实施方案

### 目录结构

```
e:\VibeCoding\
├─ pyproject.toml
├─ config\config.example.yaml
├─ config\templates\entry.yaml        # 报单模板（繁体原样）
├─ config\templates\notice.yaml       # 紧凑操作通知模板（新消息）
├─ config\templates\op_lines.yaml     # 操作記錄行模板
├─ src\autotrade\
│  ├─ main.py   config.py
│  ├─ signal_source\base.py               # SignalSource ABC（架构 B 插入点）
│  ├─ signal_source\telegram_userbot.py   # NewMessage + MessageEdited
│  ├─ signal_source\bot_api.py            # 架构 B 占位
│  ├─ parser\entry_parser.py  notice_parser.py  op_parser.py  llm_fallback.py
│  ├─ risk\engine.py  precision.py
│  ├─ exchange\base.py  bybit.py  bitget.py  deepcoin.py
│  │  bitunix_ccxt.py  bitunix_rest.py  factory.py
│  ├─ execution\order_manager.py  position_tracker.py  reconciler.py
│  ├─ storage\db.py   notify\notifier.py   wizard.py
├─ tests\fixtures\messages\*.txt
└─ scripts\run.py
```

`signal_source/base.py` 接口：`start(handler: Callable[[RawMessage], Awaitable[None]])`；RawMessage 含 chat_id/msg_id/text/is_edit。架构 B 同接口实现，执行引擎零改动。

### 数据流

`Userbot(NewMessage+MessageEdited) → 三类解析器 → 统一事件层(signal_ops 幂等) → TriggerRouter（主=交易所挂单价格触发 / 备=事件核对补单）→ OrderManager(ExchangeAdapter) → PositionTracker → Notifier`

- 新消息：报单模板 → 新单；紧凑通知模板 → 手工操作事件
- 编辑消息：原报单全文重新解析 → 操作行差量事件
- 两通道事件统一去重（见 SQLite）

### SQLite（storage/db.py）

- `signals`：去重键 `UNIQUE(chat_id, order_id)`，编辑事件按 order_id upsert 更新 raw_text；字段含 analyst/symbol/side/entry/is_limit/leverage/sl/tps_json/margin_pct/risk_pct/stop_dist_pct/status
- `signal_ops`（统一事件层）：`UNIQUE(chat_id, order_id, line_hash)`，source∈{edit, notice}，action_type∈{tp_hit, all_tp, move_sl, hedge, hedge_exit, close, unknown}，processed 标志——**编辑行与新消息通知都进此层，仅新增事件触发动作**
- `orders` / `positions`（tp_hit_count、remaining_qty）/ `events`（审计）

### 解析器（parser/）

- `entry.yaml`：繁体模板 `訂單(\d+)\s*([A-Z0-9]+)USDT\s*(做多📈|做空📉)…進場[:：]([\d.]+)(現價|掛單)` + 可选组（槓桿/保證金/SL/TP1-4/風控/分析師）；symbol_map 映射 ccxt symbol；做空校验 TP < entry < SL
- `notice.yaml`：`📌訂單 (\d+) ([A-Z0-9]+)USDT (做多|做空) 🟥 已平倉`（+可选 `💬` 行）；套保类紧凑变体待采样后补模板
- `op_lines.yaml`：上表行模板，容忍行尾时间戳与 `（TP1 後）` 注记；`💬` 行忽略；未匹配行落 unknown 供模板补齐
- LLM 兜底（可选）：模板未命中时 OpenAI JSON 输出同 Signal/Event 结构

### 风控引擎（risk/engine.py）

- **张数 = floor(equity × R% ÷ |entry − stop| ÷ contractSize)**（用户指定公式）；minNotional/最小下单量校验
- 保证金复算校验：`|margin_pct − R%/(stop_dist_pct×leverage)| ≤ 0.1%`，超差 reject 通知；保证金% 上限同样生效
- 分析师白名单、同 symbol 反向信号 reject、并发持仓/日亏上限（配置）

### 执行与状态机（execution/）

state ∈ {PENDING, FILLED, PARTIAL_TP, BREAKEVEN, CLOSED, CANCELED, UNKNOWN}

- **进场**：set_leverage → 市价/限价开仓 → **挂 SL + n 档 TP reduce-only 限价单**（档位：floor 均分，末档 = 总量 − 前档合计）→ 主触发通道即建立，此后不依赖 Telegram
- **主触发（价格）**：TP 档成交 → 记录 tp_hit_count；SL 触发或末档 TP 成交 → 撤该 symbol 其余挂单，state=CLOSED
- **备份触发（事件核对，每次动作前先查交易所实际状态再决定）**：
  - `🎯 TPn 達成`：该档 TP 单未成交/减仓不足 → 市价补平该档（滑点阈值校验）
  - `🔒 自動移損 / 套保（SL → X）`：当前 SL ≠ X → amend SL 至 X（可反复 = 移动止损），state=BREAKEVEN
  - `🟥 已平倉 / 全部止盈 / 套保出場`：仓位尚在 → 市价全平 + 撤该 symbol 全部挂单；已被交易所平掉 → 仅记录（手工平仓为人为操作指令，双通道任一出现即执行）
- 幂等：事件层 UNIQUE + 动作前查 position/open_orders 实态；改单失败重试 3 次 → 降级市价平仓 → 高优先级告警
- **reconciler**：重启时 DB 非终态持仓与交易所 fetch_positions/open_orders 对账（DB 有、交易所无 → CLOSED，人工平仓场景）；signal_ops 未处理事件重放

### 交易所适配层（exchange/）

ExchangeAdapter ABC：fetch_equity / fetch_market(contractSize) / set_leverage / create_order(带 sl/tp) / attach_sl_tp / amend_order / cancel_order / cancel_all_for_symbol / fetch_position / fetch_open_orders + capabilities（supports_attached_sl）。

- **Bybit（MVP）**：统一账户、随单附 TP/SL，先 testnet
- **Bitget**：必填 passphrase；TP/SL 独立挂载
- **Deepcoin**：实测精度、合约倍数与部分成交后的挂单行为
- **Bitunix**：探测 ccxt.bitunix，无则手写 REST（HMAC 签名）实现同一 ABC

### 里程碑

- **M1**：骨架 + userbot（新消息+编辑双通道）+ 三类解析器 + SQLite 统一事件层，dry_run 只记录通知。验收：7 条样例 + 双通道重复触发 fixtures 解析率 ≥95%，同一事件只触发一次
- **M2**：risk + order_manager + Bybit testnet → 主网最小仓，跑通「TP 档价格触发 → 移损 → 全平」主链路 + 事件备份补单
- **M3**：套保/移损 amend SL、手工平仓双通道核对、断线恢复、events 审计
- **M4**：Bitget → Deepcoin → Bitunix 逐个接入（每家跑同一 paper 脚本）
- **M5**：pyinstaller 打包 + wizard.py（TG 登录、key 输入、连通自检）→ VIP 分发

## 验证方案

1. **单测**：fixtures 真实原文断言 Signal/Event 全字段（繁体/📈📉/时间戳/💬 忽略）；双通道同一操作重复出现只触发一次；手数公式参数化（7 样例）
2. **dry-run**：NoopAdapter 全链路不碰交易所，回放真实群消息
3. **paper**：Bybit testnet；无 testnet 的所用内存撮合（模拟部分成交/改单失败/双通道竞态）
4. **实盘**：最小仓限价远挂验证「挂单→撤→成交→TP/SL 价格触发→套保改单→手工平仓」全路径，再放开 2% 风控实盘

## 风险清单

- **TG 封号**（userbot 违反 ToS）：老号、只监听不回复、重连退避；架构 B 为最终形态
- **私密群前提**：启动时校验群类型；被踢即失效是授权设计本身
- **双通道重复触发**：统一事件层 UNIQUE + 动作前查交易所实态，杜绝双卖
- **断线/重启**：Telethon 自动重连 + 交易所端 TP/SL 主触发兜底 + reconciler 对账
- **编辑竞态**：UNIQUE 约束 + 事务；**部分成交**：改单按剩余量；**滑点**：max_slippage 拒绝
- Deepcoin/Bitunix 行为未知（含合约倍数）：paper 全路径验证后方可实盘
- 大陆 +86 无法注册 TG；交易所 key 只开交易权限 + IP 白名单；信号截图外泄技术上无解
