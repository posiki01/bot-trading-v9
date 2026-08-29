#!/usr/bin/env python3
"""
precargar_datos_iniciales.py
Precarga datos históricos iniciales en SQLite para todos los símbolos.
Esta es la primera carga (un mes completo) que se usa como base.
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Añadir el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.almacenamiento_sqlite import AlmacenamientoSQLite

# Configuración
SIMBOLOS = [
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF',
    'EURJPY', 'GBPJPY', 'AUDJPY', 'EURGBP',
    'EURNZD', 'GBPAUD', 'EURCHF', 'GBPCHF',  # ✅ AÑADIR ESTOS
    'US30', 'NAS100', 'US500',
    'XAUUSD', 'XAGUSD',
    'BTCUSD', 'ETHUSD', 'SOLUSD'
]

TIMEFRAMES = [
    (mt5.TIMEFRAME_H1, 60),    # H1
    (mt5.TIMEFRAME_H4, 240),   # H4
    (mt5.TIMEFRAME_D1, 1440),  # D1
    (mt5.TIMEFRAME_M15, 15),   # M15
    (mt5.TIMEFRAME_M5, 5),     # M5
]

DIAS_HISTORIA = 60  # 60 días para tener datos suficientes

def main():
    print("🚀 Iniciando precarga de datos históricos iniciales en SQLite...")
    
    # 1. Conectar a MT5
    if not mt5.initialize():
        print("❌ No se pudo conectar a MT5")
        return
    
    account = mt5.account_info()
    if account:
        print(f"✅ Conectado - Balance: ${account.balance:.2f}")
    
    # 2. Inicializar almacenamiento SQLite
    almacen = AlmacenamientoSQLite()
    print(f"✅ Almacenamiento SQLite inicializado")
    
    # 3. Calcular fechas
    fecha_desde = datetime.now() - timedelta(days=DIAS_HISTORIA)
    fecha_hasta = datetime.now()
    print(f"📅 Rango: {fecha_desde.strftime('%Y-%m-%d')} → {fecha_hasta.strftime('%Y-%m-%d')}")
    
    # 4. Descargar datos para cada símbolo y timeframe
    total_descargas = 0
    total_velas = 0
    
    for simbolo in SIMBOLOS:
        print(f"\n📥 Procesando {simbolo}...")
        
        # Verificar que el símbolo esté disponible
        if not mt5.symbol_select(simbolo, True):
            print(f"⚠️ {simbolo}: No se pudo seleccionar en Market Watch")
            continue
        
        for tf_mt5, tf_int in TIMEFRAMES:
            print(f"  📥 Timeframe {tf_int}min...")
            
            # Descargar datos con copy_rates_range
            rates = mt5.copy_rates_range(simbolo, tf_mt5, fecha_desde, fecha_hasta)
            
            if rates is None or len(rates) == 0:
                print(f"  ⚠️ {simbolo} TF{tf_int}: No se obtuvieron datos")
                continue
            
            # Convertir a DataFrame
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low',
                'close': 'Close', 'tick_volume': 'Volume'
            }, inplace=True)
            
            # Guardar en SQLite
            almacen.guardar_datos_historicos(simbolo, tf_int, df)
            
            total_descargas += 1
            total_velas += len(df)
            print(f"  ✅ {simbolo} TF{tf_int}: {len(df)} velas guardadas en SQLite")
    
    # 5. Desconectar de MT5
    mt5.shutdown()
    
    print(f"\n✅ PRECARGA INICIAL COMPLETADA")
    print(f"📊 Total: {total_descargas} descargas, {total_velas} velas")
    print(f"📁 Base de datos: {almacen.db_path}")

if __name__ == "__main__":
    main()