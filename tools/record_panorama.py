"""Record a Playwright video panorama of the running demo (explorer, node
monitor, wallet).  The demo services must already be running (``python
genesys.py``).  Outputs a single .webm and prints its path.

    python tools/record_panorama.py [out_dir]

Used by the project's demo-video convention (see CLAUDE.md): a change ships with
a unit test *and* a recorded video demonstrating it.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/panorama"
EXPLORER = os.environ.get("EXPLORER_URL", "http://127.0.0.1:8600")
MONITOR = os.environ.get("MONITOR_URL", "http://127.0.0.1:9001/monitor")
WALLET = os.environ.get("WALLET_URL", "http://127.0.0.1:8700")
USER_WALLET = os.environ.get("USER_WALLET", os.path.join(ROOT, "runtime/wallets/user.json"))


def caption(page, text):
    page.evaluate(
        """(t) => { let b = document.getElementById('__cap');
        if (!b) { b = document.createElement('div'); b.id = '__cap';
          b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#5ad19a;'
            + 'color:#0f1320;font:bold 18px ui-monospace,monospace;padding:10px 16px;box-shadow:0 2px 10px #000';
          document.body.appendChild(b); }
        b.textContent = t; }""", text)


def scroll_through(page, ms=1100, steps=6):
    h = page.evaluate("document.body.scrollHeight")
    for i in range(steps + 1):
        page.evaluate(f"window.scrollTo(0, {int(h * i / steps)})")
        page.wait_for_timeout(ms)
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(400)


def run():
    os.makedirs(OUT, exist_ok=True)
    priv = json.load(open(USER_WALLET))["private_key"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(record_video_dir=OUT, viewport={"width": 1366, "height": 900})
        page = ctx.new_page()

        # 1) Explorer — mesh directory, chain, governance, economics
        page.goto(EXPLORER, wait_until="load")
        page.wait_for_timeout(1500)
        caption(page, "Explorer — noeuds du mesh, chaine, gouvernance on-chain, economie")
        scroll_through(page)

        # 2) Per-node monitor — stats, topology graph, fork graph, mempool, logs
        page.goto(MONITOR, wait_until="load")
        page.wait_for_timeout(1500)
        caption(page, "Monitoring du noeud — stats, topologie, graphe de forks, mempool, logs")
        scroll_through(page)
        try:
            page.locator("#graph .blocknode").first.click()
            page.wait_for_timeout(1800)
        except Exception:
            pass

        # 3) Wallet — private key -> pubkey/balance -> send a DSL statement
        page.goto(WALLET, wait_until="load")
        page.wait_for_timeout(1200)
        caption(page, "Wallet — cle privee, cle publique, solde, envoi d'un statement DSL")
        page.fill("#pk", priv)
        page.click("#unlock")
        page.wait_for_timeout(2800)
        page.fill("#script", "let counter = counter + 1")
        page.fill("#premium", "4")
        page.click("#send")
        page.wait_for_timeout(4500)
        scroll_through(page, ms=900, steps=3)

        video = page.video
        ctx.close()
        browser.close()
        print("VIDEO", video.path())


if __name__ == "__main__":
    run()
