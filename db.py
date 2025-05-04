# -*- coding: utf-8 -*-
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

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
        c.execute("""
            CREATE TABLE IF NOT EXISTS character_map (
                character TEXT PRIMARY KEY,
                discord_id INTEGER NOT NULL
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
    return int(val) if val else None

def get_announce_channel_id():
    val = get_setting("announce_channel_id")
    return int(val) if val else None

def get_announce_style():
    val = get_setting("announce_style")
    return val if val else "classic"

def set_announce_style(style_name):
    set_setting("announce_style", style_name)

# --- Stats ---

def add_frag(killer, victim):
    now = datetime.utcnow()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("INSERT INTO frags (killer, victim, timestamp) VALUES (?, ?, ?)", (killer, victim, now))
            conn.commit()
        logging.info(f"⚔️  {killer} killed {victim} at {now}")
    except sqlite3.Error as e:
        logging.error(f"❌ Error when adding a frag: {e}")


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

# --- Linking ---

def link_character(character: str, discord_id: int):
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO character_map (character, discord_id)
            VALUES (?, ?)
            ON CONFLICT(character) DO UPDATE SET discord_id=excluded.discord_id
        ''', (character, discord_id))
        conn.commit()


def unlink_character(character: str):
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM character_map WHERE character = ?', (character,))
        conn.commit()


def get_user_characters(discord_id: int) -> list[str]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute('SELECT character FROM character_map WHERE discord_id = ?', (discord_id,))
        return [row[0] for row in c.fetchall()]


def set_character_owner(character: str, discord_id: int):
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute('REPLACE INTO character_map (character, discord_id) VALUES (?, ?)', (character, discord_id))
        conn.commit()


def get_character_owner(character: str) -> Optional[int]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute('SELECT discord_id FROM character_map WHERE character = ?', (character,))
        row = c.fetchone()
        return row[0] if row else None

def remove_character_owner(character: str) -> bool:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM character_map WHERE LOWER(character) = LOWER(?)', (character,))
        conn.commit()
        return c.rowcount > 0

def get_discord_id_by_character(character_name: str) -> Optional[int]:
    """Возвращает Discord ID, связанный с персонажем, или None если связки нет."""
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT discord_id FROM character_map WHERE character = ?", (character_name.lower(),))
        result = c.fetchone()
        return result[0] if result else None
