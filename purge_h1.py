# purge_h1.py
import sqlite3
from pathlib import Path

db = Path('data') / 'bot_data.db'
conn = sqlite3.connect(str(db))
cursor = conn.cursor()

cursor.execute("""
    SELECT name FROM sqlite_master
    WHERE type='table' AND name LIKE 'historico_%_60'
""")
tablas = [r[0] for r in cursor.fetchall()]

print(f"Tablas H1 a borrar: {len(tablas)}")
for t in tablas:
    cursor.execute(f'DROP TABLE "{t}"')
    print(f"  ✅ {t}")

conn.commit()
conn.close()
print(f"\n✅ {len(tablas)} tablas H1 eliminadas")
print("Reinicia el bot con: python main.py")