#!/usr/bin/env bash
# 下載並編譯 akochan（critter-mj/akochan），再編譯 qmax 呼叫它用的 qmax_akochan。
# akochan 的使用規約不允許和這個專案一起散布，所以要在自己的電腦上編。
#
# 用法：cd analyzer/akochan && ./build.sh
#   Linux：  需要 g++、make、git 與 boost 標頭檔（例如 sudo apt install g++ make git libboost-dev）
#   macOS：  brew install llvm libomp boost（用 akochan 的 Makefile_MacOS）
#   Windows：執行同目錄的 build.bat（或 build.ps1），會用 MSYS2 的 MinGW64 環境跑這個腳本
#
# 輸出都在 akochan/ 底下（不進版本控制）：libai.so 或 ai.dll、qmax_akochan、qmax_nprocs.txt
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d akochan ]; then
  git clone --depth 1 https://github.com/critter-mj/akochan.git
fi

# akochan 的計算工作區（ai_src 的 tehai_calculator_work）是靜態陣列，每條執行緒約 164 MB，條數在編譯時
# 由 NPROCS 決定；執行時的執行緒數不能超過它（qmax 會設好 OMP_NUM_THREADS）。
# Windows 載入 DLL 時就要預留整塊靜態記憶體，NPROCS=12 時 ai.dll 接近 2 GB 的映像上限，所以預設最多 4
# （akochan 自己的 Windows Makefile 也是 4）；要更多可以設 NPROCS（build.bat -Nprocs 6）。
NPROCS_DEFAULT="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
if [[ "$(uname -s)" == MINGW* ]] && ((NPROCS_DEFAULT > 4)); then
  NPROCS_DEFAULT=4
fi
NPROCS="${NPROCS:-$NPROCS_DEFAULT}"

# 不改 akochan 的原始碼，只用編譯器參數補兩件事：
#   -include cstdint                    新版 gcc 的標準標頭不再順帶 <cstdint>，json11.cpp 會找不到 uint8_t
#   BOOST_BIND_GLOBAL_PLACEHOLDERS      關掉新版 boost 每個檔案都印一次的過時警告
COMPAT=(-include cstdint -DBOOST_BIND_GLOBAL_PLACEHOLDERS)
CXX="${CXX:-g++}"

case "$(uname -s)" in
  # AI 部分只用到 boost 的標頭檔，不必連結 boost 的函式庫（新版 boost 不一定還有 boost_system）；
  # Windows 上 boost.asio 的標頭會用到 Winsock，要連結 ws2_32。macOS 的 LIBS 另外帶了 libomp 的路徑，保留原本的設定
  Linux*)  MAKEFILE=Makefile_Linux; EXE="";     MAKE_ARGS=("LIBS=");         SYSLIBS=() ;;
  Darwin*) MAKEFILE=Makefile_MacOS; EXE="";     MAKE_ARGS=();                SYSLIBS=(); CXX="$(brew --prefix llvm)/bin/clang++" ;;
  MINGW*)  MAKEFILE=Makefile;       EXE=".exe"; MAKE_ARGS=("LIBS=-lws2_32"); SYSLIBS=(-lws2_32) ;;
  *) echo "不支援的系統：$(uname -s)（Windows 請用 build.bat，它會用 MSYS2 的 MinGW64 環境執行）"; exit 1 ;;
esac

# akochan 用 OpenMP 平行計算，連結時需要 libgomp
omp_check() {
  echo 'int main(){}' | "$CXX" -x c++ -fopenmp - -o "$TMPDIR_CHECK/omp_check" 2>&1
}
TMPDIR_CHECK="$(mktemp -d)"
if ! omp_check > "$TMPDIR_CHECK/log"; then
  # MSYS2 有時只裝了 libgomp-1.dll、少了連結用的 libgomp.dll.a；MinGW 的連結器找 -lgomp 時
  # 也接受直接叫 libgomp.dll 的 DLL，所以複製一份改名放進額外的搜尋路徑
  if [[ "$(uname -s)" == MINGW* && -f /mingw64/bin/libgomp-1.dll ]]; then
    mkdir -p akochan/omp_link
    cp /mingw64/bin/libgomp-1.dll akochan/omp_link/libgomp.dll
    export LIBRARY_PATH="$PWD/akochan/omp_link${LIBRARY_PATH:+:$LIBRARY_PATH}"
    echo "找不到 libgomp.dll.a，改用 /mingw64/bin/libgomp-1.dll 連結"
  fi
  if ! omp_check > "$TMPDIR_CHECK/log"; then
    echo "編譯器無法使用 OpenMP（libgomp）。MSYS2 請先 pacman -S mingw-w64-x86_64-libgomp（build.bat 會自動裝）。錯誤訊息："
    tail -n 5 "$TMPDIR_CHECK/log"
    exit 1
  fi
fi
rm -rf "$TMPDIR_CHECK"

# NPROCS 和上次編譯不同時，make 不會自己發現，要全部重編
if [ "$(cat akochan/qmax_nprocs.txt 2>/dev/null || true)" != "$NPROCS" ]; then
  MAKE_ARGS+=("-B")
fi
echo "編譯 akochan 的 AI 函式庫（NPROCS=${NPROCS}）"
(cd akochan/ai_src && make -f "$MAKEFILE" NPROCS="$NPROCS" COMPILER="$CXX ${COMPAT[*]}" ${MAKE_ARGS[@]+"${MAKE_ARGS[@]}"})

echo "編譯 qmax_akochan"
EXTRA=()
case "$(uname -s)" in
  Darwin*) EXTRA=(-I"$(brew --prefix boost)/include" -L"$(brew --prefix llvm)/lib") ;;
  MINGW*)  EXTRA=(-DWINSTD) ;;  # 和 akochan 的 Windows 版一樣；部分宣告依它切換
esac
# json11 等共用程式碼（share/）在 Windows 的 ai.dll 裡沒有匯出，和 akochan 自己的 system.exe 一樣直接連結編好的目的檔
"$CXX" "${COMPAT[@]}" -std=c++11 -O3 -fopenmp -pthread -DNPROCS="$NPROCS" -Iakochan ${EXTRA[@]+"${EXTRA[@]}"} \
  qmax_akochan.cpp akochan/share/obj/*.o -Lakochan -lai ${SYSLIBS[@]+"${SYSLIBS[@]}"} -o "akochan/qmax_akochan${EXE}"

# 從 Windows 的 Python 啟動時，PATH 上沒有 MSYS2 的 DLL（libgomp、libstdc++…），甚至可能有別的程式
# 帶的同名舊版；Windows 會先找 exe 所在的目錄，所以把用到的 DLL 都複製一份放在旁邊。
# 依各檔案的匯入表逐層找（DLL 自己也會用到其他 DLL），不在 MinGW 也不在系統目錄的就是缺的。
copy_runtime_dlls() {
  local queue=("$@") seen=" " missing=() file name
  local system32
  system32="$(cygpath -S)"
  while ((${#queue[@]})); do
    file="${queue[0]}"; queue=("${queue[@]:1}")
    for name in $(objdump -p "$file" | sed -n 's/^[[:space:]]*DLL Name: //p' | tr -d '\r'); do
      [[ "$seen" == *" ${name,,} "* ]] && continue
      seen+="${name,,} "
      if [ -f "/mingw64/bin/$name" ]; then
        cp "/mingw64/bin/$name" akochan/
        echo "  複製 $name"
        queue+=("/mingw64/bin/$name")
      elif [ ! -f "akochan/$name" ] && [ ! -f "$system32/$name" ]; then
        missing+=("$name")
      fi
    done
  done
  if ((${#missing[@]})); then
    echo "找不到這些 DLL：${missing[*]}"
    exit 1
  fi
}

# 編好後試跑一次，確認能啟動（環境和 qmax 從 Python 啟動時一樣）
smoke_test() {
  local out code
  set +e
  out="$(cd akochan && OMP_NUM_THREADS="$NPROCS" LD_LIBRARY_PATH=. "./qmax_akochan${EXE}" setup_mjai.json </dev/null 2>&1)"
  code=$?
  set -e
  if [[ "$out" != QMAX_AKOCHAN_READY* ]]; then
    echo "試跑失敗（結束碼 $code）：${out:-沒有輸出}"
    exit 1
  fi
}

echo "$NPROCS" > akochan/qmax_nprocs.txt
if [[ "$(uname -s)" == MINGW* ]]; then
  echo "複製執行時需要的 DLL"
  copy_runtime_dlls "akochan/qmax_akochan.exe" "akochan/ai.dll"
  # MSYS2 會把 Windows 程式的錯誤碼（NTSTATUS）一律變成 127，看不出原因，所以試跑交給 build.ps1
  echo "編譯完成：akochan/qmax_akochan${EXE}"
  exit 0
fi
echo "試跑 qmax_akochan"
smoke_test
echo "完成：akochan/qmax_akochan${EXE}"
