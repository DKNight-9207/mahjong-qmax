# mitmproxy 代理：攔截平台的 WebSocket，每則訊息依序 解碼 → 錄製 → 平台的其他用途 → 分析。
# 分析在背景執行緒進行，hook 不等它就返回，封包不會因為分析而延遲轉發給遊戲。
import asyncio
import json
import logging
import threading
from typing import Callable

from loguru import logger
from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from qmax.advice import Advisor, AdvisorError, open_advisor
from qmax.config import resolve_path
from qmax.frontend.base import Frontend
from qmax.frontend.events import ProxyStatus
from qmax.logs import SessionLog, analyze_data_logger, proxy_logger
from qmax.pipeline import BackgroundPipeline
from qmax.platforms.base import Decoder, Platform
from qmax.recorder import GameRecorder


class ProxyAddon:
    def __init__(self, platform: Platform, settings: dict, frontend: Frontend, on_running: Callable[[], None] = lambda: None):
        log_settings = settings["logging"]
        self.platform = platform
        self.decoders: dict[str, Decoder] = {}  # 每條連線一個（flow.id -> 解碼器）
        self.recorder = GameRecorder(platform)
        self.session_log = SessionLog(
            resolve_path(log_settings["output_dir"]),
            analyze_enabled=log_settings["analyze_log"]["enabled"],
            proxy_enabled=log_settings["proxy_log"]["enabled"],
        )
        self.advisor = self._open_advisor(settings["analysis"])
        self.pipeline = BackgroundPipeline(platform, self.advisor, frontend)
        self._closed = False
        self._on_running = on_running
        logger.info(f"錄製輸出目錄：{self.recorder.live_dir}")

    def _open_advisor(self, settings: dict) -> Advisor | None:
        """啟動失敗時仍會錄製、通知牌桌事件，只是不分析。"""
        if not settings["live"]:
            logger.info("即時分析已在設定中關閉")
            return None
        try:
            advisor = open_advisor(settings["advisor"], on_call=self._log_advisor_call)
        except AdvisorError as e:
            logger.error(f"解析器啟動失敗，本次不做分析：{e}")
            return None
        logger.success(f"解析器已啟動：{advisor.description}")
        return advisor

    def _log_advisor_call(self, endpoint: str, request: dict, response: dict):
        # 在背景執行緒、引擎處理動作的途中呼叫，場況與請求是同一時刻的
        state = self.pipeline.engine.state.snapshot()
        record = {"endpoint": endpoint, "state": state, "request": request, "response": response}
        analyze_data_logger.info(json.dumps(record, ensure_ascii=False))

    # ---- mitmproxy hooks ----

    def websocket_message(self, flow: http.HTTPFlow):
        if not self.platform.accepts(flow.request.url):
            return
        frame = flow.websocket.messages[-1]
        direction = "送出" if frame.from_client else "收到"
        decoder = self.decoders.setdefault(flow.id, self.platform.new_decoder())
        try:
            msg = decoder.decode(frame.content, frame.from_client)
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
            proxy_logger.info(f"{direction}（解析失敗，{reason}）：{frame.content}")
            logger.error(f"{direction}的訊息解析失敗（{reason}），詳見 proxy_log")
            return
        proxy_logger.info(f"{direction}：{msg['method']}")

        boundary = self.recorder.feed(msg)
        self.platform.observe(msg)
        # analyze_log 要跟著分析的進度切檔，所以在背景執行緒處理這則訊息的前後才開關
        stem = self.recorder.stem
        self.pipeline.submit(
            msg,
            before=(lambda: self.session_log.open_game(stem)) if boundary == "start" else None,
            after=self.session_log.close_game if boundary == "end" else None,
        )

    def websocket_end(self, flow: http.HTTPFlow):
        self.decoders.pop(flow.id, None)

    def running(self):
        """代理開始監聽。"""
        self._on_running()

    def done(self):
        self.close()

    def close(self):
        """可以重複呼叫：代理啟動失敗時 mitmproxy 不會呼叫 done，由 ProxyServer 收尾。"""
        if self._closed:
            return
        self._closed = True
        self.pipeline.close()
        if self.advisor is not None:
            self.advisor.close()
        self.recorder.close()
        self.session_log.close()


class _ForwardToProxyLog(logging.Handler):
    """mitmproxy 內部訊息（TLS 失敗等）走標準 logging，轉存進 proxy_log。"""

    def emit(self, record: logging.LogRecord):
        try:
            proxy_logger.info(f"(mitmproxy) {record.getMessage()}")
        except Exception:
            pass


logging.getLogger().addHandler(_ForwardToProxyLog())


class ProxyServer:
    """在背景執行緒跑 mitmproxy。start/stop 可以從任何執行緒呼叫。"""

    def __init__(self, platform: Platform, settings: dict, frontend: Frontend, host: str, port: int):
        self.platform, self.settings, self.frontend = platform, settings, frontend
        self.host, self.port = host, port
        self._master: DumpMaster | None = None
        self._addon: ProxyAddon | None = None
        self._thread = threading.Thread(target=self._run, name="proxy", daemon=True)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def start(self):
        self._thread.start()

    def stop(self, timeout: float = 10.0):
        if self._master is not None:
            self._master.shutdown()
        self._thread.join(timeout)

    def wait(self):
        """等到代理停止。分段等待，讓主執行緒還收得到 Ctrl+C。"""
        while self._thread.is_alive():
            self._thread.join(0.5)

    def _run(self):
        try:
            asyncio.run(self._serve())
        except SystemExit:  # mitmproxy 啟動時有錯誤（例如 port 被占用）會直接 sys.exit
            logger.error(f"代理無法在 {self.host}:{self.port} 啟動（可能 port 已被占用），詳見 proxy_log")
        except Exception as e:
            logger.exception(f"代理意外停止：{type(e).__name__}: {e}")
        finally:
            if self._addon is not None:
                self._addon.close()
            self._master = self._addon = None
            logger.info("代理已停止")
            self.frontend.proxy_status(ProxyStatus(False, self.host, self.port))

    def _on_running(self):
        logger.info(f"代理已啟動：{self.host}:{self.port}")
        self.frontend.proxy_status(ProxyStatus(True, self.host, self.port))

    async def _serve(self):
        # 不載入 termlog/dumper：它們會把每個連線、每個訊框直接印到終端機
        options = Options(listen_host=self.host, listen_port=self.port, ssl_insecure=True)
        self._master = DumpMaster(options, with_termlog=False, with_dumper=False)
        self._addon = ProxyAddon(self.platform, self.settings, self.frontend, on_running=self._on_running)
        self._master.addons.add(self._addon)
        try:
            await self._master.run()
        finally:
            # mitmproxy 結束時不會關掉監聽的 socket，不關的話馬上重新監聽同一個 port 會失敗
            if (proxyserver := self._master.addons.get("proxyserver")) is not None:
                await proxyserver.servers.update([])
