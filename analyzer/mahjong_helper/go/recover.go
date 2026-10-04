package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"runtime/debug"
)

// withRecover 把 handler 內的 panic 轉成 JSON 錯誤回應：
//
//	{"error": "分析器內部錯誤: ...", "panic": true, "stack": "<Go 呼叫堆疊>"}
//
// 這個行程的 stderr 沒有人讀，錯誤只能靠回應帶回呼叫端。mahjong-helper 的
// 核心 parser 遇到不合法手牌（例如同一張牌手牌+副露超過 4 張）是直接 panic，
// 不處理的話請求會直接斷線。
func withRecover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bw := &bufferedWriter{header: http.Header{}, status: http.StatusOK}
		func() {
			defer func() {
				if rec := recover(); rec != nil {
					bw.header = http.Header{"Content-Type": {"application/json"}}
					bw.body.Reset() // 丟掉 panic 前寫了一半的內容
					bw.status = http.StatusOK
					json.NewEncoder(&bw.body).Encode(map[string]any{
						"error": fmt.Sprintf("分析器內部錯誤: %v", rec),
						"panic": true,
						"stack": string(debug.Stack()),
					})
				}
			}()
			next.ServeHTTP(bw, r)
		}()

		for k, vs := range bw.header {
			for _, v := range vs {
				w.Header().Add(k, v)
			}
		}
		w.WriteHeader(bw.status)
		w.Write(bw.body.Bytes())
	})
}

// bufferedWriter 先把回應留在記憶體，handler 正常結束才送出。
type bufferedWriter struct {
	header http.Header
	status int
	body   bytes.Buffer
}

func (b *bufferedWriter) Header() http.Header         { return b.header }
func (b *bufferedWriter) WriteHeader(status int)      { b.status = status }
func (b *bufferedWriter) Write(p []byte) (int, error) { return b.body.Write(p) }
