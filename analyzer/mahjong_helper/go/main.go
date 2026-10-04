// analyzer-server：把 mahjong-helper 的 util/（向聽、進張、危险度、點數）包成
// 本地 HTTP 服務，所有 endpoint 都是 JSON in / JSON out、無狀態。
//
// 啟動後在 stdout 印一行
//
//	QMAX_ANALYZER_LISTENING port=<port> version=<version>
//
// 呼叫端靠這行得知實際監聽的 port（-port 0 時由系統分配）。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"net/http"
)

// 建置時以 -ldflags "-X main.version=..." 注入，呼叫端用 /version 核對。
var version = "dev"

func handleVersion(w http.ResponseWriter, r *http.Request) {
	json.NewEncoder(w).Encode(map[string]string{"version": version})
}

func main() {
	port := flag.Int("port", 0, "監聽的 port，0 代表由系統挑選")
	flag.Parse()

	http.HandleFunc("/analyze", handleAnalyze)
	http.HandleFunc("/risk", handleRisk)
	http.HandleFunc("/exchange", handleExchange)
	http.HandleFunc("/version", handleVersion)

	listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", *port))
	if err != nil {
		panic(err)
	}
	actualPort := listener.Addr().(*net.TCPAddr).Port
	fmt.Printf("QMAX_ANALYZER_LISTENING port=%d version=%s\n", actualPort, version)

	if err := http.Serve(listener, withRecover(http.DefaultServeMux)); err != nil {
		panic(err)
	}
}
