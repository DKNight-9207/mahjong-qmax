# 通用牌局動作 → mjai 事件（一家的視角）。
#
# mjai 是開源麻將 AI 共用的事件格式（Mortal、mjai-reviewer…），一個事件一個 JSON：
#   start_game / start_kyoku / tsumo / dahai / reach / reach_accepted / chi / pon / daiminkan /
#   kakan / ankan / dora / hora / ryukyoku / end_kyoku / end_game
# 只支援四人一般規則：三麻與 GameStarted.variants 列出的特殊規則沒有對應的事件，遇到就丟 MjaiUnsupported。
#
# 別家的配牌與摸牌一律寫成 "?"（即使來源是看得到全部的牌譜），和 AI 實際對局時看到的一樣。
from dataclasses import dataclass, field

from qmax.game import actions as act
from qmax.game.tiles import JOKER, normalize

MjaiEvent = dict

_HONORS = {"1z": "E", "2z": "S", "3z": "W", "4z": "N", "5z": "P", "6z": "F", "7z": "C"}
UNKNOWN = "?"

VARIANT_ZH = {"exchange": "開局換牌", "xuezhan": "血戰到底", "jokers": "萬用牌", "dark": "暗切（暗夜之戰）"}


class MjaiUnsupported(Exception):
    """這場對局用到 mjai 表達不了的規則。"""


class MjaiMismatch(Exception):
    """動作和目前的牌對不上（例如紀錄缺了動作），繼續轉下去會產生錯的檔案。"""


def mjai_tile(tile: str | None) -> str:
    """通用牌碼 → mjai 牌碼：赤5 是 "5mr"，字牌是 E S W N P F C，看不到的牌是 "?"。"""
    if tile is None:
        return UNKNOWN
    if tile == JOKER:
        raise MjaiUnsupported("萬用牌（萬象修羅）")
    if tile in _HONORS:
        return _HONORS[tile]
    if tile[0] == "0":
        return f"5{tile[1]}r"
    return tile


@dataclass
class _Round:
    scores: list[int]
    oya: int
    dora_count: int
    hand: list[str]  # 自己的手牌（通用牌碼）
    melds: int = 0  # 自己的副露數（含暗槓）
    last_tsumo: str | None = None  # 自己最後摸的牌
    pons: list[list[str]] = field(default_factory=lambda: [[] for _ in range(4)])  # 各家的碰（加槓用）
    last_discarder: int | None = None  # 榮和時找放銃者
    last_kakan: int | None = None  # 搶槓


class MjaiConverter:
    def __init__(self):
        self.self_seat = 0
        self._round: _Round | None = None

    def convert(self, action: act.Action) -> list[MjaiEvent]:
        handler = getattr(self, "_" + type(action).__name__, None)
        if handler is None:
            raise MjaiUnsupported(f"{type(action).__name__}")
        return handler(action)

    # ---- 對局流程 ----------------------------------------------------------

    def _GameStarted(self, a: act.GameStarted) -> list[MjaiEvent]:
        if a.num_players != 4:
            raise MjaiUnsupported("三人麻將")
        if a.variants:
            raise MjaiUnsupported("、".join(VARIANT_ZH.get(v, v) for v in a.variants))
        self.self_seat = a.self_seat
        names = list(a.player_names) or [""] * 4
        return [{"type": "start_game", "id": a.self_seat, "names": names}]

    def _RoundStarted(self, a: act.RoundStarted) -> list[MjaiEvent]:
        if any(o.kind == "exchange" for o in a.options):
            raise MjaiUnsupported("開局換牌（修羅之戰、萬象修羅）")
        oya = a.kyoku % 4
        hand = list(a.hand)
        # 莊家的配牌是 14 張，mjai 是 13 張加一次摸牌
        first_draw = hand.pop() if len(hand) == 14 else None
        self._round = _Round(scores=list(a.scores), oya=oya, dora_count=len(a.dora_indicators), hand=hand)
        tehais = [[UNKNOWN] * 13 for _ in range(4)]
        tehais[self.self_seat] = [mjai_tile(t) for t in hand]
        events = [{
            "type": "start_kyoku",
            "bakaze": mjai_tile(a.round_wind),
            "dora_marker": mjai_tile(a.dora_indicators[0]),
            "kyoku": oya + 1,
            "honba": a.honba,
            "kyotaku": a.kyotaku,
            "oya": oya,
            "scores": list(a.scores),
            "tehais": tehais,
        }]
        events += [{"type": "dora", "dora_marker": mjai_tile(t)} for t in a.dora_indicators[1:]]
        events += self._TileDrawn(act.TileDrawn(oya, first_draw if oya == self.self_seat else None))
        return events

    def _RoundEnded(self, a: act.RoundEnded) -> list[MjaiEvent]:
        r = self._round
        events = []
        if a.reason != "win":
            scores = a.scores or r.scores
            events.append({"type": "ryukyoku", "deltas": [new - old for new, old in zip(scores, r.scores)]})
        self._round = None
        return events + [{"type": "end_kyoku"}]

    def _GameEnded(self, a: act.GameEnded) -> list[MjaiEvent]:
        return [{"type": "end_game"}]

    # ---- 牌桌動作 ----------------------------------------------------------

    def _DoraIndicatorsChanged(self, a: act.DoraIndicatorsChanged) -> list[MjaiEvent]:
        r = self._round
        new = a.dora_indicators[r.dora_count:]
        r.dora_count = max(r.dora_count, len(a.dora_indicators))
        return [{"type": "dora", "dora_marker": mjai_tile(t)} for t in new]

    def _RiichiAccepted(self, a: act.RiichiAccepted) -> list[MjaiEvent]:
        self._round.scores[a.seat] = a.score
        return [{"type": "reach_accepted", "actor": a.seat}]

    def _TileDrawn(self, a: act.TileDrawn) -> list[MjaiEvent]:
        r = self._round
        mine = a.seat == self.self_seat
        if mine:
            if a.tile is None:
                raise MjaiMismatch("自己摸牌卻不知道是哪一張")
            r.hand.append(a.tile)
            r.last_tsumo = a.tile
            self._check_hand(14)
        return [{"type": "tsumo", "actor": a.seat, "pai": mjai_tile(a.tile if mine else None)}]

    def _TileDiscarded(self, a: act.TileDiscarded) -> list[MjaiEvent]:
        r = self._round
        tsumogiri = a.tsumogiri
        if a.seat == self.self_seat:
            self._take(a.tile, 1)
            self._check_hand(13)
            tsumogiri = tsumogiri and a.tile == r.last_tsumo  # 莊家第一打：哪張算「摸到的」是我們選的
        r.last_discarder, r.last_kakan = a.seat, None
        events = [{"type": "reach", "actor": a.seat}] if a.riichi else []
        return events + [{"type": "dahai", "actor": a.seat, "pai": mjai_tile(a.tile), "tsumogiri": tsumogiri}]

    def _Called(self, a: act.Called) -> list[MjaiEvent]:
        r = self._round
        consumed = list(a.tiles)
        consumed.remove(a.called_tile)
        if a.seat == self.self_seat:
            for tile in consumed:
                self._take(tile, 1)
            r.melds += 1
        if a.kind == "pon":
            r.pons[a.seat].append(list(a.tiles))
        kind = {"chi": "chi", "pon": "pon", "minkan": "daiminkan"}[a.kind]
        return [{
            "type": kind, "actor": a.seat, "target": a.from_seat,
            "pai": mjai_tile(a.called_tile), "consumed": [mjai_tile(t) for t in consumed],
        }]

    def _KanDeclared(self, a: act.KanDeclared) -> list[MjaiEvent]:
        r = self._round
        mine = a.seat == self.self_seat
        if a.kind == "ankan":
            consumed = self._take(a.tile, 4) if mine else _ankan_tiles(a.tile)
            if mine:
                r.melds += 1
            return [{"type": "ankan", "actor": a.seat, "consumed": [mjai_tile(t) for t in consumed]}]
        pon = next((p for p in r.pons[a.seat] if normalize(p[0]) == normalize(a.tile)), None)
        if pon is None:
            raise MjaiMismatch(f"座位 {a.seat} 加槓 {a.tile}，但沒有對應的碰")
        r.pons[a.seat].remove(pon)
        if mine:
            self._take(a.tile, 1)
        r.last_kakan = a.seat
        return [{"type": "kakan", "actor": a.seat, "pai": mjai_tile(a.tile), "consumed": [mjai_tile(t) for t in pon]}]

    def _Won(self, a: act.Won) -> list[MjaiEvent]:
        if a.round_continues:
            raise MjaiUnsupported("血戰到底")
        r = self._round
        deltas = [new - old for new, old in zip(a.scores, r.scores)] if a.scores else None
        events = []
        for w in a.wins:
            if w.zimo:
                target = w.seat
            elif w.deal_in_seat is not None:
                target = w.deal_in_seat
            else:
                target = r.last_kakan if r.last_kakan is not None else r.last_discarder
            event = {"type": "hora", "actor": w.seat, "target": target}
            if deltas and len(a.wins) == 1:  # 一炮多響時分不出每一家的增減
                event["deltas"] = deltas
            events.append(event)
        if a.scores:
            r.scores = list(a.scores)
        return events

    def _NorthPulled(self, a: act.NorthPulled) -> list[MjaiEvent]:
        raise MjaiUnsupported("拔北（三人麻將）")

    def _TilesExchanged(self, a: act.TilesExchanged) -> list[MjaiEvent]:
        raise MjaiUnsupported("換牌（修羅之戰、萬象修羅）")

    # ---- 自己的手牌 --------------------------------------------------------

    def _take(self, tile: str, count: int) -> list[str]:
        """從自己的手牌拿走 count 張同種的牌（赤5 與 5 視為同種，優先拿完全相同的），回傳拿走的牌。"""
        hand = self._round.hand
        taken = []
        for _ in range(count):
            exact = tile if tile in hand else next((t for t in hand if normalize(t) == normalize(tile)), None)
            if exact is None:
                raise MjaiMismatch(f"自己的手牌裡沒有 {tile}：{' '.join(hand)}")
            hand.remove(exact)
            taken.append(exact)
        return taken

    def _check_hand(self, expected_without_melds: int):
        r = self._round
        expected = expected_without_melds - 3 * r.melds
        if len(r.hand) != expected:
            raise MjaiMismatch(f"自己的手牌應該是 {expected} 張，實際 {len(r.hand)} 張（紀錄可能缺了動作）")


def _ankan_tiles(tile: str) -> list[str]:
    """別家的暗槓只知道是哪種牌。5 的暗槓假設含一張赤5（雀魂四麻每種花色一張赤5）。"""
    base = normalize(tile)
    if base[0] == "5" and base[1] != "z":
        return [base, base, base, "0" + base[1]]
    return [base] * 4
