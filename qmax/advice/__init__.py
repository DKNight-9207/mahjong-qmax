"""解析器：引擎問決策點怎麼做，解析器回答。共同格式見 model.py，介面見 base.py。

程式其他地方只透過 open_advisor() 取得解析器，不直接碰解析器背後的東西（子行程、模型…）。
"""
from loguru import logger

from qmax.advice.akochan import AkochanAdvisor, AkochanLightAdvisor
from qmax.advice.base import Advisor, AdvisorError, OnCall
from qmax.advice.combined import CombinedAdvisor
from qmax.advice.mahjong_helper import MahjongHelperAdvisor
from qmax.advice.model import Advice, Candidate, Danger, Decision, Move, TileDanger, Wait

# 設定檔 analysis.advisor 可以選的解析器
ADVISORS: dict[str, type[Advisor]] = {
    MahjongHelperAdvisor.name: MahjongHelperAdvisor,
    AkochanAdvisor.name: AkochanAdvisor,
    AkochanLightAdvisor.name: AkochanLightAdvisor,
}
# 其他解析器沒有的分析（危險度、13 張的目前狀況…）與欄位（向聽、進張…）由它補
SUPPORT = MahjongHelperAdvisor.name


def open_advisor(name: str, on_call: OnCall | None = None, with_support: bool = True) -> Advisor:
    """啟動解析器；不是 mahjong-helper 時，預設搭配 mahjong-helper 補足（with_support），
    這時它啟動失敗（例如 akochan 還沒編譯）就只用 mahjong-helper。
    名稱不認得或（沒有可退回的）啟動失敗時丟 AdvisorError。"""
    if name not in ADVISORS:
        raise AdvisorError(f"沒有叫 {name!r} 的解析器，可用的有：{', '.join(ADVISORS)}")
    if name == SUPPORT or not with_support:
        return ADVISORS[name].open(on_call)
    support = ADVISORS[SUPPORT].open(on_call)
    try:
        advisor = ADVISORS[name].open(on_call)
    except AdvisorError as e:
        logger.warning(f"{e}；改用 {SUPPORT}")
        return support
    return CombinedAdvisor(advisor, support)


__all__ = [
    "ADVISORS", "Advice", "Advisor", "AdvisorError", "Candidate", "CombinedAdvisor", "Danger", "Decision", "Move",
    "OnCall", "TileDanger", "Wait", "open_advisor",
]
