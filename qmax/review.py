# 決策紀錄：把錄製檔或牌譜跑一遍，每個決策點記下解析器的建議與實際打法（一行一筆 JSON），
# 最後算出解析器的首選和實際打法的一致率。
import dataclasses
import json
from pathlib import Path

from loguru import logger

from qmax.advice import AdvisorError, open_advisor
from qmax.advice.model import same_move
from qmax.advice.decision_log import DecisionLog, DecisionRecord, comparable
from qmax.engine import GameEngine
from qmax.frontend.base import NullFrontend
from qmax.pipeline import apply, translate
from qmax.platforms.base import Platform, ReplayError

KIND_ZH = {"discard": "何切", "call": "鳴牌", "exchange": "換牌"}


def review(
    platform: Platform, path: Path, out: Path, advisor_name: str, seat: int | None = None, compare: list[str] = (),
) -> list[str] | None:
    """寫出 out（jsonl），回傳摘要（幾行文字）；檔案讀不了或解析器啟動失敗時回傳 None。
    compare：另外要比較的解析器，每個決策點各問一次（不搭配輔助解析器，看它自己的排序）。"""
    extras = []
    try:
        messages = platform.load_replay(path, seat)
        advisor = open_advisor(advisor_name)
        extras = [open_advisor(name, with_support=False) for name in compare]
    except (ReplayError, AdvisorError) as e:
        logger.error(str(e))
        for extra in extras:
            extra.close()
        return None

    with advisor:
        log = DecisionLog(advisor, extras)
        engine = GameEngine(advisor, NullFrontend(), on_decision=log.on_decision)
        translator = platform.new_translator()
        for msg in messages:
            for action in translate(translator, msg):
                log.before(action)
                apply(engine, action)
        log.finish()
    for extra in extras:
        extra.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for record in log.records:
            f.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")
    return summarize(log.records, [advisor.name, *(extra.name for extra in extras)])


def summarize(records: list[DecisionRecord], names: list[str]) -> list[str]:
    counts = {kind: sum(r.decision.kind == kind for r in records) for kind in KIND_ZH}
    lines = ["決策點：" + "、".join(f"{KIND_ZH[k]} {n}" for k, n in counts.items() if n)]
    for name in names:
        lines.append(name)
        for kind, label in KIND_ZH.items():
            rated = [r for r in records if r.decision.kind == kind and comparable(r, name)]
            if not rated:
                continue
            top1 = sum(r.ranks[name] == 0 for r in rated)
            top3 = sum(r.ranks[name] is not None and r.ranks[name] < 3 for r in rated)
            if kind == "call" and all("pass_not_rated" in r.advice[name].notes for r in rated):
                label = "鳴法（只看實際有鳴的）"
            lines.append(f"  {label}　首選一致 {_percent(top1, len(rated))}（{top1}/{len(rated)}）"
                         f"　前三 {_percent(top3, len(rated))}")
    for other in names[1:]:
        lines += _agreement(records, names[0], other)
    calls = [r.actual.kind for r in records if r.decision.kind == "call" and r.actual is not None]
    if calls:
        passed, won = calls.count("pass"), calls.count("ron")
        lines.append(f"鳴牌機會 {len(calls)} 次：實際不鳴 {passed}、鳴 {len(calls) - passed - won}、榮和 {won}")
    return lines


def _agreement(records: list[DecisionRecord], a: str, b: str) -> list[str]:
    """兩個解析器的首選有多常一樣（不看實際打法）。"""
    lines = []
    for kind, label in KIND_ZH.items():
        pairs = [
            (r.advice[a].best.move, r.advice[b].best.move) for r in records
            if r.decision.kind == kind and r.advice.get(a) and r.advice.get(b)
            and r.advice[a].best and r.advice[b].best and r.advice[a].best.move and r.advice[b].best.move
        ]
        if kind == "call":  # 沒評估「不鳴」的那一方，只在雙方都建議鳴的時候比
            pairs = [(x, y) for x, y in pairs if x.kind != "pass"]
        if pairs:
            same = sum(same_move(x, y) for x, y in pairs)
            lines.append(f"{a} 與 {b} 的{label}首選相同 {_percent(same, len(pairs))}（{same}/{len(pairs)}）")
    return lines


def _percent(n: int, total: int) -> str:
    return f"{n / total * 100:.0f}%"
