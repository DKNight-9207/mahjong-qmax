# 中文顯示用的字串與格式，文字前端與儀表板共用。
from typing import Callable

from qmax.advice.model import Advice, Candidate, Move
from qmax.frontend import events as ev
from qmax.game.actions import Option, WinResult, Yaku
from qmax.game.tiles import JOKER
from qmax.game.yaku import DORA_YAKU

TILE_ZH = {f"{n}{suit}": f"{n}{name}" for n in range(1, 10) for suit, name in (("m", "萬"), ("p", "餅"), ("s", "索"))}
TILE_ZH.update({"0m": "赤5萬", "0p": "赤5餅", "0s": "赤5索"})
TILE_ZH.update(zip(["1z", "2z", "3z", "4z", "5z", "6z", "7z"], ["東", "南", "西", "北", "白", "發", "中"]))
TILE_ZH[JOKER] = "百搭"

# 解析器附帶的說明（Advice.notes）
NOTE_ZH = {
    "jokers": "含萬用牌：只計算向聽與進張",
    "unknown_incoming": "換入的牌當作沒用的牌評估",
    "pass_not_rated": "沒有評估不鳴",
    "supplemented": "向聽、進張等數值由輔助解析器補上",
}

WIND_ZH = {"1z": "東", "2z": "南", "3z": "西", "4z": "北"}

# index 是相對座位（0 = 自家，依回合順序）。三麻沒有對家。
SEAT_NAMES_4P = ["自家", "下家", "對家", "上家"]
SEAT_NAMES_3P = ["自家", "下家", "上家"]

SHANTEN_ZH = ["聽牌", "一向聽", "二向聽", "三向聽", "四向聽", "五向聽", "六向聽"]

OPTION_ZH = {
    "chi": "吃", "pon": "碰", "minkan": "大明槓", "ankan": "暗槓", "kakan": "加槓",
    "riichi": "立直", "tsumo": "自摸", "ron": "和", "kyuushu": "九種九牌", "nuki": "拔北", "exchange": "換牌",
    "pass": "不鳴",
    "unknown": "其他",
}

YAKU_ZH = {
    "menzen_tsumo": "門前清自摸和", "riichi": "立直", "double_riichi": "兩立直", "ippatsu": "一發",
    "chankan": "搶槓", "rinshan": "嶺上開花", "haitei": "海底摸月", "houtei": "河底撈魚",
    "haku": "役牌 白", "hatsu": "役牌 發", "chun": "役牌 中", "seat_wind": "自風", "round_wind": "場風", "yakuhai": "役牌",
    "tanyao": "斷幺九", "pinfu": "平和", "iipeikou": "一盃口", "ryanpeikou": "二盃口", "chiitoitsu": "七對子",
    "ittsu": "一氣通貫", "sanshoku": "三色同順", "sanshoku_doukou": "三色同刻", "chanta": "混全帶幺九",
    "junchan": "純全帶幺九", "honroutou": "混老頭", "toitoi": "對對和", "sanankou": "三暗刻",
    "sankantsu": "三槓子", "shousangen": "小三元", "honitsu": "混一色", "chinitsu": "清一色",
    "dora": "寶牌", "aka_dora": "赤寶牌", "ura_dora": "裏寶牌", "nuki_dora": "拔北寶牌",
    "tenhou": "天和", "chiihou": "地和", "daisangen": "大三元", "suuankou": "四暗刻",
    "suuankou_tanki": "四暗刻單騎", "tsuuiisou": "字一色", "ryuuiisou": "綠一色", "chinroutou": "清老頭",
    "kokushi": "國士無雙", "kokushi_13": "國士無雙十三面", "shousuushii": "小四喜", "daisuushii": "大四喜",
    "suukantsu": "四槓子", "chuuren": "九蓮寶燈", "junsei_chuuren": "純正九蓮寶燈", "paarenchan": "八連莊",
}

ABORTIVE_ZH = {
    "kyuushu": "九種九牌", "suufon_renda": "四風連打", "suukan_sanra": "四槓散了",
    "suucha_riichi": "四家立直", "sancha_hou": "三家和了", "unknown": "途中流局",
}

UNSUPPORTED_SKIP = {"hand": "何切分析", "call": "叫牌模擬分析", "risk": "危險度分析", "exchange": "換牌分析"}

SeatName = Callable[[int], str]


def tile_zh(tile: str) -> str:
    return TILE_ZH.get(tile, tile)


def tiles_zh(tiles: list[str]) -> str:
    return " ".join(tile_zh(t) for t in tiles)


def shanten_zh(shanten: int) -> str:
    return SHANTEN_ZH[shanten] if 0 <= shanten < len(SHANTEN_ZH) else f"{shanten}向聽"


def round_name(e: ev.RoundStart) -> str:
    return f"{WIND_ZH.get(e.round_wind, e.round_wind)}{e.kyoku + 1}局 {e.honba}本場"


def kyotaku_text(kyotaku: int) -> str:
    """沒有供託時是空字串；有的話後面帶全形空白，方便接在其他欄位前面。"""
    return f"供託：{kyotaku}　" if kyotaku else ""


def seat_name(seat: int, self_seat: int, num_players: int) -> str:
    names = SEAT_NAMES_3P if num_players == 3 else SEAT_NAMES_4P
    rel = (seat - self_seat) % num_players
    return names[rel] if rel < len(names) else f"座位{seat}"


def error_text(e: ev.AnalysisError) -> str:
    return f"{e.message}（解析器內部錯誤，細節已存入 analyze log）" if e.internal else e.message


def unsupported_line(tiles: list[str], what: str) -> str:
    return f"  (手牌含有分析器不支援的特殊牌碼 {'/'.join(tiles)}，跳過{UNSUPPORTED_SKIP[what]})"


def hand_text(hand: list[str], melds: list[str]) -> str:
    return " ".join(hand) + (f" # {' '.join(melds)}" if melds else "")


def options_text(options: list[Option]) -> str:
    """不含「正常打牌」。"""
    parts = []
    for o in options:
        if o.kind == "discard":
            continue
        label = OPTION_ZH.get(o.kind, o.kind)
        sets = "／".join(tiles_zh(tiles) for tiles in o.tile_sets if tiles)
        parts.append(f"{label}（{sets}）" if sets else label)
    return "、".join(parts)


# ---- 分析結果 --------------------------------------------------------------


def waits_text(c: Candidate) -> str:
    """wait_count 是剩餘枚數的總和，種數是 waits 的長度。"""
    return f"{len(c.waits or []):>2}種{c.wait_count or 0:>3}枚"


def notes_text(advice: Advice, skip: tuple[str, ...] = ()) -> str:
    return "；".join(NOTE_ZH[n] for n in advice.notes if n not in skip)


def move_text(m: Move | None) -> str:
    if m is None:
        return "(目前手牌)"
    if m.kind in ("discard", "riichi"):
        return f"{'立直' if m.kind == 'riichi' else ''}切{tile_zh(m.tiles[0])}"
    if m.kind == "exchange":
        return f"換出 {tiles_zh(m.tiles)}"
    label = OPTION_ZH.get(m.kind, m.kind)
    if m.meld:
        return f"{label}{m.meld}"
    return f"{label} {tiles_zh(m.tiles)}".strip()


def has_details(c: Candidate) -> bool:
    """有沒有和率、打點這些細節；萬用牌模式或只算進張的解析器沒有。"""
    return c.agari_rate is not None


def ai_text(c: Candidate) -> str:
    """AI 類解析器的評估（期望值、機率）與放銃率；沒有就是空字串。"""
    parts = []
    if c.value is not None:
        parts.append(f"期望{c.value:+.2f}")
    if c.probability is not None:
        parts.append(f"機率{c.probability * 100:.1f}%")
    if c.deal_in_rate is not None:
        parts.append(f"放銃{c.deal_in_rate:.1f}%")
    return "　" + "　".join(parts) if parts else ""


def candidate_line(c: Candidate, is_naki: bool) -> str:
    """何切的一個候選。

    0~2 向聽有役就列出，副露手沒有役標 ⚠無役（Go 只在聽牌時算役，1~2 向聽的無役
    只是提醒還沒鎖定役種）。副露手不能立直，不顯示立直打點。
    """
    label = move_text(c.move) + ai_text(c)
    shanten = c.shanten
    if shanten is None:  # 只有期望值的解析器
        return f"  {label}"
    if not has_details(c):
        waits = tiles_zh([w.tile for w in c.waits or []])
        return f"  {label}　{shanten_zh(shanten)}　進張{waits_text(c)}　{waits}"

    yaku = ""
    if 0 <= shanten <= 2:
        if c.yaku:
            yaku = f"　役：{yaku_names(c.yaku)}"
        elif is_naki:
            yaku = "　⚠無役"

    if shanten == 0:
        furiten = "　⚠可能振聽" if c.furiten else ""
        return f"  {label}　進張{waits_text(c)}　和率{c.agari_rate:5.1f}%　{point_text(c, is_naki)}{yaku}{furiten}"

    improve = f"　改良{c.improve_waits:.1f}({c.improve_count}種)" if c.improve_count else ""
    mixed = f"　綜合{c.mixed_score:.1f}" if c.mixed_score else ""
    return (
        f"  {label}　進張{waits_text(c)}{improve}　"
        f"=> {c.next_waits:.2f}{shanten_zh(shanten - 1)}{mixed}{yaku}"
    )


def exchange_line(c: Candidate) -> str:
    waits = tiles_zh([w.tile for w in c.waits or []])
    return f"  {move_text(c.move)}{ai_text(c)}　保留後{shanten_zh(c.shanten)}　進張{waits_text(c)}　{waits}"


def point_text(c: Candidate, is_naki: bool) -> str:
    return f"默聽{c.dama_point:.0f}" if is_naki else f"立直{c.riichi_point:.0f}／默聽{c.dama_point:.0f}"


def call_option_lines(e: ev.CallAnalysis) -> list[str]:
    if e.unsupported_tiles:
        return [unsupported_line(e.unsupported_tiles, "call")]
    if e.error:
        return [f"  鳴牌模擬分析失敗（{error_text(e.error)}）"]
    lines = []
    for c in e.advice.candidates:
        label = move_text(c.move) + ai_text(c)
        if c.move.kind == "pass":
            lines.append(f"  {label}")
        elif c.unavailable == "suit_mismatch":
            lines.append(f"  {label}：花色對不起來，略過模擬分析")
        elif c.unavailable == "tiles_not_in_hand":
            lines.append(f"  {label}：手牌裡找不到這幾張，略過模擬分析（記法可能對不上，例如赤5）")
        elif c.followup is None or not c.followup.candidates:
            lines.append(f"  {label}：沒有候選結果")
        else:
            lines += _call_result_lines(label, c.followup)
    return lines


def _call_result_lines(label: str, followup: Advice) -> list[str]:
    """依叫完後的向聽分組列出所有切法。"""
    lines = [f"  {label}："]
    if any(c.shanten is None for c in followup.candidates):  # 沒有向聽可以分組
        return lines + [f"    {candidate_line(c, True).strip()}" for c in followup.candidates]
    groups: dict[int, list[Candidate]] = {}
    for c in followup.candidates:
        groups.setdefault(c.shanten, []).append(c)
    for shanten in sorted(groups):
        lines.append(f"    鳴牌後{shanten_zh(shanten)}:")
        lines += [f"    {candidate_line(c, True).strip()}" for c in groups[shanten]]
    return lines


# ---- 結算 ------------------------------------------------------------------


def yaku_names(names: list[str]) -> str:
    return "、".join(YAKU_ZH.get(n, n) for n in names)


def yaku_text(yaku: list[Yaku], yakuman: bool) -> str:
    parts = []
    for y in yaku:
        name = YAKU_ZH.get(y.name, y.name)
        if y.name in DORA_YAKU:
            if y.han:
                parts.append(f"{name}{y.han}")
        elif yakuman:
            parts.append(name if y.han <= 1 else f"{name}×{y.han}")
        else:
            parts.append(f"{name}{y.han}")
    return "、".join(parts)


def win_line(w: WinResult, name: SeatName) -> str:
    if w.zimo:
        how = f"{name(w.seat)} 自摸"
    elif w.deal_in_seat is not None:
        how = f"{name(w.seat)} 榮和 {name(w.deal_in_seat)}"
    else:
        how = f"{name(w.seat)} 榮和"
    size = f"{w.han}倍役滿" if w.yakuman and w.han > 1 else "役滿" if w.yakuman else f"{w.han}番{w.fu}符"
    points = f" {w.points}點" if w.points else ""
    yaku = yaku_text(w.yaku, w.yakuman)
    return f"{how} {tile_zh(w.tile)}　{size}{points}" + (f"　{yaku}" if yaku else "")


def round_end_headline(e: ev.RoundEnd, name: SeatName) -> str:
    if e.reason == "abortive_draw":
        who = f"（{name(e.abortive_seat)}）" if e.abortive_seat is not None else ""
        return f"途中流局：{ABORTIVE_ZH[e.abortive_kind or 'unknown']}{who}"
    if e.reason == "exhaustive_draw":
        tenpai = "、".join(name(s) for s in e.tenpai_seats) or "全員未聽"
        return f"{'流局滿貫' if e.nagashi_mangan else '荒牌流局'}　聽牌：{tenpai}"
    return "和了"


def score_change_text(before: int, after: int) -> str:
    return f"{before} → {after}（{signed(after - before)}）"


def signed(delta: int) -> str:
    return f"{delta:+d}" if delta else "±0"
