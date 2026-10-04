// 萬用牌（例如雀魂萬象修羅的百搭）。萬用牌可以當任何一張牌，身分到和牌時才決定。
//
// mahjong-helper 的何切分析（改良、和率、打點）不支援萬用牌，這裡只算兩樣，但都是精確值：
//   - 向聽：萬用牌代入每一種牌，取最小的向聽
//   - 進張：摸到 X 之後（萬用牌仍可代入任何牌）的最小向聽比現在小，X 就是進張
//
// 手牌字串不含萬用牌，張數另外由 analyzeReq.Jokers 傳入。
package main

import (
	"fmt"
	"sort"
	"strings"

	"qmax-analyzer/util"
	"qmax-analyzer/util/model"
)

// 何切結果裡「切萬用牌」的 discard 值，與 Python 端的 qmax.game.tiles.JOKER 相同。
const jokerTile = "jk"

// parseHandWithJokers 解析不含萬用牌的手牌。手牌少了萬用牌的張數，過不了 parser 的張數檢查，
// 所以先補上同樣張數的佔位牌解析，再從手牌拿掉、剩餘枚數還回去。
func parseHandWithJokers(hand string, jokers int) (*model.PlayerInfo, error) {
	used, _, err := util.StrToTiles34(strings.ToLower(strings.ReplaceAll(hand, "#", " ")))
	if err != nil {
		return nil, err
	}
	placeholder := 0
	for used[placeholder]+jokers > 4 {
		placeholder++
	}
	pi, err := util.ParseHumanTilesWithMelds(strings.Repeat(util.Mahjong[placeholder]+" ", jokers) + hand)
	if err != nil {
		return nil, err
	}
	pi.HandTiles34[placeholder] -= jokers
	pi.LeftTiles34[placeholder] += jokers
	return pi, nil
}

// jokerShanten 萬用牌代入後的最小向聽。tiles34 會被暫時修改，返回前還原。
func jokerShanten(tiles34 []int, jokers int) int {
	return jokerShantenAs(tiles34, jokers, util.CountOfTiles34(tiles34)+jokers)
}

// jokerShantenAs 同 jokerShanten，但把手牌當成 size 張計算；不足的張數視為沒用的牌（見 exchange.go）。
func jokerShantenAs(tiles34 []int, jokers int, size int) int {
	if jokers == 0 {
		return shantenAs(tiles34, size)
	}
	best := 99
	for t := range tiles34 {
		if tiles34[t] >= 4 {
			continue
		}
		tiles34[t]++
		best = util.MinInt(best, jokerShantenAs(tiles34, jokers-1, size))
		tiles34[t]--
	}
	return best
}

// shantenAs 把手牌當成 size 張的向聽（一般型與七對子，同 util.CalculateShanten）。
func shantenAs(tiles34 []int, size int) int {
	shanten := util.CalculateShantenOfNormal(tiles34, size)
	if size >= 13 {
		shanten = util.MinInt(shanten, util.CalculateShantenOfChiitoi(tiles34))
	}
	return shanten
}

// jokerCandidate13 3n+1 張（含萬用牌）的向聽與進張。
func jokerCandidate13(discard string, tiles34 []int, jokers int, left34 []int) candidateResp {
	shanten := jokerShanten(tiles34, jokers)
	waits := util.Waits{}
	for x, left := range left34 {
		if left == 0 || tiles34[x] >= 4 {
			continue
		}
		tiles34[x]++
		if jokerShanten(tiles34, jokers) < shanten {
			waits[x] = left
		}
		tiles34[x]--
	}
	waitList, count := waitsToResp(waits)
	return candidateResp{Discard: discard, Shanten: shanten, Waits: waitList, WaitCount: count, YakuNames: []string{}}
}

// analyzeWithJokers 13 張看目前狀況；14 張對每種切法（含切萬用牌）各給一個候選，依向聽、進張排序。
func analyzeWithJokers(pi *model.PlayerInfo, jokers int) (analyzeResp, error) {
	tiles34, left34 := pi.HandTiles34, pi.LeftTiles34
	resp := analyzeResp{IsNaki: pi.IsNaki(), Jokers: jokers, Candidates: []candidateResp{}}

	switch (util.CountOfTiles34(tiles34) + jokers) % 3 {
	case 1:
		c := jokerCandidate13("", tiles34, jokers, left34)
		resp.Shanten = c.Shanten
		resp.Candidates = append(resp.Candidates, c)
	case 2:
		resp.Shanten = jokerShanten(tiles34, jokers)
		for t, n := range tiles34 {
			if n == 0 {
				continue
			}
			tiles34[t]--
			resp.Candidates = append(resp.Candidates, jokerCandidate13(util.Mahjong[t], tiles34, jokers, left34))
			tiles34[t]++
		}
		resp.Candidates = append(resp.Candidates, jokerCandidate13(jokerTile, tiles34, jokers-1, left34))
		sort.SliceStable(resp.Candidates, func(i, j int) bool {
			a, b := resp.Candidates[i], resp.Candidates[j]
			if a.Shanten != b.Shanten {
				return a.Shanten < b.Shanten
			}
			return a.WaitCount > b.WaitCount
		})
	default:
		return resp, fmt.Errorf("手牌張數不對：%d 張加 %d 張萬用牌（不含副露應為 3n+1 或 3n+2 張）", util.CountOfTiles34(tiles34), jokers)
	}
	return resp, nil
}
