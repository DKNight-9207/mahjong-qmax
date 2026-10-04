# 訊息 -> 平台轉譯器 -> 引擎。
#
#   AnalysisPipeline    同步處理，重播用
#   BackgroundPipeline  即時對局用：轉譯在代理的執行緒做（很快），引擎與分析在背景執行緒
#                       依序處理，代理不用等分析就能把封包轉給遊戲
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable

from loguru import logger

from qmax.advice import Advisor
from qmax.engine import GameEngine
from qmax.frontend.base import Frontend
from qmax.game.actions import Action
from qmax.platforms.base import Message, Platform, Translator


class AnalysisPipeline:
    def __init__(self, platform: Platform, advisor: Advisor | None, frontend: Frontend):
        self.translator = platform.new_translator()
        self.engine = GameEngine(advisor, frontend)

    def feed(self, msg: Message):
        for action in translate(self.translator, msg):
            apply(self.engine, action)


@dataclass
class _Job:
    actions: list[Action]
    before: Callable[[], None] | None = None
    after: Callable[[], None] | None = None


_STOP = _Job([])


class BackgroundPipeline:
    def __init__(self, platform: Platform, advisor: Advisor | None, frontend: Frontend):
        self._jobs: deque[_Job] = deque()
        self._has_jobs = threading.Condition()
        self.translator = platform.new_translator()
        self.engine = GameEngine(advisor, frontend, upcoming=self.upcoming)
        self._thread = threading.Thread(target=self._run, name="analysis", daemon=True)
        self._thread.start()

    def submit(self, msg: Message, before: Callable[[], None] | None = None, after: Callable[[], None] | None = None):
        """before/after 在背景執行緒、處理這則訊息的前後執行，跟分析保持同樣的順序。"""
        self._push(_Job(translate(self.translator, msg), before, after))

    def upcoming(self) -> list[Action]:
        """已經收到、還沒處理的動作。"""
        with self._has_jobs:
            return [action for job in self._jobs for action in job.actions]

    def close(self, timeout: float = 5.0):
        """處理完已收到的訊息後結束；超過 timeout 就不等了。"""
        self._push(_STOP)
        self._thread.join(timeout)

    def _push(self, job: _Job):
        with self._has_jobs:
            self._jobs.append(job)
            self._has_jobs.notify()

    def _run(self):
        while True:
            with self._has_jobs:
                while not self._jobs:
                    self._has_jobs.wait()
                job = self._jobs.popleft()
            if job is _STOP:
                return
            _run_safely(job.before)
            for action in job.actions:
                apply(self.engine, action)
            _run_safely(job.after)


def translate(translator: Translator, msg: Message) -> list[Action]:
    try:
        return translator.translate(msg)
    except Exception as e:
        logger.exception(f"轉譯訊息失敗（{msg.get('method')}）：{type(e).__name__}: {e}")
        return []


def apply(engine: GameEngine, action: Action):
    """單一動作出錯只記錄，不影響後續的動作。"""
    try:
        engine.apply(action)
    except Exception as e:
        logger.exception(f"處理 {type(action).__name__} 失敗：{type(e).__name__}: {e}")


def _run_safely(callback: Callable[[], None] | None):
    if callback is None:
        return
    try:
        callback()
    except Exception as e:
        logger.exception(f"{type(e).__name__}: {e}")
