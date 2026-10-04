# analyzer-server 子行程：找執行檔、啟動、等它回報監聽的 port、檢查版本。
# 執行檔與 Go 原始碼在 analyzer/mahjong_helper/（重新編譯：analyzer/mahjong_helper/build.sh）。
import platform
import subprocess
import time
from pathlib import Path

from loguru import logger

from qmax import ROOT
from qmax.advice import child_process
from qmax.advice.base import OnCall
from qmax.advice.mahjong_helper.api import AnalyzerApi, AnalyzerError

RESOURCE_DIR = ROOT / "analyzer" / "mahjong_helper"
BIN_DIR = RESOURCE_DIR / "bin"

# 必須與 build.sh 編進執行檔的版本一致；不一致只警告，通常代表忘了重編。
EXPECTED_VERSION = "v0.9.0"

_GOOS = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}
_GOARCH = {"x86_64": "amd64", "AMD64": "amd64", "arm64": "arm64", "aarch64": "arm64"}

# analyzer-server 啟動後在 stdout 印這行告知實際監聽的 port：
#   QMAX_ANALYZER_LISTENING port=12345 version=v0.9.0
READY_PREFIX = "QMAX_ANALYZER_LISTENING"


def start_server(on_call: OnCall | None = None, timeout: float = 5.0) -> AnalyzerApi:
    """啟動 analyzer-server，回傳連上它的 API。失敗時丟 RuntimeError。"""
    api = AnalyzerApi(AnalyzerServer.spawn(timeout), on_call)
    try:
        remote_version = api.server_version()
    except AnalyzerError as e:
        api.close()
        raise RuntimeError(f"analyzer-server 啟動了但連不上：{e}")
    if remote_version != EXPECTED_VERSION:
        logger.warning(f"analyzer-server 版本是 {remote_version}，預期 {EXPECTED_VERSION}，可能忘了重新編譯")
    return api


def binary_path() -> Path:
    goos = _GOOS.get(platform.system())
    goarch = _GOARCH.get(platform.machine())
    if goos is None or goarch is None:
        raise RuntimeError(f"沒有對應這個平台的 analyzer-server 執行檔：{platform.system()}/{platform.machine()}")

    name = f"analyzer-server-{goos}-{goarch}" + (".exe" if goos == "windows" else "")
    path = BIN_DIR / name
    if not path.exists():
        raise RuntimeError(f"找不到 analyzer-server 執行檔：{path}（先跑 {RESOURCE_DIR / 'build.sh'}）")
    return path


class AnalyzerServer:
    def __init__(self, process: subprocess.Popen, port: int, version: str):
        self.process = process
        self.port = port
        self.version = version

    @classmethod
    def spawn(cls, timeout: float = 5.0) -> "AnalyzerServer":
        process = child_process.spawn(
            [str(binary_path()), "-port", "0"],  # port 0：由系統挑空的 port
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            if line.startswith(READY_PREFIX):
                fields = dict(part.split("=", 1) for part in line.split()[1:])
                return cls(process, int(fields["port"]), fields["version"])

        process.kill()
        raise RuntimeError("analyzer-server 啟動逾時，沒有讀到監聽訊息")

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def close(self):
        child_process.stop(self.process)
