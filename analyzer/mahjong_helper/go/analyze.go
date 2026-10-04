// POST /analyze：何切／牌效率分析，剩餘枚數會扣掉場上看得到的牌。
//
// 手牌記法沿用 mahjong-helper（util.ParseHumanTilesWithMelds）：
//
//	"24688m 34s # 6666P 234p"
//
// "#" 之前是手牌、之後是副露（空格分隔），大寫花色表示暗槓。
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sort"

	"qmax-analyzer/util"
	"qmax-analyzer/util/model"
)

type analyzeReq struct {
	Hand    string `json:"hand"`    // 自己的手牌+副露（不含萬用牌）；14 張做何切，13 張看目前狀況
	Jokers  int    `json:"jokers"`  // 手牌中的萬用牌張數；大於 0 時只算向聽與進張（見 joker.go）
	Visible string `json:"visible"` // 場上看得到、不在自己手牌/副露裡的所有牌，攤平成一串

	// 以下影響役種、打點、振聽與和率；都可省略（省略時當作無寶牌、東場東家以外、未立直）
	DoraIndicators string `json:"dora_indicators"` // 寶牌指示牌，攤平
	IsSanma        bool   `json:"is_sanma"`        // 三麻：1m 指示牌的寶牌是 9m
	NukiDora       int    `json:"nuki_dora"`       // 自己拔北的張數
	RoundWind      string `json:"round_wind"`      // 場風，例如 "1z"
	SelfWind       string `json:"self_wind"`       // 自風
	IsDealer       bool   `json:"is_dealer"`
	IsRiichi       bool   `json:"is_riichi"` // 自己已立直
	Discards       string `json:"discards"`  // 自己的捨牌（含被叫走的），攤平；用於振聽判斷與和率
}

type waitTile struct {
	Tile  string `json:"tile"`
	Count int    `json:"count"` // 剩餘枚數
}

type candidateResp struct {
	Discard string `json:"discard"` // 切的牌；13 張時為空字串

	Shanten      int        `json:"shanten"`
	Waits        []waitTile `json:"waits"`
	WaitCount    int        `json:"wait_count"`
	AvgAgariRate float64    `json:"avg_agari_rate"`
	FuritenRate  float64    `json:"furiten_rate"`
	DamaPoint    float64    `json:"dama_point"`
	RiichiPoint  float64    `json:"riichi_point"`

	AvgImproveWaitsCount     float64 `json:"avg_improve_waits_count"`      // 摸到改良牌後的平均進張
	ImproveCount             int     `json:"improve_count"`                // 改良牌種數
	MixedWaitsScore          float64 `json:"mixed_score"`                  // 綜合速度評分（1~2 向聽才有意義）
	AvgNextShantenWaitsCount float64 `json:"avg_next_shanten_waits_count"` // 向聽前進後的平均進張

	// 役種。Go 只在聽牌時計算，1~2 向聽一律為空。
	YakuNames []string `json:"yaku_names"`
}

type analyzeResp struct {
	Shanten    int             `json:"shanten"`
	Jokers     int             `json:"jokers"` // 同請求；大於 0 時候選只有向聽與進張
	IsNaki     bool            `json:"is_naki"`
	Candidates []candidateResp `json:"candidates"`
	Error      string          `json:"error,omitempty"`
}

func waitsToResp(w util.Waits) ([]waitTile, int) {
	tiles := w.AvailableTiles()
	sort.Ints(tiles)
	out := make([]waitTile, 0, len(tiles))
	for _, idx := range tiles {
		out = append(out, waitTile{Tile: util.Mahjong[idx], Count: w[idx]})
	}
	return out, w.AllCount()
}

// yakuTypesToNames 把役種 set 轉成排序固定的役名清單。
func yakuTypesToNames(yakuTypes map[int]struct{}) []string {
	if len(yakuTypes) == 0 {
		return []string{}
	}
	types := make([]int, 0, len(yakuTypes))
	for t := range yakuTypes {
		types = append(types, t)
	}
	sort.Ints(types)
	names := make([]string, 0, len(types))
	for _, t := range types {
		if name, ok := util.YakuNameMap[t]; ok {
			names = append(names, name)
		}
	}
	return names
}

func result13ToCandidate(discardTile int, r *util.Hand13AnalysisResult) candidateResp {
	discardStr := ""
	if discardTile >= 0 {
		discardStr = util.Mahjong[discardTile]
	}
	waits, count := waitsToResp(r.Waits)
	return candidateResp{
		Discard:      discardStr,
		Shanten:      r.Shanten,
		Waits:        waits,
		WaitCount:    count,
		AvgAgariRate: r.AvgAgariRate,
		FuritenRate:  r.FuritenRate,
		DamaPoint:    r.DamaPoint,
		RiichiPoint:  r.RiichiPoint,

		AvgImproveWaitsCount:     r.AvgImproveWaitsCount,
		ImproveCount:             len(r.Improves),
		MixedWaitsScore:          r.MixedWaitsScore,
		AvgNextShantenWaitsCount: r.AvgNextShantenWaitsCount,

		YakuNames: yakuTypesToNames(r.YakuTypes),
	}
}

func handleAnalyze(w http.ResponseWriter, r *http.Request) {
	var req analyzeReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(analyzeResp{Error: err.Error()})
		return
	}

	// parser 會把手牌與副露從 LeftTiles34 扣掉
	playerInfo, err := parseHand(req.Hand, req.Jokers)
	if err != nil {
		json.NewEncoder(w).Encode(analyzeResp{Error: "手牌解析失敗: " + err.Error()})
		return
	}
	if err := applySituation(playerInfo, req); err != nil {
		json.NewEncoder(w).Encode(analyzeResp{Error: err.Error()})
		return
	}

	if err := subtractVisible(playerInfo, req.Visible); err != nil {
		json.NewEncoder(w).Encode(analyzeResp{Error: err.Error()})
		return
	}

	if req.Jokers > 0 {
		resp, err := analyzeWithJokers(playerInfo, req.Jokers)
		if err != nil {
			resp.Error = err.Error()
		}
		json.NewEncoder(w).Encode(resp)
		return
	}

	count := util.CountOfTiles34(playerInfo.HandTiles34)
	resp := analyzeResp{IsNaki: playerInfo.IsNaki(), Candidates: []candidateResp{}}

	switch count % 3 {
	case 1: // 13 張
		result := util.CalculateShantenWithImproves13(playerInfo)
		resp.Shanten = result.Shanten
		resp.Candidates = []candidateResp{result13ToCandidate(-1, result)}

	case 2: // 14 張：每個切牌選擇各一個候選
		shanten, results14, incResults14 := util.CalculateShantenWithImproves14(playerInfo)
		resp.Shanten = shanten
		for _, r14 := range results14 {
			resp.Candidates = append(resp.Candidates, result13ToCandidate(r14.DiscardTile, r14.Result13))
		}
		for _, r14 := range incResults14 {
			resp.Candidates = append(resp.Candidates, result13ToCandidate(r14.DiscardTile, r14.Result13))
		}

	default:
		resp.Error = fmt.Sprintf("手牌張數不對：%d 張（不含副露應為 3n+1 或 3n+2 張）", count)
	}

	json.NewEncoder(w).Encode(resp)
}

// subtractVisible 從剩餘枚數扣掉場上看得到的牌。
func subtractVisible(pi *model.PlayerInfo, visible string) error {
	if visible == "" {
		return nil
	}
	visibleTiles34, _, err := util.StrToTiles34(visible)
	if err != nil {
		return fmt.Errorf("場況牌解析失敗: %v", err)
	}
	for i, c := range visibleTiles34 {
		pi.LeftTiles34[i] -= c
		if pi.LeftTiles34[i] < 0 {
			return fmt.Errorf("%s 加總超過 4 枚，檢查一下手牌/副露/場況牌是不是重複算了", util.Mahjong[i])
		}
	}
	return nil
}

func parseHand(hand string, jokers int) (*model.PlayerInfo, error) {
	if jokers > 0 {
		return parseHandWithJokers(hand, jokers)
	}
	return util.ParseHumanTilesWithMelds(hand)
}

// applySituation 把場況填進 PlayerInfo，欄位對應 mahjong-helper core.go 的 newModelPlayerInfo()。
func applySituation(pi *model.PlayerInfo, req analyzeReq) error {
	indicators, _, err := util.StrToTiles(req.DoraIndicators)
	if err != nil && req.DoraIndicators != "" {
		return fmt.Errorf("寶牌指示牌解析失敗: %v", err)
	}
	pi.DoraTiles = model.DoraList(indicators, req.IsSanma)
	pi.NukiDoraNum = req.NukiDora

	if pi.RoundWindTile, err = windTile(req.RoundWind); err != nil {
		return fmt.Errorf("場風解析失敗: %v", err)
	}
	if pi.SelfWindTile, err = windTile(req.SelfWind); err != nil {
		return fmt.Errorf("自風解析失敗: %v", err)
	}
	pi.IsParent = req.IsDealer
	pi.IsRiichi = req.IsRiichi

	if req.Discards != "" {
		if pi.DiscardTiles, _, err = util.StrToTiles(req.Discards); err != nil {
			return fmt.Errorf("捨牌解析失敗: %v", err)
		}
	}
	return nil
}

// windTile 省略時回傳東（27），與 NewSimplePlayerInfo 的預設相同。
func windTile(s string) (int, error) {
	if s == "" {
		return 27, nil
	}
	t, _, err := util.StrToTile34(s)
	return t, err
}
