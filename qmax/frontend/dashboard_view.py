# 儀表板的畫面狀態與繪製。TableView 由事件更新，render() 把它畫成 rich 版面：
#
#   場況（局數、寶牌、點數、最新動作）
#   各家（聽牌率、安牌、危牌）
#   手牌與分析（向聽、何切候選，開局換牌建議，或輪到自己鳴牌時的模擬結果）；一局結束後改顯示結算
#   警告（有才顯示）
from dataclasses import dataclass, field

from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from qmax.advice.model import Candidate, Danger
from qmax.frontend import events as ev
from qmax.frontend import zh

MAX_CANDIDATES = 8
MAX_DANGER_TILES = 8
MAX_ALERTS = 5


@dataclass
class Alert:
    time: str
    level: str  # "warning" | "error"
    message: str


@dataclass
class TableView:
    self_seat: int = 0
    num_players: int = 4
    round: ev.RoundStart | None = None
    scores: list[int] = field(default_factory=list)
    dora_indicators: list[str] = field(default_factory=list)
    last_action: str = ""
    hand: list[str] = field(default_factory=list)
    melds: list[str] = field(default_factory=list)
    drawn_tile: str | None = None
    operation: ev.Operation | None = None
    hand_analysis: ev.HandAnalysis | None = None
    exchange_analysis: ev.ExchangeAnalysis | None = None  # 開局換牌完成前顯示
    call_analysis: ev.CallAnalysis | None = None
    risks: dict[int, ev.RiskAnalysis] = field(default_factory=dict)
    riichi: set[int] = field(default_factory=set)
    alerts: list[Alert] = field(default_factory=list)
    round_result: ev.RoundEnd | None = None  # 一局結束到下一局開始之間顯示結算

    def seat(self, seat: int) -> str:
        return zh.seat_name(seat, self.self_seat, self.num_players)

    def start_round(self, e: ev.RoundStart):
        self.self_seat, self.num_players = e.self_seat, e.num_players
        self.round = e
        self.scores = list(e.scores)
        self.dora_indicators = list(e.dora_indicators)
        self.last_action = ""
        self.drawn_tile = None
        self.operation = self.hand_analysis = self.call_analysis = self.exchange_analysis = None
        self.risks.clear()
        self.riichi.clear()
        self.round_result = None

    def settle(self, e: ev.RoundEnd):
        self.scores = list(e.scores)
        self.round_result = e
        self.operation = self.call_analysis = None

    def display_order(self) -> list[int]:
        """跟遊戲畫面一樣由左到右：上家、對家、下家，自家放最後。"""
        rels = list(range(self.num_players - 1, 0, -1)) + [0]
        return [(self.self_seat + rel) % self.num_players for rel in rels]

    def round_name(self) -> str:
        return zh.round_name(self.round) if self.round else ""

    def score_text(self) -> str:
        return "　".join(f"{self.seat(s)} {self.scores[s]}" for s in self.display_order() if s < len(self.scores))

    def round_summary(self, e: ev.RoundEnd) -> str:
        """一局結果的一行摘要（對局結束後印在 log 畫面）。"""
        parts = [self.round_name(), zh.round_end_headline(e, self.seat)]
        parts += [zh.win_line(w, self.seat) for w in e.wins]
        changes = [
            f"{self.seat(s)}{zh.signed(e.delta_scores[s])}" for s in self.display_order()
            if s < len(e.delta_scores) and e.delta_scores[s]
        ]
        parts.append("點數 " + " ".join(changes) if changes else "點數不變")
        return "｜".join(p for p in parts if p)


def render(view: TableView) -> RenderableType:
    bottom = _result_panel(view, view.round_result) if view.round_result else _hand_panel(view)
    parts = [_round_panel(view), _opponents(view), bottom]
    if view.alerts:
        parts.append(_alerts_panel(view))
    return Group(*parts)


# ---- 場況 ------------------------------------------------------------------

def _round_panel(view: TableView) -> Panel:
    r = view.round
    if r is None:
        return Panel(Text("等待開局…", style="dim"), title="場況")
    head = Text.assemble(
        (view.round_name(), "bold"),
        f"　莊家：{view.seat(r.dealer_seat)}　場風：{zh.tile_zh(r.round_wind)}　自風：{zh.tile_zh(r.self_wind)}"
        f"　{zh.kyotaku_text(r.kyotaku)}寶牌指示牌：",
        (zh.tiles_zh(view.dora_indicators), "bold magenta"),
    )
    lines = [head, Text(view.score_text(), style="cyan")]
    if view.last_action:
        lines.append(Text(f"最新：{view.last_action}", style="dim"))
    return Panel(Group(*lines), title="場況")


# ---- 各家 ------------------------------------------------------------------

def _opponents(view: TableView) -> Table:
    grid = Table.grid(expand=True, padding=(0, 1))
    seats = view.display_order()[:-1]  # 跟遊戲畫面一樣：左上家、中對家、右下家
    for _ in seats:
        grid.add_column(ratio=1)
    grid.add_row(*(_opponent_panel(view, s) for s in seats))
    return grid


def _opponent_panel(view: TableView, seat: int) -> Panel:
    title = Text(view.seat(seat), style="bold")
    if seat in view.riichi:
        title.append(" 立直", style="bold red")
    r = view.risks.get(seat)
    if r is None:
        body = Text("尚無資料", style="dim")
    elif r.unsupported_tiles:
        body = Text(f"手牌含特殊牌碼 {'/'.join(r.unsupported_tiles)}，不分析", style="dim")
    elif r.error:
        body = Text(f"分析失敗：{zh.error_text(r.error)}", style="red")
    else:
        body = _risk_body(r.danger)
    return Panel(body, title=title, title_align="left")


def _risk_body(d: Danger) -> Group:
    stats = Text(f"巡{d.turns}　聽牌率 {d.tenpai_rate:.0f}%　打點 {d.ron_point:.0f}")
    safe = Text("安牌 ", style="bold green")
    safe.append(zh.tiles_zh(d.safe_tiles) or "—")

    risky = sorted((t for t in d.tiles if t.risk > 0), key=lambda t: -t.risk)[:MAX_DANGER_TILES]
    if not risky:
        return Group(stats, safe, Text.assemble(("危牌 ", "bold red"), "—"))
    cells = []
    for t in risky:
        style = "red" if t.risk >= 10 else "yellow" if t.risk >= 5 else ""
        mark = "★" if t.in_hand else ""  # 自己手上有
        cells.append(Text(f"{zh.tile_zh(t.tile)}{mark} {t.risk:.1f}", style=style, no_wrap=True))
    # Columns 依寬度決定一列放幾格，每格（牌+數字）不會被拆開
    return Group(stats, safe, Text("危牌", style="bold red"), Columns(cells, padding=(0, 2)))


# ---- 手牌與分析 -------------------------------------------------------------

_SUIT_ORDER = {"m": 0, "p": 1, "s": 2, "z": 3}


def _tile_sort_key(tile: str):
    rank = 5.5 if tile[0] == "0" else int(tile[0]) if tile[0].isdigit() else 99  # 赤5 排在 5 後面
    return (_SUIT_ORDER.get(tile[-1], 9), rank, tile)


def _hand_panel(view: TableView) -> Panel:
    hand = list(view.hand)
    if view.drawn_tile and view.drawn_tile in hand:
        hand.remove(view.drawn_tile)
    line = Text(zh.tiles_zh(sorted(hand, key=_tile_sort_key)), style="bold")
    if view.drawn_tile:
        line.append("　摸 ", style="dim")
        line.append(zh.tile_zh(view.drawn_tile), style="bold reverse")
    lines: list[RenderableType] = [line]
    if view.melds:
        lines.append(Text(f"副露 {'  '.join(view.melds)}", style="cyan"))
    if view.operation:
        lines.append(Text(f"⚡ 輪到你決定：{zh.options_text(view.operation.options)}", style="bold yellow"))

    if view.exchange_analysis:
        return _exchange_panel(view.exchange_analysis, lines)

    title = "手牌"
    a = view.hand_analysis
    if a and a.advice:
        notes = zh.notes_text(a.advice)
        title = f"手牌（{zh.shanten_zh(a.advice.shanten or 0)}{'，' + notes if notes else ''}）"
    if view.call_analysis:
        lines.append(Text("\n".join(line.strip() for line in zh.call_option_lines(view.call_analysis))))
    elif a:
        if a.unsupported_tiles:
            lines.append(Text(zh.unsupported_line(a.unsupported_tiles, "hand").strip(), style="dim"))
        elif a.error:
            lines.append(Text(f"分析失敗：{zh.error_text(a.error)}", style="red"))
        elif a.is_discard_choice:
            lines.append(_candidates_table(a))
        elif a.advice.best:
            lines.append(_current_hand_line(a.advice.best, a.is_naki))
    return Panel(Group(*lines), title=title, title_align="left")


def _exchange_panel(e: ev.ExchangeAnalysis, lines: list[RenderableType]) -> Panel:
    title = f"手牌（換牌：選 {e.count} 張換出）"
    if e.unsupported_tiles:
        lines.append(Text(zh.unsupported_line(e.unsupported_tiles, "exchange").strip(), style="dim"))
    elif e.error:
        lines.append(Text(f"換牌分析失敗：{zh.error_text(e.error)}", style="red"))
    else:
        title = f"手牌（{zh.shanten_zh(e.advice.shanten)}；換牌：選 {e.count} 張換出）"
        table = Table(box=None, padding=(0, 1), header_style="dim")
        for name, justify in (("換出", "left"), ("保留後", "left"), ("進張", "right"), ("進張牌", "left")):
            table.add_column(name, justify=justify, no_wrap=name != "進張牌")
        for n, c in enumerate(e.advice.candidates[:MAX_CANDIDATES]):
            waits = zh.tiles_zh([w.tile for w in c.waits or []])
            table.add_row(zh.tiles_zh(c.move.tiles), zh.shanten_zh(c.shanten), zh.waits_text(c), waits,
                          style="bold" if n == 0 else None)
        lines += [table, Text(zh.notes_text(e.advice), style="dim")]
    return Panel(Group(*lines), title=title, title_align="left")


def _current_hand_line(c: Candidate, is_naki: bool) -> Text:
    """13 張時的目前狀況：聽牌顯示聽哪些牌與打點，否則顯示進張。"""
    waits = " ".join(f"{zh.tile_zh(w.tile)}({w.count})" for w in c.waits or [])
    if c.shanten == 0 and not zh.has_details(c):
        return Text.assemble(("聽 ", "bold green"), waits, f"　共{c.wait_count}枚")
    if c.shanten == 0:
        yaku = zh.yaku_names(c.yaku or []) or ("⚠無役" if is_naki else "")
        line = Text.assemble(
            ("聽 ", "bold green"), waits,
            f"　共{c.wait_count}枚　和率{c.agari_rate:.1f}%　{zh.point_text(c, is_naki)}",
        )
        if yaku:
            line.append(f"　{yaku}")
        if c.furiten:
            line.append("　⚠可能振聽", style="yellow")
        return line
    return Text.assemble(("進張 ", "bold"), f"{len(c.waits or [])}種{c.wait_count}枚　", (waits, "dim"))


CANDIDATE_COLUMNS = [
    ("打出", "left"), ("期望", "right"), ("機率", "right"), ("放銃", "right"),
    ("向聽", "left"), ("進張", "right"), ("改良", "right"), ("前進後進張", "right"),
    ("和率", "right"), ("打點", "right"), ("綜合", "right"), ("役", "left"), ("進張牌", "left"),
]


def _candidates_table(a: ev.HandAnalysis) -> Table:
    rows = [_candidate_row(c, a.is_naki) for c in a.advice.candidates[:MAX_CANDIDATES]]
    # 只留有內容的欄：一向聽以上沒有和率/打點，聽牌時沒有改良/前進後進張，mahjong-helper 沒有期望值
    keep = [i for i in range(len(CANDIDATE_COLUMNS)) if any(row[i] for row in rows)]
    table = Table(box=None, padding=(0, 1), header_style="dim")
    for i in keep:
        name, justify = CANDIDATE_COLUMNS[i]
        table.add_column(name, justify=justify, no_wrap=name != "役")
    for n, row in enumerate(rows):
        table.add_row(*(row[i] for i in keep), style="bold" if n == 0 else None)
    return table


def _candidate_row(c: Candidate, is_naki: bool) -> list[str]:
    discard = zh.move_text(c.move).removeprefix("切") if c.move else "—"
    head = [
        discard,
        f"{c.value:+.2f}" if c.value is not None else "",
        f"{c.probability * 100:.1f}%" if c.probability is not None else "",
        f"{c.deal_in_rate:.1f}%" if c.deal_in_rate is not None else "",
    ]
    if c.shanten is None:  # 只有期望值的解析器
        return head + [""] * 9
    if not zh.has_details(c):  # 只有向聽與進張
        waits = zh.tiles_zh([w.tile for w in c.waits or []])
        return head + [zh.shanten_zh(c.shanten), zh.waits_text(c), "", "", "", "", "", "", waits]
    yaku = zh.yaku_names(c.yaku or [])
    if not yaku and is_naki and 0 <= c.shanten <= 2:
        yaku = "⚠無役"
    if c.shanten == 0:
        if c.furiten:
            yaku = f"{yaku}　⚠可能振聽".strip()
        return head + ["", zh.waits_text(c), "", "", f"{c.agari_rate:.1f}%", zh.point_text(c, is_naki), "", yaku, ""]
    improve = f"{c.improve_waits:.1f}({c.improve_count})" if c.improve_count else ""
    step = f"{c.next_waits:.2f}{zh.shanten_zh(c.shanten - 1)}"
    mixed = f"{c.mixed_score:.1f}" if c.mixed_score else ""
    return head + ["", zh.waits_text(c), improve, step, "", "", mixed, yaku, ""]


# ---- 結算 ------------------------------------------------------------------

def _result_panel(view: TableView, e: ev.RoundEnd) -> Panel:
    lines: list[RenderableType] = [Text(zh.round_end_headline(e, view.seat), style="bold")]
    lines += [Text(zh.win_line(w, view.seat)) for w in e.wins]
    table = Table(box=None, padding=(0, 2), show_header=False)
    table.add_column()
    table.add_column(justify="right")
    table.add_column(justify="right")
    for seat in view.display_order():
        if seat >= len(e.scores):
            continue
        delta = e.delta_scores[seat]
        style = "green" if delta > 0 else "red" if delta < 0 else "dim"
        table.add_row(view.seat(seat), f"{e.old_scores[seat]} → {e.scores[seat]}", Text(zh.signed(delta), style=style))
    lines.append(table)
    return Panel(Group(*lines), title=f"{view.round_name()} 結算", title_align="left", border_style="cyan")


# ---- 警告 ------------------------------------------------------------------

def _alerts_panel(view: TableView) -> Panel:
    lines = [
        Text.assemble((f"{a.time} ", "dim"), (a.message, "red" if a.level == "error" else "yellow"))
        for a in view.alerts[-MAX_ALERTS:]
    ]
    return Panel(Group(*lines), title="警告", title_align="left", border_style="red")
