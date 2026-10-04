"""akochan 解析器（critter-mj/akochan）：期望順位點最大化的麻將 AI，透過 mjai 事件溝通。

    advisor.py  轉接：牌局動作 → mjai 事件，akochan 的評估 → Advice
    server.py   qmax_akochan 子行程（原始碼與編譯腳本在 analyzer/akochan/）
"""
from qmax.advice.akochan.advisor import AkochanAdvisor, AkochanLightAdvisor

__all__ = ["AkochanAdvisor", "AkochanLightAdvisor"]
