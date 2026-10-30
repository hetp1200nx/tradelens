"""Demo feed: a realistic simulated market so you can test every screen without an account.
Prices, volume, order book and OI move every second. NOT real market data."""
from __future__ import annotations

import math
import random
import threading
import time

from .. import analytics as A
from ..market import LOCK, Market, Stock
from ..universe import DEMO_EXTRA_FNO, DEMO_MORE, INDICES, NIFTY50, SENSEX30

TICK = 0.05


def _round_tick(p):
    return round(round(p / TICK) * TICK, 2)


class DemoFeed:
    name = "demo"

    def __init__(self, market: Market):
        self.m = market
        self.rng = random.Random(42)
        self.state: dict[str, dict] = {}
        self.real0 = time.time()
        today = A.ist_day_start(int(self.real0))
        self.v0 = today + 10 * 3600 + 30 * 60  # virtual session time starts at 10:30 IST
        self.m.clock = self.now
        self.m.mode = "demo"

    def now(self) -> int:
        return int(self.v0 + (time.time() - self.real0))

    # ------------------------------------------------------------ setup
    def _new_stock(self, s: str, fno: bool) -> Stock:
        r = random.Random(s)
        st = Stock(s, s)
        st.is_fno = fno
        base = math.exp(r.uniform(math.log(80), math.log(6000)))
        st.atr_pct = r.uniform(1.0, 4.2) if fno else r.uniform(1.4, 5.5)
        st.lot = max(1, int(round(600000 / base / 25)) * 25) if fno else 1
        self._make(st, base, r)
        return st

    def start(self):
        m = self.m
        fno_syms = list(dict.fromkeys(NIFTY50 + SENSEX30 + DEMO_EXTRA_FNO))
        for s in fno_syms:
            m.catalog[s] = {"name": s, "exch": "NSE", "fno": True}
        for s in DEMO_MORE:
            m.catalog.setdefault(s, {"name": s, "exch": "NSE", "fno": False})
        for s in fno_syms:
            m.add(self._new_stock(s, True))
        for key, (nm, ex, tok, et) in INDICES.items():
            r = random.Random(key)
            st = Stock(key, nm, ex, is_index=True)
            base = 25600 if key == "NIFTY" else 83600
            st.atr_pct = 0.85
            st.lot = 75 if key == "NIFTY" else 20
            st.strike_step = 50 if key == "NIFTY" else 100
            st.is_fno = True
            self._make(st, base, r, index=True)
            m.indices[key] = st
        m.groups["nifty50"] = [s for s in NIFTY50 if s in m.stocks]
        m.groups["sensex"] = [s for s in SENSEX30 if s in m.stocks]
        for s in m.groups["nifty50"]: m.stocks[s].groups.add("nifty50")
        for s in m.groups["sensex"]: m.stocks[s].groups.add("sensex")
        fno = sorted(m.stocks.values(), key=lambda x: -x.atr_pct)
        from .. import watch
        watch.init(self, [x.sym for x in fno[:200]])
        m.status = "live (demo)"
        m.ready = True
        threading.Thread(target=self._loop, daemon=True).start()

    def track(self, sym: str):
        """Start live (simulated) data for any listed share."""
        sym = sym.upper()
        st = self.m.stocks.get(sym) or self.m.indices.get(sym)
        if st:
            return st
        info = self.m.catalog.get(sym)
        if not info:
            return None
        st = self._new_stock(sym, info.get("fno", False))
        with LOCK:
            self.m.add(st)
        return st

    # ------------------------------------------------------------ simulated Angel account (one per user)
    def _make_portfolio(self, uid: str = "demo") -> dict:
        """A pretend demat account so the Account and Planner pages can be tried without Angel One."""
        r = random.Random("portfolio" + uid)
        pick = [s for s in NIFTY50 if s in self.m.stocks]
        r.shuffle(pick)
        hold = []
        for s in pick[:6]:
            st = self.m.stocks[s]
            qty = max(1, int(r.uniform(15000, 60000) / st.prev_close))
            hold.append({"sym": s, "exch": "NSE", "token": s, "qty": qty, "avg": round(st.prev_close * r.uniform(0.82, 1.12), 2),
                         "ltp": st.prev_close, "close": st.prev_close, "isin": ""})
        pos = []
        for s, side in ((pick[6], 1), (pick[7], -1)):
            st = self.m.stocks[s]
            qty = max(1, int(30000 / st.ltp))
            px = round(st.ltp * (1 - side * 0.004), 2)
            pos.append({"symbol": f"{s}-EQ", "underlying": s, "exch": "NSE", "token": s, "kind": "EQ", "product": "INTRADAY",
                        "netqty": side * qty, "buy_qty": qty if side > 0 else 0, "sell_qty": qty if side < 0 else 0,
                        "buy_value": px * qty if side > 0 else 0, "sell_value": px * qty if side < 0 else 0,
                        "buy_avg": px if side > 0 else 0, "sell_avg": px if side < 0 else 0, "avg": px,
                        "multiplier": 1, "ltp": st.ltp, "api_pnl": 0, "strike": 0, "opt_type": "", "expiry": ""})
        nifty = self.m.indices["NIFTY"]
        k = round(nifty.ltp / 50) * 50
        opt = {"under0": nifty.ltp, "prem0": 118.0}
        pos.append({"symbol": f"NIFTY{int(k)}CE", "underlying": "NIFTY", "exch": "NFO", "token": "OPT1", "kind": "OPT",
                    "product": "CARRYFORWARD", "netqty": 75, "buy_qty": 75, "sell_qty": 0, "buy_value": 118.0 * 75,
                    "sell_value": 0, "buy_avg": 118.0, "sell_avg": 0, "avg": 118.0, "multiplier": 1, "ltp": 118.0,
                    "api_pnl": 0, "strike": k, "opt_type": "CE", "expiry": "nearest"})
        orders = [{"id": f"DEMO{i}", "symbol": p["symbol"], "side": "BUY" if p["netqty"] > 0 else "SELL",
                   "qty": abs(p["netqty"]), "filled": abs(p["netqty"]), "price": p["avg"], "avg": p["avg"],
                   "type": "LIMIT", "product": p["product"], "status": "complete", "time": "10:05:12", "text": ""}
                  for i, p in enumerate(pos)]
        return {"hold": hold, "pos": pos, "orders": orders, "opt": opt}

    def account(self, uid: str = "demo") -> dict:
        from ..storage import store
        if not hasattr(self, "pf"):
            self.pf = {}
        pf = self.pf.get(uid)
        if pf is None:
            pf = self.pf[uid] = self._make_portfolio(uid)
        bal = float(store().ukv(uid, "settings", {}).get("demo_balance", 25000))
        nifty = self.m.indices["NIFTY"]
        for p in pf["pos"]:
            if p["kind"] == "OPT":
                p["ltp"] = round(max(0.05, pf["opt"]["prem0"] + 0.55 * (nifty.ltp - pf["opt"]["under0"])), 2)
            else:
                p["ltp"] = self.m.stocks[p["underlying"]].ltp
        for h in pf["hold"]:
            h["ltp"] = self.m.stocks[h["sym"]].ltp
        used = sum(abs(p["netqty"]) * p["avg"] * (0.2 if p["kind"] == "EQ" else 1) for p in pf["pos"])
        return {"funds": {"available": bal, "net": bal, "intraday_payin": 0, "collateral": 0, "used": round(used, 2),
                          "m2m_unrealised": 0, "m2m_realised": 0},
                "holdings": pf["hold"], "positions": pf["pos"], "orders": pf["orders"],
                "updated": self.now(), "source": "demo (simulated account)", "error": ""}

    def ltp_for(self, exch, token, sym):
        st = self.m.stocks.get(sym or "") or self.m.indices.get(sym or "")
        return st.ltp if st else None

    def _make(self, st: Stock, base: float, r: random.Random, index=False):
        # daily history: 260 days, scaled to end near base
        drift = r.uniform(-0.0008, 0.0016)
        vol_d = st.atr_pct / 100 * 0.75
        p, days = base * r.uniform(0.7, 1.2), []
        avg_vol = 0 if index else r.uniform(4e5, 2.5e7) / max(1.0, base / 400)
        t0 = A.ist_day_start(int(self.real0)) - 260 * 86400
        for i in range(260):
            o = p
            c = o * math.exp(drift + vol_d * r.gauss(0, 1))
            h = max(o, c) * (1 + abs(r.gauss(0, vol_d * 0.5)))
            l = min(o, c) * (1 - abs(r.gauss(0, vol_d * 0.5)))
            days.append({"t": t0 + i * 86400, "o": o, "h": h, "l": l, "c": c, "v": avg_vol * r.uniform(0.5, 1.8)})
            p = c
        k = base / days[-1]["c"]
        for d in days:
            for f in "ohlc":
                d[f] = _round_tick(d[f] * k)
        st.daily = days
        st.refresh_daily_stats()
        st.prev_close = days[-1]["c"]
        st.atr_pct = st.atr_pct  # keep target volatility
        # today's character
        trend = r.choice([2.2, 1.6, 1.0, 0.5, 0.0, 0.0, -0.5, -1.0, -1.6, -2.2])
        sigma_s = st.atr_pct / 100 / math.sqrt(22500) * 0.75
        self.state[st.sym] = {
            "r": r, "mu": trend * st.atr_pct / 100 / 22500 * 0.8, "sig": sigma_s, "burst": 0, "bdir": 0,
            "avg_vol": avg_vol, "oi": 0 if index else avg_vol * r.uniform(2, 8), "oi0": None,
            "press": 0.0, "index": index, "cum": 0.0,
        }
        st.oi_chg_pct = 0.0
        # today's 1m candles from 09:15 to the virtual start time
        open_t = A.ist_day_start(self.v0) + A.SESSION_OPEN
        gap = r.gauss(0, st.atr_pct / 100 * 0.3)
        price = st.prev_close * math.exp(gap)
        st.open = 0
        t = open_t
        end = self.now()
        while t < end:
            price = self._advance(st, price, t)
            t += 1

    def _advance(self, st: Stock, price: float, ts: int) -> float:
        """Advance one second of simulated trading."""
        s = self.state[st.sym]
        r = s["r"]
        if s["burst"] <= 0 and r.random() < 0.0025:
            s["burst"] = r.randint(15, 70)
            s["bdir"] = (1 if s["mu"] >= 0 else -1) if r.random() < 0.65 else (-1 if s["mu"] >= 0 else 1)
        b = 0.0
        if s["burst"] > 0:
            s["burst"] -= 1
            b = s["bdir"] * s["sig"] * 0.45
        if r.random() < 0.00015:  # trend change during the day
            s["mu"] = -s["mu"] * r.uniform(0.3, 1.0)
        ret = s["mu"] + b + s["sig"] * r.gauss(0, 1)
        price = max(1.0, price * math.exp(ret))
        sod = A.ist_seconds_of_day(ts)
        u = 1.0 + 1.6 * math.exp(-((sod - A.SESSION_OPEN) / 2400.0)) + 0.8 * math.exp(-((A.SESSION_CLOSE - sod) / 2400.0))
        dv = s["avg_vol"] / 22500 * u * (0.25 + 0.9 * abs(ret) / (s["sig"] or 1)) * r.uniform(0.6, 1.4)
        s["cum"] += dv
        s["press"] = 0.85 * s["press"] + 0.15 * max(-1, min(1, (ret / (s["sig"] or 1)) * 0.6 + (s["mu"] / (s["sig"] or 1)) * 8))
        st.on_tick(_round_tick(price), s["cum"] if not s["index"] else None, ts)
        return price

    # ------------------------------------------------------------ live loop
    def _loop(self):
        while True:
            t0 = time.time()
            now = self.now()
            sod = A.ist_seconds_of_day(now)
            if A.SESSION_OPEN <= sod <= A.SESSION_CLOSE:
                with LOCK:
                    for st in list(self.m.stocks.values()) + list(self.m.indices.values()):
                        self._advance(st, st.ltp, now)
                        self._book(st)
                self.m.status = "live (demo)"
            else:
                self.m.status = "closed (demo)"
            self.m.compute_all()
            time.sleep(max(0.05, 1.0 - (time.time() - t0)))

    def _book(self, st: Stock):
        s = self.state[st.sym]
        if s["index"]:
            return
        r = s["r"]
        p = max(-0.9, min(0.9, s["press"] + r.gauss(0, 0.12)))
        total = s["avg_vol"] * 0.03 * r.uniform(0.8, 1.2)
        st.buy_qty = round(total * (1 + p) / 2)
        st.sell_qty = round(total * (1 - p) / 2)
        lv = max(1, int(s["avg_vol"] / 4000))
        st.bids = [{"price": _round_tick(st.ltp - TICK * (i + 1)), "qty": int(lv * r.uniform(0.2, 2) * (1 + p)), "orders": r.randint(1, 40)} for i in range(5)]
        st.asks = [{"price": _round_tick(st.ltp + TICK * (i + 1)), "qty": int(lv * r.uniform(0.2, 2) * (1 - p)), "orders": r.randint(1, 40)} for i in range(5)]
        st.avg_price = st.avg_price * 0.98 + st.ltp * 0.02 if st.avg_price else st.ltp
        if s["oi0"] is None:
            s["oi0"] = s["oi"]
        s["oi"] *= math.exp(r.gauss(abs(s["mu"]) * 3, 0.0004))
        st.oi = round(s["oi"])
        st.oi_chg_pct = (s["oi"] / s["oi0"] - 1) * 100
        st.uc = round(st.prev_close * 1.2, 2)
        st.lc = round(st.prev_close * 0.8, 2)
        st.w52h = max(c["h"] for c in st.daily[-250:])
        st.w52l = min(c["l"] for c in st.daily[-250:])

    # ------------------------------------------------------------ history on demand
    def ensure_history(self, st: Stock):
        """Add 4 previous simulated days of 1-minute candles for charts and backtests."""
        if st.hist_loaded:
            return
        r = random.Random(st.sym + "hist")
        mins, p = [], st.daily[-5]["c"]
        sig = (st.atr_pct or 1.5) / 100 / math.sqrt(375) * 1.1
        for back in range(4, 0, -1):
            day = A.ist_day_start(self.v0) - back * 86400
            mu = r.choice([-1, -0.5, 0, 0.5, 1]) * sig * 0.15
            for i in range(375):
                o = p
                p = o * math.exp(mu + sig * r.gauss(0, 1) + (sig * 2 * r.choice([-1, 1]) if r.random() < 0.03 else 0))
                h = max(o, p) * (1 + abs(r.gauss(0, sig * 0.4)))
                l = min(o, p) * (1 - abs(r.gauss(0, sig * 0.4)))
                mins.append({"t": day + A.SESSION_OPEN + i * 60, "o": o, "h": h, "l": l, "c": p,
                             "v": self.state[st.sym]["avg_vol"] / 375 * r.uniform(0.4, 1.8)})
        k = st.prev_close / mins[-1]["c"]
        for c in mins:
            for f in "ohlc":
                c[f] = _round_tick(c[f] * k)
        with LOCK:
            st.m1 = mins + st.m1
            st.hist_loaded = True

    def option_quote(self, st, strike, typ):
        return None  # demo: premium is estimated in signals.option()

    def history_5m(self, st: Stock, days: int = 60):
        self.ensure_history(st)
        return A.resample(st.m1, 5)
