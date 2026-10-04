# 麻將平台的介面。每個平台負責三件事：
#   1. 把 WebSocket 訊框解成訊息（Message：可轉 JSON 的 dict，至少有 "method" 訊息名稱，
#      原樣寫進錄製檔）
#   2. 判斷哪則訊息是對局開始／結束（決定錄製檔的範圍）
#   3. 把訊息轉成通用牌局動作（qmax.game.actions），交給引擎分析
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from qmax.game.actions import Action

Message = dict


class ReplayError(Exception):
    """重播檔讀不了，訊息直接顯示給使用者。"""


class Decoder(ABC):
    """一條 WebSocket 連線一個；依收發順序呼叫。"""

    @abstractmethod
    def decode(self, content: bytes, from_client: bool) -> Message:
        """解碼失敗時丟例外，訊息會寫進 proxy_log。"""


class Translator(ABC):
    """一場對局（或一次重播）一個，可以保留跨訊息的狀態。"""

    @abstractmethod
    def translate(self, msg: Message) -> list[Action]:
        """與牌局無關的訊息回傳空清單。"""


class Platform(ABC):
    name: str  # 設定檔的 platform 值，也是設定區塊與 records/ 底下目錄的名稱
    default_settings: str = ""  # 設定區塊的預設值（YAML）

    def __init__(self, settings: dict, save_settings: Callable[[], None], records_dir: Path):
        """settings：設定檔中這個平台的區塊，修改後呼叫 save_settings 存檔。
        records_dir：這個平台的錄製目錄，對局錄製檔放在底下的 live/。"""
        self.settings = settings
        self.save_settings = save_settings
        self.records_dir = records_dir

    def prepare(self):
        """代理啟動前呼叫一次，例如更新協定定義。"""

    @abstractmethod
    def accepts(self, url: str) -> bool:
        """這條 WebSocket 連線要不要處理。"""

    @abstractmethod
    def new_decoder(self) -> Decoder: ...

    @abstractmethod
    def new_translator(self) -> Translator: ...

    @abstractmethod
    def game_id_if_start(self, msg: Message) -> str | None:
        """msg 代表進入一場對局時，回傳這場的識別碼（用於錄製檔名）；否則 None。"""

    @abstractmethod
    def is_game_end(self, msg: Message) -> bool: ...

    def observe(self, msg: Message):
        """對局分析以外的用途，每則訊息都會呼叫，例如存下牌譜。"""

    def replay_files(self) -> list[Path]:
        """可以重播的檔案，新的在前。"""
        return []

    def replay_seat_selectable(self, path: Path) -> bool:
        """重播檔能不能換成別家的視角（牌譜記有四家手牌；對局錄製檔只有自己的）。"""
        return False

    @abstractmethod
    def load_replay(self, path: Path, seat: int | None) -> list[Message]:
        """讀取重播檔，回傳依序的訊息。seat：要用哪一家的視角（平台的牌譜需要時）。
        讀不了時丟 ReplayError。"""
