# 跟著主程式一起結束的子行程。解析器若是另開一個程式（Go 伺服器、AI 的 mjai bot…）就用這裡啟動，
# 即使 Python 是被強制終止（IDE 停止鍵、taskkill、crash）而沒機會呼叫 close()，子行程也會跟著結束：
#
#   Windows：把子行程放進帶 KILL_ON_JOB_CLOSE 的 Job Object；Python 結束時
#            系統關閉 job handle，子行程隨之被終止。
#   Linux：  prctl(PR_SET_PDEATHSIG)，父行程死亡時核心送 SIGTERM。這裡的「父」其實是建立子行程的
#            那條執行緒，從短命的執行緒（例如 GUI 每次 API 呼叫的執行緒）啟動，那條執行緒一結束
#            子行程就被殺，所以統一由 _SPAWNER 的常駐執行緒建立。
#   macOS：  沒有對應機制，只能靠 close()。
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor

from loguru import logger


def spawn(args: list[str], **popen_kwargs) -> subprocess.Popen:
    """同 subprocess.Popen(args, **popen_kwargs)，另外讓子行程跟著主程式結束。"""
    if platform.system() == "Linux":
        process = _SPAWNER.submit(subprocess.Popen, args, preexec_fn=_die_with_parent, **popen_kwargs).result()
    else:
        process = subprocess.Popen(args, **popen_kwargs)
    _tie_to_parent(process, args[0])
    return process


def stop(process: subprocess.Popen, timeout: float = 5.0):
    """先請它結束，逾時再強制結束。已經結束就什麼都不做。"""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()


_SPAWNER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="child-process-spawner")


def _die_with_parent():
    try:
        import ctypes
        import signal

        PR_SET_PDEATHSIG = 1
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass


if platform.system() == "Windows":
    import ctypes
    from ctypes import wintypes

    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def _create_kill_on_close_job():
        try:
            kernel32 = ctypes.windll.kernel32
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return None
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = kernel32.SetInformationJobObject(
                job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
            )
            if not ok:
                kernel32.CloseHandle(job)
                return None
            return job
        except Exception:
            return None

    # 整個行程共用一個 job，刻意不關閉 handle：它要活到行程結束才有效。
    _WINDOWS_JOB = _create_kill_on_close_job()

    def _tie_to_parent(process: subprocess.Popen, name: str):
        try:
            assigned = _WINDOWS_JOB is not None and ctypes.windll.kernel32.AssignProcessToJobObject(
                _WINDOWS_JOB, int(process._handle)
            )
        except Exception:
            assigned = False
        if not assigned:
            logger.warning(f"無法把 {name} 綁進 Windows Job Object，若 Python 被強制結束，需手動到工作管理員結束它。")

else:

    def _tie_to_parent(process: subprocess.Popen, name: str):
        pass  # Linux 由 preexec_fn 處理；macOS 無對應機制
