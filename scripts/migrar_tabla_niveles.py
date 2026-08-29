#!/usr/bin/env python3
"""
scripts/migrar_tabla_niveles.py
Añade timeframe a la restricción UNIQUE de la tabla niveles.
Ejecutar una sola vez.
"""

import sqlite3
import logging
from pathlib import Path

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('MigrarNiveles')


def migrar():
    """
    Migra la tabla niveles para incluir timeframe en la restricción UNIQUE.
    """
    # Ruta de la base de datos
    db_path = Path(__file__).parent.parent / "data" / "bot_data.db"
    
    if not db_path.exists():
        logger.error(f"❌ No se encuentra la base de datos: {db_path}")
        return False
    
    logger.info(f"📁 Base de datos: {db_path}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # 1. Verificar estructura actual
        cursor.execute("PRAGMA table_info(niveles)")
        columnas = cursor.fetchall()
        logger.info(f"📊 Columnas actuales: {[c[1] for c in columnas]}")
        
        # Verificar si ya existe la columna timeframe
        tiene_timeframe = any(c[1] == 'timeframe' for c in columnas)
        
        if tiene_timeframe:
            logger.info("✅ La columna 'timeframe' ya existe. Verificando restricción UNIQUE...")
            
            # Verificar la restricción UNIQUE actual
            cursor.execute("PRAGMA index_list(niveles)")
            indices = cursor.fetchall()
            logger.info(f"📊 Índices actuales: {indices}")
            
            # Si ya tiene UNIQUE con timeframe, no hacer nada
            cursor.execute("""
                SELECT COUNT(*) FROM sqlite_master 
                WHERE type='index' AND sql LIKE '%UNIQUE%' AND sql LIKE '%timeframe%'
            """)
            if cursor.fetchone()[0] > 0:
                logger.info("✅ La restricción UNIQUE ya incluye timeframe. No se requiere migración.")
                conn.close()
                return True
        
        # 2. Crear tabla temporal con la nueva estructura
        logger.info("🔄 Creando tabla temporal con nueva estructura...")
        cursor.execute("""
            CREATE TABLE niveles_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                simbolo TEXT NOT NULL,
                tipo TEXT NOT NULL,
                precio REAL NOT NULL,
                hits INTEGER DEFAULT 0,
                fuerza INTEGER DEFAULT 0,
                timeframe TEXT NOT NULL,
                ultima_fecha TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(simbolo, tipo, precio, timeframe)
            )
        """)
        
        # 3. Migrar datos existentes (con timeframe='H1' por defecto)
        logger.info("🔄 Migrando datos existentes...")
        cursor.execute("""
            INSERT INTO niveles_new (simbolo, tipo, precio, hits, fuerza, ultima_fecha, timeframe)
            SELECT simbolo, tipo, precio, hits, fuerza, ultima_fecha, 'H1'
            FROM niveles
        """)
        registros_migrados = cursor.rowcount
        logger.info(f"✅ {registros_migrados} registros migrados")
        
        # 4. Reemplazar tabla antigua
        logger.info("🔄 Reemplazando tabla antigua...")
        cursor.execute("DROP TABLE niveles")
        cursor.execute("ALTER TABLE niveles_new RENAME TO niveles")
        
        # 5. Recrear índices
        logger.info("🔄 Recreando índices...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_niv_simbolo ON niveles(simbolo)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_niv_precio ON niveles(precio)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_niv_tipo ON niveles(tipo)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_niv_timeframe ON niveles(timeframe)")
        
        conn.commit()
        logger.info("✅ Migración completada exitosamente")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error en migración: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    if migrar():
        logger.info("✅ Tabla niveles actualizada con timeframe en UNIQUE")
    else:
        logger.error("❌ Migración falló")