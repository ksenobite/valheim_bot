# -*- coding: utf-8 -*-

# db.py

import logging
import os
import sqlite3

from datetime import datetime, timedelta, date
from typing import Optional
from collections import defaultdict

from settings import get_db_file_path
from glicko2 import Player


DB_FILE: Optional[str] = None

def set_db_path(path):
    global DB_FILE
    DB_FILE = path
    logging.info(f"📁 Using database at: {DB_FILE}")


def get_db_path() -> str:
    global DB_FILE
    if DB_FILE is None:
        raise RuntimeError("DB path is not set.")
    return DB_FILE


def init_db():
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
                
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

        c.execute("""CREATE TABLE IF NOT EXISTS deathless_streaks (
            character TEXT PRIMARY KEY,
            count INTEGER NOT NULL
        )""")
        
        c.execute("""CREATE TABLE IF NOT EXISTS manual_adjustments (
            character TEXT NOT NULL,
            adjustment INTEGER NOT NULL,
            reason TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        
        c.execute("""CREATE TABLE IF NOT EXISTS mmr_history (
                character TEXT,
                delta INTEGER,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        c.execute("""CREATE TABLE IF NOT EXISTS last_win (
                character TEXT PRIMARY KEY,
                last_win TIMESTAMP
            )
        """)
        
        c.execute("""CREATE TABLE IF NOT EXISTS glicko_ratings (
            character TEXT PRIMARY KEY,
            rating REAL DEFAULT 1500,
            rd REAL DEFAULT 350,
            vol REAL DEFAULT 0.06,
            last_win TEXT
        )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS glicko_history (
                character TEXT NOT NULL,
                delta REAL NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
                        
        conn.commit()


def get_setting(key):
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = c.fetchone()
        return row[0] if row else None
    
    
def set_setting(key, value):
    with sqlite3.connect(get_db_path()) as conn:
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
        with sqlite3.connect(get_db_path()) as conn:
            c = conn.cursor()
            c.execute("INSERT INTO frags (killer, victim, timestamp) VALUES (?, ?, ?)", (killer, victim, now))
            conn.commit()
        logging.info(f"⚔️  {killer} killed {victim} at {now}")
        
        update_glicko_ratings(killer, victim) # 🧠 Update MMR

    except sqlite3.Error as e:
        logging.error(f"❌ Error when adding a frag: {e}")


def get_top_players(n=10, days=1):
    with sqlite3.connect(get_db_path()) as conn:
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


def get_user_characters(discord_id: Optional[int]) -> list[str]:
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
    """
    Returns the Discord ID associated with the character, or None if there is no bundle.
    """
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


# --- 💀 Deathstreaks ---

def get_deathless_streak(character: str) -> int:
    """
    Returns the character's current 'clean' win streak.
    """
    with sqlite3.connect(get_db_file_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT count FROM deathless_streaks WHERE character = ?", (character.lower(),))
        row = c.fetchone()
        return row[0] if row else 0


def increment_deathless_streak(character: str) -> int:
    """
    Increases the series by 1 and returns a new value.
    """
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


def reset_deathless_streak(character: str) -> bool:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT count FROM deathless_streaks WHERE character = ?", (character,))
        row = c.fetchone()
        if row and row[0] >= 3:
            logging.info(f"💀 Streak for {character} interrupted at {row[0]}")
            conn.execute("DELETE FROM deathless_streaks WHERE character = ?", (character,))
            return True
        conn.execute("DELETE FROM deathless_streaks WHERE character = ?", (character,))
        return False


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
        c.execute("SELECT count FROM deathless_streaks WHERE character = ?", (killer,))
        row = c.fetchone()

        if row:
            new_streak = row[0] + 1
            c.execute("UPDATE deathless_streaks SET count = ? WHERE character = ?", (new_streak, killer))
        else:
            new_streak = 1
            c.execute("INSERT INTO deathless_streaks (character, count) VALUES (?, ?)", (killer, new_streak))

        conn.commit()
        return new_streak


def clear_deathless_streaks():
    """
    Deletes all entries from the deathless_streaks table at startup.
    """
    with sqlite3.connect(get_db_file_path()) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM deathless_streaks")
        conn.commit()
        logging.info("🧹 Cleared deathless_streaks table on startup.")

# --- Adjustment ---

def get_total_wins(character: str, days: int = 7) -> int:
    """
    Counts the total number of wins in N days, taking into account manual adjustments.
    """
    since = datetime.utcnow() - timedelta(days=days)
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        
        # Fragment wins
        c.execute("""
            SELECT COUNT(*) FROM frags
            WHERE killer = ? AND timestamp >= ?
        """, (character.lower(), since))
        frag_wins = c.fetchone()[0] or 0

        # Manual adjustments
        c.execute("""
            SELECT SUM(adjustment) FROM manual_adjustments
            WHERE character = ? AND timestamp >= ?
        """, (character.lower(), since))
        manual_delta = c.fetchone()[0] or 0

        return frag_wins + manual_delta


def get_total_wins_for_user(discord_id: int) -> int:
    """
    Returns the total points of all the user's characters (frags + adjustments).
    """
    total = 0
    for character in get_user_characters(discord_id):
        total += get_total_wins(character)
    return total


def adjust_wins(character: str, delta: int, reason: Optional[str] = None):
    """
    Adds a victory adjustment to manual_adjustments.
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO manual_adjustments (character, adjustment, reason)
            VALUES (?, ?, ?)
        """, (character.lower(), delta, reason))
        conn.commit()
        logging.info(f"✏️\tManual win adjustment: {character} -> {delta} ({reason})")


def get_win_sources(character: str) -> tuple[int, int]:
    """
    Returns a tuple of (manual, natural) wins.
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT SUM(adjustment) FROM manual_adjustments WHERE character = ?", (character.lower(),))
        manual = c.fetchone()[0] or 0

        c.execute("SELECT COUNT(*) FROM frags WHERE killer = ?", (character.lower(),))
        natural = c.fetchone()[0] or 0

        return manual, natural

# --- MMR ---

def get_top_mmr(limit: int = 10) -> list[tuple[str, int]]:
    """
    Returns a list of top characters by MMR.
    Each item: (character, mmr)
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT character, mmr FROM ratings
            ORDER BY mmr DESC LIMIT ?
        """, (limit,))
        return c.fetchall()


def set_mmr_role(threshold: int, role_name: str):
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO mmr_roles (threshold, role_name)
            VALUES (?, ?)
        """, (threshold, role_name))


def get_all_mmr_roles() -> list[tuple[int, str]]:
    with sqlite3.connect(get_db_path()) as conn:
        cur = conn.execute("SELECT threshold, role_name FROM mmr_roles ORDER BY threshold ASC")
        return cur.fetchall()


def clear_mmr_roles():
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute("DELETE FROM mmr_roles")


def clear_all_mmr():
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute("DELETE FROM ratings")
        conn.commit()


def rebuild_last_win():
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM last_win")

        c.execute("""
            SELECT killer, MAX(timestamp)
            FROM frags
            GROUP BY killer
        """)
        rows = c.fetchall()

        for character, last in rows:
            c.execute("INSERT INTO last_win (character, last_win) VALUES (?, ?)", (character, last))

        conn.commit()

# --- GLICKO-2 ---

def get_glicko_rating(character: str) -> tuple[float, float, float]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT rating, rd, vol FROM glicko_ratings WHERE character = ?
        """, (character.lower(),))
        row = c.fetchone()
        return row if row else (1500.0, 350.0, 0.06)


def set_glicko_rating(character: str, rating: float, rd: float, vol: float):
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO glicko_ratings (character, rating, rd, vol)
            VALUES (?, ?, ?, ?)
        """, (character.lower(), rating, rd, vol))
        conn.commit()


def update_glicko_ratings(killer: str, victim: str):
    """🔁 Update Glicko-2 rating for both players after a kill."""
    killer = killer.lower()
    victim = victim.lower()

    p1 = Player(*get_glicko_rating(killer))
    p2 = Player(*get_glicko_rating(victim))

    # 🧠 Killer wins, victim loses
    p1.update_player([p2.getRating()], [p2.getRd()], [1])
    p2.update_player([p1.getRating()], [p1.getRd()], [0])

    set_glicko_rating(killer, p1.getRating(), p1.getRd(), p1._vol)
    set_glicko_rating(victim, p2.getRating(), p2.getRd(), p2._vol)


def get_user_glicko_mmr(discord_id: int) -> Optional[int]:
    """
    Returns the average Glicko2 rating for all characters associated with the user.
    """
    characters = get_user_characters(discord_id)
    if not characters:
        return None

    mmrs = []
    for char in characters:
        glicko_data = get_glicko_rating(char)
        if glicko_data:
            mmrs.append(glicko_data[0])

    if not mmrs:
        return None

    return int(round(sum(mmrs) / len(mmrs)))


def get_fight_stats(character: str, since: datetime) -> tuple[int, int, int]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        c.execute("""
            SELECT COUNT(*) FROM frags
            WHERE killer = ? AND timestamp >= ?
        """, (character.lower(), since))
        wins = c.fetchone()[0]

        c.execute("""
            SELECT COUNT(*) FROM frags
            WHERE victim = ? AND timestamp >= ?
        """, (character.lower(), since))
        losses = c.fetchone()[0]

        return wins, losses, wins + losses


def get_last_active_day(character: str) -> Optional[date]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT MAX(timestamp) FROM frags
            WHERE killer = ? OR victim = ?
        """, (character.lower(), character.lower()))
        result = c.fetchone()[0]
        if result:
            return datetime.fromisoformat(result).date()
        return None


def get_all_players() -> set:
    """
    Returns a set of unique identifiers:
    - Discord IDs (int) for linked users
    - Character names (str) for standalone players
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        # Linked Discord users
        c.execute("SELECT DISTINCT discord_id FROM character_map")
        discord_ids = {row[0] for row in c.fetchall()}

        # All characters from frags
        c.execute("SELECT DISTINCT killer FROM frags")
        killers = {row[0].lower() for row in c.fetchall()}
        c.execute("SELECT DISTINCT victim FROM frags")
        victims = {row[0].lower() for row in c.fetchall()}
        all_characters = killers | victims

        # Characters from character_map
        c.execute("SELECT DISTINCT character FROM character_map")
        mapped_chars = {row[0].lower() for row in c.fetchall()}

        # Unlinked characters = all_characters - linked characters
        unlinked_characters = all_characters - mapped_chars

        return discord_ids | unlinked_characters


def get_user_glicko_rating(discord_id: Optional[int] = None) -> Optional[float]:
    characters = get_user_characters(discord_id)
    if not characters:
        return None
    ratings = [get_glicko_rating(c)[0] for c in characters]
    ratings = [r for r in ratings if r is not None]
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def get_top_glicko(limit: int = 10) -> list[tuple[str, float]]:
    """
    Returns a list of top characters by Glicko-2 rating.
    Each item: (character, rating)
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT character, rating FROM glicko_ratings
            ORDER BY rating DESC LIMIT ?
        """, (limit,))
        return c.fetchall()


def init_mmr_roles_table():
    """
    Initializes the mmr_roles table if it doesn't exist.
    """
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mmr_roles (
                threshold INTEGER PRIMARY KEY,
                role_name TEXT NOT NULL
            )
        """)
        conn.commit()


def recalculate_glicko_recent(days: int = 30):
    """
    Rebuild Glicko-2 ratings based on all frags from the last N days.
    Used in /topmmr to get fresh rankings.
    """
    since = datetime.utcnow() - timedelta(days=days)
    battles_by_day = defaultdict(list)

    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT killer, victim, timestamp FROM frags WHERE timestamp >= ? ORDER BY timestamp ASC", (since,))
        rows = c.fetchall()

    for killer, victim, ts in rows:
        day = datetime.fromisoformat(ts).date()
        battles_by_day[day].append((killer.lower(), victim.lower()))

    all_players = {}
    current = min(battles_by_day) if battles_by_day else datetime.utcnow().date()
    end = max(battles_by_day) if battles_by_day else current

    while current <= end:
        fights = battles_by_day.get(current, [])
        participated = set()

        for killer, victim in fights:
            if killer not in all_players:
                all_players[killer] = Player(*get_glicko_rating(killer))
            if victim not in all_players:
                all_players[victim] = Player(*get_glicko_rating(victim))

            p1 = all_players[killer]
            p2 = all_players[victim]

            p1.update_player([p2.getRating()], [p2.getRd()], [1])
            p2.update_player([p1.getRating()], [p1.getRd()], [0])
            participated.update([killer, victim])

        for name, player in all_players.items():
            if name not in participated:
                player.pre_rating_period()

        current += timedelta(days=1)

    with sqlite3.connect(get_db_path()) as conn:
        for name, player in all_players.items():
            set_glicko_rating(name, player.getRating(), player.getRd(), player._vol)
