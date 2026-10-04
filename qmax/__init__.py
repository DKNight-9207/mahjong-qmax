"""qmax-recorder：麻將平台的 WebSocket 錄製 + 即時牌效／危險度分析。"""
from pathlib import Path

VERSION = "qmax-recorder v0.8"

# 專案根目錄；analyzer/、config/ 等路徑都以這裡為基準，不依賴工作目錄
ROOT = Path(__file__).resolve().parent.parent
