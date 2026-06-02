"""Plain-English glossary + Explain Mode toggle.

Every technical term used in the app should have an entry here. When Explain
Mode is on, sections show plain-English subtitles and friendly tab labels.

Each glossary entry:
  term        — technical / abbreviation
  plain       — one-sentence plain English
  why         — why an investor should care
  rule        — rough rule of thumb ("> X is good, < Y is concerning")
  example     — concrete example
  category    — valuation | quality | growth | technical | macro | framework | model
  see_also    — list of related terms
"""
from __future__ import annotations

import streamlit as st


GLOSSARY: dict[str, dict] = {
    # === Valuation ===
    "P/E": {
        "term": "P/E (Price-to-Earnings)",
        "plain": "How many dollars you pay for every dollar of yearly profit the company makes.",
        "why": "Most-watched valuation ratio. Low = cheap, high = the market expects growth.",
        "rule": "Under 15 = cheap. 15 to 25 = market. Over 30 = priced for growth.",
        "example": "A $100 stock with $5/share annual earnings has a P/E of 20.",
        "category": "valuation",
    },
    "Forward P/E": {
        "term": "Forward P/E",
        "plain": "Like P/E, but uses next year's expected earnings instead of last year's.",
        "why": "Tells you what investors are paying based on what's coming, not what happened.",
        "rule": "Under 15 = cheap. Compare to the trailing P/E. Big gap means estimates are rising or falling.",
        "category": "valuation",
    },
    "PEG": {
        "term": "PEG (P/E to Growth)",
        "plain": "P/E divided by earnings growth rate. Asks: are you paying a fair price for the growth?",
        "why": "A high P/E can be cheap IF the company is growing fast. PEG normalizes for that.",
        "rule": "Under 1.0 = potentially undervalued for the growth. Over 2.0 = expensive even with growth.",
        "example": "A stock at 30x P/E growing earnings 30%/yr has a PEG of 1.0 (fair).",
        "category": "valuation",
    },
    "P/B": {
        "term": "P/B (Price-to-Book)",
        "plain": "Price compared to the accounting value of company assets minus debts (book value).",
        "why": "Below 1.0 means market values the company less than its accountants do. Classic Graham value.",
        "rule": "Under 1.0 = potentially cheap on assets. Useless for asset-light tech.",
        "category": "valuation",
    },
    "EV/EBITDA": {
        "term": "EV/EBITDA",
        "plain": "Enterprise value divided by earnings before interest, taxes, depreciation.",
        "why": "Levels the playing field between companies with different debt loads and tax rates.",
        "rule": "Under 8x = cheap. 8 to 12 = normal. Over 15 = premium.",
        "category": "valuation",
    },
    "FCF Yield": {
        "term": "FCF Yield (Free Cash Flow Yield)",
        "plain": "Annual cash a company produces, divided by market cap. Like a bond yield for stocks.",
        "why": "Cash is real. Earnings can be massaged. FCF yield is the truest 'return' to owners.",
        "rule": "Over 5% with stable business = attractive. Over 8% = compelling for boring companies.",
        "category": "valuation",
    },
    "DCF": {
        "term": "DCF (Discounted Cash Flow)",
        "plain": "Estimating what a company is worth by projecting future cash and discounting back to today.",
        "why": "The textbook way to value a business. Garbage in, garbage out though.",
        "rule": "Useful for sanity checks. Sensitivity-test the growth rate and discount rate.",
        "category": "valuation",
    },
    "Reverse DCF": {
        "term": "Reverse DCF",
        "plain": "Instead of guessing future growth and computing a price, you start with today's price and back out the growth it assumes.",
        "why": "The most honest valuation question: 'What does this need to grow at to justify today's price?'",
        "rule": "Under 5%/yr implied growth = low expectations bar. Over 20%/yr = priced for perfection.",
        "example": "If Reverse DCF says 25% growth is needed and the company grows 10%, the stock is overvalued.",
        "category": "valuation",
    },
    "Owner Earnings": {
        "term": "Owner Earnings",
        "plain": "Buffett's measure of true earnings: operating cash flow minus the capex needed just to maintain the business.",
        "why": "Strips out growth investment to show what the owner would actually pocket today.",
        "category": "valuation",
    },
    "EPV": {
        "term": "EPV (Earnings Power Value)",
        "plain": "What the business is worth based purely on current earning power, ignoring growth.",
        "why": "Greenwald's no-growth valuation. EPV > book value means there's a moat.",
        "category": "valuation",
    },

    # === Quality ===
    "ROE": {
        "term": "ROE (Return on Equity)",
        "plain": "Net profit as a percentage of shareholder equity. How efficiently the company turns invested money into profit.",
        "why": "Higher ROE = better business. But watch leverage, which inflates ROE artificially.",
        "rule": "Over 15% sustained = good. Over 20% = excellent.",
        "category": "quality",
    },
    "ROIC": {
        "term": "ROIC (Return on Invested Capital)",
        "plain": "Profit as a percentage of ALL capital invested (equity + debt). Less gameable than ROE.",
        "why": "Best single quality metric. ROIC > cost of capital = creating value.",
        "rule": "Over 15% = quality compounder. Over 25% = elite.",
        "category": "quality",
    },
    "ROA": {
        "term": "ROA (Return on Assets)",
        "plain": "Profit as a percentage of total assets.",
        "why": "Shows capital efficiency without ignoring debt. Useful for comparing peers in the same industry.",
        "category": "quality",
    },
    "Gross Margin": {
        "term": "Gross Margin",
        "plain": "Profit after direct production costs, as percentage of revenue.",
        "why": "Tells you about pricing power. Stable high gross margins usually mean a moat.",
        "rule": "Munger's test: persistent over 50% = moat. Over 40% = healthy.",
        "category": "quality",
    },
    "Operating Margin": {
        "term": "Operating Margin",
        "plain": "Profit after all operating costs (production, SG&A, R&D), as percentage of revenue.",
        "why": "Captures management efficiency. Rising op margin = operating leverage.",
        "rule": "Over 15% = healthy. Over 25% = elite.",
        "category": "quality",
    },
    "FCF Conversion": {
        "term": "FCF Conversion (FCF / Net Income)",
        "plain": "How much of reported profit actually becomes cash in the bank.",
        "why": "Persistent low conversion = earnings quality issue.",
        "rule": "Over 100% = high quality. Under 70% = scrutinize accruals and capex.",
        "category": "quality",
    },
    "Net Debt/EBITDA": {
        "term": "Net Debt to EBITDA",
        "plain": "How many years of pre-interest earnings it would take to pay off net debt.",
        "why": "Most-watched leverage ratio. Banks and rating agencies live on this.",
        "rule": "Under 2x = conservative. 2 to 4 = normal. Over 5x = stressed. Negative = net cash.",
        "category": "quality",
    },
    "Interest Coverage": {
        "term": "Interest Coverage",
        "plain": "How many times the company could pay its interest bill from operating profit.",
        "why": "Bond-default safety check. Zombies that survived ZIRP often can't cover at 5% rates.",
        "rule": "Over 5x = safe. 2 to 5x = OK. Under 1.5x = stressed.",
        "category": "quality",
    },
    "Current Ratio": {
        "term": "Current Ratio",
        "plain": "Current assets divided by current liabilities. Can the company pay short-term bills?",
        "why": "Graham's liquidity check. Higher = safer if revenue stops tomorrow.",
        "rule": "Over 2.0 = comfortable. Under 1.0 = warning.",
        "category": "quality",
    },

    # === Growth ===
    "Revenue Growth": {
        "term": "Revenue Growth (YoY)",
        "plain": "How much sales grew vs the same period last year.",
        "why": "Top line is the truth. Acceleration matters more than absolute growth.",
        "category": "growth",
    },
    "EPS Growth": {
        "term": "EPS Growth (Earnings per Share)",
        "plain": "How much net profit per share is growing year over year.",
        "why": "EPS can grow from real profit growth OR from buybacks (lower share count). Both work, real growth is higher quality.",
        "category": "growth",
    },
    "Rule of 40": {
        "term": "Rule of 40 (SaaS)",
        "plain": "Revenue growth rate plus FCF margin. SaaS companies should add up to at least 40.",
        "why": "Single best SaaS quality screen. A company growing 30% with 15% FCF margin = 45 = healthy.",
        "category": "growth",
    },
    "NRR": {
        "term": "NRR (Net Revenue Retention)",
        "plain": "Revenue from existing customers this year vs same group last year.",
        "why": "Tells you if customers are expanding or churning. Best SaaS commands 130%+.",
        "rule": "Over 120% = elite. 100 to 110 = healthy. Under 100% = leaky bucket.",
        "category": "growth",
    },

    # === Technical ===
    "200 DMA": {
        "term": "200-Day Moving Average",
        "plain": "Average closing price over the last 200 trading days. The long-term trend line.",
        "why": "Algorithmic and institutional traders respect it. Price above = bull regime, below = bear.",
        "category": "technical",
    },
    "RSI": {
        "term": "RSI (Relative Strength Index)",
        "plain": "Momentum gauge from 0 to 100. Compares average gains to average losses.",
        "why": "Quick read on overbought/oversold. Best signal is divergence (price up, RSI down).",
        "rule": "Over 70 = overbought. Under 30 = oversold. 40-60 = neutral.",
        "category": "technical",
    },
    "Beta": {
        "term": "Beta",
        "plain": "How volatile the stock is vs the market. Beta 1.0 = moves with market. 2.0 = moves 2x as much.",
        "why": "Risk gauge. High beta in a falling market = big drawdown.",
        "category": "technical",
    },
    "ATR": {
        "term": "ATR (Average True Range)",
        "plain": "Average daily price swing in dollars. Volatility expressed in absolute terms.",
        "why": "Position sizing tool: 'I'll risk 1 ATR of stop loss per share.'",
        "category": "technical",
    },

    # === Macro ===
    "VIX": {
        "term": "VIX (Volatility Index)",
        "plain": "30-day implied volatility on S&P 500 options. The market's 'fear gauge'.",
        "why": "Sentiment indicator. Spikes above 30 often coincide with market lows.",
        "rule": "Under 15 = complacency. 15 to 25 = normal. Over 30 = fear. Over 40 = panic buy zone.",
        "category": "macro",
    },
    "Yield Curve": {
        "term": "Yield Curve (10Y minus 2Y)",
        "plain": "Difference between long-term and short-term Treasury yields.",
        "why": "Has inverted (gone negative) before every US recession since 1960. Steepening from inversion is the actual trigger.",
        "category": "macro",
    },
    "HY OAS": {
        "term": "HY Credit Spread (OAS)",
        "plain": "Extra yield investors demand to hold junk bonds vs Treasuries.",
        "why": "Credit always leads equity. Spreads widening = stress coming.",
        "rule": "Under 400 bps = euphoric. 500-700 = normal. Over 800 = stress.",
        "category": "macro",
    },
    "DXY": {
        "term": "DXY (Dollar Index)",
        "plain": "Strength of US dollar vs basket of other major currencies.",
        "why": "Strong dollar = headwind for US multinationals, emerging markets, commodities.",
        "category": "macro",
    },
    "Real Yields": {
        "term": "Real Yields (TIPS)",
        "plain": "Treasury yield after stripping out expected inflation. The 'true' cost of capital.",
        "why": "Rising real yields = kryptonite for growth stocks. Watch this more than nominal yields.",
        "category": "macro",
    },

    # === Quality models ===
    "Piotroski": {
        "term": "Piotroski F-Score",
        "plain": "A 9-point checklist of financial health. Each year-over-year improvement scores 1 point.",
        "why": "Academic paper found 8-9 scores beat 0-2 scores by 7.5% annualized in value stocks.",
        "rule": "8-9 = strong. 5-7 = OK. Under 5 = weak.",
        "category": "model",
    },
    "Altman Z": {
        "term": "Altman Z-Score",
        "plain": "Bankruptcy risk model from 1968. Combines 5 ratios into one number.",
        "why": "Quick check for distress risk. Less reliable for banks and REITs.",
        "rule": "Over 2.99 = safe. 1.81-2.99 = grey zone. Under 1.81 = distress risk.",
        "category": "model",
    },
    "Beneish M": {
        "term": "Beneish M-Score",
        "plain": "8-ratio model that flags potential earnings manipulation.",
        "why": "Screen for accounting red flags. A flag is not proof — it's a 'look closer' signal.",
        "rule": "Above -1.78 = flagged. Below -1.78 = clean.",
        "category": "model",
    },

    # === Investor frameworks ===
    "Buffett style": {
        "term": "Buffett (Quality Compounder)",
        "plain": "Buy wonderful businesses at fair prices and hold forever.",
        "why": "Time arbitrage: great businesses compound. The market is too short-term to price decades-ahead.",
        "rule": "High ROIC + durable margins + low debt + reasonable price.",
        "category": "framework",
    },
    "Graham style": {
        "term": "Graham (Deep Value / Cigar Butt)",
        "plain": "Buy stocks for less than their breakup or book value. Quality optional.",
        "why": "Statistical edge. Many will turn out for a reason, but the cheap ones that work pay for the losers.",
        "rule": "P/B under 1, P/E under 10, dividend paying, manageable debt.",
        "category": "framework",
    },
    "Lynch style": {
        "term": "Lynch (GARP - Growth At Reasonable Price)",
        "plain": "Buy companies you understand whose growth rate exceeds their P/E.",
        "why": "Lynch wrote the playbook for individual investors finding 10-baggers in small/mid caps.",
        "rule": "PEG under 1, growth over 15%, insider buying, story you can explain.",
        "category": "framework",
    },
    "Fisher style": {
        "term": "Fisher (Scuttlebutt / Quality Growth)",
        "plain": "Find companies with above-average growth + superior management + long runways. Own for decades.",
        "why": "Buffett borrowed heavily from Fisher. Foundation of quality-growth investing.",
        "rule": "Revenue CAGR over 15%, gross margin over 40%, clean balance sheet, R&D investment.",
        "category": "framework",
    },

    # === Insider / Catalyst ===
    "Insider Buying": {
        "term": "Insider Buying (Form 4)",
        "plain": "When officers, directors, or 10%+ holders buy stock in the open market.",
        "why": "Insiders sell for many reasons (taxes, diversification). They buy for one. Cluster buying = strongest signal.",
        "category": "framework",
    },
    "13F": {
        "term": "13F Filing",
        "plain": "Quarterly disclosure of long positions held by funds with over $100M in assets.",
        "why": "See what super-investors are doing. Watch new positions, not just existing ones.",
        "category": "framework",
    },
    "Form 4": {
        "term": "Form 4",
        "plain": "SEC filing required within 2 days when an insider buys or sells.",
        "why": "Real-time insider transaction data, free at SEC EDGAR.",
        "category": "framework",
    },

    # === Indices ===
    "S&P 500": {
        "term": "S&P 500 (^GSPC)",
        "plain": "Index of 500 largest US companies, market-cap weighted.",
        "why": "The benchmark for US stocks. What most active managers fail to beat.",
        "category": "macro",
    },
    "Nasdaq": {
        "term": "Nasdaq Composite (^IXIC)",
        "plain": "Index of all stocks listed on the Nasdaq exchange. Heavily tech-weighted.",
        "why": "Proxy for tech / growth sentiment.",
        "category": "macro",
    },
    "Russell 2000": {
        "term": "Russell 2000 (^RUT)",
        "plain": "Index of 2000 small-cap US stocks.",
        "why": "Small caps lead in early-cycle recoveries. Watch for divergence from large caps.",
        "category": "macro",
    },
    "10Y Treasury": {
        "term": "10-Year Treasury Yield",
        "plain": "Yield on the benchmark 10-year US government bond.",
        "why": "The 'discount rate of everything'. Drives stock multiples and mortgage rates.",
        "category": "macro",
    },

    # === Investor frameworks (the rest of the lenses) ===
    "Inflection": {
        "term": "Inflection (Secular Tailwind)",
        "plain": "Catch a hyper-growth company right as it turns profitable, before the earnings catch up to the story.",
        "why": "The biggest gains come from the moment a money-losing grower flips to scalable profits and the market re-rates it.",
        "rule": "Revenue accelerating >30%, gross margin EXPANDING, op margin inflecting up (negative is OK if improving fast), innovation sector.",
        "example": "An optics supplier going from 15% to 30% gross margin as a hyperscaler ramps orders (AAOI-style).",
        "category": "framework",
    },
    "CAN SLIM": {
        "term": "O'Neil CAN SLIM",
        "plain": "William O'Neil's 7-part growth-momentum system: buy fast-growing market leaders during bull markets.",
        "why": "Blends fundamentals AND chart strength — you want explosive earnings AND a stock that's already acting like a winner.",
        "rule": "C: current EPS +25%. A: annual EPS rising. N: new catalyst/high. S: tight float. L: leader. I: institutional buying. M: market uptrend.",
        "category": "framework",
    },
    "Magic Formula": {
        "term": "Greenblatt Magic Formula",
        "plain": "Joel Greenblatt's mechanical quant strategy: rank every stock by quality (high ROIC) and cheapness (high earnings yield), then buy the best-ranked.",
        "why": "He proved in 'The Little Book That Beats the Market' that mechanically buying good companies at cheap prices beats the index over time — if you can stomach the stretches it underperforms.",
        "rule": "High ROIC (>20%) + high earnings yield (EBIT/EV, ~P/E under 10). Excludes financials & utilities. Hold a basket, rebalance yearly.",
        "category": "framework",
    },
    "Dividend Aristocrat": {
        "term": "Dividend Aristocrat / Quality Income",
        "plain": "Buy durable compounders that pay you a growing dividend while you wait.",
        "why": "Real cash returns from real businesses, not yield traps. A safe, rising dividend is hard to fake.",
        "rule": "Yield >2.5%, payout ratio <70%, EPS still growing, low leverage, FCF that covers the dividend >1.5x.",
        "category": "framework",
    },
    "Minervini": {
        "term": "Minervini Trend Template",
        "plain": "Mark Minervini's pure-momentum discipline: only own stocks in a confirmed Stage-2 uptrend with earnings to back it.",
        "why": "Strong stocks stay strong. Buying leaders trending up and cutting losers fast is how momentum traders compound.",
        "rule": "Price > 50DMA > 200DMA, 30%+ off the 52w low, within 25% of the 52w high, RSI strong but not blown out, earnings growing.",
        "category": "framework",
    },
    "Scuttlebutt": {
        "term": "Scuttlebutt (Fisher's method)",
        "plain": "Philip Fisher's research method: talk to a company's customers, suppliers, ex-employees, and competitors to understand it better than the filings ever could.",
        "why": "The qualitative edge. Numbers tell you the past; scuttlebutt tells you whether the moat and management are real. Buffett called Fisher a major influence.",
        "rule": "Ask: would customers switch? Is management honest and long-term? Is R&D producing the next product? Is the runway decades long?",
        "category": "framework",
    },
    "GARP": {
        "term": "GARP (Growth At a Reasonable Price)",
        "plain": "A middle path between deep value and pure growth — buy growing companies without overpaying for the growth.",
        "why": "Peter Lynch's sweet spot. You don't need the cheapest stock or the fastest grower; you need growth the price hasn't fully captured.",
        "rule": "PEG under 1 is the classic test: the P/E should be at or below the earnings growth rate.",
        "category": "framework",
    },
    "Net-Net": {
        "term": "Net-Net (NCAV)",
        "plain": "Graham's deepest bargain: a stock trading below its net current asset value (current assets minus ALL liabilities) — you're buying the liquid assets and getting the business for free.",
        "why": "Statistically the cheapest stocks on earth. Rare today, usually tiny or troubled, but a basket historically beat the market.",
        "rule": "Price < 2/3 of (current assets − total liabilities). P/B well under 1.",
        "category": "framework",
    },
    "Cigar Butt": {
        "term": "Cigar Butt",
        "plain": "A mediocre business bought so cheaply there's 'one free puff' of profit left — Buffett's term for early-Graham deep value.",
        "why": "Quality doesn't matter if the price is low enough; the statistical discount is the edge. Buffett moved on from this to quality compounders.",
        "rule": "Very low P/B and P/E, net cash or strong liquidity, size small (these are cheap for a reason).",
        "category": "framework",
    },
    "Moat": {
        "term": "Economic Moat",
        "plain": "A durable competitive advantage that protects a company's profits from competitors — brand, network effects, switching costs, scale, or low-cost production.",
        "why": "Moats are why great businesses keep high returns for decades instead of getting competed away. The single most important quality factor.",
        "rule": "Look for persistently high gross margins, high ROIC, and pricing power through cycles.",
        "category": "quality",
    },
    "Margin of Safety": {
        "term": "Margin of Safety",
        "plain": "Buying well below your estimate of fair value, so you're protected even if you're wrong.",
        "why": "Graham's central idea. You can't predict the future precisely, so build in a cushion. Bigger discount = more protection.",
        "rule": "Buffett's traditional zone is ~25-33% below fair value; Klarman/deep-value wants ~50%.",
        "category": "framework",
    },
    "Trend Stage": {
        "term": "Trend Stage (Weinstein)",
        "plain": "Stan Weinstein's four phases a stock cycles through: Stage 1 basing, Stage 2 advancing (uptrend), Stage 3 topping, Stage 4 declining.",
        "why": "Momentum investors only buy Stage 2. Knowing the stage keeps you from buying a falling knife (Stage 4) or a stalling top (Stage 3).",
        "rule": "Stage 2 = price > 50DMA > 200DMA with the 200DMA rising.",
        "category": "technical",
    },
    "Cluster Buying": {
        "term": "Cluster Buying (insiders)",
        "plain": "Two or more company insiders buying the stock on the open market within a short window.",
        "why": "One insider buy can be noise; a cluster means several people with inside knowledge independently decided it's cheap. The strongest signal available to retail.",
        "category": "framework",
    },

    # === Technicals (added) ===
    "MACD": {
        "term": "MACD (Moving Average Convergence Divergence)",
        "plain": "A momentum indicator: the gap between a fast and slow moving average of price, plus a signal line.",
        "why": "When MACD crosses above its signal line, momentum is turning up; below, turning down. Good for spotting trend shifts.",
        "rule": "MACD above signal = bullish momentum. Below = bearish. Watch for crossovers.",
        "category": "technical",
    },
    "Moving Average": {
        "term": "Moving Average (SMA)",
        "plain": "The average closing price over a set number of days (e.g. 50-day, 200-day), redrawn each day — it smooths out the noise to show the trend.",
        "why": "Key support/resistance levels that traders and algorithms watch. The 50 and 200 DMA crossings ('golden/death cross') are widely followed.",
        "category": "technical",
    },
    "Support & Resistance": {
        "term": "Support & Resistance",
        "plain": "Price levels where a stock has repeatedly stopped falling (support) or stopped rising (resistance).",
        "why": "Where buyers and sellers have clashed before, they often clash again. Useful for entries, exits, and stops.",
        "category": "technical",
    },
    "Short Interest": {
        "term": "Short Interest / Short Float",
        "plain": "The percentage of a company's tradable shares that have been sold short (bets the price will fall).",
        "why": "High short interest = strong bearish conviction OR fuel for a short squeeze. Know which before you buy.",
        "rule": "Under 5% = no overhang. 10-20% = elevated. Over 20% = heavy bearish bet / squeeze setup.",
        "category": "technical",
    },
    "Float": {
        "term": "Float",
        "plain": "The number of shares actually available for public trading (excludes insider-locked and restricted shares).",
        "why": "A small float means the stock can move violently on modest buying or selling. Tightening float (buybacks) supports the price.",
        "category": "technical",
    },

    # === Options ===
    "Implied Volatility": {
        "term": "Implied Volatility (IV)",
        "plain": "The annualized price swing the options market is pricing in for a stock. Higher IV = options expect bigger moves (and cost more).",
        "why": "IV is the market's forecast of turbulence. Rising IV before earnings, falling IV after ('IV crush'). It drives every option's price.",
        "rule": "Compare a stock's IV to its own history. High IV = expensive options (good to sell); low IV = cheap (good to buy).",
        "category": "options",
    },
    "Expected Move": {
        "term": "Expected Move",
        "plain": "How far the options market thinks a stock will move by a given expiration, up or down — estimated from the price of the at-the-money straddle.",
        "why": "A quick, market-implied range. Great for sizing earnings bets or knowing if a target is realistic by a date.",
        "example": "If a $100 stock's expected move is ±5% into earnings, the options market is pricing roughly a $95-$105 range.",
        "category": "options",
    },
    "Put/Call Ratio": {
        "term": "Put/Call Ratio",
        "plain": "Puts (downside bets) divided by calls (upside bets), by open interest or volume.",
        "why": "A sentiment gauge. High ratio = lots of bearish positioning (can be contrarian-bullish); low ratio = bullish/complacent.",
        "rule": "Around 0.7-1.0 is typical. Over 1.2 = bearish lean. Under 0.7 = bullish lean.",
        "category": "options",
    },
    "Max Pain": {
        "term": "Max Pain",
        "plain": "The strike price at which the most options (calls + puts) expire worthless — i.e. where option buyers lose the most.",
        "why": "Stocks sometimes gravitate toward max pain near big expirations as market-makers hedge. A rough magnet level, not a guarantee.",
        "category": "options",
    },
    "Open Interest": {
        "term": "Open Interest (OI)",
        "plain": "The total number of option contracts at a given strike that are currently open (not yet closed or expired).",
        "why": "Liquidity and conviction gauge. High-OI strikes act like support/resistance and are easier to trade in and out of.",
        "category": "options",
    },
    "Straddle": {
        "term": "Straddle",
        "plain": "Buying (or selling) both a call and a put at the same strike and expiry — a bet on a big move (or no move), regardless of direction.",
        "why": "The at-the-money straddle's price is how the 'expected move' is calculated. Buy it before a catalyst if you expect a big swing either way.",
        "category": "options",
    },

    # === Capital return ===
    "Total Shareholder Yield": {
        "term": "Total Shareholder Yield",
        "plain": "Dividends plus net buybacks, as a percentage of market cap — all the cash a company returns to owners.",
        "why": "A fuller picture than dividend yield alone. Buybacks shrink the share count, raising your stake in the business.",
        "category": "quality",
    },
}


CATEGORY_LABELS = {
    "valuation": "Valuation",
    "quality": "Quality",
    "growth": "Growth",
    "technical": "Technical",
    "options": "Options",
    "macro": "Macro",
    "framework": "Framework",
    "model": "Quality Model",
}

# Maps each investor-lens profile id to its glossary "idea behind it" entry,
# so the lenses can show the philosophy inline.
PROFILE_GLOSSARY = {
    "buffett": "Buffett style",
    "graham": "Graham style",
    "lynch": "Lynch style",
    "fisher": "Fisher style",
    "inflection": "Inflection",
    "canslim": "CAN SLIM",
    "magic_formula": "Magic Formula",
    "dividend": "Dividend Aristocrat",
    "minervini": "Minervini",
}


# ---------------------------------------------------------------------------
# Explain Mode
# ---------------------------------------------------------------------------

def is_explain_mode() -> bool:
    """True if Explain Mode toggle is on. Defaults to True for new users."""
    if "explain_mode" not in st.session_state:
        st.session_state.explain_mode = True
    return st.session_state.explain_mode


def is_simple_mode() -> bool:
    """True if Simple Mode toggle is on. Defaults to False."""
    if "simple_mode" not in st.session_state:
        st.session_state.simple_mode = False
    return st.session_state.simple_mode


def explain_toggle_sidebar():
    """Render the Explain Mode and Simple Mode toggles in sidebar. Call from every page."""
    with st.sidebar:
        em = st.toggle(
            "🎓 Explain Mode",
            value=is_explain_mode(),
            help="Plain-English subtitles and 'what this means' panels for every section.",
        )
        st.session_state.explain_mode = em
        sm = st.toggle(
            "🔤 Simple Mode",
            value=is_simple_mode(),
            help="Streamlined view — fewer metrics, plain labels, key takeaways up front.",
        )
        st.session_state.simple_mode = sm
        if em and sm:
            st.caption("Beginner-friendly + simplified view.")
        elif em:
            st.caption("Beginner-friendly explanations are on.")
        elif sm:
            st.caption("Simplified view — essentials only.")
        else:
            st.caption("Pro mode — minimal hand-holding.")


def explain(term: str, fallback: str = "") -> str:
    """Return plain English for a term, or fallback if not found."""
    entry = GLOSSARY.get(term)
    return entry["plain"] if entry else fallback


def explain_full(term: str) -> dict | None:
    """Return full glossary entry."""
    return GLOSSARY.get(term)


def smart_label(technical_label: str, plain_label: str) -> str:
    """Return plain label if Explain Mode is on, else technical."""
    return plain_label if is_explain_mode() else technical_label


def explain_block_if_on(text: str):
    """Render an explain panel only if Explain Mode is on."""
    from lib.ui import explain_panel
    if is_explain_mode():
        explain_panel(text)


def search_glossary(q: str) -> list[dict]:
    if not q:
        return list(GLOSSARY.values())
    ql = q.lower()
    return [g for g in GLOSSARY.values()
            if ql in g["term"].lower() or ql in g["plain"].lower()
            or ql in (g.get("why") or "").lower()]
