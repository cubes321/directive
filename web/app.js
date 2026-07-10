/* DIRECTIVE — theater commander's desk */

"use strict";

const $ = (sel) => document.querySelector(sel);
const SVG_NS = "http://www.w3.org/2000/svg";

/* All dynamic text (LLM dispatches, user directives, data files) is escaped
   before any innerHTML interpolation; long free text uses textContent. */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

let snap = null;
let highlightedCorps = new Set();
const prevMorale = {}; // commander id -> last-rendered dynamic, so bars can tween
let directiveTimers = {};

/* ── api ─────────────────────────────────────────── */

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch {}
    const err = new Error(detail);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

function toast(msg, ok = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("ok", ok);
  t.classList.remove("hidden");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => t.classList.add("hidden"), 6000);
}

/* ── boot ────────────────────────────────────────── */

async function boot() {
  try {
    snap = await api("/api/game");
  } catch (e) {
    if (e.status !== 404) {
      // a real error, not "no game yet" — never silently discard a campaign
      toast("Could not load the campaign: " + e.message);
      return;
    }
    try {
      snap = await api("/api/game/new", { method: "POST" });
      toast("New campaign begun. 22 June 1941, 03:15 — Barbarossa is under way.", true);
    } catch (e2) {
      toast("Could not start a campaign: " + e2.message);
      return;
    }
  }
  renderAll();
}

/* ── header ──────────────────────────────────────── */

const WEATHER_LABEL = { clear: "CLEAR", mud: "MUD ◆ RASPUTITSA", snow: "SNOW ❄" };

function renderHeader() {
  $("#hud-date").textContent = snap.date;
  $("#hud-turn").textContent = String(snap.turn).padStart(2, "0");
  $("#hud-weather").textContent = WEATHER_LABEL[snap.weather] || snap.weather.toUpperCase();
  const cap = snap.political_capital;
  $("#hud-capital").textContent =
    "▰".repeat(Math.max(0, Math.min(10, cap))) +
    "▱".repeat(Math.max(0, 10 - cap)) + " " + cap;
  $("#hud-vp").textContent = `AXIS ${snap.victory_points.axis} · SOVIET ${snap.victory_points.soviet}`;
}

/* ── map ─────────────────────────────────────────── */

function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function renderMap() {
  const svg = $("#map");
  svg.textContent = "";
  const regionById = {};
  snap.regions.forEach((r) => (regionById[r.id] = r));

  const railhead = new Set(snap.railhead || []);
  const supplyLegs = snap.supply_legs || {};
  const gEdges = el("g", {}, svg);
  for (const e of snap.edges) {
    const a = regionById[e.a], b = regionById[e.b];
    el("line", {
      x1: a.x, y1: a.y, x2: b.x, y2: b.y,
      class: "edge-road" + (e.road === "highway" ? " highway" : ""),
      "stroke-dasharray": e.road === "none" ? "3 4" : "none",
    }, gEdges);
    if (e.rail) {
      // rail that both ends have converted carries supply freely — draw it live
      const supplied = railhead.has(e.a) && railhead.has(e.b);
      const cls = supplied ? "edge-rail supplied" : "edge-rail";
      el("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: cls }, gEdges);
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy);
      const nx = -dy / len, ny = dx / len;
      const ticks = Math.floor(len / 16);
      const gT = el("g", { class: supplied ? "edge-rail-ticks supplied" : "edge-rail-ticks" }, gEdges);
      for (let i = 1; i < ticks; i++) {
        const t = i / ticks;
        const px = a.x + dx * t, py = a.y + dy * t;
        el("line", { x1: px - nx * 2.6, y1: py - ny * 2.6, x2: px + nx * 2.6, y2: py + ny * 2.6 }, gT);
      }
    }
  }

  const ownByRegion = {};
  for (const c of snap.corps) (ownByRegion[c.location] ||= []).push(c);

  const gNodes = el("g", {}, svg);
  for (const r of snap.regions) {
    const g = el("g", { class: `region-node ${r.control}`, "data-region": r.id }, gNodes);
    if (r.id in supplyLegs) {
      // supply gradient: 0 legs = supplied (blue) ... 3+ = beyond supply (red)
      const legs = supplyLegs[r.id];
      const cls = legs === 0 ? "supply-halo l0"
                : legs === 1 ? "supply-halo l1"
                : legs === 2 ? "supply-halo l2"
                : "supply-halo l3";
      el("circle", { cx: r.x, cy: r.y, r: 15, class: cls }, g);
    }
    if (railhead.has(r.id)) {
      el("circle", { cx: r.x, cy: r.y, r: 11, class: "railhead-ring" }, g);
    }
    if (r.terrain === "urban") {
      el("rect", { x: r.x - 7, y: r.y - 7, width: 14, height: 14, class: "base" }, g);
    } else {
      el("circle", { cx: r.x, cy: r.y, r: 7, class: "base" }, g);
    }
    if (r.terrain === "marsh") {
      for (const off of [-3, 0, 3])
        el("line", { x1: r.x - 4, y1: r.y + off, x2: r.x + 4, y2: r.y + off, stroke: "#5a6b4f", "stroke-width": 1 }, g);
    }
    if (r.victory_points > 0) {
      const sx = r.x + 10, sy = r.y - 10;
      el("path", { d: starPath(sx, sy, 5.5), class: "vp-star" }, g);
      el("text", { x: sx + 7, y: sy + 3, class: "vp-num" }, g).textContent = r.victory_points;
    }
    el("text", { x: r.x, y: r.y + 20, class: "region-label" }, g).textContent = r.name;

    const own = ownByRegion[r.id] || [];
    if (own.length) {
      const ids = own.map((c) => c.id);
      const base = ids.some((id) => highlightedCorps.has(id)) ? "counter own hl" : "counter own";
      const gc = el("g", { class: `${base} ${supplyBand(own)}` }, g);
      el("rect", { x: r.x - 11, y: r.y - 24, width: 22, height: 13 }, gc);
      el("text", { x: r.x, y: r.y - 14 }, gc).textContent = `${own.length}⨯`;
      const commanders = [...new Set(own.map((c) => commanderSurname(c.commander)))];
      el("text", { x: r.x, y: r.y - 28, class: "commander-label" }, gc).textContent =
        commanders.join(" / ");
    }
    const contacts = snap.contacts[r.id] || [];
    if (contacts.length) {
      const gc = el("g", { class: "counter enemy" }, g);
      el("rect", { x: r.x - 11, y: r.y - (own.length ? 40 : 24), width: 22, height: 13 }, gc);
      el("text", { x: r.x, y: r.y - (own.length ? 30 : 14) }, gc).textContent = `${contacts.length}?`;
    }

    g.addEventListener("click", (ev) => showRegionPop(r, own, contacts, ev));
  }

  svg.addEventListener("click", (ev) => {
    if (ev.target === svg) $("#region-pop").classList.add("hidden");
  });
}

function commanderSurname(commanderId) {
  const cmd = snap.commanders.find((c) => c.id === commanderId);
  if (!cmd) return commanderId.toUpperCase();
  return cmd.name.split(" ").pop().toUpperCase();
}

// Lowest supply in a stack decides the counter colour — one starving corps
// should light the whole marker. Thresholds match the supply model + the
// staff's "supply critical (<40)" language.
function supplyBand(corpsList) {
  const min = Math.min(...corpsList.map((c) => Number(c.supply)));
  if (min < 40) return "sup-red";
  if (min < 75) return "sup-amber";
  return "sup-green";
}

function starPath(cx, cy, r) {
  let d = "";
  for (let i = 0; i < 10; i++) {
    const ang = -Math.PI / 2 + (i * Math.PI) / 5;
    const rad = i % 2 === 0 ? r : r * 0.45;
    d += (i ? "L" : "M") + (cx + rad * Math.cos(ang)).toFixed(1) + " " + (cy + rad * Math.sin(ang)).toFixed(1);
  }
  return d + "Z";
}

function showRegionPop(region, own, contacts, ev) {
  const pop = $("#region-pop");
  let html = `<h4>${esc(region.name)}</h4>
    <div class="meta">${esc(region.terrain)}${region.victory_points ? ` · ★${region.victory_points}` : ""} · held by ${esc(region.control.toUpperCase())}</div><ul>`;
  for (const c of own) {
    html += `<li><b>${esc(c.name)}</b><br>
      str <span class="bar" style="width:${Number(c.strength) * 0.45}px"></span> ${Number(c.strength)}
      · org ${Number(c.organization)} · sup ${Number(c.supply)}</li>`;
  }
  for (const k of contacts) {
    html += `<li><b>enemy ${esc(k.kind)}</b> — est. strength <span class="bar red" style="width:${Number(k.estimated_strength) * 0.45}px"></span> ~${Number(k.estimated_strength)}</li>`;
  }
  if (!own.length && !contacts.length) html += "<li>No formations reported.</li>";
  pop.innerHTML = html + "</ul>";
  pop.classList.remove("hidden");
  const frame = $(".map-frame").getBoundingClientRect();
  const x = ev.clientX - frame.left + 14, y = ev.clientY - frame.top + 10;
  pop.style.left = Math.min(x, frame.width - 290) + "px";
  pop.style.top = Math.min(y, frame.height - 160) + "px";
}

/* ── dispatches ──────────────────────────────────── */

function renderDispatches() {
  const page = $("#tab-dispatches");
  page.textContent = "";
  if (!snap.dispatches.length) {
    const div = document.createElement("div");
    div.className = "empty-note";
    div.textContent = "No dispatches yet. Issue your directives and end the week — the commanders will report.";
    page.appendChild(div);
    return;
  }
  const byName = {};
  snap.commanders.forEach((c) => (byName[c.id] = c));
  let lastTurn = null;
  [...snap.dispatches].reverse().forEach((d) => {
    if (d.turn !== lastTurn) {
      lastTurn = d.turn;
      const div = document.createElement("div");
      div.className = "turn-divider";
      div.textContent = `WEEK ${d.turn}`;
      page.appendChild(div);
    }
    const card = document.createElement("div");
    if (d.commander === "staff") {
      card.className = "dispatch staff";
      card.innerHTML = `
        <div class="geheim">STAB</div>
        <div class="from">Chief of Staff — Genmaj. von Greiffenberg</div>
        <div class="meta">WEEKLY STAFF ASSESSMENT · WEEK ${Number(d.turn)}</div>
        <div class="body"></div>`;
    } else if (d.commander === "okh") {
      card.className = "dispatch okh";
      card.innerHTML = `
        <div class="geheim">OKH</div>
        <div class="from">Oberkommando des Heeres</div>
        <div class="meta">DIRECTIVE · WEEK ${Number(d.turn)}</div>
        <div class="body"></div>`;
    } else {
      const cmd = byName[d.commander];
      card.className = "dispatch";
      card.innerHTML = `
        <div class="geheim">GEHEIM</div>
        <div class="from">${esc(cmd ? cmd.name : d.commander)}</div>
        <div class="meta">${esc(cmd ? cmd.role : "")} · WEEK ${Number(d.turn)}</div>
        <div class="body"></div>`;
    }
    card.querySelector(".body").textContent = d.text;
    page.appendChild(card);
  });
}

/* ── commanders ──────────────────────────────────── */

function renderCommanders() {
  const page = $("#tab-commanders");
  page.textContent = "";
  for (const cmd of snap.commanders) {
    const card = document.createElement("div");
    card.className = "cmd-card";
    const initials = esc(cmd.name.split(" ").pop().slice(0, 2).toUpperCase());
    const traits = Object.entries(cmd.traits)
      .map(([k, v]) => `
        <div class="trait"><span class="tname">${esc(k)}</span>
        <span class="tbar"><span class="tfill" style="width:${Number(v) * 10}%"></span></span></div>`)
      .join("");
    const prev = prevMorale[cmd.id] || cmd.dynamic || {};
    const morale = cmd.dynamic
      ? ["confidence", "fatigue", "relationship"]
          .map((k) => {
            const from = Number(prev[k] ?? cmd.dynamic[k]) * 10;
            const to = Number(cmd.dynamic[k]) * 10;
            return `
        <div class="morale-row"><span class="mname">${k}</span>
        <span class="mbar"><span class="mfill ${k}" style="width:${from}%" data-to="${to}"></span></span></div>`;
          })
          .join("")
      : "";
    const record = cmd.track_record.length
      ? cmd.track_record.map((r) => `<li><b>W${Number(r.turn)}</b> ${esc(r.summary)}</li>`).join("")
      : "<li>(The campaign is just beginning.)</li>";
    const benchOpts = snap.bench
      .map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`)
      .join("");
    card.innerHTML = `
      <div class="cmd-head">
        <div class="cmd-photo">${initials}</div>
        <div>
          <div class="cmd-name">${esc(cmd.name)}</div>
          <div class="cmd-role">${esc(cmd.role)}</div>
          <div class="cmd-corps">${esc(cmd.corps.join(" · "))}</div>
        </div>
      </div>
      <div class="traits">${traits}</div>
      <div class="morale"><h5>STATE OF MIND</h5>${morale}</div>
      <div class="record"><h5>SERVICE RECORD</h5><ul>${record}</ul></div>
      <div class="directive-box">
        <label>YOUR DIRECTIVE TO ${esc(cmd.name.split(" ").pop().toUpperCase())}</label>
        <textarea data-cmd="${esc(cmd.id)}" placeholder="State your intent. He will interpret it — his way."></textarea>
        <div class="directive-saved" data-saved="${esc(cmd.id)}"></div>
      </div>
      <div class="dismiss-row">
        ${snap.bench.length
          ? `<select data-replace="${esc(cmd.id)}">${benchOpts}</select>
             <button class="dismiss-btn" data-dismiss="${esc(cmd.id)}">RELIEVE</button>`
          : `<span class="dismiss-cost">No replacement available.</span>`}
        <span class="dismiss-cost">costs ${Number(cmd.dismissal_cost)} standing</span>
        <span class="spacer"></span>
        <button class="chat-toggle" data-chat="${esc(cmd.id)}">⚡ SIGNAL</button>
      </div>
      <div class="chat hidden" data-chatbox="${esc(cmd.id)}">
        <div class="chat-log" data-chatlog="${esc(cmd.id)}"></div>
        <div class="chat-row">
          <input data-chatmsg="${esc(cmd.id)}" maxlength="500"
                 placeholder="Signal ${esc(cmd.name.split(" ").pop())}…">
          <button data-chatsend="${esc(cmd.id)}">SEND</button>
        </div>
      </div>`;
    card.querySelector("textarea").value = snap.directives[cmd.id] || "";
    card.addEventListener("mouseenter", () => {
      highlightedCorps = new Set(cmd.corps);
      renderMap();
    });
    card.addEventListener("mouseleave", () => {
      highlightedCorps = new Set();
      renderMap();
    });
    page.appendChild(card);
  }

  // Bars were rendered at their previous width; on the next frame slide them to
  // the current value so a mood shift visibly animates. Then cache the current
  // values for the next render.
  requestAnimationFrame(() => {
    page.querySelectorAll(".mfill[data-to]").forEach((f) => {
      f.style.width = f.dataset.to + "%";
    });
  });
  for (const cmd of snap.commanders) {
    if (cmd.dynamic) prevMorale[cmd.id] = { ...cmd.dynamic };
  }

  page.querySelectorAll("textarea[data-cmd]").forEach((ta) => {
    ta.addEventListener("input", () => {
      const id = ta.dataset.cmd;
      clearTimeout(directiveTimers[id]);
      directiveTimers[id] = setTimeout(async () => {
        try {
          await api("/api/game/directives", {
            method: "POST",
            body: JSON.stringify({ [id]: ta.value }),
          });
          snap.directives[id] = ta.value;
          const s = page.querySelector(`[data-saved="${CSS.escape(id)}"]`);
          s.textContent = "✓ transmitted to staff";
          setTimeout(() => (s.textContent = ""), 2500);
        } catch (e) {
          toast("Directive not saved: " + e.message);
        }
      }, 600);
    });
  });

  page.querySelectorAll("button[data-chat]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.chat;
      const box = page.querySelector(`[data-chatbox="${CSS.escape(id)}"]`);
      box.classList.toggle("hidden");
      if (!box.classList.contains("hidden")) {
        renderChatLog(id);
        box.querySelector("input").focus();
      }
    });
  });

  page.querySelectorAll("button[data-chatsend]").forEach((btn) => {
    btn.addEventListener("click", () => sendSignal(btn.dataset.chatsend));
  });
  page.querySelectorAll("input[data-chatmsg]").forEach((input) => {
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") sendSignal(input.dataset.chatmsg);
    });
  });

  page.querySelectorAll("button[data-dismiss]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.dismiss;
      const sel = page.querySelector(`select[data-replace="${CSS.escape(id)}"]`);
      const cmd = snap.commanders.find((c) => c.id === id);
      if (!confirm(`Relieve ${cmd.name} of command and hand his formations to ${sel.selectedOptions[0].textContent}?`)) return;
      try {
        const r = await api("/api/game/dismiss", {
          method: "POST",
          body: JSON.stringify({ commander: id, replacement: sel.value }),
        });
        toast(`Done. It cost you ${r.cost} standing with OKH.`, true);
        snap = await api("/api/game");
        renderAll();
      } catch (e) {
        toast(e.message);
      }
    });
  });
}

function renderChatLog(commanderId) {
  const log = document.querySelector(`[data-chatlog="${CSS.escape(commanderId)}"]`);
  if (!log) return;
  log.textContent = "";
  const thread = (snap.conversations || {})[commanderId] || [];
  if (!thread.length) {
    const empty = document.createElement("div");
    empty.className = "chat-empty";
    empty.textContent = "The line is open.";
    log.appendChild(empty);
  }
  for (const line of thread) {
    const div = document.createElement("div");
    div.className = "chat-line " + line.role + (line.unprompted ? " unprompted" : "");
    const who = document.createElement("b");
    who.textContent = line.role === "player" ? "YOU" : commanderSurname(commanderId);
    div.appendChild(who);
    if (line.unprompted) {
      const mark = document.createElement("span");
      mark.className = "unprompted-mark";
      mark.textContent = " ✦ unprompted";
      div.appendChild(mark);
    }
    div.appendChild(document.createTextNode(" " + line.text));
    log.appendChild(div);
  }
  log.scrollTop = log.scrollHeight;
}

function openSignalDrawer(commanderId) {
  document.querySelector('[data-tab="commanders"]').click();
  const box = document.querySelector(`[data-chatbox="${CSS.escape(commanderId)}"]`);
  if (!box) return;
  box.classList.remove("hidden");
  renderChatLog(commanderId);
  box.scrollIntoView({ behavior: "smooth", block: "center" });
  const input = box.querySelector("input");
  if (input) input.focus();
}

async function sendSignal(commanderId) {
  const input = document.querySelector(`input[data-chatmsg="${CSS.escape(commanderId)}"]`);
  const btn = document.querySelector(`button[data-chatsend="${CSS.escape(commanderId)}"]`);
  const message = input.value.trim();
  if (!message) return;
  input.disabled = btn.disabled = true;
  btn.textContent = "…";
  snap.conversations[commanderId] = snap.conversations[commanderId] || [];
  snap.conversations[commanderId].push({ turn: snap.turn, role: "player", text: message });
  renderChatLog(commanderId);
  try {
    const r = await api("/api/game/converse", {
      method: "POST",
      body: JSON.stringify({ commander: commanderId, message }),
    });
    snap.conversations[commanderId].push({ turn: snap.turn, role: "commander", text: r.reply });
    input.value = "";
  } catch (e) {
    snap.conversations[commanderId].pop(); // the message never got through
    toast("Signal failed: " + e.message);
  } finally {
    input.disabled = btn.disabled = false;
    btn.textContent = "SEND";
    renderChatLog(commanderId);
    input.focus();
  }
}

/* ── order of battle ─────────────────────────────── */

function renderOob() {
  const page = $("#tab-oob");
  page.textContent = "";
  const regionName = {};
  snap.regions.forEach((r) => (regionName[r.id] = r.name));
  const byCommander = {};
  for (const c of snap.corps) (byCommander[c.commander] ||= []).push(c);

  for (const cmd of snap.commanders) {
    const corps = byCommander[cmd.id] || [];
    const card = document.createElement("div");
    card.className = "oob-card";
    card.innerHTML = `
      <div class="oob-head">
        <span class="oob-cmd">${esc(cmd.name)}</span>
        <span class="oob-role">${esc(cmd.role)} · ${corps.length} corps</span>
      </div>`;
    const table = document.createElement("table");
    table.className = "oob-table";
    table.innerHTML = `<thead><tr>
      <th>FORMATION</th><th>AT</th><th>STR</th><th>ORG</th><th>SUP</th>
    </tr></thead>`;
    const tbody = document.createElement("tbody");
    for (const c of corps) {
      const tr = document.createElement("tr");
      const cells = [
        `${c.name}${c.kind === "panzer" ? " ⛭" : ""}`,
        regionName[c.location] || c.location,
        c.strength, c.organization, c.supply,
      ];
      cells.forEach((v, i) => {
        const td = document.createElement("td");
        td.textContent = v;
        if (i >= 2 && Number(v) < 40) td.className = "low";
        tr.appendChild(td);
      });
      tr.addEventListener("mouseenter", () => {
        highlightedCorps = new Set([c.id]);
        renderMap();
      });
      tr.addEventListener("mouseleave", () => {
        highlightedCorps = new Set();
        renderMap();
      });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    card.appendChild(table);
    page.appendChild(card);
  }
}

/* ── battles ─────────────────────────────────────── */

function renderBattles() {
  const page = $("#tab-battles");
  page.textContent = "";
  const rep = snap.last_report;
  if (!rep || !rep.combats.length) {
    const div = document.createElement("div");
    div.className = "empty-note";
    div.textContent = "No battle reports this week.";
    page.appendChild(div);
    return;
  }
  const regionName = {};
  snap.regions.forEach((r) => (regionName[r.id] = r.name));
  for (const c of rep.combats) {
    const div = document.createElement("div");
    const axisAttacking = !c.attackers[0].startsWith("sov_");
    const won = c.outcome === "defender_retreated";
    const good = axisAttacking ? won : !won;
    div.className = "battle-line" + (good ? "" : " lost");
    const where = document.createElement("span");
    where.className = "where";
    where.textContent = regionName[c.region] || c.region;
    div.appendChild(where);
    div.appendChild(document.createTextNode(
      ` — ${c.attackers.join(", ")} attacked ${c.defenders.join(", ")} at odds ${c.odds}. ` +
      (won ? (c.encircled ? "Defenders encircled and destroyed." : "Position carried; defenders thrown back.")
           : "Assault repulsed.") +
      ` Losses: attacker ${c.attacker_losses}, defender ${c.defender_losses}.`
    ));
    page.appendChild(div);
  }
}

/* ── end turn ────────────────────────────────────── */

const TICKER_LINES = [
  "Encoding orders on the Enigma net…",
  "Couriers departing for the panzer groups…",
  "Guderian is reading your directive. He has opinions.",
  "Staff officers shading the situation map…",
  "Radio intercepts coming in from the east…",
  "Kluge requests written confirmation. Again.",
  "Air reconnaissance developing photographs…",
  "The commanders are composing their replies…",
];

async function endTurn() {
  const btn = $("#btn-endturn");
  btn.disabled = true;
  $("#overlay").classList.remove("hidden");
  const t0 = Date.now();
  let line = 0;
  $("#overlay-ticker").textContent = TICKER_LINES[0];
  const ticker = setInterval(() => {
    $("#overlay-ticker").textContent = TICKER_LINES[++line % TICKER_LINES.length];
  }, 3500);
  const clock = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    $("#overlay-elapsed").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);
  try {
    snap = await api("/api/game/end-turn", { method: "POST" });
    renderAll();
    const combats = snap.last_report ? snap.last_report.combats.length : 0;
    toast(`Week ${snap.turn - 1} resolved — ${combats} engagement${combats === 1 ? "" : "s"}. New dispatches in.`, true);
    document.querySelector('[data-tab="dispatches"]').click();
  } catch (e) {
    toast(e.message);
  } finally {
    clearInterval(ticker);
    clearInterval(clock);
    $("#overlay").classList.add("hidden");
    btn.disabled = false;
  }
}

/* ── wiring ──────────────────────────────────────── */

function renderVerdict() {
  const v = snap.victory;
  $("#verdict").classList.toggle("hidden", !v);
  $("#btn-endturn").disabled = !!v;
  if (!v) return;
  const title = $("#verdict-title");
  if (v.kind === "relieved") {
    $("#verdict-kind").textContent = `DISMISSED — ${snap.date}`;
    title.textContent = "RELIEVED OF COMMAND";
    title.className = "verdict-title soviet";
  } else {
    $("#verdict-kind").textContent = `${v.kind.toUpperCase()} VICTORY — ${snap.date}`;
    title.textContent = v.winner === "axis" ? "MOSCOW BECKONS NO MORE" : "THE FRONT HELD";
    if (v.winner === "axis" && v.kind === "decisive") title.textContent = "MOSCOW HAS FALLEN";
    title.className = "verdict-title " + v.winner;
  }
  $("#verdict-reason").textContent = v.reason;
}

/* ── OKH objectives ──────────────────────────────── */

function renderObjectives() {
  const bar = $("#objectives-bar");
  bar.textContent = "";
  const objectives = snap.objectives || [];
  if (!objectives.length) {
    bar.classList.add("hidden");
    return;
  }
  bar.classList.remove("hidden");
  const head = document.createElement("div");
  head.className = "obj-head";
  head.textContent = "OKH OBJECTIVES";
  bar.appendChild(head);
  for (const o of objectives) {
    const row = document.createElement("div");
    const left = Number(o.turns_left);
    const pending = o.status === "pending";
    row.className = "obj-row" + (pending ? " pending" : "") + (left <= 1 ? " urgent" : "");
    const title = document.createElement("span");
    title.className = "obj-title";
    title.textContent = o.title;
    const clock = document.createElement("span");
    clock.className = "obj-clock";
    clock.textContent = pending
      ? "DECISION REQUIRED"
      : `by wk ${o.deadline_turn} · ${left} left`;
    row.append(title, clock);
    if (pending) {
      row.title = "Click to decide";
      row.addEventListener("click", () => openDiversion(o.id));
    }
    bar.appendChild(row);
  }
}

const DIVERSION_DEFERRED_KEY = "directive.diversionDeferred";

function pendingDiversion() {
  return (snap.objectives || []).find((o) => o.status === "pending");
}

function renderDiversion(force = false) {
  const modal = $("#diversion");
  const obj = pendingDiversion();
  const deferred = localStorage.getItem(DIVERSION_DEFERRED_KEY) === (obj ? obj.id : "");
  if (snap.victory || !obj || (deferred && !force)) {
    modal.classList.add("hidden");
    return;
  }
  const body = $("#diversion-body");
  body.textContent = "";
  const t = document.createElement("div");
  t.className = "communique-from";
  t.textContent = obj.title;
  const detail = document.createElement("div");
  detail.className = "communique-body";
  detail.textContent = obj.detail || "";
  const stakes = document.createElement("div");
  stakes.className = "obj-stakes";
  stakes.textContent =
    `Accept: take ${obj.target} by week ${obj.deadline_turn} (+${obj.reward} standing, ` +
    `−${obj.penalty} if you fail). Decline: −${obj.decline_penalty} standing now.`;
  body.append(t, detail, stakes);
  $("#btn-diversion-accept").dataset.id = obj.id;
  $("#btn-diversion-decline").dataset.id = obj.id;
  modal.classList.remove("hidden");
}

function openDiversion(id) {
  localStorage.removeItem(DIVERSION_DEFERRED_KEY);
  renderDiversion(true);
}

async function decideDiversion(id, accept) {
  try {
    await api("/api/game/objective", {
      method: "POST",
      body: JSON.stringify({ id, accept }),
    });
    localStorage.removeItem(DIVERSION_DEFERRED_KEY);
    snap = await api("/api/game");
    renderAll();
    toast(accept ? "Diversion accepted. OKH is satisfied." : "Diversion declined. OKH takes note.",
          accept);
  } catch (e) {
    toast(e.message);
  }
}

const COMMUNIQUE_SEEN_KEY = "directive.communiqueSeenTurn";

function renderCommuniques() {
  const modal = $("#communique");
  const list = snap.communiques || [];
  // suppressed when the campaign is over, when there is nothing to show, or
  // when this turn's communiqués have already been seen (survives a refresh)
  const seen = Number(localStorage.getItem(COMMUNIQUE_SEEN_KEY) || 0);
  if (snap.victory || !list.length || seen >= snap.turn) {
    modal.classList.add("hidden");
    return;
  }
  const container = $("#communique-list");
  container.textContent = "";
  for (const c of list) {
    const cmd = snap.commanders.find((x) => x.id === c.commander);
    const card = document.createElement("div");
    card.className = "communique-msg";
    const from = document.createElement("div");
    from.className = "communique-from";
    from.textContent = c.name;
    const role = document.createElement("div");
    role.className = "communique-role";
    role.textContent = cmd ? cmd.role : "";
    const body = document.createElement("div");
    body.className = "communique-body";
    body.textContent = c.text;
    card.append(from, role, body);
    container.appendChild(card);
  }
  // REPLY targets the first (currently only) communiqué's author
  $("#btn-communique-reply").dataset.target = list[0].commander;
  modal.classList.remove("hidden");
}

function dismissCommuniques() {
  localStorage.setItem(COMMUNIQUE_SEEN_KEY, String(snap.turn));
  $("#communique").classList.add("hidden");
}

function renderAll() {
  renderHeader();
  renderMap();
  renderObjectives();
  renderDispatches();
  renderCommanders();
  renderOob();
  renderBattles();
  renderVerdict();
  renderCommuniques();
  renderDiversion();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-page").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $("#tab-" + tab.dataset.tab).classList.add("active");
  });
});

$("#btn-communique-reply").addEventListener("click", (ev) => {
  const target = ev.currentTarget.dataset.target;
  dismissCommuniques();
  if (target) openSignalDrawer(target);
});
$("#btn-communique-dismiss").addEventListener("click", dismissCommuniques);

$("#btn-diversion-accept").addEventListener("click", (ev) =>
  decideDiversion(ev.currentTarget.dataset.id, true));
$("#btn-diversion-decline").addEventListener("click", (ev) =>
  decideDiversion(ev.currentTarget.dataset.id, false));
$("#btn-diversion-later").addEventListener("click", () => {
  const obj = pendingDiversion();
  if (obj) localStorage.setItem(DIVERSION_DEFERRED_KEY, obj.id);
  $("#diversion").classList.add("hidden");
});

$("#btn-endturn").addEventListener("click", endTurn);
$("#btn-verdict-new").addEventListener("click", async () => {
  try {
    snap = await api("/api/game/new", { method: "POST" });
    renderAll();
    toast("New campaign begun.", true);
  } catch (e) {
    toast(e.message);
  }
});
$("#btn-new").addEventListener("click", async () => {
  if (!confirm("Abandon the current campaign and start over from 22 June 1941?")) return;
  try {
    snap = await api("/api/game/new", { method: "POST" });
    renderAll();
    toast("New campaign begun.", true);
  } catch (e) {
    toast(e.message);
  }
});

boot();
