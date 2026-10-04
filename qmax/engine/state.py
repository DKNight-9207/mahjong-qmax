# 場況紀錄：自己的手牌，以及各家的棄牌、副露、立直、拔北、點數。只記錄，不分析。
from qmax.game.tiles import JOKER, WIND_TILES, ankan_notation, is_ankan, meld_notation, normalize


class RoundState:
    """座位資訊在進入對局時設定，其餘每局重置。"""

    def __init__(self):
        self.self_seat = 0
        self.num_players = 4
        self.start_round(round_wind="1z", kyoku=0, dora_indicators=[], scores=[], hand=[])

    # ---- 更新 --------------------------------------------------------------

    def start_game(self, self_seat: int, num_players: int):
        self.self_seat = self_seat
        self.num_players = num_players or self.num_players

    def start_round(self, round_wind: str, kyoku: int, dora_indicators: list[str], scores: list[int], hand: list[str]):
        n = self.num_players
        self.round_wind = round_wind
        self.dealer_seat = kyoku % n
        self.dora_indicators = list(dora_indicators)
        self.round_start_scores = list(scores)
        self.scores = list(scores)  # 立直棒付出後就先扣
        self.my_hand = list(hand)
        self.melds: list[list[str]] = [[] for _ in range(n)]  # 副露記法
        self.discards: list[list[dict]] = [[] for _ in range(n)]  # [{"tile", "tsumogiri"}]
        self.is_riichi = [False] * n
        self.nuki_count = [0] * n
        # 副露後打出的第一張牌在 discards 裡的位置；聽牌率用「副露後手切了幾張」估計
        self.meld_discards_at: list[list[int]] = [[] for _ in range(n)]
        self._meld_pending = [False] * n
        # 被自己叫走的別家棄牌：棄牌史保留原樣，但算場上可見牌時要扣掉，
        # 否則會同時算在棄牌與自己的副露裡
        self.called_from_others: list[str] = []
        # 不在棄牌裡、但已離開牌山的牌：別家副露中從手牌亮出的、所有人拔的北
        self.revealed: list[str] = []

    def set_dora_indicators(self, dora_indicators: list[str]) -> bool:
        """回傳是否有變動。"""
        if dora_indicators == self.dora_indicators:
            return False
        self.dora_indicators = list(dora_indicators)
        return True

    def set_score(self, seat: int, score: int):
        if 0 <= seat < len(self.scores):
            self.scores[seat] = score

    def draw(self, tile: str):
        self.my_hand.append(tile)

    def discard(self, seat: int, tile: str, tsumogiri: bool, riichi: bool):
        self.discards[seat].append({"tile": tile, "tsumogiri": tsumogiri})
        if self._meld_pending[seat]:
            self.meld_discards_at[seat].append(len(self.discards[seat]) - 1)
            self._meld_pending[seat] = False
        if riichi:
            self.is_riichi[seat] = True
        if seat == self.self_seat:
            self._remove_from_hand(tile)

    def call(self, seat: int, tiles: list[str], called_tile: str):
        """吃/碰/大明槓。"""
        own_tiles = list(tiles)
        own_tiles.remove(called_tile)
        if seat == self.self_seat:
            self.called_from_others.append(called_tile)
            for tile in own_tiles:
                self._remove_from_hand(tile)
        else:
            self.revealed += own_tiles
        meld = meld_notation(tiles)
        if meld is not None:
            self.melds[seat].append(meld)
        self._meld_pending[seat] = True

    def ankan(self, seat: int, tile: str) -> int:
        """回傳從手牌拿走的張數（別家一律 4）。tile 是赤5 時，其餘三張是一般 5。"""
        if seat != self.self_seat:
            tiles = [tile] + [normalize(tile)] * 3
            self.revealed += tiles
            self.melds[seat].append(ankan_notation(tiles))
            self._meld_pending[seat] = True
            return 4
        taken = self._take(tile, 4)
        missing = [normalize(tile)] * (4 - len(taken))  # 紀錄跟丟時補齊，副露記法維持四張
        self.melds[seat].append(ankan_notation(taken + missing))
        return len(taken)

    def kakan(self, seat: int, tile: str):
        """碰升級成槓。碰與加槓的牌可能一張是赤5、一張是一般 5。"""
        if seat == self.self_seat:
            added = self._take(tile, 1) or [tile]
        else:
            added = [tile]
            self.revealed.append(tile)
        melds = self.melds[seat]
        for i, meld in enumerate(melds):
            if _is_pon_of(meld, tile):
                melds[i] = meld_notation([digit + meld[-1] for digit in meld[:-1]] + added)
                return
        melds.append(meld_notation([normalize(tile)] * 3 + added))

    def nuki(self, seat: int):
        if seat == self.self_seat:
            self._remove_from_hand("4z")
        self.nuki_count[seat] += 1
        self.revealed.append("4z")

    def exchange_tiles(self, out_tiles: list[str], in_tiles: list[str]):
        for tile in out_tiles:
            self._remove_from_hand(tile)
        self.my_hand += in_tiles

    def _take(self, tile: str, count: int) -> list[str]:
        """拿走最多 count 張與 tile 同種的牌（赤5 與 5 同種），優先拿完全相同的。"""
        taken = []
        for _ in range(count):
            match = tile if tile in self.my_hand else next(
                (t for t in self.my_hand if normalize(t) == normalize(tile)), None
            )
            if match is None:
                break
            self.my_hand.remove(match)
            taken.append(match)
        return taken

    def _remove_from_hand(self, tile: str):
        if tile in self.my_hand:
            self.my_hand.remove(tile)

    # ---- 查詢 --------------------------------------------------------------

    @property
    def self_melds(self) -> list[str]:
        return self.melds[self.self_seat]

    @property
    def nuki_dora(self) -> int:
        return self.nuki_count[self.self_seat]

    @property
    def jokers(self) -> int:
        return self.my_hand.count(JOKER)

    @property
    def is_sanma(self) -> bool:
        return self.num_players == 3

    @property
    def is_naki(self) -> bool:
        """暗槓不算，同 Go 的 PlayerInfo.IsNaki()。"""
        return any(not is_ankan(meld) for meld in self.self_melds)

    @property
    def self_is_riichi(self) -> bool:
        return self.is_riichi[self.self_seat]

    def seat_wind(self, seat: int) -> str:
        return WIND_TILES[(seat - self.dealer_seat) % self.num_players]

    def hand_str(self) -> str:
        """analyzer 的手牌記法：手牌 # 副露。萬用牌不寫進去，張數另外給（jokers）。"""
        return _hand_notation(self.my_hand, self.self_melds)

    def hand_str_after_call(self, own_tiles: list[str], meld: str) -> str | None:
        """用 own_tiles 叫出 meld 之後的手牌記法；手牌湊不出 own_tiles 時回傳 None。"""
        remaining = list(self.my_hand)
        for tile in own_tiles:
            if tile not in remaining:
                return None
            remaining.remove(tile)
        return _hand_notation(remaining, self.self_melds + [meld])

    def visible_str(self, exclude: str | None = None) -> str:
        """場上看得到、不在自己手牌與副露裡的牌。exclude：再多扣一張（模擬叫牌時被叫的那張）。"""
        tiles = self.dora_indicators + self.revealed + [d["tile"] for pile in self.discards for d in pile]
        for tile in self.called_from_others + ([exclude] if exclude else []):
            if tile in tiles:
                tiles.remove(tile)
        return " ".join(tiles)

    def own_discards_str(self) -> str:
        return " ".join(d["tile"] for d in self.discards[self.self_seat])

    def snapshot(self) -> dict:
        """analyze_log 記錄用。"""
        return {
            "self_seat": self.self_seat,
            "num_players": self.num_players,
            "dealer_seat": self.dealer_seat,
            "round_wind": self.round_wind,
            "dora_indicators": list(self.dora_indicators),
            "my_hand": list(self.my_hand),
            "melds": [list(m) for m in self.melds],
            "discards": [list(pile) for pile in self.discards],
            "is_riichi": list(self.is_riichi),
            "nuki_count": list(self.nuki_count),
            "revealed": list(self.revealed),
        }


def _hand_notation(hand: list[str], melds: list[str]) -> str:
    tiles = " ".join(t for t in hand if t != JOKER)
    return f"{tiles} # {' '.join(melds)}" if melds else tiles


def _is_pon_of(meld: str, tile: str) -> bool:
    base = normalize(tile)
    return len(meld) == 4 and meld[-1] == base[1] and {normalize(d + meld[-1]) for d in meld[:-1]} == {base}
