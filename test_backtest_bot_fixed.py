#!/usr/bin/env python3
"""
test_backtest_bot_fixed.py - Backtest del BOT REAL con correcciones
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from backtesting.backtesting_bot import BacktesterBot
from datetime import datetime, timedelta, timezone
import json
import pandas as pd

def main():
    print("🧪 Iniciando backtest del BOT REAL CORREGIDO...")
    
    config = Config()
    simbolos = ['EURUSD', 'GBPUSD']
    
    fecha_fin = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_inicio = fecha_fin - timedelta(days=15)
    
    print(f"📅 Rango: {fecha_inicio} → {fecha_fin}")
    print(f"📋 Símbolos: {simbolos}")
    
    reportes_dir = Path("reportes")
    reportes_dir.mkdir(parents=True, exist_ok=True)
    
    backtester = BacktesterBot(
        config=config,
        simbolos=simbolos,
        capital_inicial=300.0,
        modo_depuracion=True,
        max_lote_absoluto=0.005,
        dias_warmup=5,
        umbral_fase_1=20,       # Reducido
        max_simultaneas=3,      # Aumentado
        max_ops_dia=10,         # Aumentado
        risk_per_trade=0.01,
        use_ml=False,
    )
    
    print("▶️ Ejecutando backtest del BOT REAL CORREGIDO...")
    resultados = backtester.run(fecha_inicio, fecha_fin)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    reporte_path = reportes_dir / f"backtest_bot_fixed_{timestamp}.json"
    backtester.guardar_reporte(reporte_path)
    print(f"✅ Reporte guardado: {reporte_path}")
    
    if resultados.get('trades'):
        df_trades = pd.DataFrame(resultados['trades'])
        trades_path = reportes_dir / f"trades_bot_fixed_{timestamp}.csv"
        df_trades.to_csv(trades_path, index=False)
        print(f"✅ Trades guardados: {trades_path}")
    
    print("\n" + "=" * 60)
    print("📊 RESULTADOS DEL BACKTEST BOT REAL CORREGIDO")
    print("=" * 60)
    print(f"Total operaciones: {resultados.get('total_operaciones', 0)}")
    print(f"Win Rate: {resultados.get('win_rate', 0):.2f}%")
    print(f"Profit Factor: {resultados.get('profit_factor', 0):.2f}")
    print(f"Net Profit: ${resultados.get('net_profit', 0):.2f}")
    print(f"Total Return: {resultados.get('total_return', 0):.2f}%")
    print(f"Max Drawdown: {resultados.get('max_drawdown', 0):.2f}%")
    print(f"Capital final: ${resultados.get('capital_final', 0):.2f}")
    
    if resultados.get('trades'):
        df = pd.DataFrame(resultados['trades'])
        print(f"\n📊 Últimas 10 operaciones:")
        for idx, row in df.tail(10).iterrows():
            print(f"  {row.get('simbolo')} {row.get('direccion')} | "
                  f"Score: {row.get('score', 0):.0f} | "
                  f"PnL: ${row.get('pnl', 0):.2f} | "
                  f"Motivo: {row.get('motivo_cierre', 'N/A')}")
        
        print(f"\n📊 Distribución por modo:")
        for modo in df['modo'].unique():
            df_m = df[df['modo'] == modo]
            total = len(df_m)
            ganadoras = len(df_m[df_m['pnl'] > 0])
            pnl_total = df_m['pnl'].sum()
            print(f"  {modo}: {total} ops | {ganadoras/total*100:.1f}% win | PnL: ${pnl_total:.2f}")
    
    print("=" * 60)

if __name__ == "__main__":
    main()