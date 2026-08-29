#!/usr/bin/env python3
"""
test_force.py - Test forzado para diagnosticar por qué no hay operaciones
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from backtesting.backtesting_force import BacktesterForce
from datetime import datetime, timedelta, timezone
import json
import pandas as pd

def main():
    print("🧪 Iniciando backtest FORZADO (siempre genera operaciones)...")
    
    config = Config()
    simbolos = ['EURUSD', 'GBPUSD']
    
    fecha_fin = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_inicio = fecha_fin - timedelta(days=15)
    
    print(f"📅 Rango: {fecha_inicio} → {fecha_fin}")
    print(f"📋 Símbolos: {simbolos}")
    print(f"⚠️  Este backtest FUERZA operaciones para diagnóstico")
    
    reportes_dir = Path("reportes")
    reportes_dir.mkdir(parents=True, exist_ok=True)
    
    backtester = BacktesterForce(
        config=config,
        simbolos=simbolos,
        capital_inicial=300.0,
        modo_depuracion=True,
        max_ops_dia=10,
        risk_per_trade=0.01,
    )
    
    print("\n▶️ Ejecutando backtest FORZADO...")
    resultados = backtester.run(fecha_inicio, fecha_fin)
    
    # Guardar reporte
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    reporte_path = reportes_dir / f"backtest_force_{timestamp}.json"
    backtester.guardar_reporte(reporte_path)
    print(f"✅ Reporte guardado: {reporte_path}")
    
    print("\n" + "=" * 60)
    print("📊 RESULTADOS DEL BACKTEST FORZADO")
    print("=" * 60)
    print(f"Total operaciones: {resultados.get('total_operaciones', 0)}")
    print(f"Win Rate: {resultados.get('win_rate', 0):.2f}%")
    print(f"Profit Factor: {resultados.get('profit_factor', 0):.2f}")
    print(f"Net Profit: ${resultados.get('net_profit', 0):.2f}")
    print(f"Total Return: {resultados.get('total_return', 0):.2f}%")
    print(f"Capital final: ${resultados.get('capital_final', 0):.2f}")
    
    if resultados.get('trades'):
        print(f"\n📊 Últimas 10 operaciones:")
        df = pd.DataFrame(resultados['trades'])
        for idx, row in df.tail(10).iterrows():
            print(f"  {row.get('simbolo')} {row.get('direccion')} | "
                  f"Entrada: {row.get('entrada', 0):.5f} | "
                  f"PnL: ${row.get('pnl', 0):.2f} | "
                  f"Motivo: {row.get('motivo_cierre', 'N/A')}")
    else:
        print("\n❌ NO SE EJECUTARON OPERACIONES - Problema en el flujo")
    
    print("=" * 60)

if __name__ == "__main__":
    main()