# 對局錄製：每場對局一個 <stem>.jsonl，一行一則平台訊息（格式由平台決定）。
import json
import time

from loguru import logger

from qmax.platforms.base import Message, Platform


class GameRecorder:
    def __init__(self, platform: Platform):
        self.platform = platform
        self.live_dir = platform.records_dir / "live"
        self.stem: str | None = None  # 這場的檔名（開局時間_識別碼前 8 碼），analyze_log 也用同一個
        self._file = None

    def feed(self, msg: Message) -> str | None:
        """寫入對局中的訊息。回傳 "start"/"end" 表示這則開始或結束了一場對局。"""
        game_id = self.platform.game_id_if_start(msg)
        if game_id is not None:
            self._open(f"{time.strftime('%Y%m%d-%H%M%S')}_{game_id[:8]}")
            self._write(msg)
            return "start"
        if self._file is None:
            return None
        self._write(msg)
        if self.platform.is_game_end(msg):
            self.close()
            return "end"
        return None

    def _open(self, stem: str):
        self.close()
        self.live_dir.mkdir(parents=True, exist_ok=True)
        self.stem = stem
        path = self.live_dir / f"{stem}.jsonl"
        self._file = open(path, "a", encoding="utf-8")
        logger.success(f"開始錄製：{path.name}")

    def _write(self, msg: Message):
        self._file.write(json.dumps(msg, ensure_ascii=False, default=str) + "\n")
        self._file.flush()

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None
