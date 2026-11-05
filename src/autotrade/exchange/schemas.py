"""交易所設定 schema：嚮導按此動態渲染欄位與注意事項。

欄位統一三型：apiKey / secret / passphrase（secret=True 輸入框打碼）。
notes 為設定注意事項（權限要求等），面向真實使用者實盤。
無 testnet（產品面向真實使用者，手數正式按風控公式計算，無試運行最小手數模式）。
"""

EXCHANGE_SCHEMAS: dict[str, dict] = {
    "bybit": {
        "label": "Bybit",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
        ],
        "notes": [
            "權限：開啟「讀寫」與「合約交易」，切勿開啟「提領」",
            "儲值後需在 Bybit 把資金從「資金帳戶」劃轉到「統一交易帳戶」，否則下單會失敗",
            "建議綁定 IP 白名單（限制來源 IP，與可交易品種無關；API 管理頁面可設定）",
        ],
    },
    "binance": {
        "label": "Binance",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
        ],
        "notes": [
            "創建 Key 時開啟「啟用合約交易」（Enable Futures），切勿開啟提領",
            "強烈建議綁定 IP 白名單（限制「可調用 API 的來源 IP」，與可交易品種無關；不綁定則 Key 約 90 天自動過期）",
            "使用 USDT 本位合約（USDⓈ-M）帳戶，先劃轉 USDT 到合約帳戶",
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
            "創建 Key 時需要自己設定 Passphrase：忘記無法找回，只能刪除重建；建議不要使用特殊字符",
            "權限：開啟「交易」讀寫（統一帳戶 UTA 下含「管理」讀寫=調整槓桿），切勿開啟提領",
            "提領權限僅能通過 IP 白名單開通，請綁定你的 IP（IP 白名單限制來源 IP，與可交易品種無關）",
        ],
    },
    "gate": {
        "label": "Gate",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
        ],
        "notes": [
            "必須使用 API v4 Key（v2 不支持合約）",
            "永續合約權限選「讀寫」，錢包選「只讀」，切勿開啟提領",
            "不綁定 IP 白名單的 Key 約 90 天過期，建議綁定（限制來源 IP，與可交易品種無關）",
            "合約帳戶需先劃入 USDT 並做一筆最小交易激活，否則下單會失敗",
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
            "創建 Key 時填寫的「密碼」就是 Passphrase（可與登入密碼不同），請記好",
            "Key / Secret / Passphrase 三項只顯示一次，請立即儲存",
            "授權（Authorization）選擇含交易（Trade）的權限，切勿開啟提領",
        ],
    },
    "bitunix": {
        "label": "Bitunix",
        "fields": [
            {"key": "apiKey", "label": "API Key", "secret": False},
            {"key": "secret", "label": "Secret", "secret": True},
        ],
        "notes": [
            "帳戶選單 → API Management 創建 Key，需完成 2FA 驗證",
            "權限：開啟 Read 與 Futures/Trade，切勿開啟 Withdraw",
            "Secret 只顯示一次，丟失需撤銷重建；建議綁定 IP 白名單（限制來源 IP，與可交易品種無關）",
        ],
    },
}

EXCHANGE_ORDER = ["bybit", "binance", "bitget", "gate", "deepcoin", "bitunix"]
