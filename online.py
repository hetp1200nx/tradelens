"""Put TradeLens online from your own computer, free.

What it does:
1. Starts TradeLens (run.py) on this computer.
2. Opens a free Cloudflare Tunnel, which gives a public https link that works from your phone anywhere.
3. Updates a small page on your GitHub Pages site, so ONE fixed address always forwards to the current link
   (the tunnel link changes every time it restarts).
4. Optionally sends the new link to your Telegram.
5. Keeps the computer awake while running, and restarts the app or the tunnel if either stops.

Start it with start_online.bat (Windows) or bash start_online.sh (Mac/Linux). Stop with Ctrl+C or by closing the window.

Settings in .env (all optional except as noted):
  GITHUB_TOKEN=...            fine-grained token with Contents: Read and write on your repo (for the fixed link)
  GITHUB_REPO=hetp1200nx/tradelens
  GITHUB_LINK_BRANCH=gh-pages branch that holds only the forwarding page
"""
from __future__ import annotations

import base64
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from backend import config as C  # noqa: E402  (loads .env)

PORT = C.PORT
BIN = ROOT / "bin"
URL_RX = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
IST = timezone(timedelta(hours=5, minutes=30))
GH_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GH_REPO = os.getenv("GITHUB_REPO", "hetp1200nx/tradelens").strip()
GH_BRANCH = os.getenv("GITHUB_LINK_BRANCH", "gh-pages").strip()
STOP = threading.Event()


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ------------------------------------------------------------------ keep the computer awake (Windows)
def keep_awake():
    if platform.system() == "Windows":
        try:
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            log("Computer will stay awake while TradeLens is online (screen can still turn off).")
        except Exception:
            pass


# ------------------------------------------------------------------ cloudflared
def cloudflared_path() -> str:
    found = shutil.which("cloudflared")
    if found:
        return found
    sysname, mach = platform.system(), platform.machine().lower()
    arm = mach in ("arm64", "aarch64")
    if sysname == "Windows":
        asset, local = ("cloudflared-windows-amd64.exe" if sys.maxsize > 2 ** 32 else "cloudflared-windows-386.exe"), "cloudflared.exe"
    elif sysname == "Darwin":
        asset, local = ("cloudflared-darwin-arm64.tgz" if arm else "cloudflared-darwin-amd64.tgz"), "cloudflared"
    else:
        asset, local = ("cloudflared-linux-arm64" if arm else "cloudflared-linux-amd64"), "cloudflared"
    dest = BIN / local
    if dest.exists():
        return str(dest)
    BIN.mkdir(exist_ok=True)
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}"
    log(f"Downloading Cloudflare Tunnel (one time): {url}")
    r = requests.get(url, timeout=180, stream=True)
    r.raise_for_status()
    tmp = BIN / (asset + ".part")
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    if asset.endswith(".tgz"):
        with tarfile.open(tmp) as t:
            member = next(m for m in t.getmembers() if m.name.endswith("cloudflared"))
            member.name = local
            t.extract(member, BIN)
        tmp.unlink()
    else:
        tmp.replace(dest)
    dest.chmod(0o755)
    return str(dest)


# ------------------------------------------------------------------ forwarding page on GitHub Pages
def link_page(url: str) -> str:
    when = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    u = html.escape(url)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TradeLens</title><meta name="robots" content="noindex">
<style>
:root{{--bg:#0a0d12;--panel:#10151c;--line:#1f2731;--text:#dbe2ea;--muted:#7d8a99;--acc:#4fb3ff;--down:#ff5c63}}
@media (prefers-color-scheme: light){{:root{{--bg:#f3f5f8;--panel:#fff;--line:#e1e6ed;--text:#16202b;--muted:#5a6878;--acc:#1a73d9}}}}
*{{box-sizing:border-box}} body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;padding:16px}}
.box{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:26px;max-width:420px;width:100%;text-align:center}}
h1{{font-size:20px;margin:0 0 6px}} h1 i{{display:inline-block;width:11px;height:11px;border-radius:3px;background:linear-gradient(135deg,#1fc98a,#4fb3ff);margin-right:8px}}
p{{color:var(--muted);margin:8px 0}} a.btn{{display:inline-block;margin-top:12px;padding:10px 18px;border-radius:9px;background:var(--acc);color:#fff;text-decoration:none;font-weight:600}}
.off{{color:var(--down);font-weight:600}} .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--acc);animation:p 1s infinite alternate}}
@keyframes p{{to{{opacity:.2}}}}
</style></head><body><div class="box">
<h1><i></i>TradeLens</h1>
<p id="msg"><span class="dot"></span> Connecting…</p>
<a class="btn" id="go" href="{u}">Open TradeLens</a>
<p style="font-size:12px;margin-top:16px">Last started: {when}</p>
</div>
<script>
const URL_NOW = "{u}";
function check() {{
  const c = new AbortController(); const t = setTimeout(() => c.abort(), 6000);
  fetch(URL_NOW + "/api/ping", {{ cache: "no-store", signal: c.signal }})
    .then(r => r.json()).then(j => {{ if (j.ok) location.replace(URL_NOW); else off(); }})
    .catch(off).finally(() => clearTimeout(t));
}}
function off() {{
  document.getElementById("msg").innerHTML = '<span class="off">TradeLens is offline right now.</span><br>The computer running it is off, asleep or not connected. This page retries every 20 seconds.';
  setTimeout(check, 20000);
}}
check();
</script></body></html>
"""


def gh(method, path, **kw):
    return requests.request(method, f"https://api.github.com/repos/{GH_REPO}{path}", timeout=30,
                            headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28"}, **kw)


def publish_link(url: str) -> bool:
    if not GH_TOKEN:
        log("GITHUB_TOKEN not set in .env, so the fixed GitHub link was not updated. Use the link above directly.")
        return False
    content = base64.b64encode(link_page(url).encode()).decode()
    r = gh("GET", f"/branches/{GH_BRANCH}")
    if r.status_code == 404:  # first run: create a separate branch holding only the forwarding page
        blob = gh("POST", "/git/blobs", json={"content": content, "encoding": "base64"}).json()
        tree = gh("POST", "/git/trees", json={"tree": [
            {"path": "index.html", "mode": "100644", "type": "blob", "sha": blob["sha"]},
            {"path": ".nojekyll", "mode": "100644", "type": "blob",
             "sha": gh("POST", "/git/blobs", json={"content": "", "encoding": "utf-8"}).json()["sha"]}]}).json()
        commit = gh("POST", "/git/commits", json={"message": "TradeLens link page", "tree": tree["sha"], "parents": []}).json()
        r = gh("POST", "/git/refs", json={"ref": f"refs/heads/{GH_BRANCH}", "sha": commit["sha"]})
        if r.status_code >= 300:
            log(f"Could not create branch {GH_BRANCH}: {r.status_code} {r.text[:200]}")
            return False
        log(f"Created branch '{GH_BRANCH}' for the link page.")
    elif r.status_code >= 300:
        log(f"GitHub said {r.status_code}: {r.text[:200]}  (check GITHUB_TOKEN and GITHUB_REPO in .env)")
        return False
    else:
        cur = gh("GET", f"/contents/index.html?ref={GH_BRANCH}")
        body = {"message": f"TradeLens online at {url}", "content": content, "branch": GH_BRANCH}
        if cur.status_code == 200:
            body["sha"] = cur.json()["sha"]
        r = gh("PUT", "/contents/index.html", json=body)
        if r.status_code >= 300:
            log(f"Could not update the link page: {r.status_code} {r.text[:200]}")
            return False
    owner, name = GH_REPO.split("/", 1)
    log(f"Fixed link updated: https://{owner.lower()}.github.io/{name}/  (takes about a minute to refresh)")
    return True


def telegram(url: str):
    if C.TELEGRAM_BOT_TOKEN and C.TELEGRAM_CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/sendMessage",
                          json={"chat_id": C.TELEGRAM_CHAT_ID, "text": f"TradeLens is online: {url}"}, timeout=15)
        except Exception:
            pass


# ------------------------------------------------------------------ processes
def start_app() -> subprocess.Popen:
    log(f"Starting TradeLens on this computer (port {PORT})…")
    return subprocess.Popen([sys.executable, str(ROOT / "run.py")], cwd=str(ROOT))


def wait_app(timeout=180) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout and not STOP.is_set():
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/api/ping", timeout=3).ok:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def run_tunnel(cf: str):
    """Runs one tunnel session; returns when it stops."""
    p = subprocess.Popen([cf, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    published = False
    for line in p.stdout:
        if STOP.is_set():
            break
        m = URL_RX.search(line)
        if m and not published:
            published = True
            url = m.group(0)
            print("\n" + "=" * 64, flush=True)
            print(f"  TradeLens is ONLINE:  {url}", flush=True)
            print("=" * 64 + "\n", flush=True)
            (C.DATA_DIR / "public_url.txt").write_text(url)
            threading.Thread(target=publish_link, args=(url,), daemon=True).start()
            threading.Thread(target=telegram, args=(url,), daemon=True).start()
    p.terminate()
    return p


def main():
    keep_awake()
    try:
        cf = cloudflared_path()
    except Exception as e:
        sys.exit(f"Could not get Cloudflare Tunnel: {e}\nDownload cloudflared from https://github.com/cloudflare/cloudflared/releases "
                 f"and put it in the 'bin' folder.")
    app = start_app()
    if not wait_app():
        app.terminate()
        sys.exit("TradeLens did not start. Run start.bat to see the error.")

    def watch_app():
        nonlocal app
        while not STOP.is_set():
            if app.poll() is not None:
                log("TradeLens stopped; restarting it…")
                app = start_app()
                wait_app()
            time.sleep(3)
    threading.Thread(target=watch_app, daemon=True).start()

    try:
        while not STOP.is_set():
            log("Opening Cloudflare Tunnel…")
            run_tunnel(cf)
            if not STOP.is_set():
                log("Tunnel closed; reopening in 5 seconds (a new link will be published).")
                time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        app.terminate()
        log("TradeLens is offline.")


if __name__ == "__main__":
    main()
