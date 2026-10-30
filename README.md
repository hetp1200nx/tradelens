# TradeLens: your personal order-block & liquidity terminal

Live boards for **Sensex, Nifty 50 and your Volatile Watchlist** (starts with the 200 most volatile F&O stocks; add any NSE share), live candle charts with
order blocks and liquidity levels, buy/sell suggestions for **intraday, long term and options**,
a profit/loss calculator with full charges, your own trade journal with live P&L and exit alerts,
a backtest, and a scorecard that tracks how the signals really perform.

It only **reads** market data. It never places, changes or cancels orders. You trade in your own app as usual.

---

## 1. Try it now (demo mode, no account needed)

Needs Python 3.10+ (python.org → Download → tick "Add Python to PATH" while installing).

**Windows:** double-click `start.bat`. The first run installs everything (about a minute), then your browser opens http://localhost:8000.
**Mac/Linux:** run `bash start.sh`, then open http://localhost:8000.

Demo mode runs a simulated market (yellow **DEMO** badge at the top). Prices are fake; it's only for testing the screens.

---

## 2. Switch to live Angel One data (free)

1. **Get the API key.** Log in at https://smartapi.angelbroking.com → *Create an App* → choose **Trading APIs** (needed to read your balance, holdings and positions; TradeLens still never places orders) → any name, redirect URL `http://127.0.0.1` → copy the **API Key**.
2. **Get the TOTP secret.** Go to https://smartapi.angelbroking.com/enable-totp → log in with client ID + PIN + OTP. It shows a QR code **and a text key**. Copy the text key (that's your `ANGEL_TOTP_SECRET`). You can also scan the QR into Google Authenticator.
3. Open the `.env` file (Notepad is fine) and fill in:
   ```
   DATA_MODE=angel
   ANGEL_API_KEY=your api key
   ANGEL_CLIENT_CODE=your Angel One client ID
   ANGEL_PIN=your 4-digit login PIN
   ANGEL_TOTP_SECRET=the text key from step 2
   ```
   (Or skip `.env` and enter these when you sign up in the app; see section 5a.)
4. Start the app again. The first start of the day takes **about 2 minutes** (it downloads one year of daily history for ~230 stocks to rank volatility). Later starts that day are instant (cached in `data/cache`).

Login happens automatically every day with the TOTP secret. No daily manual step.

> Keep `.env` private: it holds your account login. Never share it or upload it anywhere.

---

## 3. Save your trades in Supabase (recommended)

Without Supabase, trades are saved in `data/trades.json` on the machine running the app (fine for a laptop).
For phone + laptop and cloud hosting, use Supabase (free tier is plenty):

1. https://supabase.com → New project (region: Mumbai).
2. SQL Editor → paste everything in `supabase.sql` → Run.
3. Project Settings → API → copy the **Project URL** and the **service_role** secret key into `.env`:
   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_KEY=the service_role key
   ```
The key stays on the server only; the web page never sees it.

---

## 4. Use it on your phone

- **Same Wi-Fi:** run the app on your laptop, find the laptop's IP (`ipconfig` on Windows, e.g. 192.168.1.5), and open `http://192.168.1.5:8000` on the phone.
- **From anywhere (free):** install Cloudflare Tunnel (`cloudflared`) on the laptop and run
  `cloudflared tunnel --url http://localhost:8000`. It prints an `https://….trycloudflare.com` link you can open on your phone. Everyone must sign in.
- **Always on, laptop off:** run it on a small cloud server (e.g. Oracle Cloud "Always Free" VM, Mumbai region). Copy the folder, fill `.env`, run `bash start.sh`. Free web hosts that sleep when idle (like Render free) are **not** suitable because the live feed must stay connected.

Tap **🔔 Alerts off** to turn on phone/browser notifications.

### Telegram alerts (optional)
Create a bot with @BotFather → copy the token into `TELEGRAM_BOT_TOKEN`. Send your bot any message, then open
`https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": …}` into `TELEGRAM_CHAT_ID`.

---

## 5. What each screen does

**Boards:** pick Sensex / Nifty 50 / Top 200. Every stock is scored every second:
- **Strength (0–100):** today's move vs the stock's normal daily range (ATR), volume vs a normal day at this time, buyer/seller quantity in the order book, and where price sits in the day's range. Choppy stocks score 0.
- **Vol ×:** today's volume compared with a normal day at the same time.
- **Buy / Sell bar:** total pending buy vs sell quantity.
- **OI view (F&O):** Long build-up, Short build-up, Short covering, Long unwinding.

**Stock page (tap any stock):**
- Live chart (1m to weekly) with EMA 20/50, VWAP, order-block zones, liquidity levels and your own trade lines.
- **Suggestion** tab per style. Each gives BUY / SELL / WAIT / AVOID, an entry zone, stop-loss, 2 targets, risk-reward, the reasons, and the warnings.
  - *Intraday (5-min):* trend from VWAP + EMA 20/50 + order-book pressure + OI; entry at the nearest fresh order block; stop just beyond it; targets at untaken liquidity / previous-day high-low. Warns in the first 15 min, after 2:30/3:00 PM, in choppy or low-volume stocks, when price is stretched, near circuits, or when reward is under 1.2× risk.
  - *Long term (daily):* 50/200-day trend, daily order blocks, RSI. "SELL" here means exit or avoid holding.
  - *Option:* follows the intraday signal; suggests a 1-strike in-the-money CE/PE, premium entry/SL/targets and risk per lot, with time-decay and expiry warnings. Live mode uses the real option price; demo mode estimates it.
- **Live quote:** OHLC, volume, VWAP, circuits, 52-week range, OI, buyer vs seller quantity and 5-level market depth.
- **P&L calculator:** net profit/loss at SL, T1 and T2 **after brokerage, STT, exchange fees, SEBI fee, stamp duty, GST and DP charges**, plus the move needed just to cover charges. "Add to my trades" puts it straight into your journal.
- **Backtest:** replays the intraday order-block rule on ~60 days of 5-minute history and shows win rate, average R (after costs), profit factor and the worst losing streak.

**My Trades:** add trades you took in your own trading app. Each open trade shows live price, net P&L after charges,
room to stop-loss and plain advice: *Hold* / *Target 1 reached: book part, move SL to entry* / *Target 2: exit* / *Stop-loss hit: exit* /
*Signal turned against you* / *Market closes soon*. Each alert pops up once (toast + sound + notification + Telegram).

**Scorecard:** every 30 seconds the app records BUY/SELL signals from the strongest stocks and later marks them win/loss by
whether target 1 or the stop-loss came first. Use this (and backtests) to decide how much to trust the signals.

---

## 5a. Sign in, accounts and admin (version 3)

TradeLens now has user accounts. Everyone signs in, and each user has their own watchlist, trades, price alerts,
Trade Planner settings and Angel One account.

- **Sign up:** first name, last name, username, email, mobile, Angel One API (API key, client ID, login PIN, TOTP secret; optional, can be added later in Profile), password (8+ characters with an uppercase letter, a lowercase letter, a number and a symbol), then a 4-digit passcode.
- **Sign in:** username + password. Tick **Remember me** and the next time you open TradeLens on that device you just enter your **4-digit passcode** (5 wrong tries → password needed again). Sign-in sessions last 12 hours; remembered devices 60 days.
- **Profile** (tap your name, top right): edit details, add/replace/remove your Angel API, change password (signs out other devices), change passcode, sign out, lock.
- **Your Angel API** powers your own balance, portfolio, positions and orders. Live prices are shared by everyone and come from one API the admin picks (Admin → user → **Use for live prices**); the first user who adds a working API is picked automatically and TradeLens restarts itself into live mode.
- **Admin dashboard** (sign in with the admin username/password from `.env`): all users with email, mobile, joined/last login, Angel API status (client ID + masked key), balance, portfolio, P&L, trade counts; tap a user for their positions, holdings, orders, TradeLens journal, watchlist and price alerts. Actions: reset password (shows a one-time temporary password), disable/enable, delete user, use their API for live prices, and download every user's trades as CSV.

**Security:** passwords and passcodes are stored only as one-way scrypt hashes, so nobody, admin included, can read them; admin resets them instead. Angel API key, PIN and TOTP secret are encrypted with `SECRET_KEY` (created automatically in `.env`; back it up, because losing it means users must re-enter their Angel details). The admin login is set by `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env`; change the password there if the file is ever shared. If you use Supabase, run the updated `supabase.sql` (it adds the `users` table).

## 5c. Views, theme and bulk import (version 3)

- **Grid view:** on Boards, switch **☰ List / ▦ Grid**. Every share in Sensex, Nifty 50 or your Volatile Watchlist becomes a live card: sector, sparkline, price and change, rank (#1 bullish…), conviction (strength + dots), VWAP, order-block zone, R1/R2, S1/S2, risk-reward, signal, and a mini intraday chart with order-block zones, support (S1–S4) and resistance (R1–R4) lines, VWAP and the live price. Filter by text, All / Bullish / Bearish / Signals, and sort by strength, % change, volume or name. Only cards on screen are drawn, so 500+ shares stay smooth. Tap a card to open the share.
- **Market Flow (tree view):** a new tab showing the whole list at once. Sectors are ranked on the left; every share's move since the open is drawn as a line (green above 0, red below), fanning out live; the right edge splits into bullish vs bearish counts; and the strongest buying and selling shares are shown as cards with their last 2 hours of 5-minute volume (green = buying candles, red = selling). Hover a line to see the share; tap a sector to highlight it; tap a line or card to open the share. Leading and lagging sectors are shown at the top. Refreshes every 5 seconds.
- **Light / dark mode:** the ☾ / ☀ button in the top bar. Your choice is remembered on each device (first visit follows the phone/computer setting). Charts switch colours too.
- **Import Excel / CSV:** in **+ Add share**, tap **Import Excel / CSV** and pick a `.xlsx` or `.csv` file. Symbols can be in the first column or in a column named Symbol / Stock / Share / Scrip / Name. Formats like `RELIANCE-EQ`, `NSE:IRFC`, `hdfcbank.ns` and `Tata Steel` are understood. You get a report: added, already in the list, and not found. **Template** downloads a sample file. (Old `.xls` files: save as `.xlsx` first.)

## 5b. New in version 2

**Volatile Watchlist** (third board): starts with the 200 most volatile F&O stocks. Tap **+ Add share**, type a few letters, and pick from the live dropdown (every NSE share is searchable). Remove with ✕ on its row. The list is saved (Supabase or local file) and can hold 1,500 shares; the search box filters it instantly. Live data covers up to ~2,800 instruments (3 Angel connections).

**Search any share** (top bar): opens any listed share, even if it isn't in a list. On a stock page, **☆ Watch** adds it to the watchlist and **🔔 Price alert** sets an alert.

**Angel Account** (read-only): available balance, margin used, **active trades (positions) with live P&L**, **portfolio (holdings) with live P&L and today's change**, and today's orders. Refreshes every 5 seconds; prices tick live. Set a **daily loss limit** to get a "stop trading for today" warning. The wallet balance also shows in the top bar.

**Trade Planner**: uses your Angel available balance (or any amount you type) and suggests sized trades for **intraday, options and long term**:
- Quantity is set so the loss at stop-loss stays within *max loss per trade* (default 1% of balance) and capital/margin within *max capital per trade* (default 40%).
- Each idea shows entry, SL, targets, margin/capital, loss at SL, profit at T1/T2 after charges, and **expected P&L** = win-chance × profit − loss-chance × loss.
- Win-chance comes from your Scorecard once it has 20+ results; before that a cautious 42% (intraday/options) / 45% (long term) is used, and each card says which.
- ★ marks a set of trades that fits your balance together (total risk ≤ 4% of balance).
- Below ₹2,000 it shows **Recharge wallet** instead of trades.
- Stock options usually need ₹10,000–35,000 per lot; with a small balance the planner says so instead of suggesting oversized trades.

**Radar**: live feed of volume spikes (2.5× normal), new day highs/lows with volume, strength crossing 70, and trends starting after choppy trading. Plus **price alerts** you set (toast, sound, phone notification, Telegram).

**Market mood** gauge on Boards, **Export to Excel (CSV)** in My Trades, and the app is **installable**: on your phone open it in Chrome/Safari → "Add to Home screen".

## 6. Important to know

- These are **rules, not predictions**. No algorithm wins every trade. Judge it by the Scorecard over several weeks, and by *average R after costs*, not just win rate.
- No API in India shows *who* is buying (FII/operator/retail); only how much is being bought and sold.
- For personal use this is fine. Selling or sharing these signals with others needs SEBI registration.
- **Charges** are in `backend/charges.py` (Angel One rates + Budget 2026 STT on F&O). Check your contract note once and edit if anything differs.
- **Index lists** (Nifty 50, Sensex 30) are in `backend/universe.py`. NSE/BSE rebalance them a few times a year; edit when they change. The F&O list and the top-200 volatility ranking update automatically in live mode.
- **First live day:** the Angel One connection code follows their published SmartAPI format but couldn't be tested against your account from here. If the status pill shows an error, it shows the exact message; send it to me and I'll fix it.

## 7. Files
```
run.py                  start the server
backend/feeds/angel.py  Angel One login, history, live WebSocket feed (read-only)
backend/feeds/demo.py   simulated market for testing
backend/analytics.py    indicators, order blocks, liquidity, VWAP
backend/signals.py      intraday / long-term / option suggestion rules
backend/market.py       live quotes, candles, board strength scores
backend/engine.py       trade tracking, alerts, scorecard, backtest
backend/charges.py      brokerage and tax calculation
backend/planner.py      Trade Planner (balance-based sizing + expected P&L)
backend/account.py      your Angel holdings / positions / orders / funds (read-only)
backend/watch.py        Volatile Watchlist storage
backend/storage.py      Supabase or local-file storage
frontend/               the web app (works on phone and desktop)
```
