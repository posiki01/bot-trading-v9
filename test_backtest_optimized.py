#!/usr/bin/env python3
# test_backtest_optimized.py - VERSIÓN REFACTORIZADA

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from backtesting.backtesting_bot import BacktesterBot
from datetime import datetime, timedelta, timezone
import json
import pandas as pd


def main():
    # ============================================================
    # CONFIGURACIÓN DEL BACKTEST
    # ============================================================
    
    # 🔥 PARÁMETROS AJUSTABLES
    SL_PIPS = 80                  # SL en pips (aumentado de 35)
    RR_OBJETIVO = 1.2               # R:R objetivo (aumentado de 1.5)
    CAPITAL_INICIAL = 300.0
    RISK_PER_TRADE = 0.01          # 0.5% riesgo por operación
    MAX_OPS_DIA = 3                 # Reducido de 8
    MAX_SIMULTANEAS = 2
    DIAS_BACKTEST = 60
    
    print("🧪 Iniciando backtest OPTIMIZADO V2")
    print("=" * 60)
    print(f"📊 SL: {SL_PIPS} pips | R:R: {RR_OBJETIVO}")
    print(f"📊 Risk per trade: {RISK_PER_TRADE*100:.1f}%")
    print(f"📊 Max ops/día: {MAX_OPS_DIA}")
    print("=" * 60)
    
    config = Config()
    simbolos = ['EURUSD', 'GBPUSD', 'AUDUSD']
    
    fecha_fin = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_inicio = fecha_fin - timedelta(days=DIAS_BACKTEST)
    
    print(f"📅 Rango: {fecha_inicio.strftime('%Y-%m-%d')} → {fecha_fin.strftime('%Y-%m-%d')}")
    print(f"📋 Símbolos: {simbolos}")
    
    reportes_dir = Path("reportes")
    reportes_dir.mkdir(parents=True, exist_ok=True)
    
    # ============================================================
    # CREAR BACKTESTER CON PARÁMETROS OPTIMIZADOS
    # ============================================================
    
    backtester = BacktesterBot(
        config=config,
        simbolos=simbolos,
        capital_inicial=CAPITAL_INICIAL,
        modo_depuracion=True,
        max_lote_absoluto=0.005,
        dias_warmup=15,
        umbral_fase_1=60,
        max_simultaneas=MAX_SIMULTANEAS,
        max_ops_dia=MAX_OPS_DIA,
        risk_per_trade=RISK_PER_TRADE,
        use_ml=False,
        # 🔥 PARÁMETROS CRÍTICOS PARA SL/TP
        sl_pips=80,              # ← AHORA SE PASAN
        rr_objetivo=1.2,      # ← AHORA SE PASAN
    )
    
    # ============================================================
    # EJECUTAR BACKTEST
    # ============================================================
    
    print("▶️ Ejecutando backtest...")
    resultados = backtester.run(fecha_inicio, fecha_fin)
    
    # ============================================================
    # GUARDAR REPORTES
    # ============================================================
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    reporte_path = reportes_dir / f"backtest_optimized_{timestamp}.json"
    backtester.guardar_reporte(reporte_path)
    print(f"✅ Reporte guardado: {reporte_path}")
    
    if resultados.get('trades'):
        df_trades = pd.DataFrame(resultados['trades'])
        trades_path = reportes_dir / f"trades_optimized_{timestamp}.csv"
        df_trades.to_csv(trades_path, index=False)
        print(f"✅ Trades guardados: {trades_path}")
    
    # ============================================================
    # MOSTRAR RESULTADOS
    # ============================================================
    
    print("\n" + "=" * 60)
    print("📊 RESULTADOS DEL BACKTEST")
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
        
        print(f"\n📊 Distribución por modo:")
        for modo in df['modo'].unique():
            df_m = df[df['modo'] == modo]
            total = len(df_m)
            ganadoras = len(df_m[df_m['pnl'] > 0])
            pnl_total = df_m['pnl'].sum()
            print(f"  {modo}: {total} ops | {ganadoras/total*100:.1f}% win | PnL: ${pnl_total:.2f}")
        
        print(f"\n📊 Distribución por dirección:")
        for direccion in df['direccion'].unique():
            df_d = df[df['direccion'] == direccion]
            total = len(df_d)
            ganadoras = len(df_d[df_d['pnl'] > 0])
            pnl_total = df_d['pnl'].sum()
            print(f"  {direccion}: {total} ops | {ganadoras/total*100:.1f}% win | PnL: ${pnl_total:.2f}")
    
    print("=" * 60)


if __name__ == "__main__":
    main()