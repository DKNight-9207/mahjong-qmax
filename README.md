# Mahjong-QuickMAX

麻將平台的 WebSocket 中間人代理：錄製對局、即時顯示何切／鳴牌／危險度分析。目前僅支援雀魂。

- 雀魂協定解碼與自動更新改寫自 [MajsoulMax](https://github.com/Avenshy/MajsoulMax)（GPLv3），
  去掉了皮膚解鎖與素材替換。
- 分析引擎是 [mahjong-helper](https://github.com/EndlessCheng/mahjong-helper) 的 `util/`
  包成的本地 HTTP 服務（`analyzer/mahjong_helper/`），各平台執行檔已預先編好。
- 視窗介面的牌圖來自 [riichi-mahjong-tiles](https://github.com/FluffyStuff/riichi-mahjong-tiles)（公有領域）。

> [!CAUTION]
> 使用此工具可能會被遊戲官方判定為作弊
>
> 本項目供學習、研究為主。若有拿去打排位而導致被封帳之情形，後果須自負，作者不負擔任何責任

## 安裝

```bash
pip install -r requirements.txt
```

需使用 Python 3.10 以上。

## 使用

```bash
python main.py                                  # 啟動代理（預設 0.0.0.0:23410）
python main.py --port 23410 --host 127.0.0.1    # 指定位址
python main.py --text                           # 不用儀表板，以捲動文字顯示
python main.py gui                              # 開視窗介面，在視窗裡開始／停止監聽
python main.py gui --debug                      # 同上，並開啟開發者工具（F12），調整畫面用
python main.py replay <錄製檔>                   # 重播，印出分析結果
python main.py replay <錄製檔> --out out.log     # 同上，寫進檔案（UTF-8）
python main.py replay <牌譜> --seat 2            # 牌譜指定用哪一家的視角
python main.py review <錄製檔或牌譜>              # 決策紀錄：解析器建議 vs 實際打法，算一致率
python main.py mjai <錄製檔或牌譜>                # 匯出 mjai 事件檔（給 Mortal 等 AI 用）
```

第一次執行會產生 `config/settings.yaml`：選擇平台、錄製目錄、解析器與是否即時分析、日誌輸出，
以及各平台自己的設定。設定檔裡多出來的舊欄位會被忽略並在下次存檔時移除。

### 代理設定：

1. 瀏覽器或系統代理設成 `127.0.0.1:23410`，開 `mitm.it` 安裝 mitmproxy 的 CA 憑證。
   只裝在拿來玩麻將的瀏覽器／設定檔，不要設成系統全域信任。
2. 網頁版直接用瀏覽器代理；Steam／客戶端需另外導流（例如 Proxifier）。
3. 開一場對局，`records/<平台>/live/` 就會出現錄製檔。

### Proxifier 設定教學 (以雀魂 Steam 版為例):

Profile → Proxy Servers → Add
> Address: 127.0.0.1
> 
> Port: 23410
> 
> Protocol: HTTPS

Profile → Proxification Rules → Add
> Name: majsoul
> 
> Applications: jantama_mahjongsoul.exe
> 
> Action: Proxy HTTPS 127.0.0.1 (剛剛創建的那個)

### 雀魂

- 在用戶端點開牌譜回放，會存成 `records/majsoul/history/<uuid>.json`，可以直接重播。
- 重播牌譜時用 `majsoul.account_id`（進入對局時自動記下）找出自己是哪一家；
  還沒記錄過或想看別家視角時用 `--seat`。
- 協定定義 `qmax/platforms/majsoul/liqi.desc` 啟動時自動更新，可在 `majsoul.liqi` 關閉。
- 除錯用：把牌譜攤平成逐動作的 `.flat.jsonl`：
  `python -m qmax.platforms.majsoul.flatten_record <uuid>.json`

### 視窗介面

`python main.py gui` 開一個視窗（[pywebview](https://pywebview.flowrl.com/)，Windows 用內建的 WebView2）。
在右上角填位址與 port、按「開始監聽」才會啟動代理；版面與終端機儀表板相同，另外顯示各家的
暱稱、河與副露，日誌收在最下方。關掉視窗會停止監聽。直接執行 `python main.py` 則是終端機模式，
一啟動就監聽。

畫面在 `qmax/gui/web/`：牌面圖案占牌的比例是 `style.css` 開頭的 `--tile-face`，牌本身的大小在
`.tile.lg`（手牌）與 `.tile.sm`（其他地方）。
用 `--debug` 開啟時可以按 F12 直接改 CSS 看效果，滿意後再寫回檔案；按 F5 重新整理會重新讀取檔案
（即時對局的畫面會清空，等下一個事件才恢復）。

「回放」分頁可以一步一步看錄製檔或牌譜（監聽照常在背景進行，即時對局有新動作時「即時」分頁會亮點）：

- 上方選檔案（列出 `records/` 底下的錄製檔與牌譜，或按「其他檔案…」）
- 「⏮ 上一大步」回到這家上一次摸牌、「◀ 上一步」「下一步 ▶」、「下一大步 ⏭」到這家下一次摸牌；
  「▶ 播放」每 n 秒自動下一步；拉桿直接跳。鍵盤：← →、Shift+← →、空白鍵
- 局選單跳到「東X局 N本場」，滑鼠停在某一局上會顯示點數變動、誰和牌、幾番與役
- 牌譜可以按各家暱稱旁的攝影機圖示換成那一家的視角（錄製檔只有自己的手牌，不能換）
- 每一步都會重新分析當下的場況（何切、鳴牌、各家危險度）

### 終端機畫面

平常是 log 模式，狀態訊息逐行印出。進入對局後切到遊戲模式（終端機的備用畫面，
像 vim/less 那樣），固定版面顯示：

- 場況：局數、本場、莊家、場風/自風、寶牌指示牌、各家點數、最新動作
- 各家（左上家、中對家、右下家）：聽牌率、估計打點、安牌、危牌（★ 表示自己手上有）
- 手牌與分析：標題一律顯示向聽數；要切牌時列何切候選，打完牌後顯示進張（聽牌時顯示聽的牌、
  和率、打點）；輪到自己鳴牌時改顯示模擬結果。開局要換牌（修羅之戰、萬象修羅）時改顯示換哪幾張最好。
  一局結束到下一局開始前改顯示結算
- 警告：有警告或錯誤時才出現

對局結束後切回 log 模式，先印最終點數與每局結果（一局一行），再補印遊戲中累積的日誌。

儀表板需要真正的終端機（Windows Terminal、macOS/Linux 終端機）。輸出被導向檔案，
或在 PyCharm 執行視窗中（未勾選 Run 設定的「Emulate terminal in output console」）
會自動改用捲動文字。

## 輸出

| 路徑 | 內容 | 切檔 |
|---|---|---|
| `records/<平台>/live/<stem>.jsonl` | 對局中的所有訊息，一行一則（格式由平台決定） | 每局一份 |
| `records/majsoul/history/<uuid>.json` | 雀魂牌譜回放的原始回應 | 每份牌譜一份 |
| `logs/app/<啟動時間>.log` | 狀態訊息、警告、錯誤（一律記錄） | 每次啟動一份 |
| `logs/analyze/<stem>.log` | 解析器每次對外呼叫的紀錄 | 每局一份 |
| `logs/proxy/<啟動時間>.log` | 收發的訊息名稱、mitmproxy 內部訊息 | 每次啟動一份 |
| `logs/review/<檔名>.jsonl` | 決策紀錄（`main.py review`） | 每次執行 |
| `logs/mjai/<檔名>.mjson` | mjai 事件檔（`main.py mjai`） | 每次執行 |

`<stem>` 是 `開局時間_對局識別碼前8碼`，同一局的錄製檔與 analyze log 檔名相同。

何切／危險度的文字只顯示在畫面上，不存檔；要回頭查分析結果看 `logs/analyze/`：

```jsonc
{"endpoint": "analyze" | "risk" | "exchange" | "akochan.ai_review", "state": {場況快照}, "request": {...}, "response": {...}}
// request/response 的格式由解析器決定。mahjong-helper 失敗時 response 是
// {"error": ..., "panic": true, "stack": ...}（panic/stack 只在 Go 內部 panic 時出現）
```

### AI 解析器：akochan

除了 mahjong-helper（牌效率），也可以用 [akochan](https://github.com/critter-mj/akochan) 給建議。
akochan 是開源的麻將 AI，評估每個選擇之後的期望順位點（考慮點數狀況、別家的威脅），
四麻一般規則限定。

akochan 的使用規約只允許非公開的研究與檢討使用，也不允許和這個專案一起散布，所以要自己編譯。
這裡選擇 akochan 是為了驗證 mjai 四麻翻譯器是否正確做出轉換，並非鼓勵使用 AI 作弊。

- Windows：執行 `analyzer\akochan\build.bat`（或 `build.ps1`）。它會用 [MSYS2](https://www.msys2.org/)
  的 MinGW64 環境安裝編譯工具並編譯；沒裝 MSYS2 時會問要不要用 winget 安裝（裝在別處時加
  `-Msys2 路徑`）。執行時需要的 DLL 會複製到輸出資料夾，之後不必開 MSYS2；最後會在不含 MSYS2
  路徑的環境試跑一次，確認單獨也能啟動。akochan 計算用的執行緒數在 Windows 預設最多 4（每條約佔
  164 MB 記憶體，載入時就預留），要更多可以 `build.bat -Nprocs 6`。
- Linux：`cd analyzer/akochan && ./build.sh`，需要 `g++ make git` 與 boost 標頭檔
  （`sudo apt install g++ make git libboost-dev`）。
- macOS：先 `brew install llvm libomp boost`，再 `./build.sh`。
- Linux 實際測試過；Windows 版在 Linux 上用 MinGW 交叉編譯、wine 執行驗證過；macOS 是照 akochan
  的說明寫的。

編好後把 `config/settings.yaml` 的 `analysis.advisor` 改成 `akochan`。建議的排序與期望值來自
akochan；向聽、進張、和率等數值、危險度、13 張時的進張、換牌由 mahjong-helper 補上，表格同時
看得到兩邊。鳴牌會連「不鳴」一起評估。每個決策點計算約 0.5～5 秒（依電腦核心數）。

嫌慢可以改用 `akochan-light`：同一個 AI，換成 akochan 內建的輕量策略（手牌變化少看一層、列舉的
組合數設上限）。用一場 158 個決策點的錄製比較，計算時間平均 1.39 → 0.43 秒（最慢 6.5 → 3.8 秒），
首選和 `akochan` 相同 92%，不同時差距平均只有 0.03 期望順位點；首選落在 `akochan` 前三名的有 99%。

`python main.py review <檔案> --advisor akochan --compare mahjong-helper` 會在每個決策點同時問兩個
解析器，摘要多了兩者首選相同的比例。

### mjai 匯出

`python main.py mjai <檔案> [--seat N] [--out 路徑]` 轉成 [mjai](https://github.com/gimite/mjai) 事件檔
（一行一個事件），Mortal、mjai-reviewer 等開源麻將 AI 工具共用這個格式。

- 一家的視角：別家的配牌與摸牌寫成 `"?"`，和 AI 實際對局時看到的一樣（牌譜也是）。
- 只支援四人一般規則。三麻、修羅之戰（換牌、血戰到底）、萬象修羅（萬用牌）、暗夜之戰（暗切）
  會直接說明原因、不輸出；特殊規則依雀魂的對局設定判斷。
- 別家的暗槓只知道是哪種牌；5 的暗槓假設含一張赤5（雀魂四麻每種花色一張赤5）。
- 一炮多響時分不出每一家的點數增減，`hora` 不帶 `deltas`。

### 決策紀錄

`python main.py review <檔案> [--seat N] [--out 路徑]` 把一場跑一遍，每個決策點（何切、鳴牌、換牌）
寫一行 JSON 到 `logs/review/<檔名>.jsonl`：當時的場況、決策點的合法選項、解析器的建議、
實際怎麼做、實際的選擇排在建議的第幾。最後印出首選一致率與前三一致率：

```
決策點：何切 76、鳴牌 8、換牌 4
mahjong-helper
  何切　首選一致 75%（56/75）　前三 89%
  鳴法（只看實際有鳴的）　首選一致 100%（5/5）　前三 100%
  換牌　首選一致 25%（1/4）　前三 50%
鳴牌機會 8 次：實際不鳴 3、鳴 5、榮和 0
```

- 赤5 與 5 視為同一張；立直切牌與一般切牌視為同一個選擇。
- 暗槓、加槓、拔北、自摸、九種九牌這類選擇不在何切候選裡，不算進一致率。
- mahjong-helper 沒有評估「不鳴」，鳴牌只比較實際有鳴的那幾次用的是不是首選的鳴法。
- 一致率不等於強弱：只代表和實際打法有多接近。

## 架構

```
平台 WebSocket ─► Decoder ─► 訊息 ─┬─► GameRecorder（錄製）
                  （平台）          ├─► Platform.observe（平台的其他用途，例如存牌譜）
                                   └─► Translator ─► 通用牌局動作 ─► GameEngine ─► Frontend
                                       （平台）       game/actions.py   （場況）    （畫面）
                                                                          │  ▲
                                                               Decision   ▼  │  Advice
                                                                         Advisor（解析器）
                                                                    advice/mahjong_helper.py
```

只有 `qmax/platforms/<平台>/` 知道平台的協定；引擎、分析、前端只認通用牌局動作與通用牌碼
（`qmax/game/`）。同樣地，只有 `qmax/advice/<解析器>.py` 知道解析器的輸入輸出格式；
引擎與前端只認 `advice/model.py` 的共同格式。重播走同一條路，只是訊息來自檔案（`Platform.load_replay`）。

即時對局時，代理的 hook 只做解碼、錄製、轉譯（每則不到 1ms），之後交給背景的分析執行緒
依序處理就返回，封包轉發不會等分析。分析跟不上時（例如分析器卡住），如果同一家的下一次打牌
或這局的結束已經在排隊，就略過這次的危險度分析；場況與何切、鳴牌分析照常逐則處理。

```
main.py                 進入點（argparse）
qmax/
  config.py             config/settings.yaml 讀寫
  logs.py               loguru 輸出分流、每局切檔
  proxy.py              mitmproxy addon；ProxyServer 在背景執行緒跑代理
  recorder.py           錄製檔
  app.py                App：設定、平台、代理的啟動／停止、重播（終端機與視窗共用）
  pipeline.py           訊息 → 轉譯器 → 引擎；即時對局用背景執行緒
  review.py             決策紀錄（main.py review）
  mjai/
    convert.py          通用牌局動作 → mjai 事件
    export.py           錄製檔或牌譜 → .mjson（main.py mjai）
  replay.py             重播（一次跑完整場）
  replay_session.py     GUI 回放：跳到任何一步、換視角
  game/
    tiles.py            通用牌碼、副露記法
    yaku.py             通用役名
    actions.py          平台交給引擎的通用牌局動作
  platforms/
    base.py             Platform / Decoder / Translator 介面
    majsoul/            雀魂：協定解碼、轉譯、牌譜、協定更新
  advice/
    model.py            決策點（Decision）、建議（Advice、Candidate、Move）、危險度（Danger）
    base.py             Advisor 介面（解析器）
    decision_log.py     決策紀錄：記下建議與實際打法、算排名
    combined.py         主解析器＋輔助解析器（補主解析器沒有的分析與欄位）
    child_process.py    跟著主程式一起結束的子行程（另開程式的解析器共用）
    mahjong_helper/     mahjong-helper 解析器
      advisor.py        轉接：場況 → Go 的請求，Go 的回應 → Advice
      server.py         analyzer-server 子行程：找執行檔、啟動、檢查版本
      api.py            analyzer-server 的 HTTP API（analyze / risk / exchange）
    akochan/            akochan 解析器
      advisor.py        轉接：牌局動作 → mjai 事件，akochan 的評估 → Advice
      server.py         qmax_akochan 子行程
  engine/
    state.py            RoundState：場況紀錄
    engine.py           GameEngine：處理牌局動作、在決策點問解析器、通知前端
  frontend/
    events.py           事件內容（dataclass，可直接轉 JSON）
    base.py             Frontend 介面
    zh.py               中文顯示用字串
    text.py             捲動文字前端
    dashboard.py        終端機儀表板：log 模式／遊戲模式
    dashboard_view.py   儀表板的畫面狀態與繪製
  gui/
    window.py           開視窗；GuiApi 把 App 的指令開放給網頁
    frontend.py         WebFrontend：事件轉成 JSON 推給網頁
    web/                畫面（HTML/CSS/JS）與牌圖
analyzer/               解析器的資源檔，一個解析器一個資料夾（程式在 qmax/advice/<同名>/）
  mahjong_helper/
    go/                 analyzer-server 的 Go 原始碼（util/ 來自 mahjong-helper）
    bin/                五個平台的執行檔
    build.sh            重新編譯
  akochan/
    qmax_akochan.cpp    把 akochan 的評估包成一行請求、一行回應的程式
    tactics_light.json  akochan-light 用的策略設定
    build.sh            下載並編譯 akochan 與 qmax_akochan（輸出在 akochan/，不進版本控制）
    build.bat / .ps1    Windows：用 MSYS2 執行 build.sh
```

### 新增平台

在 `qmax/platforms/<名稱>/` 實作 `Platform`（見 `platforms/base.py`）並加進
`platforms/__init__.py` 的 `PLATFORMS`：

- `Decoder`：把 WebSocket 訊框解成訊息（dict，至少有 `"method"`）
- `Translator`：把訊息轉成 `qmax/game/actions.py` 的動作；牌碼轉成通用牌碼，役轉成 `game/yaku.py` 的名稱
- 判斷對局開始／結束、讀取重播檔、平台自己的預設設定

### 新增解析器

在 `qmax/advice/` 實作 `Advisor`（見 `advice/base.py`），並加進 `advice/__init__.py` 的 `ADVISORS`，
設定檔的 `analysis.advisor` 就能選它。程式其他地方只透過 `open_advisor(名稱)` 取得解析器，
不知道背後是子行程、載入的模型還是遠端服務：

- `open(on_call)`（classmethod）／`close()`：啟動與釋放。怎麼啟動由解析器自己決定；
  `on_call` 是每次對外呼叫的原始請求與回應，寫進 `logs/analyze/`。
- `advise(decision, state)`：決策點（`Decision`：何切、鳴牌、換牌，或 13 張時的目前狀況）
  回傳 `Advice`：由好到壞的候選，每個候選是一個選擇（`Move`）加上解析器算得出的數值。
  `Candidate` 列出了 mahjong-helper（向聽、進張、和率、打點…）與 AI（機率、期望值）會用到的欄位，
  沒有的留 `None`；前端看哪些欄位有值決定顯示哪些欄。
- `observe(action, state)`：每個牌局動作之後通知。吃事件流、自己記狀態的解析器（例如 AI）用；
  收到 `GameStarted` 要重設狀態（GUI 回放每次跳轉都從對局開頭重跑）。
- `danger(seat, state)`：某一家對自己的危險度，不支援就回傳 `None`。
- 失敗時丟 `AdvisorError`（`rejected` / `internal` / `unreachable`）。

要比較兩個解析器，把另一個放進 `DecisionLog` 的 `extras`，每個決策點會各問一次，
排名一起寫進決策紀錄。

### 前端介面

引擎不直接輸出文字，而是呼叫 `qmax.frontend.Frontend` 的方法通知事件：

| 類別 | 方法 |
|---|---|
| 日誌 | `info` `warning` `error` |
| 對局流程 | `game_start` `round_start` `round_end` `game_over` |
| 牌桌動作 | `draw` `hand_update` `dora_update` `discard` `call` `kan` `nuki` `exchange_tiles` `win` `operation` |
| 分析結果 | `hand_analysis` `exchange_analysis` `call_analysis` `risk_analysis` |

每個方法收到一個 `qmax/frontend/events.py` 裡的 dataclass（日誌是一段文字；分析結果裡是
`advice/model.py` 的 `Advice`、`Danger`），
`dataclasses.asdict()` 後可直接送給 GUI。事件與平台無關。

即時對局時，牌桌與分析事件來自背景的分析執行緒，日誌則可能來自任何執行緒，
所以前端的方法可能同時被呼叫（儀表板用一把鎖讓畫面狀態一次只被一邊讀寫）。

日誌由後端負責：所有狀態訊息都會寫進 `logs/app/`，再依等級轉給前端的
`info`/`warning`/`error`；前端怎麼顯示、甚至不顯示，都不影響日誌檔。
前端處理某個事件時出錯，只會記錄在 app log，後端照常繼續。

解析器沒有回應（逾時）時記錯誤並暫停分析到下一局；行程已經結束就不再分析。
兩種情況下牌桌事件照常通知前端。

## mahjong-helper 解析器（analyzer-server）

除錯時可以直接呼叫 Go 的 HTTP API：

```python
from qmax.advice.mahjong_helper.server import start_server

with start_server() as api:
    api.analyze("123456789m 45s", visible="6s 6s")
    api.risk(discards=[{"tile": "1z", "tsumogiri": False}], hand="123456789m 45s", is_riichi=True)
```

欄位說明見 `qmax/advice/mahjong_helper/api.py` 與 `analyzer/mahjong_helper/go/analyze.go`、`risk.go`。
錯誤一律丟出 `AnalyzerError`；Go 端 panic 時 `is_panic=True`，`stack` 是 Go 的呼叫堆疊。
程式其他地方不直接呼叫這裡，而是透過 `open_advisor("mahjong-helper")`。

修改 Go 程式後：

```bash
cd analyzer/mahjong_helper && ./build.sh v0.9.0
```

並把 `qmax/advice/mahjong_helper/server.py` 的 `EXPECTED_VERSION` 改成相同版本號。

## 已知限制

- 目前僅支援雀魂平台，且尚不支援通過網址下載分析。
- 手牌有萬用牌（雀魂萬象修羅的百搭）時，何切只算向聽與進張（精確值），沒有改良、和率、打點與役。
- 換牌建議不考慮換入的牌（當成沒用的牌），也不考慮換給誰。
- 目前尚不相容赤壁之戰。因為赤壁採用非標準日麻役種。
- 斷線重連時，重連前的動作不會補進分析。
- macOS 上 Python 被強制結束時，解析器的子行程不會自動關閉。
- akochan 不支援三麻與特殊規則（換牌、萬用牌、血戰到底、暗切），這些對局自動改用 mahjong-helper。
- akochan 計算耗時較長，不一定能用於即時分析。
- mjai 沒找到三麻規範，因此 mjai 只支援四麻

## License

GPLv3（沿用上游 MajsoulMax，見 `LICENSE`）。
