/* FINN frontend. No framework, no build step: one file a reviewer can read top to bottom. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = JSON.parse(localStorage.getItem("finn." + k)); return v ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("finn." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

const S = {
  meta: null, digest: null,
  rules: store.get("rules", null),
  book: store.get("book", null),           // null = the server's default book
  seen: new Set(store.get("seen", [])),
  win: store.get("win", { hours: 24 }),
  auth: store.get("auth", null),            // {token, user, role}
};
const WINDOWS = [[24, "24 hours", "24h"], [72, "3 days", "3d"], [168, "7 days", "7d"], [720, "30 days", "30d"]];

/* ---------- formatting ---------- */
const inr = (v, d = 0) => v == null ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const cr = v => v == null ? "–" : v >= 100000 ? `₹${(v / 100000).toFixed(2)} L cr` : `₹${inr(v)} cr`;
const pct = (v, d = 1) => v == null ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}%`;
const tone = v => v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
function ago(iso) {
  const t = new Date(iso), mins = (Date.now() - t) / 60000;
  if (mins < 60) return `${Math.max(1, Math.round(mins))} min ago`;
  if (mins < 60 * 20) return `${Math.round(mins / 60)} h ago`;
  return t.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) + ", " + t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
}
const dayLabel = d => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
function windowWords() {
  if (S.win.from) return `between ${dayLabel(S.win.from)} and ${S.win.to ? dayLabel(S.win.to) : "now"}`;
  const w = WINDOWS.find(x => x[0] === S.win.hours);
  return `in the last ${w ? w[1] : S.win.hours + " hours"}`;
}

/* ---------- api ---------- */
function params(extra = {}) {
  const r = S.rules || {};
  const p = new URLSearchParams({ vol: r.vol, px: r.px, lookback: r.lookback, watch: (r.watch || []).join(","), mute: (r.mute || []).join(","), ...extra });
  if (S.book) p.set("symbols", S.book.map(h => `${h.symbol}:${h.weight}`).join(","));
  return p.toString();
}
async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (S.auth?.token) headers.Authorization = "Bearer " + S.auth.token;
  const res = await fetch(path, { ...opts, headers });
  const data = await res.json().catch(() => ({ error: `The server answered ${res.status}.` }));
  if (res.status === 401 && data.signed_out) { signOut(true); }
  if (res.status === 429) throw new Error(data.error || "Too many requests. Wait a moment and try again.");
  if (!res.ok) throw new Error(data.error || `The server answered ${res.status}.`);
  return data;
}
function signOut(expired) {
  S.auth = null; localStorage.removeItem("finn.auth");
  if (expired) toast("Your session expired, so you are browsing as a guest.");
}
function toast(msg) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.setAttribute("role", "status"); document.body.append(t); }
  t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => t.hidden = true, 4000);
}
async function loadDigest(fresh) {
  const w = S.win.from ? { from: S.win.from, ...(S.win.to ? { to: S.win.to } : {}) } : { hours: S.win.hours };
  S.digest = await api("api/digest?" + params({ ...w, ...(fresh ? { fresh: 1 } : {}) }));
  return S.digest;
}

/* ---------- small drawings ---------- */
function spark(vals, w = 64, h = 24, dir = 0) {
  const v = (vals || []).filter(x => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), k = hi - lo || 1;
  const X = i => (2 + i / (v.length - 1) * (w - 6)).toFixed(1), Y = y => (h - 3 - (y - lo) / k * (h - 6)).toFixed(1);
  const pts = v.map((y, i) => `${X(i)},${Y(y)}`).join(" ");
  const col = dir > 0 ? "var(--up)" : dir < 0 ? "var(--down)" : "var(--muted)";
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="var(--faint)" stroke-width="1.4" stroke-linejoin="round"/><circle cx="${X(v.length - 1)}" cy="${Y(v[v.length - 1])}" r="2.6" fill="${col}"/></svg>`;
}
function bars(labels, series, { line = false, unit = "", minTop = 0 } = {}) {
  // series: [{values, color}] - one or two side by side. Compact, with first/last labels only.
  const W = 320, H = 86, top = 6, base = H - 16, n = labels.length;
  const all = series.flatMap(s => s.values).filter(v => v != null);
  if (!all.length) return `<p class="muted">Not reported.</p>`;
  let hi = Math.max(...all, 0, minTop), lo = Math.min(...all, 0);
  if (line) { const a = Math.min(...all), z = Math.max(...all), pad = Math.max((z - a) * 0.25, Math.abs(z) * 0.04, 0.5); lo = a - pad; hi = z + pad; }
  const k = (hi - lo) || 1;
  const y = v => top + (hi - v) / k * (base - top);
  const slot = W / n, bw = Math.min(22, slot * 0.72) / series.length;
  let out = "";
  if (line) {
    const s = series[0];
    const pts = s.values.map((v, i) => v == null ? null : `${(i * slot + slot / 2).toFixed(1)},${y(v).toFixed(1)}`).filter(Boolean).join(" ");
    out += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"/>`;
    s.values.forEach((v, i) => { if (v != null) out += `<circle cx="${(i * slot + slot / 2).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.4" fill="${s.color}"/>`; });
  } else {
    series.forEach((s, j) => s.values.forEach((v, i) => {
      if (v == null) return;
      const x = i * slot + (slot - bw * series.length) / 2 + j * bw, y0 = y(Math.max(v, 0)), hgt = Math.max(1, Math.abs(y(v) - y(0)));
      out += `<rect x="${x.toFixed(1)}" y="${y0.toFixed(1)}" width="${(bw - 1).toFixed(1)}" height="${hgt.toFixed(1)}" fill="${v < 0 ? "var(--down)" : s.color}" rx="1"/>`;
    }));
    out += `<line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="var(--rule)"/>`;
  }
  out += `<text x="${slot / 2}" y="${H - 3}" text-anchor="middle">${esc(labels[0])}</text><text x="${W - slot / 2}" y="${H - 3}" text-anchor="middle">${esc(labels[n - 1])}</text>`;
  return `<svg class="bars" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(labels[0])} to ${esc(labels[n - 1])}${unit ? ", " + unit : ""}">${out}</svg>`;
}
const lastOf = a => { const v = (a || []).filter(x => x != null); return v[v.length - 1]; };
const firstOf = a => (a || []).find(x => x != null);

/* ---------- Today ---------- */
function viewToday() {
  const v = $("#view");
  v.innerHTML = windowPicker() + `<div id="today"><div class="skel" style="height:30px;width:80%"></div><div class="skel" style="height:46px"></div><div class="skel" style="height:120px"></div></div>`;
  bindWindow();
  loadDigest().then(renderToday).catch(e => { $("#today").innerHTML = `<div class="err">${esc(e.message)}</div><button class="btn ghost" data-act="retry-today">Try again</button>`; });
}
function windowPicker() {
  const chips = WINDOWS.map(([h, label, short]) => `<button class="chip ${!S.win.from && S.win.hours === h ? "on" : ""}" data-h="${h}" aria-label="Last ${label}">${short}</button>`).join("");
  const custom = S.win.from ? `<div class="custom"><input type="date" id="wf" value="${esc(S.win.from)}" aria-label="From"><span>to</span><input type="date" id="wt" value="${esc(S.win.to || "")}" aria-label="To"></div>` : "";
  return `<div class="window" role="group" aria-label="Time window">${chips}<button class="chip ${S.win.from ? "on" : ""}" data-h="custom">Dates</button></div>${custom}`;
}
function bindWindow() {
  $$(".window .chip").forEach(b => b.onclick = () => {
    if (b.dataset.h === "custom") {
      const d = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
      S.win = { from: S.win.from || d, to: S.win.to || "" };
    } else S.win = { hours: +b.dataset.h };
    store.set("win", S.win); viewToday();
  });
  const f = $("#wf"), t = $("#wt");
  if (f) f.onchange = t.onchange = () => { S.win = { from: f.value, to: t.value }; store.set("win", S.win); if (f.value) viewToday(); };
}
function renderToday(d) {
  const c = d.counts, active = d.matters.filter(p => !S.seen.has(p.id)), done = d.matters.filter(p => S.seen.has(p.id));
  const down = new Set(d.errors.filter(e => e.what === "filings" && !e.error.includes("saved copy")).map(e => e.symbol)).size;
  if (down && down === Object.keys(d.weights).length && !c.total) {      // say so, rather than "nothing happened"
    $("#today").innerHTML = `<div class="err"><b>FINN could not reach the exchanges.</b> Nothing is shown rather than an empty day that may not be empty.</div>
      <button class="btn ghost" id="again">Try again</button><details class="note"><summary>What failed</summary>${d.errors.slice(0, 6).map(e => `<div>${esc(e.symbol)} ${esc(e.what)}: ${esc(e.error)}</div>`).join("")}</details>`;
    $("#again").onclick = () => { $("#today").innerHTML = `<div class="skel" style="height:46px"></div>`; loadDigest(true).then(renderToday).catch(() => viewToday()); };
    return;
  }
  const lede = c.total === 0
    ? `No filings ${windowWords()}.`
    : `${c.total} filing${c.total > 1 ? "s" : ""} ${windowWords()}. ${c.matters === 0 ? "None need you." : c.matters === 1 ? "One is worth your time." : `${c.matters} are worth your time.`}`;
  const ticks = d.ticks.map(t => `<i class="${t.tier}${S.seen.has(t.id) ? " done" : ""}" data-id="${t.id}"></i>`).join("");
  let h = `<section class="signal"><p class="lede">${esc(lede)}</p>
    ${c.total ? `<div class="ticks" aria-hidden="true">${ticks}</div>` : ""}
    <div class="strip-meta"><span>${c.total ? `${c.buried} buried, ${c.folded} duplicates folded` : ""}</span>
    <span>as of ${new Date(d.asof).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })}
    ${"speechSynthesis" in window && (c.matters || d.movers.length) ? ` &nbsp;<button class="listen" id="listen">Listen</button>` : ""}</span></div></section>`;

  if (d.movers.length) {
    const days = [...new Set(d.movers.map(a => a.date))];
    h += `<h2>Unusual moves <small>${days.length === 1 ? dayLabel(days[0]) + " close" : `past ±${d.rules.px}% or ${d.rules.vol}× volume`}</small></h2><div class="moves">` + d.movers.map(a => `
      <a class="move" href="#research/${esc(a.symbol)}">
        <div><span class="tk">${esc(a.symbol)}</span><div class="what">${esc(a.text.charAt(0).toUpperCase() + a.text.slice(1))}${days.length > 1 ? `, ${dayLabel(a.date)}` : ""}</div></div>
        ${spark(a.spark, 64, 24, a.pct)}
        <div><div class="pct ${tone(a.pct)}">${pct(a.pct)}</div><div class="volx ${a.fired.includes("volume") ? "hot" : ""}">${a.volx.toFixed(1)}× vol</div></div>
      </a>`).join("") + `</div>`;
  }
  if (d.matters.length) {
    h += `<h2>Worth your time <small>${active.length} left</small></h2>`;
    h += active.map(card).join("");
    if (!active.length) h += `<div class="caught"><strong>You're caught up.</strong><span class="muted">Everything that mattered ${windowWords()} is marked done.</span></div>`;
    if (done.length) h += `<details class="rows" style="margin-top:10px"><summary style="padding:10px 14px;font-size:14px;cursor:pointer">Done (${done.length})</summary>${done.map(card).join("")}</details>`;
  }
  if (d.know.length) {
    h += `<h2>Good to know</h2><div class="rows">` + d.know.map(p => `
      <a class="row" href="${esc(p.url || "#")}" target="_blank" rel="noopener">
        <span class="tk">${esc(p.symbol)}</span>
        <span class="t">${esc(p.line)}<small>${esc(p.label)}, ${ago(p.ts)}${p.related ? `, +${p.related.length} related` : ""}</small></span></a>`).join("") + `</div>`;
  }
  if (d.upcoming.length) {
    h += `<h2>Coming up</h2><div class="rows">` + d.upcoming.map(u => `
      <a class="row" href="${esc(u.url || "#")}" target="_blank" rel="noopener">
        <span class="up-date">${dayLabel(u.date)}</span>
        <span class="t"><b class="tk">${esc(u.symbol)}</b> ${esc(u.what.toLowerCase())}</span></a>`).join("") + `</div>`;
  }
  if (d.buried.length) {
    h += `<h2>Buried <small>${c.buried} routine filings you can skip</small></h2><div class="rows">` + d.buried.map(g => `
      <details class="bury"><summary><span>${esc(g.label)}</span><span>${g.items.length}</span></summary>${g.items.map(i => `
        <a class="row" href="${esc(i.url || "#")}" target="_blank" rel="noopener"><span class="tk">${esc(i.symbol)}</span><span class="t">${esc(i.line || i.headline)}</span></a>`).join("")}</details>`).join("") + `</div>`;
  }
  if (!c.total && !d.movers.length) h += `<div class="empty">Nothing was filed and nothing moved past your thresholds. Try a longer window.</div>`;
  if (d.errors.length) {
    const who = [...new Set(d.errors.map(e => e.symbol))];
    h += `<details class="note"><summary>${who.length} of ${Object.keys(d.weights).length} companies could not be fully refreshed</summary>${d.errors.map(e => `<div>${esc(e.symbol)} ${esc(e.what)}: ${esc(e.error)}</div>`).join("")}</details>`;
  }
  $("#today").innerHTML = h;
  bindCards();
  const L = $("#listen"); if (L) L.onclick = () => listen(d, L);
  active.forEach(p => { if (p.cat === "management_change" || (S.meta?.llm.ready && p.sub !== "numbers")) detail(p); });
}
function card(p) {
  const mv = S.digest.movers.find(a => a.symbol === p.symbol);
  const name = (S.digest.names[p.symbol] || p.company || "").replace(/ (Limited|Ltd\.?)$/i, "");
  let body = "";
  if (p.first_cut) {
    const f = p.first_cut;
    body += f.fresh ? `<div class="cut">${f.rows.map(r => `<div><div class="k">${r.k}</div><div class="v">${inr(r.v)}</div>
        <div class="d ${tone(r.yoy)}">${pct(r.yoy, 0)} <span>YoY</span></div><div class="d ${tone(r.qoq)}">${pct(r.qoq, 0)} <span>QoQ</span></div></div>`).join("")}</div>
      <div class="cutnote">${esc(f.period)}, ${esc(f.basis)}, ₹ crore. EBITDA margin ${f.margin.now ?? "–"}%${f.margin.y != null ? ` against ${f.margin.y}% a year ago` : ""}.</div>`
      : `<div class="pending">The numbers for this quarter are not in the standardised tables yet. Open the filing for now; this card fills in once they are.</div>`;
  }
  if (p.cat === "management_change") body += `<div class="people" id="d-${p.id}"><div class="skel" style="width:70%"></div><div class="skel" style="width:90%"></div></div>`;
  if (mv && p.why.some(w => w.includes("stock moved"))) body += `<div class="with-move ${tone(mv.pct)}"><span>Stock ${pct(mv.pct)} on ${mv.volx.toFixed(1)}× volume around this filing</span></div>`;
  return `<article class="card ${S.seen.has(p.id) ? "done" : ""}" id="c-${p.id}">
    <div class="head"><a class="tk" href="#research/${esc(p.symbol)}">${esc(p.symbol)}</a><span class="co">${esc(name)}</span><span class="when">${ago(p.ts)}</span></div>
    <span class="kind">${esc(p.label)}</span>
    <p class="line" id="l-${p.id}">${esc(p.line)}</p>${body}
    ${p.related ? `<details class="related"><summary>${p.related.length} more filing${p.related.length > 1 ? "s" : ""} about this</summary><ul>${p.related.map(r => `<li><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.line || r.headline)}</a></li>`).join("")}</ul></details>` : ""}
    <div class="why" hidden><b>Why this is ranked ${p.score}/100</b><ul>${p.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>
    <div class="acts">
      ${p.url ? `<a class="primary" href="${esc(p.url)}" target="_blank" rel="noopener">Open filing</a>` : ""}
      <a href="#research/${esc(p.symbol)}">Research</a>
      <button data-why>Why ranked here</button><span class="spacer"></span>
      <button class="primary" data-done="${p.id}">${S.seen.has(p.id) ? "Undo" : "Done"}</button>
    </div></article>`;
}
function bindCards() {
  $$("[data-why]").forEach(b => b.onclick = () => { const w = $(".why", b.closest(".card")); w.hidden = !w.hidden; });
  $$("[data-done]").forEach(b => b.onclick = () => {
    const id = b.dataset.done;
    S.seen.has(id) ? S.seen.delete(id) : S.seen.add(id);
    store.set("seen", [...S.seen].slice(-400));
    const y = scrollY; renderToday(S.digest); scrollTo(0, y);
  });
}
async function detail(p) {
  try {
    const d = await api(`api/filing/${p.id}?` + params());
    const box = $(`#d-${p.id}`);
    if (box) {
      const people = (d.people || []).map(x => `<div class="person"><span class="dir ${x.action === "Joining" ? "in" : "out"}">${x.action === "Joining" ? "In" : "Out"}</span><span><b>${esc(x.name)}</b>, ${esc(x.role)}${x.effective ? `, from ${esc(x.effective)}` : ""}</span></div>`).join("");
      const bio = d.background?.length ? `<div class="bio"><ul>${d.background.map(b => `<li>${esc(b)}</li>`).join("")}</ul></div>` : d.profile ? `<div class="bio">${esc(d.profile)}</div>` : "";
      box.innerHTML = people + bio + (d.lookup ? `<a class="muted" style="font-size:13px;margin-top:6px" href="${esc(d.lookup)}" target="_blank" rel="noopener">Look them up on LinkedIn</a>` : "") || `<span class="muted" style="font-size:13px">The filing gives no profile. Open it for details.</span>`;
    }
    const line = $(`#l-${p.id}`), inn = (d.people || []).find(x => x.action === "Joining"), out = (d.people || []).find(x => x.action === "Leaving");
    if (line && inn && out) line.textContent = `${inn.role} change: ${inn.name.replace(/^(Mr|Ms|Mrs|Dr|Shri|Smt)\.? /, "")} replaces ${out.name.replace(/^(Mr|Ms|Mrs|Dr|Shri|Smt)\.? /, "")}`;
    else if (line && d.summary) line.textContent = d.summary;
  } catch { const box = $(`#d-${p.id}`); if (box) box.innerHTML = ""; }
}
function listen(d, btn) {
  if (speechSynthesis.speaking) { speechSynthesis.cancel(); btn.textContent = "Listen"; return; }
  const nm = s => (d.names[s] || s).replace(/ (Limited|Ltd\.?)$/i, "");
  const parts = [$(".lede").textContent];
  d.movers.slice(0, 3).forEach(a => parts.push(`${nm(a.symbol)} is ${a.say}, ${a.text}.`));
  d.matters.filter(p => !S.seen.has(p.id)).slice(0, 6).forEach(p => {
    let s = `${nm(p.symbol)}. ${p.label}. ${p.line}.`;
    if (p.first_cut?.fresh) { const r = p.first_cut.rows; s += ` Revenue ${r[0].yoy > 0 ? "up" : "down"} ${Math.abs(r[0].yoy)} percent year on year, profit ${r[3].yoy > 0 ? "up" : "down"} ${Math.abs(r[3].yoy)} percent.`; }
    parts.push(s);
  });
  const u = new SpeechSynthesisUtterance(parts.join(" "));
  u.lang = "en-IN"; u.rate = 1.05; u.onend = () => btn.textContent = "Listen";
  speechSynthesis.speak(u); btn.textContent = "Stop";
}

/* ---------- Book ---------- */
async function viewBook() {
  const v = $("#view");
  v.innerHTML = `<h1>Your book</h1><div class="skel" style="height:200px;margin-top:14px"></div>`;
  try {
    const d = S.digest || await loadDigest();
    const rows = Object.keys(d.weights).map(s => ({ s, w: d.weights[s], q: d.quotes[s] })).sort((a, b) => Math.abs(b.q?.pct ?? -1) - Math.abs(a.q?.pct ?? -1));
    const day = rows.find(r => r.q)?.q.date;
    v.innerHTML = `<h1>Your book</h1><p class="muted" style="margin-top:4px">${rows.length} holdings, biggest movers first${day ? `. Close of ${dayLabel(day)}` : ""}.</p>
      <div class="rows" style="margin-top:14px">${rows.map(r => `
        <a class="hold" href="#research/${esc(r.s)}"><div><span class="tk">${esc(r.s)}</span> <span class="muted" style="font-size:12px">${r.w}%</span><div class="nm">${esc((d.names[r.s] || "").replace(/ (Limited|Ltd\.?)$/i, ""))}</div></div>
        ${r.q ? spark(r.q.spark, 60, 24, r.q.pct) : "<span></span>"}
        <div>${r.q ? `<div class="px">${inr(r.q.close, r.q.close < 1000 ? 1 : 0)}</div><div class="ch ${tone(r.q.pct)}">${pct(r.q.pct)}</div>` : `<div class="ch muted">no price</div>`}</div></a>`).join("")}</div>
      <p class="note">Tap a holding to research it. Edit holdings and weights under Rules.</p>`;
  } catch (e) { v.innerHTML = `<h1>Your book</h1><div class="err">${esc(e.message)}</div>`; }
}

/* ---------- Research ---------- */
const ST = { missed: ["Missed", "bad"], behind: ["Running behind", "bad"], beat: ["Beat", "good"], met: ["Met", "good"], ahead: ["Ahead", "good"], "on track": ["On track", "good"], open: ["Not reported yet", "wait"], "long-dated": ["Long-dated", "wait"], unmeasured: ["Not measurable", "wait"] };
let pollTimer = null;
async function viewResearch(sym) {
  clearTimeout(pollTimer);
  const v = $("#view");
  v.innerHTML = `<button class="back" data-act="back">Back</button><h1>${esc(sym)}</h1><div class="skel" style="height:90px;margin-top:14px"></div><div class="skel" style="height:160px"></div>`;
  let r;
  try { r = await api(`api/research/${encodeURIComponent(sym)}`); }
  catch (e) { v.innerHTML = `<button class="back" data-act="back">Back</button><h1>${esc(sym)}</h1><div class="err">${esc(e.message)}</div><p class="muted">Check the ticker, or search by company name in the bar below.</p>`; return; }
  const s = r.snapshot, t = r.trajectory, b = r.balance, c = r.cash, n = t.years.length;
  const good = r.flags.filter(f => f.tone === "good"), bad = r.flags.filter(f => f.tone !== "good");
  v.innerHTML = `<button class="back" data-act="back">Back</button>
    <div class="rhead"><div><h1>${esc(r.name.replace(/ (Limited|Ltd\.?)$/i, ""))}</h1><div class="muted" style="font-size:13px;margin-top:3px">${esc(r.symbol)}, ${esc(r.basis)} figures in ₹ crore</div></div>
      <div class="px"><b>₹${inr(s.price)}</b>${s.mcap ? cr(s.mcap) : ""}</div></div>
    <div class="jump">${[["said", "Said vs did"], ["flags", "What the numbers say"], ["snap", "Snapshot"], ["trend", "Trajectory"], ["bs", "Balance sheet"], ["cash", "Cash"], ["biz", "Business"], ["case", "Both sides"]].map(([id, l]) => `<button class="chip" data-jump="${id}">${l}</button>`).join("")}</div>

    <h2 id="said">Said vs did <small>last five earnings calls</small></h2>
    <div id="ledger"><div class="panel-card steps"><ul><li class="now">Finding the call transcripts</li></ul></div></div>

    <h2 id="flags">What the numbers say</h2>
    ${r.flags.length ? `<div class="rows">${r.flags.map(f => `<div class="flag ${f.tone}"><i></i><div><b>${esc(f.title)}</b><span>${esc(f.evidence)}</span></div></div>`).join("")}</div>` : `<p class="muted">Nothing stands out in the reported numbers.</p>`}

    <h2 id="snap">Snapshot <small>${esc(s.rev_label === "TTM" ? "trailing twelve months" : s.rev_label)}</small></h2>
    <div class="grid">${[["Revenue", inr(s.rev)], [r.financial ? "Fin. margin" : "Op. margin", s.opm == null ? "–" : s.opm + "%"], ["Net profit", inr(s.pat)], ["P/E", s.pe ?? "–"],
      ["ROCE", s.roce == null ? "–" : s.roce + "%"], ["ROE", s.roe == null ? "–" : s.roe + "%"], ["Debt/equity", r.financial ? "n/a" : s.de ?? "–"], ["Div. yield", s.yield == null ? "–" : s.yield + "%"]].map(([k, val]) => `<div><div class="k">${k}</div><div class="v">${val}</div></div>`).join("")}</div>

    <h2 id="trend">Trajectory <small>${esc(t.years[0] || "")} to ${esc(t.years[n - 1] || "")}</small></h2>
    <div class="panel-card">
      <div class="chart-title"><span><b>Revenue</b> ${inr(firstOf(t.sales))} to ${inr(lastOf(t.sales))}</span><span>${t.cagr.sales5 != null ? `5y ${t.cagr.sales5}% a year, 3y ${t.cagr.sales3}%` : ""}</span></div>
      ${bars(t.years, [{ values: t.sales, color: "var(--ink)" }])}
      <div class="chart-title" style="margin-top:12px"><span><b>Net profit</b> ${inr(firstOf(t.pat))} to ${inr(lastOf(t.pat))}</span><span>${t.cagr.pat5 != null ? `5y ${t.cagr.pat5}% a year, 3y ${t.cagr.pat3}%` : ""}</span></div>
      ${bars(t.years, [{ values: t.pat, color: "#7C869A" }])}
      <div class="chart-title" style="margin-top:12px"><span><b>${r.financial ? "Financing" : "Operating"} margin</b> ${firstOf(t.opm) ?? "–"}% to ${lastOf(t.opm) ?? "–"}%</span></div>
      ${bars(t.years, [{ values: t.opm, color: "var(--ink)" }], { line: true })}
    </div>
    <div class="panel-card" style="margin-top:8px"><table class="q"><thead><tr><th>Quarter</th><th>Revenue</th><th>YoY</th><th>Margin</th><th>Profit</th></tr></thead><tbody>
      ${r.quarters.slice(-6).reverse().map(q => `<tr><td>${esc(q.q)}</td><td>${inr(q.sales)}</td><td class="${tone(q.yoy)}">${pct(q.yoy, 0)}</td><td>${q.opm == null ? "–" : q.opm + "%"}</td><td>${inr(q.pat)}</td></tr>`).join("")}</tbody></table></div>

    <h2 id="bs">Balance sheet</h2>
    ${r.financial ? `<p class="muted">Leverage and working-capital ratios do not apply to a lender; its deposits are its raw material.</p>` : `<div class="panel-card">
      <div class="chart-title"><span><b>Debt to equity</b> ${firstOf(b.de) ?? "–"} to ${lastOf(b.de) ?? "–"}</span><span>borrowings ${inr(lastOf(b.debt))}</span></div>
      ${bars(b.years, [{ values: b.de, color: "var(--ink)" }], { minTop: 1 })}
      <div class="chart-title" style="margin-top:12px"><span><b>Debtor days</b> ${firstOf(b.debtor) ?? "–"} to ${lastOf(b.debtor) ?? "–"}</span><span>cash cycle ${lastOf(b.ccc) ?? "–"} days</span></div>
      ${bars(b.ryears, [{ values: b.debtor, color: "#7C869A" }], { line: true })}</div>`}

    <h2 id="cash">Cash quality <small>do profits turn into cash?</small></h2>
    <div class="panel-card">
      <div class="chart-title"><span><b>Operating cash against profit</b></span><span>${lastOf(c.conv) != null ? `${lastOf(c.conv)}% converted in ${esc(c.years[c.years.length - 1])}` : ""}</span></div>
      ${bars(c.years, [{ values: c.pat, color: "#B9BFCC" }, { values: c.cfo, color: "var(--ink)" }])}
      <div class="legend"><span><i style="background:#B9BFCC"></i>Reported profit</span><span><i style="background:var(--ink)"></i>Cash from operations</span></div>
      ${c.fcf.some(x => x != null) ? `<div class="chart-title" style="margin-top:12px"><span><b>Free cash flow</b></span><span>${inr(lastOf(c.fcf))} in ${esc(c.years[c.years.length - 1])}</span></div>${bars(c.years, [{ values: c.fcf, color: "var(--ink)" }])}` : ""}
    </div>

    <h2 id="biz">Business</h2>
    <div class="panel-card" id="business"><p>${esc(r.about || "No description available.")}</p></div>

    <h2 id="case">Both sides <small>from the numbers above</small></h2>
    <div class="panel-card two" id="sides"><div><h3 class="up">For</h3><ul>${good.map(f => `<li>${esc(f.title)}</li>`).join("") || "<li class='muted'>Nothing in the numbers argues for it.</li>"}</ul></div>
      <div><h3 class="down">Against</h3><ul>${bad.map(f => `<li>${esc(f.title)}</li>`).join("") || "<li class='muted'>Nothing in the numbers argues against it.</li>"}</ul></div></div>

    <h2>Sources</h2>
    <div class="panel-card src"><ul><li><a href="${esc(r.source)}" target="_blank" rel="noopener">Standardised statements on screener.in</a></li><span id="srcs"></span></ul>
      <p class="note" style="margin-top:8px">Only the company's own filings, reports and call transcripts. No news, broker notes or outside knowledge.</p></div>`;
  $$("[data-jump]").forEach(x => x.onclick = () => { const el = document.getElementById(x.dataset.jump); scrollTo({ top: el.getBoundingClientRect().top + scrollY - $("#top").offsetHeight - 58, behavior: "smooth" }); });
  pollNarrative(r.symbol);
}
async function pollNarrative(sym, retry) {
  const box = $("#ledger");
  if (!box || !location.hash.includes(sym)) return;
  let j;
  try { j = await api(`api/narrative/${encodeURIComponent(sym)}${retry ? "?retry=1" : ""}`); }
  catch (e) { box.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  if (j.state === "running") {
    box.innerHTML = `<div class="panel-card steps"><ul>${j.steps.map((s, i) => `<li class="${i === j.steps.length - 1 ? "now" : ""}">${esc(s)}</li>`).join("") || `<li class="now">Finding the call transcripts</li>`}</ul></div>`;
    pollTimer = setTimeout(() => pollNarrative(sym), 700); return;
  }
  if (j.state === "error") { box.innerHTML = `<div class="err">The transcript pass failed: ${esc(j.error)}</div><button class="btn ghost" id="retry">Try again</button>`; $("#retry").onclick = () => pollNarrative(sym, true); return; }
  renderLedger(j.result);
}
function scoreWords(sc, n) {
  const measured = sc.kept + sc.missed + sc.live;
  if (!n) return "Management gave no numeric targets in the calls we could read.";
  if (!measured) return `${n} target${n > 1 ? "s" : ""} on record, none measurable against reported numbers yet.`;
  const bits = [];
  if (sc.kept) bits.push(`${sc.kept} kept`);
  if (sc.missed) bits.push(`${sc.missed} missed`);
  if (sc.behind) bits.push(`${sc.behind} running behind`);
  if (sc.live - sc.behind > 0) bits.push(`${sc.live - sc.behind} on track`);
  return `Of ${measured} measurable target${measured > 1 ? "s" : ""}: ${bits.join(", ")}.` + (sc.cuts ? ` Guidance was cut mid-year ${sc.cuts === 1 ? "once" : sc.cuts === 2 ? "twice" : sc.cuts + " times"}.` : "");
}
function bullet(e) {
  if (e.actual == null) return "";
  const m = e.target.match(/[\d.]+/g) || [];
  let lo = e.target.startsWith("under") ? null : +m[0], hi = e.target.endsWith("+") ? null : +(m[1] ?? m[0]);
  const vals = [lo, hi, e.actual].filter(x => x != null), a = Math.min(...vals), z = Math.max(...vals), pad = Math.max(1.5, (z - a) * 0.3);
  const x = v => ((v - (a - pad)) / (z - a + 2 * pad) * 100).toFixed(1);
  const L = lo == null ? 0 : x(lo), R = hi == null ? 100 : x(hi);
  const cls = ST[e.status][1] === "bad" ? "bad" : "good";
  return `<div class="bullet" aria-hidden="true"><div class="track"></div><div class="band" style="left:${L}%;width:${Math.max(1.5, R - L)}%"></div><div class="dot ${cls}" style="left:${x(e.actual)}%"></div></div>`;
}
function renderLedger(n) {
  const main = n.ledger.filter(e => !["unmeasured", "long-dated"].includes(e.status)), rest = n.ledger.filter(e => ["unmeasured", "long-dated"].includes(e.status));
  const one = e => `<div class="prom"><div class="top"><span class="lbl">${esc(e.label)} <span>${esc(e.period)}${e.assumed_period ? " (period assumed)" : ""}</span></span><span class="st ${ST[e.status][1]}">${ST[e.status][0]}</span></div>
    ${e.actual != null ? `<div class="nums"><span><b>${esc(e.target)}</b>promised</span><span><b>${e.actual}%</b>${esc(e.final ? "delivered" : "so far")}</span></div>${bullet(e)}<div class="muted" style="font-size:12.5px">${esc(e.detail)}</div>`
      : `<div class="nums"><span><b>${esc(e.target)}</b>promised</span></div><div class="muted" style="font-size:12.5px">${esc(e.detail)}</div>`}
    ${e.revisions.map(r => `<div class="revise ${r.move === "cut" ? "lowered" : "raised"}">${r.move === "cut" ? "Cut" : "Raised"} to ${esc(r.target)} in ${esc(r.date)}${e.status_vs_latest ? `, and ${ST[e.status_vs_latest][0].toLowerCase()} against that` : ""}</div>`).join("")}
    <blockquote class="quote" style="margin:8px 0 0">“${esc(e.said.quote)}”<cite>${esc(e.said.speaker || "Management")}, <a href="${esc(e.said.url)}" target="_blank" rel="noopener">${esc(e.said.date)} call, page ${e.said.page}</a></cite></blockquote></div>`;
  const unread = n.calls.filter(c => !c.ok);
  $("#ledger").innerHTML = `<p class="verdict">${esc(scoreWords(n.score, n.ledger.length))}</p>
    ${n.synthesis?.read ? `<p style="margin:-2px 0 12px">${esc(n.synthesis.read)}</p>` : ""}
    ${main.map(one).join("")}
    ${rest.length ? `<details class="rows"><summary style="padding:10px 14px;font-size:14px;cursor:pointer">${rest.length} more that cannot be scored yet</summary><div style="padding:0 8px 8px">${rest.map(one).join("")}</div></details>` : ""}
    <p class="note">${n.calls.filter(c => c.ok).length} of ${n.calls.length} transcripts read${unread.length ? ` (${unread.map(c => `${c.date}: ${c.error}`).join("; ")})` : ""}. Quotes are checked word for word against the transcript; targets are compared with reported figures by code, not by a model. ${n.method === "rules" ? "Extraction ran on rules alone, so unusual phrasings can be missed." : ""} EBITDA margin is measured as operating profit before other income.</p>`;
  $("#srcs").innerHTML = n.calls.filter(c => c.ok).map(c => `<li><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.date)} earnings call transcript</a></li>`).join("") + (n.business?.source ? `<li><a href="${esc(n.business.source.url)}" target="_blank" rel="noopener">${esc(n.business.source.title)}, pages ${n.business.source.pages.join(", ")}</a></li>` : "");
  if (n.business) $("#business").innerHTML = `<p>${esc(n.business.what)}</p>${n.business.segments?.length ? `<table class="q" style="margin-top:8px"><tbody>${n.business.segments.map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.share || "")}</td><td class="muted" style="white-space:normal;text-align:left;padding-left:10px">${esc(s.note || "")}</td></tr>`).join("")}</tbody></table>` : ""}${n.business.geography ? `<p class="muted" style="margin-top:8px">${esc(n.business.geography)}</p>` : ""}`;
  if (n.synthesis?.bull?.length) $("#sides").innerHTML = `<div><h3 class="up">For</h3><ul>${n.synthesis.bull.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div><div><h3 class="down">Against</h3><ul>${(n.synthesis.bear || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`;
}

/* ---------- Rules ---------- */
let previewTimer = null;
function viewRules() {
  const r = S.rules, m = S.meta, book = S.book || m.portfolio;
  const cats = Object.entries(m.labels).filter(([k]) => k !== "unclassified");
  $("#view").innerHTML = `<h1>Your rules</h1><p class="muted" style="margin-top:4px">You decide what counts as unusual. FINN watches for it.</p>
    <h2>Alert me when</h2>
    <div class="rule"><p class="say">a stock moves more than <b id="pxv">±${r.px}%</b> in a day</p><input type="range" id="px" min="1" max="10" step="0.5" value="${r.px}" aria-label="Price move threshold"></div>
    <div class="rule"><p class="say">or trades more than <b id="volv">${r.vol}×</b> its <b id="lbv">${r.lookback}-day</b> average volume</p>
      <label class="cap">Multiple<input type="range" id="vol" min="1.2" max="5" step="0.1" value="${r.vol}"></label>
      <label class="cap">Averaged over<input type="range" id="lb" min="5" max="60" step="5" value="${r.lookback}"></label></div>
    <p class="preview" id="preview"></p>

    <h2>Filing types <small>Auto lets FINN rank them</small></h2>
    <div class="rows">${cats.map(([k, label]) => { const st = r.watch.includes(k) ? "watch" : r.mute.includes(k) ? "mute" : "auto"; return `<div class="cat"><span>${esc(label)}</span><span class="seg" data-cat="${k}">
      <button class="${st === "watch" ? "on alert" : ""}" data-st="watch">Always</button><button class="${st === "auto" ? "on" : ""}" data-st="auto">Auto</button><button class="${st === "mute" ? "on" : ""}" data-st="mute">Mute</button></span></div>`; }).join("")}</div>

    <h2>Your book <small>weights in % of book</small></h2>
    <div class="rows" id="bk">${book.map((h, i) => `<div class="bk"><span class="tk">${esc(h.symbol)}</span><input type="number" min="0" max="100" step="0.5" value="${h.weight}" data-i="${i}" aria-label="Weight of ${esc(h.symbol)}"><button data-rm="${i}" aria-label="Remove ${esc(h.symbol)}">×</button></div>`).join("")}</div>
    <div style="display:flex;gap:8px;margin-top:10px"><input id="add" placeholder="Add a company or ticker" style="flex:1;min-width:0;border:1px solid var(--rule);border-radius:10px;padding:9px 12px;background:var(--card)"><button class="btn" id="addb">Add</button></div>
    <div id="addres"></div>
    ${S.book ? `<button class="btn ghost" id="reset" style="margin-top:10px">Restore the default book</button>` : ""}

    <h2>Notifications</h2>
    <div class="rule"><p style="font-size:14px">While FINN is open or installed on your home screen, it checks every 10 minutes and notifies you of anything new that is worth your time.</p>
      <button class="btn ${store.get("notify", false) ? "ghost" : ""}" id="notify" style="margin-top:10px">${store.get("notify", false) ? "Turn notifications off" : "Notify me on this device"}</button></div>

    <h2>Account</h2>
    <div class="rule" id="account">${accountHtml()}</div>

    <h2>Engine</h2>
    <div class="rule kv">
      <span>Reading model</span><span>${esc(m.llm.fast || "none: rules only")}</span>
      <span>Reasoning model</span><span>${esc(m.llm.smart || "none")}</span>
      <span>Model calls, 24 h</span><span>${m.llm.today.calls} (${m.llm.today.cached} answered from cache)</span>
      <span>Model spend, 24 h</span><span>$${m.llm.today.usd.toFixed(4)}</span>
      <span>Data cache</span><span>${m.cache.hit} hits, ${m.cache.miss} misses</span>
      ${m.llm.budget ? `<span>Model reading</span><span class="down">paused: ${esc(m.llm.budget)}</span>` : ""}
    </div>
    ${S.auth?.role === "admin" ? `<h2>Operations <small>admin only</small></h2><div id="ops" class="rule"><div class="skel"></div></div>` : ""}
    <p class="note">Classification, ranking, alerts and every number are computed by code and cost nothing. A model is used only to read filings and transcripts, and FINN works without one.</p>`;

  const save = () => { store.set("rules", S.rules); S.digest = null; clearTimeout(previewTimer); previewTimer = setTimeout(preview, 350); };
  $("#px").oninput = e => { r.px = +e.target.value; $("#pxv").textContent = `±${r.px}%`; save(); };
  $("#vol").oninput = e => { r.vol = +e.target.value; $("#volv").textContent = `${r.vol}×`; save(); };
  $("#lb").oninput = e => { r.lookback = +e.target.value; $("#lbv").textContent = `${r.lookback}-day`; save(); };
  $$(".seg button").forEach(b => b.onclick = () => {
    const k = b.parentElement.dataset.cat;
    r.watch = r.watch.filter(x => x !== k); r.mute = r.mute.filter(x => x !== k);
    if (b.dataset.st === "watch") r.watch.push(k); if (b.dataset.st === "mute") r.mute.push(k);
    store.set("rules", r); S.digest = null; const y = scrollY; viewRules(); scrollTo(0, y);
  });
  const setBook = b => { S.book = b; store.set("book", b); S.digest = null; const y = scrollY; viewRules(); scrollTo(0, y); };
  $$("#bk input").forEach(i => i.onchange = () => { const b = book.map(h => ({ ...h })); b[+i.dataset.i].weight = +i.value || 0; S.book = b; store.set("book", b); S.digest = null; });
  $$("[data-rm]").forEach(x => x.onclick = () => setBook(book.filter((_, i) => i !== +x.dataset.rm)));
  const add = async () => {
    const q = $("#add").value.trim(); if (q.length < 2) return;
    $("#addres").innerHTML = `<div class="skel"></div>`;
    try {
      const hits = await api("api/search?q=" + encodeURIComponent(q));
      $("#addres").innerHTML = hits.length ? `<div class="rows" style="margin-top:8px">${hits.map(h => `<button class="row" style="width:100%;border:0;background:none;text-align:left" data-add="${esc(h.symbol)}"><span class="tk">${esc(h.symbol)}</span><span class="t">${esc(h.name)}</span></button>`).join("")}</div>` : `<p class="preview">No listed company matches “${esc(q)}”.</p>`;
      $$("[data-add]").forEach(x => x.onclick = () => { if (!book.some(h => h.symbol === x.dataset.add)) setBook([...book, { symbol: x.dataset.add, weight: 3 }]); });
    } catch (e) { $("#addres").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  };
  $("#addb").onclick = add; $("#add").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); add(); } };
  if ($("#reset")) $("#reset").onclick = () => { S.book = null; localStorage.removeItem("finn.book"); S.digest = null; viewRules(); };
  $("#notify").onclick = async () => {
    if (store.get("notify", false)) { store.set("notify", false); viewRules(); return; }
    if (!("Notification" in window)) { alert("This browser does not support notifications. On iPhone, add FINN to your home screen first."); return; }
    if (await Notification.requestPermission() === "granted") { store.set("notify", true); store.set("notified", (S.digest?.matters || []).map(p => p.id)); watch(); viewRules(); }
  };
  bindAccount();
  if ($("#ops")) loadOps();
  preview();
}
function accountHtml() {
  const me = S.meta.me;
  if (me.mode === "open") return `<p style="font-size:14px">No accounts are set up on this server, so everyone has analyst access.</p>`;
  if (S.auth) return `<div class="kv"><span>Signed in as</span><span><b>${esc(S.auth.user)}</b></span><span>Role</span><span>${esc(S.auth.role)}</span></div>
      <ul class="can">${me.can.map(c => `<li>${esc(c)}</li>`).join("")}</ul>
      <button class="btn ghost" id="signout" style="margin-top:10px">Sign out</button>`;
  return `<p style="font-size:14px">You are browsing as a guest: everything is readable, using rules. Sign in to switch on model reading and higher limits.</p>
    <form id="login" class="login" autocomplete="on">
      <input name="username" autocomplete="username" placeholder="Username" aria-label="Username" required>
      <input name="password" type="password" autocomplete="current-password" placeholder="Password" aria-label="Password" required>
      <button class="btn" type="submit">Sign in</button>
    </form><p class="preview" id="loginmsg"></p>`;
}
function bindAccount() {
  const f = $("#login");
  if (f) f.onsubmit = async e => {
    e.preventDefault();
    const body = { username: f.username.value, password: f.password.value };
    $("#loginmsg").textContent = "Signing in…";
    try {
      const r = await api("api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      S.auth = { token: r.token, user: r.me.user, role: r.me.role }; store.set("auth", S.auth);
      S.meta = await api("api/meta"); S.digest = null; toast(`Signed in as ${r.me.user}.`); viewRules();
    } catch (err) { $("#loginmsg").textContent = err.message; f.password.value = ""; f.password.focus(); }
  };
  const o = $("#signout");
  if (o) o.onclick = async () => { signOut(); S.meta = await api("api/meta"); S.digest = null; toast("Signed out."); viewRules(); };
}
async function loadOps() {
  try {
    const m = await api("api/admin/metrics");
    const up = m.uptime_s > 3600 ? `${(m.uptime_s / 3600).toFixed(1)} h` : `${Math.round(m.uptime_s / 60)} min`;
    const c = m.counts;
    $("#ops").innerHTML = `<div class="kv"><span>Uptime</span><span>${up}</span>
        <span>Requests</span><span>${c.requests || 0} (${m.status["500"] || 0} errors, ${c.rate_limited || 0} rate-limited)</span>
        <span>Requests coalesced</span><span>${c.coalesced || 0}</span>
        <span>Data cache hit rate</span><span>${m.cache.hit + m.cache.miss ? Math.round(m.cache.hit / (m.cache.hit + m.cache.miss) * 100) : 0}%</span></div>
      <table class="q" style="margin-top:12px"><thead><tr><th>Slowest routes</th><th>n</th><th>p50</th><th>p95</th></tr></thead><tbody>
        ${Object.entries(m.routes).slice(0, 6).map(([k, v]) => `<tr><td style="font-weight:400;font-size:12.5px">${esc(k.replace("GET /api/", "").replace("POST /api/", ""))}</td><td>${v.n}</td><td>${v.p50} ms</td><td>${v.p95} ms</td></tr>`).join("")}</tbody></table>
      <table class="q" style="margin-top:12px"><thead><tr><th>Recent sign-ins</th><th></th><th>When</th></tr></thead><tbody>
        ${m.audit.slice(0, 6).map(a => `<tr><td style="font-weight:400">${esc(a.user || "?")}</td><td class="${a.ok ? "up" : "down"}">${a.ok ? "ok" : "failed"}</td><td>${ago(new Date(a.ts * 1000).toISOString())}</td></tr>`).join("") || `<tr><td class="muted" colspan="3">None yet</td></tr>`}</tbody></table>`;
  } catch (e) { $("#ops").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}
async function preview() {
  const el = $("#preview"); if (!el) return;
  el.textContent = "Checking the last 30 days…";
  try {
    const d = await api("api/digest?" + params({ hours: 720 }));
    const stocks = new Set(d.movers.map(a => a.symbol)).size;
    if ($("#preview")) $("#preview").innerHTML = d.movers.length ? `With these settings you would have had <b>${d.movers.length} alert${d.movers.length > 1 ? "s" : ""}</b> across ${stocks} stock${stocks > 1 ? "s" : ""} in the last 30 days.` : `With these settings <b>nothing</b> would have alerted you in the last 30 days.`;
  } catch { if ($("#preview")) $("#preview").textContent = ""; }
}

/* ---------- ask bar ---------- */
let sugTimer = null;
function hideSuggest() { $("#suggest").hidden = true; }
$("#q").addEventListener("input", e => {
  clearTimeout(sugTimer);
  const q = e.target.value.trim();
  if (q.length < 2 || q.split(/\s+/).length > 3 || q.includes("?")) return hideSuggest();
  sugTimer = setTimeout(async () => {
    try {
      const hits = await api("api/search?q=" + encodeURIComponent(q));
      if ($("#q").value.trim() !== q || !hits.length) return hideSuggest();
      $("#suggest").innerHTML = hits.slice(0, 5).map(h => `<button type="button" data-s="${esc(h.symbol)}"><span>${esc(h.name)}</span><span class="tk">${esc(h.symbol)}</span></button>`).join("");
      $("#suggest").hidden = false;
      $$("#suggest button").forEach(b => b.onclick = () => { $("#q").value = ""; hideSuggest(); location.hash = "#research/" + b.dataset.s; });
    } catch { hideSuggest(); }
  }, 220);
});
$("#dock").addEventListener("submit", async e => {
  e.preventDefault();
  const q = $("#q").value.trim(); if (!q) return;
  hideSuggest(); $("#q").blur(); $("#go").disabled = true;
  try {
    const body = { q }; if (S.book) body.symbols = S.book.map(h => `${h.symbol}:${h.weight}`).join(",");
    const a = await api("api/ask" + (S.book ? "?symbols=" + encodeURIComponent(body.symbols) : ""), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (a.type === "digest") { S.win = { hours: a.hours }; store.set("win", S.win); location.hash === "#today" ? viewToday() : location.hash = "#today"; }
    else if (a.type === "research") location.hash = "#research/" + a.symbol;
    else if (a.type === "answer") sheet(`<p class="muted" style="font-size:13px">${esc(q)}</p>
        ${a.text ? `<p class="answer">${esc(a.text)}</p>` : `<p class="answer">${a.passages.length ? "Closest passages from the company's recent calls:" : esc(a.text || "Nothing in the recent call transcripts speaks to that.")}</p>`}
        ${a.passages.map((p, i) => `<div class="passage">${a.text ? `<b>[${i + 1}]</b> ` : ""}${esc(p.text)}<cite><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.date)} call, page ${p.page}</a></cite></div>`).join("")}
        <a class="btn" style="display:inline-block;text-decoration:none;margin-top:6px" href="#research/${esc(a.symbol)}" data-close>Open full research on ${esc(a.symbol)}</a>`);
    else sheet(`<p class="answer">${esc(a.message)}</p><p class="muted">Try “TCS”, “what changed in the last 3 days”, or “what did Infosys say about margins?”</p>`);
    $("#q").value = "";
  } catch (err) { sheet(`<div class="err">${esc(err.message)}</div>`); }
  $("#go").disabled = false;
});
function sheet(html) {
  const s = $("#sheet"); $(".panel", s).innerHTML = html; s.hidden = false;
  $$("[data-close]", s).forEach(x => x.addEventListener("click", () => s.hidden = true));
}
document.addEventListener("keydown", e => { if (e.key === "Escape") { $("#sheet").hidden = true; hideSuggest(); } });

// Voice: speak a ticker or a question. Chrome and Android; hidden elsewhere.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  const mic = $("#mic"); mic.hidden = false;
  mic.onclick = () => {
    const rec = new SR(); rec.lang = "en-IN"; rec.interimResults = false;
    mic.classList.add("live");
    rec.onresult = ev => { $("#q").value = ev.results[0][0].transcript; $("#dock").requestSubmit(); };
    rec.onend = rec.onerror = () => mic.classList.remove("live");
    rec.start();
  };
}

/* ---------- notifications while open ---------- */
let watching = null;
function watch() {
  clearInterval(watching);
  if (!store.get("notify", false) || !("Notification" in window) || Notification.permission !== "granted") return;
  watching = setInterval(async () => {
    try {
      const d = await api("api/digest?" + params({ hours: 24, fresh: 1 }));
      const known = new Set(store.get("notified", []));
      d.matters.filter(p => !known.has(p.id)).slice(0, 3).forEach(p => new Notification(`${p.symbol}: ${p.label}`, { body: p.line, tag: p.id, icon: "icon.svg" }));
      d.movers.filter(a => !known.has(a.symbol + a.date)).slice(0, 3).forEach(a => new Notification(`${a.symbol} ${pct(a.pct)}`, { body: a.text, tag: a.symbol + a.date, icon: "icon.svg" }));
      store.set("notified", [...d.matters.map(p => p.id), ...d.movers.map(a => a.symbol + a.date)]);
    } catch { /* try again next time */ }
  }, 10 * 60 * 1000);
}

/* ---------- delegated actions (no inline handlers: the CSP forbids them) ---------- */
document.addEventListener("click", e => {
  const el = e.target.closest("[data-act]");
  if (!el) return;
  if (el.dataset.act === "back") history.length > 1 ? history.back() : (location.hash = "#today");
  if (el.dataset.act === "retry-today") viewToday();
});

/* ---------- router ---------- */
function route() {
  clearTimeout(pollTimer); hideSuggest(); $("#sheet").hidden = true;
  const [name, arg] = (location.hash || "#today").slice(1).split("/");
  $$("#tabs a").forEach(a => a.classList.toggle("on", a.dataset.tab === name));
  scrollTo(0, 0);
  if (name === "research" && arg) viewResearch(decodeURIComponent(arg));
  else if (name === "book") viewBook();
  else if (name === "rules") viewRules();
  else viewToday();
}
(async function start() {
  try { S.meta = await api("api/meta"); }
  catch (e) {
    try { if (S.auth === null) S.meta = await api("api/meta"); else throw e; }   // a stale token was just dropped: retry as guest
    catch (e2) { $("#view").innerHTML = `<div class="err">FINN's server is not answering: ${esc(e2.message)}</div>`; return; }
  }
  if (S.auth && S.meta.me.user) S.auth.role = S.meta.me.role;      // roles can change server-side
  else if (S.auth) signOut();
  S.rules = { ...S.meta.rules, ...(S.rules || {}) };
  S.rules.watch ||= []; S.rules.mute ||= [];
  $("#sample").hidden = !S.meta.sample;
  const setTop = () => document.documentElement.style.setProperty("--top", $("#top").offsetHeight + "px");
  setTop(); addEventListener("resize", setTop);
  addEventListener("hashchange", route);
  route(); watch();
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});
})();
