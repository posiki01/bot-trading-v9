# test_adx.py
import pandas as pd
import numpy as np
from analysis.regimen_indicadores import RegimenIndicadores

# Cargar un DF real desde SQLite
from data.almacenamiento_sqlite import AlmacenamientoSQLite
from pathlib import Path

alm = AlmacenamientoSQLite(base_dir=Path('data'), modo_backup=False)
df = alm.obtener_datos_historicos('EURUSD', 60)
alm.cerrar()

print(f"Velas: {len(df)}")
adx = RegimenIndicadores.calcular_adx(df)
print(f"ADX EURUSD: {adx:.2f}")

# Manual: ¿qué debería dar?
high = df['High']
low = df['Low']
close = df['Close']
tr = pd.concat([
    high - low,
    (high - close.shift()).abs(),
    (low - close.shift()).abs()
], axis=1).max(axis=1)
atr = tr.rolling(14).mean().iloc[-1]
print(f"ATR: {atr:.5f}")
print(f"Rango últimas 14 velas: {(high.iloc[-14:].max() - low.iloc[-14:].min()):.5f}")
print(f"Rango últimas 100 velas: {(high.iloc[-100:].max() - low.iloc[-100:].min()):.5f}")