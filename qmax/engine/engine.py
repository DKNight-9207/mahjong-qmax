# 引擎：依序處理通用牌局動作 → 更新場況 → 需要時呼叫分析 → 通知前端。
from typing import Callable

from loguru import logger

from qmax.advice.base import Advisor, AdvisorError
from qmax.advice.model import Advice, Decision
from qmax.engine.state import RoundState
from qmax.frontend import events as ev
from qmax.frontend.base import Frontend
from qmax.game import actions as act
from qmax.game.tiles import unsupported_tiles

CALL_OPTIONS = {"chi", "pon", "minkan"}
DEFAULT_EXCHANGE_COUNT = 3

# on_decision(decision, advice, state)：每個決策點分析完後通知（決策紀錄用）；分析失敗時 advice 是 None
OnDecision = Callable[[Decision, Advice | None, RoundState], None]


class GameEngine:
    def __init__(
        self,
        advisor: Advisor | None,
        frontend: Frontend,
        upcoming: Callable[[], list[act.Action]] = list,
        on_decision: OnDecision | None = None,
    ):
        """advisor 為 None 時只追蹤場況、通知牌桌事件，不做分析。
        upcoming：已經收到、還沒處理的動作；分析跟不上時用來略過馬上會過時的危險度分析。"""
        self.upcoming = upcoming
        self.on_decision = on_decision
        self.state = RoundState()
        self.advisor = advisor
        self.frontend = frontend
        self.round_seen = False  # 中途才開始接收時，第一局開始前的動作沒有場況可對照，略過
        self._analysis_paused = False  # 解析器沒回應時暫停到下一局
        self.analysis_enabled = True  # 回放快轉時關掉，只更新場況
        self._advisor_dead = False
        self._handlers: dict[type, Callable] = {
            act.GameStarted: self._game_started,
            act.RoundStarted: self._round_started,
            act.RoundEnded: self._round_ended,
            act.GameEnded: self._game_ended,
            act.DoraIndicatorsChanged: self._dora_changed,
            act.RiichiAccepted: self._riichi_accepted,
            act.TileDrawn: self._tile_drawn,
            act.TileDiscarded: self._tile_discarded,
            act.Called: self._called,
            act.KanDeclared: self._kan_declared,
            act.NorthPulled: self._north_pulled,
            act.TilesExchanged: self._tiles_exchanged,
            act.Won: self._won,
        }

    def apply(self, action: act.Action):
        """例外不在這裡吞，由呼叫端決定怎麼處理。"""
        if not self.round_seen and not isinstance(action, (act.GameStarted, act.RoundStarted, act.GameEnded)):
            return
        if self.advisor is not None:
            self.advisor.observe(action)
        self._handlers[type(action)](action)

    # ---- 對局流程 ----------------------------------------------------------

    def _game_started(self, a: act.GameStarted):
        self.state.start_game(a.self_seat, a.num_players)
        self._notify(self.frontend.game_start, ev.GameStart(a.self_seat, a.num_players, list(a.player_names)))

    def _round_started(self, a: act.RoundStarted):
        self.round_seen = True
        self._analysis_paused = self._advisor_dead
        s = self.state
        s.start_round(a.round_wind, a.kyoku, a.dora_indicators, a.scores, a.hand)
        event = ev.RoundStart(
            round_wind=a.round_wind,
            kyoku=a.kyoku,
            honba=a.honba,
            kyotaku=a.kyotaku,
            dealer_seat=s.dealer_seat,
            self_wind=s.seat_wind(s.self_seat),
            dora_indicators=list(s.dora_indicators),
            scores=list(s.round_start_scores),
            hand=list(s.my_hand),
            self_seat=s.self_seat,
            num_players=s.num_players,
        )
        self._notify(self.frontend.round_start, event)
        self._hand_update()
        exchange = next((o for o in a.options if o.kind == "exchange"), None)
        if exchange:  # 開局要先換牌，這時談切哪張沒有意義
            preset = exchange.tile_sets[0] if exchange.tile_sets else []
            self._analyze_exchange(len(preset) or DEFAULT_EXCHANGE_COUNT, a.options)
        else:
            self._analyze_hand("deal", options=a.options)
        self._offer(a.options)

    def _round_ended(self, a: act.RoundEnded):
        s = self.state
        scores = list(a.scores) if a.scores else list(s.scores)
        old = s.round_start_scores if len(s.round_start_scores) == len(scores) else scores
        s.scores = scores
        event = ev.RoundEnd(
            reason=a.reason,
            old_scores=list(old),
            scores=scores,
            delta_scores=[new - before for new, before in zip(scores, old)],
            wins=list(a.wins),
            tenpai_seats=list(a.tenpai_seats),
            nagashi_mangan=a.nagashi_mangan,
            abortive_kind=a.abortive_kind,
            abortive_seat=a.abortive_seat,
        )
        self._notify(self.frontend.round_end, event)

    def _game_ended(self, a: act.GameEnded):
        self._notify(self.frontend.game_over, ev.GameOver(a.reason))

    # ---- 牌桌動作 ----------------------------------------------------------

    def _dora_changed(self, a: act.DoraIndicatorsChanged):
        if self.state.set_dora_indicators(a.dora_indicators):
            self._notify(self.frontend.dora_update, ev.DoraUpdate(list(self.state.dora_indicators)))

    def _riichi_accepted(self, a: act.RiichiAccepted):
        self.state.set_score(a.seat, a.score)

    def _tile_drawn(self, a: act.TileDrawn):
        s = self.state
        if a.seat == s.self_seat and a.tile:
            s.draw(a.tile)
            self._notify(self.frontend.draw, ev.Draw(a.tile))
            self._hand_update()
            self._analyze_hand("draw", drawn_tile=a.tile, options=a.options)
        self._offer(a.options)

    def _tile_discarded(self, a: act.TileDiscarded):
        s = self.state
        s.discard(a.seat, a.tile, a.tsumogiri, a.riichi)
        self._notify(self.frontend.discard, ev.Discard(a.seat, a.tile, a.tsumogiri, a.riichi))
        if a.seat == s.self_seat:
            self._hand_update()
            self._analyze_hand("discard")
            return
        if self._offer(a.options):
            self._analyze_calls(a.options, a.tile)
        if not self._risk_outdated(a.seat):
            self._analyze_risk(a.seat)

    def _called(self, a: act.Called):
        self.state.call(a.seat, a.tiles, a.called_tile)
        self._notify(self.frontend.call, ev.Call(a.seat, a.kind, list(a.tiles), a.called_tile, a.from_seat))
        if a.seat == self.state.self_seat:
            self._hand_update()
            if a.kind != "minkan":  # 大明槓之後會摸嶺上牌，到時再分析
                self._analyze_hand("call")

    def _kan_declared(self, a: act.KanDeclared):
        s = self.state
        if a.kind == "ankan":
            taken = s.ankan(a.seat, a.tile)
            if taken < 4:
                logger.warning(f"暗槓 {a.tile} 時手牌只找到 {taken} 張，牌數記錄可能已經跟丟了")
        else:
            s.kakan(a.seat, a.tile)
        self._notify(self.frontend.kan, ev.Kan(a.seat, a.kind, a.tile))
        if a.seat == s.self_seat:
            self._hand_update()

    def _north_pulled(self, a: act.NorthPulled):
        self.state.nuki(a.seat)
        self._notify(self.frontend.nuki, ev.Nuki(a.seat))
        if a.seat == self.state.self_seat:
            self._hand_update()

    def _tiles_exchanged(self, a: act.TilesExchanged):
        self.state.exchange_tiles(a.out_tiles, a.in_tiles)
        self._notify(self.frontend.exchange_tiles, ev.ExchangeTiles(list(a.out_tiles), list(a.in_tiles)))
        self._hand_update()
        self._analyze_hand("exchange", options=a.options)
        self._offer(a.options)

    def _won(self, a: act.Won):
        if a.scores:
            self.state.scores = list(a.scores)
        for result in a.wins:
            self._notify(self.frontend.win, ev.Win(result, a.round_continues))

    def _offer(self, options: list[act.Option]) -> bool:
        """通知前端輪到自己做選擇；只有正常打牌可選時不通知，回傳是否有通知。"""
        if all(o.kind == "discard" for o in options):
            return False
        self._notify(self.frontend.operation, ev.Operation(list(options)))
        return True

    def _hand_update(self):
        self._notify(self.frontend.hand_update, ev.HandUpdate(list(self.state.my_hand), list(self.state.self_melds)))

    def _notify(self, method: Callable[[object], None], event):
        """前端出錯只記錄，不影響後端繼續處理（例如後續的分析）。"""
        try:
            method(event)
        except Exception as e:
            logger.exception(f"前端處理 {method.__name__} 失敗：{type(e).__name__}: {e}")

    # ---- 分析 --------------------------------------------------------------

    def _can_analyze(self) -> bool:
        return self.advisor is not None and self.analysis_enabled and not self._analysis_paused

    def analyze_position(self, last: act.Action | None):
        """回放跳到某一步時（快轉過程不分析），對當下的場況做一次完整分析。last：最後處理的動作。"""
        s = self.state
        if not self.round_seen or isinstance(last, (act.RoundEnded, act.GameEnded)):
            return
        if isinstance(last, act.Won) and not last.round_continues:
            return
        exchange = isinstance(last, act.RoundStarted) and any(o.kind == "exchange" for o in last.options)
        if exchange:
            self._analyze_exchange(DEFAULT_EXCHANGE_COUNT, last.options)
        elif isinstance(last, act.TileDrawn) and last.seat == s.self_seat and last.tile:
            self._analyze_hand("draw", drawn_tile=last.tile, options=last.options)
        else:
            self._analyze_hand("seek")
        for seat in range(s.num_players):
            if seat != s.self_seat and s.discards[seat]:
                self._analyze_risk(seat)
        if isinstance(last, act.TileDiscarded) and last.seat != s.self_seat:
            self._analyze_calls(last.options, last.tile)

    def _ask(self, decision: Decision) -> tuple[Advice | None, ev.AnalysisError | None]:
        advice, error = self._call(lambda: self.advisor.advise(decision, self.state))
        if self.on_decision is not None:
            self.on_decision(decision, advice, self.state)
        return advice, error

    def _call(self, request: Callable[[], object]) -> tuple[object | None, ev.AnalysisError | None]:
        """回傳 (結果, 錯誤)。沒有回應時暫停分析到下一局。"""
        try:
            return request(), None
        except AdvisorError as e:
            if e.kind == "unreachable":
                self._pause_analysis(str(e))
            elif e.kind == "internal":
                logger.error(f"解析器內部錯誤（細節已存入 analyze log）：{e}")
            return None, ev.AnalysisError(str(e), e.kind == "internal")

    def _pause_analysis(self, reason: str):
        # 每次呼叫最多卡住解析器的逾時時間，也會拖慢代理轉發封包，所以不重試
        self._analysis_paused = True
        if self.advisor.is_alive():
            logger.error(f"解析器沒有回應，本局暫停分析：{reason}")
        else:
            self._advisor_dead = True
            logger.error(f"解析器已停止運作，之後不再分析：{reason}")

    def _analyze_hand(self, trigger: str, drawn_tile: str | None = None, options: list[act.Option] | None = None):
        s = self.state
        if not self._can_analyze() or len(s.my_hand) % 3 == 0:
            return
        event = ev.HandAnalysis(trigger, drawn_tile, list(s.my_hand), list(s.self_melds), s.is_naki, advice=None)
        event.unsupported_tiles = unsupported_tiles(s.my_hand)
        if not event.unsupported_tiles:
            kind = "discard" if event.is_discard_choice else "status"
            event.advice, event.error = self._ask(Decision(kind, list(options or [])))
        self._notify(self.frontend.hand_analysis, event)

    def _analyze_exchange(self, count: int, options: list[act.Option] | None = None):
        if not self._can_analyze():
            return
        s = self.state
        event = ev.ExchangeAnalysis(count, list(s.my_hand), advice=None)
        event.unsupported_tiles = unsupported_tiles(s.my_hand)
        if not event.unsupported_tiles:
            event.advice, event.error = self._ask(Decision("exchange", list(options or []), exchange_count=count))
        self._notify(self.frontend.exchange_analysis, event)

    def _analyze_calls(self, options: list[act.Option], called_tile: str):
        if not any(o.kind in CALL_OPTIONS and o.tile_sets for o in options) or not self._can_analyze():
            return
        event = ev.CallAnalysis(called_tile, advice=None)
        event.unsupported_tiles = unsupported_tiles(self.state.my_hand + [called_tile])
        if not event.unsupported_tiles:
            event.advice, event.error = self._ask(Decision("call", list(options), called_tile=called_tile))
        self._notify(self.frontend.call_analysis, event)

    def _risk_outdated(self, seat: int) -> bool:
        """後面已經排著這家的下一次打牌，或這局已經結束：現在算的危險度馬上就會被取代。"""
        for action in self.upcoming():
            if isinstance(action, act.TileDiscarded) and action.seat == seat:
                return True
            if isinstance(action, (act.RoundEnded, act.RoundStarted, act.GameEnded)):
                return True
        return False

    def _analyze_risk(self, seat: int):
        if not self._can_analyze():
            return
        event = ev.RiskAnalysis(seat, danger=None)
        event.unsupported_tiles = unsupported_tiles(self.state.my_hand)
        if not event.unsupported_tiles:
            event.danger, event.error = self._call(lambda: self.advisor.danger(seat, self.state))
            if event.danger is None and event.error is None:  # 這個解析器不算危險度
                return
        self._notify(self.frontend.risk_analysis, event)
