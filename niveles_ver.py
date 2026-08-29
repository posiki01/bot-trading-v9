from data.almacenamiento_sqlite import AlmacenamientoSQLite
import sqlite3

almacen = AlmacenamientoSQLite()
conn = sqlite3.connect(almacen.db_path)
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(niveles)")
print("Columnas en tabla niveles:")
for col in cursor.fetchall():
    print(col)