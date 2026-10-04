# 終端機儀表板前端。
#
# 平常是 log 模式：日誌逐行印出。收到 game_start（或對局中途接上時的
# round_start）切到遊戲模式：改用終端機的備用畫面顯示固定版面，直到
# game_over 才切回來。遊戲模式中的日誌先存進 log_buffer，切回後再印；
# 警告與錯誤另外同時顯示在畫面最下方。
import atexit
import functools
import threading
import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

from qmax.frontend import events as ev
from qmax.frontend import zh
from qmax.frontend.base import Frontend
from qmax.frontend.dashboard_view import Alert, TableView, render

LOG_STYLES = {"info": "", "warning": "yellow", "error": "bold red"}
LOG_MARKS = {"info": "", "warning": "⚠ ", "error": "✖ "}


def _exclusive(method):
    """日誌可能從任何執行緒進來，牌桌事件從分析執行緒進來；畫面狀態一次只讓一邊讀寫。"""

    @functools.wraps(method)
    def wrapper(self, *args):
        with self._lock:
            return method(self, *args)

    return wrapper


class DashboardFrontend(Frontend):
    def __init__(self):
        self._lock = threading.RLock()
        self.console = Console()
        self.view = TableView()
        self.live: Live | None = None
        self.log_buffer: list[tuple[str, str, str]] = []  # (時間, 等級, 訊息)，遊戲模式中暫存
        self.round_summaries: list[str] = []  # 每局結果一行，對局結束切回 log 模式時印出
        atexit.register(self.close)  # 確保程式怎麼結束都會切回原本的畫面

    # ---- 模式切換 ----

    @property
    def in_game(self) -> bool:
        return self.live is not None

    def _enter_game(self):
        if self.in_game:
            return
        self.view = TableView(self_seat=self.view.self_seat, num_players=self.view.num_players)
        self.live = Live(
            render(self.view),
            console=self.console,
            screen=True,  # 備用畫面：離開時原本的 log 畫面原樣回來
            auto_refresh=False,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self.live.start(refresh=True)

    def _leave_game(self, summary: str | None = None):
        if not self.in_game:
            return
        self.live.stop()
        self.live = None
        if summary:
            self.console.print(Text(summary, style="bold"))
        for line in self.round_summaries:
            self.console.print(Text(f"  {line}"))
        self.round_summaries.clear()
        for entry in self.log_buffer:
            self._print_log(*entry)
        self.log_buffer.clear()

    def _refresh(self):
        if self.in_game:
            self.live.update(render(self.view), refresh=True)

    @_exclusive
    def close(self):
        self._leave_game()

    # ---- 日誌 ----

    @_exclusive
    def info(self, message: str):
        self._log("info", message)

    @_exclusive
    def warning(self, message: str):
        self._log("warning", message)

    @_exclusive
    def error(self, message: str):
        self._log("error", message)

    def _log(self, level: str, message: str):
        entry = (time.strftime("%H:%M:%S"), level, message)
        if not self.in_game:
            self._print_log(*entry)
            return
        self.log_buffer.append(entry)
        if level != "info":
            self.view.alerts.append(Alert(*entry))
            self._refresh()

    def _print_log(self, at: str, level: str, message: str):
        self.console.print(Text.assemble((f"[{at}] ", "cyan"), (LOG_MARKS[level] + message, LOG_STYLES[level])))

    # ---- 對局流程 ----

    @_exclusive
    def game_start(self, e: ev.GameStart):
        self.view.self_seat, self.view.num_players = e.self_seat, e.num_players
        self._enter_game()

    @_exclusive
    def round_start(self, e: ev.RoundStart):
        self._enter_game()
        self.view.start_round(e)
        self._refresh()

    @_exclusive
    def round_end(self, e: ev.RoundEnd):
        self.view.settle(e)
        self.round_summaries.append(self.view.round_summary(e))
        self._set_last_action(zh.round_end_headline(e, self.view.seat))

    @_exclusive
    def game_over(self, e: ev.GameOver):
        reason = "打完" if e.reason == "finished" else "離桌"
        score = self.view.score_text()
        self._leave_game(f"對局結束（{reason}）" + (f"　{score}" if score else ""))

    # ---- 牌桌動作 ----

    @_exclusive
    def draw(self, e: ev.Draw):
        self.view.drawn_tile = e.tile
        self.view.operation = self.view.call_analysis = None

    @_exclusive
    def hand_update(self, e: ev.HandUpdate):
        self.view.hand, self.view.melds = list(e.hand), list(e.melds)
        self._refresh()

    @_exclusive
    def dora_update(self, e: ev.DoraUpdate):
        self.view.dora_indicators = list(e.dora_indicators)
        self._refresh()

    @_exclusive
    def discard(self, e: ev.Discard):
        v = self.view
        v.operation = v.call_analysis = None
        if e.riichi:
            v.riichi.add(e.seat)
        if e.seat == v.self_seat:
            v.drawn_tile = None
            v.hand_analysis = None
        flags = ("（摸切）" if e.tsumogiri else "") + ("（立直）" if e.riichi else "")
        self._set_last_action(f"{v.seat(e.seat)} 切 {zh.tile_zh(e.tile)}{flags}")

    @_exclusive
    def call(self, e: ev.Call):
        if e.seat == self.view.self_seat:
            self.view.operation = None
        self._set_last_action(f"{self.view.seat(e.seat)} {zh.OPTION_ZH[e.kind]} {zh.tiles_zh(e.tiles)}")

    @_exclusive
    def kan(self, e: ev.Kan):
        self._set_last_action(f"{self.view.seat(e.seat)} {zh.OPTION_ZH[e.kind]} {zh.tile_zh(e.tile)}")

    @_exclusive
    def nuki(self, e: ev.Nuki):
        self._set_last_action(f"{self.view.seat(e.seat)} 拔北")

    @_exclusive
    def exchange_tiles(self, e: ev.ExchangeTiles):
        self.view.operation = self.view.call_analysis = self.view.exchange_analysis = None  # 換牌已經做完
        self._set_last_action(f"換牌：換出 {zh.tiles_zh(e.out_tiles)}，換入 {zh.tiles_zh(e.in_tiles)}")

    @_exclusive
    def win(self, e: ev.Win):
        self._set_last_action(zh.win_line(e.result, self.view.seat))

    def _set_last_action(self, text: str):
        self.view.last_action = text
        self._refresh()

    @_exclusive
    def operation(self, e: ev.Operation):
        self.view.operation = e
        self._refresh()

    # ---- 分析結果 ----

    @_exclusive
    def hand_analysis(self, e: ev.HandAnalysis):
        self.view.hand_analysis = e
        self.view.call_analysis = None  # 手牌變了，之前的鳴牌模擬已過時
        self._refresh()

    @_exclusive
    def exchange_analysis(self, e: ev.ExchangeAnalysis):
        self.view.exchange_analysis = e
        self._refresh()

    @_exclusive
    def call_analysis(self, e: ev.CallAnalysis):
        self.view.call_analysis = e
        self._refresh()

    @_exclusive
    def risk_analysis(self, e: ev.RiskAnalysis):
        self.view.risks[e.seat] = e
        self._refresh()
