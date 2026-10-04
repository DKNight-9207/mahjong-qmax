"""麻將平台：每個平台一個子套件，實作 base.Platform。"""
from qmax.platforms.base import Platform, ReplayError
from qmax.platforms.majsoul import MajsoulPlatform

PLATFORMS: dict[str, type[Platform]] = {p.name: p for p in (MajsoulPlatform,)}

__all__ = ["PLATFORMS", "Platform", "ReplayError"]
