"""Trade Planner: turns your available balance into concrete, sized trade ideas with expected P&L.

How it works (all visible in the app):
1. Scans the strongest stocks (Nifty 50, Sensex, your watchlist) for intraday + option setups,
   and every tracked stock for long-term setups, using the same rules as the stock page.
2. Sizes each idea so the loss at stop-loss is at most your risk-per-trade (default 1% of balance),
   and capital/margin per idea is at most your max-allocation (default 40%).
3. Expected P&L = win-chance x (net profit at target 1) + loss-chance x (net loss at stop-loss), after all charges.
   The win-chance comes from the app's own Scorecard once it has 20+ results; until then a cautious default is used,
   and the page says which one it used.
4. Only ideas with positive expected P&L are shown, best first. The "fits together" set never uses more
   than your balance and never risks more than 4x your per-trade risk at once.
Rules, not guarantees: a positive expected value means the setup has paid off on average, not that this trade will.
"""
from __future__ import annotations

import math
import time

from . import analytics as A
from . import signals as S
from .charges import trade_pnl
from .market import LOCK, MARKET

DEFAULTS = {"risk_pct": 1.0, "max_alloc_pct": 40.0, "intraday_leverage": 5.0, "max_per_style": 4,
            "min_balance": 2000.0, "default_p_intraday": 0.42, "default_p_long": 0.45}

_cache: dict = {}


def _p(engine, style, st_cfg):
    sc = engine.scorecard_stats()
    if style in ("intraday", "option") and (sc.get("total") or 0) >= 20 and sc.get("win_rate") is not None:
        p = sc["win_rate"] / 100
        return max(0.25, min(0.70, p)), f"your Scorecard ({sc['total']} live signals, {sc['win_rate']}% hit target 1)"
    key = "default_p_long" if style == "long" else "default_p_intraday"
    return st_cfg[key], f"cautious default {st_cfg[key] * 100:.0f}% (Scorecard needs 20+ results first)"


def _idea(st, style, sig, side, entry, sl, t1, t2, qty, seg, capital, p, p_src, extra=None):
    r_sl = trade_pnl(side, entry, sl, qty, seg)
    r_t1 = trade_pnl(side, entry, t1, qty, seg)
    r_t2 = trade_pnl(side, entry, t2, qty, seg)
    ev = p * r_t1["net"] + (1 - p) * r_sl["net"]
    risk = -r_sl["net"]
    d = {"sym": st.sym, "style": style, "action": sig["action"], "side": side, "segment": seg,
         "ready": sig["action"] in ("BUY", "SELL") or sig["action"].startswith("BUY "),
         "entry": round(entry, 2), "sl": round(sl, 2), "t1": round(t1, 2), "t2": round(t2, 2), "qty": qty,
         "capital": round(capital, 2), "risk": round(risk, 2), "profit_t1": r_t1["net"], "profit_t2": r_t2["net"],
         "charges": r_t1["charges"]["total"], "ev": round(ev, 2), "ev_per_risk": round(ev / risk, 3) if risk > 0 else 0,
         "p": round(p, 3), "p_source": p_src, "confidence": sig.get("confidence"), "summary": sig.get("summary", ""),
         "reasons": sig.get("reasons", [])[:4], "warnings": [w["text"] for w in sig.get("warnings", [])][:3],
         "ltp": st.ltp}
    if extra:
        d.update(extra)
    return d


def build(engine, feed, balance: float, cfg: dict, uid: str = "", watch: list[str] | None = None) -> dict:
    c = {**DEFAULTS, **(cfg or {})}
    key = (round(balance), tuple(sorted(c.items())))
    hit = _cache.get(uid)
    if hit and hit[0] == key and time.time() - hit[1] < 30:
        return hit[2]
    out = {"balance": balance, "settings": c, "generated": MARKET.clock(), "ideas": {"intraday": [], "long": [], "option": []},
           "skipped": [], "recharge": balance < c["min_balance"]}
    if out["recharge"]:
        out["message"] = (f"Available balance ₹{balance:,.0f} is below ₹{c['min_balance']:,.0f}. "
                          "Add funds in the Angel One app to get trade suggestions sized to your balance.")
        return out
    risk_budget = balance * c["risk_pct"] / 100
    alloc = balance * c["max_alloc_pct"] / 100
    lev = max(1.0, c["intraday_leverage"])
    now = MARKET.clock()
    sod = A.ist_seconds_of_day(now)
    out["risk_budget"] = round(risk_budget, 2)
    out["alloc_cap"] = round(alloc, 2)

    # ---- intraday + option candidates: strongest names on each board
    cand = []
    for g in ("nifty50", "sensex", "watchlist"):
        b = MARKET.board(g, watch if g == "watchlist" else None)
        cand += [r["sym"] for r in b["bulls"][:10] + b["bears"][:10]]
    cand = list(dict.fromkeys(["NIFTY", "SENSEX"] + cand))  # index options are the most affordable lots
    p_i, src_i = _p(engine, "intraday", c)
    for sym in cand:
        st = MARKET.stocks.get(sym) or MARKET.indices.get(sym)
        if not st:
            continue
        try:
            feed.ensure_history(st)
        except Exception:
            continue
        sig = engine.signals_for(st, 15)
        s = sig["intraday"]
        if not st.is_index and s["action"] in ("BUY", "SELL", "WAIT") and s.get("entry") and s.get("sl"):
            side = "BUY" if s["t1"] > s["entry"] else "SELL"
            rps = abs(s["entry"] - s["sl"])
            q = min(math.floor(risk_budget / rps) if rps else 0, math.floor(alloc / (s["entry"] / lev)))
            if q >= 1:
                out["ideas"]["intraday"].append(_idea(st, "intraday", s, side, s["entry"], s["sl"], s["t1"], s["t2"], q,
                                                      "intraday", q * s["entry"] / lev, p_i, src_i,
                                                      {"margin_note": f"intraday margin ≈ {100 / lev:.0f}% of value"}))
            else:
                out["skipped"].append(f"{sym} intraday: 1 share risks more than your per-trade risk")
        o = sig["option"]
        if o.get("option") and (o["action"].startswith("BUY") or o["action"] == "WAIT"):
            op = o["option"]
            lot = max(1, int(op["lot"] or 1))
            rpl = (op["entry"] - op["sl"]) * lot
            cost_lot = op["entry"] * lot
            lots = min(math.floor(risk_budget / rpl) if rpl > 0 else 0, math.floor(alloc / cost_lot) if cost_lot else 0)
            if lots >= 1:
                q = lots * lot
                idea = _idea(st, "option", o, "BUY", op["entry"], op["sl"], op["t1"], op["t2"], q, "option", q * op["entry"],
                             p_i, src_i, {"contract": op["symbol"], "lots": lots, "lot": lot, "estimated": op["estimated"],
                                          "stock_entry": o["underlying"]["entry"], "stock_sl": o["underlying"]["sl"]})
                if sod >= 14 * 3600:
                    idea["warnings"].append("After 2 PM: time decay works against option buyers")
                out["ideas"]["option"].append(idea)
            else:
                need = max(rpl, 0)
                out["skipped"].append(f"{op['symbol']}: 1 lot costs ₹{cost_lot:,.0f} and risks ₹{need:,.0f}; too big for your balance/risk")

    # ---- long-term candidates: every tracked stock, daily rules
    p_l, src_l = _p(engine, "long", c)
    with LOCK:
        stocks = list(MARKET.stocks.values())
    for st in stocks:
        if st.ltp <= 0 or len(st.daily) < 60:
            continue
        s = S.long_term(st, now)
        if s["action"] != "BUY" and not (s["action"] == "WAIT" and s.get("entry") and s.get("t1", 0) > s.get("entry", 0)
                                          and abs(st.ltp - s["entry"]) / st.ltp < 0.03):
            continue
        if not s.get("entry") or not s.get("sl") or s["t1"] <= s["entry"]:
            continue
        rps = s["entry"] - s["sl"]
        q = min(math.floor(risk_budget * 2 / rps) if rps > 0 else 0, math.floor(alloc / s["entry"]))  # long term: 2x risk budget, wider stops
        if q >= 1:
            out["ideas"]["long"].append(_idea(st, "long", s, "BUY", s["entry"], s["sl"], s["t1"], s["t2"], q, "delivery",
                                              q * s["entry"], p_l, src_l))

    for k in out["ideas"]:
        lst = [i for i in out["ideas"][k] if i["ev"] > 0]
        lst.sort(key=lambda i: (-i["ready"], -i["ev_per_risk"]))
        out["ideas"][k] = lst[: int(c["max_per_style"])]
    # ---- a set that fits together inside the balance
    allid = sorted([i for k in out["ideas"] for i in out["ideas"][k]], key=lambda i: -i["ev_per_risk"])
    used = risk = 0.0
    chosen = []
    for i in allid:
        if used + i["capital"] <= balance and risk + i["risk"] <= risk_budget * 4 + 1e-6 and len(chosen) < 4:
            used += i["capital"]
            risk += i["risk"]
            i["in_plan"] = True
            chosen.append(i)
    out["plan"] = {"count": len(chosen), "capital": round(used, 2), "risk": round(risk, 2),
                   "ev": round(sum(i["ev"] for i in chosen), 2),
                   "best_case": round(sum(i["profit_t1"] for i in chosen), 2),
                   "worst_case": round(-risk, 2)}
    out["skipped"] = out["skipped"][:8]
    _cache[uid] = (key, time.time(), out)
    return out
