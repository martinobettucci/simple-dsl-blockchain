const short = (h) => (h ? h.slice(0, 12) + "…" : "—");

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

async function refresh() {
  try {
    const [chain, balances, validators, pending, branches, state, governance, nodes] = await Promise.all([
      get("/chain"), get("/balances"), get("/validators"),
      get("/pending"), get("/branches"), get("/state"), get("/governance"),
      get("/nodes").catch(() => ({ nodes: [] })),
    ]);

    const nbody = document.querySelector("#nodes tbody");
    nbody.innerHTML = "";
    (nodes.nodes || []).forEach((n) => {
      const tr = el("tr");
      const role = n.is_archive ? "archive" : (n.role || "—");
      tr.append(
        el("td", `<span class="mono">${n.host}:${n.port}</span>`),
        el("td", role),
        el("td", String(n.height ?? "—")),
        el("td", `<span class="hash">${n.pubkey ? short(n.pubkey) : "—"}</span>`),
        el("td", `<a href="${n.monitor}" target="_blank">⛭ monitor</a>`)
      );
      nbody.append(tr);
    });
    if (!(nodes.nodes || []).length) {
      nbody.append(el("tr", `<td colspan="5" class="hash">no nodes discovered</td>`));
    }

    document.getElementById("tip").textContent = "height: " + chain.height;
    document.getElementById("state").textContent = JSON.stringify(state.state, null, 2);

    const bbody = document.querySelector("#balances tbody");
    bbody.innerHTML = "";
    Object.entries(balances.balances).sort((a, b) => b[1] - a[1]).forEach(([addr, v]) => {
      const tr = el("tr");
      tr.append(el("td", `<span class="hash">${short(addr)}</span>`), el("td", String(v)));
      bbody.append(tr);
    });

    document.getElementById("quorum").textContent =
      `quorum: ${validators.quorum} / ${validators.count} validators`;
    const vbody = document.querySelector("#validators tbody");
    vbody.innerHTML = "";
    validators.validators.forEach((v) => {
      const tr = el("tr");
      tr.append(
        el("td", `<span class="hash">${short(v.pubkey)}</span>`),
        el("td", String(v.signed)),
        el("td", `<span class="paid">${v.paid_blocks}</span>`),
        el("td", String(v.miss_count)),
        el("td", String(v.last_signed))
      );
      vbody.append(tr);
    });

    renderGovernance(governance);

    const pbody = document.querySelector("#pending tbody");
    pbody.innerHTML = "";
    pending.pending.forEach((p) => {
      const tr = el("tr");
      tr.append(
        el("td", `<span class="hash">${short(p.hash)}</span>`),
        el("td", String(p.height)),
        el("td", `${p.signatures} / ${p.quorum}`),
        el("td", p.finalized ? "✅" : "⏳")
      );
      pbody.append(tr);
    });

    const blist = document.getElementById("branches");
    blist.innerHTML = "";
    branches.branches.forEach((b) => {
      blist.append(el("li", `tip ${short(b.tip)} · length ${b.length}`));
    });

    renderChain(chain.chain);
  } catch (e) {
    console.error(e);
  }
}

function renderGovernance(gov) {
  const abody = document.querySelector("#applications tbody");
  abody.innerHTML = "";
  Object.entries(gov.applications || {}).forEach(([cand, voters]) => {
    const tr = el("tr");
    tr.append(
      el("td", `<span class="hash">${short(cand)}</span>`),
      el("td", `${voters.length} / ${gov.quorum}`)
    );
    abody.append(tr);
  });
  if (!Object.keys(gov.applications || {}).length) {
    abody.append(el("tr", `<td colspan="2" class="hash">none</td>`));
  }

  const pbody = document.querySelector("#proposals tbody");
  pbody.innerHTML = "";
  Object.entries(gov.config_proposals || {}).forEach(([pid, p]) => {
    const tr = el("tr");
    tr.append(
      el("td", `<span class="hash">${short(pid)}</span>`),
      el("td", `<span class="mono">${JSON.stringify(p.changes)}</span>`),
      el("td", `${(p.votes || []).length} / ${gov.quorum}`)
    );
    pbody.append(tr);
  });
  if (!Object.keys(gov.config_proposals || {}).length) {
    pbody.append(el("tr", `<td colspan="3" class="hash">none</td>`));
  }

  document.getElementById("govconfig").textContent = JSON.stringify(gov.config || {}, null, 2);
}

const GOV_LABEL = {
  validator_apply: "🪪 apply as validator",
  validator_vote: "🗳️ vote validator",
  config_propose: "⚙️ propose config",
  config_vote: "🗳️ vote config",
};

function renderChain(chain) {
  const root = document.getElementById("chain");
  root.innerHTML = "";
  [...chain].reverse().forEach((b) => {
    const div = el("div", "");
    div.className = "block";
    const frozen = new Set(b.signers_frozen || []);
    const sigs = Object.keys(b.validator_signatures || {})
      .map((pk) => `<span class="${frozen.has(pk) ? "paid" : "unpaid"}">${short(pk)}${frozen.has(pk) ? " 💰" : ""}</span>`)
      .join(" ");
    let html = `<div class="head">
        <span class="h">#${b.header.height}</span>
        <span class="hash">${short(b.hash)}</span>
        <span class="pill">miner ${short(b.header.miner)}</span>
        <span class="pill">${b.finalized ? "finalized" : "pending"}</span>
      </div>
      <div>state: <span class="mono">${JSON.stringify(b.state)}</span></div>
      <div>signatures: ${sigs || "—"} <span class="hash">(💰 = paid / frozen)</span></div>`;
    (b.transactions || []).forEach((t) => {
      const kind = (t.type && t.type !== "dsl")
        ? `<span class="pill">${GOV_LABEL[t.type] || t.type}</span> <span class="mono">${JSON.stringify(t.data || {})}</span>`
        : `<span class="mono">${t.script}</span>`;
      html += `<div class="tx">from ${short(t.from)} ·
        <span class="premium">premium ${t.premium}</span> ·
        nonce ${t.nonce} · ${kind}</div>`;
    });
    div.innerHTML = html;
    root.append(div);
  });
}

refresh();
setInterval(refresh, 2000);
