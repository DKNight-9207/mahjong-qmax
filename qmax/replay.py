# 離線重播：讀取平台的錄製檔或牌譜，走與即時對局相同的分析流程。
from pathlib import Path

from loguru import logger

from qmax.advice import AdvisorError, open_advisor
from qmax.frontend.base import Frontend
from qmax.pipeline import AnalysisPipeline
from qmax.platforms.base import Platform, ReplayError


def replay(platform: Platform, path: Path, frontend: Frontend, advisor_name: str, seat: int | None = None):
    try:
        messages = platform.load_replay(path, seat)
        advisor = open_advisor(advisor_name)
    except (ReplayError, AdvisorError) as e:
        logger.error(str(e))
        return

    with advisor:
        logger.info(f"解析器：{advisor.description}　重播：{path}")
        pipeline = AnalysisPipeline(platform, advisor, frontend)
        for msg in messages:
            pipeline.feed(msg)
    if not pipeline.engine.round_seen:
        logger.warning(f"{path.name} 裡沒有任何一局的開局資訊，沒有東西可以重播")
