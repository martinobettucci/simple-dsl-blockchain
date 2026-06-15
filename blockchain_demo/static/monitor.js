const SVGNS = "http://www.w3.org/2000/svg";
const short = (h) => (h ? h.slice(0, 10) + "…" : "—");
let selected = null; // selected block hash (kept across refreshes)

async function get(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
function el(tag, html) {
  const e = document.createElement(tag);
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function svg(tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

async function refresh() {
  try {
    const [stats, peers, graph, mempool, logs] = await Promise.all([
      get("/stats"), get("/peers"), get("/graph"), get("/mempool"), get("/logs?limit=200"),
    ]);
    renderStats(stats);
    renderTopology(stats, peers.peers || []);
    renderGraph(graph);
    renderMempool(mempool);
    renderLogs(logs.logs || []);
    document.getElementById("live").classList.remove("down");
  } catch (e) {
    document.getElementById("live").classList.add("down");
    console.error(e);
  }
}

function renderStats(s) {
  document.getElementById("ident").innerHTML =
    `<b>${s.is_archive ? "archive" : s.role}</b> · :${s.port} · ` +
    `<span class="hash">${s.pubkey ? short(s.pubkey) : "no wallet"}</span>` +
    (s.is_validator ? ` · <span class="badge val">validator</span>` : "");
  const c = s.counters || {};
  const cards = [
    ["height", s.height], ["validators", `${s.validators} (q=${s.quorum})`],
    ["mempool", s.mempool], ["pending", s.pending], ["peers", s.peers],
    ["blocks known", s.blocks_known], ["uptime", s.uptime_s + "s"],
    ["proposed", c.proposed], ["finalized", c.finalized], ["accepted", c.accepted],
    ["sigs given", c.sigs], ["tx ok/rej/dup", `${c.tx_accepted}/${c.tx_rejected}/${c.tx_duplicate}`],
  ];
  const box = document.getElementById("stats");
  clear(box);
  cards.forEach(([k, v]) => {
    const d = el("div"); d.className = "card";
    d.append(el("div", String(v)), el("small", k));
    box.append(d);
  });
}

function renderTopology(self, peers) {
  const s = document.getElementById("topo");
  clear(s);
  const W = s.clientWidth || 800, H = 340, cx = W / 2, cy = H / 2;
  document.getElementById("topo-empty").textContent =
    peers.length ? "" : "no peers known yet (mesh still forming)";
  const R = Math.min(cx, cy) - 60;
  // edges + peer nodes
  peers.forEach((p, i) => {
    const a = (2 * Math.PI * i) / peers.length - Math.PI / 2;
    const x = cx + R * Math.cos(a), y = cy + R * Math.sin(a);
    s.append(svg("line", { x1: cx, y1: cy, x2: x, y2: y, class: "edge" }));
    if (p.latency_ms)
      s.append(svg("text", { x: (cx + x) / 2, y: (cy + y) / 2 - 4, class: "elabel" },
        `${Math.round(p.latency_ms)}ms`));
    const g = svg("g", { class: "peer", transform: `translate(${x},${y})` });
    g.style.cursor = "pointer";
    g.append(svg("circle", { r: 22, class: "node " + (p.is_validator ? "val" : "plain") }));
    g.append(svg("text", { y: 4, class: "nlabel" }, ":" + p.port));
    g.append(svg("text", { y: 40, class: "sub" }, p.is_validator ? "validator" : "node"));
    g.addEventListener("click", () => { window.location.href = `http://${p.host}:${p.port}/monitor`; });
    s.append(g);
  });
  // center = this node
  const c = svg("g", { transform: `translate(${cx},${cy})` });
  c.append(svg("circle", { r: 30, class: "node self" }));
  c.append(svg("text", { y: -2, class: "nlabel" }, "this"));
  c.append(svg("text", { y: 14, class: "sub light" }, ":" + self.port));
  s.append(c);
}

function renderGraph(graph) {
  const s = document.getElementById("graph");
  clear(s);
  const DX = 132, DY = 86;
  const items = [
    ...graph.blocks.map((b) => ({ ...b, pending: false })),
    ...graph.pending.map((b) => ({ ...b, pending: true, finalized: false, canonical: false })),
  ];
  if (!items.length) return;
  const heights = {};
  items.forEach((b) => (heights[b.height] = heights[b.height] || []).push(b));
  const pos = {};
  let maxLane = 0, maxH = 0;
  Object.keys(heights).map(Number).sort((a, b) => a - b).forEach((h) => {
    const grp = heights[h];
    grp.sort((a, b) => ((b.canonical ? 1 : 0) - (a.canonical ? 1 : 0)) ||
      ((a.pending ? 1 : 0) - (b.pending ? 1 : 0)) || (a.hash < b.hash ? -1 : 1));
    grp.forEach((b, i) => { pos[b.hash] = { x: h * DX + 70, y: i * DY + 50, b }; maxLane = Math.max(maxLane, i); });
    maxH = Math.max(maxH, h);
  });
  s.setAttribute("width", (maxH + 1) * DX + 40);
  s.setAttribute("height", (maxLane + 1) * DY + 40);
  // edges (prev -> block), skipping genesis self-loop
  items.forEach((b) => {
    const p = pos[b.hash], q = pos[b.prev];
    if (p && q && !b.genesis) s.append(svg("line", { x1: q.x + 52, y1: q.y, x2: p.x - 52, y2: p.y, class: "edge" }));
  });
  // block nodes
  items.forEach((b) => {
    const p = pos[b.hash];
    const cls = b.pending ? "pending" : b.canonical ? "canonical" : "fork";
    const g = svg("g", { transform: `translate(${p.x},${p.y})`, class: "blocknode " + cls });
    g.style.cursor = "pointer";
    g.append(svg("rect", { x: -52, y: -26, width: 104, height: 52, rx: 7 }));
    g.append(svg("text", { y: -8, class: "bh" }, b.genesis ? "#0 genesis" : "#" + b.height));
    g.append(svg("text", { y: 6, class: "bhash" }, short(b.hash)));
    g.append(svg("text", { y: 20, class: "bsub" },
      b.pending ? `${b.signatures || 0} sigs` : `${b.txs} tx · ${b.signers} paid`));
    if (b.hash === selected) g.classList.add("sel");
    g.addEventListener("click", () => selectBlock(b.hash, g));
    s.append(g);
  });
}

async function selectBlock(hash, gEl) {
  selected = hash;
  document.querySelectorAll("#graph .blocknode.sel").forEach((x) => x.classList.remove("sel"));
  if (gEl) gEl.classList.add("sel");
  const box = document.getElementById("blockdetail");
  try {
    const { block: b } = await get("/block/" + hash);
    const gov = b.governance || {};
    const txs = (b.transactions || []).map((t) =>
      t.type && t.type !== "dsl"
        ? `  · ${t.type} ${JSON.stringify(t.data || {})}`
        : `  · ${short(t.from)} premium ${t.premium} :: ${t.script}`).join("\n");
    box.textContent =
      `#${b.header.height}  ${hash}\n` +
      `prev:   ${b.header.prev_hash}\n` +
      `miner:  ${b.header.miner}\n` +
      `state:  ${JSON.stringify(b.state)}\n` +
      `finalized: ${b.finalized}   signers_frozen: ${(b.signers_frozen || []).map(short).join(", ") || "—"}\n` +
      (gov.validators ? `governance validators: ${gov.validators.length} (quorum ${gov.quorum})\n` : "") +
      `transactions (${(b.transactions || []).length}):\n${txs || "  (none)"}`;
  } catch (e) {
    box.textContent = "block not found (pruned?)";
  }
}

function renderMempool(mp) {
  document.getElementById("mempool-mode").textContent = mp.mode;
  const body = document.querySelector("#mempool tbody");
  clear(body);
  (mp.mempool || []).forEach((t) => {
    const tr = el("tr");
    const payload = t.type === "dsl" ? `<span class="mono">${t.script}</span>`
      : `<span class="pill">${t.type}</span> <span class="mono">${JSON.stringify(t.data)}</span>`;
    tr.append(el("td", String(t.order)), el("td", `<span class="hash">${short(t.from)}</span>`),
      el("td", t.type), el("td", `<span class="premium">${t.premium}</span>`),
      el("td", String(t.nonce)), el("td", payload));
    body.append(tr);
  });
  if (!(mp.mempool || []).length) body.append(el("tr", `<td colspan="6" class="hash">empty</td>`));
}

function renderLogs(logs) {
  const pre = document.getElementById("logs");
  pre.textContent = logs.map((l) => l.msg).join("\n") || "(no logs yet)";
  pre.scrollTop = pre.scrollHeight;
}

refresh();
setInterval(refresh, 2000);
