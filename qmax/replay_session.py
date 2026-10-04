# GUI 的回放：可以跳到任何一步、換視角。跳到哪一步，就從頭快轉（只更新場況、不分析）到那裡，
# 再對當下的場況做一次分析，所以不必一開檔就把整場算完。
import threading
from dataclasses import dataclass
from pathlib import Path

from qmax.advice import Advisor
from qmax.engine import GameEngine
from qmax.frontend import events as ev
from qmax.frontend.base import Frontend, NullFrontend
from qmax.game import actions as act
from qmax.pipeline import translate
from qmax.platforms.base import Platform, ReplayError

# 附帶在其他動作上的變化，不單獨算一步
SIDE_EFFECTS = (act.DoraIndicatorsChanged, act.RiichiAccepted)


class EventLog(NullFrontend):
    """依序記下收到的牌桌與分析事件 (方法名, 事件)。"""

    def __init__(self):
        self.events: list[tuple[str, object]] = []


for _name in Frontend.__abstractmethods__ - {"info", "warning", "error"}:
    setattr(EventLog, _name, lambda self, e, _name=_name: self.events.append((_name, e)))


@dataclass
class ReplayRound:
    step: int  # 這局開始的那一步
    start: ev.RoundStart
    end: ev.RoundEnd | None


class ReplaySession:
    def __init__(self, platform: Platform, advisor: Advisor | None, path: Path):
        self.platform, self.advisor, self.path = platform, advisor, path
        self.seat_selectable = platform.replay_seat_selectable(path)
        self._lock = threading.Lock()  # GUI 可能連續送出好幾個跳轉
        self._load(seat=None)

    def _load(self, seat: int | None):
        try:
            messages = self.platform.load_replay(self.path, seat)
        except ReplayError:
            if seat is not None or not self.seat_selectable:
                raise
            messages = self.platform.load_replay(self.path, 0)  # 認不出自己是哪一家：先看東家，畫面上可以換
        translator = self.platform.new_translator()
        self.actions = [a for msg in messages for a in translate(translator, msg)]
        # 第 k 步 = 處理完 actions[:ends[k]]
        self.ends = [i + 1 for i, a in enumerate(self.actions) if not isinstance(a, SIDE_EFFECTS)]
        start = next((a for a in self.actions if isinstance(a, act.GameStarted)), act.GameStarted(0, 4))
        self.self_seat, self.num_players, self.player_names = start.self_seat, start.num_players, start.player_names
        self._scan()

    def _scan(self):
        """快轉整場一次，找出每局的開始與結算，以及「大步」的位置（自己摸牌、每局開始）。"""
        log = EventLog()
        engine = GameEngine(None, log)
        self.rounds: list[ReplayRound] = []
        self.big_steps: list[int] = []
        done = 0
        for step, end in enumerate(self.ends):
            for action in self.actions[done:end]:
                engine.apply(action)
            done = end
            last = self.actions[end - 1]
            if isinstance(last, act.RoundStarted):
                self.big_steps.append(step)
            elif isinstance(last, act.TileDrawn) and last.seat == self.self_seat and last.tile:
                self.big_steps.append(step)
        current = None
        for step, (name, event) in self._events_by_step(log):
            if name == "round_start":
                current = ReplayRound(step, event, None)
                self.rounds.append(current)
            elif name == "round_end" and current is not None:
                current.end = event

    def _events_by_step(self, log: EventLog):
        """重跑一次，把每個事件對到產生它的那一步。"""
        log.events.clear()
        engine = GameEngine(None, log)
        done = 0
        for step, end in enumerate(self.ends):
            before = len(log.events)
            for action in self.actions[done:end]:
                engine.apply(action)
            done = end
            for item in log.events[before:]:
                yield step, item

    @property
    def steps(self) -> int:
        return len(self.ends)

    def switch_seat(self, seat: int):
        with self._lock:
            self._load(seat)

    def events_at(self, step: int) -> list[tuple[str, object]]:
        """重建第 step 步的畫面所需的事件：進入對局，加上這一局從開始到這一步，再加上這一刻的分析。"""
        step = max(0, min(step, self.steps - 1))
        with self._lock:
            log = EventLog()
            engine = GameEngine(self.advisor, log)
            engine.analysis_enabled = False
            for action in self.actions[: self.ends[step]]:
                engine.apply(action)
            engine.analysis_enabled = True
            engine.analyze_position(self.actions[self.ends[step] - 1])
        names = [name for name, _ in log.events]
        start = max((i for i, name in enumerate(names) if name == "round_start"), default=0)
        game_start = [item for item in log.events[:start] if item[0] == "game_start"][-1:]
        return game_start + log.events[start:]
