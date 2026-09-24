# borrar_h1.py
"""
Borra SOLO las tablas H1 (timeframe 60) de SQLite para forzar reconstrucción.
Preserva: H4, D1, M5, M15, config, niveles, operaciones.
"""

import sqlite3
from pathlib import Path

db_path = Path('data') / 'bot_data.db'

if not db_path.exists():
    print(f"❌ No existe: {db_path}")
    raise SystemExit(1)

print(f"📁 DB: {db_path.absolute()}")
print(f"📦 Tamaño: {db_path.stat().st_size / 1024:.1f} KB")

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# Listar tablas H1
cursor.execute("""
    SELECT name FROM sqlite_master
    WHERE type='table' AND name LIKE 'historico_%_60'
""")
tablas = [row[0] for row in cursor.fetchall()]

print(f"\n📋 Tablas H1 encontradas: {len(tablas)}")
for t in tablas:
    # Contar filas
    try:
        cursor.execute(f'SELECT COUNT(*) FROM "{t}"')
        count = cursor.fetchone()[0]
        print(f"   {t}: {count} velas")
    except Exception as e:
        print(f"   {t}: error contando ({e})")

if not tablas:
    print("\n✅ No hay tablas H1 que borrar")
    conn.close()
    raise SystemExit(0)

# Confirmar
print(f"\n⚠️  Se van a borrar {len(tablas)} tablas H1")
print("   (H4, D1, M5, M15 y todo lo demás se preserva)")
respuesta = input("¿Continuar? (escribe SI): ").strip()

if respuesta != 'SI':
    print("❌ Cancelado")
    conn.close()
    raise SystemExit(0)

# Borrar
for t in tablas:
    cursor.execute(f'DROP TABLE "{t}"')

conn.commit()
conn.close()

print(f"\n✅ {len(tablas)} tablas H1 eliminadas")
print("\n👉 Ahora reinicia el bot:")
print("   python main.py")
print("\nEl bot reconstruirá H1 desde M5 fresco automáticamente.")