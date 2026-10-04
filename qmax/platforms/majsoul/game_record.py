# 雀魂牌譜（.lq.Lobby.fetchGameRecord 的回應）。
#
# data 欄位是三層包裝的 protobuf（不需要即時對局那套 XOR）：
#   base64 -> lq.Wrapper(GameDetailRecords) -> actions[].result -> lq.Wrapper(RecordXXX)
#
# 牌譜以全知視角記錄（四家配牌、每家可選的動作都有）。重播時選定一個座位，
# 轉成那一家在即時對局中會收到的訊息，交給同一套轉譯器處理。
import base64

from qmax.platforms.base import Message
from qmax.platforms.majsoul.liqi import schema, to_dict
from qmax.platforms.majsoul.messages import ACTION_PROTOTYPE, AUTH_GAME, GAME_END_RESULT

EXCHANGE_OPTION = 12  # operation_list[].type：換牌


def flatten(record: dict) -> list[dict]:
    """[{"method": ".lq.RecordXXX", "data": {...}}, ...]，依時間順序。"""
    if not record.get("data"):
        return []
    s = schema()
    name, payload = s.unwrap(base64.b64decode(record["data"]))
    if name != ".lq.GameDetailRecords":
        raise ValueError(f"非預期的外層包裝：{name!r}")

    flat = []
    for action in s.parse("GameDetailRecords", payload).actions:
        if not action.result:  # 系統事件
            continue
        method, data = s.unwrap(action.result)
        flat.append({"method": method, "data": to_dict(s.parse(method.rsplit(".", 1)[-1], data))})
    return flat


def players(record: dict) -> list[dict]:
    """[{"seat", "account_id", "nickname"}]，依座位；電腦玩家的 account_id 為 0。"""
    head = record.get("head") or {}
    by_seat = {a.get("seat", 0): a for a in head.get("accounts") or []}
    count = max(_player_count(record), max(by_seat, default=-1) + 1)
    return [
        {
            "seat": seat,
            "account_id": by_seat.get(seat, {}).get("account_id", 0),
            "nickname": by_seat.get(seat, {}).get("nickname", "電腦"),
        }
        for seat in range(count)
    ]


def _player_count(record: dict) -> int:
    # accounts 不含電腦玩家，人數要從配點清單看
    for item in flatten(record):
        if item["method"] == ".lq.RecordNewRound":
            return len(item["data"].get("scores") or [])
    return 0


def to_live_messages(record: dict, seat: int) -> list[Message]:
    """轉成 seat 這一家視角的即時對局訊息。"""
    # 電腦玩家沒有帳號，給不重複的負數，讓轉譯器認得出自己
    table = players(record)
    seat_list = [p["account_id"] or -(p["seat"] + 1) for p in table]
    nicknames = [{"account_id": account, "nickname": p["nickname"]} for account, p in zip(seat_list, table)]
    config = (record.get("head") or {}).get("config") or {}
    messages = [
        {"id": 0, "type": "Req", "method": AUTH_GAME, "data": {"account_id": seat_list[seat]}},
        {"id": 0, "type": "Res", "method": AUTH_GAME,
         "data": {"seat_list": seat_list, "players": nicknames, "game_config": config}},
    ]
    new_round = {}
    for step, item in enumerate(flatten(record)):
        name = "Action" + item["method"].rsplit(".", 1)[-1].removeprefix("Record")
        data = _as_seen_by(seat, name, dict(item["data"]))
        if name == "ActionNewRound":
            new_round = data
        elif name == "ActionChangeTile":
            # 牌譜的開局沒有記下換牌選項，從這局後面有換牌補回去，讓重播也會做換牌分析
            new_round["operation"] = {"seat": seat, "operation_list": [{"type": EXCHANGE_OPTION}]}
        messages.append({"id": step, "type": "Notify", "method": ACTION_PROTOTYPE, "data": {"name": name, "data": data}})
    messages.append({"id": 0, "type": "Notify", "method": GAME_END_RESULT, "data": {}})
    return messages


def _as_seen_by(seat: int, name: str, data: dict) -> dict:
    def own(operation):
        return operation if operation and operation.get("seat", 0) == seat else None

    if name == "ActionNewRound":
        data["tiles"] = data.get(f"tiles{seat}") or []  # tiles0..tiles3：各家配牌
        data["doras"] = data.get("doras") or ([data["dora"]] if data.get("dora") else [])  # 舊牌譜只有 dora
        data["operation"] = own(data.get("operation"))
    elif name == "ActionDiscardTile":
        # operations：每一家對這張牌可選的動作
        data["operation"] = next((o for o in data.get("operations") or [] if o.get("seat", 0) == seat), None)
    elif name in ("ActionDealTile", "ActionChiPengGang"):
        data["operation"] = own(data.get("operation"))
    elif name == "ActionChangeTile":
        infos = data.get("change_tile_infos") or []  # 依座位
        mine = infos[seat] if seat < len(infos) else {}
        data = {"in_tiles": mine.get("in_tiles") or [], "out_tiles": mine.get("out_tiles") or [], "doras": data.get("doras") or []}
    return data
