"""mjai 格式：開源麻將 AI（Mortal 等）共用的事件格式。

    convert.py  通用牌局動作 → mjai 事件
    export.py   錄製檔或牌譜 → .mjson（main.py mjai）
"""
from qmax.mjai.convert import MjaiConverter, MjaiMismatch, MjaiUnsupported, mjai_tile

__all__ = ["MjaiConverter", "MjaiMismatch", "MjaiUnsupported", "mjai_tile"]
