// 畫面狀態與繪製。Python 端（qmax/gui/frontend.py）以 qmax.receive(方法名, 事件) 推送即時對局的事件，
// 事件內容同 qmax/frontend/events.py；指令與回放走 window.pywebview.api（qmax/gui/window.py 的 GuiApi）。
// 回放跳到某一步時，向 Python 要「重建那一步所需的事件」，套用到一份全新的畫面狀態。
"use strict";

const MAX_CANDIDATES = 8;
const MAX_DANGER = 8;
const MAX_LOG = 300;

// 牌圖：tiles/（FluffyStuff/riichi-mahjong-tiles，公有領域），牌面 Front.svg 上疊花色圖
const SUIT_FILE = { m: "Man", p: "Pin", s: "Sou" };
const HONOR_FILE = {
  "1z": "Ton", "2z": "Nan", "3z": "Shaa", "4z": "Pei", "5z": "Haku", "6z": "Hatsu", "7z": "Chun",
  jk: "Joker",  // 萬用牌（百搭），這個專案自己畫的
};

let labels = null;
let api = null;
const pending = [];

// 畫面狀態。即時對局與回放各有一份，view 指向目前畫在畫面上的那一份。
function newView() {
  return {
    selfSeat: 0,
    numPlayers: 4,
    names: [],  // 依座位的暱稱
    round: null,
    scores: [],
    dora: [],
    lastAction: "",
    hand: [],
    melds: [],
    drawn: null,
    operation: null,
    handAnalysis: null,
    exchangeAnalysis: null,
    callAnalysis: null,
    risks: {},
    riichi: new Set(),
    rivers: [[], [], [], []],  // 依座位：{tile, tsumogiri, riichi, taken}
    openMelds: [[], [], [], []],  // 依座位：{kind, tiles}；自己的副露另外以 hand_update 的 melds 為準
    nuki: [0, 0, 0, 0],
    roundResult: null,
  };
}

const liveView = newView();
let view = liveView;
let mode = "live";  // "live" | "replay"
let liveUnseen = false;  // 在回放分頁時，即時對局有新動作
let proxy = { listening: false, host: "", port: 0 };
const logs = [];

// ---- 接收事件 ---------------------------------------------------------------

const handlers = {
  game_start(e) {
    Object.assign(view, { selfSeat: e.self_seat, numPlayers: e.num_players, names: e.player_names, round: null, roundResult: null });
  },
  round_start(e) {
    Object.assign(view, {
      ...newView(), names: view.names,
      selfSeat: e.self_seat, numPlayers: e.num_players, round: e, scores: e.scores.slice(),
      dora: e.dora_indicators.slice(),
    });
  },
  round_end(e) {
    view.scores = e.scores.slice();
    view.roundResult = e;
    view.operation = view.callAnalysis = null;
    view.lastAction = roundHeadline(e);
  },
  game_over(e) { view.lastAction = e.reason === "finished" ? "對局結束" : "已離桌"; },
  draw(e) {
    view.drawn = e.tile;
    view.operation = view.callAnalysis = null;
  },
  hand_update(e) { view.hand = e.hand; view.melds = e.melds; },
  dora_update(e) { view.dora = e.dora_indicators; },
  discard(e) {
    view.operation = view.callAnalysis = null;
    if (e.riichi) view.riichi.add(e.seat);
    if (e.seat === view.selfSeat) { view.drawn = null; view.handAnalysis = null; }
    view.rivers[e.seat].push({ tile: e.tile, tsumogiri: e.tsumogiri, riichi: e.riichi, taken: false });
    const flags = (e.tsumogiri ? "（摸切）" : "") + (e.riichi ? "（立直）" : "");
    view.lastAction = `${seatName(e.seat)} 切 ${tileName(e.tile)}${flags}`;
  },
  call(e) {
    if (e.seat === view.selfSeat) view.operation = null;
    const river = view.rivers[e.from_seat];
    if (river.length) river.at(-1).taken = true;
    view.openMelds[e.seat].push({ kind: e.kind, tiles: e.tiles });
    view.lastAction = `${seatName(e.seat)} ${labels.options[e.kind]} ${e.tiles.map(tileName).join(" ")}`;
  },
  kan(e) {
    const melds = view.openMelds[e.seat];
    if (e.kind === "kakan") {
      const pon = melds.find((m) => m.kind === "pon" && sameTile(m.tiles[0], e.tile));
      if (pon) Object.assign(pon, { kind: "kakan", tiles: [...pon.tiles, e.tile] });
    } else {
      melds.push({ kind: "ankan", tiles: [e.tile, e.tile, e.tile, e.tile] });
    }
    view.lastAction = `${seatName(e.seat)} ${labels.options[e.kind]} ${tileName(e.tile)}`;
  },
  nuki(e) {
    view.nuki[e.seat] += 1;
    view.lastAction = `${seatName(e.seat)} 拔北`;
  },
  exchange_tiles(e) {
    view.operation = view.callAnalysis = view.exchangeAnalysis = null;
    view.lastAction = `換牌：換出 ${e.out_tiles.map(tileName).join(" ")}，換入 ${e.in_tiles.map(tileName).join(" ")}`;
  },
  win(e) { view.lastAction = winLine(e.result); },
  operation(e) { view.operation = e; },
  hand_analysis(e) { view.handAnalysis = e; view.callAnalysis = null; },
  exchange_analysis(e) { view.exchangeAnalysis = e; },
  call_analysis(e) { view.callAnalysis = e; },
  risk_analysis(e) { view.risks[e.seat] = e; },
};

/** 把事件套用到 target（handlers 裡的 view 與座位名稱都以 target 為準）。 */
function applyTo(target, method, event) {
  const handler = handlers[method];
  if (!handler) return;
  const shown = view;
  view = target;
  try { handler(event); } finally { view = shown; }
}

let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; render(); });
}

window.qmax = {
  /** 即時對局的事件（qmax/gui/frontend.py）。 */
  receive(method, event) {
    if (!labels) { pending.push([method, event]); return; }
    if (method === "log") {
      logs.push(event);
      if (logs.length > MAX_LOG) logs.shift();
    } else if (method === "proxy_status") {
      proxy = event;
    } else {
      applyTo(liveView, method, event);
      if (mode !== "live") liveUnseen = true;
    }
    scheduleRender();
  },
};

// ---- 名稱與格式 ---------------------------------------------------------------

function seatName(seat) {
  const names = view.numPlayers === 3 ? labels.seats3 : labels.seats4;
  const rel = (seat - view.selfSeat + view.numPlayers) % view.numPlayers;
  return names[rel] ?? `座位${seat}`;
}

/** 由左到右同遊戲畫面：上家、對家、下家，自家最後。 */
function displayOrder() {
  const order = [];
  for (let rel = view.numPlayers - 1; rel >= 0; rel--) order.push((view.selfSeat + rel) % view.numPlayers);
  return order.slice(0, -1).concat(view.selfSeat);
}

const tileName = (t) => labels.tiles[t] ?? t;
const shantenName = (n) => labels.shanten[n] ?? `${n}向聽`;
const signed = (n) => (n > 0 ? `+${n}` : n < 0 ? `${n}` : "±0");
const sameTile = (a, b) => a.replace("0", "5") === b.replace("0", "5");

function roundName(r) {
  return `${labels.winds[r.round_wind] ?? r.round_wind}${r.kyoku + 1}局 ${r.honba}本場`;
}

function roundHeadline(e) {
  if (e.reason === "abortive_draw") {
    const who = e.abortive_seat != null ? `（${seatName(e.abortive_seat)}）` : "";
    return `途中流局：${labels.abortive[e.abortive_kind ?? "unknown"]}${who}`;
  }
  if (e.reason === "exhaustive_draw") {
    const tenpai = e.tenpai_seats.map(seatName).join("、") || "全員未聽";
    return `${e.nagashi_mangan ? "流局滿貫" : "荒牌流局"}　聽牌：${tenpai}`;
  }
  return "和了";
}

const DORA_YAKU = new Set(["dora", "aka_dora", "ura_dora", "nuki_dora"]);

function yakuText(yaku, yakuman) {
  return yaku
    .filter((y) => !(DORA_YAKU.has(y.name) && y.han === 0))
    .map((y) => {
      const name = labels.yaku[y.name] ?? y.name;
      if (yakuman && !DORA_YAKU.has(y.name)) return y.han > 1 ? `${name}×${y.han}` : name;
      return `${name}${y.han}`;
    })
    .join("、");
}

const winSize = (w) => (w.yakuman ? (w.han > 1 ? `${w.han}倍役滿` : "役滿") : `${w.han}番${w.fu}符`);

function winLine(w) {
  const how = w.zimo ? "自摸" : w.deal_in_seat != null ? `榮和 ${seatName(w.deal_in_seat)}` : "榮和";
  const points = w.points ? ` ${w.points}點` : "";
  return `${seatName(w.seat)} ${how} ${tileName(w.tile)}　${winSize(w)}${points}`;
}

function waitsText(c) {
  return `${(c.waits ?? []).length}種 ${c.wait_count ?? 0}枚`;
}

function pointText(c, isNaki) {
  return isNaki ? `默聽 ${Math.round(c.dama_point)}` : `立直 ${Math.round(c.riichi_point)}／默聽 ${Math.round(c.dama_point)}`;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
}

// ---- 牌 -----------------------------------------------------------------------

function tileFile(code) {
  if (HONOR_FILE[code]) return HONOR_FILE[code];
  if (!SUIT_FILE[code[1]]) return null;
  return code[0] === "0" ? `${SUIT_FILE[code[1]]}5-Dora` : `${SUIT_FILE[code[1]]}${code[0]}`;
}

/** classes：額外的 class（sm/lg 尺寸、河裡的 tsumogiri/taken/sideways）。 */
function tile(code, classes = "", title = "") {
  const name = escapeHtml(tileName(code) + title);
  const file = tileFile(code);
  const face = file
    ? `<img src="tiles/${file}.svg" alt="${name}" draggable="false">`
    : `<span class="text">${escapeHtml(code)}</span>`;
  return `<span class="tile ${classes}" title="${name}">${face}</span>`;
}

const tileBack = (classes = "") => `<span class="tile back ${classes}" title="暗槓"></span>`;
const tiles = (codes, classes = "") => `<span class="tiles">${codes.map((c) => tile(c, classes)).join("")}</span>`;

const SUIT_ORDER = { m: 0, p: 1, s: 2, z: 3 };
function tileSortKey(t) {
  const rank = t[0] === "0" ? 5.5 : /\d/.test(t[0]) ? Number(t[0]) : 99;
  return (SUIT_ORDER[t[1]] ?? 9) * 100 + rank;
}

/** 副露記法（"555z"、暗槓 "4444M"）轉成 {kind, tiles}。 */
function parseMeld(meld) {
  const suit = meld.at(-1);
  return { kind: suit === suit.toUpperCase() ? "ankan" : "open", tiles: [...meld.slice(0, -1)].map((d) => d + suit.toLowerCase()) };
}

function meldHtml(m) {
  if (m.kind === "ankan") return `<span class="tiles">${tileBack("sm")}${tile(m.tiles[1], "sm")}${tile(m.tiles[2], "sm")}${tileBack("sm")}</span>`;
  return tiles(m.tiles, "sm");
}

function riverHtml(seat) {
  const river = view.rivers[seat];
  if (!river.length) return `<span class="muted">—</span>`;
  return `<div class="river">${river.map((d) => {
    const classes = ["sm", d.tsumogiri ? "tsumogiri" : "", d.taken ? "taken" : "", d.riichi ? "sideways" : ""].join(" ");
    const note = (d.tsumogiri ? "（摸切）" : "") + (d.riichi ? "（立直）" : "") + (d.taken ? "（被鳴）" : "");
    return tile(d.tile, classes, note);
  }).join("")}</div>`;
}

/** 河與副露（含拔北）。melds：{kind, tiles} 的陣列。 */
function tableRows(seat, melds) {
  const extras = melds.map(meldHtml);
  if (view.nuki[seat]) extras.push(`<span class="nuki">${tile("4z", "sm")}<span class="muted">×${view.nuki[seat]}</span></span>`);
  return `<div><div class="row-label">河</div>${riverHtml(seat)}</div>
    ${extras.length ? `<div class="melds"><span class="row-label">副露</span>${extras.join("")}</div>` : ""}`;
}

// ---- 繪製 -----------------------------------------------------------------------

function render() {
  view = mode === "live" ? liveView : replay.view;
  renderTabs();
  renderBar();
  renderReplayBar();
  renderOpponents();
  renderMine();
  renderLog();
}

function renderTabs() {
  for (const tab of document.querySelectorAll(".tabs [data-mode]")) {
    tab.setAttribute("aria-selected", String(tab.dataset.mode === mode));
  }
  document.getElementById("tab-live").classList.toggle("unseen", liveUnseen);
}

function renderBar() {
  const r = view.round;
  document.getElementById("round").innerHTML = r
    ? `<h1>${roundName(r)}</h1>
       <span class="facts">莊家 ${seatName(r.dealer_seat)}　自風 ${labels.winds[r.self_wind] ?? ""}${r.kyotaku ? `　供託 ${r.kyotaku}` : ""}</span>
       <span class="dora">寶牌指示牌 ${view.dora.length ? tiles(view.dora, "sm") : "尚未翻開"}</span>`
    : "";

  const form = document.getElementById("listen");
  const { listening, host, port } = proxy;
  form.classList.toggle("on", listening);
  const status = document.getElementById("status");
  status.classList.toggle("on", listening);
  status.textContent = listening ? `監聽中 ${host}:${port}` : "未監聽";
  document.getElementById("toggle").textContent = listening ? "停止監聽" : "開始監聽";
}

/** 座位標題：上家／對家…加上暱稱；回放牌譜時其他家旁邊有換視角的按鈕。 */
function seatHeading(seat) {
  const nick = view.names[seat];
  const camera = mode === "replay" && replay.meta?.seat_selectable && seat !== view.selfSeat
    ? `<button type="button" class="camera" data-seat="${seat}" title="換成${escapeHtml(nick ?? seatName(seat))}的視角" aria-label="換成這家的視角">${CAMERA_ICON}</button>`
    : "";
  return `<h2>${seatName(seat)}</h2>${nick ? `<span class="nick">${escapeHtml(nick)}</span>` : ""}${camera}`;
}

const CAMERA_ICON = `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/>
  <circle cx="12" cy="13" r="3.5"/></svg>`;

function renderOpponents() {
  const box = document.getElementById("opponents");
  if (!view.round) { box.innerHTML = ""; return; }
  const seats = displayOrder().slice(0, -1);
  box.style.setProperty("--count", seats.length);
  box.innerHTML = seats.map(opponentCard).join("");
}

function opponentCard(seat) {
  const r = view.risks[seat];
  const riichi = view.riichi.has(seat);
  let body = "";
  if (r?.unsupported_tiles?.length) body = `<p class="muted">手牌含分析器不支援的牌，略過</p>`;
  else if (r?.error) body = `<p class="warn">分析失敗：${escapeHtml(r.error.message)}</p>`;
  else if (r?.danger) body = riskBody(r.danger);
  return `<article class="seat ${riichi ? "riichi" : ""}">
    <header>${seatHeading(seat)}${riichi ? `<span class="badge">立直</span>` : ""}
      <span class="score">${view.scores[seat] ?? ""}</span></header>
    ${tableRows(seat, view.openMelds[seat])}
    ${body}
  </article>`;
}

function riskBody(res) {
  const danger = res.tiles.filter((t) => t.risk > 0).sort((a, b) => b.risk - a.risk).slice(0, MAX_DANGER);
  const items = danger.map((t) => {
    const heat = t.risk >= 10 ? "hot" : t.risk >= 5 ? "warm" : "";
    return `<li class="${t.in_hand ? "in-hand" : ""}">${tile(t.tile, "sm")}<span class="v ${heat}">${t.risk.toFixed(1)}</span></li>`;
  });
  return `<div class="stats"><span>巡 <b>${res.turns}</b></span><span>聽牌率 <b>${Math.round(res.tenpai_rate)}%</b></span>
      <span>打點 <b>${Math.round(res.ron_point)}</b></span></div>
    <div><div class="row-label">安牌</div>${res.safe_tiles.length ? tiles(res.safe_tiles, "sm") : `<span class="muted">沒有</span>`}</div>
    <div><div class="row-label">危牌（★ 自己手上有）</div>${items.length ? `<ul class="danger">${items.join("")}</ul>` : `<span class="muted">沒有</span>`}</div>`;
}

function renderMine() {
  const box = document.getElementById("mine");
  if (!view.round) { box.innerHTML = mode === "live" ? liveEmptyState() : replayEmptyState(); return; }

  const hand = view.hand.slice();
  if (view.drawn && hand.includes(view.drawn)) hand.splice(hand.lastIndexOf(view.drawn), 1);
  hand.sort((a, b) => tileSortKey(a) - tileSortKey(b));

  const parts = [
    mineHeader(),
    `<div class="hand">${tiles(hand, "lg")}${view.drawn ? `<span class="drawn">${tile(view.drawn, "lg")}</span>` : ""}</div>`,
    tableRows(view.selfSeat, view.melds.map(parseMeld)),
  ];
  if (view.operation) parts.push(`<div class="prompt">輪到你決定：${optionsText(view.operation.options)}</div>`);
  if (view.lastAction) parts.push(`<div class="muted">最新：${escapeHtml(view.lastAction)}</div>`);
  parts.push(analysisBlock());
  box.innerHTML = parts.join("");
}

function liveEmptyState() {
  if (!proxy.listening) {
    const port = document.getElementById("port").value || "23410";
    return `<div class="empty">按右上角的 <b>開始監聽</b>，再把玩麻將的瀏覽器代理設成這台電腦的
      <b>127.0.0.1:${escapeHtml(port)}</b>。<br>第一次使用要先在那個瀏覽器開 mitm.it 安裝憑證。</div>`;
  }
  return `<div class="empty">監聽中，進入對局後這裡會顯示手牌與分析。</div>`;
}

function replayEmptyState() {
  if (replay.error) return `<div class="empty warn">${escapeHtml(replay.error)}</div>`;
  if (replay.loading) return `<div class="empty">讀取中…</div>`;
  if (replay.meta) return `<div class="empty">按 <b>下一步</b> 或 <b>播放</b> 開始。</div>`;
  return `<div class="empty">在上方選一個錄製檔或牌譜開始回放。<br>
    雀魂在用戶端點開牌譜回放時會自動存檔；牌譜可以換成任何一家的視角。</div>`;
}

function mineHeader() {
  const ex = view.exchangeAnalysis?.advice;
  const a = view.handAnalysis?.advice;
  const shanten = ex ? ex.shanten : a ? a.shanten : null;
  const note = ex ? `換牌：選 ${view.exchangeAnalysis.count} 張換出` : a ? notesText(a) : "";
  const engine = (view.roundResult ? null : view.callAnalysis?.advice ?? ex ?? a)?.engine;  // 下面顯示的是誰的建議
  return `<header>${seatHeading(view.selfSeat)}
    ${shanten != null ? `<span class="shanten ${shanten <= 0 ? "tenpai" : ""}">${shanten < 0 ? "和了" : shantenName(shanten)}</span>` : ""}
    ${note ? `<span class="note">${note}</span>` : ""}
    ${engine ? `<span class="engine" title="給建議的解析器">${escapeHtml(engine)}</span>` : ""}
    ${view.riichi.has(view.selfSeat) ? `<span class="badge">立直</span>` : ""}
    <span class="score">${view.scores[view.selfSeat] ?? ""}</span></header>`;
}

function optionsText(options) {
  return options
    .filter((o) => o.kind !== "discard")
    .map((o) => {
      const label = labels.options[o.kind] ?? o.kind;
      const sets = o.tile_sets.filter((s) => s.length).map((s) => s.map(tileName).join(" ")).join("／");
      return sets ? `${label}（${sets}）` : label;
    })
    .join("、");
}

function analysisBlock() {
  if (view.roundResult) return resultBlock(view.roundResult);
  if (view.exchangeAnalysis) return exchangeBlock(view.exchangeAnalysis);
  if (view.callAnalysis) return callBlock(view.callAnalysis);
  const a = view.handAnalysis;
  if (!a) return "";
  if (a.unsupported_tiles.length) return `<p class="muted">手牌含分析器不支援的牌，略過分析</p>`;
  if (a.error) return `<p class="warn">分析失敗：${escapeHtml(a.error.message)}</p>`;
  if (a.advice.kind === "discard") return candidatesTable(a.advice, a.is_naki);
  return currentHand(a.advice.candidates[0], a.is_naki);
}

const notesText = (advice, skip = []) => advice.notes.filter((n) => !skip.includes(n)).map((n) => labels.notes[n] ?? n).join("；");
/** 有沒有和率、打點這些細節；萬用牌模式或只算進張的解析器沒有。 */
const hasDetails = (c) => c.agari_rate != null;

/** 一個選擇（Move）怎麼顯示：切的牌、換出的牌、鳴法。 */
function moveHtml(m) {
  if (!m) return "—";
  if (m.kind === "pass") return "不鳴";
  if (m.kind === "discard") return tile(m.tiles[0], "sm");
  if (m.kind === "riichi") return `立直 ${tile(m.tiles[0], "sm")}`;
  if (m.kind === "exchange") return tiles(m.tiles, "sm");
  const label = labels.options[m.kind] ?? m.kind;
  return `${label} ${m.meld ? meldHtml(parseMeld(m.meld)) : tiles(m.tiles, "sm")}`;
}

/** AI 類解析器的評估（期望值、機率）與放銃率；只顯示有值的欄。 */
function aiCells(advice) {
  const has = (key) => advice.candidates.some((c) => c[key] != null);
  const cols = [
    ["value", "期望", (v) => (v >= 0 ? "+" : "") + v.toFixed(2)],
    ["probability", "機率", (v) => (v * 100).toFixed(1) + "%"],
    ["deal_in_rate", "放銃", (v) => v.toFixed(1) + "%"],
  ].filter(([key]) => has(key));
  return {
    head: cols.map(([, label]) => `<th>${label}</th>`).join(""),
    row: (c) => cols.map(([key, , fmt]) => `<td class="num">${c[key] != null ? fmt(c[key]) : ""}</td>`).join(""),
    text: (c) => cols.filter(([key]) => c[key] != null).map(([key, label, fmt]) => `${label} ${fmt(c[key])}`).join("　"),
  };
}

function candidatesTable(advice, isNaki) {
  const ai = aiCells(advice);
  const hasShanten = advice.candidates.some((c) => c.shanten != null);
  const details = advice.candidates.some(hasDetails);
  const rows = advice.candidates.slice(0, MAX_CANDIDATES).map((c, i) => {
    const head = `<tr class="${i === 0 ? "best" : ""}"><td>${moveHtml(c.move)}</td>${ai.row(c)}`;
    if (!hasShanten) return `${head}</tr>`;
    if (c.shanten == null) return `${head}<td></td><td></td><td></td>${details ? "<td></td>" : ""}</tr>`;
    const base = `${head}<td>${shantenName(c.shanten)}</td><td class="num">${waitsText(c)}</td>`;
    if (!details) return `${base}<td>${tiles((c.waits ?? []).map((w) => w.tile), "sm")}</td></tr>`;
    let yaku = (c.yaku ?? []).map((y) => labels.yaku[y] ?? y).join("、");
    if (!yaku && isNaki && c.shanten >= 0 && c.shanten <= 2) yaku = `<span class="warn">無役</span>`;
    const furiten = c.furiten ? `<span class="warn">可能振聽</span>` : "";
    const detail = !hasDetails(c) ? ""
      : c.shanten === 0
        ? `和率 ${c.agari_rate.toFixed(1)}%　${pointText(c, isNaki)}`
        : `${c.improve_count ? `改良 ${c.improve_waits.toFixed(1)}（${c.improve_count}種）　` : ""}前進後 ${c.next_waits.toFixed(2)}`;
    return `${base}<td>${detail}</td><td class="yaku">${yaku} ${furiten}</td></tr>`;
  });
  const tail = !hasShanten ? "" : details ? "<th>切後</th><th>進張</th><th></th><th>役</th>" : "<th>切後</th><th>進張</th><th>進張牌</th>";
  const head = `<tr><th>切</th>${ai.head}${tail}</tr>`;
  return `<table class="analysis">${head}${rows.join("")}</table>`;
}

function currentHand(c, isNaki) {
  if (!c) return "";
  const waits = tiles(c.waits.map((w) => w.tile), "sm");
  if (c.shanten === 0) {
    const extra = hasDetails(c) ? `　和率 ${c.agari_rate.toFixed(1)}%　${pointText(c, isNaki)}` : "";
    return `<div><div class="row-label muted">聽牌（共 ${c.wait_count} 枚${extra}）</div>${waits}</div>`;
  }
  return `<div><div class="row-label muted">進張 ${waitsText(c)}</div>${waits}</div>`;
}

function exchangeBlock(e) {
  if (e.unsupported_tiles.length) return `<p class="muted">手牌含分析器不支援的牌，略過換牌分析</p>`;
  if (e.error) return `<p class="warn">換牌分析失敗：${escapeHtml(e.error.message)}</p>`;
  const ai = aiCells(e.advice);
  const rows = e.advice.candidates.slice(0, MAX_CANDIDATES).map((c, i) => `<tr class="${i === 0 ? "best" : ""}">
      <td>${moveHtml(c.move)}</td><td>${shantenName(c.shanten)}</td><td class="num">${waitsText(c)}</td>
      <td>${tiles(c.waits.map((w) => w.tile), "sm")}</td>${ai.row(c)}</tr>`);
  const notes = notesText(e.advice);
  return `<table class="analysis"><tr><th>換出</th><th>保留後</th><th>進張</th><th>進張牌</th>${ai.head}</tr>${rows.join("")}</table>
    ${notes ? `<p class="muted">${escapeHtml(notes)}</p>` : ""}`;
}

function callBlock(e) {
  if (e.unsupported_tiles.length) return `<p class="muted">手牌含分析器不支援的牌，略過鳴牌模擬</p>`;
  if (e.error) return `<p class="warn">鳴牌模擬失敗：${escapeHtml(e.error.message)}</p>`;
  const ai = aiCells(e.advice);
  const notes = notesText(e.advice);
  return (notes ? `<p class="note muted">${escapeHtml(notes)}</p>` : "") + e.advice.candidates.map((c, i) => {
    const score = ai.text(c);
    const best = i === 0 && e.advice.candidates.length > 1 ? `<span class="pick">首選</span>` : "";
    const title = `${moveHtml(c.move)}${score ? `<span class="muted">${score}</span>` : ""}${best}`;
    let body;
    if (c.move.kind === "pass") body = "";
    else if (c.unavailable === "suit_mismatch") body = `<p class="muted">花色對不起來，略過</p>`;
    else if (c.unavailable === "tiles_not_in_hand") body = `<p class="muted">手牌裡找不到這幾張，略過</p>`;
    else if (!c.followup) body = "";
    else if (c.followup.kind === "status") body = currentHand(c.followup.candidates[0], true);  // 大明槓後
    else body = candidatesTable(c.followup, true);
    return `<div class="call-option"><h3>${title}</h3>${body}</div>`;
  }).join("");
}

function winsHtml(e) {
  return e.wins.map((w) => {
    const yaku = yakuText(w.yaku, w.yakuman);
    return `<p class="win">${escapeHtml(winLine(w))}${yaku ? `<br><span class="muted">${escapeHtml(yaku)}</span>` : ""}</p>`;
  }).join("");
}

function scoreRows(e) {
  return displayOrder().filter((s) => s < e.scores.length).map((s) => {
    const d = e.delta_scores[s];
    const nick = view.names[s] ? ` <span class="nick">${escapeHtml(view.names[s])}</span>` : "";
    return `<tr><td>${seatName(s)}${nick}</td><td class="num">${e.old_scores[s]} → ${e.scores[s]}</td>
      <td class="num ${d > 0 ? "plus" : d < 0 ? "minus" : "muted"}">${signed(d)}</td></tr>`;
  }).join("");
}

function resultBlock(e) {
  return `<div class="result"><h3>${roundName(view.round)} 結算　${escapeHtml(roundHeadline(e))}</h3>
    ${winsHtml(e)}<table class="analysis">${scoreRows(e)}</table></div>`;
}

let logOpen = false;

function renderLog() {
  const box = document.getElementById("log");
  box.classList.toggle("open", logOpen);
  const latest = logs.at(-1);
  const alert = [...logs].reverse().find((l) => l.level !== "info");
  const toggle = document.getElementById("log-toggle");
  toggle.setAttribute("aria-expanded", String(logOpen));
  toggle.innerHTML = `${logOpen ? "收起日誌" : "日誌"}　${
    alert ? `<span class="alert ${alert.level}">${escapeHtml(alert.message)}</span>` : latest ? escapeHtml(latest.message) : ""}`;
  document.getElementById("log-lines").innerHTML = logs
    .map((l) => `<li class="${l.level}"><time>${l.time}</time>${escapeHtml(l.message)}</li>`)
    .join("");
  if (logOpen) {
    const lines = document.getElementById("log-lines");
    lines.scrollTop = lines.scrollHeight;
  }
}

// ---- 回放 -----------------------------------------------------------------------

const replay = {
  files: [],
  path: null,
  meta: null,  // GuiApi._replay_meta()
  view: newView(),
  step: -1,  // 畫面上是第幾步；-1 表示還沒跳過
  want: -1,  // 要跳到第幾步（連按時只跳最後一次）
  seeking: null,  // 跳轉中的 Promise
  generation: 0,  // 換檔或換視角時加一，丟掉之前還在路上的跳轉結果
  playing: false,
  timer: 0,
  interval: 1000,
  loading: false,
  error: "",
};

const lastStep = () => (replay.meta ? replay.meta.steps - 1 : 0);
const clampStep = (n) => Math.max(0, Math.min(n, lastStep()));

/** 這一步屬於第幾局（meta.rounds 的索引）；還沒開局時是 -1。 */
function roundIndexAt(step) {
  let found = -1;
  replay.meta?.rounds.forEach((r, i) => { if (r.step <= step) found = i; });
  return found;
}

function freshReplayView() {
  const v = newView();
  if (replay.meta) Object.assign(v, { selfSeat: replay.meta.self_seat, numPlayers: replay.meta.num_players, names: replay.meta.player_names });
  return v;
}

async function loadReplayFiles() {
  replay.files = await api.replay_files();
  renderFileSelect();
}

function renderFileSelect() {
  const select = document.getElementById("replay-file");
  const options = [`<option value="">選擇檔案…</option>`];
  const known = replay.files.some((f) => f.path === replay.path);
  if (replay.path && !known) options.push(`<option value="${escapeHtml(replay.path)}">${escapeHtml(replay.path)}</option>`);
  for (const f of replay.files) options.push(`<option value="${escapeHtml(f.path)}">${f.time}　${f.kind}　${escapeHtml(f.name)}</option>`);
  select.innerHTML = options.join("");
  select.value = replay.path ?? "";
}

async function openReplay(path) {
  pause();
  Object.assign(replay, { path, meta: null, view: newView(), step: -1, want: -1, error: "", loading: Boolean(path) });
  replay.generation += 1;
  renderFileSelect();
  render();
  if (!path) return;
  const meta = await api.replay_open(path);
  replay.loading = false;
  if (meta.error) { replay.error = meta.error; render(); return; }
  replay.meta = meta;
  replay.view = freshReplayView();
  await seek(meta.rounds.length ? meta.rounds[0].step : 0);
}

/** 跳到第 step 步。跳轉中再被呼叫時只更新目標，回傳同一個 Promise。 */
function seek(step) {
  if (!replay.meta) return Promise.resolve();
  replay.want = clampStep(step);
  renderReplayBar();
  if (!replay.seeking) {
    replay.seeking = (async () => {
      try {
        while (replay.want !== replay.step) {
          const target = replay.want;
          const generation = replay.generation;
          const events = await api.replay_seek(target);
          if (generation !== replay.generation) continue;
          if (!Array.isArray(events)) {  // Python 端出錯
            replay.error = events?.error ?? "回放失敗";
            replay.want = replay.step;
            pause();
            render();
            break;
          }
          const v = freshReplayView();
          for (const [method, event] of events) applyTo(v, method, event);
          replay.view = v;
          replay.step = target;
          if (mode === "replay") render();
        }
      } finally {
        replay.seeking = null;
      }
    })();
  }
  return replay.seeking;
}

const current = () => replay.want;

function bigStepBefore(step) {
  const earlier = replay.meta.big_steps.filter((b) => b < step);
  return earlier.length ? earlier.at(-1) : 0;
}

function bigStepAfter(step) {
  return replay.meta.big_steps.find((b) => b > step) ?? lastStep();
}

function play() {
  if (!replay.meta) return;
  if (current() >= lastStep()) seek(0);
  replay.playing = true;
  tick();
}

async function tick() {
  if (!replay.playing) return;
  if (current() >= lastStep()) { pause(); return; }
  await seek(current() + 1);
  clearTimeout(replay.timer);
  if (replay.playing) replay.timer = setTimeout(tick, replay.interval);
}

function pause() {
  replay.playing = false;
  clearTimeout(replay.timer);
  renderReplayBar();
}

async function switchSeat(seat) {
  pause();
  const step = current();
  replay.meta = await api.replay_switch_seat(seat);
  replay.generation += 1;
  replay.step = -1;  // 同一步也要重抓
  await seek(step);
}

function renderReplayBar() {
  const bar = document.getElementById("replay-bar");
  bar.hidden = mode !== "replay";
  if (bar.hidden) return;
  const meta = replay.meta;
  const step = current();
  for (const id of ["big-prev", "prev"]) document.getElementById(id).disabled = !meta || step <= 0;
  for (const id of ["big-next", "next"]) document.getElementById(id).disabled = !meta || step >= lastStep();
  const playButton = document.getElementById("play");
  playButton.disabled = !meta;
  playButton.textContent = replay.playing ? "⏸ 暫停" : "▶ 播放";
  playButton.classList.toggle("on", replay.playing);
  const slider = document.getElementById("replay-slider");
  slider.disabled = !meta;
  slider.max = meta ? lastStep() : 0;
  slider.value = Math.max(step, 0);
  const pos = document.getElementById("replay-pos");
  pos.textContent = replay.error && meta ? replay.error : meta ? `第 ${step + 1} / ${meta.steps} 步` : "";
  pos.classList.toggle("warn", Boolean(replay.error));

  const roundButton = document.getElementById("round-button");
  const index = roundIndexAt(step);
  roundButton.disabled = !meta?.rounds.length;
  roundButton.textContent = `${index >= 0 ? roundName(meta.rounds[index].start) : "選擇局"} ▾`;
}

/** 選單裡每一局的一行摘要。 */
function roundBrief(end) {
  if (!end) return "未結束";
  if (end.reason === "abortive_draw") return "途中流局";
  if (end.reason === "exhaustive_draw") return end.nagashi_mangan ? "流局滿貫" : "流局";
  return end.wins.map((w) => `${playerName(w.seat)} ${w.zimo ? "自摸" : "榮和"} ${w.yakuman ? "役滿" : `${w.han}番`}`).join("、");
}

/** 暱稱；沒有暱稱或撞名（例如好幾個「電腦」）時用上家／對家…。 */
function playerName(seat) {
  const name = view.names[seat];
  return name && view.names.filter((n) => n === name).length === 1 ? name : seatName(seat);
}

function openRoundList() {
  const list = document.getElementById("round-list");
  const index = roundIndexAt(current());
  list.innerHTML = replay.meta.rounds.map((r, i) => `<li role="option" tabindex="-1" data-index="${i}" aria-selected="${i === index}">
      <span class="name">${roundName(r.start)}</span><span class="brief">${escapeHtml(roundBrief(r.end))}</span></li>`).join("");
  list.hidden = false;
  document.getElementById("round-button").setAttribute("aria-expanded", "true");
  list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
}

function closeRoundList() {
  document.getElementById("round-list").hidden = true;
  document.getElementById("round-tip").hidden = true;
  document.getElementById("round-button").setAttribute("aria-expanded", "false");
}

/** 滑鼠停在選單某一局時的說明：結果、和了的役與番數、各家點數變動。 */
function showRoundTip(item) {
  const r = replay.meta.rounds[Number(item.dataset.index)];
  const tip = document.getElementById("round-tip");
  if (!r.end) {
    tip.innerHTML = `<h3>${roundName(r.start)}</h3><p class="muted">牌譜在這局中途結束</p>`;
  } else {
    tip.innerHTML = `<h3>${roundName(r.start)}　${escapeHtml(roundHeadline(r.end))}</h3>
      ${winsHtml(r.end)}<table class="analysis">${scoreRows(r.end)}</table>`;
  }
  // 放在選單右邊，右邊放不下就放左邊；超出視窗底部就往上移
  const list = item.parentElement;
  const menu = tip.parentElement.getBoundingClientRect();
  tip.hidden = false;
  const { width, height } = tip.getBoundingClientRect();
  const right = list.offsetLeft + list.offsetWidth + 8;
  const fitsRight = menu.left + right + width <= window.innerWidth - 8;
  tip.style.left = `${fitsRight ? right : Math.max(list.offsetLeft - width - 8, 8 - menu.left)}px`;
  const top = list.offsetTop + item.offsetTop - list.scrollTop;
  tip.style.top = `${Math.max(0, Math.min(top, window.innerHeight - 8 - height - menu.top))}px`;
}

function setMode(next) {
  if (mode === next) return;
  mode = next;
  if (mode === "live") { liveUnseen = false; pause(); }
  closeRoundList();
  if (mode === "replay" && !replay.files.length) loadReplayFiles();
  render();
}

// ---- 指令 -----------------------------------------------------------------------

function bindControls() {
  document.getElementById("listen").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("toggle");
    button.disabled = true;
    try {
      if (proxy.listening) await api.stop_listening();
      else await api.start_listening(document.getElementById("host").value.trim(), Number(document.getElementById("port").value));
    } finally {
      button.disabled = false;
    }
  });
  document.getElementById("log-toggle").addEventListener("click", () => { logOpen = !logOpen; renderLog(); });

  for (const tab of document.querySelectorAll(".tabs [data-mode]")) {
    tab.addEventListener("click", () => setMode(tab.dataset.mode));
  }

  // 回放
  const fileSelect = document.getElementById("replay-file");
  fileSelect.addEventListener("focus", loadReplayFiles);  // 打開選單前更新清單（可能剛存了新牌譜）
  fileSelect.addEventListener("change", () => openReplay(fileSelect.value || null));
  document.getElementById("replay-browse").addEventListener("click", async () => {
    const path = await api.replay_choose_file();
    if (path) openReplay(path);
  });
  document.getElementById("big-prev").addEventListener("click", () => { pause(); seek(bigStepBefore(current())); });
  document.getElementById("prev").addEventListener("click", () => { pause(); seek(current() - 1); });
  document.getElementById("next").addEventListener("click", () => { pause(); seek(current() + 1); });
  document.getElementById("big-next").addEventListener("click", () => { pause(); seek(bigStepAfter(current())); });
  document.getElementById("play").addEventListener("click", () => (replay.playing ? pause() : play()));
  document.getElementById("interval").addEventListener("change", (event) => { replay.interval = Number(event.target.value); });
  document.getElementById("replay-slider").addEventListener("input", (event) => { pause(); seek(Number(event.target.value)); });

  const roundButton = document.getElementById("round-button");
  const roundList = document.getElementById("round-list");
  roundButton.addEventListener("click", () => (roundList.hidden ? openRoundList() : closeRoundList()));
  roundList.addEventListener("mouseover", (event) => {
    const item = event.target.closest("li");
    if (item) showRoundTip(item);
  });
  roundList.addEventListener("click", (event) => {
    const item = event.target.closest("li");
    if (!item) return;
    closeRoundList();
    pause();
    seek(replay.meta.rounds[Number(item.dataset.index)].step);
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#round-menu")) closeRoundList();
  });

  // 座位旁的攝影機按鈕（畫面重畫時會換掉，所以掛在上層）
  document.querySelector("main").addEventListener("click", (event) => {
    const camera = event.target.closest(".camera");
    if (camera) switchSeat(Number(camera.dataset.seat));
  });

  document.addEventListener("keydown", (event) => {
    if (mode !== "replay" || !replay.meta) return;
    if (event.target.closest("input:not([type=range]), select, textarea")) return;
    if (event.key === "Escape") { closeRoundList(); return; }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      pause();
      const forward = event.key === "ArrowRight";
      if (event.shiftKey) seek(forward ? bigStepAfter(current()) : bigStepBefore(current()));
      else seek(current() + (forward ? 1 : -1));
    } else if (event.key === " " && !event.target.closest("button")) {
      event.preventDefault();
      replay.playing ? pause() : play();
    }
  });
}

window.addEventListener("pywebviewready", async () => {
  api = window.pywebview.api;
  const status = await api.status();
  document.getElementById("host").value = status.host;
  document.getElementById("port").value = status.port;
  proxy.listening = status.listening;
  labels = await api.labels();
  bindControls();
  for (const [method, event] of pending.splice(0)) qmax.receive(method, event);
  render();
});
