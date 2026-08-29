#!/usr/bin/env python3
"""
test_backtest_bot.py - Backtest usando el BOT REAL
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
    print("🧪 Iniciando backtest con el BOT REAL...")
    
    config = Config()
    simbolos = ['EURUSD', 'GBPUSD']
    
    fecha_fin = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_inicio = fecha_fin - timedelta(days=30)
    
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
        dias_warmup=7,
        umbral_fase_1=30,
        max_simultaneas=2,
        max_ops_dia=5,
        risk_per_trade=0.01,
        use_ml=False,
    )
    
    print("▶️ Ejecutando backtest con el BOT REAL...")
    resultados = backtester.run(fecha_inicio, fecha_fin)
    
    # ============================================================
    # GUARDAR REPORTES
    # ============================================================
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # JSON
    reporte_path = reportes_dir / f"backtest_bot_{timestamp}.json"
    with open(reporte_path, 'w', encoding='utf-8') as f:
        datos = {k: v for k, v in resultados.items() if k not in ['trades', 'equity_curve']}
        datos['trades'] = resultados.get('trades', [])
        datos['equity_curve'] = resultados.get('equity_curve', [])
        json.dump(datos, f, indent=2, default=str)
    print(f"✅ Reporte guardado: {reporte_path}")
    
    # Trades CSV
    if resultados.get('trades'):
        df_trades = pd.DataFrame(resultados['trades'])
        trades_path = reportes_dir / f"trades_bot_{timestamp}.csv"
        df_trades.to_csv(trades_path, index=False)
        print(f"✅ Trades guardados: {trades_path}")
    
    # Equity curve
    if resultados.get('equity_curve'):
        df_equity = pd.DataFrame({
            'timestamp': resultados.get('timestamps', range(len(resultados['equity_curve']))),
            'equity': resultados['equity_curve']
        })
        equity_path = reportes_dir / f"equity_curve_bot_{timestamp}.csv"
        df_equity.to_csv(equity_path, index=False)
        print(f"✅ Equity curve guardada: {equity_path}")
    
    # ============================================================
    # MOSTRAR RESULTADOS
    # ============================================================
    
    print("\n" + "=" * 60)
    print("📊 RESULTADOS DEL BACKTEST CON BOT REAL")
    print("=" * 60)
    print(f"Total operaciones: {resultados.get('total_operaciones', 0)}")
    print(f"Win Rate: {resultados.get('win_rate', 0):.2f}%")
    print(f"Profit Factor: {resultados.get('profit_factor', 0):.2f}")
    print(f"Net Profit: ${resultados.get('net_profit', 0):.2f}")
    print(f"Total Return: {resultados.get('total_return', 0):.2f}%")
    print(f"Max Drawdown: {resultados.get('max_drawdown', 0):.2f}%")
    print(f"Capital final: ${resultados.get('capital_final', 0):.2f}")
    
    if resultados.get('trades'):
        df_trades = pd.DataFrame(resultados['trades'])
        print("\n📊 Distribución por modo:")
        if 'modo' in df_trades.columns:
            for modo in df_trades['modo'].unique():
                df_m = df_trades[df_trades['modo'] == modo]
                total = len(df_m)
                ganadoras = len(df_m[df_m['pnl'] > 0])
                pnl_total = df_m['pnl'].sum()
                print(f"  {modo}: {total} ops | {ganadoras/total*100:.1f}% win | PnL: ${pnl_total:.2f}")
    
    print("=" * 60)

if __name__ == "__main__":
    main()