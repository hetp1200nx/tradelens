"""Background work: live P&L on your trades, exit alerts, signal scorecard, backtests, Telegram."""
from __future__ import annotations

import threading
import time

import requests

from . import analytics as A
from . import config as C
from . import signals as S
from .charges import trade_pnl
from .market import LOCK, MARKET
from .storage import store


class Engine:
    def __init__(self, feed):
        self.feed = feed
        self.alerts: list[dict] = []
        self._alert_id = 0
        self.sig_cache: dict[str, tuple[float, dict]] = {}
        self.scorecard: list[dict] = list(store().kv.get("scorecard", []) or [])
        self._last_score_save = time.time()
        self.radar: list[dict] = []
        self._radar_id = 0
        self._radar_seen: dict[tuple, float] = {}
        self._prev_metrics: dict[str, dict] = {}

    # ---------------- helpers
    def stock(self, sym):
        return MARKET.stocks.get(sym) or MARKET.indices.get(sym)

    def signals_for(self, st, max_age=2.0) -> dict:
        hit = self.sig_cache.get(st.sym)
        if hit and time.time() - hit[0] < max_age:
            return hit[1]
        with LOCK:
            sig = S.all_signals(st, MARKET.clock(), self.feed.option_quote)
        self.sig_cache[st.sym] = (time.time(), sig)
        return sig

    def push_alert(self, kind, text, sym=None, trade_id=None, user=None):
        self._alert_id += 1
        a = {"id": self._alert_id, "kind": kind, "text": text, "sym": sym, "trade_id": trade_id, "ts": int(time.time()), "user": user}
        self.alerts.append(a)
        self.alerts = self.alerts[-300:]
        if C.TELEGRAM_BOT_TOKEN and C.TELEGRAM_CHAT_ID:
            threading.Thread(target=self._telegram, args=(f"TradeLens: {text}",), daemon=True).start()

    def _telegram(self, text):
        try:
            requests.post(f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/sendMessage",
                          json={"chat_id": C.TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        except Exception:
            pass

    # ---------------- trades
    def trade_live(self, t: dict) -> dict:
        st = self.stock(t["symbol"])
        out = dict(t)
        if not st or st.ltp <= 0:
            out["live"] = None
            return out
        seg = t.get("segment", "intraday")
        cur, estimated = st.ltp, False
        if seg == "option":
            q = self.feed.option_quote(st, float(t.get("opt_strike") or 0), t.get("opt_type", "CE"))
            if q and q.get("ltp"):
                cur = q["ltp"]
            else:
                ue = float(t.get("underlying_entry") or st.ltp)
                d = 1 if t.get("opt_type", "CE") == "CE" else -1
                cur = max(0.05, float(t["entry"]) + 0.6 * (st.ltp - ue) * d)
                estimated = True
        if t.get("status") == "closed":
            cur = float(t.get("exit_price") or cur)
        side = t.get("side", "BUY")
        qty = float(t.get("qty") or 0)
        entry = float(t.get("entry") or 0)
        pnl = trade_pnl(side, entry, cur, qty, seg)
        d = 1 if side == "BUY" else -1
        sl, t1, t2 = (float(t[k]) if t.get(k) not in (None, "") else None for k in ("sl", "t1", "t2"))
        state, advice = "running", "Hold. Stay with the plan."
        if sl is not None and (cur - sl) * d <= 0:
            state, advice = "sl_hit", "Stop-loss hit: EXIT now and protect capital."
        elif t2 is not None and (cur - t2) * d >= 0:
            state, advice = "t2_hit", "Target 2 reached: EXIT and book full profit."
        elif t1 is not None and (cur - t1) * d >= 0:
            state, advice = "t1_hit", "Target 1 reached: book part profit, move stop-loss to your entry price."
        # setup check from the live signal of the underlying
        sig = self.signals_for(st, 5)
        style = "long" if seg == "delivery" else "intraday"
        s = sig[style]
        if state == "running":
            if (d > 0 and s["action"] == "SELL") or (d < 0 and s["action"] == "BUY"):
                state, advice = "flip", f"Signal turned {'bearish' if d > 0 else 'bullish'}: consider exiting early."
            elif seg in ("intraday", "option", "futures") and A.ist_seconds_of_day(MARKET.clock()) >= 15 * 3600 + 10 * 60:
                state, advice = "eod", "Market closes soon: square off intraday position."
        out["live"] = {"price": round(cur, 2), "estimated": estimated, "underlying": st.ltp, "pnl": pnl,
                       "state": state, "advice": advice,
                       "to_sl": None if sl is None else round((cur - sl) * d, 2),
                       "to_t1": None if t1 is None else round((t1 - cur) * d, 2)}
        return out

    def _check_trades(self):
        stg = store()
        for t in list(stg.trades.values()):
            if t.get("status") != "open":
                continue
            lv = self.trade_live(t).get("live")
            if not lv:
                continue
            kind = lv["state"]
            sent = t.setdefault("alerts_sent", [])
            if kind != "running" and kind not in sent:
                sent.append(kind)
                stg.update(t["id"], {"alerts_sent": sent})
                self.push_alert(kind, f"{t['symbol']} {t.get('side')} @ {t.get('entry')}: {lv['advice']} (now {lv['price']}, P&L ₹{lv['pnl']['net']:,.0f})",
                                t["symbol"], t["id"], t.get("user"))

    # ---------------- scorecard (how good were past signals?)
    def _scorecard_collect(self):
        cand = set()
        for g in ("watchlist", "nifty50", "sensex"):
            b = MARKET.board(g)
            cand.update(r["sym"] for r in b["bulls"][:8] + b["bears"][:8])
        active = {(x["sym"], x["style"]) for x in self.scorecard if x["status"] == "active"}
        for sym in cand:
            if (sym, "intraday") in active:
                continue
            st = self.stock(sym)
            if not st:
                continue
            self.feed.ensure_history(st)  # signals need a few days of 5-minute candles
            s = self.signals_for(st, 10)["intraday"]
            if s["action"] in ("BUY", "SELL") and s.get("entry"):
                self.scorecard.append({"sym": sym, "style": "intraday", "side": s["action"], "entry": s["entry"],
                                       "sl": s["sl"], "t1": s["t1"], "t": MARKET.clock(), "status": "active", "r": None})
        self.scorecard = self.scorecard[-400:]

    def _scorecard_update(self):
        now = MARKET.clock()
        sod = A.ist_seconds_of_day(now)
        for x in self.scorecard:
            if x["status"] != "active":
                continue
            st = self.stock(x["sym"])
            if not st or st.ltp <= 0:
                continue
            d = 1 if x["side"] == "BUY" else -1
            risk = abs(x["entry"] - x["sl"]) or 1e-9
            p = st.ltp
            if (p - x["sl"]) * d <= 0:
                x.update(status="loss", r=-1.0, closed=now)
            elif (p - x["t1"]) * d >= 0:
                x.update(status="win", r=round(abs(x["t1"] - x["entry"]) / risk, 2), closed=now)
            elif sod >= 15 * 3600 + 20 * 60 or A.ist_day_start(now) > A.ist_day_start(x["t"]):
                x.update(status="expired", r=round((p - x["entry"]) * d / risk, 2), closed=now)
        if time.time() - self._last_score_save > 60:
            self._last_score_save = time.time()
            store().set_kv("scorecard", self.scorecard)

    def scorecard_stats(self) -> dict:
        done = [x for x in self.scorecard if x["status"] in ("win", "loss", "expired")]
        wins = [x for x in done if x["status"] == "win" or (x["status"] == "expired" and (x["r"] or 0) > 0)]
        tot_r = sum(x["r"] or 0 for x in done)
        return {"total": len(done), "wins": len(wins), "losses": len(done) - len(wins),
                "win_rate": round(len(wins) / len(done) * 100, 1) if done else None,
                "avg_r": round(tot_r / len(done), 2) if done else None, "total_r": round(tot_r, 2),
                "active": [x for x in self.scorecard if x["status"] == "active"][-30:],
                "recent": done[-40:][::-1]}

    # ---------------- live radar: unusual activity across every tracked share
    def _radar_event(self, sym, kind, text, tone):
        key = (sym, kind)
        if time.time() - self._radar_seen.get(key, 0) < 20 * 60:  # same event for a stock at most every 20 min
            return
        self._radar_seen[key] = time.time()
        self._radar_id += 1
        self.radar.append({"id": self._radar_id, "sym": sym, "kind": kind, "text": text, "tone": tone, "ts": MARKET.clock()})
        self.radar = self.radar[-150:]

    def _radar_scan(self):
        sod = A.ist_seconds_of_day(MARKET.clock())
        if not (A.SESSION_OPEN + 5 * 60 <= sod <= A.SESSION_CLOSE):
            return
        with LOCK:
            items = [(s, st.metrics, st.high, st.low, st.ltp) for s, st in MARKET.stocks.items() if st.metrics]
        for sym, m, hi, lo, ltp in items:
            prev = self._prev_metrics.get(sym)
            self._prev_metrics[sym] = {"vol_ratio": m["vol_ratio"], "strength": m["strength"], "high": hi, "low": lo, "bias": m["bias"]}
            if not prev:
                continue
            if m["vol_ratio"] >= 2.5 > prev["vol_ratio"]:
                self._radar_event(sym, "volume", f"Volume spike: {m['vol_ratio']:.1f}x normal ({m['chg']:+.2f}%)", "warn")
            if hi > prev["high"] > 0 and m["vol_ratio"] >= 1.3 and m["direction"] > 0:
                self._radar_event(sym, "high", f"New day high {hi:.2f} with {m['vol_ratio']:.1f}x volume", "up")
            if 0 < lo < prev["low"] and m["vol_ratio"] >= 1.3 and m["direction"] < 0:
                self._radar_event(sym, "low", f"New day low {lo:.2f} with {m['vol_ratio']:.1f}x volume", "down")
            if m["strength"] >= 70 > prev["strength"]:
                self._radar_event(sym, "strength", f"{m['bias']}: strength crossed 70 ({m['chg']:+.2f}%)", "up" if m["direction"] > 0 else "down")
            if prev["bias"] == "Choppy" and m["bias"] != "Choppy" and m["strength"] >= 40:
                self._radar_event(sym, "trend", f"Trend started: {m['bias'].lower()} after choppy trading", "up" if m["direction"] > 0 else "down")

    # ---------------- price alerts you set
    def _check_price_alerts(self):
        stg = store()
        for key in [k for k in list(stg.kv) if k.startswith("u:") and k.endswith(":price_alerts")]:
            self._check_user_alerts(key.split(":")[1])

    def _check_user_alerts(self, uid):
        stg = store()
        alerts = stg.ukv(uid, "price_alerts", [])
        changed = False
        for a in alerts:
            if a.get("done"):
                continue
            st = self.stock(a["sym"])
            if not st or st.ltp <= 0:
                continue
            hit = st.ltp >= a["price"] if a["op"] == "above" else st.ltp <= a["price"]
            if hit:
                a["done"] = True
                a["hit_at"] = MARKET.clock()
                changed = True
                self.push_alert("price", f"{a['sym']} {'crossed above' if a['op'] == 'above' else 'fell below'} {a['price']} (now {st.ltp})"
                                + (f": {a['note']}" if a.get("note") else ""), a["sym"], user=uid)
        if changed:
            stg.set_ukv(uid, "price_alerts", alerts)

    # ---------------- loop
    def start(self):
        def loop():
            n = 0
            while True:
                try:
                    if MARKET.ready:
                        self._check_trades()
                        self._check_price_alerts()
                        self._scorecard_update()
                        if n % 3 == 0:
                            self._radar_scan()
                        if n % 30 == 5:
                            self._scorecard_collect()
                except Exception as e:
                    print("engine error:", e)
                n += 1
                time.sleep(1)
        threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------- BACKTEST
def backtest_intraday(c5: list[dict]) -> dict:
    """Replays the intraday order-block rule on past 5-minute candles.
    Entry when price returns into a fresh order block in the trend direction (above/below VWAP and EMA20 vs EMA50).
    Stop just beyond the block, target 1.5R, forced exit 15:15. Max 2 trades per day."""
    n = len(c5)
    if n < 120:
        return {"error": "Not enough history for a backtest (need 120+ five-minute candles)."}
    closes = [c["c"] for c in c5]
    e20, e50 = A.ema(closes, 20), A.ema(closes, 50)
    vw, cur_day, pv, vv = [], None, 0.0, 0.0
    for c in c5:
        d = A.ist_day_start(c["t"])
        if d != cur_day:
            cur_day, pv, vv = d, 0.0, 0.0
        pv += (c["h"] + c["l"] + c["c"]) / 3 * c["v"]
        vv += c["v"]
        vw.append(pv / vv if vv else e20[len(vw)])  # indices have no volume
    trades, pos, obs = [], None, []
    per_day: dict[int, int] = {}
    for i in range(60, n):
        c = c5[i]
        sod = A.ist_seconds_of_day(c["t"])
        day = A.ist_day_start(c["t"])
        if pos:
            d = pos["d"]
            hit_sl = (c["l"] <= pos["sl"]) if d > 0 else (c["h"] >= pos["sl"])
            hit_t = (c["h"] >= pos["t1"]) if d > 0 else (c["l"] <= pos["t1"])
            r = None
            if hit_sl:
                r = -1.0
            elif hit_t:
                r = 1.5
            elif sod >= 15 * 3600 + 15 * 60 or day != pos["day"]:
                r = (c["c"] - pos["entry"]) * d / pos["risk"]
            if r is not None:
                cost_r = pos["entry"] * 0.0006 / pos["risk"]
                trades.append({"t": pos["t"], "side": "BUY" if d > 0 else "SELL", "entry": round(pos["entry"], 2),
                               "sl": round(pos["sl"], 2), "t1": round(pos["t1"], 2), "r": round(r, 2),
                               "r_net": round(r - cost_r, 2)})
                pos = None
            continue
        if i % 3 == 0:
            obs = A.order_blocks(c5[max(0, i - 150):i], 3)
        if not (A.SESSION_OPEN + 15 * 60 <= sod <= 14 * 3600 + 45 * 60) or per_day.get(day, 0) >= 2:
            continue
        a = A.atr(c5[max(0, i - 60):i], 14)
        bull = c["c"] > vw[i] and e20[i - 1] > e50[i - 1]
        bear = c["c"] < vw[i] and e20[i - 1] < e50[i - 1]
        for ob in obs:
            if bull and ob["type"] == "bull" and c["l"] <= ob["top"] and c["c"] >= ob["bottom"] and c5[i - 1]["l"] > ob["top"]:
                entry = min(ob["top"], c["o"])
                sl = ob["bottom"] - 0.25 * a
                d = 1
            elif bear and ob["type"] == "bear" and c["h"] >= ob["bottom"] and c["c"] <= ob["top"] and c5[i - 1]["h"] < ob["bottom"]:
                entry = max(ob["bottom"], c["o"])
                sl = ob["top"] + 0.25 * a
                d = -1
            else:
                continue
            risk = abs(entry - sl)
            if risk <= entry * 0.001:
                continue
            pos = {"d": d, "entry": entry, "sl": sl, "t1": entry + d * 1.5 * risk, "risk": risk, "t": c["t"], "day": day}
            per_day[day] = per_day.get(day, 0) + 1
            break
    if not trades:
        return {"trades": [], "n": 0, "note": "The rule found no trades in this period."}
    wins = [t for t in trades if t["r"] > 0]
    gp = sum(t["r"] for t in trades if t["r"] > 0)
    gl = -sum(t["r"] for t in trades if t["r"] < 0)
    streak = worst = 0
    for t in trades:
        streak = streak + 1 if t["r"] < 0 else 0
        worst = max(worst, streak)
    days = len({A.ist_day_start(c["t"]) for c in c5})
    return {"n": len(trades), "days": days, "wins": len(wins), "losses": len(trades) - len(wins),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "avg_r": round(sum(t["r"] for t in trades) / len(trades), 2),
            "avg_r_net": round(sum(t["r_net"] for t in trades) / len(trades), 2),
            "total_r": round(sum(t["r"] for t in trades), 2),
            "profit_factor": round(gp / gl, 2) if gl else None,
            "max_losing_streak": worst, "trades": trades[-40:][::-1]}
