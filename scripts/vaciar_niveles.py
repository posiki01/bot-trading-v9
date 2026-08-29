#!/usr/bin/env python3
"""
scripts/vaciar_niveles.py
Vacia la tabla niveles de SQLite.
Ejecutar antes de la precarga.
"""

import sqlite3
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('VaciarNiveles')

def vaciar():
    db_path = Path(__file__).parent.parent / "data" / "bot_data.db"
    
    if not db_path.exists():
        logger.error(f"❌ No se encuentra la base de datos: {db_path}")
        return False
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM niveles")
        conn.commit()
        logger.info(f"✅ Tabla niveles vaciada: {cursor.rowcount} registros eliminados")
        return True
    except Exception as e:
        logger.error(f"❌ Error al vaciar: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    vaciar()