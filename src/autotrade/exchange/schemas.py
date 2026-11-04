"""交易所配置 schema：向导按此动态渲染字段与注意事项。

字段统一三型：apiKey / secret / passphrase（secret=True 输入框打码）。
notes 为配置注意事项（权限要求等），面向真实用户实盘。
无 testnet（产品面向真实用户，试运行用 risk.trial_min_qty 最小手数保护）。
"""

EXCHANGE_SCHEMAS: dict[str, dict] = {
    "bybit": {
        "label": "Bybit",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
        ],
        "notes": [
            "权限：开启「读写」与「合约交易」，切勿开启「提现」",
            "充值后需在 Bybit 把资金从「资金账户」划转到「统一交易账户」，否则下单会失败",
            "建议绑定 IP 白名单（API 管理页面可设置）",
        ],
    },
    "binance": {
        "label": "Binance",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
        ],
        "notes": [
            "创建 Key 时开启「启用合约交易」（Enable Futures），切勿开启提现",
            "强烈建议绑定 IP 白名单（不绑定的 Key 约 90 天自动过期）",
            "使用 USDT 本位合约（USDⓈ-M）账户，先划转 USDT 到合约账户",
        ],
    },
    "bitget": {
        "label": "Bitget",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
            {"key": "passphrase", "label": "Passphrase（必填）", "secret": True},
        ],
        "notes": [
            "创建 Key 时需要自己设定 Passphrase：忘记无法找回，只能删除重建；建议不要使用特殊字符",
            "权限：开启「交易」读写（统一账户 UTA 下含「管理」读写=调整杠杆），切勿开启提现",
            "提现权限仅能通过 IP 白名单开通，请绑定你的 IP",
        ],
    },
    "gate": {
        "label": "Gate",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
        ],
        "notes": [
            "必须使用 API v4 Key（v2 不支持合约）",
            "永续合约权限选「读写」，钱包选「只读」，切勿开启提现",
            "不绑定 IP 白名单的 Key 约 90 天过期，建议绑定",
            "合约账户需先划入 USDT 并做一笔最小交易激活，否则下单会失败",
        ],
    },
    "deepcoin": {
        "label": "Deepcoin",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
            {"key": "passphrase", "label": "Passphrase（必填）", "secret": True},
        ],
        "notes": [
            "创建 Key 时填写的「密码」就是 Passphrase（可与登录密码不同），请记好",
            "Key / Secret / Passphrase 三项只显示一次，请立即保存",
            "授权（Authorization）选择含交易（Trade）的权限，切勿开启提现",
        ],
    },
    "bitunix": {
        "label": "Bitunix",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
        ],
        "notes": [
            "账户菜单 → API Management 创建 Key，需完成 2FA 验证",
            "权限：开启 Read 与 Futures/Trade，切勿开启 Withdraw",
            "Secret 只显示一次，丢失需撤销重建；建议绑定 IP",
        ],
    },
}

EXCHANGE_ORDER = ["bybit", "binance", "bitget", "gate", "deepcoin", "bitunix"]
