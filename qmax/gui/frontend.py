# GUI 前端：每個事件 dataclasses.asdict() 後轉成 JSON，交給網頁的 qmax.receive(方法名, 內容)。
#
# 事件可能來自任何執行緒；這裡只排進佇列，由一條送出執行緒依序呼叫 evaluate_js，
# 不讓分析執行緒等網頁畫完，也避免在 GUI 自己的執行緒裡等 GUI。
import dataclasses
import json
import queue
import threading
import time
from typing import Callable

from qmax.frontend import events as ev
from qmax.frontend.base import Frontend

Send = Callable[[str], None]  # 執行一段 JS


class WebFrontend(Frontend):
    def __init__(self):
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._send: Send | None = None
        self._thread = threading.Thread(target=self._run, name="gui-sender", daemon=True)

    def connect(self, send: Send):
        """網頁載入完成後呼叫；之前收到的事件會依序補送。網頁重新整理後會再被呼叫一次。"""
        self._send = send
        if not self._thread.is_alive():
            self._thread.start()

    def close(self):
        self._queue.put(None)

    def _push(self, method: str, payload):
        if dataclasses.is_dataclass(payload):
            payload = dataclasses.asdict(payload)
        self._queue.put(f"qmax.receive({json.dumps(method)}, {json.dumps(payload)})")

    def _run(self):
        while (script := self._queue.get()) is not None:
            try:
                self._send(script)
            except Exception:  # 視窗已經關掉
                return

    # ---- 日誌 ----

    def info(self, message: str):
        self._log("info", message)

    def warning(self, message: str):
        self._log("warning", message)

    def error(self, message: str):
        self._log("error", message)

    def _log(self, level: str, message: str):
        self._push("log", {"time": time.strftime("%H:%M:%S"), "level": level, "message": message})

    # ---- 其餘事件原樣轉送 ----

    def proxy_status(self, e: ev.ProxyStatus):
        self._push("proxy_status", e)

    def game_start(self, e: ev.GameStart):
        self._push("game_start", e)

    def round_start(self, e: ev.RoundStart):
        self._push("round_start", e)

    def round_end(self, e: ev.RoundEnd):
        self._push("round_end", e)

    def game_over(self, e: ev.GameOver):
        self._push("game_over", e)

    def draw(self, e: ev.Draw):
        self._push("draw", e)

    def hand_update(self, e: ev.HandUpdate):
        self._push("hand_update", e)

    def dora_update(self, e: ev.DoraUpdate):
        self._push("dora_update", e)

    def discard(self, e: ev.Discard):
        self._push("discard", e)

    def call(self, e: ev.Call):
        self._push("call", e)

    def kan(self, e: ev.Kan):
        self._push("kan", e)

    def nuki(self, e: ev.Nuki):
        self._push("nuki", e)

    def exchange_tiles(self, e: ev.ExchangeTiles):
        self._push("exchange_tiles", e)

    def win(self, e: ev.Win):
        self._push("win", e)

    def operation(self, e: ev.Operation):
        self._push("operation", e)

    def hand_analysis(self, e: ev.HandAnalysis):
        self._push("hand_analysis", e)

    def exchange_analysis(self, e: ev.ExchangeAnalysis):
        self._push("exchange_analysis", e)

    def call_analysis(self, e: ev.CallAnalysis):
        self._push("call_analysis", e)

    def risk_analysis(self, e: ev.RiskAnalysis):
        self._push("risk_analysis", e)
