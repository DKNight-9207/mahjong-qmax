# akochan 的轉接：牌局動作 → mjai 事件 → akochan 的 ai_review → Advice。
#
# akochan 每個決策點都從這局的完整紀錄重算，所以這裡只記事件，被問到時才把這局的紀錄整份送過去。
# 它評估的是「這樣做之後的期望順位點」（akochan 的 pt_exp_total），沒有向聽、進張、危險度；
# 13 張時的目前狀況與換牌也不處理（交給 CombinedAdvisor 的輔助解析器）。
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from qmax.advice.akochan.server import DEFAULT_TACTICS, AkochanServer, AkochanServerError
from qmax import ROOT
from qmax.advice.base import Advisor, AdvisorError, OnCall
from qmax.advice.model import Advice, Candidate, Decision, Move
from qmax.game import actions as act
from qmax.game.tiles import meld_notation
from qmax.mjai import MjaiConverter, MjaiMismatch, MjaiUnsupported

if TYPE_CHECKING:
    from qmax.engine.state import RoundState

# akochan 的 start_game 擴充欄位：kyoku_first 是「從第幾局開始算」，半莊戰 0、東風戰 4（只剩南場的長度）
KYOKU_FIRST = {"hanchan": 0, "tonpuu": 4}

_FROM_MJAI = {"E": "1z", "S": "2z", "W": "3z", "N": "4z", "P": "5z", "F": "6z", "C": "7z"}
_CALLS = {"chi": "chi", "pon": "pon", "daiminkan": "minkan"}


def generic_tile(pai: str) -> str:
    if pai in _FROM_MJAI:
        return _FROM_MJAI[pai]
    if pai.endswith("r"):
        return "0" + pai[1]
    return pai


class AkochanAdvisor(Advisor):
    name = "akochan"
    tactics: Path = DEFAULT_TACTICS

    def __init__(self, on_call: OnCall | None = None):
        self.on_call = on_call
        self._server: AkochanServer | None = None
        self._start_server()
        self._converter = MjaiConverter()
        self._start_game: dict | None = None
        self._round: list[dict] = []  # 這局的 mjai 事件（從 start_kyoku 起）
        self._unsupported: str | None = None  # 這場不能用 akochan 的原因
        self._last_call_review: list | None = None  # 鳴牌決策的結果，鳴完之後的打牌直接沿用

    @classmethod
    def open(cls, on_call: OnCall | None = None) -> AkochanAdvisor:
        return cls(on_call)

    def _start_server(self):
        try:
            self._server = AkochanServer(self.tactics)
        except (AkochanServerError, OSError) as e:
            raise AdvisorError(f"akochan 啟動失敗：{e}", "unreachable") from e

    def close(self):
        if self._server is not None:
            self._server.close()

    def is_alive(self) -> bool:
        return True  # 子行程結束了下次會重開

    # ---- 記錄事件 ----------------------------------------------------------

    def observe(self, action: act.Action):
        if isinstance(action, act.GameStarted):
            self._converter = MjaiConverter()
            self._unsupported = None
            self._round = []
        if self._unsupported:
            return
        try:
            events = self._converter.convert(action)
        except (MjaiUnsupported, MjaiMismatch) as e:
            self._unsupported = str(e)
            logger.warning(f"akochan 這場不分析：{e}")
            return
        for event in events:
            if event["type"] == "start_game":
                event["kyoku_first"] = KYOKU_FIRST.get(action.length or "hanchan", 0)
                event["aka_flag"] = True  # 雀魂四麻有赤5
                self._start_game = event
            elif event["type"] == "start_kyoku":
                self._round = [event]
            else:
                self._round.append(event)

    # ---- 建議 --------------------------------------------------------------

    def advise(self, decision: Decision, state: RoundState) -> Advice:
        if self._unsupported:
            raise AdvisorError(f"akochan 不支援：{self._unsupported}", "rejected")
        if decision.kind in ("status", "exchange"):
            raise AdvisorError(f"akochan 沒有「{decision.kind}」的分析", "rejected")
        me = state.self_seat
        last = self._round[-1] if self._round else {}
        if decision.kind == "discard" and last.get("actor") == me and last.get("type") in ("chi", "pon"):
            return self._after_call(last)
        review = self._request(me)
        if decision.kind == "call":
            self._last_call_review = review
            return Advice(self.name, "call", _call_candidates(self.name, review))
        return Advice(self.name, "discard", _discard_candidates(review))

    def _after_call(self, call: dict) -> Advice:
        """鳴牌後的打牌：akochan 在鳴牌決策時已經連同之後要打哪張一起算好了。"""
        chosen = [
            c for c in self._last_call_review or []
            if c["moves"][0]["type"] == call["type"] and sorted(c["moves"][0].get("consumed", [])) == sorted(call["consumed"])
        ]
        if not chosen:
            raise AdvisorError("akochan 鳴牌時沒有評估這種鳴法", "rejected")
        return Advice(self.name, "discard", _discard_candidates([{"moves": c["moves"][1:], "review": c["review"]} for c in chosen]))

    def _request(self, seat: int) -> list:
        if self._server is None or not self._server.is_alive():
            self._start_server()
        record = [self._start_game, *self._round]
        log_request = {"id": seat, "events": len(record), "last": record[-1]}  # 整份紀錄太長，日誌只記最後一個事件
        try:
            response = self._server.request(seat, record)
        except AkochanServerError as e:
            self._log(log_request, {"error": str(e)})
            raise AdvisorError(str(e), "unreachable" if e.unreachable else "internal") from e
        self._log(log_request, response)
        return response

    def _log(self, request: dict, response):
        if self.on_call:
            self.on_call("akochan.ai_review", request, response if isinstance(response, dict) else {"result": response})


class AkochanLightAdvisor(AkochanAdvisor):
    """akochan 的輕量設定（策略 base 用 light）：手牌變化少看一層、列舉的組合數設上限。
    同一場牌譜比較，計算時間約為預設的三分之一，首選有九成多相同，不同時期望順位點差距很小。"""

    name = "akochan-light"
    tactics = ROOT / "analyzer" / "akochan" / "tactics_light.json"


def _move(moves: list[dict]) -> Move | None:
    """akochan 的一組動作（例如 [reach, dahai]、[pon, dahai]）→ 這個決策點的選擇。"""
    first = moves[0]
    kind = first["type"]
    if kind == "dahai":
        return Move("discard", [generic_tile(first["pai"])])
    if kind == "reach":
        return Move("riichi", [generic_tile(moves[1]["pai"])])
    if kind == "ankan":
        return Move("ankan", [generic_tile(first["consumed"][0])])
    if kind == "kakan":
        return Move("kakan", [generic_tile(first["pai"])])
    if kind == "hora":
        return Move("tsumo" if first.get("target") == first.get("actor") else "ron")
    if kind == "ryukyoku":
        return Move("kyuushu")
    if kind == "none":
        return Move("pass")
    if kind in _CALLS:
        own = [generic_tile(t) for t in first["consumed"]]
        return Move(_CALLS[kind], own, meld_notation(own + [generic_tile(first["pai"])]))
    return None


def _candidate(move: Move, review: dict) -> Candidate:
    rate = review.get("total_houjuu_hai_prob_now")
    return Candidate(move, value=review.get("pt_exp_total"), deal_in_rate=rate * 100 if rate is not None else None)


def _discard_candidates(review: list) -> list[Candidate]:
    candidates = [_candidate(m, c["review"]) for c in review if (m := _move(c["moves"])) is not None]
    return sorted(candidates, key=lambda c: -(c.value if c.value is not None else float("-inf")))


def _call_candidates(engine: str, review: list) -> list[Candidate]:
    """同一種鳴法接不同的打牌是好幾筆，合成一個候選，打牌放進 followup。"""
    groups: dict[tuple, Candidate] = {}
    for c in review:
        move = _move(c["moves"])
        if move is None:
            continue
        key = (move.kind, tuple(sorted(move.tiles)))
        if key not in groups:
            groups[key] = Candidate(move, value=c["review"].get("pt_exp_total"))
            if move.kind != "pass":
                groups[key].followup = Advice(engine, "discard", [])
        group = groups[key]
        if group.followup is not None and len(c["moves"]) > 1:
            group.followup.candidates.append(_candidate(_move(c["moves"][1:]), c["review"]))
            group.value = max(group.value, c["review"].get("pt_exp_total", group.value))
    for group in groups.values():
        if group.followup is not None:
            group.followup.candidates.sort(key=lambda c: -(c.value or 0))
    return sorted(groups.values(), key=lambda c: -(c.value if c.value is not None else float("-inf")))
