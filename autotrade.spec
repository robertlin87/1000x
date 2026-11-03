# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：打包为 onedir 单目录（含 autotrade.exe + 依赖）。"""
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# ccxt / telethon 有大量动态导入与数据文件，collect_all 全部收集
for pkg in ("ccxt", "telethon", "ruamel.yaml", "aiosqlite"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run_app.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest", "pydoc_data"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="autotrade",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI 窗口应用，无黑控制台；日志在应用窗口内显示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="autotrade",
)
