# 引擎通知前端的事件內容。全部是純資料，dataclasses.asdict() 後可直接轉 JSON 給 GUI。
#
# 座位一律是絕對座位（0 = 起始東家）；相對位置（下家/對家…）由前端用
# self_seat、num_players 換算。牌一律是通用牌碼，顯示名稱由前端決定。
from dataclasses import dataclass, field
from typing import Literal

from qmax.advice.model import Advice, Danger
from qmax.game.actions import AbortiveKind, CallKind, KanKind, Option, WinResult

# ---- 程式狀態 -------------------------------------------------------------


@dataclass
class ProxyStatus:
    listening: bool
    host: str
    port: int


# ---- 對局流程 -------------------------------------------------------------


@dataclass
class GameStart:
    self_seat: int
    num_players: int
    player_names: list[str]  # 依座位的暱稱


@dataclass
class RoundStart:
    round_wind: str  # 場風牌碼
    kyoku: int  # 局，0 起算
    honba: int
    kyotaku: int  # 供託棒數
    dealer_seat: int
    self_wind: str
    dora_indicators: list[str]
    scores: list[int]  # 依座位
    hand: list[str]  # 自己的配牌
    self_seat: int
    num_players: int


@dataclass
class RoundEnd:
    """點數以「這局開始時」對「結束後」計算，含這局付出的立直棒。"""

    reason: Literal["win", "exhaustive_draw", "abortive_draw"]  # 和了 / 荒牌流局 / 途中流局
    old_scores: list[int]
    scores: list[int]
    delta_scores: list[int]
    wins: list[WinResult] = field(default_factory=list)
    tenpai_seats: list[int] = field(default_factory=list)  # 荒牌流局時聽牌的座位
    nagashi_mangan: bool = False
    abortive_kind: AbortiveKind | None = None
    abortive_seat: int | None = None  # 九種九牌的宣告者


@dataclass
class GameOver:
    reason: Literal["finished", "terminated"]  # 打完 / 中途離桌


# ---- 牌桌動作 -------------------------------------------------------------


@dataclass
class Draw:
    """自己摸牌。"""

    tile: str


@dataclass
class HandUpdate:
    """自己的手牌或副露有變動。"""

    hand: list[str]  # 不含副露
    melds: list[str]  # 副露記法，例如 "555z"、暗槓 "4444M"


@dataclass
class DoraUpdate:
    dora_indicators: list[str]  # 目前全部的指示牌


@dataclass
class Discard:
    seat: int
    tile: str
    tsumogiri: bool
    riichi: bool  # 立直宣言牌


@dataclass
class Call:
    seat: int
    kind: CallKind
    tiles: list[str]  # 整組副露
    called_tile: str  # 其中從別家拿來的那張
    from_seat: int


@dataclass
class Kan:
    seat: int
    kind: KanKind
    tile: str


@dataclass
class Nuki:
    seat: int


@dataclass
class ExchangeTiles:
    """自己換牌（修羅之戰等模式）。"""

    out_tiles: list[str]
    in_tiles: list[str]


@dataclass
class Win:
    result: WinResult
    round_continues: bool  # 血戰到底中途和了


@dataclass
class Operation:
    """輪到自己做選擇（只有「正常打牌」可選時不會發出）。"""

    options: list[Option]


# ---- 分析結果 -------------------------------------------------------------
#
# 分析可能：成功（advice / danger）、失敗（error）、或因手牌含解析器不支援的牌而跳過
# （unsupported_tiles 非空）。三者恰好一個成立。內容格式見 qmax/advice/model.py。


@dataclass
class AnalysisError:
    message: str
    internal: bool  # 解析器內部錯誤（例如 Go panic），細節記在 analyze log


@dataclass
class HandAnalysis:
    """手牌 3n+2 張時是何切（advice.kind == "discard"）；3n+1 張時是目前狀況（"status"，一個候選）。"""

    # draw：摸牌後；deal：配牌；discard：自己打牌後；call：自己吃碰後；exchange：換牌後；seek：回放跳到這一步
    trigger: Literal["draw", "deal", "discard", "call", "exchange", "seek"]
    drawn_tile: str | None  # trigger 為 draw 時是摸到的牌
    hand: list[str]
    melds: list[str]
    is_naki: bool  # 副露手不能立直，不顯示立直打點
    advice: Advice | None
    error: AnalysisError | None = None
    unsupported_tiles: list[str] = field(default_factory=list)

    @property
    def is_discard_choice(self) -> bool:
        return len(self.hand) % 3 == 2


@dataclass
class ExchangeAnalysis:
    """開局換牌要換出哪幾張。"""

    count: int  # 要換出幾張
    hand: list[str]
    advice: Advice | None
    error: AnalysisError | None = None
    unsupported_tiles: list[str] = field(default_factory=list)


@dataclass
class CallAnalysis:
    """別家打出 called_tile，自己可以吃碰槓。advice 的每個候選是一種鳴法，followup 是叫完後的何切。"""

    called_tile: str
    advice: Advice | None
    error: AnalysisError | None = None
    unsupported_tiles: list[str] = field(default_factory=list)


@dataclass
class RiskAnalysis:
    """seat 這家對自己的危險度。"""

    seat: int
    danger: Danger | None
    error: AnalysisError | None = None
    unsupported_tiles: list[str] = field(default_factory=list)
