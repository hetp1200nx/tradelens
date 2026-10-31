"""In-memory market state: quotes, live candle building and board metrics for every tracked stock."""
from __future__ import annotations

import threading
import time

from . import analytics as A

LOCK = threading.RLock()


class Stock:
    def __init__(self, sym, name=None, exch="NSE", token=None, is_index=False):
        self.sym = sym
        self.name = name or sym
        self.exch = exch
        self.token = token
        self.fut_token = None
        self.lot = 1
        self.strike_step = None
        self.is_fno = False
        self.is_index = is_index
        self.groups: set[str] = set()
        from .universe import SECTOR_OF
        self.sector = SECTOR_OF.get(sym, "Index" if is_index else "Other")
        # live quote
        self.ltp = self.open = self.high = self.low = self.prev_close = 0.0
        self.volume = 0.0
        self.avg_price = 0.0
        self.buy_qty = self.sell_qty = 0.0
        self.bids: list[dict] = []
        self.asks: list[dict] = []
        self.oi = 0.0
        self.oi_chg_pct = 0.0
        self.oi_chg_ok = True
        self.uc = self.lc = 0.0
        self.w52h = self.w52l = 0.0
        self.last_ts = 0
        # history
        self.daily: list[dict] = []     # completed days, oldest first
        self.m1: list[dict] = []        # 1-minute candles (history + today), oldest first
        self.hist_loaded = False
        self._last_cum_vol = 0.0
        self.avg_vol20 = 0.0
        self.atr_d = 0.0
        self.atr_pct = 0.0
        self.metrics: dict = {}

    # ----- stats from daily history -----
    def refresh_daily_stats(self):
        if self.daily:
            vols = [c["v"] for c in self.daily[-20:]]
            self.avg_vol20 = sum(vols) / len(vols) if vols else 0
            self.atr_d = A.atr(self.daily[-60:], 14)
            last = self.daily[-1]["c"] or 1
            self.atr_pct = self.atr_d / last * 100
            if not self.prev_close:
                self.prev_close = self.daily[-1]["c"]

    # ----- live tick -----
    def on_tick(self, ltp: float, cum_vol: float | None, ts: int):
        if ltp <= 0:
            return
        if self.last_ts and A.ist_day_start(ts) > A.ist_day_start(self.last_ts) and self.ltp:
            # new trading day: close yesterday into daily history and reset the day's values
            if self.open:
                self.daily.append({"t": A.ist_day_start(self.last_ts), "o": self.open, "h": self.high,
                                   "l": self.low, "c": self.ltp, "v": self.volume})
                self.daily = self.daily[-400:]
            self.prev_close = self.ltp
            self.open = self.high = self.low = 0.0
            self.volume = 0.0
            self._last_cum_vol = 0.0
            self.refresh_daily_stats()
        self.ltp = ltp
        self.last_ts = ts
        if not self.open:
            self.open = ltp
        self.high = max(self.high or ltp, ltp)
        self.low = min(self.low or ltp, ltp)
        if cum_vol is not None:
            if cum_vol < self._last_cum_vol:
                self._last_cum_vol = 0.0
            dv = cum_vol - self._last_cum_vol if self._last_cum_vol else 0.0
            self._last_cum_vol = cum_vol
            self.volume = cum_vol
        else:
            dv = 0.0
        minute = ts // 60 * 60
        if self.m1 and self.m1[-1]["t"] == minute:
            c = self.m1[-1]
            c["h"] = max(c["h"], ltp)
            c["l"] = min(c["l"], ltp)
            c["c"] = ltp
            c["v"] += dv
        elif not self.m1 or minute > self.m1[-1]["t"]:
            self.m1.append({"t": minute, "o": ltp, "h": ltp, "l": ltp, "c": ltp, "v": dv})
            if len(self.m1) > 2600:
                del self.m1[: len(self.m1) - 2600]

    def today_candles(self, now: int) -> list[dict]:
        day = A.ist_day_start(self.m1[-1]["t"]) if self.m1 else A.ist_day_start(now)
        return [c for c in self.m1 if c["t"] >= day]

    # ----- board metrics -----
    def compute_metrics(self, now: int):
        if self.ltp <= 0:
            self.metrics = {}
            return
        pc = self.prev_close or self.open or self.ltp
        chg = (self.ltp - pc) / pc * 100
        atr_pct = self.atr_pct or 1.5
        norm = chg / atr_pct
        sod = A.ist_seconds_of_day(now)
        frac = min(1.0, max(0.06, (sod - A.SESSION_OPEN) / (A.SESSION_CLOSE - A.SESSION_OPEN)))
        last_day = A.ist_day_start(self.m1[-1]["t"]) if self.m1 else A.ist_day_start(now)
        if sod < A.SESSION_OPEN or last_day < A.ist_day_start(now):
            frac = 1.0   # market not open yet / weekend / holiday: volume shown is the last full session
        exp_vol = self.avg_vol20 * frac
        vol_ratio = self.volume / exp_vol if exp_vol else 1.0
        tot = self.buy_qty + self.sell_qty
        pressure = (self.buy_qty - self.sell_qty) / tot if tot else 0.0
        rng = (self.high - self.low) or 1e-9
        range_pos = (self.ltp - self.low) / rng
        today = self.today_candles(now)
        if len(today) >= 10:
            eff = A.range_efficiency(A.resample(today, 5))
            last15 = today[-15:]
            mom = (last15[-1]["c"] - last15[0]["o"]) / pc * 100 / atr_pct
        else:
            eff = abs(self.ltp - (self.open or self.ltp)) / rng
            mom = norm
        direction = 1 if chg > 0 else -1 if chg < 0 else 0
        choppy = abs(norm) < 0.3 or eff < 0.15
        # OI interpretation (F&O only)
        oi_sig = ""
        if self.is_fno and self.oi:
            if chg > 0 and self.oi_chg_pct > 0:
                oi_sig = "Long build-up"
            elif chg > 0 and self.oi_chg_pct < 0:
                oi_sig = "Short covering"
            elif chg < 0 and self.oi_chg_pct > 0:
                oi_sig = "Short build-up"
            elif chg < 0 and self.oi_chg_pct < 0:
                oi_sig = "Long unwinding"
        if choppy:
            strength = 0.0
            liquidity = 0.0
        else:
            aligned_pos = range_pos if direction > 0 else 1 - range_pos
            strength = (min(abs(norm), 3) / 3 * 50 + min(vol_ratio, 3) / 3 * 25
                        + max(0.0, pressure * direction) * 15 + aligned_pos * 10)
            oi_confirm = 1.0 if oi_sig in ("Long build-up", "Short build-up") else 0.5 if oi_sig else 0.4
            liquidity = (min(vol_ratio, 3) / 3 * 40 + min(abs(mom), 1.5) / 1.5 * 30 * (1 if mom * direction > 0 else 0.3)
                         + oi_confirm * 30)
        if choppy:
            bias = "Choppy"
        elif direction > 0:
            bias = "Strong bullish" if strength >= 60 else "Bullish"
        else:
            bias = "Strong bearish" if strength >= 60 else "Bearish"
        self.metrics = {
            "sym": self.sym, "name": self.name, "sector": self.sector, "ltp": round(self.ltp, 2), "chg": round(chg, 2),
            "open": self.open, "high": self.high, "low": self.low, "prev_close": pc,
            "volume": self.volume, "vol_ratio": round(vol_ratio, 2), "pressure": round(pressure, 3),
            "buy_qty": self.buy_qty, "sell_qty": self.sell_qty,
            "oi": self.oi, "oi_chg": round(self.oi_chg_pct, 2) if self.oi_chg_ok else None, "oi_signal": oi_sig,
            "strength": round(strength, 1), "liquidity": round(liquidity, 1),
            "direction": direction, "bias": bias, "choppy": choppy, "is_fno": self.is_fno,
            "atr_pct": round(atr_pct, 2), "is_index": self.is_index,
            "above_vwap": (self.ltp >= self.avg_price) if self.avg_price else None,
        }


class Market:
    def __init__(self):
        self.stocks: dict[str, Stock] = {}
        self.groups: dict[str, list[str]] = {"sensex": [], "nifty50": [], "watchlist": []}
        # every share that can be searched and added: sym -> {"name", "exch", "token", "fno"}
        self.catalog: dict[str, dict] = {}
        self.auto_watch: list[str] = []  # default Volatile Watchlist for new users
        self.indices: dict[str, Stock] = {}
        self.status = "starting"
        self.mode = "demo"
        self.clock = lambda: int(time.time())  # demo mode replaces this with its virtual clock
        self.ready = False

    def add(self, st: Stock):
        self.stocks[st.sym] = st

    def compute_all(self):
        now = self.clock()
        with LOCK:
            for st in list(self.stocks.values()) + list(self.indices.values()):
                try:
                    st.compute_metrics(now)
                except Exception:
                    st.metrics = {}

    def board(self, view: str, syms: list[str] | None = None) -> dict:
        syms = syms if syms is not None else self.groups.get(view, [])
        rows = [self.stocks[s].metrics for s in syms if s in self.stocks and self.stocks[s].metrics]
        bulls = sorted([r for r in rows if r["direction"] > 0 and not r["choppy"]],
                       key=lambda r: -r["strength"])[:20]
        bears = sorted([r for r in rows if r["direction"] < 0 and not r["choppy"]],
                       key=lambda r: -r["strength"])[:20]
        adv = sum(1 for r in rows if r["chg"] > 0)
        dec = sum(1 for r in rows if r["chg"] < 0)
        vw = [r for r in rows if r.get("above_vwap") is not None]
        above = sum(1 for r in vw if r["above_vwap"])
        tot = len(rows) or 1
        mood = round((adv / tot) * 50 + ((above / len(vw)) if vw else adv / tot) * 50)
        mood_label = ("Strongly bullish" if mood >= 70 else "Bullish" if mood >= 57 else "Strongly bearish" if mood <= 30
                      else "Bearish" if mood <= 43 else "Neutral")
        return {"view": view, "rows": rows, "bulls": bulls, "bears": bears,
                "breadth": {"adv": adv, "dec": dec, "total": len(rows), "above_vwap": above,
                            "mood": mood, "mood_label": mood_label},
                "indices": {k: v.metrics for k, v in self.indices.items() if v.metrics},
                "status": self.status, "mode": self.mode, "ts": self.clock()}


    def search(self, q: str, limit: int = 20, watch: list[str] | None = None) -> list[dict]:
        """Live search across every listed share (prefix matches first, then name matches)."""
        q = q.upper().strip()
        if not q:
            return []
        wl = set(watch if watch is not None else self.groups.get("watchlist", []))
        pref, cont = [], []
        for sym, info in self.catalog.items():
            if sym.startswith(q):
                pref.append(sym)
            elif q in sym or q in (info.get("name") or "").upper():
                cont.append(sym)
            if len(pref) >= limit:
                break
        out = []
        for sym in sorted(pref, key=len)[:limit] + sorted(cont)[: max(0, limit - len(pref))]:
            info = self.catalog[sym]
            st = self.stocks.get(sym) or self.indices.get(sym)
            out.append({"sym": sym, "name": info.get("name") or sym, "fno": info.get("fno", False),
                        "in_watchlist": sym in wl, "ltp": st.ltp if st else None,
                        "chg": st.metrics.get("chg") if st and st.metrics else None})
        return out


MARKET = Market()
