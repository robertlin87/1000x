# autotrade — Telegram 信号自动跟单机器人

币圈 Telegram 私密信号群 → 自动解析报单 → 交易所永续合约全自动跟单。

- **授权模型**：VIP 用自己的 TG 账号登录软件监听群，被踢出群即失效（群资格即授权）
- **主触发**：进场即在交易所挂 SL + TP1-4 限价单（价格驱动）；群消息（新消息 + 原帖编辑）作为备份核对与人为操作指令通道
- **交易所**：Bybit（MVP），ccxt 统一引擎

## 用户使用指南（面向不懂技术的用户）

**方式一：使用打包好的 exe（推荐，无需安装 Python）**

1. 下载 `autotrade` 文件夹（内含 `autotrade.exe`）
2. 双击 `autotrade.exe`
3. 首次运行会弹出**配置向导**，按提示填：
   - TG 的 `api_id` / `api_hash`（到 <https://my.telegram.org> 申请）
   - 点「登录 Telegram」→ 弹窗输入手机号、验证码（有 2FA 再输密码）
   - 点「选择群聊」选你的信号群
   - Bybit 的 API Key / Secret（只开「读写 + 合约交易」权限，**不要开提现**）
   - 点「保存并自检」
4. 配置完成后自动启动监听，窗口里滚动显示日志；**关闭窗口即停止**

> 网络要求：大陆环境需开 VPN（程序会自动读取系统代理，无需手动填代理端口）。
> 交易所：充值后需在 Bybit 把资金从「资金账户」划转到「统一交易账户」。

**方式二：源码部署（面向技术用户）**

双击 `install.bat`（需要已安装 Python 3.11+），脚本会自动建虚拟环境、装依赖、启动应用。

## 开发者快速开始

```bash
python -m venv .venv                               # 独立环境（本机有 3.12/3.15 两个 Python，venv 固定用 3.12）
.venv\Scripts\python -m pip install -e .           # Windows；Linux/macOS 用 .venv/bin/python
.venv\Scripts\python -m unittest discover -s tests -v   # 单测
.venv\Scripts\python run_app.py                    # 启动应用（向导/监听）
.venv\Scripts\python scripts\run.py --config config\config.yaml   # 命令行启动
```

### 打包 exe

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller autotrade.spec
# 产物在 dist/autotrade/ 目录
```

## 文档

- 完整实施计划：[docs/PLAN.md](docs/PLAN.md)
- **接手开发必读**：[docs/HANDOFF.md](docs/HANDOFF.md)
- 配置模板：[config/config.example.yaml](config/config.example.yaml)

## 目录速览

```
src/autotrade/
├── app.py            # 应用入口（向导/监听）
├── gui/              # GUI 向导、登录弹窗、运行窗口
├── paths.py          # 外部目录管理（打包后写 %APPDATA%/autotrade）
├── proxy.py          # 代理动态解析（自动读系统代理）
├── parser/           # 报单/通知/操作行解析器
├── risk/             # 风控、手数公式、精度
├── exchange/         # 交易所适配（Bybit）
├── execution/        # OrderManager、PositionTracker、TriggerRouter
├── storage/          # SQLite
└── signal_source/    # Telethon userbot
```
