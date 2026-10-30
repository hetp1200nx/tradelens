"""Web server: sign-in, per-user REST API, admin API, live stream (Server-Sent Events) and the web app."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import zlib
from datetime import datetime, timedelta, timezone

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import analytics as A
from . import config as C
from . import planner as P
from . import users as U
from . import watch as W
from . import views as V
from .account import live_view
from .charges import breakeven_move, trade_pnl
from .engine import Engine, backtest_intraday
from .market import LOCK, MARKET
from .storage import store

FEED = None
ENGINE: Engine | None = None
BROKERS = None
FEED_SRC = ""
RESTART = None
TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
SESS, DEV = "tl_s", "tl_d"
IST_TZ = timezone(timedelta(hours=5, minutes=30))
OPEN_PATHS = ("/api/auth/", "/api/ping")


def J(data, status=200):
    return Response(json.dumps(data, default=str), status_code=status, media_type="application/json")


# ------------------------------------------------------------------ auth middleware
class Auth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        p = request.url.path
        request.state.user = U.read_token(request.cookies.get(SESS), "s")
        if p.startswith("/api/") and not p.startswith(OPEN_PATHS):
            if not request.state.user:
                dev = U.read_token(request.cookies.get(DEV), "d")
                return J({"error": "sign in required", "state": "passcode" if dev and dev.get("pc") else "login"}, 401)
            if p.startswith("/api/admin/") and request.state.user["role"] != "admin":
                return J({"error": "admin only"}, 403)
        return await call_next(request)


def _secure(request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _set_session(resp, request, u, remember: bool | None):
    resp.set_cookie(SESS, U.make_token("s", u, U.SESSION_HOURS), max_age=U.SESSION_HOURS * 3600 if remember else None,
                    httponly=True, samesite="lax", secure=_secure(request))
    if remember:
        resp.set_cookie(DEV, U.make_token("d", u, U.DEVICE_DAYS * 24), max_age=U.DEVICE_DAYS * 86400,
                        httponly=True, samesite="lax", secure=_secure(request))


def uid_of(request) -> str:
    return request.state.user["id"]


# ------------------------------------------------------------------ helpers
def _stock(sym):
    return MARKET.stocks.get(sym) or MARKET.indices.get(sym)


async def _stock_any(sym):
    """Find a share, starting live data for it if it is listed but not tracked yet."""
    sym = (sym or "").upper()
    st = _stock(sym)
    if st is None and sym in MARKET.catalog:
        st = await run_in_threadpool(FEED.track, sym)
    return st


def settings(uid) -> dict:
    return {**P.DEFAULTS, "daily_loss_limit": 0.0, "demo_balance": 25000.0, **(store().ukv(uid, "settings", {}) or {})}


def account_payload(uid) -> dict:
    acc = live_view(BROKERS.account(uid), FEED.ltp_for)
    cfg = settings(uid)
    day0 = A.ist_day_start(MARKET.clock())
    booked = 0.0
    for t in store().list(uid):
        if t.get("status") == "closed" and (t.get("exit_time") or 0) >= day0:
            lv = ENGINE.trade_live(t).get("live")
            booked += lv["pnl"]["net"] if lv else 0
    today = acc["totals"]["positions_pnl"] + booked
    lim = float(cfg.get("daily_loss_limit") or 0)
    acc["guard"] = {"today_pnl": round(today, 2), "limit": lim, "breached": bool(lim) and today <= -lim,
                    "used_pct": round(-today / lim * 100, 1) if lim and today < 0 else 0.0}
    return acc


def board_for(uid, view):
    return MARKET.board(view, W.user_list(uid) if view == "watchlist" else None)


def candles_payload(st, tf: str) -> dict:
    FEED.ensure_history(st)
    with LOCK:
        if tf in TF_MIN:
            cs = A.resample(st.m1, TF_MIN[tf])[-1500:]
        else:
            d = list(st.daily)
            if st.ltp > 0 and st.open:
                d.append({"t": A.ist_day_start(MARKET.clock()), "o": st.open, "h": st.high, "l": st.low, "c": st.ltp, "v": st.volume})
            cs = A.resample_weekly(d) if tf == "1W" else d
            cs = cs[-1000:]
        cs = [dict(c) for c in cs]
    win = cs[-300:]
    obs = A.order_blocks(win, 3)
    liq = A.liquidity_levels(win)
    closes = [c["c"] for c in cs]
    e20 = A.ema(closes, 20)
    e50 = A.ema(closes, 50)
    vw = []
    if tf in ("1m", "5m", "15m"):
        day, pv, vv = None, 0.0, 0.0
        for c in cs:
            dd = A.ist_day_start(c["t"])
            if dd != day:
                day, pv, vv = dd, 0.0, 0.0
            pv += (c["h"] + c["l"] + c["c"]) / 3 * c["v"]
            vv += c["v"]
            if vv:
                vw.append({"t": c["t"], "v": round(pv / vv, 2)})
    price = st.ltp
    return {
        "sym": st.sym, "tf": tf, "candles": cs,
        "ema20": [{"t": c["t"], "v": round(v, 2)} for c, v in zip(cs, e20)][20:],
        "ema50": [{"t": c["t"], "v": round(v, 2)} for c, v in zip(cs, e50)][50:],
        "vwap": vw,
        "order_blocks": [{"type": o["type"], "top": o["top"], "bottom": o["bottom"], "t": o["t"]} for o in obs],
        "liquidity": {"buy_side": [x for x in liq["buy_side"] if x["price"] > price][:3],
                      "sell_side": sorted([x for x in liq["sell_side"] if x["price"] < price], key=lambda x: -x["price"])[:3]},
    }


def detail_payload(st) -> dict:
    sig = ENGINE.signals_for(st, 1.0)
    with LOCK:
        q = {"sym": st.sym, "name": st.name, "exch": st.exch, "ltp": st.ltp, "open": st.open, "high": st.high,
             "low": st.low, "prev_close": st.prev_close, "volume": st.volume, "avg_price": st.avg_price,
             "buy_qty": st.buy_qty, "sell_qty": st.sell_qty, "bids": st.bids[:5], "asks": st.asks[:5],
             "oi": st.oi, "oi_chg": round(st.oi_chg_pct, 2), "uc": st.uc, "lc": st.lc, "w52h": st.w52h,
             "w52l": st.w52l, "lot": st.lot, "is_fno": st.is_fno, "is_index": st.is_index,
             "avg_vol20": st.avg_vol20, "atr_pct": round(st.atr_pct, 2), "ts": MARKET.clock()}
        m = dict(st.metrics)
    return {"quote": q, "metrics": m, "signals": sig}


def last_bars(st, tf):
    with LOCK:
        if tf in TF_MIN:
            tail = [c for c in st.m1[-(TF_MIN[tf] * 2 + 2):]]
            return [dict(c) for c in A.resample(tail, TF_MIN[tf])[-2:]]
        if tf == "1D" and st.ltp > 0 and st.open:
            return [{"t": A.ist_day_start(MARKET.clock()), "o": st.open, "h": st.high, "l": st.low, "c": st.ltp, "v": st.volume}]
    return []


# ------------------------------------------------------------------ auth routes
async def auth_me(request):
    u = request.state.user
    if u:
        return J({"state": "ok", "user": U.public(u), "mode": MARKET.mode, "feed": FEED_SRC})
    dev = U.read_token(request.cookies.get(DEV), "d")
    if dev and dev.get("pc"):
        return J({"state": "passcode", "name": dev["first_name"], "username": dev["username"]})
    return J({"state": "login"})


async def auth_register(request):
    b = await request.json()
    errs = await run_in_threadpool(U.validate_signup, b)
    if errs:
        return J({"ok": False, "errors": errs}, 400)
    angel_status = None
    if b.get("api_key"):
        ok, msg = await run_in_threadpool(U.verify_angel, {k: b[k].strip() for k in ("api_key", "client_code", "pin", "totp_secret")})
        if not ok and not msg.startswith("saved"):
            return J({"ok": False, "errors": {"angel": f"Angel One rejected these details: {msg}"}}, 400)
        angel_status = ("connected", "") if ok else ("saved", msg)
    u = await run_in_threadpool(U.create, b)
    if angel_status:
        U.mark_angel(u["id"], *angel_status)
        if angel_status[0] == "connected":
            _maybe_first_feed(u["id"])
    U.logged_in(u)
    r = J({"ok": True, "user": U.public(u)})
    _set_session(r, request, u, bool(b.get("remember", True)))
    return r


async def auth_login(request):
    b = await request.json()
    un = (b.get("username") or "").strip()
    wait = U.throttled(un)
    if wait:
        return J({"ok": False, "error": f"Too many wrong attempts. Try again in {wait // 60 + 1} minutes."}, 429)
    u = U.find_by_username(un)
    if not u or not await run_in_threadpool(U.check_secret, b.get("password") or "", u["pw"]):
        U.note_fail(un)
        return J({"ok": False, "error": "Wrong username or password"}, 401)
    if u.get("disabled"):
        return J({"ok": False, "error": "This account is disabled. Contact the admin."}, 403)
    U.logged_in(u)
    remember = bool(b.get("remember"))
    r = J({"ok": True, "user": U.public(u), "need_passcode": remember and not u.get("pc")})
    _set_session(r, request, u, remember)
    return r


async def auth_unlock(request):
    b = await request.json()
    u = U.read_token(request.cookies.get(DEV), "d")
    if not u or not u.get("pc"):
        return J({"ok": False, "error": "Please sign in with your password", "state": "login"}, 401)
    if not await run_in_threadpool(U.check_secret, str(b.get("passcode") or ""), u["pc"]):
        u["pc_fails"] = u.get("pc_fails", 0) + 1
        store().save_user(u)
        if u["pc_fails"] >= U.MAX_PASSCODE_FAILS:
            r = J({"ok": False, "error": "Too many wrong passcodes. Sign in with your password.", "state": "login"}, 401)
            r.delete_cookie(DEV)
            return r
        left = U.MAX_PASSCODE_FAILS - u["pc_fails"]
        return J({"ok": False, "error": f"Wrong passcode ({left} {'try' if left == 1 else 'tries'} left)"}, 401)
    U.logged_in(u)
    r = J({"ok": True, "user": U.public(u)})
    _set_session(r, request, u, True)
    return r


async def auth_logout(request):
    b = await request.json() if request.headers.get("content-length") not in (None, "0") else {}
    r = J({"ok": True})
    r.delete_cookie(SESS)
    if b.get("forget_device", True):
        r.delete_cookie(DEV)
    return r


# ------------------------------------------------------------------ profile
async def profile(request):
    u = request.state.user
    if request.method == "POST":
        b = await request.json()
        e = {}
        for k in ("first_name", "last_name"):
            if k in b and not str(b[k]).strip():
                e[k] = "Required"
        if "email" in b:
            em = str(b["email"]).strip().lower()
            if "@" not in em or "." not in em.split("@")[-1]:
                e["email"] = "Enter a valid email"
            elif any(x["id"] != u["id"] and x.get("email") == em for x in store().users.values()):
                e["email"] = "Another account uses this email"
        if e:
            return J({"ok": False, "errors": e}, 400)
        for k in ("first_name", "last_name", "email", "phone"):
            if k in b:
                u[k] = str(b[k]).strip().lower() if k == "email" else str(b[k]).strip()
        store().save_user(u)
    return J({**U.public(u), "mode": MARKET.mode, "feed": FEED_SRC})


def _maybe_first_feed(uid):
    """If nothing powers live prices yet, the first user to add a working API does (after an automatic restart)."""
    cur = store().kv.get("data_user")
    if FEED_SRC == "demo" and C.DATA_MODE != "demo" and not (cur and cur != uid and U.angel_creds(cur)):
        store().set_kv("data_user", uid)
        RESTART()


async def profile_angel(request):
    u = request.state.user
    if request.method == "DELETE":
        u.pop("angel", None)
        store().save_user(u)
        BROKERS.reset(u["id"])
        return J({"ok": True, "user": U.public(u)})
    b = await request.json()
    vals = {k: str(b.get(k) or "").strip() for k in ("api_key", "client_code", "pin", "totp_secret")}
    if not all(vals.values()):
        return J({"ok": False, "error": "Fill all four Angel One fields"}, 400)
    ok, msg = await run_in_threadpool(U.verify_angel, vals)
    if not ok and not msg.startswith("saved"):
        return J({"ok": False, "error": f"Angel One rejected these details: {msg}"}, 400)
    U.set_angel(u, **vals, status="connected" if ok else "saved", error="" if ok else msg)
    store().save_user(u)
    BROKERS.reset(u["id"])
    if ok:
        _maybe_first_feed(u["id"])
    return J({"ok": True, "user": U.public(u), "restarting": ok and FEED_SRC == "demo" and C.DATA_MODE != "demo" and store().kv.get("data_user") == u["id"]})


async def profile_password(request):
    u = request.state.user
    b = await request.json()
    if not await run_in_threadpool(U.check_secret, b.get("current") or "", u["pw"]):
        return J({"ok": False, "errors": {"current": "Current password is wrong"}}, 400)
    if not U.password_ok(b.get("new") or ""):
        return J({"ok": False, "errors": {"new": "Password needs " + U.PW_RULE}}, 400)
    if b["new"] != b.get("confirm"):
        return J({"ok": False, "errors": {"confirm": "Passwords don't match"}}, 400)
    u["pw"] = U.hash_secret(b["new"])
    u["gen"] = u.get("gen", 1) + 1  # signs out all other devices
    store().save_user(u)
    r = J({"ok": True})
    _set_session(r, request, u, bool(request.cookies.get(DEV)))
    return r


async def profile_passcode(request):
    u = request.state.user
    b = await request.json()
    if u.get("pc") and not await run_in_threadpool(U.check_secret, b.get("password") or "", u["pw"]):
        return J({"ok": False, "errors": {"password": "Password is wrong"}}, 400)
    pc = str(b.get("passcode") or "")
    if not pc.isdigit() or len(pc) != 4:
        return J({"ok": False, "errors": {"passcode": "Passcode must be 4 digits"}}, 400)
    if pc != str(b.get("confirm") or ""):
        return J({"ok": False, "errors": {"confirm": "Passcodes don't match"}}, 400)
    u["pc"] = U.hash_secret(pc)
    u["pc_fails"] = 0
    store().save_user(u)
    return J({"ok": True})


# ------------------------------------------------------------------ market routes (shared)
async def status(request):
    return J({"status": MARKET.status, "mode": MARKET.mode, "ready": MARKET.ready, "ts": MARKET.clock(), "feed": FEED_SRC,
              "feed_error": getattr(FEED, "error", ""), "storage": "supabase" if store().supa else "local file",
              "storage_error": store().error})


async def board(request):
    return J(board_for(uid_of(request), request.query_params.get("view", "nifty50")))


async def search(request):
    return J(MARKET.search(request.query_params.get("q", ""), int(request.query_params.get("limit", 20)), W.user_list(uid_of(request))))


async def stock(request):
    st = await _stock_any(request.path_params["sym"])
    if not st:
        return J({"error": "unknown symbol"}, 404)
    await run_in_threadpool(FEED.ensure_history, st)
    return J(await run_in_threadpool(detail_payload, st))


async def candles(request):
    st = await _stock_any(request.path_params["sym"])
    if not st:
        return J({"error": "unknown symbol"}, 404)
    return J(await run_in_threadpool(candles_payload, st, request.query_params.get("tf", "5m")))


async def backtest(request):
    st = await _stock_any(request.path_params["sym"])
    if not st:
        return J({"error": "unknown symbol"}, 404)

    def run():
        res = backtest_intraday(FEED.history_5m(st, 60))
        res["sym"] = st.sym
        res["source"] = "simulated demo data (not meaningful)" if MARKET.mode == "demo" else "Angel One 5-minute history"
        return res
    return J(await run_in_threadpool(run))


async def scorecard(request):
    return J(ENGINE.scorecard_stats())


async def radar(request):
    return J(ENGINE.radar[::-1][:100])


async def pnl(request):
    b = await request.json()
    side, seg = b.get("side", "BUY"), b.get("segment", "intraday")
    entry, qty = float(b["entry"]), float(b["qty"])
    out = {"breakeven_move": breakeven_move(side, entry, qty, seg), "capital": round(entry * qty, 2)}
    for k in ("sl", "t1", "t2", "exit"):
        if b.get(k) not in (None, ""):
            out[k] = trade_pnl(side, entry, float(b[k]), qty, seg)
    return J(out)


# ------------------------------------------------------------------ per-user routes
async def watchlist(request):
    uid = uid_of(request)
    b = await request.json()
    sym, action = (b.get("sym") or "").upper(), b.get("action", "add")
    if action == "remove":
        return J(W.remove(uid, sym))
    res = await run_in_threadpool(W.add, FEED, uid, sym)
    return J(res, 200 if res.get("ok") else 400)


async def grid(request):
    """Card data (mini chart, levels, signal) for the shares currently visible in the grid."""
    syms = [x for x in (request.query_params.get("syms") or "").upper().split(",") if x][:40]

    def build():
        out = []
        for sym in syms:
            st = _stock(sym)
            if not st:
                continue
            if not st.hist_loaded:
                try:
                    FEED.ensure_history(st)
                except Exception:
                    pass
            out.append(V.card(ENGINE, st))
        return out
    return J(await run_in_threadpool(build))


async def flow(request):
    view = request.query_params.get("view", "nifty50")
    syms = W.user_list(uid_of(request)) if view == "watchlist" else MARKET.groups.get(view, [])
    return J(await run_in_threadpool(V.flow, list(syms)))


async def watch_import(request):
    """Bulk add shares from an Excel (.xlsx) or CSV file sent as the request body."""
    uid = uid_of(request)
    data = await request.body()
    if len(data) > 5_000_000:
        return J({"ok": False, "error": "File too large (max 5 MB)"}, 400)
    try:
        names = V.parse_symbols(data, request.headers.get("x-filename", "upload.csv"))
    except Exception as e:
        return J({"ok": False, "error": f"Could not read the file: {e}"}, 400)
    if not names:
        return J({"ok": False, "error": "No share names found. Put symbols in the first column or a column named Symbol."}, 400)

    def run():
        cat = MARKET.catalog
        nospace = {k.replace(" ", ""): k for k in cat}
        added, already, missing = [], [], []
        current = set(W.user_list(uid))
        for raw in names[:2000]:
            sym = raw if raw in cat else nospace.get(raw.replace(" ", ""))
            if not sym:
                pref = [k for k in cat if k.startswith(raw.replace(" ", "")[:6])] if len(raw) >= 4 else []
                sym = pref[0] if len(pref) == 1 else None
            if not sym:
                missing.append(raw)
                continue
            if sym in current:
                already.append(sym)
                continue
            r = W.add(FEED, uid, sym)
            if r.get("ok"):
                added.append(sym)
                current.add(sym)
            else:
                missing.append(f"{raw} ({r.get('error')})")
        return {"ok": True, "found": len(names), "added": added, "already": already, "missing": missing[:100],
                "missing_count": len(missing)}
    return J(await run_in_threadpool(run))


async def account(request):
    return J(await run_in_threadpool(account_payload, uid_of(request)))


async def settings_ep(request):
    uid = uid_of(request)
    if request.method == "POST":
        b = await request.json()
        cur = store().ukv(uid, "settings", {}) or {}
        for k in ("risk_pct", "max_alloc_pct", "intraday_leverage", "daily_loss_limit", "demo_balance", "max_per_style"):
            if k in b and b[k] not in (None, ""):
                cur[k] = float(b[k])
        store().set_ukv(uid, "settings", cur)
        P._cache.pop(uid, None)
    return J(settings(uid))


async def planner(request):
    uid = uid_of(request)
    amt = request.query_params.get("amount")
    if amt not in (None, ""):
        bal, src = float(amt), "amount you entered"
    else:
        f = (await run_in_threadpool(BROKERS.account, uid)).get("funds") or {}
        bal, src = float(f.get("available") or 0), ("Angel One available cash" if BROKERS.live_ok() else "demo balance")
    res = await run_in_threadpool(P.build, ENGINE, FEED, bal, settings(uid), uid, W.user_list(uid))
    return J({**res, "balance_source": src})


async def price_alerts(request):
    uid = uid_of(request)
    lst = store().ukv(uid, "price_alerts", []) or []
    if request.method == "POST":
        b = await request.json()
        sym = (b.get("sym") or "").upper()
        st = await _stock_any(sym)
        if not st or not b.get("price"):
            return J({"error": "share and price are required"}, 400)
        price = float(b["price"])
        op = b.get("op") or ("above" if price >= st.ltp else "below")
        lst.append({"id": hashlib.md5(f"{uid}{sym}{price}{len(lst)}{MARKET.clock()}".encode()).hexdigest()[:10], "sym": sym,
                    "price": price, "op": op, "note": b.get("note", ""), "created": MARKET.clock(), "done": False})
        store().set_ukv(uid, "price_alerts", lst)
    elif request.method == "DELETE":
        lst = [a for a in lst if a["id"] != request.query_params.get("id")]
        store().set_ukv(uid, "price_alerts", lst)
    out = []
    for a in lst:
        st = _stock(a["sym"])
        out.append({**a, "ltp": st.ltp if st else None})
    return J(out[::-1])


def _csv(rows_iter) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user", "date", "symbol", "side", "type", "strike", "CE/PE", "qty", "entry", "sl", "t1", "t2", "status", "exit",
                "gross", "charges", "net", "notes"])
    for t in rows_iter:
        lv = ENGINE.trade_live(t).get("live") or {}
        p = lv.get("pnl") or {}
        un = (U.get(t.get("user")) or {}).get("username", "")
        d = datetime.fromtimestamp(t.get("created_at", 0), IST_TZ).strftime("%Y-%m-%d %H:%M")
        w.writerow([un, d, t.get("symbol"), t.get("side"), t.get("segment"), t.get("opt_strike", ""), t.get("opt_type", ""),
                    t.get("qty"), t.get("entry"), t.get("sl"), t.get("t1"), t.get("t2"), t.get("status"),
                    t.get("exit_price", ""), p.get("gross"), (p.get("charges") or {}).get("total"), p.get("net"), t.get("notes", "")])
    return buf.getvalue()


async def trades_csv(request):
    data = await run_in_threadpool(_csv, store().list(uid_of(request)))
    return Response(data, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tradelens_trades.csv"})


async def trades(request):
    uid = uid_of(request)
    if request.method == "POST":
        b = await request.json()
        for k in ("symbol", "side", "qty", "entry"):
            if b.get(k) in (None, ""):
                return J({"error": f"{k} is required"}, 400)
        b["symbol"] = b["symbol"].upper()
        st = await _stock_any(b["symbol"])
        if not st:
            return J({"error": "unknown symbol"}, 400)
        if b.get("segment") == "option" and not b.get("underlying_entry"):
            b["underlying_entry"] = st.ltp
        t = store().add(b, uid)
        return J(ENGINE.trade_live(t))
    return J(await run_in_threadpool(lambda: [ENGINE.trade_live(t) for t in store().list(uid)]))


async def trade_one(request):
    uid = uid_of(request)
    tid = request.path_params["tid"]
    if request.method == "DELETE":
        store().delete(tid, uid)
        return J({"ok": True})
    b = await request.json()
    if b.get("status") == "closed" and not b.get("exit_price"):
        t = store().get(tid, uid)
        if t:
            b["exit_price"] = ENGINE.trade_live(t)["live"]["price"]
    if b.get("status") == "closed":
        b.setdefault("exit_time", MARKET.clock())
    t = store().update(tid, b, uid)
    return J(ENGINE.trade_live(t) if t else {"error": "not found"}, 200 if t else 404)


# ------------------------------------------------------------------ admin
def _user_summary(u) -> dict:
    uid = u["id"]
    tr = store().list(uid)
    live = [ENGINE.trade_live(t) for t in tr]
    open_pnl = sum((t.get("live") or {}).get("pnl", {}).get("net", 0) for t in live if t.get("status") == "open")
    booked = sum((t.get("live") or {}).get("pnl", {}).get("net", 0) for t in live if t.get("status") == "closed")
    acc = live_view(BROKERS.account(uid), FEED.ltp_for) if u["role"] != "admin" or u.get("angel") else None
    return {**U.public(u, admin_view=True),
            "stats": {"trades": len(tr), "open": sum(1 for t in tr if t.get("status") == "open"),
                      "open_pnl": round(open_pnl, 2), "booked": round(booked, 2),
                      "watchlist": len(W.user_list(uid)), "alerts": len(store().ukv(uid, "price_alerts", []) or []),
                      "balance": (acc or {}).get("funds", {}).get("available"),
                      "portfolio_value": (acc or {}).get("totals", {}).get("value"),
                      "portfolio_pnl": (acc or {}).get("totals", {}).get("pnl"),
                      "positions_pnl": (acc or {}).get("totals", {}).get("positions_pnl"),
                      "account_error": (acc or {}).get("error", "")}}


async def admin_users(request):
    rows = await run_in_threadpool(lambda: [_user_summary(u) for u in sorted(store().users.values(), key=lambda x: x["created"])])
    tot = {"users": sum(1 for r in rows if r["role"] != "admin"), "active_today": 0, "trades": sum(r["stats"]["trades"] for r in rows),
           "open_trades": sum(r["stats"]["open"] for r in rows), "with_api": sum(1 for r in rows if r["angel"]["connected"]),
           "balance": round(sum(r["stats"]["balance"] or 0 for r in rows if r["role"] != "admin"), 2),
           "portfolio_value": round(sum(r["stats"]["portfolio_value"] or 0 for r in rows if r["role"] != "admin"), 2)}
    day0 = A.ist_day_start(int(datetime.now().timestamp()))
    tot["active_today"] = sum(1 for r in rows if r["role"] != "admin" and (r.get("last_login") or 0) >= day0)
    return J({"users": rows, "totals": tot, "feed": FEED_SRC, "mode": MARKET.mode, "data_user": store().kv.get("data_user")})


async def admin_user(request):
    uid = request.path_params["uid"]
    u = U.get(uid)
    if not u:
        return J({"error": "user not found"}, 404)
    if request.method == "POST":
        b = await request.json()
        act = b.get("action")
        if uid == "admin" and act in ("disable", "delete"):
            return J({"error": "The admin account can't be disabled or deleted here"}, 400)
        if act == "disable":
            u["disabled"] = True
            u["gen"] = u.get("gen", 1) + 1
            store().save_user(u)
            BROKERS.reset(uid)
        elif act == "enable":
            u["disabled"] = False
            store().save_user(u)
        elif act == "reset_password":
            temp = U.reset_password(u)
            return J({"ok": True, "temp_password": temp,
                      "note": "Give this temporary password to the user privately. They should change it in Profile."})
        elif act == "delete":
            if store().kv.get("data_user") == uid:
                store().set_kv("data_user", None)
            store().delete_user(uid)
            BROKERS.reset(uid)
            return J({"ok": True, "deleted": True})
        elif act == "data_source":
            if not U.angel_creds(uid):
                return J({"error": "This user has no Angel One API details"}, 400)
            store().set_kv("data_user", uid)
            if C.DATA_MODE != "demo" and not (C.ANGEL_API_KEY and C.ANGEL_PIN):
                RESTART()
                return J({"ok": True, "restarting": True})
            return J({"ok": True, "restarting": False,
                      "note": "Saved. Live prices currently come from .env or demo mode is forced (DATA_MODE=demo)."})
        else:
            return J({"error": "unknown action"}, 400)
    data = await run_in_threadpool(lambda: {
        "user": _user_summary(u),
        "account": live_view(BROKERS.account(uid), FEED.ltp_for),
        "trades": [ENGINE.trade_live(t) for t in store().list(uid)],
        "watchlist": W.user_list(uid),
        "price_alerts": store().ukv(uid, "price_alerts", []) or [],
        "settings": settings(uid),
    })
    return J(data)


async def admin_csv(request):
    data = await run_in_threadpool(_csv, store().list())
    return Response(data, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tradelens_all_trades.csv"})


# ------------------------------------------------------------------ live stream
async def _tick(uid, view, st, tf, want_acct, cur, n) -> list[tuple[str, object]]:
    """One round of live updates. Shared by the live stream (SSE) and the polling fallback.
    cur = {"since": last alert id seen, "rsince": last radar id seen}; updated in place."""
    ev = []
    if view and n % 2 == 0:
        ev.append(("board", board_for(uid, view)))
    if st:
        d = await run_in_threadpool(detail_payload, st)
        d["bars"] = last_bars(st, tf)
        ev.append(("detail", d))
    if n % 2 == 1:
        tr = await run_in_threadpool(lambda: [ENGINE.trade_live(t) for t in store().list(uid) if t.get("status") == "open"])
        ev.append(("trades", tr))
    if want_acct and n % 2 == 0:
        ev.append(("account", await run_in_threadpool(account_payload, uid)))
    rnew = [a for a in ENGINE.radar if a["id"] > cur["rsince"]]
    if rnew:
        cur["rsince"] = rnew[-1]["id"]
        ev.append(("radar", rnew[-20:]))
    new = [a for a in ENGINE.alerts if a["id"] > cur["since"]]
    if new:
        cur["since"] = new[-1]["id"]
        mine = [a for a in new if a.get("user") in (uid, None)]
        if mine:
            ev.append(("alerts", mine))
    if n % 3 == 0:
        bal = await run_in_threadpool(BROKERS.balance, uid)
        ev.append(("status", {"status": MARKET.status, "mode": MARKET.mode, "ts": MARKET.clock(), "balance": bal}))
    return ev


def _stream_params(request):
    q = request.query_params
    return (q.get("view") or "", q.get("sym") or "", q.get("tf") or "5m", q.get("acct") == "1",
            {"since": int(q.get("since") or (ENGINE.alerts[-1]["id"] if ENGINE.alerts else 0)),
             "rsince": int(q.get("rsince") or (ENGINE.radar[-1]["id"] if ENGINE.radar else 0))})


async def stream(request: Request):
    uid = uid_of(request)
    view, sym, tf, want_acct, cur = _stream_params(request)
    st = (await _stock_any(sym)) if sym else None

    async def gen():
        n = 0
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                break
            u = U.get(uid)
            if not u or u.get("disabled"):
                yield "event: signout\ndata: {}\n\n"
                break
            try:
                for name, data in await _tick(uid, view, st, tf, want_acct, cur, n):
                    yield f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps(str(e))}\n\n"
            n += 1
            await asyncio.sleep(1)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if "gzip" in request.headers.get("accept-encoding", ""):
        # Compress the live stream (6-9x smaller) and flush after every event so updates still arrive instantly.
        async def gz():
            co = zlib.compressobj(6, zlib.DEFLATED, 31)
            async for chunk in gen():
                yield co.compress(chunk.encode() if isinstance(chunk, str) else chunk) + co.flush(zlib.Z_SYNC_FLUSH)
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"
        return StreamingResponse(gz(), media_type="text/event-stream", headers=headers)
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


async def poll(request: Request):
    """Polling fallback for networks/tunnels that block live streams: the browser calls this about once a second."""
    uid = uid_of(request)
    u = U.get(uid)
    if not u or u.get("disabled"):
        return J({"events": [["signout", {}]]})
    view, sym, tf, want_acct, cur = _stream_params(request)
    n = int(request.query_params.get("n") or 0)
    st = (await _stock_any(sym)) if sym else None
    try:
        ev = await _tick(uid, view, st, tf, want_acct, cur, n)
    except Exception as e:
        ev = [("error", str(e))]
    return J({"events": [[k, v] for k, v in ev], "since": cur["since"], "rsince": cur["rsince"]})


async def ping(request: Request):
    """Public health check (used by the GitHub Pages link page to see if TradeLens is online)."""
    return Response(json.dumps({"ok": True, "app": "TradeLens", "status": MARKET.status}), media_type="application/json",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})


def build_app(feed, engine, brokers, feed_src, restart):
    global FEED, ENGINE, BROKERS, FEED_SRC, RESTART
    FEED, ENGINE, BROKERS, FEED_SRC, RESTART = feed, engine, brokers, feed_src, restart
    routes = [
        Route("/api/auth/me", auth_me), Route("/api/auth/register", auth_register, methods=["POST"]),
        Route("/api/auth/login", auth_login, methods=["POST"]), Route("/api/auth/unlock", auth_unlock, methods=["POST"]),
        Route("/api/auth/logout", auth_logout, methods=["POST"]),
        Route("/api/profile", profile, methods=["GET", "POST"]),
        Route("/api/profile/angel", profile_angel, methods=["POST", "DELETE"]),
        Route("/api/profile/password", profile_password, methods=["POST"]),
        Route("/api/profile/passcode", profile_passcode, methods=["POST"]),
        Route("/api/status", status), Route("/api/board", board), Route("/api/search", search),
        Route("/api/watchlist", watchlist, methods=["POST"]),
        Route("/api/watchlist/import", watch_import, methods=["POST"]),
        Route("/api/grid", grid), Route("/api/flow", flow), Route("/api/account", account),
        Route("/api/settings", settings_ep, methods=["GET", "POST"]), Route("/api/planner", planner),
        Route("/api/radar", radar), Route("/api/price_alerts", price_alerts, methods=["GET", "POST", "DELETE"]),
        Route("/api/trades.csv", trades_csv),
        Route("/api/stock/{sym:path}", stock), Route("/api/candles/{sym:path}", candles),
        Route("/api/backtest/{sym:path}", backtest), Route("/api/scorecard", scorecard),
        Route("/api/pnl", pnl, methods=["POST"]),
        Route("/api/trades", trades, methods=["GET", "POST"]),
        Route("/api/trades/{tid}", trade_one, methods=["PATCH", "DELETE"]),
        Route("/api/admin/users", admin_users), Route("/api/admin/trades.csv", admin_csv),
        Route("/api/admin/user/{uid}", admin_user, methods=["GET", "POST"]),
        Route("/api/stream", stream), Route("/api/poll", poll), Route("/api/ping", ping),
        Mount("/", StaticFiles(directory=str(C.ROOT / "frontend"), html=True)),
    ]
    return Starlette(routes=routes, middleware=[Middleware(Auth)])
