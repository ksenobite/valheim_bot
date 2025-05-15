# -*- coding: utf-8 -*-

# db.py

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional
from settings import get_db_file_path


DB_FILE = None

def set_db_path(path):
    global DB_FILE
    DB_FILE = path
    logging.info(f"📁 Using database at: {DB_FILE}")

def get_db_path():
    return DB_FILE

def init_db():
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        # Основные таблицы
        c.execute("""CREATE TABLE IF NOT EXISTS frags (
            id INTEGER PRIMARY KEY,
            killer TEXT,
            victim TEXT,
            timestamp DATETIME
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS character_map (
            character TEXT PRIMARY KEY,
            discord_id INTEGER NOT NULL
        )""")

        # Новая таблица
        c.execute("""CREATE TABLE IF NOT EXISTS deathless_streaks (
            character TEXT PRIMARY KEY,
            streak INTEGER NOT NULL
        )""")

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

# --- Roles ---

def init_rank_roles_table():
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS rank_roles (
                wins_threshold INTEGER PRIMARY KEY,
                role_name TEXT NOT NULL
            )
        """)
        conn.commit()

def set_rank_role(wins_threshold: int, role_name: str):
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO rank_roles (wins_threshold, role_name)
            VALUES (?, ?)
            ON CONFLICT(wins_threshold) DO UPDATE SET role_name=excluded.role_name
        """, (wins_threshold, role_name))
        conn.commit()

def clear_rank_roles():
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM rank_roles")
        conn.commit()

def get_all_rank_roles() -> list[tuple[int, str]]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT wins_threshold, role_name FROM rank_roles ORDER BY wins_threshold DESC")
        return c.fetchall()

def is_auto_role_update_enabled() -> bool:
    return get_setting("auto_role_update_enabled") == "1"

def set_auto_role_update_enabled(enabled: bool):
    set_setting("auto_role_update_enabled", "1" if enabled else "0")

def get_auto_role_update_days(default: int = 7) -> int:
    value = get_setting("auto_role_update_days")
    return int(value) if value and value.isdigit() else default

def set_auto_role_update_days(days: int):
    set_setting("auto_role_update_days", str(days))


# --- deathstreaks ---

def get_deathless_streak(character: str) -> int:
    """Возвращает текущую 'чистую' серию побед персонажа."""
    with sqlite3.connect(get_db_file_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT count FROM deathless_streaks WHERE character = ?", (character.lower(),))
        row = c.fetchone()
        return row[0] if row else 0

def increment_deathless_streak(character: str) -> int:
    """Увеличивает серию на 1 и возвращает новое значение."""
    current = get_deathless_streak(character)
    new_value = current + 1
    with sqlite3.connect(get_db_file_path()) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO deathless_streaks (character, count)
            VALUES (?, ?)
            ON CONFLICT(character) DO UPDATE SET count = excluded.count
        """, (character.lower(), new_value))
    return new_value


def reset_deathless_streak(character: str):
    """Сбрасывает серию до 0."""
    with sqlite3.connect(get_db_file_path()) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO deathless_streaks (character, count)
            VALUES (?, 0)
            ON CONFLICT(character) DO UPDATE SET count = 0
        """, (character.lower(),))

# db.py (внизу файла)

# 💀 Deathless streaks
def update_deathless_streaks(killer: str, victim: str) -> int:
    """
    Updates the deathless streak for the killer and resets the victim's streak.
    Returns the killer's updated streak count.
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        # Reset victim's streak
        c.execute("DELETE FROM deathless_streaks WHERE character = ?", (victim,))

        # Get current killer streak
        c.execute("SELECT streak FROM deathless_streaks WHERE character = ?", (killer,))
        row = c.fetchone()

        if row:
            new_streak = row[0] + 1
            c.execute("UPDATE deathless_streaks SET streak = ? WHERE character = ?", (new_streak, killer))
        else:
            new_streak = 1
            c.execute("INSERT INTO deathless_streaks (character, streak) VALUES (?, ?)", (killer, new_streak))

        conn.commit()
        return new_streak
