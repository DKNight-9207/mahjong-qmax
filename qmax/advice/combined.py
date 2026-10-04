# 主解析器加輔助解析器：主解析器決定排序，它沒有的分析或欄位由輔助解析器補。
#
# 例如 akochan（AI）只給每個選擇的期望值，沒有向聽、進張、和率、危險度，也不分析 13 張時的
# 目前狀況；輔助用 mahjong-helper，表格就能同時看到 AI 的排序與 mahjong-helper 的數值。
from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING

from qmax.advice.base import Advisor, AdvisorError, OnCall
from qmax.advice.model import Advice, Candidate, Danger, Decision, same_move
from qmax.game import actions as act

if TYPE_CHECKING:
    from qmax.engine.state import RoundState

# 從輔助解析器補過來的欄位（主解析器是 None 時才補）
_SUPPLEMENT = [f.name for f in fields(Candidate) if f.name not in ("move", "followup", "unavailable", "probability", "value")]


class CombinedAdvisor(Advisor):
    def __init__(self, primary: Advisor, support: Advisor):
        self.primary, self.support = primary, support
        self.name = primary.name

    @classmethod
    def open(cls, on_call: OnCall | None = None) -> CombinedAdvisor:
        raise NotImplementedError("用 open_advisor() 組合")

    @property
    def description(self) -> str:
        return f"{self.primary.description}，輔助：{self.support.description}"

    def close(self):
        self.primary.close()
        self.support.close()

    def is_alive(self) -> bool:
        return self.primary.is_alive() and self.support.is_alive()

    def observe(self, action: act.Action):
        self.primary.observe(action)
        self.support.observe(action)

    def advise(self, decision: Decision, state: RoundState) -> Advice:
        try:
            primary = self.primary.advise(decision, state)
        except AdvisorError as e:
            if e.kind == "unreachable":
                raise
            return self.support.advise(decision, state)  # 主解析器不支援這種決策或這場的規則
        try:
            support = self.support.advise(decision, state)
        except AdvisorError:
            return primary
        return merge(primary, support)

    def danger(self, seat: int, state: RoundState) -> Danger | None:
        return self.primary.danger(seat, state) or self.support.danger(seat, state)


def merge(primary: Advice, support: Advice) -> Advice:
    """依主解析器的候選順序，把輔助解析器同一個選擇的數值補進來。"""
    candidates = [_merge_candidate(c, support) for c in primary.candidates]
    notes = [n for n in primary.notes]
    if any(c.shanten is not None for c in candidates) or support.shanten is not None:
        notes.append("supplemented")
    notes += [n for n in support.notes if n not in notes and n != "pass_not_rated"]
    shanten = primary.shanten if primary.shanten is not None else support.shanten
    return Advice(primary.engine, primary.kind, candidates, shanten, notes)


def _merge_candidate(c: Candidate, support: Advice) -> Candidate:
    match = next((s for s in support.candidates if c.move and s.move and same_move(c.move, s.move)), None)
    if match is None:
        return c
    for name in _SUPPLEMENT:
        if getattr(c, name) is None:
            setattr(c, name, getattr(match, name))
    if c.followup is not None and match.followup is not None:
        c.followup = merge(c.followup, match.followup)
    elif c.followup is None and c.move.kind != "pass":
        c.followup = match.followup
    return c
