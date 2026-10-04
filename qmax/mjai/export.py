# 錄製檔或牌譜 → mjai 事件檔（.mjson，一行一個事件）。
import json
from pathlib import Path

from loguru import logger

from qmax.mjai.convert import MjaiConverter, MjaiMismatch, MjaiUnsupported
from qmax.pipeline import translate
from qmax.platforms.base import Platform, ReplayError


def export_mjai(platform: Platform, path: Path, out: Path, seat: int | None = None) -> int | None:
    """寫出 out，回傳事件數；不能轉（讀不了、規則不支援、紀錄對不上）時記錯誤並回傳 None。"""
    try:
        messages = platform.load_replay(path, seat)
    except ReplayError as e:
        logger.error(str(e))
        return None

    converter = MjaiConverter()
    translator = platform.new_translator()
    events = []
    try:
        for msg in messages:
            for action in translate(translator, msg):
                events += converter.convert(action)
    except MjaiUnsupported as e:
        logger.error(f"{path.name} 用到 mjai 不支援的規則：{e}")
        return None
    except MjaiMismatch as e:
        where = _position(events)
        logger.error(f"{path.name} 轉成 mjai 時對不上（{where}）：{e}")
        return None

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(events)


def _position(events: list[dict]) -> str:
    kyoku = next((e for e in reversed(events) if e["type"] == "start_kyoku"), None)
    if kyoku is None:
        return "開局前"
    return f"{kyoku['bakaze']}{kyoku['kyoku']}局 {kyoku['honba']}本場，第 {len(events)} 個事件"



