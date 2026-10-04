"""qmax-recorder 進入點。

    python main.py                       啟動代理：錄製對局並即時分析
    python main.py --port 23410          指定代理 port
    python main.py --text                不用儀表板，以捲動文字顯示
    python main.py gui                   開啟視窗介面，在視窗裡開始／停止監聽
    python main.py gui --debug           同上，並開啟網頁的開發者工具（F12）
    python main.py replay FILE [--seat N] [--out LOG]
                                         重播錄製檔或牌譜
    python main.py review FILE [--seat N] [--out JSONL]
                                         決策紀錄：解析器建議與實際打法、一致率
    python main.py mjai FILE [--seat N] [--out MJSON]
                                         匯出 mjai 事件檔（四人一般規則）
"""
import argparse
import sys
from pathlib import Path



def _force_utf8_stdout():
    # 輸出被導向管線/IDE 時，Windows 會用系統編碼（cp950），印不出簡體牌名
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _make_frontend(force_text: bool):
    from qmax.frontend.dashboard import DashboardFrontend
    from qmax.frontend.text import TextFrontend

    # 儀表板需要真正的終端機
    if force_text or not sys.stdout.isatty():
        return TextFrontend()
    return DashboardFrontend()


def cmd_proxy(args):
    from qmax.app import App
    from qmax.logs import forward_to_frontend

    frontend = _make_frontend(args.text)
    forward_to_frontend(frontend)
    try:
        app = App(frontend)
        app.start_proxy(args.host, args.port)
        try:
            app.wait_proxy()
        except KeyboardInterrupt:
            app.stop_proxy()
    finally:
        frontend.close()


def cmd_replay(args):
    from qmax.app import App
    from qmax.frontend.text import TextFrontend
    from qmax.logs import forward_to_frontend

    if not args.out:
        frontend = TextFrontend()
        forward_to_frontend(frontend)
        App(frontend).replay(args.file, args.seat)
        return
    with open(args.out, "w", encoding="utf-8") as out:
        frontend = TextFrontend(emit=lambda line: print(line, file=out))
        forward_to_frontend(frontend)
        App(frontend).replay(args.file, args.seat)
    print(f"已寫入：{args.out}")


def cmd_review(args):
    from qmax.app import App
    from qmax.frontend.text import TextFrontend
    from qmax.logs import forward_to_frontend

    frontend = TextFrontend()
    forward_to_frontend(frontend)
    app = App(frontend)
    if args.advisor:
        app.settings["analysis"]["advisor"] = args.advisor  # 只影響這次，不存檔
    out, summary = app.review(args.file, args.seat, args.out, args.compare or [])
    if summary is not None:
        print("\n".join(summary))
        print(f"已寫入：{out}")


def cmd_mjai(args):
    from qmax.app import App
    from qmax.frontend.text import TextFrontend
    from qmax.logs import forward_to_frontend

    frontend = TextFrontend()
    forward_to_frontend(frontend)
    out, count = App(frontend).export_mjai(args.file, args.seat, args.out)
    if count is not None:
        print(f"已寫入：{out}（{count} 個事件）")


def cmd_gui(args):
    from qmax.gui.window import run_gui

    run_gui(debug=args.debug)


def main():
    from qmax import VERSION
    from qmax.app import DEFAULT_HOST, DEFAULT_PORT

    _force_utf8_stdout()

    parser = argparse.ArgumentParser(description=VERSION)
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"代理監聽位址（預設 {DEFAULT_HOST}）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"代理監聽 port（預設 {DEFAULT_PORT}）")
    parser.add_argument("--text", action="store_true", help="不用儀表板，以捲動文字顯示（例如 IDE 的執行視窗）")
    parser.set_defaults(func=cmd_proxy)
    sub = parser.add_subparsers(title="子命令", metavar="{gui,replay,review,mjai}")

    p_gui = sub.add_parser("gui", help="開啟視窗介面，在視窗裡開始／停止監聽")
    p_gui.add_argument("--debug", action="store_true", help="開啟網頁的開發者工具（F12），調整畫面用")
    p_gui.set_defaults(func=cmd_gui)

    p_replay = sub.add_parser("replay", help="重播錄製檔或牌譜，印出分析結果")
    p_replay.add_argument("file", type=Path, help="records/<平台>/live/*.jsonl，或平台的牌譜檔")
    p_replay.add_argument("--seat", type=int, help="牌譜用哪一家的視角（0 起算）；不指定時找自己的帳號")
    p_replay.add_argument("--out", type=Path, help="輸出寫進這個檔案（UTF-8），不印在終端機")
    p_replay.set_defaults(func=cmd_replay)

    p_review = sub.add_parser("review", help="決策紀錄：每個決策點的解析器建議與實際打法，並算出一致率")
    p_review.add_argument("file", type=Path, help="同 replay")
    p_review.add_argument("--seat", type=int, help="同 replay")
    p_review.add_argument("--out", type=Path, help="輸出的 jsonl（預設 logs/review/<檔名>.jsonl）")
    p_review.add_argument("--advisor", help="用哪個解析器（預設是設定檔的 analysis.advisor）")
    p_review.add_argument("--compare", action="append", metavar="NAME", help="另外要比較的解析器，可以重複")
    p_review.set_defaults(func=cmd_review)

    p_mjai = sub.add_parser("mjai", help="匯出 mjai 事件檔（四人一般規則，一家的視角）")
    p_mjai.add_argument("file", type=Path, help="同 replay")
    p_mjai.add_argument("--seat", type=int, help="同 replay")
    p_mjai.add_argument("--out", type=Path, help="輸出的 .mjson（預設 logs/mjai/<檔名>.mjson）")
    p_mjai.set_defaults(func=cmd_mjai)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
