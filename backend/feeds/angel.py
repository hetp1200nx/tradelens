"""Live market data + your account from Angel One SmartAPI. READ-ONLY: this file never places,
modifies or cancels orders. It only calls login, instrument list, candles, quotes, the live price
WebSocket, holdings, positions, order book and funds (RMS limit).

Needs: pip install smartapi-python pyotp logzero websocket-client requests
Login is automatic every morning using your TOTP secret (no daily manual step).
"""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from .. import analytics as A
from .. import config as C
from ..market import LOCK, Market, Stock
from ..universe import INDICES, NIFTY50, SENSEX30

IST_TZ = timezone(timedelta(hours=5, minutes=30))
SCRIP_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE = C.DATA_DIR / "cache"
CACHE.mkdir(exist_ok=True)
EXCH_TYPE = {"NSE": 1, "NFO": 2, "BSE": 3, "BFO": 4, "MCX": 5}
EXCH_NAME = {v: k for k, v in EXCH_TYPE.items()}
TOKENS_PER_CONN = 950      # Angel allows ~1000 tokens per WebSocket session
MAX_CONNS = 3              # and up to 3 sessions per client


def _today_str():
    return datetime.now(IST_TZ).strftime("%Y%m%d")


def _parse_ts(s: str) -> int:
    return int(datetime.fromisoformat(s).timestamp())


def _expiry_date(s: str):
    try:
        return datetime.strptime(s, "%d%b%Y").date()
    except Exception:
        return None


class _Conn:
    def __init__(self):
        self.tokens: set[tuple[int, str]] = set()
        self.sws = None
        self.open = False


class AngelFeed:
    name = "angel"

    def __init__(self, market: Market, creds: dict):
        """creds: {api_key, client_code, pin, totp_secret} of the account that powers the shared price feed."""
        self.creds = creds
        self.m = market
        self.m.mode = "live"
        self.api = None
        self.jwt = self.feed_token = None
        self.by_token: dict[tuple[int, str], tuple[Stock | None, str]] = {}
        self.eq: dict[str, dict] = {}
        self.futs: dict[str, dict] = {}
        self.options: dict[str, list[dict]] = {}
        self.hist_lock = threading.Lock()
        self.api_lock = threading.Lock()
        self._optq: dict[str, tuple[float, dict]] = {}
        self.conns: list[_Conn] = []
        self.conn_lock = threading.Lock()
        self.acct_ltp: dict[tuple[int, str], float] = {}
        self.acct: dict = {"funds": {}, "holdings": [], "positions": [], "orders": [], "updated": None, "source": "Angel One"}
        self.last_tick = 0.0
        self.error = ""

    # ------------------------------------------------------------ login
    def login(self):
        import pyotp
        from SmartApi import SmartConnect
        c = self.creds or {}
        if not all(c.get(k) for k in ("api_key", "client_code", "pin", "totp_secret")):
            raise RuntimeError("No Angel One API for live prices: admin must choose a user's API (Admin → Users → Use for live prices)")
        api = SmartConnect(api_key=c["api_key"])
        data = api.generateSession(c["client_code"], c["pin"], pyotp.TOTP(c["totp_secret"]).now())
        if not data or not data.get("status"):
            raise RuntimeError(f"Angel One login failed: {data.get('message') if data else 'no response'}")
        self.api = api
        self.jwt = data["data"]["jwtToken"]
        self.feed_token = api.getfeedToken()
        self.login_day = _today_str()

    # ------------------------------------------------------------ instruments
    @staticmethod
    def _iter_json_array(path):
        """Read a big JSON array one object at a time (keeps memory low on small servers)."""
        dec = json.JSONDecoder()
        buf, started = "", False
        with open(path, encoding="utf-8") as f:
            while True:
                chunk = f.read(1 << 20)
                buf += chunk
                if not started:
                    i = buf.find("[")
                    if i < 0:
                        if not chunk:
                            return
                        continue
                    buf, started = buf[i + 1:], True
                pos, n = 0, len(buf)
                while True:
                    while pos < n and buf[pos] in " \r\n\t,":
                        pos += 1
                    if pos >= n or buf[pos] == "]":
                        break
                    try:
                        obj, end = dec.raw_decode(buf, pos)
                    except ValueError:
                        break
                    yield obj
                    pos = end
                buf = buf[pos:]
                if not chunk:
                    return

    def _scrip_master(self) -> list[dict]:
        """Instrument list, trimmed to what TradeLens uses (NSE shares, stock futures, live options)."""
        f = CACHE / f"scripmaster_slim_{_today_str()}.json"
        if f.exists():
            return json.loads(f.read_text())
        for old in list(CACHE.glob("scripmaster_*.json")) + list(CACHE.glob("scripmaster_*.raw")):
            old.unlink(missing_ok=True)
        raw = CACHE / f"scripmaster_{_today_str()}.raw"
        with requests.get(SCRIP_URL, timeout=120, stream=True) as r:
            r.raise_for_status()
            with open(raw, "wb") as out:
                for part in r.iter_content(1 << 20):
                    out.write(part)
        today = datetime.now(IST_TZ).date()
        keep = ("token", "symbol", "name", "expiry", "strike", "lotsize", "instrumenttype", "exch_seg", "tick_size")
        rows = []
        for r in self._iter_json_array(raw):
            seg, it = r.get("exch_seg"), r.get("instrumenttype")
            if seg == "NSE" and str(r.get("symbol", "")).endswith("-EQ"):
                pass
            elif (it == "FUTSTK" and seg == "NFO") or (it in ("OPTSTK", "OPTIDX") and seg in ("NFO", "BFO")):
                ex = _expiry_date(r.get("expiry", ""))
                if not ex or ex < today:
                    continue
            else:
                continue
            rows.append({k: r[k] for k in keep if k in r})
        raw.unlink(missing_ok=True)
        f.write_text(json.dumps(rows))
        print(f"[TradeLens] instruments loaded: {len(rows)}", flush=True)
        return rows

    def _build_universe(self):
        sm = self._scrip_master()
        today = datetime.now(IST_TZ).date()
        opts = {}
        for r in sm:
            seg, it, nm = r.get("exch_seg"), r.get("instrumenttype"), r.get("name")
            if seg == "NSE" and r.get("symbol", "").endswith("-EQ"):
                self.eq[nm] = r
            elif it == "FUTSTK" and seg == "NFO":
                ex = _expiry_date(r.get("expiry", ""))
                if ex and ex >= today and (nm not in self.futs or ex < self.futs[nm]["_ex"]):
                    r["_ex"] = ex
                    self.futs[nm] = r
            elif it in ("OPTSTK", "OPTIDX") and seg in ("NFO", "BFO"):
                ex = _expiry_date(r.get("expiry", ""))
                if ex and ex >= today:
                    r["_ex"] = ex
                    opts.setdefault(nm, []).append(r)
        for nm, lst in opts.items():
            exps = sorted({x["_ex"] for x in lst})[:2]
            self.options[nm] = [x for x in lst if x["_ex"] in exps]
        # searchable catalog: every NSE share
        for nm, r in self.eq.items():
            self.m.catalog[nm] = {"name": nm, "exch": "NSE", "token": r["token"], "fno": nm in self.futs}
        for key, (nm, ex, tok, et) in INDICES.items():
            self.m.catalog[key] = {"name": nm, "exch": ex, "token": tok, "fno": True}
            st = Stock(key, nm, ex, tok, is_index=True)
            st.strike_step = self._strike_step(key) or (50 if key == "NIFTY" else 100)
            lst = self.options.get(key) or []
            st.lot = int(float(lst[0].get("lotsize") or 1)) if lst else 1
            st.is_fno = bool(lst)
            self.m.indices[key] = st
            self.by_token[(et, tok)] = (st, "index")
        # stocks needed at start: Nifty 50, Sensex and every F&O stock (to rank volatility)
        for nm in dict.fromkeys(NIFTY50 + SENSEX30 + sorted(self.futs)):
            self._make_stock(nm)
        self.m.groups["nifty50"] = [s for s in NIFTY50 if s in self.m.stocks]
        self.m.groups["sensex"] = [s for s in SENSEX30 if s in self.m.stocks]
        for s in self.m.groups["nifty50"]: self.m.stocks[s].groups.add("nifty50")
        for s in self.m.groups["sensex"]: self.m.stocks[s].groups.add("sensex")

    def _make_stock(self, nm) -> Stock | None:
        r = self.eq.get(nm)
        if not r:
            return None
        st = Stock(nm, nm, "NSE", r["token"])
        st.is_fno = nm in self.futs
        if nm in self.futs:
            st.fut_token = self.futs[nm]["token"]
            st.lot = int(float(self.futs[nm].get("lotsize") or 1))
        st.strike_step = self._strike_step(nm)
        with LOCK:
            self.m.add(st)
            self.by_token[(1, st.token)] = (st, "eq")
            if st.fut_token:
                self.by_token[(2, st.fut_token)] = (st, "fut")
        return st

    def _strike_step(self, nm):
        lst = self.options.get(nm)
        if not lst:
            return None
        ex = min(x["_ex"] for x in lst)
        strikes = sorted({float(x["strike"]) / 100 for x in lst if x["_ex"] == ex})
        diffs = [b - a for a, b in zip(strikes, strikes[1:]) if b - a > 0]
        return min(diffs) if diffs else None

    # ------------------------------------------------------------ add any share (watchlist / search)
    def track(self, sym: str):
        """Make sure a share has live data. Used when you add a share to the watchlist or open any share."""
        sym = sym.upper()
        st = self.m.stocks.get(sym) or self.m.indices.get(sym)
        if st:
            return st
        st = self._make_stock(sym)
        if not st:
            return None
        st.daily = [c for c in self._candles("NSE", st.token, "ONE_DAY", 400) if c["t"] < A.ist_day_start(int(time.time()))]
        st.refresh_daily_stats()
        if self.m.ready:  # at startup, quotes and subscriptions are done in bulk afterwards
            self._seed({"NSE": [st.token]} if not st.fut_token else {"NSE": [st.token], "NFO": [st.fut_token]})
            self.subscribe([(1, st.token)] + ([(2, st.fut_token)] if st.fut_token else []))
        return st

    # ------------------------------------------------------------ history
    def _candles(self, exch, token, interval, days, retries=3):
        to = datetime.now(IST_TZ)
        fr = to - timedelta(days=days)
        params = {"exchange": exch, "symboltoken": token, "interval": interval,
                  "fromdate": fr.strftime("%Y-%m-%d 09:15"), "todate": to.strftime("%Y-%m-%d %H:%M")}
        for attempt in range(retries):
            with self.hist_lock:
                time.sleep(0.36)  # stay under 3 requests/second
                try:
                    res = self.api.getCandleData(params)
                except Exception as e:
                    res = {"status": False, "message": str(e)}
            if res and res.get("status") and res.get("data") is not None:
                return [{"t": _parse_ts(r[0]), "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in res["data"]]
            time.sleep(1.0 + attempt)
        return []

    def _load_daily(self):
        f = CACHE / f"daily_{_today_str()}.json"
        cache = json.loads(f.read_text()) if f.exists() else {}
        today0 = A.ist_day_start(int(time.time()))
        todo = list(self.m.stocks.values()) + list(self.m.indices.values())
        for i, st in enumerate(todo):
            if st.sym not in cache:
                exch = st.exch if st.exch in ("NSE", "BSE") else "NSE"
                cache[st.sym] = self._candles(exch, st.token, "ONE_DAY", 400)
                if i % 20 == 0:
                    f.write_text(json.dumps(cache))
                    self.m.status = f"loading history {i}/{len(todo)}"
            with LOCK:
                st.daily = [c for c in cache[st.sym] if c["t"] < today0]
                st.refresh_daily_stats()
        f.write_text(json.dumps(cache))
        for old in CACHE.glob("daily_*.json"):
            if old.name != f.name:
                old.unlink(missing_ok=True)

    def ensure_history(self, st: Stock):
        """Load the last ~5 trading days of 1-minute candles for charts (once per stock)."""
        if st.hist_loaded or not self.api:
            return
        exch = st.exch if st.exch in ("NSE", "BSE") else "NSE"
        hist = self._candles(exch, st.token, "ONE_MINUTE", 7)
        with LOCK:
            first_live = st.m1[0]["t"] if st.m1 else 10 ** 12
            st.m1 = [c for c in hist if c["t"] < first_live] + st.m1
            st.hist_loaded = True

    def history_5m(self, st: Stock, days: int = 60):
        exch = st.exch if st.exch in ("NSE", "BSE") else "NSE"
        return self._candles(exch, st.token, "FIVE_MINUTE", min(days, 95))

    # ------------------------------------------------------------ quotes
    def _seed(self, groups: dict[str, list[str]]):
        for ex, toks in groups.items():
            for i in range(0, len(toks), 50):
                try:
                    with self.hist_lock:
                        time.sleep(0.4)
                        res = self.api.getMarketData("FULL", {ex: toks[i:i + 50]})
                    for q in (res or {}).get("data", {}).get("fetched", []) or []:
                        self._apply_full(EXCH_TYPE[ex], str(q.get("symbolToken")), q)
                except Exception as e:
                    self.error = f"quote seed: {e}"

    def _seed_quotes(self):
        """Fill quotes once at startup (also shows last prices when the market is closed)."""
        groups = {"NSE": [], "NFO": [], "BSE": []}
        for (et, tok), (st, role) in self.by_token.items():
            ex = EXCH_NAME.get(et)
            if ex in groups and st is not None:
                groups[ex].append(tok)
        self._seed(groups)
        self.m.compute_all()

    def _apply_full(self, et, tok, q):
        hit = self.by_token.get((et, tok))
        if not hit or hit[0] is None:
            return
        st, role = hit
        with LOCK:
            if role == "fut":
                st.oi = float(q.get("opnInterest") or 0)
                return
            st.ltp = float(q.get("ltp") or 0)
            st.open = float(q.get("open") or 0)
            st.high = float(q.get("high") or 0)
            st.low = float(q.get("low") or 0)
            st.prev_close = float(q.get("close") or st.prev_close)
            st.volume = float(q.get("tradeVolume") or 0)
            st.avg_price = float(q.get("avgPrice") or 0)
            st.buy_qty = float(q.get("totBuyQuan") or 0)
            st.sell_qty = float(q.get("totSellQuan") or 0)
            st.uc = float(q.get("upperCircuit") or 0)
            st.lc = float(q.get("lowerCircuit") or 0)
            st.w52h = float(q.get("52WeekHigh") or 0)
            st.w52l = float(q.get("52WeekLow") or 0)
            dp = q.get("depth") or {}
            st.bids = [{"price": d.get("price"), "qty": d.get("quantity"), "orders": d.get("orders")} for d in dp.get("buy", [])]
            st.asks = [{"price": d.get("price"), "qty": d.get("quantity"), "orders": d.get("orders")} for d in dp.get("sell", [])]

    def _on_data(self, wsapp, msg):
        try:
            if not isinstance(msg, dict):
                return
            et = int(msg.get("exchange_type", 0))
            tok = str(msg.get("token", "")).strip("\x00 ")
            hit = self.by_token.get((et, tok))
            if not hit:
                return
            st, role = hit
            div = 100.0
            self.last_tick = time.time()
            if role == "acct":  # a holding/position we only need the price of
                self.acct_ltp[(et, tok)] = float(msg.get("last_traded_price", 0)) / div
                return
            ts = int((msg.get("exchange_timestamp") or time.time() * 1000) / 1000)
            with LOCK:
                if role == "fut":
                    if msg.get("open_interest") is not None:
                        st.oi = float(msg["open_interest"])
                    v = msg.get("open_interest_change_percentage")
                    try:
                        v = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        v = None
                    if v is not None and math.isfinite(v) and abs(v) <= 500:
                        st.oi_chg_pct, st.oi_chg_ok = v, True
                    elif v is not None:
                        # Angel sometimes sends a corrupt value here; show "–" instead of nonsense
                        st.oi_chg_pct, st.oi_chg_ok = 0.0, False
                    return
                ltp = float(msg.get("last_traded_price", 0)) / div
                if msg.get("open_price_of_the_day"):
                    st.open = float(msg["open_price_of_the_day"]) / div
                    st.high = float(msg.get("high_price_of_the_day", 0)) / div or st.high
                    st.low = float(msg.get("low_price_of_the_day", 0)) / div or st.low
                if msg.get("closed_price"):
                    st.prev_close = float(msg["closed_price"]) / div
                vol = msg.get("volume_trade_for_the_day")
                st.on_tick(ltp, float(vol) if vol is not None and role == "eq" else None, ts)
                if role == "eq":
                    st.avg_price = float(msg.get("average_traded_price", 0)) / div or st.avg_price
                    st.buy_qty = float(msg.get("total_buy_quantity", st.buy_qty) or 0)
                    st.sell_qty = float(msg.get("total_sell_quantity", st.sell_qty) or 0)
                    if msg.get("upper_circuit_limit"):
                        st.uc = float(msg["upper_circuit_limit"]) / div
                        st.lc = float(msg.get("lower_circuit_limit", 0)) / div
                    if msg.get("52_week_high_price"):
                        st.w52h = float(msg["52_week_high_price"]) / div
                        st.w52l = float(msg.get("52_week_low_price", 0)) / div
                    if msg.get("best_5_buy_data"):
                        st.bids = [{"price": float(d.get("price", 0)) / div, "qty": d.get("quantity"), "orders": d.get("no of orders")} for d in msg["best_5_buy_data"]]
                        st.asks = [{"price": float(d.get("price", 0)) / div, "qty": d.get("quantity"), "orders": d.get("no of orders")} for d in msg.get("best_5_sell_data", [])]
        except Exception as e:
            self.error = f"tick: {e}"

    # ------------------------------------------------------------ WebSocket connections (up to 3 x ~950 tokens)
    @staticmethod
    def _token_list(pairs):
        lists: dict[int, list[str]] = {}
        for et, tok in pairs:
            lists.setdefault(et, []).append(tok)
        return [{"exchangeType": et, "tokens": toks} for et, toks in lists.items()]

    def subscribe(self, pairs: list[tuple[int, str]]):
        """Add tokens to the live feed, opening another connection when one is full."""
        pairs = [p for p in pairs if not any(p in c.tokens for c in self.conns)]
        if not pairs:
            return True
        with self.conn_lock:
            conn = next((c for c in self.conns if len(c.tokens) + len(pairs) <= TOKENS_PER_CONN), None)
            if conn is None:
                if len(self.conns) >= MAX_CONNS:
                    self.error = "Live feed limit reached (about 2,800 instruments). Remove some watchlist shares."
                    return False
                conn = _Conn()
                self.conns.append(conn)
                conn.tokens.update(pairs)
                threading.Thread(target=self._ws_loop, args=(conn,), daemon=True).start()
                return True
            conn.tokens.update(pairs)
        if conn.open and conn.sws:
            try:
                conn.sws.subscribe("tl-add", 3, self._token_list(pairs))
            except Exception as e:
                self.error = f"subscribe: {e}"
        return True

    def _ws_loop(self, conn: _Conn):
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        while True:
            try:
                if getattr(self, "login_day", None) != _today_str():
                    with self.api_lock:
                        if getattr(self, "login_day", None) != _today_str():
                            self.login()
                sws = SmartWebSocketV2(self.jwt, self.creds["api_key"], self.creds["client_code"], self.feed_token, max_retry_attempt=5)
                conn.sws = sws

                def on_open(wsapp, conn=conn, sws=sws):
                    conn.open = True
                    sws.subscribe("tradelens", 3, self._token_list(list(conn.tokens)))  # 3 = SnapQuote

                def on_close(*a, conn=conn):
                    conn.open = False

                sws.on_open = on_open
                sws.on_data = self._on_data
                sws.on_error = lambda *a: setattr(self, "error", f"ws error: {a[-1] if a else ''}")
                sws.on_close = on_close
                sws.connect()  # blocks until the connection closes
            except Exception as e:
                self.error = f"ws: {e}"
            conn.open = False
            time.sleep(5)

    def _status_loop(self):
        while True:
            sod = A.ist_seconds_of_day(int(time.time()))
            wd = datetime.now(IST_TZ).weekday()
            if self.m.ready:
                if wd < 5 and A.SESSION_OPEN <= sod <= A.SESSION_CLOSE:
                    self.m.status = "live" if time.time() - self.last_tick < 15 else "connecting…"
                else:
                    self.m.status = "market closed (last prices)"
            self.m.compute_all()
            time.sleep(1)

    # ------------------------------------------------------------ live prices for users' holdings / positions
    def watch_tokens(self, pairs):
        """pairs: [(exchange name, token)] from users' portfolios. Adds them to the live feed if not tracked."""
        new = []
        for exch, tok in pairs:
            et = EXCH_TYPE.get(exch)
            if et and tok and (et, tok) not in self.by_token:
                self.by_token[(et, tok)] = (None, "acct")
                new.append((et, tok))
        if new and self.m.ready:
            self.subscribe(new)

    def ltp_for(self, exch, token, sym):
        et = EXCH_TYPE.get(exch)
        hit = self.by_token.get((et, token)) if et else None
        if hit and hit[0] is not None and hit[0].ltp:
            return hit[0].ltp
        if et and (et, token) in self.acct_ltp:
            return self.acct_ltp[(et, token)]
        st = self.m.stocks.get(sym or "")
        return st.ltp if st and st.ltp else None

    # ------------------------------------------------------------ options
    def option_quote(self, st: Stock, strike: float, typ: str):
        lst = self.options.get(st.sym)
        if not lst:
            return None
        ex = min(x["_ex"] for x in lst)
        cand = [x for x in lst if x["_ex"] == ex and abs(float(x["strike"]) / 100 - strike) < 1e-6
                and x["symbol"].endswith(typ)]
        if not cand:
            return None
        r = cand[0]
        key = r["token"]
        hit = self._optq.get(key)
        if hit and time.time() - hit[0] < 3:
            return hit[1]
        try:
            with self.hist_lock:
                res = self.api.ltpData(r["exch_seg"], r["symbol"], r["token"])
            ltp = float(res["data"]["ltp"])
        except Exception:
            return None
        q = {"ltp": ltp, "symbol": r["symbol"], "lot": int(float(r.get("lotsize") or st.lot)),
             "expiry": r["expiry"], "days_to_expiry": (ex - datetime.now(IST_TZ).date()).days}
        self._optq[key] = (time.time(), q)
        return q

    # ------------------------------------------------------------ start
    def start(self):
        def boot():
            try:
                self.m.status = "logging in to Angel One…"
                self.login()
                self.m.status = "loading instruments…"
                self._build_universe()
                import gc; gc.collect()
                self._load_daily()
                from .. import watch
                ranked = sorted((s for s in self.m.stocks.values() if s.is_fno), key=lambda s: -(s.atr_pct or 0))
                watch.init(self, [s.sym for s in ranked[:C.TOP_VOLATILE_COUNT]])
                self.m.status = "loading quotes…"
                self._seed_quotes()
                self.m.ready = True
                pairs = list(self.by_token.keys())
                for i in range(0, len(pairs), TOKENS_PER_CONN):
                    self.subscribe(pairs[i:i + TOKENS_PER_CONN])
                threading.Thread(target=self._status_loop, daemon=True).start()
                print("[TradeLens] LIVE: Angel One prices streaming", flush=True)
            except Exception as e:
                self.error = str(e)
                self.m.status = f"ERROR: {e}"
                print(f"[TradeLens] Angel One feed error: {e}", flush=True)
        threading.Thread(target=boot, daemon=True).start()
