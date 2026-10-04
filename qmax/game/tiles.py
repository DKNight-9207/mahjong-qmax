# 通用牌碼與副露記法。
#
# 牌碼（同 mahjong-helper）："1m".."9m" 萬、"1p".."9p" 餅、"1s".."9s" 索、
# "1z".."7z" 東南西北白發中；赤5 是 "0m"/"0p"/"0s"；萬用牌是 "jk"。
#
# 副露記法（mahjong-helper）：數字由小到大接花色，例如吃 "123s"、碰 "555z"、
# 大明槓/加槓 "4444m"；暗槓用大寫花色 "4444M"。

JOKER = "jk"  # 萬用牌：可以當任何一張牌，例如雀魂萬象修羅的百搭
WIND_TILES = ["1z", "2z", "3z", "4z"]  # 東南西北，index 對應場風/自風編號

STANDARD_TILES = (
    {f"{n}{suit}" for n in range(1, 10) for suit in "mps"}
    | {"0m", "0p", "0s"}
    | {f"{n}z" for n in range(1, 8)}
)


def unsupported_tiles(tiles: list[str]) -> list[str]:
    """分析器只認得標準牌碼與萬用牌，其他特殊牌送進去會解析失敗。"""
    return [t for t in tiles if t not in STANDARD_TILES and t != JOKER]


def normalize(tile: str) -> str:
    """赤5 換成一般 5，用來判斷兩張牌是不是同一種。"""
    return "5" + tile[1] if tile[0] == "0" else tile


def _rank(tile: str) -> int:
    return 5 if tile[0] == "0" else int(tile[0])  # 赤5 排在 4 和 6 之間


def meld_notation(tiles: list[str]) -> str | None:
    """吃/碰/明槓的一組牌轉成副露記法；花色不一致時回傳 None。"""
    if len({t[1] for t in tiles}) != 1:
        return None
    return "".join(t[0] for t in sorted(tiles, key=_rank)) + tiles[0][1]


def ankan_notation(tiles: list[str]) -> str:
    """暗槓的四張牌轉成副露記法（大寫花色），保留赤5，例如 ["0s","5s","5s","5s"] -> "0555S"。"""
    notation = meld_notation(tiles)
    return notation[:-1] + notation[-1].upper()


def is_ankan(meld: str) -> bool:
    return meld[-1].isupper()
