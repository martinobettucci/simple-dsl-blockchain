const short = (h) => (h ? h.slice(0, 16) + "…" : "—");
let privKey = null, pubKey = null, poll = null;

const $ = (id) => document.getElementById(id);
async function jpost(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                              body: JSON.stringify(body) });
  return r.json();
}

async function init() {
  try {
    const cfg = await (await fetch("/api/config")).json();
    if (cfg.rpc) $("rpc").value = cfg.rpc;
  } catch (e) { /* ignore */ }
}

async function unlock() {
  const pk = $("pk").value.trim();
  const res = await jpost("/api/derive", { private_key: pk });
  if (res.error) { setConn(false, res.error); return; }
  privKey = pk; pubKey = res.public_key;
  $("pub").textContent = pubKey;
  $("unlock").disabled = true; $("lock").disabled = false; $("send").disabled = false;
  setConn(true, "unlocked");
  refreshAccount();
  poll = setInterval(refreshAccount, 3000);
}

function lock() {
  privKey = null; pubKey = null;
  if (poll) clearInterval(poll);
  $("pub").textContent = $("bal").textContent = $("nonce").textContent = $("height").textContent = "—";
  $("unlock").disabled = false; $("lock").disabled = true; $("send").disabled = true;
  setConn(false, "locked");
}

async function refreshAccount() {
  if (!pubKey) return;
  const rpc = encodeURIComponent($("rpc").value.trim());
  try {
    const a = await (await fetch(`/api/account?pubkey=${pubKey}&rpc=${rpc}`)).json();
    if (a.error) { setConn(true, "rpc error"); return; }
    $("bal").textContent = a.balance;
    $("nonce").textContent = a.next_nonce;
    $("height").textContent = a.height;
    setConn(true, "unlocked");
  } catch (e) { setConn(true, "rpc error"); }
}

async function send() {
  if (!privKey) return;
  $("send").disabled = true;
  $("result").textContent = "signing & relaying…";
  const res = await jpost("/api/send", {
    private_key: privKey, script: $("script").value, premium: Number($("premium").value),
    rpc: $("rpc").value.trim(),
  });
  if (res.error) {
    $("result").textContent = "error: " + res.error;
  } else {
    const s = res.submitted || {};
    $("result").textContent =
      `status:  ${s.status || "?"}\n` +
      `tx hash: ${res.tx_hash}\n` +
      `nonce:   ${res.nonce}\n` +
      `from:    ${short(res.from)}`;
  }
  $("send").disabled = false;
  refreshAccount();
}

function setConn(ok, label) {
  const c = $("conn");
  c.textContent = "● " + label;
  c.classList.toggle("down", !ok);
}

$("unlock").addEventListener("click", unlock);
$("lock").addEventListener("click", lock);
$("send").addEventListener("click", send);
init();
