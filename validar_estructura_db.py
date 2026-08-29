#!/usr/bin/env python3
"""
validar_estructura_db.py - Muestra la estructura completa de la base de datos SQLite
"""

import sqlite3
from pathlib import Path
from datetime import datetime


def obtener_estructura_db(db_path: Path):
    """
    Muestra la estructura completa de la base de datos SQLite.
    """
    print("=" * 80)
    print(f"📊 VALIDACIÓN DE ESTRUCTURA DE BASE DE DATOS")
    print("=" * 80)
    print(f"📁 Base de datos: {db_path}")
    print(f"📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    if not db_path.exists():
        print(f"❌ ERROR: La base de datos no existe en {db_path}")
        return
    
    # Tamaño del archivo
    size_kb = db_path.stat().st_size / 1024
    print(f"📊 Tamaño: {size_kb:.2f} KB ({size_kb / 1024:.2f} MB)")
    print("=" * 80)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # ============================================================
    # 1. OBTENER LISTA DE TABLAS
    # ============================================================
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tablas = cursor.fetchall()
    
    print(f"\n📋 TABLAS ENCONTRADAS ({len(tablas)}):")
    print("-" * 40)
    
    for tabla in tablas:
        nombre = tabla[0]
        print(f"  📌 {nombre}")
    
    print("-" * 40)
    
    # ============================================================
    # 2. DETALLE DE CADA TABLA
    # ============================================================
    
    for tabla in tablas:
        nombre = tabla[0]
        print(f"\n{'='*60}")
        print(f"📌 TABLA: {nombre}")
        print('='*60)
        
        # Obtener columnas
        cursor.execute(f"PRAGMA table_info({nombre})")
        columnas = cursor.fetchall()
        
        print(f"📋 Columnas ({len(columnas)}):")
        for col in columnas:
            cid = col[0]
            name = col[1]
            type_ = col[2]
            notnull = col[3]
            dflt_value = col[4]
            pk = col[5]
            
            pk_str = "🔑" if pk else "  "
            notnull_str = "NOT NULL" if notnull else "NULLABLE"
            dflt_str = f" DEFAULT {dflt_value}" if dflt_value is not None else ""
            
            print(f"    {pk_str} {cid}. {name} ({type_}) {notnull_str}{dflt_str}")
        
        # Obtener índices
        cursor.execute(f"PRAGMA index_list({nombre})")
        indices = cursor.fetchall()
        
        if indices:
            print(f"\n📊 Índices ({len(indices)}):")
            for idx in indices:
                idx_name = idx[1]
                idx_unique = "UNIQUE" if idx[2] else "NON-UNIQUE"
                print(f"    • {idx_name} ({idx_unique})")
                
                # Detalle del índice
                cursor.execute(f"PRAGMA index_info({idx_name})")
                idx_info = cursor.fetchall()
                for info in idx_info:
                    print(f"        - Columna: {info[2]} (seq: {info[1]})")
    
    # ============================================================
    # 3. VERIFICACIÓN DE COLUMNAS CRÍTICAS
    # ============================================================
    
    print(f"\n{'='*80}")
    print("🔍 VERIFICACIÓN DE COLUMNAS CRÍTICAS")
    print('='*80)
    
    # Verificar tabla niveles
    cursor.execute("PRAGMA table_info(niveles)")
    niveles_cols = {col[1] for col in cursor.fetchall()}
    
    niveles_requeridas = {'id', 'simbolo', 'tipo', 'precio', 'hits', 'fuerza', 'timeframe', 'ultima_fecha'}
    niveles_faltantes = niveles_requeridas - niveles_cols
    niveles_extra = niveles_cols - niveles_requeridas
    
    print(f"\n📌 TABLA niveles:")
    if not niveles_faltantes:
        print(f"  ✅ TODAS las columnas requeridas están presentes")
        print(f"    ✓ {', '.join(sorted(niveles_requeridas))}")
    else:
        print(f"  ❌ FALTAN columnas: {', '.join(sorted(niveles_faltantes))}")
    
    if niveles_extra:
        print(f"  ⚠️ Columnas extra encontradas: {', '.join(sorted(niveles_extra))}")
    
    # Verificar tabla operaciones
    cursor.execute("PRAGMA table_info(operaciones)")
    ops_cols = {col[1] for col in cursor.fetchall()}
    
    ops_requeridas = {
        'id', 'ticket', 'simbolo', 'direccion', 'entrada', 'salida', 'lotes',
        'sl', 'tp', 'tp2', 'timestamp', 'ganancia', 'comision', 'swap',
        'estado', 'motivo_cierre', 'puntuacion', 'es_sniper', 'es_demo',
        'modo', 'contexto_apertura', 'analisis_fase1'
    }
    ops_faltantes = ops_requeridas - ops_cols
    
    print(f"\n📌 TABLA operaciones:")
    if not ops_faltantes:
        print(f"  ✅ TODAS las columnas requeridas están presentes")
    else:
        print(f"  ❌ FALTAN columnas: {', '.join(sorted(ops_faltantes))}")
    
    # Verificar tabla regimenes
    cursor.execute("PRAGMA table_info(regimenes)")
    reg_cols = {col[1] for col in cursor.fetchall()}
    
    reg_requeridas = {
        'simbolo', 'regimen', 'confianza', 'adx_h4', 'adx_h1',
        'er_kaufman', 'bb_width_pct', 'atr_pct', 'estructura_swings',
        'direccion_favor', 'timestamp'
    }
    reg_faltantes = reg_requeridas - reg_cols
    
    print(f"\n📌 TABLA regimenes:")
    if not reg_faltantes:
        print(f"  ✅ TODAS las columnas requeridas están presentes")
    else:
        print(f"  ❌ FALTAN columnas: {', '.join(sorted(reg_faltantes))}")
    
    # ============================================================
    # 4. ESTADÍSTICAS DE DATOS
    # ============================================================
    
    print(f"\n{'='*80}")
    print("📊 ESTADÍSTICAS DE DATOS")
    print('='*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM niveles")
        count = cursor.fetchone()[0]
        print(f"  📌 niveles: {count} registros")
    except Exception:
        print(f"  ⚠️ niveles: No se puede contar (puede no existir)")
    
    try:
        cursor.execute("SELECT COUNT(*) FROM operaciones")
        count = cursor.fetchone()[0]
        print(f"  📌 operaciones: {count} registros")
    except Exception:
        print(f"  ⚠️ operaciones: No se puede contar")
    
    try:
        cursor.execute("SELECT COUNT(*) FROM regimenes")
        count = cursor.fetchone()[0]
        print(f"  📌 regimenes: {count} registros")
    except Exception:
        print(f"  ⚠️ regimenes: No se puede contar")
    
    conn.close()
    print(f"\n{'='*80}")
    print("✅ VALIDACIÓN COMPLETADA")
    print("=" * 80)


if __name__ == "__main__":
    db_path = Path("data/bot_data.db")
    obtener_estructura_db(db_path)