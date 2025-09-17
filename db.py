# -*- coding: utf-8 -*-
# db.py

import logging
import os
import sqlite3

from datetime import datetime, timedelta, date
from typing import Optional, Tuple
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

def add_frag(killer: str, victim: str, channel_id: Optional[int] = None):
    now = datetime.utcnow()
    killer = killer.lower()
    victim = victim.lower()

    # find event by channel
    if channel_id is not None:
        event_id = get_event_id_by_channel(channel_id)
        if event_id is None:
            # channel not registered — ignore or fall back to default
            logging.warning(f"🔕 Unregistered channel {channel_id} — frag ignored.")
            return
    else:
        event_id = get_default_event_id()

    try:
        with sqlite3.connect(get_db_path()) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO frags (killer, victim, timestamp, event_id) VALUES (?, ?, ?, ?)",
                (killer, victim, now.isoformat(), event_id)
            )
            conn.commit()
        logging.info(f"⚔️  {killer} killed {victim} at {now} (event_id={event_id})")

        # update per-event glicko
        update_glicko_ratings(killer, victim, event_id)

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

def get_deathless_streak(character: str, event_id: Optional[int] = None) -> int:
    """
    Returns the current 'deathless' episode for the character.
    If the deathless_streaks table contains an event_id column and an event_id is passed,
    the series for the specified event will be returned.
    Otherwise, the behavior is compatible with the old version (by character name).
    """
    character = character.lower()
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        if _table_has_column(conn, "deathless_streaks", "event_id") and event_id is not None:
            c.execute(
                "SELECT count FROM deathless_streaks WHERE character = ? AND event_id = ?",
                (character, event_id),
            )
        else:
            # fallback to the old scheme
            c.execute("SELECT count FROM deathless_streaks WHERE character = ?", (character,))
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

def reset_deathless_streak(character: str, event_id: Optional[int] = None) -> bool:
    """
    Resets the series for character.
    Returns True if there was an active series >= 3 (then you can make an announcement about the interruption).
    It works within the event_id framework if the table supports event_id and it is passed.
    """
    character = character.lower()
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        event_aware = _table_has_column(conn, "deathless_streaks", "event_id")

        if event_aware and event_id is not None:
            c.execute("SELECT count FROM deathless_streaks WHERE character = ? AND event_id = ?", (character, event_id))
            row = c.fetchone()
            if row and row[0] >= 3:
                logging.info(f"💀 Streak for {character} interrupted (event_id={event_id}) at {row[0]}")
                c.execute("DELETE FROM deathless_streaks WHERE character = ? AND event_id = ?", (character, event_id))
                conn.commit()
                return True
            # delete the entry (if any), even if <3
            c.execute("DELETE FROM deathless_streaks WHERE character = ? AND event_id = ?", (character, event_id))
            conn.commit()
            return False
        else:
            # fallback: the old structure
            c.execute("SELECT count FROM deathless_streaks WHERE character = ?", (character,))
            row = c.fetchone()
            if row and row[0] >= 3:
                logging.info(f"💀 Streak for {character} interrupted at {row[0]}")
                c.execute("DELETE FROM deathless_streaks WHERE character = ?", (character,))
                conn.commit()
                return True
            c.execute("DELETE FROM deathless_streaks WHERE character = ?", (character,))
            conn.commit()
            return False

def update_deathless_streaks(killer: str, victim: str, event_id: Optional[int] = None) -> int:
    """
    Increases the streak of the killer and resets the streak of the victim.
    If the deathless_streaks table has an event_id column and event_id is passed,
    operations are performed within this event; otherwise, globally (old behavior).
    Returns a new killer series.
    """
    killer = killer.lower()
    victim = victim.lower()

    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        event_aware = _table_has_column(conn, "deathless_streaks", "event_id")

        if event_aware and event_id is not None:
            # Reset the victim in this event
            c.execute("DELETE FROM deathless_streaks WHERE character = ? AND event_id = ?", (victim, event_id))
            # Get the current killer episode in this event
            c.execute("SELECT count FROM deathless_streaks WHERE character = ? AND event_id = ?", (killer, event_id))
            row = c.fetchone()
            if row:
                new_streak = row[0] + 1
                c.execute("UPDATE deathless_streaks SET count = ? WHERE character = ? AND event_id = ?", (new_streak, killer, event_id))
            else:
                new_streak = 1
                c.execute("INSERT INTO deathless_streaks (character, count, event_id) VALUES (?, ?, ?)", (killer, new_streak, event_id))
        else:
            # fallback: old structure (without event_id)
            c.execute("DELETE FROM deathless_streaks WHERE character = ?", (victim,))
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
    """🔎 Backward-compatible wrapper for old calls (rating, rd, vol)."""
    rating, rd, vol, _ = get_glicko_rating_extended(character)
    return rating, rd, vol

def get_glicko_rating_extended(character: str, event_id: Optional[int] = None) -> tuple[float, float, float, Optional[str]]:
    character = character.lower()
    if event_id is None:
        event_id = get_default_event_id()
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT rating, rd, vol, last_activity FROM glicko_ratings
            WHERE character = ? AND event_id = ?
        """, (character, event_id))
        row = c.fetchone()
        if row:
            return (row[0], row[1], row[2], row[3])
        # default
        return (1500.0, 350.0, 0.06, None)

def set_glicko_rating(
    character: str,
    rating: float,
    rd: float,
    vol: float,
    event_id: Optional[int] = None,
    last_activity: Optional[str] = None
):
    """
    Insert or update Glicko-2 rating for a character within the given event.
    """
    character = character.lower()
    if event_id is None:
        event_id = get_default_event_id()

    with sqlite3.connect(get_db_path()) as conn:
        conn.execute("""
            INSERT INTO glicko_ratings (character, rating, rd, vol, last_activity, event_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(character, event_id) DO UPDATE SET
                rating = excluded.rating,
                rd = excluded.rd,
                vol = excluded.vol,
                last_activity = excluded.last_activity
        """, (character, rating, rd, vol, last_activity, event_id))
        conn.commit()

def update_glicko_ratings(killer: str, victim: str, event_id: Optional[int] = None):
    killer = killer.lower()
    victim = victim.lower()
    if event_id is None:
        event_id = get_default_event_id()

    # read current ratings for this event
    r1 = get_glicko_rating_extended(killer, event_id)
    r2 = get_glicko_rating_extended(victim, event_id)
    p1 = Player(r1[0], r1[1], r1[2])
    p2 = Player(r2[0], r2[1], r2[2])

    p1.update_player([p2.getRating()], [p2.getRd()], [1])
    p2.update_player([p1.getRating()], [p1.getRd()], [0])

    now_iso = datetime.utcnow().isoformat()
    set_glicko_rating(killer, p1.getRating(), p1.getRd(), p1._vol, event_id=event_id, last_activity=now_iso)
    set_glicko_rating(victim, p2.getRating(), p2.getRd(), p2._vol, event_id=event_id, last_activity=now_iso)

def get_user_glicko_mmr(discord_id: int, event_id: int) -> Optional[int]:
    """
    Returns the average Glicko2 rating for all user characters within the event_id.
    """
    characters = get_user_characters(discord_id)
    if not characters:
        return None

    mmrs = []
    for char in characters:
        glicko_data = get_glicko_rating_extended(char, event_id=event_id)
        if glicko_data:
            mmrs.append(glicko_data[0])

    if not mmrs:
        return None

    return int(round(sum(mmrs) / len(mmrs)))

def get_fight_stats(character: str, since: datetime, event_id: int) -> tuple[int, int, int]:
    """
    Returns (wins, losses, total) of the character within the event_id.
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        c.execute("""
            SELECT COUNT(*) FROM frags
            WHERE killer = ? AND timestamp >= ? AND event_id = ?
        """, (character.lower(), since, event_id))
        wins = c.fetchone()[0]

        c.execute("""
            SELECT COUNT(*) FROM frags
            WHERE victim = ? AND timestamp >= ? AND event_id = ?
        """, (character.lower(), since, event_id))
        losses = c.fetchone()[0]

        return wins, losses, wins + losses

def get_last_active_iso(character: str, event_id: Optional[int] = None) -> Optional[str]:
    """
    Return the ISO datetime string of the last activity (max timestamp) for a character
    in the given event, or None if there are no frags.
    """
    if event_id is None:
        event_id = get_default_event_id()

    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT MAX(timestamp) FROM frags
            WHERE event_id = ? AND (killer = ? OR victim = ?)
        """, (event_id, character.lower(), character.lower()))
        row = c.fetchone()[0]
        return row if row else None

def get_last_active_day(character: str, event_id: Optional[int] = None) -> Optional[date]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT last_activity FROM glicko_ratings
            WHERE character = ? AND (? IS NULL OR event_id = ?)
        """, (character.lower(), event_id, event_id))
        result = c.fetchone()
        if result and result[0]:
            return datetime.fromisoformat(result[0]).date()
        return None

def get_all_players(event_id: int) -> set:
    """
    Returns unique players within the event_id:
    - Discord IDs (int) for related users
    - Character names (str) for unrelated users
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        # Linked Discord users (everything, globally, 
        # because the user<->char connection does not depend on the event)
        c.execute("SELECT DISTINCT discord_id FROM character_map")
        discord_ids = {row[0] for row in c.fetchall() if row[0] is not None}

        # All characters from frags in this event
        c.execute("SELECT DISTINCT killer FROM frags WHERE event_id = ?", (event_id,))
        killers = {row[0].lower() for row in c.fetchall()}

        c.execute("SELECT DISTINCT victim FROM frags WHERE event_id = ?", (event_id,))
        victims = {row[0].lower() for row in c.fetchall()}

        all_characters = killers | victims

        # Characters that are in character_map (globally)
        c.execute("SELECT DISTINCT character FROM character_map")
        mapped_chars = {row[0].lower() for row in c.fetchall()}

        # Unlinked only within this event
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

# --- Events ---

def create_event(name: str, description: Optional[str] = None) -> int:
    name = name.strip().lower()
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO events (name, description) VALUES (?, ?)", (name, description))
        conn.commit()
        c.execute("SELECT id FROM events WHERE name = ?", (name,))
        row = c.fetchone()
        if row is None:
            # Something went wrong, so we throw an exception so that the code calls it explicitly.
            logging.error(f"Failed to create/find event '{name}' in DB")
            raise RuntimeError(f"Failed to create or fetch event '{name}'")
        return int(row[0])

def get_event_by_name(name: str) -> Optional[tuple]:
    if not name:
        return None
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, description, created_at FROM events WHERE name = ?", (name.strip().lower(),))
        return c.fetchone()

def get_event_id_by_channel(channel_id: int) -> Optional[int]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT event_id FROM event_channels WHERE channel_id = ?", (int(channel_id),))
        row = c.fetchone()
        return row[0] if row else None

def set_event_channel(event_name: str, channel_id: int) -> bool:
    """
    Binds a channel to an event both as a track and as an announcement.
    """
    event = get_event_by_name(event_name)
    if not event:
        event_id = create_event(event_name)
    else:
        event_id = event[0]

    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        # Deleting the old bindings of this channel (if any)
        c.execute("DELETE FROM event_channels WHERE channel_id = ?", (int(channel_id),))

        # Adding both entries
        c.execute("""
            INSERT INTO event_channels (event_id, channel_id, channel_type)
            VALUES (?, ?, 'track')
        """, (event_id, int(channel_id)))
        c.execute("""
            INSERT INTO event_channels (event_id, channel_id, channel_type)
            VALUES (?, ?, 'announce')
        """, (event_id, int(channel_id)))

        conn.commit()

    return True

def clear_event_channels(event_name: str):
    event = get_event_by_name(event_name)
    if not event:
        return
    event_id = event[0]
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute("DELETE FROM event_channels WHERE event_id = ?", (event_id,))
        conn.commit()

def list_events() -> list[tuple]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, description, created_at FROM events ORDER BY created_at DESC")
        return c.fetchall()

def get_default_event_id() -> int:
    # try settings.default_event otherwise 'arena'
    default_name = get_setting("default_event") or "arena"
    ev = get_event_by_name(default_name)
    if ev:
        return ev[0]
    return create_event(default_name)

def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    c = conn.cursor()
    try:
        c.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in c.fetchall()]
        return column in cols
    except Exception:
        return False

def get_event_id_by_name(name: str) -> Optional[int]:
    """
    Get the ID of an event by its name.
    Returns None if not found.
    """
    if not name:
        return None
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM events WHERE name = ?", (name.strip().lower(),))
        row = c.fetchone()
        return row[0] if row else None

def ensure_default_event():
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = 'default_event'")
        row = c.fetchone()
        if not row:
            c.execute("INSERT INTO settings (key, value) VALUES ('default_event', 'arena')")
            conn.commit()
            logging.info("✅ Default event set to 'arena'")
