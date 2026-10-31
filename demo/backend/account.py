"""Your Angel One account, READ-ONLY: wallet balance, holdings (portfolio), positions (active trades), today's orders.
Raw broker responses are normalised here; live P&L is recalculated every second from the latest prices."""
from __future__ import annotations


def _f(x, d=0.0):
    try:
        if x in (None, ""):
            return d
        return float(x)
    except (TypeError, ValueError):
        return d


def norm_funds(r: dict | None) -> dict:
    r = r or {}
    avail = _f(r.get("availablecash"), _f(r.get("net")))
    return {
        "available": avail,                                # cash you can use
        "net": _f(r.get("net"), avail),                    # net margin available
        "intraday_payin": _f(r.get("availableintradaypayin")),
        "collateral": _f(r.get("collateral")),
        "used": _f(r.get("utiliseddebits")),
        "m2m_unrealised": _f(r.get("m2munrealized")),
        "m2m_realised": _f(r.get("m2mrealized")),
    }


def norm_holdings(rows: list | None) -> list[dict]:
    out = []
    for r in rows or []:
        qty = _f(r.get("quantity")) + _f(r.get("t1quantity"))
        if qty <= 0:
            continue
        sym = str(r.get("tradingsymbol", "")).replace("-EQ", "").replace("-BE", "")
        out.append({"sym": sym, "exch": r.get("exchange", "NSE"), "token": str(r.get("symboltoken", "")),
                    "qty": qty, "avg": _f(r.get("averageprice")), "ltp": _f(r.get("ltp")),
                    "close": _f(r.get("close")), "isin": r.get("isin", "")})
    return out


def norm_positions(rows: list | None) -> list[dict]:
    out = []
    for r in rows or []:
        it = str(r.get("instrumenttype", ""))
        kind = "OPT" if it.startswith("OPT") else "FUT" if it.startswith("FUT") else "EQ"
        out.append({
            "symbol": r.get("tradingsymbol", ""), "underlying": r.get("symbolname") or str(r.get("tradingsymbol", "")).replace("-EQ", ""),
            "exch": r.get("exchange", "NSE"), "token": str(r.get("symboltoken", "")), "kind": kind,
            "product": r.get("producttype", ""), "netqty": _f(r.get("netqty")),
            "buy_qty": _f(r.get("buyqty")) + _f(r.get("cfbuyqty")), "sell_qty": _f(r.get("sellqty")) + _f(r.get("cfsellqty")),
            "buy_value": _f(r.get("totalbuyvalue"), _f(r.get("buyamount")) + _f(r.get("cfbuyamount"))),
            "sell_value": _f(r.get("totalsellvalue"), _f(r.get("sellamount")) + _f(r.get("cfsellamount"))),
            "buy_avg": _f(r.get("totalbuyavgprice"), _f(r.get("buyavgprice"))),
            "sell_avg": _f(r.get("totalsellavgprice"), _f(r.get("sellavgprice"))),
            "avg": _f(r.get("avgnetprice"), _f(r.get("netprice"))),
            "multiplier": _f(r.get("multiplier"), 1.0) or 1.0,
            "ltp": _f(r.get("ltp")), "api_pnl": _f(r.get("pnl"), _f(r.get("unrealised")) + _f(r.get("realised"))),
            "strike": _f(r.get("strikeprice")), "opt_type": r.get("optiontype", ""), "expiry": r.get("expirydate", ""),
        })
    return out


def norm_orders(rows: list | None) -> list[dict]:
    out = []
    for r in rows or []:
        out.append({"id": r.get("orderid"), "symbol": r.get("tradingsymbol"), "side": r.get("transactiontype"),
                    "qty": _f(r.get("quantity")), "filled": _f(r.get("filledshares")), "price": _f(r.get("price")),
                    "avg": _f(r.get("averageprice")), "type": r.get("ordertype"), "product": r.get("producttype"),
                    "status": r.get("orderstatus") or r.get("status"), "time": r.get("updatetime") or r.get("exchtime"),
                    "text": r.get("text", "")})
    return out


def live_view(acc: dict, ltp_fn) -> dict:
    """Recalculate P&L with the newest price. ltp_fn(exch, token, sym) -> price or None."""
    hold, pos = [], []
    for h in acc.get("holdings", []):
        ltp = ltp_fn(h["exch"], h["token"], h["sym"]) or h["ltp"]
        inv = h["avg"] * h["qty"]
        val = ltp * h["qty"]
        pnl = val - inv
        day = (ltp - h["close"]) * h["qty"] if h["close"] else 0.0
        hold.append({**h, "ltp": round(ltp, 2), "invested": round(inv, 2), "value": round(val, 2), "pnl": round(pnl, 2),
                     "pnl_pct": round(pnl / inv * 100, 2) if inv else 0.0, "day_pnl": round(day, 2),
                     "day_pct": round((ltp - h["close"]) / h["close"] * 100, 2) if h["close"] else 0.0})
    for p in acc.get("positions", []):
        ltp = ltp_fn(p["exch"], p["token"], p["underlying"] if p["kind"] == "EQ" else None) or p["ltp"]
        if p["buy_value"] or p["sell_value"]:
            pnl = (p["sell_value"] - p["buy_value"]) + p["netqty"] * ltp * p["multiplier"]
        else:
            pnl = p["api_pnl"]
        pos.append({**p, "ltp": round(ltp, 2), "pnl": round(pnl, 2), "open": p["netqty"] != 0})
    inv = sum(h["invested"] for h in hold)
    val = sum(h["value"] for h in hold)
    return {
        "funds": acc.get("funds", {}), "holdings": sorted(hold, key=lambda h: -h["value"]),
        "positions": sorted(pos, key=lambda p: (not p["open"], p["symbol"])), "orders": acc.get("orders", []),
        "totals": {"invested": round(inv, 2), "value": round(val, 2), "pnl": round(val - inv, 2),
                   "pnl_pct": round((val - inv) / inv * 100, 2) if inv else 0.0,
                   "day_pnl": round(sum(h["day_pnl"] for h in hold), 2),
                   "positions_pnl": round(sum(p["pnl"] for p in pos), 2),
                   "open_positions": sum(1 for p in pos if p["open"])},
        "updated": acc.get("updated"), "error": acc.get("error", ""), "source": acc.get("source", ""),
    }
