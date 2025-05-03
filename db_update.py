import sqlite3

def update_database(db_path: str):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print("🔧 Приведение значений к нижнему регистру...")

    # Update frags.killer
    c.execute("SELECT id, killer FROM frags")
    for row_id, name in c.fetchall():
        if name:
            c.execute("UPDATE frags SET killer = ? WHERE id = ?", (name.lower(), row_id))

    # Update of frags.victim
    c.execute("SELECT id, victim FROM frags")
    for row_id, name in c.fetchall():
        if name:
            c.execute("UPDATE frags SET victim = ? WHERE id = ?", (name.lower(), row_id))

    # Creating a character_map if it doesn't exist
    c.execute("""
        CREATE TABLE IF NOT EXISTS character_map (
            character TEXT PRIMARY KEY,
            discord_id INTEGER NOT NULL
        )
    """)

    # Reducing character_map.character to lowercase
    c.execute("SELECT rowid, character FROM character_map")
    for row_id, name in c.fetchall():
        if name:
            c.execute("UPDATE character_map SET character = ? WHERE rowid = ?", (name.lower(), row_id))

    conn.commit()
    conn.close()
    print("✅ База данных успешно обновлена.")

if __name__ == "__main__":
    update_database("frags.db")
