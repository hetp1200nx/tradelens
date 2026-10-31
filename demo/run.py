"""Start TradeLens:  python run.py   then open http://localhost:8000"""
import os
import sys
import threading

import uvicorn

from backend import config as C
from backend import users as U
from backend.app import build_app
from backend.brokers import Brokers
from backend.engine import Engine
from backend.market import MARKET
from backend.storage import store


def feed_creds():
    """Whose Angel One API powers the shared live prices: .env first, else the user admin chose."""
    env = {"api_key": C.ANGEL_API_KEY, "client_code": C.ANGEL_CLIENT_CODE, "pin": C.ANGEL_PIN, "totp_secret": C.ANGEL_TOTP_SECRET}
    if all(env.values()):
        return env, ".env"
    uid = store().kv.get("data_user")
    if uid and U.angel_creds(uid):
        return U.angel_creds(uid), f"user {U.get(uid)['username']}"
    if C.DATA_MODE != "demo":
        # nobody chosen (or that user removed their API): use the first account whose Angel API checked out
        # (accounts whose API last checked out first; a temporary Angel error must not drop us to demo)
        for u in sorted(store().users.values(), key=lambda x: ((x.get("angel") or {}).get("status") != "connected", x.get("created") or 0)):
            if not u.get("disabled") and U.angel_creds(u["id"]):
                store().set_kv("data_user", u["id"])
                return U.angel_creds(u["id"]), f"user {u['username']}"
    return None, ""


def make_feed():
    creds, src = feed_creds()
    if C.DATA_MODE == "demo" or (C.DATA_MODE == "auto" and not creds):
        from backend.feeds.demo import DemoFeed
        return DemoFeed(MARKET), "demo"
    from backend.feeds.angel import AngelFeed
    return AngelFeed(MARKET, creds), src


def restart_soon(delay=4):
    """Restart the server (used after admin changes which API powers live prices)."""
    def go():
        print("[TradeLens] restarting to switch live-price source", flush=True)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Timer(delay, go).start()


U.ensure_admin()
U.ensure_demo_user()
feed, feed_src = make_feed()
print(f"[TradeLens] starting: {'DEMO prices' if feed_src == 'demo' else 'LIVE prices via ' + feed_src}"
      f" | storage: {'Supabase' if store().supa else 'local file'}", flush=True)
feed.start()
engine = Engine(feed)
engine.start()
brokers = Brokers(feed)
app = build_app(feed, engine, brokers, feed_src, restart_soon)

if __name__ == "__main__":
    print("TradeLens DEMO: simulated prices only. Sign in with  Demo / demo@123")
    print(f"TradeLens running ({'DEMO' if feed_src == 'demo' else 'LIVE via ' + feed_src}) -> http://localhost:{C.PORT}")
    uvicorn.run(app, host="0.0.0.0", port=C.PORT, log_level="warning")
