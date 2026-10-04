# 從 Avenshy/MajsoulData 的最新 release 下載雀魂協定定義 liqi.desc。
import requests
from google.protobuf import descriptor_pb2, descriptor_pool
from loguru import logger

from qmax.platforms.majsoul.liqi import LIQI_DESC

RELEASE_API = "https://api.github.com/repos/Avenshy/MajsoulData/releases/latest"
RELEASES_PAGE = "https://github.com/Avenshy/MajsoulData/releases/latest"


def update(current_version: str, token: str) -> str:
    """有新版就下載並覆蓋，回傳更新後（或原本）的版本號。"""
    resp = requests.get(RELEASE_API, timeout=10, headers=_headers(token))
    if resp.headers.get("X-RateLimit-Remaining") == "0":
        logger.error(
            "GitHub API 額度用完，無法更新 liqi 協定。可以：\n"
            "1. 在 config/settings.yaml 的 majsoul.liqi.github_token 填入 GitHub Token 後重試\n"
            f"2. 到 {RELEASES_PAGE} 手動下載 liqi.desc 覆蓋 {LIQI_DESC}，"
            "並把 settings.yaml 的 majsoul.liqi.version 改成該版本號\n"
            "3. 換個網路／代理，或等一小時後再試"
        )
        return current_version

    if resp.status_code != 200:
        raise ConnectionError(f"GitHub API 回應 HTTP {resp.status_code}")
    release = resp.json()
    new_version = release["tag_name"]
    if new_version == current_version:
        logger.info(f"liqi 協定已是最新：{new_version}")
        return new_version

    asset = next((a for a in release.get("assets", []) if a["name"] == "liqi.desc"), None)
    if asset is None:
        raise FileNotFoundError(f"release {new_version} 沒有 liqi.desc")
    logger.info(f"下載 liqi.desc（{new_version}）……")
    desc = requests.get(asset["browser_download_url"], timeout=10, headers=_headers(token)).content
    _validate(desc)
    LIQI_DESC.write_bytes(desc)
    logger.success(f"liqi 協定更新成功：{new_version}")
    return new_version


def _validate(desc: bytes):
    """定義有問題時在這裡丟例外，不覆蓋原本可用的檔案。"""
    files = descriptor_pb2.FileDescriptorSet()
    files.ParseFromString(desc)
    pool = descriptor_pool.DescriptorPool()
    for file in files.file:
        pool.Add(file)


def _headers(token: str) -> dict:
    headers = {"X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
