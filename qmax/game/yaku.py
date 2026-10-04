# 通用役名。平台轉譯器把自己的役代碼換成這些名稱，前端再換成要顯示的文字。
YAKU = (
    # 一般役
    "menzen_tsumo", "riichi", "double_riichi", "ippatsu", "chankan", "rinshan", "haitei", "houtei",
    "haku", "hatsu", "chun", "seat_wind", "round_wind",
    "yakuhai",  # 役牌，沒說是哪一種（解析器估算可能的役時用）
    "tanyao", "pinfu", "iipeikou", "ryanpeikou", "chiitoitsu",
    "ittsu", "sanshoku", "sanshoku_doukou", "chanta", "junchan", "honroutou",
    "toitoi", "sanankou", "sankantsu", "shousangen", "honitsu", "chinitsu",
    # 寶牌（han 是張數）
    "dora", "aka_dora", "ura_dora", "nuki_dora",
    # 役滿（han 是役滿倍數）
    "tenhou", "chiihou", "daisangen", "suuankou", "suuankou_tanki", "tsuuiisou", "ryuuiisou",
    "chinroutou", "kokushi", "kokushi_13", "shousuushii", "daisuushii", "suukantsu",
    "chuuren", "junsei_chuuren", "paarenchan",
)

DORA_YAKU = {"dora", "aka_dora", "ura_dora", "nuki_dora"}
