# 雀魂的役 id -> 通用役名（qmax.game.yaku）。1~34 已用實際牌譜核對。
YAKU_BY_ID = {
    1: "menzen_tsumo", 2: "riichi", 3: "chankan", 4: "rinshan", 5: "haitei", 6: "houtei",
    7: "haku", 8: "hatsu", 9: "chun", 10: "seat_wind", 11: "round_wind",
    12: "tanyao", 13: "iipeikou", 14: "pinfu", 15: "chanta", 16: "ittsu", 17: "sanshoku",
    18: "double_riichi", 19: "sanshoku_doukou", 20: "sankantsu", 21: "toitoi", 22: "sanankou",
    23: "shousangen", 24: "honroutou", 25: "chiitoitsu", 26: "junchan", 27: "honitsu",
    28: "ryanpeikou", 29: "chinitsu", 30: "ippatsu",
    31: "dora", 32: "aka_dora", 33: "ura_dora", 34: "nuki_dora",
    35: "tenhou", 36: "chiihou", 37: "daisangen", 38: "suuankou", 39: "tsuuiisou", 40: "ryuuiisou",
    41: "chinroutou", 42: "kokushi", 43: "shousuushii", 44: "suukantsu", 45: "chuuren",
    46: "paarenchan", 47: "junsei_chuuren", 48: "suuankou_tanki", 49: "kokushi_13", 50: "daisuushii",
}


def yaku_name(fan_id: int) -> str:
    """沒對照到的役保留雀魂的 id，前端照原樣顯示。"""
    return YAKU_BY_ID.get(fan_id, f"majsoul_{fan_id}")
