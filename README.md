# Stock Analysis

A comprehensive stock research app built with Streamlit. Diagnose any ticker with 9 investor lenses (Buffett, Graham, Lynch, Fisher, and more), quality flags, reverse DCF, options P&L simulation, and paper trading.

**No API keys required** for data — everything runs on free sources (yfinance, Finviz, SEC EDGAR, FRED, Nasdaq).

![Aurora Glass Theme](https://img.shields.io/badge/theme-Aurora%20Glass-blueviolet)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![Streamlit 1.54+](https://img.shields.io/badge/streamlit-1.54+-red)

---

## Features

| Page | What it does |
|------|-------------|
| **Stock Pro** | Full diagnosis: 9 investor lenses, 5-year trends, quality flags (Piotroski/Altman/Beneish), reverse DCF, auto-generated bull/bear thesis |
| **Discover** | Screen the market across 10 investing styles with debiased sampling |
| **Compare** | Two tickers head-to-head across every metric and lens |
| **Macro Pro** | Live indices, macro regime tiles, 20 FRED indicators |
| **Options Lab** | Interactive Black-Scholes P&L simulator with real chain data |
| **Calendar** | Full-market earnings, economic events, IPOs by date range |
| **Insider Buys** | Market-wide SEC Form 4 purchases with cluster-buy detection |
| **Watchlist** | Track tickers with price since added and gain/loss |
| **Thesis Journal** | Bull/bear cases with stop/target alerts |
| **Paper Trading** | Simulated portfolios with live P&L (stocks + options) |
| **Backtest** | Forward-return tracking for your scorecards |
| **Glossary** | 71 investing terms in plain English |

## Quick start

### Option 1: Streamlit Community Cloud (easiest)

1. Fork this repo on GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Click "New app" and point it at your fork (`app.py`)
4. Done — you get a free public URL like `yourname-stock-analysis.streamlit.app`

### Option 2: Run locally

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/stock-analysis-public.git
cd stock-analysis-public

# Install dependencies
pip install -r requirements.txt

# Run
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

## Data sources

All free, no API keys required:

- **yfinance** — stock quotes, financials, options chains, earnings
- **Finviz** — RSI, insider activity, screening, sector data
- **SEC EDGAR** — Form 4 insider transactions (authoritative)
- **FRED** — macro indicators (treasury yields, CPI, unemployment, etc.)
- **Nasdaq** — earnings calendar, economic events, IPOs

## Optional: Claude AI sidebar

The app includes an optional AI chat sidebar powered by Claude. To enable it:

1. Get an API key from [console.anthropic.com](https://console.anthropic.com)
2. Add it as a Streamlit secret:
   - **Streamlit Cloud**: Settings > Secrets > add `ANTHROPIC_API_KEY = "sk-ant-..."`
   - **Local**: create `.streamlit/secrets.toml` with `ANTHROPIC_API_KEY = "sk-ant-..."`

The app works fully without this — all analysis is data-driven, not AI-dependent.

## Architecture

```
app.py                    # Home — nav card grid
pages/
  1_Indicators_Pro.py     # Macro dashboard
  2_Stock_Pro.py          # Main diagnosis (10 tabs)
  3_Discover.py           # Market screener
  4_Thesis.py             # Thesis journal + alerts
  5_Glossary.py           # Searchable dictionary
  6_Backtest.py           # Forward-return tracking
  7_Paper_Trading.py      # Simulated portfolios
  8_Calendar.py           # Earnings/econ/IPO calendar
  9_Insider_Buys.py       # SEC Form 4 purchases
  10_Compare.py           # Head-to-head comparison
  11_Watchlist.py         # Tracked tickers
  12_Options_Lab.py       # Options P&L simulator
lib/                      # Data fetchers, scoring, valuation, UI system
tests/                    # Unit tests (pytest)
```

## Storage

The app uses SQLite for persistence (watchlist, theses, paper trades). The database is created automatically at `data/stocks.db` on first run. On Streamlit Cloud, this resets on each deploy — your watchlist and paper trades are session-scoped.

For persistent storage on Streamlit Cloud, you could connect a cloud database, but for casual use the auto-created SQLite works fine.

## License

MIT
