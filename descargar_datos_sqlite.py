#!/usr/bin/env python3
"""
descargar_datos_sqlite.py
Descarga datos históricos de MT5 y los guarda en SQLite.
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from data.almacenamiento_sqlite import AlmacenamientoSQLite

# Configuración
SIMBOLOS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 
            'EURJPY', 'GBPJPY', 'AUDJPY', 'EURGBP', 'US30', 'NAS100', 'US500', 
            'XAUUSD', 'XAGUSD', 'BTCUSD', 'ETHUSD', 'SOLUSD']

TIMEFRAME = mt5.TIMEFRAME_H1  # H1
N_VELAS = 250
DIAS_HISTORIA = 30

def main():
    print("🚀 Iniciando descarga de datos históricos...")
    
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
    
    # 4. Descargar datos para cada símbolo
    for simbolo in SIMBOLOS:
        print(f"\n📥 Descargando {simbolo}...")
        
        # Verificar que el símbolo esté disponible
        if not mt5.symbol_select(simbolo, True):
            print(f"⚠️ {simbolo}: No se pudo seleccionar en Market Watch")
            continue
        
        # Descargar datos con copy_rates_range
        rates = mt5.copy_rates_range(simbolo, TIMEFRAME, fecha_desde, fecha_hasta)
        
        if rates is None or len(rates) == 0:
            print(f"⚠️ {simbolo}: No se obtuvieron datos de MT5")
            continue
        
        # Convertir a DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'tick_volume': 'Volume'
        }, inplace=True)
        
        # Guardar en SQLite (a través de la caché del orquestador)
        # Nota: AlmacenamientoSQLite no tiene un método directo para guardar DataFrames,
        # así que guardamos en un archivo CSV para usarlo después.
        
        csv_path = Path("data/cache") / f"{simbolo}_H1.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path)
        print(f"✅ {simbolo}: {len(df)} velas guardadas en {csv_path}")
    
    # 5. Desconectar de MT5
    mt5.shutdown()
    print("\n✅ Descarga completada")
    print("📁 Los datos están en: data/cache/*_H1.csv")

if __name__ == "__main__":
    main()