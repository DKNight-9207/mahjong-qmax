# 雀魂訊息 -> 通用牌局動作。
from dataclasses import replace
from typing import Callable

from loguru import logger

from qmax.game import actions as act
from qmax.game.tiles import JOKER, WIND_TILES
from qmax.platforms.base import Message, Translator
from qmax.platforms.majsoul.messages import ACTION_PROTOTYPE, AUTH_GAME, GAME_END_RESULT, TERMINATE_GAME
from qmax.platforms.majsoul.yaku import yaku_name

MAJSOUL_JOKER = "bd"  # 萬象修羅的百搭

GAME_END_REASONS = {GAME_END_RESULT: "finished", TERMINATE_GAME: "terminated"}

# operation_list[].type，都已在實際錄製中出現過
OPTION_KINDS = {
    1: "discard", 2: "chi", 3: "pon", 4: "ankan", 5: "minkan", 6: "kakan",
    7: "riichi", 8: "tsumo", 9: "ron", 10: "kyuushu", 11: "nuki", 12: "exchange",
}
CALL_KINDS = {0: "chi", 1: "pon", 2: "minkan"}  # ActionChiPengGang.type
# game_config.mode.detail_rule 的欄位 → 特殊規則
RULE_VARIANTS = {
    "huansanzhang": "exchange", "xuezhandaodi": "xuezhan",
    "wanxiangxiuluo_mode": "jokers", "reveal_discard": "dark",
}
# game_config.mode.mode 的個位數：1 東風戰、2 半莊戰（十位數是人數，例如 11 是三人東）
GAME_LENGTHS = {1: "tonpuu", 2: "hanchan"}
# 認得但不影響牌局的動作
IGNORED_ACTIONS = {"ActionMJStart"}
KAN_KINDS = {2: "kakan", 3: "ankan"}  # ActionAnGangAddGang.type
# ActionLiuJu.type；1 已用實際錄製確認，其餘依雀魂的列舉順序
ABORTIVE_KINDS = {1: "kyuushu", 2: "suufon_renda", 3: "suukan_sanra", 4: "suucha_riichi", 5: "sancha_hou"}


class MajsoulTranslator(Translator):
    def __init__(self):
        self.account_id: int | None = None
        self.self_seat = 0
        self.in_game = False
        self.round_wins: list[act.WinResult] = []  # 血戰到底一局會有多筆
        self._unknown_actions: set[str] = set()  # 這場已經警告過的動作
        self._actions: dict[str, Callable[[dict], list[act.Action]]] = {
            "ActionNewRound": self._new_round,
            "ActionDealTile": self._deal_tile,
            "ActionDiscardTile": self._discard_tile,
            "ActionChiPengGang": self._chi_peng_gang,
            "ActionAnGangAddGang": self._an_gang_add_gang,
            "ActionBaBei": lambda d: [act.NorthPulled(d.get("seat", 0))],
            "ActionChangeTile": self._change_tile,
            "ActionHule": self._hule,
            "ActionHuleXueZhanMid": self._hule_xuezhan_mid,
            "ActionHuleXueZhanEnd": self._hule_xuezhan_end,
            "ActionNoTile": self._no_tile,
            "ActionLiuJu": self._liu_ju,
        }

    def translate(self, msg: Message) -> list[act.Action]:
        method = msg.get("method")
        data = msg.get("data") or {}
        if method == AUTH_GAME:
            return self._auth_game(msg.get("type"), data)
        if method in GAME_END_REASONS:
            return self._game_end(GAME_END_REASONS[method])
        if method != ACTION_PROTOTYPE:
            return []
        handler = self._actions.get(data.get("name"))
        if handler is None:
            self._warn_unknown(data.get("name"))
            return []
        action = data.get("data") or {}
        return self._side_effects(data["name"], action) + handler(action)

    def _warn_unknown(self, name: str | None):
        if name in IGNORED_ACTIONS or name in self._unknown_actions:
            return
        self._unknown_actions.add(name)
        logger.warning(f"不認得的對局動作 {name}，略過；這場的場況與分析可能不正確")

    def _side_effects(self, name: str, data: dict) -> list[act.Action]:
        """槓後的新寶牌、立直成立，都附在之後某個動作的欄位裡。"""
        found = []
        if name != "ActionNewRound" and data.get("doras"):
            found.append(act.DoraIndicatorsChanged(list(data["doras"])))
        liqi = data.get("liqi")  # {"seat", "score"（付出立直棒後）, "failed"}
        if liqi and not liqi.get("failed"):
            found.append(act.RiichiAccepted(liqi.get("seat", 0), liqi.get("score", 0)))
        return found

    # ---- 對局流程 ----------------------------------------------------------

    def _auth_game(self, msg_type: str | None, data: dict) -> list[act.Action]:
        # Req.account_id：自己的帳號；Res.seat_list[座位] = account_id；Res.players[]：{"account_id", "nickname"}
        self.in_game = True
        if msg_type == "Req":
            self.account_id = data.get("account_id")
            return []
        seat_list = data.get("seat_list") or []
        if self.account_id in seat_list:
            self.self_seat = seat_list.index(self.account_id)
        else:
            logger.warning(f"seat_list 裡找不到自己的帳號 {self.account_id}，當成座位 0 分析")
            self.self_seat = 0
        nicknames = {p.get("account_id"): p.get("nickname") for p in data.get("players") or []}
        names = [nicknames.get(account) or "電腦" for account in seat_list]
        mode = (data.get("game_config") or {}).get("mode") or {}
        rules = mode.get("detail_rule") or {}
        variants = [variant for key, variant in RULE_VARIANTS.items() if rules.get(key)]
        length = GAME_LENGTHS.get((mode.get("mode") or 0) % 10)
        self._unknown_actions = set()
        return [act.GameStarted(self.self_seat, len(seat_list), names, variants, length)]

    def _game_end(self, reason: str) -> list[act.Action]:
        # 離桌會連續收到好幾則結束訊息，只轉一次
        if not self.in_game:
            return []
        self.in_game = False
        return [act.GameEnded(reason)]

    def _new_round(self, data: dict) -> list[act.Action]:
        # tiles：自己的配牌；chang：場（0=東）；ju：局；ben：本場；liqibang：供託棒數；scores：依座位
        self.round_wins = []
        return [
            act.RoundStarted(
                round_wind=WIND_TILES[data.get("chang", 0) % len(WIND_TILES)],
                kyoku=data.get("ju", 0),
                honba=data.get("ben", 0),
                kyotaku=data.get("liqibang", 0),
                dora_indicators=list(data.get("doras") or []),
                scores=list(data.get("scores") or []),
                hand=_tiles(data.get("tiles")),
                options=self._options(data.get("operation")),
            )
        ]

    # ---- 牌桌動作 ----------------------------------------------------------

    def _deal_tile(self, data: dict) -> list[act.Action]:
        # tile 只有自己摸牌時才有
        tile = _tile(data["tile"]) if data.get("tile") else None
        return [act.TileDrawn(data.get("seat", 0), tile, self._options(data.get("operation")))]

    def _discard_tile(self, data: dict) -> list[act.Action]:
        # moqie：摸切；is_liqi：立直宣言牌；operation：自己能不能吃/碰/槓/和這張
        if data.get("tile") is None:
            return []
        return [
            act.TileDiscarded(
                seat=data.get("seat", 0),
                tile=_tile(data["tile"]),
                tsumogiri=bool(data.get("moqie")),
                riichi=bool(data.get("is_liqi")),
                options=self._options(data.get("operation")),
            )
        ]

    def _chi_peng_gang(self, data: dict) -> list[act.Action]:
        # tiles：整組副露；froms[i]：tiles[i] 來自哪個座位
        seat, tiles, froms = data.get("seat", 0), _tiles(data.get("tiles")), data.get("froms") or []
        kind = CALL_KINDS.get(data.get("type"))
        called = next((i for i, origin in enumerate(froms) if origin != seat), None)
        if kind is None or called is None or called >= len(tiles):
            logger.warning(f"看不懂的鳴牌資料，略過：{data}")
            return []
        return [act.Called(seat, kind, tiles, tiles[called], froms[called])]

    def _an_gang_add_gang(self, data: dict) -> list[act.Action]:
        # tiles 是單一張牌的字串
        kind = KAN_KINDS.get(data.get("type"))
        if kind is None or not data.get("tiles"):
            return []
        return [act.KanDeclared(data.get("seat", 0), kind, _tile(data["tiles"]))]

    def _change_tile(self, data: dict) -> list[act.Action]:
        options = self._options(data.get("operation"))
        return [act.TilesExchanged(_tiles(data.get("out_tiles")), _tiles(data.get("in_tiles")), options)]

    def _options(self, operation: dict | None) -> list[act.Option]:
        if not operation or operation.get("seat", 0) != self.self_seat:
            return []
        return [_option(item) for item in operation.get("operation_list") or []]

    # ---- 和了與流局 --------------------------------------------------------
    #
    # 和了的 data：
    #   hules[]：{"seat", "zimo", "hu_tile", "count"（番）, "fu", "dadian"（打點）, "yiman",
    #             "fans": [{"id", "val"}]}；血戰到底中途和了的牌譜版本沒有 dadian/fans
    #   delta_scores / scores：依座位，這次和了的增減與之後的點數（立直棒在立直時已付）
    #   hules_history：血戰到底整局結束時，這局全部的和了（欄位完整）

    def _hule(self, data: dict) -> list[act.Action]:
        won = self._won(data, round_continues=False)
        return [won, act.RoundEnded("win", won.scores, wins=list(self.round_wins))]

    def _hule_xuezhan_mid(self, data: dict) -> list[act.Action]:
        return [self._won(data, round_continues=True)]

    def _hule_xuezhan_end(self, data: dict) -> list[act.Action]:
        won = self._won(data, round_continues=False)
        self._fill_from_history(data.get("hules_history") or [])
        return [won, act.RoundEnded("win", won.scores, wins=list(self.round_wins))]

    def _no_tile(self, data: dict) -> list[act.Action]:
        # players[]：{"tingpai", "already_hule"（血戰到底已和了）}；liujumanguan：流局滿貫
        # scores[]：{"old_scores", "delta_scores"}，流局滿貫時可能有多筆，增減要加總
        settlements = data.get("scores") or []
        scores = None
        if settlements and settlements[0].get("old_scores"):
            scores = list(settlements[0]["old_scores"])
            for entry in settlements:
                for seat, delta in enumerate((entry.get("delta_scores") or [])[: len(scores)]):
                    scores[seat] += delta
        tenpai = [
            seat for seat, player in enumerate(data.get("players") or [])
            if player.get("tingpai") and not player.get("already_hule")
        ]
        self._fill_from_history(data.get("hules_history") or [])
        return [
            act.RoundEnded(
                "exhaustive_draw", scores, wins=list(self.round_wins),
                tenpai_seats=tenpai, nagashi_mangan=bool(data.get("liujumanguan")),
            )
        ]

    def _liu_ju(self, data: dict) -> list[act.Action]:
        # 途中流局，點數不變；seat：九種九牌的宣告者
        kind = ABORTIVE_KINDS.get(data.get("type"), "unknown")
        seat = data.get("seat", 0) if kind == "kyuushu" else None
        return [act.RoundEnded("abortive_draw", None, abortive_kind=kind, abortive_seat=seat)]

    def _won(self, data: dict, round_continues: bool) -> act.Won:
        # 一次和了裡扣點的只有放銃者；包牌等多家扣點時無法判斷
        losers = [seat for seat, delta in enumerate(data.get("delta_scores") or []) if delta < 0]
        wins = []
        for h in data.get("hules") or []:
            zimo = bool(h.get("zimo"))
            wins.append(
                act.WinResult(
                    seat=h.get("seat", 0),
                    zimo=zimo,
                    deal_in_seat=losers[0] if not zimo and len(losers) == 1 else None,
                    tile=_tile(h.get("hu_tile", "")),
                    han=h.get("count", 0),
                    fu=h.get("fu", 0),
                    points=h.get("dadian", 0),
                    yakuman=bool(h.get("yiman")),
                    yaku=_yaku(h),
                )
            )
        self.round_wins += [replace(w) for w in wins]  # 之後會補欄位，不改到已送出的
        return act.Won(wins, list(data.get("scores") or []), round_continues)

    def _fill_from_history(self, history: list[dict]):
        if len(history) != len(self.round_wins):
            return
        for win, h in zip(self.round_wins, history):
            win.yaku = win.yaku or _yaku(h)
            win.points = win.points or h.get("dadian", 0)


def _option(item: dict) -> act.Option:
    # {"type", "combination": ["2m|3m", ...], "change_tiles": 換牌時雀魂預選的三張}
    kind = OPTION_KINDS.get(item.get("type"), "unknown")
    if kind == "exchange":
        return act.Option(kind, [_tiles(item.get("change_tiles"))])
    return act.Option(kind, [_tiles(combo.split("|")) for combo in item.get("combination") or []])


def _tile(tile: str) -> str:
    return JOKER if tile == MAJSOUL_JOKER else tile


def _tiles(tiles: list[str] | None) -> list[str]:
    return [_tile(t) for t in tiles or []]


def _yaku(hule: dict) -> list[act.Yaku]:
    return [act.Yaku(yaku_name(f.get("id", 0)), f.get("val", 0)) for f in hule.get("fans") or []]
