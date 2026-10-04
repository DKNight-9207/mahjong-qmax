"""除錯用：把牌譜攤平成逐動作的 .flat.jsonl。

    python -m qmax.platforms.majsoul.flatten_record records/majsoul/history/<uuid>.json ...
"""
import json
import sys
from collections import Counter
from pathlib import Path

from qmax.platforms.majsoul.game_record import flatten


def main():
    for arg in sys.argv[1:]:
        path = Path(arg)
        flat = flatten(json.loads(path.read_text(encoding="utf-8")))
        out = path.with_suffix(".flat.jsonl")
        with open(out, "w", encoding="utf-8") as f:
            for item in flat:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        print(f"{path.name} -> {out.name}（共 {len(flat)} 則動作）")
        for method, count in Counter(item["method"] for item in flat).most_common():
            print(f"  {count:>4}  {method}")


if __name__ == "__main__":
    main()
