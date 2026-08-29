#!/usr/bin/env python3
"""
scripts/verificar_estructura.py
Verifica la estructura de la tabla niveles después de la migración.
"""

import sqlite3
from pathlib import Path

def verificar():
    db_path = Path(__file__).parent.parent / "data" / "bot_data.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Verificar columnas
    cursor.execute("PRAGMA table_info(niveles)")
    columnas = cursor.fetchall()
    print("📊 Columnas:")
    for col in columnas:
        print(f"   {col[1]} ({col[2]})")
    
    # Verificar restricción UNIQUE
    cursor.execute("PRAGMA index_list(niveles)")
    indices = cursor.fetchall()
    print("\n📊 Índices:")
    for idx in indices:
        print(f"   {idx[1]} ({idx[2]})")
    
    conn.close()

if __name__ == "__main__":
    verificar()