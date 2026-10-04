# 決策紀錄：每個決策點記下當時的場況、各解析器的建議、實際怎麼做。
# 用來比較解析器（彼此、和實際打法），之後也可以當訓練資料。
#
# 用法：引擎的 on_decision 接到 DecisionLog.on_decision；每個動作交給引擎之前先呼叫
# before(action)（判斷上一個決策實際怎麼做，也轉給要比較的解析器）。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qmax.advice.base import Advisor, AdvisorError
from qmax.advice.model import Advice, Decision, Move, same_move
from qmax.game import actions as act
from qmax.game.tiles import meld_notation

if TYPE_CHECKING:
    from qmax.engine.state import RoundState

# 附帶在其他動作上的變化，不代表任何人做了選擇
_SIDE_EFFECTS = (act.DoraIndicatorsChanged, act.RiichiAccepted)
_WAIT = object()  # 這個動作還看不出實際怎麼做


@dataclass
class DecisionRecord:
    round_wind: str
    kyoku: int
    honba: int
    state: dict  # RoundState.snapshot()
    decision: Decision
    advice: dict[str, Advice | None]  # 解析器名稱 → 建議；失敗時是 None
    actual: Move | None = None  # 實際怎麼做；看不出來（例如紀錄在這裡結束）時是 None
    ranks: dict[str, int | None] = field(default_factory=dict)  # 實際的選擇排在各解析器的第幾（0 起算）


class DecisionLog:
    def __init__(self, primary: Advisor, extras: list[Advisor] | None = None):
        """primary：引擎用的解析器（建議由引擎轉來）；extras：另外要比較的解析器，每個決策點各問一次。"""
        self.primary = primary
        self.extras = list(extras or [])
        self.records: list[DecisionRecord] = []
        self._pending: list[DecisionRecord] = []
        self._round = ("", 0, 0)
        self._self_seat = 0

    # ---- 接收 --------------------------------------------------------------

    def on_decision(self, decision: Decision, advice: Advice | None, state: RoundState):
        if decision.kind == "status":
            return
        advices = {self.primary.name: advice}
        for extra in self.extras:
            try:
                advices[extra.name] = extra.advise(decision, state)
            except AdvisorError:
                advices[extra.name] = None
        record = DecisionRecord(*self._round, state=state.snapshot(), decision=decision, advice=advices)
        self._self_seat = state.self_seat
        self.records.append(record)
        self._pending.append(record)

    def before(self, action: act.Action):
        if isinstance(action, act.RoundStarted):
            self._round = (action.round_wind, action.kyoku, action.honba)
        if isinstance(action, act.GameStarted):
            self._self_seat = action.self_seat
        for extra in self.extras:
            extra.observe(action)
        while self._pending:
            record = self._pending[0]
            actual = _actual_move(record.decision, action, self._self_seat)
            if actual is _WAIT:
                return
            self._resolve(record, actual)

    def finish(self):
        """紀錄結束時還沒看到結果的決策。"""
        for record in list(self._pending):
            self._resolve(record, None)

    def _resolve(self, record: DecisionRecord, actual: Move | None):
        self._pending.remove(record)
        record.actual = actual
        record.ranks = {name: rank_of(actual, advice) for name, advice in record.advice.items()}


def _actual_move(decision: Decision, action: act.Action, me: int):
    """從決策之後的下一個動作看出實際的選擇。"""
    if isinstance(action, _SIDE_EFFECTS):
        return _WAIT
    if decision.kind == "exchange":
        if isinstance(action, act.TilesExchanged):
            return Move("exchange", list(action.out_tiles))
        if isinstance(action, (act.RoundEnded, act.RoundStarted, act.GameEnded)):
            return None
        return _WAIT
    if decision.kind == "call":
        if isinstance(action, act.Called) and action.seat == me:
            own = list(action.tiles)
            own.remove(action.called_tile)
            return Move(action.kind, own, meld_notation(list(action.tiles)))
        if isinstance(action, act.Won) and any(w.seat == me and not w.zimo for w in action.wins):
            return Move("ron")
        return Move("pass")  # 包括別家先鳴或先和
    # discard：摸牌或鳴牌之後
    if isinstance(action, act.TileDiscarded) and action.seat == me:
        return Move("riichi" if action.riichi else "discard", [action.tile])
    if isinstance(action, act.KanDeclared) and action.seat == me:
        return Move(action.kind, [action.tile])
    if isinstance(action, act.NorthPulled) and action.seat == me:
        return Move("nuki", ["4z"])
    if isinstance(action, act.Won) and any(w.seat == me and w.zimo for w in action.wins):
        return Move("tsumo")
    if isinstance(action, act.RoundEnded) and action.abortive_kind == "kyuushu" and action.abortive_seat == me:
        return Move("kyuushu")
    return None


def rank_of(actual: Move | None, advice: Advice | None) -> int | None:
    """實際的選擇排在建議的第幾（0 起算）；建議裡沒有、或無從比較時是 None。"""
    if actual is None or advice is None:
        return None
    for i, candidate in enumerate(advice.candidates):
        if candidate.move is not None and same_move(candidate.move, actual):
            return i
    return None


def comparable(record: DecisionRecord, name: str) -> bool:
    """這筆決策能不能拿來算這個解析器的一致率。"""
    advice = record.advice.get(name)
    if record.actual is None or advice is None or not advice.candidates:
        return False
    if record.actual.kind == "pass" and "pass_not_rated" in advice.notes:
        return False
    # 暗槓、自摸、榮和這類選擇不在何切／鳴牌的候選裡
    if record.decision.kind == "discard" and record.actual.kind not in ("discard", "riichi"):
        return False
    if record.decision.kind == "call" and record.actual.kind not in ("chi", "pon", "minkan", "pass"):
        return False
    return True
