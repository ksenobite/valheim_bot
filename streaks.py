# -*- coding: utf-8 -*-

# streaks.py

from collections import defaultdict
from datetime import datetime
import logging

# Configuration of text announcement styles for deathless streaks
DEATHLESS_STYLES = {
    "classic": {
        3: {"title": "⚔️ On a Killing Spree!", "emojis": "🔥"},
        5: {"title": "🔥 Unstoppable!", "emojis": "⚡🔥"},
        7: {"title": "💀 Dominating!", "emojis": "💀💀"},
        10: {"title": "👑 Godlike!", "emojis": "👑🔥👑"},
    },
    "epic": {
        3: {"title": "⚡ Battle Momentum", "emojis": "⚔️⚔️"},
        5: {"title": "🔥 Storm Unleashed", "emojis": "🔥🌪️"},
        7: {"title": "💥 War Machine", "emojis": "💀🔥💀"},
        10: {"title": "👑 Immortal", "emojis": "👑💥👑"},
    },
    "tournament": {
        3: {"title": "⚡ 3 Kills — No Death", "emojis": "⚡"},
        5: {"title": "⚡ 5 Kills — No Death", "emojis": "⚡⚡"},
        7: {"title": "⚡ 7 Kills — No Death", "emojis": "⚡⚡⚡"},
        10: {"title": "⚡ 10 Kills — Still Standing", "emojis": "⚡⚡⚡⚡"},
    }
}

# Dictionary of active episodes: killer_name -> {"count": int, "last_kill": datetime}
active_streaks = defaultdict(lambda: {"count": 0, "last_kill": None})

def handle_kill(killer: str, victim: str):
    """Updates the winning streak."""
    killer = killer.lower()
    victim = victim.lower()

    # Reset the victim's series
    if victim in active_streaks:
        logging.info(f"🩸 Deathless streak reset: {victim}")
        del active_streaks[victim]

    # Update the killer series
    active_streaks[killer]["count"] += 1
    active_streaks[killer]["last_kill"] = datetime.utcnow()

    return active_streaks[killer]["count"]


def get_streak_announce(count: int, style: str = "classic"):
    """Get the style for the current deathless streak."""
    config = DEATHLESS_STYLES.get(style, {})
    return config.get(count, None)


def reset_all_streaks():
    """Full reset of all episodes — for example, when restarting the bot"""
    active_streaks.clear()
