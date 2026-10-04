# 解析器的共同語言：引擎問「這個決策點怎麼做」（Decision），解析器回答排序好的選擇（Advice）。
#
# 各解析器擅長的東西不同：mahjong-helper 給向聽、進張、和率、打點這類可解釋的數字，
# 訓練出來的 AI 給每個選擇的機率或期望值。Candidate 把兩邊會用到的欄位都列出來，
# 沒有的就是 None，前端看哪些欄位有值決定怎麼顯示；比較不同解析器時只比排序與首選，
# 分數跨解析器沒有意義。
from dataclasses import dataclass, field
from typing import Literal

from qmax.game.actions import Option
from qmax.game.tiles import normalize

MoveKind = Literal[
    "discard",  # 切牌
    "riichi",  # 立直宣言並切牌
    "chi", "pon", "minkan", "ankan", "kakan",
    "nuki",  # 拔北
    "tsumo", "ron",
    "kyuushu",  # 九種九牌
    "exchange",  # 開局換牌
    "pass",  # 不鳴牌
]
DecisionKind = Literal[
    "discard",  # 摸牌或鳴牌後要切哪張
    "call",  # 別家打牌後要不要吃碰槓
    "exchange",  # 開局換哪幾張
    "status",  # 不是決策：13 張時的目前狀況（向聽、進張、聽牌時的和率）
]
AdviceNote = Literal[
    "jokers",  # 手牌有萬用牌，只算了向聽與進張
    "unknown_incoming",  # 換牌：換入的牌未知，當成沒用的牌評估
    "pass_not_rated",  # 鳴牌：沒有評估「不鳴」，只比較各種鳴法
    "supplemented",  # 向聽、進張等數值是另一個解析器補上的（排序仍是這個解析器的）
]


@dataclass
class Move:
    kind: MoveKind
    tiles: list[str] = field(default_factory=list)
    # discard/riichi：切的牌；吃碰大明槓：自己手上出的牌；暗槓/加槓/拔北：那張牌；exchange：換出的牌
    meld: str | None = None  # 吃碰槓叫出的副露記法，例如 "555z"


@dataclass
class Wait:
    tile: str
    count: int  # 剩餘枚數


@dataclass
class Candidate:
    move: Move | None  # status 時為 None
    shanten: int | None = None  # 這樣做之後的向聽
    waits: list[Wait] | None = None  # 進張；聽牌時是聽的牌
    wait_count: int | None = None  # 進張的剩餘枚數合計
    agari_rate: float | None = None  # 和率（%），聽牌時
    riichi_point: float | None = None  # 立直時的平均打點
    dama_point: float | None = None  # 默聽時的平均打點
    improve_count: int | None = None  # 改良的種數
    improve_waits: float | None = None  # 改良後的平均進張
    next_waits: float | None = None  # 前進一向聽後的平均進張
    mixed_score: float | None = None  # mahjong-helper 的綜合評分
    yaku: list[str] | None = None  # 可能的役（通用役名，見 game/yaku.py）
    furiten: bool | None = None  # 可能振聽
    deal_in_rate: float | None = None  # 打出的牌放銃的機率（%）
    probability: float | None = None  # AI：選這個的機率
    value: float | None = None  # AI：期望值（單位由解析器決定，例如 akochan 是順位點）
    followup: "Advice | None" = None  # 鳴牌：叫完之後的切牌建議
    unavailable: Literal["suit_mismatch", "tiles_not_in_hand"] | None = None  # 鳴牌：沒辦法模擬的原因


@dataclass
class Advice:
    engine: str  # 解析器名稱，例如 "mahjong-helper"
    kind: DecisionKind
    candidates: list[Candidate]  # 由好到壞
    shanten: int | None = None  # 目前的向聽
    notes: list[AdviceNote] = field(default_factory=list)

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


def same_move(a: Move, b: Move) -> bool:
    """赤5 與 5 視為同一張；切牌與立直切牌視為同一個選擇（不是每個解析器都分得出要不要立直）。"""
    discard = {"discard", "riichi"}
    if a.kind != b.kind and not (a.kind in discard and b.kind in discard):
        return False
    return sorted(map(normalize, a.tiles)) == sorted(map(normalize, b.tiles))


@dataclass
class Decision:
    kind: DecisionKind
    options: list[Option] = field(default_factory=list)  # 平台給的合法選項（有的話）
    called_tile: str | None = None  # call：別家打出、可以鳴的牌
    exchange_count: int = 0  # exchange：要換出幾張


# ---- 危險度 -------------------------------------------------------------------


@dataclass
class TileDanger:
    tile: str
    risk: float  # 放銃危險度（越大越危險）
    left_count: int  # 場上還沒看到的張數
    in_hand: int  # 自己手上有幾張


@dataclass
class Danger:
    """某一家對自己的威脅。"""

    turns: int  # 巡目
    tenpai_rate: float  # 聽牌機率（%）
    ron_point: float  # 被榮和時的估計打點
    safe_tiles: list[str]
    tiles: list[TileDanger]  # 每種牌的危險度
