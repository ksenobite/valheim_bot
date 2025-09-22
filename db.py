# -*- coding: utf-8 -*-
# db.py

import logging
import os
import sqlite3

from datetime import datetime, timedelta, date, timezone
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
    """
    Initialize or migrate the SQLite schema to the current event-aware layout.
    This function is idempotent and adds missing columns/tables/indexes safely.
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        # --- Core tables (create if missing) ---
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

        c.execute("""
            CREATE TABLE IF NOT EXISTS manual_adjustments (
                character TEXT NOT NULL,
                adjustment INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # frags with event_id
        c.execute("""
            CREATE TABLE IF NOT EXISTS frags (
                id INTEGER PRIMARY KEY,
                killer TEXT,
                victim TEXT,
                timestamp DATETIME,
                event_id INTEGER
            )
        """)

        # deathless_streaks with event_id and composite PK
        c.execute("""
            CREATE TABLE IF NOT EXISTS deathless_streaks (
                character TEXT NOT NULL,
                count INTEGER NOT NULL,
                event_id INTEGER NOT NULL,
                PRIMARY KEY (character, event_id)
            )
        """)

        # glicko_ratings target schema (event-aware, composite PK)
        c.execute("""
            CREATE TABLE IF NOT EXISTS glicko_ratings (
                character TEXT NOT NULL,
                rating REAL DEFAULT 1500,
                rd REAL DEFAULT 350,
                vol REAL DEFAULT 0.06,
                last_activity TEXT,
                event_id INTEGER NOT NULL,
                PRIMARY KEY (character, event_id)
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

        # Events support
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS event_channels (
                event_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL UNIQUE,
                channel_type TEXT NOT NULL CHECK(channel_type IN ('track','announce')),
                PRIMARY KEY(event_id, channel_id, channel_type)
            )
        """)

        # Rank/MMR roles
        c.execute("""
            CREATE TABLE IF NOT EXISTS rank_roles (
                wins_threshold INTEGER PRIMARY KEY,
                role_name TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS mmr_roles (
                threshold INTEGER PRIMARY KEY,
                role_name TEXT NOT NULL
            )
        """)

        # --- Migrations: add missing columns (legacy DBs) ---
        def ensure_column(table: str, column: str, ddl: str):
            if not _table_has_column(conn, table, column):
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
                except sqlite3.OperationalError:
                    pass

        ensure_column("frags", "event_id", "event_id INTEGER")
        ensure_column("deathless_streaks", "event_id", "event_id INTEGER")
        ensure_column("manual_adjustments", "event_id", "event_id INTEGER")
        ensure_column("glicko_history", "event_id", "event_id INTEGER")
        # rename last_win -> last_activity is non-trivial; just ensure last_activity exists
        # If legacy deathless_streaks exists without composite PK, rebuild it to the new schema
        try:
            c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='deathless_streaks'")
            row = c.fetchone()
            ddl = row[0] if row else ""
        except Exception:
            ddl = ""

        needs_deathless_rebuild = False
        if ddl:
            normalized = ddl.replace("`", "").replace("\n", " ").lower()
            if "primary key (character, event_id)" not in normalized:
                needs_deathless_rebuild = True

        if needs_deathless_rebuild:
            # Detect available columns for legacy copy
            has_event = _table_has_column(conn, "deathless_streaks", "event_id")

            # Ensure default event exists and get its id for legacy rows
            from_this_default = get_default_event_id()

            c.execute("""
                CREATE TABLE IF NOT EXISTS deathless_streaks__new (
                    character TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    event_id INTEGER NOT NULL,
                    PRIMARY KEY (character, event_id)
                )
            """)

            # Build INSERT ... SELECT depending on legacy columns
            event_expr = "event_id" if has_event else str(int(from_this_default))

            select_sql = f"""
                INSERT OR IGNORE INTO deathless_streaks__new
                    (character, count, event_id)
                SELECT
                    character,
                    count,
                    {event_expr}
                FROM deathless_streaks
            """
            c.execute(select_sql)

            c.execute("DROP TABLE IF EXISTS deathless_streaks")
            c.execute("ALTER TABLE deathless_streaks__new RENAME TO deathless_streaks")

        # If legacy glicko_ratings exists without composite PK, rebuild it to the new schema
        try:
            c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='glicko_ratings'")
            row = c.fetchone()
            ddl = row[0] if row else ""
        except Exception:
            ddl = ""

        needs_rebuild = False
        if ddl:
            normalized = ddl.replace("`", "").replace("\n", " ").lower()
            if "primary key (character, event_id)" not in normalized:
                needs_rebuild = True

        if needs_rebuild:
            # Detect available columns for legacy copy
            has_event = _table_has_column(conn, "glicko_ratings", "event_id")
            has_last_activity = _table_has_column(conn, "glicko_ratings", "last_activity")
            has_last_win = _table_has_column(conn, "glicko_ratings", "last_win")

            # Ensure default event exists and get its id for legacy rows
            from_this_default = get_default_event_id()

            c.execute("""
                CREATE TABLE IF NOT EXISTS glicko_ratings__new (
                    character TEXT NOT NULL,
                    rating REAL DEFAULT 1500,
                    rd REAL DEFAULT 350,
                    vol REAL DEFAULT 0.06,
                    last_activity TEXT,
                    event_id INTEGER NOT NULL,
                    PRIMARY KEY (character, event_id)
                )
            """)

            # Build INSERT ... SELECT depending on legacy columns
            last_expr = "NULL"
            if has_last_activity:
                last_expr = "last_activity"
            elif has_last_win:
                last_expr = "last_win"

            event_expr = "event_id" if has_event else str(int(from_this_default))

            select_sql = f"""
                INSERT OR IGNORE INTO glicko_ratings__new
                    (character, rating, rd, vol, last_activity, event_id)
                SELECT
                    character,
                    COALESCE(rating, 1500),
                    COALESCE(rd, 350),
                    COALESCE(vol, 0.06),
                    {last_expr},
                    {event_expr}
                FROM glicko_ratings
            """
            c.execute(select_sql)

            c.execute("DROP TABLE IF EXISTS glicko_ratings")
            c.execute("ALTER TABLE glicko_ratings__new RENAME TO glicko_ratings")

        # --- Indices to speed up queries ---
        c.execute("CREATE INDEX IF NOT EXISTS idx_frags_killer ON frags(killer)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_frags_victim ON frags(victim)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_frags_timestamp ON frags(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_frags_event ON frags(event_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_char_map_user ON character_map(discord_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_glicko_event_char ON glicko_ratings(event_id, character)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_event_channels_event ON event_channels(event_id)")

        # Helpful indices for new event-aware tables
        c.execute("CREATE INDEX IF NOT EXISTS idx_manual_character_event ON manual_adjustments(character, event_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_gh_character_event ON glicko_history(character, event_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ds_character_event ON deathless_streaks(character, event_id)")

        # --- Backfill NULL event_id to default event (id=1 typically) for legacy rows ---
        try:
            default_event_id = get_default_event_id()
        except Exception:
            default_event_id = 1

        try:
            c.execute("UPDATE frags SET event_id = ? WHERE event_id IS NULL", (default_event_id,))
        except Exception:
            pass
        try:
            c.execute("UPDATE manual_adjustments SET event_id = ? WHERE event_id IS NULL", (default_event_id,))
        except Exception:
            pass
        try:
            c.execute("UPDATE glicko_history SET event_id = ? WHERE event_id IS NULL", (default_event_id,))
        except Exception:
            pass
        try:
            c.execute("UPDATE deathless_streaks SET event_id = ? WHERE event_id IS NULL", (default_event_id,))
        except Exception:
            pass
        try:
            c.execute("UPDATE glicko_ratings SET event_id = ? WHERE event_id IS NULL", (default_event_id,))
        except Exception:
            pass

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

# --- Stats ---

def add_frag(killer: str, victim: str, channel_id: Optional[int] = None):
    now = datetime.now(timezone.utc)
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
        logging.exception(f"❌ Error when adding a frag: {e}")

def get_top_players(n=10, days=1):
    try:
        with sqlite3.connect(get_db_path()) as conn:
            c = conn.cursor()
            since = datetime.now(timezone.utc) - timedelta(days=days)
            c.execute("""
                SELECT killer, COUNT(*) as count FROM frags
                WHERE timestamp >= ?
                GROUP BY killer
                ORDER BY count DESC
                LIMIT ?
            """, (since, n))
            return c.fetchall()
    except sqlite3.Error as e:
        logging.exception(f"❌ Error getting top players: {e}")
        return []

# --- Linking ---

def link_character(character: str, discord_id: int):
    try:
        with sqlite3.connect(get_db_path()) as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO character_map (character, discord_id)
                VALUES (?, ?)
                ON CONFLICT(character) DO UPDATE SET discord_id=excluded.discord_id
            ''', (character, discord_id))
            conn.commit()
    except sqlite3.Error as e:
        logging.exception(f"❌ Error linking character {character} to user {discord_id}: {e}")
        raise

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

def increment_deathless_streak(character: str, event_id: Optional[int] = None) -> int:
    """
    Increases the series by 1 and returns a new value.
    """
    if event_id is None:
        event_id = get_default_event_id()
    current = get_deathless_streak(character, event_id)
    new_value = current + 1
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO deathless_streaks (character, count, event_id)
            VALUES (?, ?, ?)
        """, (character.lower(), new_value, event_id))
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
                c.execute("INSERT OR REPLACE INTO deathless_streaks (character, count, event_id) VALUES (?, ?, ?)", (killer, new_streak, event_id))
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
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM deathless_streaks")
        conn.commit()
        logging.info("🧹 Cleared deathless_streaks table on startup.")

# --- Adjustment ---

def get_total_wins(character: str, days: int = 7, event_id: Optional[int] = None) -> int:
    """
    Counts the total number of wins in N days, taking into account manual adjustments.
    """
    since = datetime.utcnow() - timedelta(days=days)
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        
        # Fragment wins
        if event_id is None:
            event_id = get_default_event_id()
        c.execute("""
            SELECT COUNT(*) FROM frags
            WHERE killer = ? AND timestamp >= ? AND event_id = ?
        """, (character.lower(), since, event_id))
        frag_wins = c.fetchone()[0] or 0

        # Manual adjustments
        c.execute("""
            SELECT SUM(adjustment) FROM manual_adjustments
            WHERE character = ? AND timestamp >= ? AND event_id = ?
        """, (character.lower(), since, event_id))
        manual_delta = c.fetchone()[0] or 0

        return frag_wins + manual_delta

def get_total_wins_for_user(discord_id: int, days: int = 7, event_id: Optional[int] = None) -> int:
    """
    Returns the total points of all the user's characters (frags + adjustments).
    """
    total = 0
    for character in get_user_characters(discord_id):
        total += get_total_wins(character, days=days, event_id=event_id)
    return total

def adjust_wins(character: str, delta: int, reason: Optional[str] = None, event_id: Optional[int] = None):
    """
    Adds a victory adjustment to manual_adjustments.
    """
    if event_id is None:
        event_id = get_default_event_id()
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO manual_adjustments (character, adjustment, reason, event_id)
            VALUES (?, ?, ?, ?)
        """, (character.lower(), delta, reason, event_id))
        conn.commit()
        logging.info(f"✏️\tManual win adjustment: {character} -> {delta} ({reason}) [event_id={event_id}]")

def get_win_sources(character: str, event_id: Optional[int] = None) -> tuple[int, int]:
    """
    Returns a tuple of (manual, natural) wins.
    """
    if event_id is None:
        event_id = get_default_event_id()
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT SUM(adjustment) FROM manual_adjustments WHERE character = ? AND event_id = ?", (character.lower(), event_id))
        manual = c.fetchone()[0] or 0

        c.execute("SELECT COUNT(*) FROM frags WHERE killer = ? AND event_id = ?", (character.lower(), event_id))
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
        cur = conn.execute("SELECT threshold, role_name FROM mmr_roles ORDER BY threshold DESC")
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

    now_iso = datetime.now(timezone.utc).isoformat()
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
        if event_id:
            c.execute("""
                SELECT MAX(timestamp) FROM frags
                WHERE (killer = ? OR victim = ?) AND event_id = ?
            """, (character.lower(), character.lower(), event_id))
        else:
            c.execute("""
                SELECT MAX(timestamp) FROM frags
                WHERE killer = ? OR victim = ?
            """, (character.lower(), character.lower()))
        result = c.fetchone()[0]
        if result:
            return datetime.fromisoformat(result).date()
        return None

def get_all_players(event_id: Optional[int] = None) -> set:
    """Return set of discord_ids (int) and unlinked character names (str) for the given event_id.
       If event_id is None -> return global set (backwards compatible).
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        if event_id:
            # characters that participated in this event
            c.execute("SELECT DISTINCT killer FROM frags WHERE event_id = ?", (event_id,))
            killers = {row[0].lower() for row in c.fetchall()}
            c.execute("SELECT DISTINCT victim FROM frags WHERE event_id = ?", (event_id,))
            victims = {row[0].lower() for row in c.fetchall()}
        else:
            c.execute("SELECT DISTINCT killer FROM frags")
            killers = {row[0].lower() for row in c.fetchall()}
            c.execute("SELECT DISTINCT victim FROM frags")
            victims = {row[0].lower() for row in c.fetchall()}

        all_chars = killers | victims

        # map characters -> discord_id (only those present in character_map)
        if not all_chars:
            return set()

        placeholders = ",".join("?" for _ in all_chars)
        q = f"SELECT character, discord_id FROM character_map WHERE character IN ({placeholders})"
        c.execute(q, tuple(all_chars))
        mapped = {row[0].lower(): row[1] for row in c.fetchall()}

        discord_ids = set(mapped.values())
        mapped_chars = set(mapped.keys())
        unlinked_chars = all_chars - mapped_chars

        return discord_ids | unlinked_chars

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

def recalculate_glicko_recent(days: int = 30, event_id: Optional[int] = None):
    """
    Rebuild Glicko-2 ratings based on all frags from the last N days.
    Used in /topmmr to get fresh rankings.
    """
    if event_id is None:
        event_id = get_default_event_id()
        
    since = datetime.utcnow() - timedelta(days=days)
    battles_by_day = defaultdict(list)

    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT killer, victim, timestamp FROM frags WHERE timestamp >= ? AND event_id = ? ORDER BY timestamp ASC", (since, event_id))
        rows = c.fetchall()

    for killer, victim, ts in rows:
        day = datetime.fromisoformat(ts).date()
        battles_by_day[day].append((killer.lower(), victim.lower()))

    all_players = {}
    current = min(battles_by_day) if battles_by_day else datetime.now(timezone.utc).date()
    end = max(battles_by_day) if battles_by_day else current

    while current <= end:
        fights = battles_by_day.get(current, [])
        participated = set()

        for killer, victim in fights:
            if killer not in all_players:
                all_players[killer] = Player(*get_glicko_rating_extended(killer, event_id)[:3])
            if victim not in all_players:
                all_players[victim] = Player(*get_glicko_rating_extended(victim, event_id)[:3])

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
            last_act = get_last_active_iso(name, event_id=event_id)
            set_glicko_rating(name, player.getRating(), player.getRd(), player._vol, event_id=event_id, last_activity=last_act)

# --- Events ---

def create_event(name: str, description: Optional[str] = None) -> int:
    """
    Create a new event. Raises ValueError if an event with the same name already exists.
    Returns the new event's id as int.
    """
    if not name or not name.strip():
        raise ValueError("Event name cannot be empty.")

    normalized = name.strip().lower()

    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        # Check uniqueness
        c.execute("SELECT id FROM events WHERE name = ?", (normalized,))
        if c.fetchone():
            raise ValueError(f"❌ Event `{normalized}` already exists.")

        # Insert
        c.execute("INSERT INTO events (name, description) VALUES (?, ?)", (normalized, description))
        conn.commit()

        # Explicitly fetch the id to avoid relying on lastrowid (type could be None)
        c.execute("SELECT id FROM events WHERE name = ?", (normalized,))
        row = c.fetchone()
        if not row:
            logging.error(f"Failed to create/find event '{normalized}' in DB after insert.")
            raise RuntimeError(f"Failed to create or fetch event '{normalized}'")
        return int(row[0])

def get_event_by_name(name: str) -> Optional[tuple]:
    """
    Return the event row (id, name, description, created_at) for the normalized event name,
    or None if not found.
    """
    if not name or not name.strip():
        return None

    normalized = name.strip().lower()
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, description, created_at FROM events WHERE name = ?", (normalized,))
        return c.fetchone()

def get_event_id_by_channel(channel_id: int) -> Optional[int]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT event_id FROM event_channels WHERE channel_id = ?", (int(channel_id),))
        row = c.fetchone()
        return row[0] if row else None

def set_event_channel(event_name: str, channel_id: int) -> bool:
    """
    Binds a channel to an existing event as a track+announcement.
    If the event does not exist, it triggers an exception.
    """
    event = get_event_by_name(event_name)
    if not event:
        raise ValueError(f"❌ Event `{event_name}` not found.")

    event_id = event[0]

    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()

        # Delete the old bindings of this channel (if any)
        c.execute("DELETE FROM event_channels WHERE channel_id = ?", (int(channel_id),))

        # Adding both bindings (track + announce)
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
    """
    Returns a list of events with a description and
    an associated announcement channel (if any).
    Format: (name, description, channel_id, is_default)
    """
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT e.name, e.description, ec.channel_id, 
                   CASE WHEN e.id = 1 THEN 1 ELSE 0 END as is_default
            FROM events e
            LEFT JOIN event_channels ec 
                   ON e.id = ec.event_id AND ec.channel_type = 'announce'
            ORDER BY e.created_at DESC
        """)
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

def get_event_channel(event_id: int, channel_type: str) -> Optional[int]:
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT channel_id FROM event_channels
            WHERE event_id = ? AND channel_type = ?
        """, (int(event_id), channel_type))
        row = c.fetchone()
        logging.debug(f"DEBUG get_event_channel(event_id={event_id}, channel_type={channel_type}) -> {row}")
        return int(row[0]) if row else None
