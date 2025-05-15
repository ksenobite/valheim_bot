# -*- coding: utf-8 -*-

# streaks.py

from collections import defaultdict
from datetime import datetime
import logging

# Конфигурация стилей текстовых анонсов для deathless streaks
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

# Словарь активных серий: killer_name -> {"count": int, "last_kill": datetime}
active_streaks = defaultdict(lambda: {"count": 0, "last_kill": None})

def handle_kill(killer: str, victim: str):
    """Обновляет серию побед."""
    killer = killer.lower()
    victim = victim.lower()

    # Сбросить серию жертвы
    if victim in active_streaks:
        logging.info(f"🩸 Deathless streak reset: {victim}")
        del active_streaks[victim]

    # Обновить серию убийцы
    active_streaks[killer]["count"] += 1
    active_streaks[killer]["last_kill"] = datetime.utcnow()

    return active_streaks[killer]["count"]


def get_streak_announce(count: int, style: str = "classic"):
    """Получить стиль для текущей deathless streak."""
    config = DEATHLESS_STYLES.get(style, {})
    return config.get(count, None)


def reset_all_streaks():
    """Полный сброс всех серий — например, при рестарте бота"""
    active_streaks.clear()
