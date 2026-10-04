// POST /risk：單一對手對自己的危险度。無狀態，每次呼叫都傳完整快照。
//
// 計算方式同 mahjong-helper core.go 的 analysisTilesRisk()：
//   - 安牌：這家的棄牌（振聽）+ extra_safe + 這家明槓的第一張
//   - 巡目：這家的棄牌數
//   - 聽牌率：立直為 100，否則 util.CalcTenpaiRate（三麻再經 util.GetTenpaiRate3）
//   - 估計打點：立直一發／立直／副露（含寶牌數）／默聽 四級，莊家 ×1.5
//     副露的寶牌數 = 副露中的寶牌 + 赤5 + 拔北（北是寶牌時拔北再算一次），同上游 playerInfo.doraNum()
//   - 危险度：util.CalculateRiskTiles34(...).FixWithPoint(ronPoint)
package main

import (
	"encoding/json"
	"net/http"
	"strings"

	"qmax-analyzer/util"
	"qmax-analyzer/util/model"
)

type discardEvent struct {
	Tile      string `json:"tile"`
	Tsumogiri bool   `json:"tsumogiri"` // 摸切；影響聽牌率估算
}

type riskReq struct {
	Hand           string `json:"hand"`            // 我的手牌+副露（同 /analyze），可省略
	Jokers         int    `json:"jokers"`          // 我手牌中的萬用牌張數（同 /analyze）
	Visible        string `json:"visible"`         // 場上看得到、不是我手牌的牌，攤平
	DoraIndicators string `json:"dora_indicators"` // 寶牌指示牌，攤平
	RoundWind      string `json:"round_wind"`      // 場風，例如 "1z"
	SelfWind       string `json:"self_wind"`       // 這家的自風

	// 以下是這家對手的資訊
	Discards       []discardEvent `json:"discards"`         // 依序
	Melds          string         `json:"melds"`            // 副露（同 /analyze 記法）
	MeldDiscardsAt []int          `json:"meld_discards_at"` // 每次副露後第一張棄牌在 discards 的 index
	NukiDora       int            `json:"nuki_dora"`        // 拔北張數
	ExtraSafe      string         `json:"extra_safe"`       // 立直後過牌/同巡振聽的額外安牌，攤平
	IsRiichi       bool           `json:"is_riichi"`
	IsIppatsu      bool           `json:"is_ippatsu"` // 立直一發巡內
	IsDealer       bool           `json:"is_dealer"`
	IsSanma        bool           `json:"is_sanma"` // 三麻：1m 指示牌的寶牌是 9m
}

type riskTileResp struct {
	Tile      string  `json:"tile"`
	Risk      float64 `json:"risk"`
	LeftCount int     `json:"left_count"`
}

type riskResp struct {
	Turns      int            `json:"turns"`
	TenpaiRate float64        `json:"tenpai_rate"`
	RonPoint   float64        `json:"ron_point"`
	Risk       []riskTileResp `json:"risk"`
	SafeTiles  []string       `json:"safe_tiles"`
	Error      string         `json:"error,omitempty"`
}

// parseMeldsOnly 借用手牌 parser 解析純副露字串。parser 要求至少一張手牌，
// 所以前面塞一張副露裡沒有的牌當假手牌（若塞的牌與副露同種，暗槓會變成第五張而被判不合法）。
func parseMeldsOnly(meldsStr string) ([]model.Meld, error) {
	if meldsStr == "" {
		return nil, nil
	}
	used, _, err := util.StrToTiles34(strings.ToLower(meldsStr))
	if err != nil {
		return nil, err
	}
	placeholder := 0
	for used[placeholder] > 0 {
		placeholder++
	}
	pi, err := util.ParseHumanTilesWithMelds(util.Mahjong[placeholder] + " # " + meldsStr)
	if err != nil {
		return nil, err
	}
	return pi.Melds, nil
}

// nakiDoraCount 估計副露者確定的寶牌數，同上游 playerInfo.doraNum()。
func nakiDoraCount(melds []model.Meld, doraList []int, nukiDora int) int {
	count := 0
	for _, meld := range melds {
		for _, t := range meld.Tiles {
			for _, d := range doraList {
				if t == d {
					count++
				}
			}
		}
		if meld.ContainRedFive {
			count++
		}
	}
	count += nukiDora
	for _, d := range doraList {
		if d == 30 { // 北是寶牌（西是指示牌）時，拔出的北再算一次
			count += nukiDora
		}
	}
	return count
}

func handleRisk(w http.ResponseWriter, r *http.Request) {
	var req riskReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(riskResp{Error: err.Error()})
		return
	}

	// 剩餘枚數 = 4 − 我的手牌與副露 − 場上可見牌
	leftTiles34 := util.InitLeftTiles34()
	if req.Hand != "" {
		handInfo, err := parseHand(req.Hand, req.Jokers)
		if err != nil {
			json.NewEncoder(w).Encode(riskResp{Error: "手牌解析失敗: " + err.Error()})
			return
		}
		for i, c := range handInfo.HandTiles34 {
			leftTiles34[i] -= c
		}
		for _, meld := range handInfo.Melds {
			for _, t := range meld.Tiles {
				leftTiles34[t]--
			}
		}
	}
	if req.Visible != "" {
		visibleTiles34, _, err := util.StrToTiles34(req.Visible)
		if err != nil {
			json.NewEncoder(w).Encode(riskResp{Error: "場況牌解析失敗: " + err.Error()})
			return
		}
		for i, c := range visibleTiles34 {
			leftTiles34[i] -= c
		}
	}
	for i, c := range leftTiles34 {
		if c < 0 {
			json.NewEncoder(w).Encode(riskResp{Error: "剩餘枚數算出負的了（" + util.Mahjong[i] + "），檢查一下 hand/visible 是否重複算了同一張牌"})
			return
		}
	}

	melds, err := parseMeldsOnly(req.Melds)
	if err != nil {
		json.NewEncoder(w).Encode(riskResp{Error: "副露解析失敗: " + err.Error()})
		return
	}

	doraTiles, _, err := util.StrToTiles34(req.DoraIndicators)
	if err != nil && req.DoraIndicators != "" {
		json.NewEncoder(w).Encode(riskResp{Error: "寶牌指示牌解析失敗: " + err.Error()})
		return
	}
	// 指示牌 -> 寶牌清單（可重複）
	var doraIndicatorTiles []int
	for i, c := range doraTiles {
		for k := 0; k < c; k++ {
			doraIndicatorTiles = append(doraIndicatorTiles, i)
		}
	}
	doraList := model.DoraList(doraIndicatorTiles, req.IsSanma)

	roundWindTile := 27
	if req.RoundWind != "" {
		t, _, err := util.StrToTile34(req.RoundWind)
		if err == nil {
			roundWindTile = t
		}
	}
	selfWindTile := 27
	if req.SelfWind != "" {
		t, _, err := util.StrToTile34(req.SelfWind)
		if err == nil {
			selfWindTile = t
		}
	}

	safeTiles34 := make([]bool, 34)
	plainDiscards := make([]int, 0, len(req.Discards))
	tenpaiRateDiscards := make([]int, 0, len(req.Discards))
	for _, d := range req.Discards {
		t, _, err := util.StrToTile34(d.Tile)
		if err != nil {
			json.NewEncoder(w).Encode(riskResp{Error: "棄牌解析失敗: " + err.Error()})
			return
		}
		safeTiles34[t] = true
		plainDiscards = append(plainDiscards, t)
		if d.Tsumogiri {
			tenpaiRateDiscards = append(tenpaiRateDiscards, ^t) // util.CalcTenpaiRate 以位元反相表示摸切
		} else {
			tenpaiRateDiscards = append(tenpaiRateDiscards, t)
		}
	}
	if req.ExtraSafe != "" {
		extraSafeTiles34, _, err := util.StrToTiles34(req.ExtraSafe)
		if err != nil {
			json.NewEncoder(w).Encode(riskResp{Error: "extra_safe 解析失敗: " + err.Error()})
			return
		}
		for i, c := range extraSafeTiles34 {
			if c > 0 {
				safeTiles34[i] = true
			}
		}
	}
	for _, meld := range melds {
		if meld.IsKan() {
			safeTiles34[meld.Tiles[0]] = true
		}
	}

	// 巡目
	turns := len(req.Discards)
	if turns > util.MaxTurns {
		turns = util.MaxTurns
	}
	if turns == 0 {
		turns = 1
	}

	// 聽牌率
	var tenpaiRate float64
	if req.IsRiichi {
		tenpaiRate = 100.0
	} else {
		meldPtrs := make([]*model.Meld, len(melds))
		for i := range melds {
			meldPtrs[i] = &melds[i]
		}
		tenpaiRate = util.CalcTenpaiRate(meldPtrs, tenpaiRateDiscards, req.MeldDiscardsAt)
		if req.IsSanma {
			tenpaiRate = util.GetTenpaiRate3(tenpaiRate)
		}
	}

	isNaki := false // 暗槓不算
	for _, meld := range melds {
		if meld.MeldType != model.MeldTypeAnkan {
			isNaki = true
		}
	}

	var ronPoint float64
	switch {
	case req.IsRiichi && req.IsIppatsu:
		ronPoint = util.RonPointRiichiIppatsu
	case req.IsRiichi:
		ronPoint = util.RonPointRiichiHiIppatsu
	case isNaki:
		ronPoint = util.RonPointOtherNakiWithDora(nakiDoraCount(melds, doraList, req.NukiDora))
	default:
		ronPoint = util.RonPointDama
	}
	if req.IsDealer {
		ronPoint *= 1.5
	}

	risk34 := util.CalculateRiskTiles34(turns, safeTiles34, leftTiles34, doraList, roundWindTile, selfWindTile).
		FixWithPoint(ronPoint)

	resp := riskResp{
		Turns:      turns,
		TenpaiRate: tenpaiRate,
		RonPoint:   ronPoint,
		Risk:       []riskTileResp{},
		SafeTiles:  []string{},
	}
	for i, v := range risk34 {
		resp.Risk = append(resp.Risk, riskTileResp{
			Tile:      util.Mahjong[i],
			Risk:      v,
			LeftCount: leftTiles34[i],
		})
	}
	for i, safe := range safeTiles34 {
		if safe {
			resp.SafeTiles = append(resp.SafeTiles, util.Mahjong[i])
		}
	}

	json.NewEncoder(w).Encode(resp)
}
