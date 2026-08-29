#!/usr/bin/env python3
"""
test_integracion.py - Prueba de integración de todos los módulos V9.0
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

print("🧪 PRUEBA DE INTEGRACIÓN V9.0")
print("=" * 60)

errores = 0

# 1. Configuración
try:
    from config.settings import Config
    from config.umbrales import Umbrales
    config = Config()
    print("✅ Configuración cargada")
except Exception as e:
    print(f"❌ Error en configuración: {e}")
    errores += 1

# 2. Utilidades
try:
    from utils.logger_persistente import LoggerPersistente
    from utils.cache import CacheUnificado
    from utils.tiempo import HorarioMercado
    from utils.helpers import safe_float
    print("✅ Utilidades cargadas")
except Exception as e:
    print(f"❌ Error en utilidades: {e}")
    errores += 1

# 3. Análisis
try:
    from analysis.tecnico import AnalisisTecnico
    from analysis.capas import create_analisis_por_capas
    from analysis.fases import AnalisisPorFase
    from analysis.pipeline import PipelineOportunidades
    from analysis.regimen import MarketRegimeFilter
    from analysis.niveles import NivelTracker
    from analysis.scoring import ScoreEngine
    from analysis.ml.ml_optimizer import MLOptimizer
    from analysis.patron_tracker import PatronTracker
    print("✅ Análisis cargado")
except Exception as e:
    print(f"❌ Error en análisis: {e}")
    errores += 1

# 4. Trading
try:
    from trading.riesgo import GestionRiesgo
    from trading.stops import GestorStops
    from trading.trailing import TrailingEngine
    from trading.ejecucion import EjecutorOperaciones
    from trading.sniper import create_sniper_checklist
    from trading.operabilidad import create_decisor_operabilidad
    from trading.modos import ModoSelector
    from trading.timer import EntryTimer
    print("✅ Trading cargado")
except Exception as e:
    print(f"❌ Error en trading: {e}")
    errores += 1

# 5. ML
try:
    from analysis.ml import (
        EntrenadorML, SurrogateTrader, HardNegativeMiner,
        DriftDetector, MLCache, PredictorML
    )
    print("✅ ML cargado")
except Exception as e:
    print(f"❌ Error en ML: {e}")
    errores += 1

# 6. Backtest
try:
    from backtesting.backtesting_bot import BacktesterBot
    print("✅ Backtest cargado")
except Exception as e:
    print(f"❌ Error en backtest: {e}")
    errores += 1

print("=" * 60)

if errores == 0:
    print("✅ TODOS LOS MÓDULOS CARGADOS CORRECTAMENTE")
    print("\n🚀 El bot está listo para ejecutar")
    
    # Preguntar si ejecutar backtest
    print("\n¿Ejecutar backtest de prueba? (s/n)")
    respuesta = input("> ").strip().lower()
    if respuesta == 's':
        print("\n▶️ Ejecutando backtest rápido...")
        try:
            from backtesting.backtesting_bot import BacktesterBot
            from datetime import datetime, timedelta, timezone
            
            fecha_fin = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            fecha_inicio = fecha_fin - timedelta(days=15)
            
            backtester = BacktesterBot(
                config=config,
                simbolos=['EURUSD', 'GBPUSD'],
                capital_inicial=300.0,
                modo_depuracion=True,
                max_lote_absoluto=0.005,
                dias_warmup=5,
                umbral_fase_1=20,
                max_simultaneas=2,
                max_ops_dia=5,
                risk_per_trade=0.01,
            )
            
            resultados = backtester.run(fecha_inicio, fecha_fin)
            print(f"\n📊 Resultados:")
            print(f"   Operaciones: {resultados.get('total_operaciones', 0)}")
            print(f"   Win Rate: {resultados.get('win_rate', 0):.2f}%")
            print(f"   Capital final: ${resultados.get('capital_final', 0):.2f}")
        except Exception as e:
            print(f"❌ Error en backtest: {e}")
            import traceback
            traceback.print_exc()
else:
    print(f"❌ {errores} ERRORES ENCONTRADOS - REVISAR")