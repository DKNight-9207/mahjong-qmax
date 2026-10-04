// POST /exchange：開局換牌（換三張）要換出哪幾張。
//
// 換入的牌未知，當成沒用的牌：保留的牌照 13 張手牌計算向聽與進張，等於只靠保留的牌湊出整副手牌。
// 莊家 14 張時假設換入的牌之後會打掉一張，同樣照 13 張計算。萬用牌不換出，但照常代入計算。
// 先算所有換法的向聽（很快），只對向聽最小的幾種再算進張（比較慢）。
package main

import (
	"encoding/json"
	"net/http"
	"sort"

	"qmax-analyzer/util"
)

const maxExchangeCandidates = 10

type exchangeReq struct {
	Hand    string `json:"hand"`    // 同 /analyze（不含萬用牌，不可有副露）
	Jokers  int    `json:"jokers"`  // 同 /analyze
	Visible string `json:"visible"` // 同 /analyze
	Count   int    `json:"count"`   // 要換出幾張
}

type exchangeCandidate struct {
	Tiles     []string   `json:"tiles"`      // 換出的牌
	Shanten   int        `json:"shanten"`    // 換入的牌都沒用時的向聽
	Waits     []waitTile `json:"waits"`      // 同上情況下的進張
	WaitCount int        `json:"wait_count"` // 進張剩餘枚數總和
}

type exchangeResp struct {
	Shanten    int                 `json:"shanten"` // 目前手牌的向聽
	Candidates []exchangeCandidate `json:"candidates"`
	Error      string              `json:"error,omitempty"`
}

func handleExchange(w http.ResponseWriter, r *http.Request) {
	var req exchangeReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(exchangeResp{Error: err.Error()})
		return
	}
	pi, err := parseHand(req.Hand, req.Jokers)
	if err != nil {
		json.NewEncoder(w).Encode(exchangeResp{Error: "手牌解析失敗: " + err.Error()})
		return
	}
	if err := subtractVisible(pi, req.Visible); err != nil {
		json.NewEncoder(w).Encode(exchangeResp{Error: err.Error()})
		return
	}
	tiles34, left34 := pi.HandTiles34, pi.LeftTiles34
	resp := exchangeResp{Shanten: jokerShanten(tiles34, req.Jokers), Candidates: []exchangeCandidate{}}

	var options [][]int
	forEachCombination(tiles34, req.Count, 0, nil, func(out []int) {
		options = append(options, append([]int(nil), out...))
	})

	// 第一輪：所有換法的向聽
	shantens := make([]int, len(options))
	best := 99
	for i, out := range options {
		removeTiles(tiles34, out)
		shantens[i] = jokerShantenAs(tiles34, req.Jokers, 13)
		addTiles(tiles34, out)
		best = util.MinInt(best, shantens[i])
	}

	// 第二輪：向聽最小的換法再算進張
	for i, out := range options {
		if shantens[i] != best {
			continue
		}
		removeTiles(tiles34, out)
		waits := util.Waits{}
		for x, left := range left34 {
			if left == 0 || tiles34[x] >= 4 {
				continue
			}
			tiles34[x]++
			if jokerShantenAs(tiles34, req.Jokers, 14) < best {
				waits[x] = left
			}
			tiles34[x]--
		}
		addTiles(tiles34, out)
		waitList, count := waitsToResp(waits)
		names := make([]string, len(out))
		for k, t := range out {
			names[k] = util.Mahjong[t]
		}
		resp.Candidates = append(resp.Candidates, exchangeCandidate{names, best, waitList, count})
	}
	sort.SliceStable(resp.Candidates, func(i, j int) bool {
		return resp.Candidates[i].WaitCount > resp.Candidates[j].WaitCount
	})
	if len(resp.Candidates) > maxExchangeCandidates {
		resp.Candidates = resp.Candidates[:maxExchangeCandidates]
	}
	json.NewEncoder(w).Encode(resp)
}

// forEachCombination 列舉從 tiles34 取 k 張的所有組合（同種牌不重複列舉），牌依編號排序。
func forEachCombination(tiles34 []int, k int, from int, picked []int, visit func([]int)) {
	if k == 0 {
		visit(picked)
		return
	}
	for t := from; t < len(tiles34); t++ {
		if tiles34[t] == 0 {
			continue
		}
		tiles34[t]--
		forEachCombination(tiles34, k-1, t, append(picked, t), visit)
		tiles34[t]++
	}
}

func removeTiles(tiles34 []int, tiles []int) {
	for _, t := range tiles {
		tiles34[t]--
	}
}

func addTiles(tiles34 []int, tiles []int) {
	for _, t := range tiles {
		tiles34[t]++
	}
}
