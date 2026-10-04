# mahjong-helper（analyzer-server）的轉接：場況 → Go 的請求，Go 的回應 → Advice / Danger。
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from qmax.advice.base import Advisor, AdvisorError, OnCall
from qmax.advice.model import Advice, Candidate, Danger, Decision, Move, TileDanger, Wait
from qmax.advice.mahjong_helper.api import AnalyzerApi, AnalyzerError
from qmax.advice.mahjong_helper.server import start_server
from qmax.game.tiles import meld_notation

if TYPE_CHECKING:
    from qmax.engine.state import RoundState

CALL_KINDS = ("chi", "pon", "minkan")

# Go 回傳的役名（mahjong-helper 的 YakuNameMap，簡體）→ 通用役名
_YAKU = {
    "立直": "riichi", "七对": "chiitoitsu", "自摸": "menzen_tsumo", "w立": "double_riichi",
    "平和": "pinfu", "两杯口": "ryanpeikou", "一杯口": "iipeikou", "三色": "sanshoku", "一通": "ittsu",
    "对对": "toitoi", "三暗刻": "sanankou", "三色同刻": "sanshoku_doukou", "三杠子": "sankantsu",
    "断幺": "tanyao", "役牌": "yakuhai", "混全": "chanta", "纯全": "junchan", "混老头": "honroutou",
    "小三元": "shousangen", "混一色": "honitsu", "清一色": "chinitsu",
    "四暗刻": "suuankou", "四暗刻单骑": "suuankou_tanki", "大三元": "daisangen", "小四喜": "shousuushii",
    "大四喜": "daisuushii", "字一色": "tsuuiisou", "清老头": "chinroutou", "绿一色": "ryuuiisou",
    "九莲": "chuuren", "纯正九莲": "junsei_chuuren", "四杠子": "suukantsu",
}
_ERROR_KINDS = {"rejected": "rejected", "panic": "internal", "unreachable": "unreachable"}


class MahjongHelperAdvisor(Advisor):
    name = "mahjong-helper"

    def __init__(self, analyzer: AnalyzerApi):
        self.analyzer = analyzer

    @classmethod
    def open(cls, on_call: OnCall | None = None) -> MahjongHelperAdvisor:
        """啟動 analyzer-server 子行程。"""
        try:
            return cls(start_server(on_call=on_call))
        except (RuntimeError, OSError) as e:  # 找不到執行檔、啟動逾時、連不上
            raise AdvisorError(f"analyzer-server 啟動失敗：{e}", "unreachable") from e

    def close(self):
        self.analyzer.close()

    @property
    def description(self) -> str:
        return f"{self.name}（analyzer-server {self.analyzer.version}）"

    def is_alive(self) -> bool:
        return self.analyzer.is_alive()

    def advise(self, decision: Decision, state: RoundState) -> Advice:
        if decision.kind == "exchange":
            return self._exchange(decision.exchange_count, state)
        if decision.kind == "call":
            return self._calls(decision, state)
        response = _ask(lambda: self.analyzer.analyze(state.hand_str(), visible=state.visible_str(), **_situation(state)))
        return _hand_advice(response, decision.kind)

    def danger(self, seat: int, state: RoundState) -> Danger:
        s = state
        response = _ask(lambda: self.analyzer.risk(
            discards=list(s.discards[seat]),
            melds=" ".join(s.melds[seat]),
            meld_discards_at=list(s.meld_discards_at[seat]),
            nuki_dora=s.nuki_count[seat],
            hand=s.hand_str(),
            jokers=s.jokers,
            visible=s.visible_str(),
            dora_indicators=" ".join(s.dora_indicators),
            round_wind=s.round_wind,
            self_wind=s.seat_wind(seat),
            is_riichi=s.is_riichi[seat],
            is_dealer=seat == s.dealer_seat,
            is_sanma=s.is_sanma,
        ))
        tiles = [TileDanger(t["tile"], t["risk"], t["left_count"], s.my_hand.count(t["tile"])) for t in response["risk"]]
        return Danger(response["turns"], response["tenpai_rate"], response["ron_point"], list(response["safe_tiles"] or []), tiles)

    def _exchange(self, count: int, state: RoundState) -> Advice:
        response = _ask(lambda: self.analyzer.exchange(state.hand_str(), jokers=state.jokers, visible=state.visible_str(), count=count))
        candidates = [
            Candidate(Move("exchange", list(c["tiles"])), shanten=c["shanten"], waits=_waits(c), wait_count=c["wait_count"])
            for c in response["candidates"]
        ]
        notes = ["unknown_incoming"] + (["jokers"] if state.jokers else [])
        return Advice(MahjongHelperAdvisor.name, "exchange", candidates, shanten=response["shanten"], notes=notes)

    def _calls(self, decision: Decision, state: RoundState) -> Advice:
        """每種鳴法模擬叫完之後的何切；不評估「不鳴」。"""
        called = decision.called_tile
        candidates = []
        for option in decision.options:
            if option.kind not in CALL_KINDS:
                continue
            for own in option.tile_sets:
                meld = meld_notation(own + [called])
                move = Move(option.kind, list(own), meld)
                hand = state.hand_str_after_call(own, meld) if meld else None
                if meld is None:
                    candidates.append(Candidate(move, unavailable="suit_mismatch"))
                elif hand is None:
                    candidates.append(Candidate(move, unavailable="tiles_not_in_hand"))
                else:
                    # 被叫的牌已經在副露裡，不能再算進場上可見牌
                    visible = state.visible_str(exclude=called)
                    response = _ask(lambda: self.analyzer.analyze(hand, visible=visible, **_situation(state)))
                    # 大明槓之後要摸嶺上牌，叫完是 13 張
                    followup = _hand_advice(response, "status" if option.kind == "minkan" else "discard")
                    best = followup.best
                    candidates.append(Candidate(
                        move, shanten=best.shanten, waits=best.waits, wait_count=best.wait_count, followup=followup,
                    ) if best else Candidate(move, followup=followup))
        candidates.sort(key=_call_rank)
        notes = ["pass_not_rated"] + (["jokers"] if state.jokers else [])
        return Advice(MahjongHelperAdvisor.name, "call", candidates, notes=notes)


def _call_rank(c: Candidate) -> tuple:
    """模擬得出來的在前；向聽小、進張多的在前。"""
    if c.shanten is None:
        return (1, 0, 0)
    return (0, c.shanten, -(c.wait_count or 0))


def _situation(s: RoundState) -> dict:
    return {
        "jokers": s.jokers,
        "dora_indicators": " ".join(s.dora_indicators),
        "is_sanma": s.is_sanma,
        "nuki_dora": s.nuki_dora,
        "round_wind": s.round_wind,
        "self_wind": s.seat_wind(s.self_seat),
        "is_dealer": s.self_seat == s.dealer_seat,
        "is_riichi": s.self_is_riichi,
        "discards": s.own_discards_str(),
    }


def _ask(request: Callable[[], dict]) -> dict:
    try:
        return request()
    except AnalyzerError as e:
        raise AdvisorError(str(e), _ERROR_KINDS.get(e.kind, "rejected")) from e


def _hand_advice(response: dict, kind: str) -> Advice:
    """/analyze 的回應。萬用牌模式只有向聽與進張可信，其餘欄位不填。"""
    jokers = response.get("jokers", 0) > 0
    candidates = _settle_ties([_hand_candidate(c, jokers) for c in response.get("candidates", [])])
    return Advice(MahjongHelperAdvisor.name, kind, candidates, shanten=response.get("shanten"), notes=["jokers"] if jokers else [])


def _hand_candidate(c: dict, jokers: bool) -> Candidate:
    move = Move("discard", [c["discard"]]) if c.get("discard") else None
    candidate = Candidate(move, shanten=c["shanten"], waits=_waits(c), wait_count=c["wait_count"])
    if jokers:
        return candidate
    candidate.agari_rate = c["avg_agari_rate"]
    candidate.riichi_point = c["riichi_point"]
    candidate.dama_point = c["dama_point"]
    candidate.improve_count = c["improve_count"]
    candidate.improve_waits = c["avg_improve_waits_count"]
    candidate.next_waits = c["avg_next_shanten_waits_count"]
    candidate.mixed_score = c["mixed_score"]
    candidate.yaku = [_YAKU.get(name, name) for name in c.get("yaku_names") or []]
    candidate.furiten = c.get("furiten_rate", 0) > 0
    return candidate


def _settle_ties(candidates: list[Candidate]) -> list[Candidate]:
    """Go 算平均值時的浮點誤差（map 的走訪順序每次不同）會讓同分的候選每次排得不一樣。
    數值相同（四捨五入到小數 6 位）的相鄰候選改依牌碼排，讓同一個局面每次結果相同。"""
    def score(c: Candidate) -> tuple:
        numbers = (c.improve_waits, c.next_waits, c.agari_rate, c.riichi_point, c.dama_point, c.mixed_score)
        return (c.shanten, c.wait_count, *(round(x, 6) if x is not None else None for x in numbers))

    settled, group = [], []
    for c in candidates:
        if group and score(c) != score(group[0]):
            settled += sorted(group, key=lambda g: g.move.tiles if g.move else [])
            group = []
        group.append(c)
    return settled + sorted(group, key=lambda g: g.move.tiles if g.move else [])


def _waits(c: dict) -> list[Wait]:
    return [Wait(w["tile"], w["count"]) for w in c.get("waits") or []]
