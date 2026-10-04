import json
import uuid
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from qmax.platforms.base import Message, Platform, ReplayError
from qmax.platforms.majsoul import game_record, liqi_update
from qmax.platforms.majsoul.liqi import LiqiDecoder
from qmax.platforms.majsoul.messages import AUTH_GAME, FETCH_GAME_RECORD, GAME_END_RESULT, TERMINATE_GAME
from qmax.platforms.majsoul.translator import MajsoulTranslator

DEFAULT_SETTINGS = """\
# 自己的帳號，進入對局時自動記下；重播牌譜時用來找出自己是哪一家
account_id: 0
# 協定定義自動更新（來源：Avenshy/MajsoulData）
liqi:
  auto_update: true
  github_token: ''
  version: '0.16.243-4.0.45'  # 隨附的 liqi.desc 版本
"""


class MajsoulPlatform(Platform):
    name = "majsoul"
    default_settings = DEFAULT_SETTINGS

    def prepare(self):
        liqi = self.settings["liqi"]
        if not liqi["auto_update"]:
            return
        logger.info("檢查 liqi 協定更新……")
        try:
            liqi["version"] = liqi_update.update(liqi["version"], liqi["github_token"])
            self.save_settings()
        except Exception as e:
            logger.error(f"liqi 協定更新失敗，部分訊息可能無法解析：{e}")

    def accepts(self, url: str) -> bool:
        return urlparse(url).path != "/ob"  # 觀戰通道

    def new_decoder(self) -> LiqiDecoder:
        return LiqiDecoder()

    def new_translator(self) -> MajsoulTranslator:
        return MajsoulTranslator()

    def game_id_if_start(self, msg: Message) -> str | None:
        if msg.get("method") != AUTH_GAME or msg.get("type") != "Req":
            return None
        data = msg.get("data") or {}
        return str(data.get("game_uuid") or data.get("account_id") or uuid.uuid4().hex)

    def is_game_end(self, msg: Message) -> bool:
        return msg.get("method") in (TERMINATE_GAME, GAME_END_RESULT)

    def observe(self, msg: Message):
        if msg.get("method") == AUTH_GAME and msg.get("type") == "Req":
            self._remember_account((msg.get("data") or {}).get("account_id"))
        elif msg.get("method") == FETCH_GAME_RECORD and msg.get("type") == "Res":
            self._save_game_record(msg.get("data") or {})

    def _remember_account(self, account_id: int | None):
        if account_id and account_id != self.settings["account_id"]:
            self.settings["account_id"] = account_id
            self.save_settings()
            logger.info(f"已記下自己的帳號 {account_id}")

    def _save_game_record(self, data: dict):
        history_dir = self.records_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        uid = (data.get("head") or {}).get("uuid") or uuid.uuid4().hex
        path = history_dir / f"{uid}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        logger.success(f"已存下牌譜：{path.name}")

    def replay_files(self) -> list[Path]:
        files = [*(self.records_dir / "live").glob("*.jsonl"), *(self.records_dir / "history").glob("*.json")]
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    def replay_seat_selectable(self, path: Path) -> bool:
        return path.suffix == ".json"

    def load_replay(self, path: Path, seat: int | None) -> list[Message]:
        if path.suffix == ".json":
            return self._load_game_record(path, seat)
        messages = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if any(str(m.get("method", "")).startswith(".lq.Record") for m in messages[:20]):
            raise ReplayError(f"{path.name} 是攤平後的牌譜，沒有座位資訊；請改用同名的 .json")
        return messages

    def _load_game_record(self, path: Path, seat: int | None) -> list[Message]:
        record = json.loads(path.read_text(encoding="utf-8"))
        table = game_record.players(record)
        names = "、".join(f"{p['seat']}={p['nickname']}" for p in table)
        if seat is None:
            account_id = self.settings["account_id"]
            mine = [p["seat"] for p in table if account_id and p["account_id"] == account_id]
            if not mine:
                raise ReplayError(f"找不到自己在這場的座位，請用 --seat 指定（{names}）")
            seat = mine[0]
        elif not 0 <= seat < len(table):
            raise ReplayError(f"--seat {seat} 不存在，這場的座位：{names}")
        logger.info(f"以座位 {seat}（{table[seat]['nickname']}）的視角重播")
        return game_record.to_live_messages(record, seat)
