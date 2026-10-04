#!/usr/bin/env bash
# 把 go/ 底下的原始碼交叉編譯成五個平台的執行檔，輸出到 bin/。
# 用法：cd analyzer/mahjong_helper && ./build.sh [版本號]
#
# 只需要在開發機（或 CI）上跑一次，使用者機器不需要裝 Go。
set -euo pipefail

VERSION="${1:-dev}"
cd "$(dirname "$0")/go"

TARGETS=(
  "linux amd64"
  "linux arm64"
  "windows amd64"
  "darwin amd64"
  "darwin arm64"
)

mkdir -p ../bin

for target in "${TARGETS[@]}"; do
  read -r GOOS GOARCH <<< "$target"
  OUT="../bin/analyzer-server-${GOOS}-${GOARCH}"
  if [ "$GOOS" = "windows" ]; then
    OUT="${OUT}.exe"
  fi
  echo "building ${GOOS}/${GOARCH} -> ${OUT}"
  CGO_ENABLED=0 GOOS="$GOOS" GOARCH="$GOARCH" go build \
    -ldflags "-X main.version=${VERSION}" \
    -o "$OUT" .
done

echo "done. version=${VERSION}"
ls -la ../bin
