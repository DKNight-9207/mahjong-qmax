# 在 Windows 編譯 akochan 與 qmax_akochan：裝好 MSYS2 的編譯工具後，用它的 MinGW64 環境執行 build.sh。
# 用法：執行同目錄的 build.bat，或在 PowerShell 執行 .\build.ps1
#   -Msys2 路徑   MSYS2 不在 C:\msys64 時指定
#   -Nprocs 數字  akochan 計算用的執行緒數（預設 min(核心數, 4)；每條約佔 164 MB，載入時就預留）
param(
    [string]$Msys2 = "C:\msys64",
    [int]$Nprocs = 0
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8  # build.sh 的訊息是 UTF-8
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$bash = Join-Path $Msys2 "usr\bin\bash.exe"

if (-not (Test-Path $bash)) {
    Write-Host "找不到 MSYS2（$Msys2）。"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "要用 winget 安裝 MSYS2 嗎？(y/N)"
        if ($answer -match '^[yY]') {
            winget install --id MSYS2.MSYS2 -e --accept-source-agreements --accept-package-agreements
        }
    }
    if (-not (Test-Path $bash)) {
        Write-Host "請先安裝 MSYS2（https://www.msys2.org/，預設裝在 C:\msys64），或用 -Msys2 指定安裝位置。"
        exit 1
    }
}

function Invoke-Msys([string]$Command) {
    $env:MSYSTEM = "MINGW64"     # 用 MinGW64 的 gcc 與函式庫
    $env:CHERE_INVOKING = "1"    # 登入後留在目前的資料夾，不切到 MSYS2 的家目錄
    Push-Location $here
    try {
        & $bash -lc $Command
        if ($LASTEXITCODE -ne 0) { throw "執行失敗：$Command" }
    } finally {
        Pop-Location
    }
}

Write-Host "更新 MSYS2 並安裝編譯工具（第一次會下載一陣子）"
# 先整個更新（MSYS2 建議的做法）：只更新部分套件時，gcc 和它的函式庫（例如 OpenMP 的 libgomp）
# 版本可能對不上。更新到 MSYS2 本身時它會要求重開，所以更新兩次，第一次的結束代碼不管。
$env:MSYSTEM = "MINGW64"
& $bash -lc "pacman -Syu --noconfirm"
Invoke-Msys "pacman -Syu --noconfirm"
Invoke-Msys "pacman -S --needed --noconfirm mingw-w64-x86_64-gcc mingw-w64-x86_64-boost git make"
# gcc 16.2.0-4 起 OpenMP 的函式庫拆成獨立的 libgomp 套件，不會跟著 gcc 裝；舊版 MSYS2 沒有這個套件名稱
Invoke-Msys "if pacman -Si mingw-w64-x86_64-libgomp >/dev/null 2>&1; then pacman -S --needed --noconfirm mingw-w64-x86_64-libgomp; fi"

Write-Host "編譯 akochan 與 qmax_akochan"
if ($Nprocs -gt 0) { $env:NPROCS = "$Nprocs" }
Invoke-Msys "./build.sh"

# 用一般 Windows 的環境（PATH 只有系統目錄）試跑一次，確認單獨能啟動；qmax 從 Python 啟動時也是這樣。
# 程式還沒開始執行就失敗（缺 DLL 等）時什麼都不會印，結束碼（NTSTATUS）是唯一的線索。
$statusText = @{  # 鍵是 NTSTATUS 的十進位（PowerShell 5 的十六進位常數是有號 int，會溢位）
    ([uint32]3221225781) = "找不到需要的 DLL"
    ([uint32]3221225785) = "DLL 版本不符（找不到進入點）"
    ([uint32]3221225595) = "映像或 DLL 格式不符"
    ([uint32]3221225477) = "程式崩潰（記憶體存取錯誤）"
    ([uint32]3221225725) = "程式崩潰（堆疊溢位）"
    ([uint32]3221225773) = "記憶體不足（系統認可上限）"
    ([uint32]3221225495) = "記憶體不足"
    ([uint32]3)          = "akochan 內部檢查失敗（abort）"
}
Write-Host "試跑 qmax_akochan"
$buildDir = Join-Path $here "akochan"
$savedPath = $env:Path
$env:Path = "$env:SystemRoot\System32;$env:SystemRoot"
$env:OMP_NUM_THREADS = (Get-Content (Join-Path $buildDir "qmax_nprocs.txt") -Raw).Trim()
Push-Location $buildDir
try {
    $output = @("" | & .\qmax_akochan.exe setup_mjai.json)
    $code = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$LASTEXITCODE), 0)
} finally {
    Pop-Location
    $env:Path = $savedPath
}
if ($output.Count -eq 0 -or $output[0] -ne "QMAX_AKOCHAN_READY") {
    $reason = $statusText[$code]
    if (-not $reason) { $reason = "未知的錯誤" }
    Write-Host ("試跑失敗：{0}（結束碼 0x{1:X8}）" -f $reason, $code)
    if ($output.Count -gt 0) { Write-Host "輸出：$($output -join ' / ')" }
    exit 1
}

Write-Host ""
Write-Host "完成。把 config\settings.yaml 的 analysis.advisor 改成 akochan 就會使用。"
