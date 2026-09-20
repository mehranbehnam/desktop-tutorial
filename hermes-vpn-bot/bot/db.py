import sqlite3
import time
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    created_at INTEGER,
    trial_used INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    plan_key TEXT,
    gb INTEGER,
    days INTEGER,
    base_price INTEGER,
    amount INTEGER,
    status TEXT DEFAULT 'pending',      -- pending | awaiting_review | approved | rejected
    xui_email TEXT,
    renew_target_email TEXT,            -- set when this order is a renewal of an existing client
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS clients (
    xui_email TEXT PRIMARY KEY,
    tg_id INTEGER,
    uuid TEXT,
    gb INTEGER,
    expiry_time INTEGER,
    created_at INTEGER
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_user(tg_id: int, username: str | None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (tg_id, username, created_at) VALUES (?, ?, ?)"
            "ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username",
            (tg_id, username, int(time.time())),
        )


def has_used_trial(tg_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT trial_used FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return bool(row and row["trial_used"])


def mark_trial_used(tg_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET trial_used=1 WHERE tg_id=?", (tg_id,))


def create_order(
    tg_id: int,
    plan_key: str,
    gb: int,
    days: int,
    base_price: int,
    amount: int,
    renew_target_email: str | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO orders (tg_id, plan_key, gb, days, base_price, amount, status, renew_target_email, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'awaiting_review', ?, ?)",
            (tg_id, plan_key, gb, days, base_price, amount, renew_target_email, int(time.time())),
        )
        return cur.lastrowid


def get_order(order_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()


def set_order_status(order_id: int, status: str, xui_email: str | None = None):
    with get_conn() as conn:
        if xui_email is not None:
            conn.execute("UPDATE orders SET status=?, xui_email=? WHERE id=?", (status, xui_email, order_id))
        else:
            conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))


def amount_in_use(amount: int) -> bool:
    """True if another order is currently awaiting review with the same exact amount."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM orders WHERE amount=? AND status='awaiting_review'", (amount,)
        ).fetchone()
        return row is not None


def save_client(xui_email: str, tg_id: int, client_uuid: str, gb: int, expiry_time: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO clients (xui_email, tg_id, uuid, gb, expiry_time, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(xui_email) DO UPDATE SET gb=excluded.gb, expiry_time=excluded.expiry_time",
            (xui_email, tg_id, client_uuid, gb, expiry_time, int(time.time())),
        )


def get_clients_for_user(tg_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM clients WHERE tg_id=?", (tg_id,)).fetchall()


def report_since(seconds: int | None):
    """Approved-order count/total since `seconds` ago, or all-time if None."""
    with get_conn() as conn:
        if seconds is None:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total "
                "FROM orders WHERE status='approved'"
            ).fetchone()
        else:
            since = int(time.time()) - seconds
            row = conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total "
                "FROM orders WHERE status='approved' AND created_at >= ?",
                (since,),
            ).fetchone()
        return row["cnt"], row["total"]


def all_clients():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM clients").fetchall()


def all_user_ids() -> list[int]:
    """Every user who ever /started the bot — the broadcast audience."""
    with get_conn() as conn:
        return [r["tg_id"] for r in conn.execute("SELECT tg_id FROM users").fetchall()]


def recent_orders(limit: int = 10):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def stats() -> dict:
    """Aggregate counters for a one-glance business overview."""
    with get_conn() as conn:
        users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        trial_used = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE trial_used=1"
        ).fetchone()["n"]
        clients = conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]
        approved = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total "
            "FROM orders WHERE status='approved'"
        ).fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE status='awaiting_review'"
        ).fetchone()["n"]
        return {
            "users": users,
            "trial_used": trial_used,
            "clients": clients,
            "orders_approved": approved["n"],
            "revenue_total": approved["total"],
            "orders_pending": pending,
        }
