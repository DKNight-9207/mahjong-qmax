# qmax_akochan 子行程（analyzer/akochan/qmax_akochan.cpp）：一行請求、一行回應。
# akochan 要自己編（analyzer/akochan/build.sh），使用規約不允許和這個專案一起散布。
import json
import os
import platform
import queue
import signal
import subprocess
import threading
from pathlib import Path

from qmax import ROOT
from qmax.advice import child_process

BUILD_DIR = ROOT / "analyzer" / "akochan" / "akochan"  # build.sh 的輸出，也是 akochan 讀參數檔（params/）的目錄
DEFAULT_TACTICS = BUILD_DIR / "setup_mjai.json"  # akochan 附的策略設定
READY = "QMAX_AKOCHAN_READY"

_DLL_HINT = "重新執行 build.bat，它會把需要的 DLL 複製到 qmax_akochan.exe 旁邊並試跑一次"
_WINDOWS_STATUS = {
    0xC0000135: f"找不到需要的 DLL（{_DLL_HINT}）",
    0xC0000139: f"DLL 版本不符，可能載入了 PATH 上其他程式的同名 DLL（{_DLL_HINT}）",
    0xC000007B: f"DLL 格式不符，可能載入了 32 位元的同名 DLL（{_DLL_HINT}）",
    0xC0000005: "程式崩潰（記憶體存取錯誤）",
    0xC00000FD: "程式崩潰（堆疊溢位）",
    3: "akochan 內部檢查失敗（abort）",
}


class AkochanServerError(Exception):
    """unreachable：子行程沒有回應或已經結束；其他：請求被拒絕。"""

    def __init__(self, message: str, unreachable: bool):
        super().__init__(message)
        self.unreachable = unreachable


def binary_path() -> Path:
    path = BUILD_DIR / ("qmax_akochan.exe" if platform.system() == "Windows" else "qmax_akochan")
    if not path.exists():
        raise AkochanServerError(f"找不到 {path.name}，akochan 要先自己編譯（analyzer/akochan/build.sh）", unreachable=True)
    return path


class AkochanServer:
    def __init__(self, tactics: Path = DEFAULT_TACTICS, timeout: float = 30.0):
        """tactics：akochan 的策略設定檔。timeout：一次計算最多等多久（akochan 一次大約 0.5～5 秒，依電腦而定）。"""
        self.timeout = timeout
        self._lines: queue.Queue[str | None] = queue.Queue()
        binary = binary_path()
        env = dict(os.environ)
        env["OMP_NUM_THREADS"] = (BUILD_DIR / "qmax_nprocs.txt").read_text().strip()  # 不能超過編譯時的 NPROCS
        library_path = "PATH" if platform.system() == "Windows" else "LD_LIBRARY_PATH"
        env[library_path] = os.pathsep.join([str(BUILD_DIR), env.get(library_path, "")])
        self.process = child_process.spawn(
            [str(binary), str(tactics)],
            cwd=BUILD_DIR, env=env, text=True, bufsize=1, encoding="utf-8",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        threading.Thread(target=self._read, name="akochan-reader", daemon=True).start()
        try:
            first = self._lines.get(timeout=10.0)
        except queue.Empty:
            self.close()
            raise AkochanServerError("qmax_akochan 無法啟動：10 秒內沒有回應", unreachable=True)
        if first != READY:
            # 啟動失敗時程式通常什麼都沒印（例如缺 DLL），結束碼才是線索；有印東西也一併附上
            self.close()
            output = [first, *self._drain()] if first is not None else []
            shown = f"；輸出：{' / '.join(output[-5:])}" if output else ""
            raise AkochanServerError(f"qmax_akochan 無法啟動：{self._exit_reason()}{shown}", unreachable=True)

    def request(self, seat: int, record: list[dict]) -> list:
        """record：從 start_game 起、這一局到目前為止的 mjai 事件。回傳 akochan 的 ai_review 結果。"""
        if not self.is_alive():
            raise AkochanServerError("qmax_akochan 已經結束", unreachable=True)
        self.process.stdin.write(json.dumps({"id": seat, "record": record}, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        line = self._next_line(self.timeout)
        try:
            response = json.loads(line)
        except ValueError:
            # akochan 內部檢查失敗時會印出原因、接著結束
            raise AkochanServerError(f"akochan 內部錯誤：{line}", unreachable=False)
        if isinstance(response, dict) and "error" in response:
            raise AkochanServerError(response["error"], unreachable=False)
        return response

    def _next_line(self, timeout: float) -> str:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self.close()  # 算到一半的結果之後才回來會和下一個請求對錯，直接收掉
            raise AkochanServerError(f"akochan 超過 {timeout:.0f} 秒沒有回應", unreachable=True)
        if line is None:
            raise AkochanServerError(f"qmax_akochan 已經結束：{self._exit_reason()}", unreachable=True)
        return line

    def _read(self):
        for line in self.process.stdout:
            self._lines.put(line.rstrip("\n"))
        self._lines.put(None)

    def _drain(self) -> list[str]:
        """行程結束後，讀出還留在佇列裡的輸出。"""
        lines = []
        try:
            while (line := self._lines.get(timeout=2.0)) is not None:
                lines.append(line)
        except queue.Empty:
            pass
        return lines

    def _exit_reason(self) -> str:
        try:
            code = self.process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            return "沒有回應"
        if platform.system() == "Windows":
            # 結束碼可能是 NTSTATUS（0xC…）；程式還沒開始執行就失敗（例如缺 DLL）時只有這個線索
            code &= 0xFFFFFFFF
            return _WINDOWS_STATUS.get(code, f"結束碼 {code}（0x{code:08X}）")
        if code < 0:
            return f"被訊號 {signal.Signals(-code).name} 終止"
        return f"結束碼 {code}"

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def close(self):
        child_process.stop(self.process)
