// Research demonstrator — not a medical device.
// Polls /api/state once a second and redraws. No libraries, no internet.
"use strict";

const ticked = new Set();          // checklist ticks survive redraws (this page only)
let last = null;

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : String(k));
  return e;
}

const pad = (n) => String(n).padStart(2, "0");
function hms(t) {
  if (t == null) return "—";
  const d = new Date(t * 1000);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}
function dur(s) {
  if (s == null) return "—";
  s = Math.max(0, Math.round(s));
  if (s < 90) return `${s} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}
const slope = (v, unit) => (v == null ? "" : ` (${v > 0 ? "+" : ""}${v} ${unit})`);

// ------------------------------------------------------------------ bands
function kv(k, v) { return el("div", { class: "kv" }, el("span", { class: "k" }, k), el("span", { class: "v" }, v)); }

function checklist(b) {
  const d = b.dispatch, c = d.checklist;
  const closed = b.state === "RESOLVED";   // only when the band itself confirms
  const box = el("div", { class: "dispatch" + (closed ? " closed" : "") },
    el("div", { class: "dispatch-title" },
      closed ? "Alert closed — responder was dispatched" : "DISPATCH RESPONDER"),
    el("div", { class: "sub" },
      `Alert happened ${hms(d.alert_event_time)}, reached base ${hms(d.arrival)} (${dur(d.latency_s)} later)`),
    b.responder ? el("div", { class: "responder" },
      el("b", {}, "Responder: " + ({ dispatched: "dispatched", en_route: "on foot from the trailhead", on_scene: "on scene" })[b.responder.status]),
      b.responder.eta_min != null && b.responder.status !== "on_scene" ? ` · about ${b.responder.eta_min} min to the wearer` : "",
      ` · updated ${hms(b.responder.time)} (simulated responder)`) : null,
    el("h3", {}, "Why"),
    el("div", {},
      d.reasons.map((r) => el("span", { class: "pill alert" }, r)),
      b.reasons.filter((r) => !d.reasons.includes(r))
        .map((r) => el("span", { class: "pill alert" }, r + " (since dispatch)"))),
    el("h3", {}, "Payload class"),
    el("div", {}, el("b", {}, c.label), d.families.length ? ` — families: ${d.families.join(", ")}` : ""),
    el("h3", {}, "What the responder carries"),
    el("ul", { class: "carry" }, c.carry.map((x) => el("li", {}, x))),
    el("h3", {}, "Reminders"),
    el("ul", { class: "checks" }, c.reminders.map((r) => {
      const key = b.device_id + "|" + r;
      const cb = el("input", { type: "checkbox", checked: ticked.has(key),
        onchange: (e) => (e.target.checked ? ticked.add(key) : ticked.delete(key)) });
      return el("li", {}, el("label", {}, cb, el("span", {}, r)));
    })),
    c.status === "PLACEHOLDER"
      ? el("div", { class: "placeholder" }, "PLACEHOLDER content — to be supplied by a toxinologist (R-08). Not treatment instructions.")
      : null);
  return box;
}

function bandCard(b, now) {
  const v = b.vitals;
  const stale = b.age_s > 900;
  const card = el("article", { class: "band " + b.state },
    el("div", { class: "band-head" },
      el("div", {},
        el("div", { class: "band-id" }, `Band ${b.device_id} · ${b.wear_site}`),
        el("div", { class: "state" }, b.state_title),
        el("p", { class: "state-text" }, b.state_text),
        b.last_note ? el("div", { class: "sub" }, b.last_note) : null),
      el("div", { class: "age" + (stale ? " stale" : "") },
        "Last message ", el("b", {}, b.last_type), el("br"),
        "happened ", el("b", {}, hms(b.event_time)), el("br"),
        "data is ", el("b", {}, dur(b.age_s)), " old",
        b.delay_s > 120 ? el("div", {}, `held ${dur(b.delay_s)} by link loss`) : null)),
    el("div", {},
      b.families.map((f) => el("span", { class: "pill" }, `${f.name}: ${f.level}`)),
      b.test_invalid ? el("span", { class: "pill warn" }, "Test invalid (control line failed)") : null,
      b.unclassified ? el("span", { class: "pill warn" }, "Positive, family unclassified") : null,
      b.flags.sensor_expired ? el("span", { class: "pill warn" }, "Sensor patch expired") : null,
      b.flags.battery_low ? el("span", { class: "pill warn" }, "Battery low") : null,
      !b.flags.gps_valid ? el("span", { class: "pill warn" }, "No GPS fix") : null),
    el("div", { class: "grid2" },
      kv("SpO2", v.spo2 == null ? "—" : `${v.spo2} %${slope(v.spo2_slope, "%/10 min")}`),
      kv("Breathing rate", v.rr == null ? "—" : `${v.rr} /min${slope(v.rr_slope, "/10 min")}`),
      kv("Heart rate", v.hr == null ? "—" : `${v.hr} bpm`),
      kv("Skin temp", v.skin_temp == null ? "—" : `${v.skin_temp.toFixed(1)} °C`),
      kv("Local signal from", b.local_source),
      kv("Battery", b.battery == null ? "—" : `${b.battery} %`),
      kv("Sensor patch age", b.sensor_age_min == null ? "—" : dur(b.sensor_age_min * 60)),
      kv("GPS fix age", b.position && b.position.fix_age_s != null ? dur(b.position.fix_age_s) : "—")));

  if (b.dispatch) card.append(checklist(b));
  for (const c of b.cancelled_after_dispatch)
    card.append(el("div", { class: "banner" },
      `Local team cancelled at ${hms(c.event_time)} after a responder was dispatched. ` +
      "Decide whether to recall the responder (R-18)."));
  if (b.stale_alerts)
    card.append(el("div", { class: "sub" }, `${b.stale_alerts} late alert(s) ignored: they arrived after the band's own cancel (R-20).`));
  if (b.can_resolve)
    card.append(el("div", { class: "actions" }, el("button", { onclick: () => resolve(b.device_id) },
      "Responder on scene — close alert")));
  if (b.resolved_by_base && b.state === "ESCALATED")
    card.append(el("div", { class: "sub" }, `Close sent at ${hms(b.resolved_by_base)}; waiting for the band to confirm (needs sky).`));
  return card;
}

async function resolve(id) {
  if (!confirm(`Close the alert for band ${id}? This sends RESOLVE to the band.`)) return;
  await fetch("/api/resolve", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: id }) });
  poll();
}

// ------------------------------------------------------------------ plot
const SVGNS = "http://www.w3.org/2000/svg";
function s(tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}
function niceStep(span) {
  const raw = span / 4, p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 5, 10]) if (m * p >= raw) return m * p;
  return 10 * p;
}
function haversineKm(a, b) {
  const R = 6371, r = Math.PI / 180;
  const dlat = (b.lat - a.lat) * r, dlon = (b.lon - a.lon) * r;
  const h = Math.sin(dlat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dlon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function bearing(a, b) {
  const r = Math.PI / 180;
  const y = Math.sin((b.lon - a.lon) * r) * Math.cos(b.lat * r);
  const x = Math.cos(a.lat * r) * Math.sin(b.lat * r) - Math.sin(a.lat * r) * Math.cos(b.lat * r) * Math.cos((b.lon - a.lon) * r);
  const deg = (Math.atan2(y, x) / r + 360) % 360;
  return `${Math.round(deg)}° ${["N","NE","E","SE","S","SW","W","NW"][Math.round(deg / 45) % 8]}`;
}

function drawPlot(st) {
  const box = document.getElementById("plot"), coords = document.getElementById("coords");
  const base = st.base_position;
  const pts = st.bands.filter((b) => b.position);
  box.replaceChildren(); coords.replaceChildren();
  if (!pts.length && !base) { box.append(el("p", { class: "sub" }, "No position yet.")); return; }
  const all = pts.map((b) => b.position).concat(base ? [base] : []);
  const lat0 = all.reduce((a, p) => a + p.lat, 0) / all.length;
  const lon0 = all.reduce((a, p) => a + p.lon, 0) / all.length;
  const kx = 111.32 * Math.cos(lat0 * Math.PI / 180), ky = 110.57;   // km per degree
  const xy = (p) => [(p.lon - lon0) * kx, (p.lat - lat0) * ky];
  let half = 0.5;
  for (const p of all) { const [x, y] = xy(p); half = Math.max(half, Math.abs(x) * 1.25, Math.abs(y) * 1.25); }
  const W = 480, H = 360, sc = Math.min(W, H) / 2 / half;
  const px = (p) => { const [x, y] = xy(p); return [W / 2 + x * sc, H / 2 - y * sc]; };
  const css = getComputedStyle(document.documentElement);
  const col = (n) => css.getPropertyValue(n).trim();
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Position plot" });
  const step = niceStep(half * 2 * W / Math.min(W, H));
  for (let v = -Math.ceil(half * 2 / step) * step; v <= half * 2; v += step) {
    const gx = W / 2 + v * sc, gy = H / 2 - v * sc;
    if (gx >= 0 && gx <= W) svg.append(s("line", { x1: gx, y1: 0, x2: gx, y2: H, stroke: col("--grid") }));
    if (gy >= 0 && gy <= H) svg.append(s("line", { x1: 0, y1: gy, x2: W, y2: gy, stroke: col("--grid") }));
  }
  // scale bar + north arrow
  svg.append(s("line", { x1: 16, y1: H - 18, x2: 16 + step * sc, y2: H - 18, stroke: col("--ink"), "stroke-width": 2 }));
  svg.append(s("text", { x: 16, y: H - 24, "font-size": 11, fill: col("--muted") }, `${step >= 1 ? step : step * 1000} ${step >= 1 ? "km" : "m"}`));
  svg.append(s("text", { x: W - 18, y: 20, "font-size": 12, "font-weight": 700, fill: col("--muted"), "text-anchor": "middle" }, "N ↑"));
  if (base) {
    const [x, y] = px(base);
    svg.append(s("rect", { x: x - 6, y: y - 6, width: 12, height: 12, fill: col("--accent") }));
    svg.append(s("text", { x: x + 10, y: y + 4, "font-size": 12, fill: col("--ink") }, "Base"));
  }
  for (const b of pts) {
    const color = b.state === "ESCALATED" ? col("--alert")
      : ["RESOLVED", "STOOD_DOWN", "IDLE"].includes(b.state) ? col("--ok") : col("--warn");
    if (b.track.length > 1)
      svg.append(s("polyline", { points: b.track.map((p) => px(p).join(",")).join(" "), fill: "none",
        stroke: color, "stroke-width": 1.5, "stroke-dasharray": "4 3" }));
    if (base) {
      const [bx, by] = px(base), [x, y] = px(b.position);
      svg.append(s("line", { x1: bx, y1: by, x2: x, y2: y, stroke: col("--muted"), "stroke-width": 1, "stroke-dasharray": "2 4" }));
    }
    const [x, y] = px(b.position);
    svg.append(s("circle", { cx: x, cy: y, r: 8, fill: color, stroke: col("--panel"), "stroke-width": 2 }));
    if (b.responder && b.responder.lat != null) {
      const [rx, ry] = px(b.responder);
      svg.append(s("path", { d: `M${rx} ${ry - 8} L${rx + 7} ${ry + 6} L${rx - 7} ${ry + 6} Z`, fill: col("--info"), stroke: col("--panel"), "stroke-width": 2 }));
      svg.append(s("text", { x: rx + 10, y: ry + 14, "font-size": 11, fill: col("--muted") }, "Responder"));
    }
    svg.append(s("text", { x: x + 12, y: y - 8, "font-size": 12, "font-weight": 700, fill: col("--ink") }, `Band ${b.device_id}`));
    const line = `Band ${b.device_id}: ${b.position.lat.toFixed(6)}, ${b.position.lon.toFixed(6)}` +
      (base ? ` — ${haversineKm(base, b.position).toFixed(2)} km ${bearing(base, b.position)} from base` : "") +
      (b.position.fix_age_s != null ? ` · fix ${dur(b.position.fix_age_s)} old` : "");
    coords.append(el("div", {}, line));
  }
  box.append(svg);
}

// ------------------------------------------------------------------ log
function drawLog(st) {
  const tb = document.getElementById("log");
  tb.replaceChildren(...st.log.map((r) => el("tr", {},
    el("td", {}, hms(r.arrival)),
    el("td", {}, r.device_id),
    el("td", { class: "t-" + r.type }, r.type + (r.retransmission ? " (retry)" : "")),
    el("td", {}, hms(r.event_time)),
    el("td", { class: r.delay_s > 120 ? "late" : "" }, dur(r.delay_s)))));
  document.getElementById("log-note").textContent =
    `${st.log.length} unique · ${st.duplicates} duplicate(s) ignored` + (st.rejected.length ? ` · ${st.rejected.length} rejected` : "");
}

// ------------------------------------------------------------------ main loop
function draw(st) {
  document.getElementById("clock").textContent = hms(st.now);
  document.getElementById("clock-kind").textContent = st.sim_clock ? "UTC · simulated time" : "UTC";
  document.getElementById("scenario").textContent = st.scenario ? `Scenario: ${st.scenario}` : "No scenario running";
  const bands = document.getElementById("bands");
  if (st.bands.length) {
    const order = { ESCALATED: 0, SYSTEMIC_WATCH: 1, CONTACT: 1, SYSTEMIC_ONLY: 2 };
    const sorted = [...st.bands].sort((a, b) => (order[a.state] ?? 3) - (order[b.state] ?? 3));
    bands.replaceChildren(...sorted.map((b) => bandCard(b, st.now)));
  }
  drawPlot(st);
  drawLog(st);
}

async function poll() {
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    const st = await r.json();
    const sig = JSON.stringify(st);
    if (sig !== last) { last = sig; draw(st); }
  } catch (e) {
    document.getElementById("clock-kind").textContent = "dashboard server not reachable";
  }
}
poll();
setInterval(poll, 1000);
