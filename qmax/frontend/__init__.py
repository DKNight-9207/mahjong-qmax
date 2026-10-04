"""前端：接收引擎的事件並呈現。

    events.py          事件內容（dataclass，可直接轉 JSON）
    base.py            Frontend 介面
    zh.py              中文顯示用字串，以下兩個前端共用
    text.py            捲動文字
    dashboard.py       終端機儀表板：log 模式／遊戲模式切換
    dashboard_view.py  儀表板的畫面狀態與繪製
"""
from qmax.frontend.base import Frontend

__all__ = ["Frontend"]
