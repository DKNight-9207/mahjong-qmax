# config/settings.yaml 的讀寫。不存在時用預設值建立；使用者只寫部分欄位時，其餘沿用預設；
# 預設值裡沒有的欄位會被忽略，下次存檔時移除。
from pathlib import Path
from textwrap import indent

from ruamel.yaml import YAML

from qmax import ROOT
from qmax.platforms import PLATFORMS

SETTINGS_PATH = ROOT / "config" / "settings.yaml"

DEFAULT_SETTINGS = """\
# 要分析的平台：majsoul（雀魂）
platform: majsoul
# 錄製輸出，底下依平台分目錄（相對路徑以專案根目錄為基準）
recorder:
  output_dir: './records'
# 分析
#   advisor：用哪個解析器：mahjong-helper、akochan、akochan-light（akochan 要先編譯，見 README；
#            向聽、危險度等由 mahjong-helper 補。akochan-light 約快 3 倍，首選九成多和 akochan 相同）
#   live：   即時對局要不要分析；關閉就不啟動解析器，只顯示牌桌
analysis:
  advisor: mahjong-helper
  live: true
# 日誌（狀態訊息 logs/app/ 一律記錄）
#   analyze_log：解析器每次對外呼叫的紀錄（logs/analyze/）
#   proxy_log：  收發的訊息名稱（logs/proxy/）
logging:
  output_dir: './logs'
  analyze_log:
    enabled: true
  proxy_log:
    enabled: true
"""

_yaml = YAML()


def load_settings() -> tuple[dict, bool]:
    """回傳 (設定, 是否為首次建立)。"""
    settings = _yaml.load(_defaults())
    if not SETTINGS_PATH.exists():
        return settings, True
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        _deep_merge(settings, _yaml.load(f) or {})
    return settings, False


def _defaults() -> str:
    platform_sections = [f"{name}:\n{indent(p.default_settings, '  ')}" for name, p in PLATFORMS.items()]
    return "\n".join([DEFAULT_SETTINGS, *platform_sections])


def save_settings(settings: dict):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        _yaml.dump(settings, f)


def resolve_path(path_str: str) -> Path:
    """設定裡的相對路徑以專案根目錄為基準。"""
    return ROOT / path_str


def _deep_merge(base: dict, override: dict):
    for key, value in override.items():
        if key not in base:
            continue
        if isinstance(value, dict) and isinstance(base[key], dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
