"""mahjong-helper 解析器：EndlessCheng/mahjong-helper 的 util/ 包成本地 HTTP 服務（analyzer-server），
原始碼與執行檔在 analyzer/mahjong_helper/。

    advisor.py  轉接：場況 → 請求，回應 → Advice
    server.py   analyzer-server 子行程
    api.py      analyzer-server 的 HTTP API
"""
from qmax.advice.mahjong_helper.advisor import MahjongHelperAdvisor

__all__ = ["MahjongHelperAdvisor"]
