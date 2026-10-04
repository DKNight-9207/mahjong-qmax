# analyzer-server（mahjong-helper 包成的 Go HTTP 服務）的 HTTP API。
#
# 手牌記法沿用 mahjong-helper：手牌與副露用 "#" 分隔，副露之間空格分開，
# 暗槓用大寫花色。例如：
#   "123456789m 11z"        門清
#   "123456789m 11z # 555p" 碰 555p
#   "123m # 6666P 234p"     暗槓 6666p + 吃 234p
from __future__ import annotations

from typing import TYPE_CHECKING

import requests

from qmax.advice.base import OnCall  # endpoint 是 "analyze"、"risk" 或 "exchange"；失敗時 response 是 AnalyzerError.to_dict()

if TYPE_CHECKING:
    from qmax.advice.mahjong_helper.server import AnalyzerServer


class AnalyzerError(ValueError):
    """呼叫 analyzer-server 失敗。

    kind：rejected    Go 回報輸入有問題（例如手牌張數不對）
          panic       Go 內部 panic（通常代表 bug 或上游狀態追蹤錯誤）
          unreachable 連線失敗、逾時、回應格式不對（analyzer-server 可能已停止）
    stack：panic 時 Go 的呼叫堆疊
    """

    def __init__(self, message: str, kind: str = "rejected", stack: str = ""):
        super().__init__(message)
        self.kind = kind
        self.stack = stack

    @property
    def is_panic(self) -> bool:
        return self.kind == "panic"

    def to_dict(self) -> dict:
        """{"error": str, "panic": True, "stack": str}；panic/stack 只在 Go 內部 panic 時才有。"""
        d = {"error": str(self)}
        if self.is_panic:
            d["panic"] = True
            d["stack"] = self.stack
        return d


class AnalyzerApi:
    """與 analyzer-server 溝通的唯一管道；所有呼叫都經過 _post()，由它統一通知 on_call。"""

    def __init__(self, server: AnalyzerServer, on_call: OnCall | None = None):
        self.server = server
        self.version = server.version
        self.base_url = f"http://127.0.0.1:{server.port}"
        self.on_call = on_call

    def server_version(self) -> str:
        """GET /version，同時確認 HTTP 連得上。"""
        try:
            return requests.get(f"{self.base_url}/version", timeout=2).json()["version"]
        except (requests.RequestException, ValueError, KeyError) as e:
            raise AnalyzerError(f"analyzer-server 連線失敗（/version）：{e}", kind="unreachable") from e

    def analyze(
        self,
        hand: str,
        visible: str = "",
        jokers: int = 0,
        dora_indicators: str = "",
        is_sanma: bool = False,
        nuki_dora: int = 0,
        round_wind: str = "",
        self_wind: str = "",
        is_dealer: bool = False,
        is_riichi: bool = False,
        discards: str = "",
    ) -> dict:
        """牌效率（何切）分析。

        hand：自己的手牌+副露，不含萬用牌。14 張做何切、13 張看目前聽牌狀況。
        jokers：手牌中的萬用牌張數。大於 0 時只算向聽與進張，其餘數值為 0；
                何切候選裡切萬用牌的 discard 是 "jk"。
        visible：場上看得到、不在自己手牌/副露裡的所有牌，攤平成一串，
                 用來扣除剩餘枚數。
        dora_indicators / is_sanma / nuki_dora：寶牌指示牌、是否三麻、自己拔北張數（打點）
        round_wind / self_wind / is_dealer：場風、自風、是否莊家（役牌、打點）
        is_riichi：自己已立直
        discards：自己的捨牌，攤平（振聽判斷、和率）

        回傳：{"shanten": int, "is_naki": bool, "jokers": int, "candidates": [
                 {"discard": 切的牌（13 張時為空）, "shanten", "waits": [{"tile", "count"}],
                  "wait_count", "avg_agari_rate", "furiten_rate", "dama_point", "riichi_point",
                  "avg_improve_waits_count", "improve_count", "mixed_score",
                  "avg_next_shanten_waits_count", "yaku_names": [役名]}, ...]}
        """
        return self._post(
            "analyze",
            {
                "hand": hand,
                "visible": visible,
                "jokers": jokers,
                "dora_indicators": dora_indicators,
                "is_sanma": is_sanma,
                "nuki_dora": nuki_dora,
                "round_wind": round_wind,
                "self_wind": self_wind,
                "is_dealer": is_dealer,
                "is_riichi": is_riichi,
                "discards": discards,
            },
        )

    def risk(
        self,
        discards: list,
        hand: str = "",
        jokers: int = 0,
        visible: str = "",
        dora_indicators: str = "",
        round_wind: str = "",
        self_wind: str = "",
        melds: str = "",
        meld_discards_at: list[int] | None = None,
        nuki_dora: int = 0,
        extra_safe: str = "",
        is_riichi: bool = False,
        is_ippatsu: bool = False,
        is_dealer: bool = False,
        is_sanma: bool = False,
    ) -> dict:
        """單一對手的危險度分析。無狀態，每次都要傳完整快照。

        discards：這家的棄牌，依序，[{"tile": "1z", "tsumogiri": bool}]
        hand、jokers：我的手牌+副露與萬用牌張數（同 analyze）；visible：場上看得到、不是我手牌的牌（攤平）
        melds：這家的副露；meld_discards_at：這家每次副露後第一張棄牌在 discards 的位置（聽牌率）
        nuki_dora：這家拔北張數（副露時的打點估計）
        extra_safe：立直後過牌/同巡振聽產生的額外安牌
        round_wind / self_wind：場風、這家的自風（"1z"~"4z"）

        回傳：{"turns", "tenpai_rate", "ron_point",
               "risk": [{"tile", "risk", "left_count"}] × 34, "safe_tiles": [牌]}
        """
        return self._post(
            "risk",
            {
                "hand": hand,
                "jokers": jokers,
                "visible": visible,
                "dora_indicators": dora_indicators,
                "round_wind": round_wind,
                "self_wind": self_wind,
                "discards": discards,
                "melds": melds,
                "meld_discards_at": meld_discards_at or [],
                "nuki_dora": nuki_dora,
                "extra_safe": extra_safe,
                "is_riichi": is_riichi,
                "is_ippatsu": is_ippatsu,
                "is_dealer": is_dealer,
                "is_sanma": is_sanma,
            },
        )

    def exchange(self, hand: str, jokers: int = 0, visible: str = "", count: int = 3) -> dict:
        """開局換牌要換出哪 count 張。hand、jokers、visible 同 analyze（不可有副露）。

        換入的牌未知，當成沒用的牌：保留的牌照 13 張手牌計算向聽與進張。

        回傳：{"shanten": 目前向聽, "candidates": [
                 {"tiles": [換出的牌], "shanten", "waits": [{"tile", "count"}], "wait_count"}, ...]}
              依進張排序，只列保留後向聽最小的換法
        """
        return self._post("exchange", {"hand": hand, "jokers": jokers, "visible": visible, "count": count})

    def _post(self, endpoint: str, request: dict) -> dict:
        try:
            response = self._send(endpoint, request)
        except AnalyzerError as e:
            self._notify(endpoint, request, e.to_dict())
            raise
        self._notify(endpoint, request, response)
        return response

    def _send(self, endpoint: str, request: dict) -> dict:
        """所有失敗情況都轉成 AnalyzerError。
        Go 端錯誤格式：{"error": str, "panic": bool, "stack": str}"""
        try:
            resp = requests.post(f"{self.base_url}/{endpoint}", json=request, timeout=5)
        except requests.RequestException as e:
            raise AnalyzerError(f"analyzer-server 連線失敗（/{endpoint}）：{e}", kind="unreachable") from e
        try:
            data = resp.json()
        except ValueError:
            raise AnalyzerError(
                f"analyzer-server 回傳的不是 JSON（/{endpoint}，HTTP {resp.status_code}）：{resp.text[:200]}",
                kind="unreachable",
            )
        if data.get("error"):
            kind = "panic" if data.get("panic") else "rejected"
            raise AnalyzerError(data["error"], kind=kind, stack=data.get("stack", ""))
        return data

    def _notify(self, endpoint: str, request: dict, response: dict):
        if self.on_call:
            self.on_call(endpoint, request, response)

    def is_alive(self) -> bool:
        return self.server.is_alive()

    def close(self):
        self.server.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
