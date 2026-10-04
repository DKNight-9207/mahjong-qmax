# 捲動文字前端：每個事件印成一行行中文。用於重播，以及輸出不是終端機時。
import time
from typing import Callable

from qmax.frontend import events as ev
from qmax.frontend import zh
from qmax.frontend.base import Frontend

HAND_TRIGGER_ZH = {"deal": "配牌", "discard": "打牌後", "call": "鳴牌後", "exchange": "換牌後", "seek": "目前手牌"}


class TextFrontend(Frontend):
    def __init__(self, emit: Callable[[str], None] = print):
        self.emit = emit
        self.self_seat = 0
        self.num_players = 4

    def _seat(self, seat: int) -> str:
        return zh.seat_name(seat, self.self_seat, self.num_players)

    def _emit_all(self, lines: list[str]):
        for line in lines:
            self.emit(line)

    # ---- 日誌 ----

    def info(self, message: str):
        self._log("", message)

    def warning(self, message: str):
        self._log("⚠ ", message)

    def error(self, message: str):
        self._log("✖ ", message)

    def _log(self, mark: str, message: str):
        self.emit(f"[{time.strftime('%H:%M:%S')}] {mark}{message}")

    # ---- 對局流程 ----

    def game_start(self, e: ev.GameStart):
        self.self_seat, self.num_players = e.self_seat, e.num_players
        names = "、".join(f"{self._seat(seat)} {name}" for seat, name in enumerate(e.player_names))
        self.emit(f"[進入對局] 自己是座位 {e.self_seat}（{e.num_players} 人）　{names}")

    def round_start(self, e: ev.RoundStart):
        self.self_seat, self.num_players = e.self_seat, e.num_players
        self.emit(
            f"\n===== {zh.round_name(e)}　莊家：{self._seat(e.dealer_seat)}　{zh.kyotaku_text(e.kyotaku)}"
            f"寶牌指示牌：{zh.tiles_zh(e.dora_indicators)} ====="
        )
        self.emit(f"配牌：{' '.join(e.hand)}")

    def round_end(self, e: ev.RoundEnd):
        self.emit(f"[本局結束] {zh.round_end_headline(e, self._seat)}")
        for w in e.wins:
            self.emit(f"  {zh.win_line(w, self._seat)}")
        for seat in range(len(e.scores)):
            self.emit(f"  {self._seat(seat)} {zh.score_change_text(e.old_scores[seat], e.scores[seat])}")

    def game_over(self, e: ev.GameOver):
        self.emit(f"\n===== 對局結束（{'打完' if e.reason == 'finished' else '離桌'}） =====")

    # ---- 牌桌動作 ----

    def draw(self, e: ev.Draw):
        pass  # 顯示在 hand_analysis 的標題

    def hand_update(self, e: ev.HandUpdate):
        pass

    def dora_update(self, e: ev.DoraUpdate):
        self.emit(f"[新寶牌指示牌] 目前：{zh.tiles_zh(e.dora_indicators)}")

    def discard(self, e: ev.Discard):
        if e.seat == self.self_seat:
            self.emit(f"[自家切 {e.tile}]")
            return
        flags = "/".join(name for name, on in (("摸切", e.tsumogiri), ("立直", e.riichi)) if on)
        self.emit(f"[{self._seat(e.seat)}切 {e.tile}{f'（{flags}）' if flags else ''}]")

    def call(self, e: ev.Call):
        self.emit(f"[{self._seat(e.seat)}{zh.OPTION_ZH[e.kind]} {' '.join(e.tiles)}]")

    def kan(self, e: ev.Kan):
        self.emit(f"[{self._seat(e.seat)}{zh.OPTION_ZH[e.kind]} {e.tile}]")

    def nuki(self, e: ev.Nuki):
        self.emit(f"[{self._seat(e.seat)}拔北]")

    def exchange_tiles(self, e: ev.ExchangeTiles):
        self.emit(f"[換牌] 換出 {' '.join(e.out_tiles)}　換入 {' '.join(e.in_tiles)}")

    def win(self, e: ev.Win):
        self.emit(f"[{'中途和了' if e.round_continues else '和了'}] {zh.win_line(e.result, self._seat)}")

    def operation(self, e: ev.Operation):
        self.emit(f"  ⚡ 輪到你決定：{zh.options_text(e.options)}")

    # ---- 分析結果 ----

    def hand_analysis(self, e: ev.HandAnalysis):
        trigger = f"自家摸 {e.drawn_tile}" if e.trigger == "draw" else HAND_TRIGGER_ZH[e.trigger]
        title = f"\n[{trigger}] 手牌：{zh.hand_text(e.hand, e.melds)}"
        if e.unsupported_tiles:
            self._emit_all([title, zh.unsupported_line(e.unsupported_tiles, "hand")])
        elif e.error:
            self._emit_all([title, f"  (何切分析失敗：{zh.error_text(e.error)})"])
        else:
            notes = zh.notes_text(e.advice)
            self.emit(f"{title}　（{zh.shanten_zh(e.advice.shanten or 0)}{'，' + notes if notes else ''}）")
            self._emit_all([zh.candidate_line(c, e.is_naki) for c in e.advice.candidates])

    def exchange_analysis(self, e: ev.ExchangeAnalysis):
        title = f"\n[換牌：選 {e.count} 張換出] 手牌：{' '.join(e.hand)}"
        if e.unsupported_tiles:
            self._emit_all([title, zh.unsupported_line(e.unsupported_tiles, "exchange")])
        elif e.error:
            self._emit_all([title, f"  (換牌分析失敗：{zh.error_text(e.error)})"])
        else:
            self.emit(f"{title}　（{zh.shanten_zh(e.advice.shanten)}；{zh.notes_text(e.advice)}）")
            self._emit_all([zh.exchange_line(c) for c in e.advice.candidates])

    def call_analysis(self, e: ev.CallAnalysis):
        self._emit_all(zh.call_option_lines(e))

    def risk_analysis(self, e: ev.RiskAnalysis):
        if e.unsupported_tiles:
            self.emit(zh.unsupported_line(e.unsupported_tiles, "risk"))
            return
        if e.error:
            self.emit(f"  (危險度計算失敗：{zh.error_text(e.error)})")
            return
        d = e.danger
        self.emit(f"  {self._seat(e.seat)}　巡{d.turns}　聽牌率{d.tenpai_rate:.0f}%　估計打點{d.ron_point:.0f}")
        risky = sorted((t for t in d.tiles if t.risk > 0), key=lambda t: -t.risk)[:10]
        if risky:
            parts = [f"{zh.tile_zh(t.tile)}{'★' if t.in_hand else ''}({t.risk:.1f}/剩{t.left_count})" for t in risky]
            self.emit(f"    危險度排行：{', '.join(parts)}")  # ★：自己手上有
        if d.safe_tiles:
            self.emit(f"    安牌：{zh.tiles_zh(d.safe_tiles)}")
