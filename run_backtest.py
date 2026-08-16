#!/usr/bin/env python3
"""
run_backtest.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Orquestador de Backtest con Análisis Exhaustivo y Logs Detallados.

USO:
    python run_backtest.py --dias 30 --capital 300 --debug
    python run_backtest.py --dias 30 --modo_forzado RETEST --capital 300
    python run_backtest.py --dias 30 --simbolos EURUSD GBPUSD USDJPY --capital 300
"""

import argparse
import logging
import sys
import json
import time
import threading
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# ============================================================
# CONFIGURACIÓN DE RUTAS
# ============================================================

# Agregar raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from backtesting.backtesting_engine_v2 import BacktesterV2 as Backtester


# ============================================================
# LOGGING
# ============================================================

def setup_logging(debug: bool, log_file: Optional[str] = None):
    """Configura el sistema de logging."""
    level = logging.DEBUG if debug else logging.INFO
    
    formatter = logging.Formatter(
        '%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Limpiar handlers existentes
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Handler de consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Handler de archivo (opcional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Silenciar logs de bibliotecas externas
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


# ============================================================
# TIMEOUT
# ============================================================

class TimeoutError(Exception):
    pass


class TimeoutThread(threading.Thread):
    """Thread para control de timeout."""
    
    def __init__(self, timeout_minutos: int):
        super().__init__(daemon=True)
        self.timeout_minutos = timeout_minutos
        self._stop_event = threading.Event()
        self._start_time = time.time()
        self._last_log = 0
        self._logger = logging.getLogger('RunBacktest.Timeout')
    
    def run(self):
        elapsed = 0
        while not self._stop_event.is_set() and elapsed < self.timeout_minutos * 60:
            time.sleep(5)
            elapsed = time.time() - self._start_time
            if elapsed - self._last_log > 60:
                self._last_log = elapsed
                remaining = (self.timeout_minutos * 60) - elapsed
                self._logger.debug(f"⏱️ Timeout: {remaining/60:.1f} min restantes")
        
        if not self._stop_event.is_set():
            raise TimeoutError(f"El backtest ha excedido el tiempo límite de {self.timeout_minutos} minutos")
    
    def stop(self):
        self._stop_event.set()


# ============================================================
# ANÁLISIS DE RESULTADOS
# ============================================================

def imprimir_analisis_detallado(resultados: Dict[str, Any]):
    """Imprime un análisis exhaustivo de los resultados del backtest."""
    logger = logging.getLogger('RunBacktest.Analisis')
    
    print("\n" + "=" * 80)
    print("📊 ANÁLISIS EXHAUSTIVO DE BACKTEST")
    print("=" * 80)
    
    # 1. Resumen general
    print("\n📈 RESUMEN GENERAL:")
    print(f"   Total Operaciones: {resultados.get('total_operaciones', 0)}")
    print(f"   Operaciones Ganadoras: {resultados.get('ganadoras', 0)}")
    print(f"   Operaciones Perdedoras: {resultados.get('perdedoras', 0)}")
    print(f"   Win Rate: {resultados.get('win_rate', 0):.2f}%")
    print(f"   Profit Factor: {resultados.get('profit_factor', 0):.2f}")
    print(f"   Sharpe Ratio: {resultados.get('sharpe_ratio', 0):.3f}")
    print(f"   Máximo Drawdown: {resultados.get('max_drawdown', 0):.2f}%")
    print(f"   Retorno Total: {resultados.get('total_return', 0):.2f}%")
    print(f"   Beneficio Neto: ${resultados.get('net_profit', 0):.2f}")
    print(f"   Capital Final: ${resultados.get('capital_final', 0):.2f}")
    print(f"   Tiempo de ejecución: {resultados.get('tiempo', 0):.2f}s")
    
    # 2. Rendimiento por modo
    rendimiento_modos = resultados.get('rendimiento_por_modo', {})
    if rendimiento_modos:
        print("\n🎯 RENDIMIENTO POR MODO DE OPERACIÓN:")
        print("   " + "-" * 80)
        print(f"   {'MODO':<20} {'TOTAL':<8} {'GANADORAS':<10} {'PERDEDORAS':<10} {'WINRATE':<10} {'P&L TOTAL':<12} {'P&L PROMEDIO':<12}")
        print("   " + "-" * 80)
        
        for modo, data in sorted(rendimiento_modos.items(), key=lambda x: x[1].get('winrate', 0), reverse=True):
            winrate = data.get('winrate', 0)
            print(f"   {modo:<20} {data.get('total', 0):<8} {data.get('ganadores', 0):<10} {data.get('perdedores', 0):<10} "
                  f"{winrate:<9.1f}% ${data.get('pnl_total', 0):<11.2f} ${data.get('pnl_promedio', 0):<11.2f}")
    
    # 3. Estadísticas del Sniper
    stats_sniper = resultados.get('estadisticas_sniper', {})
    if stats_sniper:
        print("\n🔍 ESTADÍSTICAS DEL SNIPER:")
        print(f"   Total Evaluaciones: {stats_sniper.get('total_evaluaciones', 0)}")
        print(f"   Total Aprobados: {stats_sniper.get('total_aprobados', 0)}")
        print(f"   Total Rechazados: {stats_sniper.get('total_rechazados', 0)}")
        print(f"   Tasa de Aprobación: {stats_sniper.get('tasa_aprobacion', 0):.2f}%")
        print(f"   Tasa de Rechazo: {stats_sniper.get('tasa_rechazo', 0):.2f}%")
        
        top_motivos = stats_sniper.get('top_motivos_rechazo', {})
        if top_motivos:
            print("\n   TOP MOTIVOS DE RECHAZO:")
            for i, (motivo, count) in enumerate(list(top_motivos.items())[:10], 1):
                print(f"      {i}. {motivo[:60]}: {count} veces")
        
        distribucion_modos = stats_sniper.get('distribucion_modos', {})
        if distribucion_modos:
            print("\n   📊 DISTRIBUCIÓN DE MODOS:")
            for modo, pct in sorted(distribucion_modos.items(), key=lambda x: x[1], reverse=True):
                print(f"      {modo}: {pct:.1f}%")
    
    # 4. Scores promedio
    scores_promedio = resultados.get('scores_promedio', {})
    if scores_promedio:
        print("\n📊 SCORES PROMEDIO:")
        print(f"   H1: {scores_promedio.get('h1', 0):.1f}")
        print(f"   M15: {scores_promedio.get('m15', 0):.1f}")
        print(f"   M5: {scores_promedio.get('m5', 0):.1f}")
        print(f"   Final: {scores_promedio.get('final', 0):.1f}")
    
    # 5. Estadísticas de horario
    stats_horario = resultados.get('estadisticas_horario', {})
    if stats_horario:
        print("\n🕐 ESTADÍSTICAS DE HORARIO:")
        print(f"   Spread promedio simulado: {stats_horario.get('spread_promedio', 0):.1f} pips")
        print(f"   Distribución calidad horario: {dict(stats_horario.get('por_calidad', {}))}")
    
    # 6. Motivos de rechazo (del análisis)
    motivos_rechazo = resultados.get('estadisticas_analisis', {}).get('motivos_rechazo', {})
    if motivos_rechazo:
        print("\n⛔ MOTIVOS DE RECHAZO (ANÁLISIS):")
        for motivo, count in sorted(motivos_rechazo.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"      {motivo[:60]}: {count} veces")
    
    print("\n" + "=" * 80)


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main():
    """Función principal del orquestador."""
    
    parser = argparse.ArgumentParser(
        description='Backtest Engine V9.0 con Análisis Exhaustivo',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EJEMPLOS:
  # Backtest básico con 30 días
  python run_backtest.py --dias 30 --capital 300
  
  # Backtest con modo forzado
  python run_backtest.py --dias 30 --modo_forzado RETEST --capital 300
  
  # Backtest con símbolos específicos
  python run_backtest.py --dias 30 --simbolos EURUSD GBPUSD USDJPY --capital 300
  
  # Backtest con logs detallados
  python run_backtest.py --dias 7 --capital 300 --debug --log_file logs/backtest.log
  
  # Backtest rápido sin precarga
  python run_backtest.py --dias 7 --capital 300 --no_precarga
        """
    )
    
    # ============================================================
    # PARÁMETROS GENERALES
    # ============================================================
    
    parser.add_argument('--dias', type=int, default=30,
                       help='Días operativos a simular (default: 30)')
    parser.add_argument('--warmup', type=int, default=21,
                       help='Días de warm-up (default: 21)')
    parser.add_argument('--capital', type=float, default=300.0,
                       help='Capital inicial (default: 300.0)')
    parser.add_argument('--max_lote', type=float, default=0.005,
                       help='Lote máximo absoluto (default: 0.005)')
    parser.add_argument('--debug', action='store_true',
                       help='Activar logs DEBUG')
    parser.add_argument('--log_file', type=str, default=None,
                       help='Archivo de log (default: None)')
    parser.add_argument('--timeout_minutos', type=int, default=30,
                       help='Timeout en minutos (default: 30)')
    parser.add_argument('--no_timeout', action='store_true',
                       help='Desactivar timeout')
    parser.add_argument('--no_precarga', action='store_true',
                       help='Desactivar precarga de modos')
    
    # ============================================================
    # PARÁMETROS DE ESTRATEGIA
    # ============================================================
    
    parser.add_argument('--umbral', type=int, default=20,
                       help='Umbral Fase 1 (default: 20)')
    parser.add_argument('--simbolos', type=str, nargs='+', default=None,
                       help='Símbolos a testear (default: todos)')
    parser.add_argument('--modo_forzado', type=str, default=None,
                       choices=['RETEST', 'BREAKOUT', 'PULLBACK', 'NIVEL_FUERTE',
                               'PATRON', 'RUPTURA_FALSA', 'VELA_BORDE',
                               'RETEST_FALLBACK', 'SNIPER_ELITE'],
                       help='Forzar un modo específico')
    parser.add_argument('--modo_exploratorio', action='store_true',
                       help='Modo exploratorio (filtros menos estrictos)')
    
    # ============================================================
    # PARÁMETROS DE RIESGO
    # ============================================================
    
    parser.add_argument('--max_simultaneas', type=int, default=3,
                       help='Máximo posiciones simultáneas (default: 3)')
    parser.add_argument('--max_ops_dia', type=int, default=5,
                       help='Máximo operaciones por día (default: 5)')
    parser.add_argument('--risk_per_trade', type=float, default=0.01,
                       help='Riesgo por operación (default: 0.01)')
    parser.add_argument('--max_daily_drawdown', type=float, default=0.06,
                       help='Drawdown diario máximo (default: 0.06)')
    parser.add_argument('--slippage_pips', type=float, default=0.5,
                       help='Slippage en pips (default: 0.5)')
    
    # ============================================================
    # PARÁMETROS DE SIMULACIÓN
    # ============================================================
    
    parser.add_argument('--zona_horaria', type=str, default='COLOMBIA',
                       choices=['COLOMBIA', 'UTC', 'LONDON', 'NEW_YORK', 'TOKYO'],
                       help='Zona horaria (default: COLOMBIA)')
    
    # ============================================================
    # PARÁMETROS DE REPORTES
    # ============================================================
    
    parser.add_argument('--no_guardar', action='store_true',
                       help='No guardar reportes')
    parser.add_argument('--reportes_dir', type=str, default='reportes',
                       help='Directorio de reportes (default: reportes)')
    
    args = parser.parse_args()
    
    # ============================================================
    # CONFIGURACIÓN DE LOGGING
    # ============================================================
    
    setup_logging(args.debug, args.log_file)
    logger = logging.getLogger('RunBacktest')
    
    # ============================================================
    # BANNER DE INICIO
    # ============================================================
    
    logger.info("=" * 70)
    logger.info("🚀 BACKTEST ENGINE V9.0 - ORQUESTADOR REFACTORIZADO")
    logger.info("=" * 70)
    logger.info(f"📅 Días: {args.dias}")
    logger.info(f"📅 Warmup: {args.warmup}")
    logger.info(f"💰 Capital: ${args.capital:.2f}")
    logger.info(f"📊 Umbral Fase 1: {args.umbral}")
    logger.info(f"📊 Modo forzado: {args.modo_forzado or 'Ninguno'}")
    logger.info(f"🎯 Fidelidad: {'EXPLORATORIA' if args.modo_exploratorio else 'REAL'}")
    logger.info(f"📊 Zona horaria: {args.zona_horaria}")
    logger.info(f"📊 Límite posiciones: {args.max_simultaneas}")
    logger.info(f"📊 Límite operaciones/día: {args.max_ops_dia}")
    logger.info(f"📊 Lote máximo: {args.max_lote}")
    logger.info(f"📊 Riesgo por operación: {args.risk_per_trade:.1%}")
    logger.info(f"📦 Precarga de modos: {'DESACTIVADA' if args.no_precarga else 'ACTIVADA'}")
    logger.info("=" * 70)
    
    # ============================================================
    # CONFIGURACIÓN
    # ============================================================
    
    try:
        config = Config()
    except Exception as e:
        logger.error(f"❌ Error cargando configuración: {e}")
        return 1
    
    # ============================================================
    # FECHAS
    # ============================================================
    
    fecha_fin = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_inicio = fecha_fin - timedelta(days=args.dias + args.warmup)
    
    logger.info(f"📅 Rango: {fecha_inicio.strftime('%Y-%m-%d')} a {fecha_fin.strftime('%Y-%m-%d')}")
    
    # ============================================================
    # SÍMBOLOS
    # ============================================================
    
    if args.simbolos:
        simbolos = args.simbolos
    else:
        simbolos = config.SIMBOLOS_OPERABLES
    
    logger.info(f"📋 Símbolos: {', '.join(simbolos)} ({len(simbolos)} símbolos)")
    
    # ============================================================
    # TIMEOUT
    # ============================================================
    
    timeout_thread = None
    
    try:
        # ============================================================
        # INICIALIZAR BACKTESTER
        # ============================================================
        
        logger.info("🔧 Inicializando Backtester V9.0...")
        
        backtester = Backtester(
            config=config,
            simbolos=simbolos,
            modo_forzado=args.modo_forzado,
            capital_inicial=args.capital,
            max_lote_absoluto=args.max_lote,
            dias_warmup=args.warmup,
            umbral_fase_1=args.umbral,
            modo_depuracion=args.debug,
            use_ml=False,
            use_risk_manager=True,
            max_simultaneas=args.max_simultaneas,
            max_ops_dia=args.max_ops_dia,
            risk_per_trade=args.risk_per_trade,
            max_daily_drawdown=args.max_daily_drawdown,
            slippage_pips=args.slippage_pips,
            zona_horaria=args.zona_horaria,
            fidelidad_real=not args.modo_exploratorio,
            usar_precarga=not args.no_precarga
        )
        
        # ============================================================
        # INICIAR TIMEOUT
        # ============================================================
        
        if not args.no_timeout:
            logger.info(f"⏱️ Iniciando timeout de {args.timeout_minutos} minutos...")
            timeout_thread = TimeoutThread(args.timeout_minutos)
            timeout_thread.daemon = True
            timeout_thread.start()
        
        # ============================================================
        # EJECUTAR BACKTEST
        # ============================================================
        
        logger.info("▶️ Ejecutando backtest...")
        start_time = time.time()
        
        resultados = backtester.run(fecha_inicio, fecha_fin)
        
        elapsed = time.time() - start_time
        
        # ============================================================
        # DETENER TIMEOUT
        # ============================================================
        
        if timeout_thread:
            timeout_thread.stop()
            timeout_thread.join(timeout=1)
        
        # ============================================================
        # VERIFICAR ERRORES
        # ============================================================
        
        if isinstance(resultados, dict) and 'error' in resultados:
            logger.error(f"❌ Error en backtest: {resultados['error']}")
            return 1
        
        # ============================================================
        # GUARDAR REPORTES
        # ============================================================
        
        if not args.no_guardar:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            reportes_dir = Path(args.reportes_dir)
            reportes_dir.mkdir(parents=True, exist_ok=True)
            
            # Reporte principal
            reporte_path = reportes_dir / f"backtest_{timestamp}.json"
            backtester.guardar_reporte(reporte_path)
            logger.info(f"✅ Reporte guardado en: {reporte_path}")
            
            # Equity curve
            equity_path = reportes_dir / f"equity_curve_{timestamp}.csv"
            backtester.guardar_equity_curve(equity_path)
            logger.info(f"✅ Equity curve guardada en: {equity_path}")
            
            # Estadísticas del sniper
            if 'estadisticas_sniper' in resultados:
                stats_path = reportes_dir / f"sniper_stats_{timestamp}.json"
                with open(stats_path, 'w', encoding='utf-8') as f:
                    json.dump(resultados['estadisticas_sniper'], f, indent=2, default=str)
                logger.info(f"✅ Estadísticas del Sniper guardadas en: {stats_path}")
            
            # Trades
            trades_path = reportes_dir / f"trades_{timestamp}.csv"
            if resultados.get('trades'):
                import pandas as pd
                df_trades = pd.DataFrame(resultados['trades'])
                columnas = ['simbolo', 'direccion', 'entrada', 'salida', 'pnl', 'modo', 'regimen', 'motivo_cierre']
                columnas_existentes = [c for c in columnas if c in df_trades.columns]
                if columnas_existentes:
                    df_trades[columnas_existentes].to_csv(trades_path, index=False)
                    logger.info(f"✅ Trades guardados en: {trades_path}")
        
        # ============================================================
        # MOSTRAR ANÁLISIS
        # ============================================================
        
        imprimir_analisis_detallado(resultados)
        
        # ============================================================
        # RESUMEN FINAL
        # ============================================================
        
        logger.info("=" * 70)
        logger.info(f"✅ BACKTEST COMPLETADO EN {elapsed:.2f}s")
        logger.info(f"📊 Total operaciones: {resultados.get('total_operaciones', 0)}")
        logger.info(f"📊 Win Rate: {resultados.get('win_rate', 0):.2f}%")
        logger.info(f"💰 Capital final: ${resultados.get('capital_final', 0):.2f}")
        logger.info("=" * 70)
        
        return 0
        
    except TimeoutError as e:
        logger.error(f"❌ {e}")
        if timeout_thread:
            timeout_thread.stop()
        return 1
        
    except KeyboardInterrupt:
        logger.info("⌨️ Interrupción de teclado. Saliendo...")
        if timeout_thread:
            timeout_thread.stop()
        return 0
        
    except Exception as e:
        logger.error(f"❌ Fallo crítico en ejecución: {e}", exc_info=True)
        if timeout_thread:
            timeout_thread.stop()
        return 1


# ============================================================
# PUNTO DE ENTRADA
# ============================================================

if __name__ == "__main__":
    sys.exit(main())