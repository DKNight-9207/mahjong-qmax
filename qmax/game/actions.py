# 平台轉譯器交給引擎的通用牌局動作，與哪個麻將平台無關。
#
# 座位一律是絕對座位（0 = 起始東家）；牌一律是通用牌碼（見 tiles.py）。
from dataclasses import dataclass, field
from typing import Literal

OptionKind = Literal[
    "discard", "chi", "pon", "minkan", "ankan", "kakan", "riichi", "tsumo", "ron", "kyuushu", "nuki",
    "exchange",  # 換牌（修羅之戰等模式的開局換三張）
    "unknown",
]
CallKind = Literal["chi", "pon", "minkan"]
KanKind = Literal["ankan", "kakan"]
# 特殊規則
RuleVariant = Literal[
    "exchange",  # 開局換牌（雀魂修羅之戰）
    "xuezhan",  # 血戰到底：有人和了這局還繼續
    "jokers",  # 萬用牌（雀魂萬象修羅的百搭）
    "dark",  # 可以暗切（雀魂暗夜之戰）
]
AbortiveKind = Literal["kyuushu", "suufon_renda", "suukan_sanra", "suucha_riichi", "sancha_hou", "unknown"]


@dataclass
class Option:
    """輪到自己時可以做的一個選擇。"""

    kind: OptionKind
    # 吃/碰/槓：每種組合要用到的自己手牌；立直：可以宣言的切牌，每組一張；換牌：平台預選的那組
    tile_sets: list[list[str]] = field(default_factory=list)


@dataclass
class Yaku:
    name: str  # 通用役名，見 yaku.py
    han: int  # 番數；役滿時是役滿倍數；寶牌類是張數


@dataclass
class WinResult:
    seat: int
    zimo: bool
    deal_in_seat: int | None  # 放銃者；自摸或無法判斷時為 None
    tile: str
    han: int  # 役滿時是役滿倍數
    fu: int
    points: int  # 打點，不含本場與供託；平台沒給時為 0
    yakuman: bool
    yaku: list[Yaku]


# ---- 對局流程 -------------------------------------------------------------


@dataclass
class GameStarted:
    self_seat: int
    num_players: int
    player_names: list[str] = field(default_factory=list)  # 依座位的暱稱
    variants: list[RuleVariant] = field(default_factory=list)  # 和一般規則不同的地方
    length: Literal["tonpuu", "hanchan"] | None = None  # 東風戰／半莊戰；不知道時為 None


@dataclass
class RoundStarted:
    round_wind: str  # 場風牌碼
    kyoku: int  # 局，0 起算；莊家座位 = kyoku % 人數
    honba: int
    kyotaku: int  # 供託：場上累積的立直棒數（暗夜之戰的鎖牌費也算在內），一根一千點
    dora_indicators: list[str]
    scores: list[int]  # 依座位
    hand: list[str]  # 自己的配牌（莊家 14 張）
    options: list[Option] = field(default_factory=list)  # 莊家開局就能做的選擇（立直、九種九牌…）


@dataclass
class RoundEnded:
    reason: Literal["win", "exhaustive_draw", "abortive_draw"]  # 和了 / 荒牌流局 / 途中流局
    scores: list[int] | None  # 依座位的結算後點數；None 表示沒有變動
    wins: list[WinResult] = field(default_factory=list)  # 這局全部的和了
    tenpai_seats: list[int] = field(default_factory=list)
    nagashi_mangan: bool = False
    abortive_kind: AbortiveKind | None = None
    abortive_seat: int | None = None  # 九種九牌的宣告者


@dataclass
class GameEnded:
    reason: Literal["finished", "terminated"]  # 打完 / 中途離桌


# ---- 牌桌動作 -------------------------------------------------------------


@dataclass
class DoraIndicatorsChanged:
    dora_indicators: list[str]  # 目前全部的指示牌


@dataclass
class RiichiAccepted:
    seat: int
    score: int  # 付出立直棒後的點數


@dataclass
class TileDrawn:
    seat: int
    tile: str | None  # 別家摸牌時看不到
    options: list[Option] = field(default_factory=list)  # 給自己的選擇


@dataclass
class TileDiscarded:
    seat: int
    tile: str
    tsumogiri: bool
    riichi: bool  # 立直宣言牌
    options: list[Option] = field(default_factory=list)  # 自己對這張牌能做的選擇


@dataclass
class Called:
    """吃/碰/大明槓。"""

    seat: int
    kind: CallKind
    tiles: list[str]  # 整組副露
    called_tile: str  # 其中從別家拿來的那張
    from_seat: int


@dataclass
class KanDeclared:
    """暗槓/加槓。"""

    seat: int
    kind: KanKind
    tile: str  # 赤5 參與時可能是赤5 的牌碼


@dataclass
class NorthPulled:
    """三麻拔北。"""

    seat: int


@dataclass
class TilesExchanged:
    """自己換牌（修羅之戰等模式）。"""

    out_tiles: list[str]
    in_tiles: list[str]
    options: list[Option] = field(default_factory=list)  # 莊家換完牌接著要打牌，這時能做的選擇


@dataclass
class Won:
    wins: list[WinResult]
    scores: list[int]  # 依座位，這次和了結算後的點數
    round_continues: bool  # 血戰到底中途和了，這局還沒結束


Action = (
    GameStarted | RoundStarted | RoundEnded | GameEnded
    | DoraIndicatorsChanged | RiichiAccepted | TileDrawn | TileDiscarded
    | Called | KanDeclared | NorthPulled | TilesExchanged | Won
)
