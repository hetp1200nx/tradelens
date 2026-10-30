"""Volatile Watchlist, one per user. A new user starts with the 200 most volatile F&O stocks.
The market feed tracks the union of everyone's lists; each user's board shows only their own list."""
from __future__ import annotations

from .market import LOCK, MARKET
from .storage import store

MAX_WATCH = 1500


def _rebuild_union():
    allsyms = list(MARKET.auto_watch)
    for k, v in store().kv.items():
        if k.startswith("u:") and k.endswith(":watchlist") and isinstance(v, list):
            allsyms += v
    union = [s for s in dict.fromkeys(allsyms) if s in MARKET.stocks]
    with LOCK:
        MARKET.groups["watchlist"] = union
        for s in union:
            MARKET.stocks[s].groups.add("watchlist")


def init(feed, default: list[str]):
    """Called by the feed at startup with the ranked most-volatile list."""
    MARKET.auto_watch = [s for s in default if feed.track(s)]
    for k, v in list(store().kv.items()):
        if k.startswith("u:") and k.endswith(":watchlist") and isinstance(v, list):
            for s in v:
                try:
                    feed.track(s)
                except Exception as e:
                    print("watchlist track failed", s, e)
    _rebuild_union()


def user_list(uid: str) -> list[str]:
    lst = store().ukv(uid, "watchlist")
    return list(lst) if isinstance(lst, list) else list(MARKET.auto_watch)


def add(feed, uid: str, sym: str) -> dict:
    sym = sym.upper().strip()
    wl = user_list(uid)
    if sym in wl:
        return {"ok": True, "already": True, "sym": sym}
    if len(wl) >= MAX_WATCH:
        return {"ok": False, "error": f"Watchlist is full ({MAX_WATCH} shares)"}
    if sym not in MARKET.catalog and sym not in MARKET.stocks:
        return {"ok": False, "error": f"{sym} is not a listed share"}
    if not feed.track(sym):
        return {"ok": False, "error": f"Could not start live data for {sym}"}
    wl.insert(0, sym)
    store().set_ukv(uid, "watchlist", wl)
    _rebuild_union()
    return {"ok": True, "sym": sym}


def remove(uid: str, sym: str) -> dict:
    sym = sym.upper().strip()
    wl = [s for s in user_list(uid) if s != sym]
    store().set_ukv(uid, "watchlist", wl)
    _rebuild_union()
    return {"ok": True, "sym": sym}
