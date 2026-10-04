# 前端介面：引擎依對局進行的順序呼叫，每種事件一個方法。
# 前端只負責呈現，不修改傳入的資料、不呼叫解析器。
#
# info/warning/error 是後端的日誌：後端已經寫進日誌檔，這裡只決定要不要、怎麼顯示。
#
# 執行緒：即時對局時，牌桌與分析事件來自背景的分析執行緒；日誌可能來自任何執行緒，
# 所以日誌方法可能與其他方法同時被呼叫。
from abc import ABC, abstractmethod

from qmax.frontend import events as ev


class Frontend(ABC):
    # ---- 日誌 ----

    @abstractmethod
    def info(self, message: str): ...

    @abstractmethod
    def warning(self, message: str): ...

    @abstractmethod
    def error(self, message: str): ...

    def close(self):
        """程式結束前呼叫，例如還原終端機畫面。"""

    def proxy_status(self, e: ev.ProxyStatus):
        """代理開始或停止監聽（包括啟動失敗）。終端機前端用日誌就夠了，不必實作。"""

    # ---- 對局流程 ----

    @abstractmethod
    def game_start(self, e: ev.GameStart): ...

    @abstractmethod
    def round_start(self, e: ev.RoundStart): ...

    @abstractmethod
    def round_end(self, e: ev.RoundEnd): ...

    @abstractmethod
    def game_over(self, e: ev.GameOver): ...

    # ---- 牌桌動作 ----

    @abstractmethod
    def draw(self, e: ev.Draw): ...

    @abstractmethod
    def hand_update(self, e: ev.HandUpdate): ...

    @abstractmethod
    def dora_update(self, e: ev.DoraUpdate): ...

    @abstractmethod
    def discard(self, e: ev.Discard): ...

    @abstractmethod
    def call(self, e: ev.Call): ...

    @abstractmethod
    def kan(self, e: ev.Kan): ...

    @abstractmethod
    def nuki(self, e: ev.Nuki): ...

    @abstractmethod
    def exchange_tiles(self, e: ev.ExchangeTiles): ...

    @abstractmethod
    def win(self, e: ev.Win): ...

    @abstractmethod
    def operation(self, e: ev.Operation): ...

    # ---- 分析結果 ----

    @abstractmethod
    def hand_analysis(self, e: ev.HandAnalysis): ...

    @abstractmethod
    def exchange_analysis(self, e: ev.ExchangeAnalysis): ...

    @abstractmethod
    def call_analysis(self, e: ev.CallAnalysis):
        """緊接在對應的 operation 之後。"""

    @abstractmethod
    def risk_analysis(self, e: ev.RiskAnalysis): ...


class NullFrontend(Frontend):
    """什麼都不顯示：只要分析結果、不要畫面時用（例如決策紀錄）。"""


for _name in Frontend.__abstractmethods__:
    setattr(NullFrontend, _name, lambda self, e: None)
NullFrontend.__abstractmethods__ = frozenset()
