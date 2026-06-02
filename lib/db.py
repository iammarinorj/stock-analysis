"""SQLite persistence for watchlist + saved scorecards."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# Project root data directory
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stocks.db"


@contextmanager
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                added_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scorecards (
                symbol TEXT PRIMARY KEY,
                scored_at TEXT NOT NULL,
                total INTEGER,
                max INTEGER,
                pct REAL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS favorites (
                indicator_name TEXT PRIMARY KEY
            );
            -- v2: multi-profile scorecards (Buffett/Graham/Lynch/Fisher)
            CREATE TABLE IF NOT EXISTS profile_scorecards (
                symbol TEXT NOT NULL,
                profile TEXT NOT NULL,
                scored_at TEXT NOT NULL,
                total INTEGER,
                max INTEGER,
                pct REAL,
                payload TEXT NOT NULL,
                PRIMARY KEY (symbol, profile)
            );
            -- v2: thesis journal (one open thesis per symbol+side)
            CREATE TABLE IF NOT EXISTS theses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,            -- 'long' | 'short'
                profile TEXT,                  -- buffett/graham/lynch/fisher
                entry_price REAL,
                target_price REAL,
                stop_price REAL,
                position_size_pct REAL,
                bull_case TEXT,
                bear_case TEXT,
                breaks_if TEXT,
                key_metric TEXT,
                key_metric_target REAL,
                status TEXT NOT NULL DEFAULT 'open',  -- open|closed|stopped
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                close_price REAL,
                close_notes TEXT,
                review_date TEXT
            );
            -- v2: triggered alerts
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                condition TEXT NOT NULL,       -- e.g. "Price < 200DMA"
                value_at_trigger REAL,
                fired_at TEXT NOT NULL,
                seen INTEGER DEFAULT 0
            );
            -- v3: silent snapshots for forward-return tracking
            -- Saved automatically on every diagnose. Over time becomes
            -- the dataset for "did our scorecard predict returns?"
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                snapped_at TEXT NOT NULL,
                price REAL,
                buffett_pct REAL,
                graham_pct REAL,
                lynch_pct REAL,
                fisher_pct REAL,
                best_profile TEXT,
                best_pct REAL
            );
            CREATE INDEX IF NOT EXISTS idx_snap_symbol_time
                ON snapshots(symbol, snapped_at);

            -- v4: paper trading
            CREATE TABLE IF NOT EXISTS paper_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                starting_cash REAL NOT NULL,
                current_cash REAL NOT NULL,
                opened_at TEXT NOT NULL,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL DEFAULT 'long',
                qty REAL NOT NULL,
                entry_price REAL NOT NULL,
                entry_date TEXT NOT NULL,
                exit_price REAL,
                exit_date TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                target_price REAL,
                stop_price REAL,
                thesis TEXT,
                notes TEXT,
                FOREIGN KEY (account_id) REFERENCES paper_accounts(id)
            );
            CREATE INDEX IF NOT EXISTS idx_paper_pos_account
                ON paper_positions(account_id, status);
            CREATE TABLE IF NOT EXISTS paper_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                position_id INTEGER,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,  -- 'BUY' | 'SELL'
                qty REAL NOT NULL,
                price REAL NOT NULL,
                total REAL NOT NULL,
                executed_at TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (account_id) REFERENCES paper_accounts(id)
            );
            CREATE INDEX IF NOT EXISTS idx_paper_tx_account
                ON paper_transactions(account_id, executed_at);
            -- v5: paper options trading
            CREATE TABLE IF NOT EXISTS paper_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                opt_type TEXT NOT NULL,          -- 'call' | 'put'
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,            -- '2026-07-18' format
                side TEXT NOT NULL DEFAULT 'long',  -- 'long' | 'short' (selling)
                qty INTEGER NOT NULL,            -- number of contracts
                entry_premium REAL NOT NULL,     -- price per share paid/received
                entry_date TEXT NOT NULL,
                exit_premium REAL,
                exit_date TEXT,
                status TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'closed' | 'expired'
                thesis TEXT,
                notes TEXT,
                FOREIGN KEY (account_id) REFERENCES paper_accounts(id)
            );
            CREATE INDEX IF NOT EXISTS idx_paper_opts_account
                ON paper_options(account_id, status);

            -- Last-seen tickers per screen, to flag new entrants ("new this week").
            CREATE TABLE IF NOT EXISTS screen_history (
                style TEXT PRIMARY KEY,
                tickers TEXT NOT NULL,
                run_at TEXT NOT NULL
            );
        """)
        # --- lightweight migrations (add columns to existing DBs) ---
        wl_cols = [r[1] for r in c.execute("PRAGMA table_info(watchlist)").fetchall()]
        if "added_price" not in wl_cols:
            c.execute("ALTER TABLE watchlist ADD COLUMN added_price REAL")


# Watchlist -------------------------------------------------------------

def add_to_watchlist(symbol: str, added_price: float | None = None):
    """Add a symbol. Stores the price at add-time so the UI can show the
    return since you started watching it."""
    init_db()
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO watchlist (symbol, added_at, added_price) VALUES (?, ?, ?)",
            (symbol.upper(), datetime.utcnow().isoformat(), added_price),
        )
        # Backfill the add-price if the row existed without one.
        if added_price is not None:
            c.execute(
                "UPDATE watchlist SET added_price = ? WHERE symbol = ? AND added_price IS NULL",
                (added_price, symbol.upper()),
            )


def get_prev_screen_tickers(style: str) -> tuple[set, str | None]:
    """Return (set of tickers from the last saved run, run_at) for a screen style."""
    init_db()
    with conn() as c:
        row = c.execute("SELECT tickers, run_at FROM screen_history WHERE style = ?", (style,)).fetchone()
    if not row:
        return set(), None
    try:
        return set(json.loads(row["tickers"])), row["run_at"]
    except Exception:
        return set(), row["run_at"]


def save_screen_tickers(style: str, tickers: list[str]):
    """Persist the current ticker set for a screen so the next run can diff it."""
    init_db()
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO screen_history (style, tickers, run_at) VALUES (?, ?, ?)",
            (style, json.dumps(sorted(set(tickers))), datetime.utcnow().isoformat()),
        )


def backfill_watchlist_price(symbol: str, price: float | None):
    """Set added_price for an EXISTING watchlist row that has none (e.g. added
    before we tracked price, or added without a quote). Never inserts."""
    if price is None:
        return
    init_db()
    with conn() as c:
        c.execute(
            "UPDATE watchlist SET added_price = ? WHERE symbol = ? AND added_price IS NULL",
            (float(price), symbol.upper()),
        )


def get_watchlist_detailed() -> list[dict]:
    """Watchlist rows with added_at + added_price (for since-added performance)."""
    init_db()
    with conn() as c:
        rows = c.execute(
            "SELECT symbol, added_at, added_price FROM watchlist ORDER BY added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def remove_from_watchlist(symbol: str):
    init_db()
    with conn() as c:
        c.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))


def get_watchlist() -> list[str]:
    init_db()
    with conn() as c:
        rows = c.execute("SELECT symbol FROM watchlist ORDER BY added_at DESC").fetchall()
    return [r["symbol"] for r in rows]


# Scorecards ------------------------------------------------------------

def save_scorecard(symbol: str, scorecard: dict):
    init_db()
    with conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO scorecards
               (symbol, scored_at, total, max, pct, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                symbol.upper(),
                datetime.utcnow().isoformat(),
                int(scorecard.get("total", 0)),
                int(scorecard.get("max", 0)),
                float(scorecard.get("pct", 0)),
                json.dumps(scorecard),
            ),
        )


def get_scorecard(symbol: str) -> dict | None:
    init_db()
    with conn() as c:
        row = c.execute(
            "SELECT payload, scored_at FROM scorecards WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
    if not row:
        return None
    sc = json.loads(row["payload"])
    sc["scored_at"] = row["scored_at"]
    return sc


def list_scorecards() -> list[dict]:
    """All saved scorecards with summary fields."""
    init_db()
    with conn() as c:
        rows = c.execute(
            "SELECT symbol, scored_at, total, max, pct FROM scorecards ORDER BY scored_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_scorecard(symbol: str):
    init_db()
    with conn() as c:
        c.execute("DELETE FROM scorecards WHERE symbol = ?", (symbol.upper(),))


# Favorites (for indicators page) ---------------------------------------

def add_favorite(name: str):
    init_db()
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO favorites (indicator_name) VALUES (?)", (name,))


def remove_favorite(name: str):
    init_db()
    with conn() as c:
        c.execute("DELETE FROM favorites WHERE indicator_name = ?", (name,))


def get_favorites() -> list[str]:
    init_db()
    with conn() as c:
        rows = c.execute("SELECT indicator_name FROM favorites").fetchall()
    return [r["indicator_name"] for r in rows]


# -----------------------------------------------------------------------
# v2: Multi-profile scorecards
# -----------------------------------------------------------------------

def save_profile_scorecard(symbol: str, profile: str, sc: dict):
    init_db()
    with conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO profile_scorecards
               (symbol, profile, scored_at, total, max, pct, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                symbol.upper(), profile,
                datetime.utcnow().isoformat(),
                int(sc.get("total", 0)),
                int(sc.get("max", 0)),
                float(sc.get("pct", 0)),
                json.dumps(sc),
            ),
        )


def get_profile_scorecards(symbol: str) -> dict:
    """Return {profile_id: payload} for all profiles saved for a symbol."""
    init_db()
    with conn() as c:
        rows = c.execute(
            "SELECT profile, payload, scored_at, pct FROM profile_scorecards WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchall()
    out = {}
    for r in rows:
        d = json.loads(r["payload"])
        d["scored_at"] = r["scored_at"]
        out[r["profile"]] = d
    return out


def list_profile_scorecards_summary() -> list[dict]:
    """All saved multi-profile scorecards, latest per symbol."""
    init_db()
    with conn() as c:
        rows = c.execute(
            """SELECT symbol, profile, scored_at, pct
               FROM profile_scorecards
               ORDER BY scored_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------------
# v2: Thesis journal
# -----------------------------------------------------------------------

def save_thesis(t: dict) -> int:
    init_db()
    with conn() as c:
        cur = c.execute(
            """INSERT INTO theses (symbol, side, profile, entry_price, target_price,
               stop_price, position_size_pct, bull_case, bear_case, breaks_if,
               key_metric, key_metric_target, status, opened_at, review_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                t["symbol"].upper(), t.get("side", "long"), t.get("profile"),
                t.get("entry_price"), t.get("target_price"), t.get("stop_price"),
                t.get("position_size_pct"),
                t.get("bull_case"), t.get("bear_case"), t.get("breaks_if"),
                t.get("key_metric"), t.get("key_metric_target"),
                t.get("status", "open"),
                datetime.utcnow().isoformat(),
                t.get("review_date"),
            ),
        )
        return cur.lastrowid


def get_theses(status: str = "open", symbol: str | None = None) -> list[dict]:
    init_db()
    q = "SELECT * FROM theses WHERE status = ?"
    params = [status]
    if symbol:
        q += " AND symbol = ?"
        params.append(symbol.upper())
    q += " ORDER BY opened_at DESC"
    with conn() as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def close_thesis(thesis_id: int, close_price: float, notes: str = ""):
    init_db()
    with conn() as c:
        c.execute(
            """UPDATE theses SET status = 'closed', closed_at = ?,
               close_price = ?, close_notes = ? WHERE id = ?""",
            (datetime.utcnow().isoformat(), close_price, notes, thesis_id),
        )


def delete_thesis(thesis_id: int):
    init_db()
    with conn() as c:
        c.execute("DELETE FROM theses WHERE id = ?", (thesis_id,))


# -----------------------------------------------------------------------
# v2: Alerts
# -----------------------------------------------------------------------

def fire_alert(symbol: str, condition: str, value: float | None = None):
    init_db()
    with conn() as c:
        c.execute(
            "INSERT INTO alerts (symbol, condition, value_at_trigger, fired_at) VALUES (?,?,?,?)",
            (symbol.upper(), condition, value, datetime.utcnow().isoformat()),
        )


def get_alerts(seen: bool = False) -> list[dict]:
    init_db()
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM alerts WHERE seen = ? ORDER BY fired_at DESC",
            (1 if seen else 0,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_alerts_seen():
    init_db()
    with conn() as c:
        c.execute("UPDATE alerts SET seen = 1 WHERE seen = 0")


# -----------------------------------------------------------------------
# v3: Snapshots (forward-return tracking)
# -----------------------------------------------------------------------

def save_snapshot(symbol: str, price: float | None, scores: dict):
    """Save a point-in-time scorecard snapshot. Called automatically on every diagnose.

    Over time these accumulate into a real out-of-sample dataset for
    'did our scorecard predict returns?'.
    """
    init_db()
    if not symbol or price is None:
        return
    # Skip if we already saved one in the last 12 hours (no point in flooding)
    with conn() as c:
        recent = c.execute(
            """SELECT 1 FROM snapshots
               WHERE symbol = ? AND snapped_at > datetime('now', '-12 hours')
               LIMIT 1""",
            (symbol.upper(),),
        ).fetchone()
        if recent:
            return
        get = lambda pid: float(scores.get(pid, {}).get("pct", 0) or 0)
        best_pid = max(scores, key=lambda k: scores[k].get("pct", 0)) if scores else None
        best_pct = float(scores.get(best_pid, {}).get("pct", 0) or 0) if best_pid else None
        c.execute(
            """INSERT INTO snapshots
               (symbol, snapped_at, price, buffett_pct, graham_pct, lynch_pct, fisher_pct,
                best_profile, best_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol.upper(), datetime.utcnow().isoformat(), float(price),
             get("buffett"), get("graham"), get("lynch"), get("fisher"),
             best_pid, best_pct),
        )


def get_snapshots(symbol: str | None = None, older_than_days: int = 0) -> list[dict]:
    """Return snapshots, optionally filtered by symbol or age threshold."""
    init_db()
    q = "SELECT * FROM snapshots WHERE 1=1"
    params = []
    if symbol:
        q += " AND symbol = ?"
        params.append(symbol.upper())
    if older_than_days > 0:
        q += " AND snapped_at < datetime('now', ?)"
        params.append(f"-{older_than_days} days")
    q += " ORDER BY snapped_at DESC"
    with conn() as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def get_all_snapshots() -> list[dict]:
    init_db()
    with conn() as c:
        rows = c.execute("SELECT * FROM snapshots ORDER BY snapped_at DESC").fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------------
# v4: Paper trading
# -----------------------------------------------------------------------

def create_paper_account(name: str, starting_cash: float, notes: str = "") -> int:
    init_db()
    with conn() as c:
        cur = c.execute(
            """INSERT INTO paper_accounts (name, starting_cash, current_cash, opened_at, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (name, starting_cash, starting_cash, datetime.utcnow().isoformat(), notes),
        )
        return cur.lastrowid


def get_paper_accounts() -> list[dict]:
    init_db()
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM paper_accounts ORDER BY opened_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_paper_account(account_id: int) -> dict | None:
    init_db()
    with conn() as c:
        row = c.execute(
            "SELECT * FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
    return dict(row) if row else None


def paper_account_by_name(name: str) -> dict | None:
    init_db()
    with conn() as c:
        row = c.execute(
            "SELECT * FROM paper_accounts WHERE name = ?", (name,)
        ).fetchone()
    return dict(row) if row else None


def update_paper_cash(account_id: int, new_cash: float):
    init_db()
    with conn() as c:
        c.execute(
            "UPDATE paper_accounts SET current_cash = ? WHERE id = ?",
            (new_cash, account_id),
        )


def delete_paper_account(account_id: int):
    init_db()
    with conn() as c:
        c.execute("DELETE FROM paper_transactions WHERE account_id = ?", (account_id,))
        c.execute("DELETE FROM paper_positions WHERE account_id = ?", (account_id,))
        c.execute("DELETE FROM paper_options WHERE account_id = ?", (account_id,))
        c.execute("DELETE FROM paper_accounts WHERE id = ?", (account_id,))


def open_paper_position(account_id: int, symbol: str, qty: float, entry_price: float,
                        side: str = "long", target_price: float | None = None,
                        stop_price: float | None = None, thesis: str = "",
                        notes: str = "") -> int:
    init_db()
    cost = qty * entry_price
    now = datetime.utcnow().isoformat()
    with conn() as c:
        acct = c.execute("SELECT current_cash FROM paper_accounts WHERE id = ?",
                         (account_id,)).fetchone()
        if not acct:
            raise ValueError(f"Account {account_id} not found")
        if acct["current_cash"] < cost:
            raise ValueError(
                f"Insufficient cash: need ${cost:,.2f}, have ${acct['current_cash']:,.2f}"
            )
        cur = c.execute(
            """INSERT INTO paper_positions
               (account_id, symbol, side, qty, entry_price, entry_date,
                target_price, stop_price, thesis, notes, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (account_id, symbol.upper(), side, qty, entry_price, now,
             target_price, stop_price, thesis, notes),
        )
        pos_id = cur.lastrowid
        c.execute(
            """INSERT INTO paper_transactions
               (account_id, position_id, symbol, action, qty, price, total, executed_at, notes)
               VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?)""",
            (account_id, pos_id, symbol.upper(), qty, entry_price, cost, now, notes),
        )
        c.execute(
            "UPDATE paper_accounts SET current_cash = current_cash - ? WHERE id = ?",
            (cost, account_id),
        )
        return pos_id


def close_paper_position(position_id: int, exit_price: float, notes: str = ""):
    init_db()
    now = datetime.utcnow().isoformat()
    with conn() as c:
        pos = c.execute("SELECT * FROM paper_positions WHERE id = ?",
                        (position_id,)).fetchone()
        if not pos:
            raise ValueError(f"Position {position_id} not found")
        if pos["status"] != "open":
            raise ValueError("Position already closed")
        proceeds = pos["qty"] * exit_price
        c.execute(
            """UPDATE paper_positions
               SET exit_price = ?, exit_date = ?, status = 'closed', notes = ?
               WHERE id = ?""",
            (exit_price, now, notes, position_id),
        )
        c.execute(
            """INSERT INTO paper_transactions
               (account_id, position_id, symbol, action, qty, price, total, executed_at, notes)
               VALUES (?, ?, ?, 'SELL', ?, ?, ?, ?, ?)""",
            (pos["account_id"], position_id, pos["symbol"], pos["qty"],
             exit_price, proceeds, now, notes),
        )
        c.execute(
            "UPDATE paper_accounts SET current_cash = current_cash + ? WHERE id = ?",
            (proceeds, pos["account_id"]),
        )


def get_paper_positions(account_id: int, status: str | None = None) -> list[dict]:
    init_db()
    q = "SELECT * FROM paper_positions WHERE account_id = ?"
    params = [account_id]
    if status:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY entry_date DESC"
    with conn() as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def get_paper_transactions(account_id: int) -> list[dict]:
    init_db()
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM paper_transactions WHERE account_id = ? ORDER BY executed_at DESC",
            (account_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------------
# v5: Paper options trading
# -----------------------------------------------------------------------

def open_paper_option(account_id: int, symbol: str, opt_type: str, strike: float,
                      expiry: str, side: str, qty: int, entry_premium: float,
                      thesis: str = "", notes: str = "") -> int:
    """Open a paper options position.

    For LONG: deducts cost (qty * 100 * entry_premium) from cash.
    For SHORT (writing): adds premium received to cash.
    Returns the new position id.
    """
    init_db()
    total = qty * 100 * entry_premium
    now = datetime.utcnow().isoformat()
    with conn() as c:
        acct = c.execute("SELECT current_cash FROM paper_accounts WHERE id = ?",
                         (account_id,)).fetchone()
        if not acct:
            raise ValueError(f"Account {account_id} not found")
        if side == "long" and acct["current_cash"] < total:
            raise ValueError(
                f"Insufficient cash: need ${total:,.2f}, have ${acct['current_cash']:,.2f}"
            )
        cur = c.execute(
            """INSERT INTO paper_options
               (account_id, symbol, opt_type, strike, expiry, side, qty,
                entry_premium, entry_date, status, thesis, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (account_id, symbol.upper(), opt_type.lower(), strike, expiry,
             side, qty, entry_premium, now, thesis, notes),
        )
        pos_id = cur.lastrowid
        # Adjust cash: long pays premium, short receives premium
        if side == "long":
            c.execute(
                "UPDATE paper_accounts SET current_cash = current_cash - ? WHERE id = ?",
                (total, account_id),
            )
        else:  # short / write
            c.execute(
                "UPDATE paper_accounts SET current_cash = current_cash + ? WHERE id = ?",
                (total, account_id),
            )
        return pos_id


def close_paper_option(option_id: int, exit_premium: float, notes: str = ""):
    """Close an open options position at the given exit premium.

    For LONG: adds proceeds (qty * 100 * exit_premium) to cash.
    For SHORT: deducts buyback cost (qty * 100 * exit_premium) from cash.
    """
    init_db()
    now = datetime.utcnow().isoformat()
    with conn() as c:
        pos = c.execute("SELECT * FROM paper_options WHERE id = ?",
                        (option_id,)).fetchone()
        if not pos:
            raise ValueError(f"Option position {option_id} not found")
        if pos["status"] != "open":
            raise ValueError("Option position already closed/expired")
        total = pos["qty"] * 100 * exit_premium
        c.execute(
            """UPDATE paper_options
               SET exit_premium = ?, exit_date = ?, status = 'closed', notes = ?
               WHERE id = ?""",
            (exit_premium, now, notes, option_id),
        )
        # Adjust cash: long receives proceeds, short pays to buy back
        if pos["side"] == "long":
            c.execute(
                "UPDATE paper_accounts SET current_cash = current_cash + ? WHERE id = ?",
                (total, pos["account_id"]),
            )
        else:  # short
            c.execute(
                "UPDATE paper_accounts SET current_cash = current_cash - ? WHERE id = ?",
                (total, pos["account_id"]),
            )


def expire_paper_option(option_id: int, notes: str = ""):
    """Mark an option as expired with exit_premium=0.

    Long loses all premium paid; short keeps all premium received.
    No cash adjustment needed — long already paid; short already received.
    """
    init_db()
    now = datetime.utcnow().isoformat()
    with conn() as c:
        pos = c.execute("SELECT * FROM paper_options WHERE id = ?",
                        (option_id,)).fetchone()
        if not pos:
            raise ValueError(f"Option position {option_id} not found")
        if pos["status"] != "open":
            raise ValueError("Option position already closed/expired")
        c.execute(
            """UPDATE paper_options
               SET exit_premium = 0, exit_date = ?, status = 'expired', notes = ?
               WHERE id = ?""",
            (now, notes, option_id),
        )


def get_paper_options(account_id: int, status: str | None = None) -> list[dict]:
    """Get paper options positions, optionally filtered by status."""
    init_db()
    q = "SELECT * FROM paper_options WHERE account_id = ?"
    params: list = [account_id]
    if status:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY entry_date DESC"
    with conn() as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]
