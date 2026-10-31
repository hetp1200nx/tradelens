"""Each user's own Angel One account (READ-ONLY): balance, holdings, positions, orders.
Every user with Angel details gets a separate SmartAPI session using THEIR API key. Polling runs every
5 seconds while the user (or admin) is looking, and slows to once a minute otherwise.
Market prices come from the shared live feed; this module never places or changes orders."""
from __future__ import annotations

import threading
import time

from . import users as U
from .account import norm_funds, norm_holdings, norm_orders, norm_positions
from .market import MARKET

ACTIVE_SECS = 600


class UserBroker:
    def __init__(self, uid: str, feed):
        self.uid = uid
        self.feed = feed
        self.acct = {"funds": {}, "holdings": [], "positions": [], "orders": [], "updated": None,
                     "source": "your Angel One account", "error": "connecting to Angel One…"}
        self.last_access = time.time()
        self.stop = False
        self.api = None
        self.day = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _login(self, creds):
        import pyotp
        from SmartApi import SmartConnect
        api = SmartConnect(api_key=creds["api_key"])
        r = api.generateSession(creds["client_code"], creds["pin"], pyotp.TOTP(creds["totp_secret"]).now())
        if not r or not r.get("status"):
            raise RuntimeError((r or {}).get("message") or "login failed")
        self.api = api
        self.day = time.strftime("%Y%m%d")

    def _call(self, fn):
        time.sleep(0.35)
        res = fn()
        if not res or res.get("status") is False:
            raise RuntimeError((res or {}).get("message") or "no response")
        return res.get("data")

    def _shared_api(self, creds):
        """If this user's account also powers the live prices, reuse that Angel session (no second login)."""
        fc = getattr(self.feed, "creds", None) or {}
        api = getattr(self.feed, "api", None)
        if api is not None and fc.get("client_code") == creds.get("client_code") and fc.get("api_key") == creds.get("api_key"):
            return api
        return None

    def _loop(self):
        n = 0
        while not self.stop:
            idle = time.time() - self.last_access > ACTIVE_SECS
            wait = 60 if idle else 5
            stage = "login"
            try:
                creds = U.angel_creds(self.uid)
                if not creds:
                    raise RuntimeError("Angel One details missing")
                shared = self._shared_api(creds)
                if shared is not None:
                    self.api = shared
                elif self.api is None or self.day != time.strftime("%Y%m%d"):
                    self._login(creds)
                U.mark_angel(self.uid, "connected", "")
                stage = "data"
                acct = dict(self.acct)
                acct["funds"] = norm_funds(self._call(self.api.rmsLimit))
                pos = self._call(self.api.position)
                acct["positions"] = norm_positions(pos if isinstance(pos, list) else [])
                if n % 3 == 0 or not acct["holdings"]:
                    h = self._call(self.api.holding)
                    rows = h.get("holdings") if isinstance(h, dict) else h
                    acct["holdings"] = norm_holdings(rows if isinstance(rows, list) else [])
                    o = self._call(self.api.orderBook)
                    acct["orders"] = norm_orders(o if isinstance(o, list) else [])
                acct["updated"], acct["error"] = int(time.time()), ""
                self.acct = acct
                if hasattr(self.feed, "watch_tokens"):
                    self.feed.watch_tokens([(x["exch"], x["token"]) for x in acct["holdings"] + acct["positions"]])
            except Exception as e:
                msg = str(e)
                low = msg.lower()
                if stage == "login":
                    # wrong key / PIN / TOTP: this is something the user must fix in Profile
                    self.api = None
                    self.acct = {**self.acct, "error": f"Angel One login failed: {msg}. Check your API details in Profile; the key must be a 'Trading API' key."}
                    U.mark_angel(self.uid, "error", msg)
                else:
                    # login is fine; Angel's account service didn't answer (common late at night / maintenance)
                    if "token" in low or "session" in low or "invalid" in low or "expired" in low:
                        self.api = None
                    when = time.strftime("%H:%M", time.gmtime(self.acct["updated"] + 19800)) if self.acct.get("updated") else ""
                    self.acct = {**self.acct, "error": f"Angel One's account service isn't answering right now ({msg}). "
                                 f"Your API is fine; retrying automatically every 30 s{' - showing figures from ' + when if when else ''}. "
                                 "This is common at night and during Angel's maintenance."}
                    wait = max(wait, 30)
            n += 1
            time.sleep(wait)


class Brokers:
    def __init__(self, feed):
        self.feed = feed
        self.sessions: dict[str, UserBroker] = {}
        self.lock = threading.Lock()

    def live_ok(self) -> bool:
        if MARKET.mode == "demo":
            return False
        try:
            import SmartApi  # noqa: F401
            return True
        except ImportError:
            return False

    def account(self, uid: str) -> dict:
        """Raw normalised account for a user (demo account when not connected or in demo mode)."""
        if not self.live_ok():
            return self.feed.account(uid)
        if not U.angel_creds(uid):
            return {"funds": {}, "holdings": [], "positions": [], "orders": [], "updated": None, "source": "",
                    "error": "Add your Angel One API details in Profile to see your balance, portfolio and trades."}
        with self.lock:
            b = self.sessions.get(uid)
            if b is None:
                b = self.sessions[uid] = UserBroker(uid, self.feed)
        b.last_access = time.time()
        return b.acct

    def reset(self, uid: str):
        """Call after a user's Angel details change or the user is deleted."""
        with self.lock:
            b = self.sessions.pop(uid, None)
        if b:
            b.stop = True

    def balance(self, uid: str):
        return (self.account(uid).get("funds") or {}).get("available")
