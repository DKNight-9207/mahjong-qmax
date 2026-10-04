# 日誌（後端負責，前端顯示與否不影響日誌）。以 loguru 的 stream 標籤分流：
#
#   （無標籤）           狀態訊息 → logs/app/<啟動時間>.log，並依等級轉給前端 info/warning/error
#   analyze_data_logger 解析器每次對外呼叫的紀錄 → logs/analyze/<對局>.log
#                       一行一個 JSON：{"endpoint", "state", "request", "response"}
#   proxy_logger        收發的訊息名稱、mitmproxy 內部訊息 → logs/proxy/<啟動時間>.log
import time
from pathlib import Path

from loguru import logger

from qmax.frontend import Frontend

analyze_data_logger = logger.bind(stream="analyze_data")
proxy_logger = logger.bind(stream="proxy")


def _untagged(record) -> bool:
    return "stream" not in record["extra"]


def _only(stream: str):
    return lambda record: record["extra"].get("stream") == stream


def forward_to_frontend(frontend: Frontend):
    """狀態訊息轉給前端顯示。會移除 loguru 預設的 stderr 輸出：終端機只能由前端寫。"""

    def sink(message):
        record = message.record
        text = record["message"]
        if record["level"].no >= 40:
            frontend.error(text)
        elif record["level"].no >= 30:
            frontend.warning(text)
        else:
            frontend.info(text)

    logger.remove()
    logger.add(sink, level="INFO", filter=_untagged, format="{message}")


def start_app_log(output_dir: Path):
    """狀態訊息寫進 logs/app/<啟動時間>.log，整個執行期間一份。"""
    _add_file(output_dir / "app" / f"{time.strftime('%Y%m%d-%H%M%S')}.log", _untagged,
              "[{time:HH:mm:ss.SSS}] {level:<7} {message}")


def _add_file(path: Path, filter_, format_: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return logger.add(path, level="INFO", filter=filter_, format=format_, encoding="utf-8")


class SessionLog:
    """代理開著的期間：proxy_log 一份；analyze_log 跟著對局切檔。"""

    def __init__(self, output_dir: Path, analyze_enabled=True, proxy_enabled=True):
        self.analyze_enabled = analyze_enabled
        self.analyze_dir = output_dir / "analyze"
        self._analyze_sink = None
        self._proxy_sink = None
        if proxy_enabled:
            self._proxy_sink = _add_file(output_dir / "proxy" / f"{time.strftime('%Y%m%d-%H%M%S')}.log",
                                         _only("proxy"), "[{time:HH:mm:ss.SSS}] {message}")

    def open_game(self, stem: str):
        self.close_game()
        if self.analyze_enabled:
            self._analyze_sink = _add_file(self.analyze_dir / f"{stem}.log", _only("analyze_data"), "{message}")

    def close_game(self):
        if self._analyze_sink is not None:
            logger.remove(self._analyze_sink)
            self._analyze_sink = None

    def close(self):
        self.close_game()
        if self._proxy_sink is not None:
            logger.remove(self._proxy_sink)
            self._proxy_sink = None
