# 應用程式控制層：終端模式與 GUI 共用。前端（或 main.py）透過這裡下指令，結果以 Frontend 事件回傳。
from pathlib import Path

from loguru import logger

from qmax import VERSION
from qmax.advice import Advisor, open_advisor
from qmax.config import SETTINGS_PATH, load_settings, resolve_path, save_settings
from qmax.frontend.base import Frontend
from qmax.logs import start_app_log
from qmax.mjai.export import export_mjai
from qmax.platforms import PLATFORMS, Platform
from qmax.proxy import ProxyServer
from qmax.replay import replay
from qmax.replay_session import ReplaySession
from qmax.review import review

DEFAULT_HOST, DEFAULT_PORT = "0.0.0.0", 23410
DISCLAIMER = "本工具僅用於個人娛樂模式對局的錄製與離線分析，不建議在排位對局中即時使用。"


class App:
    def __init__(self, frontend: Frontend):
        self.frontend = frontend
        self.settings, created = load_settings()
        self.platform = self._make_platform()
        self.proxy: ProxyServer | None = None
        self._prepared = False
        self._replay_advisor: Advisor | None = None  # GUI 回放用，第一次開檔時才啟動
        start_app_log(resolve_path(self.settings["logging"]["output_dir"]))
        if created:
            logger.info(f"首次執行，已產生預設設定 {SETTINGS_PATH}")
        self.save_settings()

    def _make_platform(self) -> Platform:
        name = self.settings["platform"]
        if name not in PLATFORMS:
            raise SystemExit(f"config/settings.yaml 的 platform 是 {name!r}，可用的有：{', '.join(PLATFORMS)}")
        records_dir = resolve_path(self.settings["recorder"]["output_dir"]) / name
        return PLATFORMS[name](self.settings[name], self.save_settings, records_dir)

    def save_settings(self):
        save_settings(self.settings)

    @property
    def advisor_name(self) -> str:
        return self.settings["analysis"]["advisor"]

    @property
    def listening(self) -> bool:
        return self.proxy is not None and self.proxy.running

    def start_proxy(self, host: str, port: int):
        if self.listening:
            return
        if not self._prepared:  # 協定更新等只在第一次監聽前做
            logger.warning(f"{VERSION}　{DISCLAIMER}")
            self.platform.prepare()
            self._prepared = True
        self.proxy = ProxyServer(self.platform, self.settings, self.frontend, host, port)
        self.proxy.start()

    def stop_proxy(self):
        if self.proxy is not None:
            self.proxy.stop()
            self.proxy = None

    def wait_proxy(self):
        """等到代理停止（終端模式用）。"""
        if self.proxy is not None:
            self.proxy.wait()

    def replay(self, path: Path, seat: int | None = None):
        """一次跑完整場，結果送給前端（終端模式）。"""
        replay(self.platform, path, self.frontend, self.advisor_name, seat)

    def review(
        self, path: Path, seat: int | None = None, out: Path | None = None, compare: list[str] = (),
    ) -> tuple[Path, list[str] | None]:
        """決策紀錄。out 預設是 logs/review/<檔名>.jsonl。回傳 (輸出路徑, 摘要)。"""
        if out is None:
            out = self._derived_path("review", path, seat, ".jsonl")
        return out, review(self.platform, path, out, self.advisor_name, seat, compare)

    def export_mjai(self, path: Path, seat: int | None = None, out: Path | None = None) -> tuple[Path, int | None]:
        """匯出 mjai 事件檔。out 預設是 logs/mjai/<檔名>.mjson。回傳 (輸出路徑, 事件數)；失敗時事件數是 None。"""
        if out is None:
            out = self._derived_path("mjai", path, seat, ".mjson")
        return out, export_mjai(self.platform, path, out, seat)

    def _derived_path(self, kind: str, path: Path, seat: int | None, suffix: str) -> Path:
        name = path.stem + (f"-seat{seat}" if seat is not None else "")
        return resolve_path(self.settings["logging"]["output_dir"]) / kind / f"{name}{suffix}"

    def replay_files(self) -> list[Path]:
        return self.platform.replay_files()

    def open_replay(self, path: Path) -> ReplaySession:
        """可以逐步跳轉的回放（GUI）。檔案讀不了時丟 ReplayError，解析器啟動失敗時丟 AdvisorError。"""
        if self._replay_advisor is None:
            self._replay_advisor = open_advisor(self.advisor_name)
        return ReplaySession(self.platform, self._replay_advisor, path)

    def close(self):
        self.stop_proxy()
        if self._replay_advisor is not None:
            self._replay_advisor.close()
            self._replay_advisor = None
