# -*- coding: utf-8 -*-

import sqlite3
import logging
from datetime import datetime, timedelta

DB_FILE = None

def set_db_path(path):
    global DB_FILE
    DB_FILE = path
    logging.info(f"📁 Using database at: {DB_FILE}")


def get_db_path():
    return DB_FILE


def init_db():
    if not DB_FILE:
        raise ValueError("DB_FILE is not set. Call set_db_path(path) first.")
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # SAFE: Creates tables only if they don't exist
        c.execute("""
            CREATE TABLE IF NOT EXISTS frags (
                id INTEGER PRIMARY KEY,
                killer TEXT,
                victim TEXT,
                timestamp DATETIME
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()


def get_setting(key):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = c.fetchone()
        return row[0] if row else None


def set_setting(key, value):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

# --- Announce ---

def get_tracking_channel_id():
    val = get_setting("tracking_channel_id")
    logging.info(f"Tracking channel loaded from DB: {val}")
    return int(val) if val else None


def get_announce_channel_id():
    val = get_setting("announce_channel_id")
    logging.info(f"Announce channel loaded from DB: {val}")
    return int(val) if val else None


def get_announce_style():
    val = get_setting("announce_style")
    return val if val else "classic"

def set_announce_style(style_name):
    set_setting("announce_style", style_name)

# --- Stats ---

def add_frag(killer, victim):
    now = datetime.utcnow()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO frags (killer, victim, timestamp) VALUES (?, ?, ?)", (killer, victim, now))
        conn.commit()
    logging.info(f"{killer} killed {victim} at {now}")


def get_top_players(n=5, days=1):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        since = datetime.utcnow() - timedelta(days=days)
        c.execute("""
            SELECT killer, COUNT(*) as count FROM frags
            WHERE timestamp >= ?
            GROUP BY killer
            ORDER BY count DESC
            LIMIT ?
        """, (since, n))
        return c.fetchall()
