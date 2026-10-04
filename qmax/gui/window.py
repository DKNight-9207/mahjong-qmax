# 開 GUI 視窗。網頁透過 window.pywebview.api 呼叫 GuiApi 的方法（在 pywebview 的工作執行緒執行）。
import dataclasses
import time
from pathlib import Path

import webview

from qmax import VERSION
from qmax.app import DEFAULT_HOST, DEFAULT_PORT, App
from qmax.frontend import zh
from qmax.gui.frontend import WebFrontend
from qmax.logs import forward_to_frontend
from qmax.advice import AdvisorError
from qmax.platforms.base import ReplayError
from qmax.replay_session import ReplaySession

WEB_DIR = Path(__file__).with_name("web")


class GuiApi:
    def __init__(self, app: App):
        self._app = app
        self._window: webview.Window | None = None  # 底線開頭：pywebview 不會把它開放給網頁
        self._replay: ReplaySession | None = None

    def labels(self) -> dict:
        """顯示用的中文名稱，與終端機前端共用同一份。"""
        return {
            "tiles": zh.TILE_ZH, "winds": zh.WIND_ZH, "shanten": zh.SHANTEN_ZH, "options": zh.OPTION_ZH,
            "yaku": zh.YAKU_ZH, "abortive": zh.ABORTIVE_ZH,
            "seats4": zh.SEAT_NAMES_4P, "seats3": zh.SEAT_NAMES_3P,
            "notes": zh.NOTE_ZH,
        }

    def status(self) -> dict:
        return {"version": VERSION, "listening": self._app.listening, "host": DEFAULT_HOST, "port": DEFAULT_PORT}

    def start_listening(self, host: str, port: int):
        self._app.start_proxy(host, int(port))

    def stop_listening(self):
        self._app.stop_proxy()

    # ---- 回放 ----

    def replay_files(self) -> list[dict]:
        platform = self._app.platform
        return [
            {
                "path": str(path), "name": path.name,
                "kind": "牌譜" if platform.replay_seat_selectable(path) else "錄製",
                "time": time.strftime("%m/%d %H:%M", time.localtime(path.stat().st_mtime)),
            }
            for path in self._app.replay_files()
        ]

    def replay_choose_file(self) -> str | None:
        dialog = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        chosen = self._window.create_file_dialog(
            dialog, directory=str(self._app.platform.records_dir), file_types=("牌譜與錄製檔 (*.json;*.jsonl)", "所有檔案 (*.*)"),
        )
        return chosen[0] if chosen else None

    def replay_open(self, path: str) -> dict:
        try:
            self._replay = self._app.open_replay(Path(path))
        except (ReplayError, AdvisorError, OSError, ValueError) as e:
            self._replay = None
            return {"error": str(e)}
        return self._replay_meta()

    def replay_seek(self, step: int) -> list:
        """第 step 步的畫面所需的事件：[[方法名, 內容], ...]，網頁從空白狀態依序套用。"""
        if self._replay is None:
            return []
        return [[name, dataclasses.asdict(event)] for name, event in self._replay.events_at(int(step))]

    def replay_switch_seat(self, seat: int) -> dict:
        self._replay.switch_seat(int(seat))
        return self._replay_meta()

    def _replay_meta(self) -> dict:
        r = self._replay
        return {
            "name": r.path.name, "steps": r.steps, "big_steps": r.big_steps,
            "rounds": [
                {"step": x.step, "start": dataclasses.asdict(x.start), "end": x.end and dataclasses.asdict(x.end)}
                for x in r.rounds
            ],
            "seat_selectable": r.seat_selectable, "self_seat": r.self_seat,
            "num_players": r.num_players, "player_names": r.player_names,
        }


def run_gui(debug: bool = False):
    """debug：開啟網頁的開發者工具（F12、右鍵檢查、F5 重新整理），調整畫面用。"""
    frontend = WebFrontend()
    forward_to_frontend(frontend)
    app = App(frontend)
    api = GuiApi(app)
    window = api._window = webview.create_window(
        VERSION, url=str(WEB_DIR / "index.html"), js_api=api,
        width=1000, height=760, min_size=(720, 560), background_color="#1F2B3A",
    )
    window.events.loaded += lambda: frontend.connect(window.evaluate_js)
    try:
        webview.start(debug=debug)
    finally:
        app.close()
        frontend.close()
