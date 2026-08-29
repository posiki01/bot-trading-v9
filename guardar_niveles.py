#!/usr/bin/env python3
"""
guardar_niveles.py - Guarda niveles de soporte/resistencia en SQLite
CORREGIDO: Conexión MT5 explícita, manejo de errores
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from core.orquestador import Orquestador
from data.almacenamiento_sqlite import AlmacenamientoSQLite


def guardar_niveles():
    print("🚀 INICIANDO GUARDADO DE NIVELES")
    print("=" * 60)
    
    # 1. Crear orquestador y conectar a MT5
    print("🔌 Conectando a MT5...")
    bot = Orquestador(modo_depuracion=True)
    
    if not bot.mt5.conectar():
        print("❌ No se pudo conectar a MT5")
        return
    
    print("✅ Conectado a MT5")
    
    # 2. Obtener datos H1 para EURUSD
    simbolo = 'EURUSD'
    print(f"\n📥 Obteniendo datos H1 para {simbolo}...")
    
    df_h1 = bot.mt5.obtener_datos(simbolo, n_velas=500, timeframe=60)
    
    if df_h1 is None or df_h1.empty:
        print(f"❌ No se pudieron obtener datos para {simbolo}")
        bot.mt5.desconectar()
        return
    
    print(f"✅ {len(df_h1)} velas obtenidas")
    print(f"   Último precio: {df_h1['Close'].iloc[-1]:.5f}")
    
    # 3. Detectar niveles
    print("\n🔍 Detectando niveles...")
    precio_actual = df_h1['Close'].iloc[-1]
    
    niveles = bot.nivel_tracker.detectar_y_actualizar_niveles(
        simbolo=simbolo,
        df=df_h1,
        precio_actual=precio_actual
    )
    
    soportes = niveles.get('soportes', [])
    resistencias = niveles.get('resistencias', [])
    
    print(f"📊 Niveles detectados:")
    print(f"   Soportes: {len(soportes)}")
    for i, s in enumerate(soportes[:5]):
        if isinstance(s, dict):
            print(f"      {i+1}. {s['precio']:.5f} (hits: {s.get('hits', 0)})")
        else:
            print(f"      {i+1}. {s:.5f}")
    
    print(f"   Resistencias: {len(resistencias)}")
    for i, r in enumerate(resistencias[:5]):
        if isinstance(r, dict):
            print(f"      {i+1}. {r['precio']:.5f} (hits: {r.get('hits', 0)})")
        else:
            print(f"      {i+1}. {r:.5f}")
    
    # 4. Guardar en SQLite
    print("\n💾 Guardando niveles en SQLite...")
    almacen = AlmacenamientoSQLite()
    
    try:
        almacen.guardar_niveles(
            simbolo=simbolo,
            soportes=soportes,
            resistencias=resistencias,
            timeframe='H1'
        )
        print(f"✅ Niveles guardados correctamente en SQLite para {simbolo}")
    except Exception as e:
        print(f"❌ Error guardando niveles: {e}")
    
    # 5. Verificar
    print("\n🔍 Verificando niveles guardados...")
    niveles_sqlite = almacen.obtener_niveles(simbolo)
    
    print(f"📊 Niveles en SQLite para {simbolo}:")
    print(f"   Soportes: {len(niveles_sqlite['soportes'])}")
    for i, s in enumerate(niveles_sqlite['soportes'][:5]):
        print(f"      {i+1}. {s['precio']:.5f} (hits: {s['hits']}, TF: {s.get('timeframe', 'N/A')})")
    
    print(f"   Resistencias: {len(niveles_sqlite['resistencias'])}")
    for i, r in enumerate(niveles_sqlite['resistencias'][:5]):
        print(f"      {i+1}. {r['precio']:.5f} (hits: {r['hits']}, TF: {r.get('timeframe', 'N/A')})")
    
    # 6. Desconectar
    bot.mt5.desconectar()
    print("\n✅ Guardado de niveles completado")


if __name__ == "__main__":
    guardar_niveles()