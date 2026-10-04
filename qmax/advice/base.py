# 解析器介面。引擎只透過這裡問建議，不知道背後是 mahjong-helper 還是 AI。
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, Literal

from qmax.advice.model import Advice, Danger, Decision
from qmax.game import actions as act

if TYPE_CHECKING:  # qmax.engine 會 import 這裡
    from qmax.engine.state import RoundState


class AdvisorError(Exception):
    """kind：rejected     解析器說輸入有問題
             internal     解析器內部錯誤（細節記在 analyze log）
             unreachable  解析器沒有回應或已停止"""

    def __init__(self, message: str, kind: Literal["rejected", "internal", "unreachable"] = "rejected"):
        super().__init__(message)
        self.kind = kind


# on_call(endpoint, request, response)：解析器每次對外呼叫的原始請求與回應，除錯紀錄用（logs/analyze/）。
# 失敗時 response 是 {"error": ...}。
OnCall = Callable[[str, dict, dict], None]


class Advisor(ABC):
    """解析器怎麼啟動（子行程、載入模型、連遠端…）由各自的 open() 決定，用完要 close()。
    也可以用 with：with open_advisor(...) as advisor: ..."""

    name: str

    @classmethod
    @abstractmethod
    def open(cls, on_call: OnCall | None = None) -> Advisor:
        """啟動並回傳可以使用的解析器。失敗時丟 AdvisorError。"""

    def close(self):
        """釋放資源（關子行程、卸載模型…）。可以重複呼叫。"""

    @property
    def description(self) -> str:
        """顯示在日誌裡的名稱與版本。"""
        return self.name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def observe(self, action: act.Action):
        """每個牌局動作在引擎處理之前通知（所以 advise() 被問到時，引起這次決策的動作已經收過了）。
        需要自己記狀態的解析器（例如吃事件流的 AI）用；收到 GameStarted 時要重設狀態，
        因為回放每次跳轉都會從對局開頭重跑一次。要很快，回放快轉時每個動作都會呼叫。"""

    @abstractmethod
    def advise(self, decision: Decision, state: RoundState) -> Advice:
        """失敗時丟 AdvisorError。"""

    def danger(self, seat: int, state: RoundState) -> Danger | None:
        """seat 這家對自己的危險度；不支援時回傳 None。失敗時丟 AdvisorError。"""
        return None

    def is_alive(self) -> bool:
        """沒有回應（AdvisorError unreachable）時，用來分辨是暫時卡住還是已經停止。"""
        return True
