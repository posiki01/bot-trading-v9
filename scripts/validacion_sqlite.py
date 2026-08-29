#!/usr/bin/env python3
"""
validacion_sqlite.py - Validación solo de SQLite (sin dependencias de core)
"""

import sys
import os
from pathlib import Path

# Agregar el directorio raíz
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from data.almacenamiento_sqlite import AlmacenamientoSQLite

def validar_sqlite():
    print("🚀 Validando SQLite...")
    print("=" * 60)
    
    almacen = AlmacenamientoSQLite()
    
    # 1. Verificar que la base de datos existe
    db_path = almacen.db_path
    print(f"📁 Base de datos: {db_path}")
    
    if not db_path.exists():
        print("❌ La base de datos NO existe")
        return
    
    size_kb = db_path.stat().st_size / 1024
    print(f"📊 Tamaño: {size_kb:.1f} KB")
    
    # 2. Verificar que hay datos
    simbolos = ['EURUSD', 'AUDUSD', 'XAUUSD', 'USDJPY']
    
    for simbolo in simbolos:
        try:
            niveles = almacen.obtener_niveles(simbolo)
            print(f"\n📊 {simbolo}:")
            print(f"   Soportes: {len(niveles.get('soportes', []))}")
            print(f"   Resistencias: {len(niveles.get('resistencias', []))}")
            
            # Mostrar primeros 3
            if niveles.get('soportes'):
                print("   Top soportes:")
                for i, s in enumerate(niveles['soportes'][:3]):
                    print(f"      {i+1}. {s['precio']:.5f} (hits: {s['hits']})")
            
            if niveles.get('resistencias'):
                print("   Top resistencias:")
                for i, r in enumerate(niveles['resistencias'][:3]):
                    print(f"      {i+1}. {r['precio']:.5f} (hits: {r['hits']})")
                    
        except Exception as e:
            print(f"❌ Error en {simbolo}: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Validación completada")

if __name__ == "__main__":
    validar_sqlite()