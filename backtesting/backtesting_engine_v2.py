#!/usr/bin/env python3
"""
backtesting/backtesting_engine_v2.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Backtesting Engine con simulación REALISTA del comportamiento del bot.

MEJORAS V9.0:
- CORRECCIÓN: Todos los imports para la nueva estructura
- CORRECCIÓN: Integración con NivelTracker V9.0
- CORRECCIÓN: Integración con Sniper V9.0
- CORRECCIÓN: Integración con Fases V9.0
- CORRECCIÓN: Spread simulado por tipo de activo y horario
- CORRECCIÓN: PnL REALISTA con spread y slippage
- CORRECCIÓN: SL mínimo por activo (XAUUSD=60, BTCUSD=80, etc.)
- MEJORA: Consistencia 100% con bot principal
- MEJORA: Logs detallados de cada paso
- MEJORA: Estadísticas de horario y spread
"""

import time
import threading
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import logging
import MetaTrader5 as mt5
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import json
import sys
import os

# ============================================================
# AGREGAR RAIZ AL PATH
# ============================================================

sys.path.insert(0, str(Path(__file__).parent.parent))

# ============================================================
# IMPORTS REFACTORIZADOS V9.0
# ============================================================

from config.settings import Config

# Análisis
from analysis.tecnico import AnalisisTecnico
from analysis.capas import AnalisisPorCapas, create_analisis_por_capas
from analysis.fases import AnalisisPorFase
from analysis.pipeline import PipelineOportunidades, FaseOportunidad
from analysis.regimen import MarketRegimeFilter, RegimenMercado, RegimenData
from analysis.niveles import NivelTracker
from analysis.scoring import ScoreEngine
from analysis.patron_tracker import PatronTracker

# Trading
from trading.riesgo import GestionRiesgo
from trading.stops import GestorStops
from trading.sniper_checklist import SniperChecklist, create_sniper_checklist
from trading.operabilidad import create_decisor_operabilidad

# Utilidades
from utils.tiempo import HorarioMercado
from utils.cache import CacheUnificado
from utils.logger_persistente import LoggerPersistente
from utils.helpers import safe_float

# ============================================================
# VERIFICACIÓN DE IMPORTS
# ============================================================

try:
    from analysis.ml import MLOptimizer
except ImportError:
    MLOptimizer = None
    logger = logging.getLogger('BotTrading.Backtesting')
    logger.warning("⚠️ MLOptimizer no disponible")

logger = logging.getLogger('BotTrading.Backtesting')


# ============================================================
# ALMACENAMIENTO MOCK
# ============================================================

class AlmacenMock:
    """Mock de almacenamiento para backtesting."""
    
    def __init__(self):
        self.niveles = {}
        self.operaciones = []
        self.configuracion = {}
        self.watchlist = {}
        self.directorio_base = Path("data")

    def obtener_configuracion(self):
        return self.configuracion

    def guardar_configuracion(self, config):
        if isinstance(config, dict):
            self.configuracion.update(config)

    def obtener_niveles(self, simbolo):
        return self.niveles.get(simbolo, {'soportes': [], 'resistencias': []})

    def guardar_niveles(self, simbolo, soportes, resistencias):
        self.niveles[simbolo] = {'soportes': soportes, 'resistencias': resistencias}

    def guardar_watchlist(self, watchlist):
        self.watchlist = watchlist if watchlist else {}

    def obtener_watchlist(self):
        return self.watchlist

    def guardar_operacion(self, op):
        self.operaciones.append(op)

    def obtener_operaciones(self, filtros=None):
        return self.operaciones

    def guardar_metrica_diaria(self, fecha, metricas):
        pass

    def cerrar(self):
        pass


# ============================================================
# CLASE PRINCIPAL - BACKTESTER
# ============================================================

class BacktesterV2:
    """
    Backtesting Engine con simulación REALISTA.
    V9.0 - COMPLETAMENTE REFACTORIZADO.
    """

    # ================================================================
    # CONSTANTES
    # ================================================================
    
    MAX_WATCHLIST_SIZE = 10
    MAX_CONTEXTO_H1_SIZE = 20
    LIMPIEZA_CONTEXTO_INTERVALO = 24

    def __init__(
        self,
        config: Config,
        simbolos: List[str],
        modo_forzado: Optional[str] = None,
        capital_inicial: float = 300.0,
        comision_por_lote: float = 1.0,
        slippage_pips: float = 0.5,
        use_risk_manager: bool = True,
        max_simultaneas: Optional[int] = None,
        max_ops_dia: Optional[int] = None,
        risk_per_trade: Optional[float] = None,
        max_daily_drawdown: Optional[float] = None,
        umbral_fase_1: int = 20,
        use_ml: bool = False,
        umbral_score: int = 30,
        modo_depuracion: bool = True,
        max_lote_absoluto: float = 0.005,
        dias_warmup: int = 21,
        zona_horaria: str = 'COLOMBIA',
        simular_latencia: bool = True,
        latencia_ms: float = 100.0,
        fidelidad_real: bool = True,
        usar_precarga: bool = False,
    ):
        """
        Inicializa el Backtester.
        """
        self.config = config
        self.simbolos = simbolos
        self.modo_forzado = modo_forzado
        self.dias_warmup = dias_warmup
        self.capital_inicial = capital_inicial
        self.capital_actual = capital_inicial
        self.comision_por_lote = comision_por_lote
        self.slippage_pips = slippage_pips
        self.use_risk_manager = use_risk_manager
        self.umbral_fase_1 = umbral_fase_1
        self.use_ml = use_ml
        self.umbral_score = umbral_score
        self.modo_depuracion = modo_depuracion
        self.max_lote_absoluto = max_lote_absoluto
        self.zona_horaria = zona_horaria
        self.simular_latencia = simular_latencia
        self.latencia_ms = latencia_ms
        self.fidelidad_real = fidelidad_real
        self.usar_precarga = usar_precarga
        self.modo_evaluacion = 'REAL' if fidelidad_real else 'DIAGNOSTICO'
        self.almacen_simulado = AlmacenMock()

        self.modo_backtest = True

        # ============================================================
        # 1. INICIALIZAR LOGGING
        # ============================================================
        
        self.logger = logging.getLogger('BotTrading.Backtesting')
        if modo_depuracion:
            self.logger.setLevel(logging.DEBUG)

        self.logger.info(f"📊 BacktesterV2 V9.0 REFACTORIZADO inicializado")
        self.logger.info(f"   Símbolos: {len(simbolos)}")
        self.logger.info(f"   Capital: ${capital_inicial:.2f}")
        self.logger.info(f"   Comisión por lote: ${comision_por_lote:.2f}")

        # ============================================================
        # 2. INICIALIZAR MÓDULOS
        # ============================================================

        self.analisis = AnalisisTecnico()
        self.horario = HorarioMercado(zona_usuario=zona_horaria)
        
        # Caché unificado
        self.cache = CacheUnificado(
            max_size=200,
            default_ttl=300,
            modo_backtest=True
        )
        
        self.score_engine = ScoreEngine(
            config=config,
            analysis_cache=self.cache,
            modo_backtest=True
        )

        nivel_analisis = logging.DEBUG if self.modo_depuracion else logging.INFO
        
        # Inicializar analisis_capas sin analisis_tecnico (se creará internamente)
        self.analisis_capas = create_analisis_por_capas(
            analisis_tecnico=self.analisis,
            config=config,
            score_engine=self.score_engine,
            modo_backtest=True,
            modo_depuracion=self.modo_depuracion
        )

        # ============================================================
        # 3. PARÁMETROS DE RIESGO
        # ============================================================

        self.max_simultaneas = max_simultaneas or 3
        self.max_ops_dia = max_ops_dia or 8
        self.risk_per_trade = risk_per_trade or 0.01
        self.max_daily_drawdown = max_daily_drawdown or 0.06

        # ============================================================
        # 4. ALMACENAMIENTO SIMULADO
        # ============================================================

        self.patron_tracker = PatronTracker(almacen=self.almacen_simulado, config=config)

        # ============================================================
        # 5. NIVEL TRACKER
        # ============================================================
        
        try:
            self.nivel_tracker = NivelTracker(
                almacen=self.almacen_simulado,
                config=config,
                modo_backtest=True
            )
            self.logger.info("✅ NivelTracker V9.0 inicializado (backtest)")
        except Exception as e:
            self.logger.warning(f"⚠️ Error inicializando NivelTracker: {e}")
            self.nivel_tracker = None

        # ============================================================
        # 6. GESTIÓN DE RIESGO
        # ============================================================

        if use_risk_manager:
            self.risk_manager = GestionRiesgo(
                capital_inicial=capital_inicial,
                almacen=self.almacen_simulado,
                modo_backtest=True
            )
        else:
            self.risk_manager = None

        # ============================================================
        # 7. FILTRO DE RÉGIMEN
        # ============================================================

        self.regimen_filter = MarketRegimeFilter(config=config, modo_backtest=True)
        self.regimen_mercado: Dict[str, RegimenData] = {}

        # ============================================================
        # 8. PIPELINE Y SNIPER
        # ============================================================

        self.pipeline = PipelineOportunidades(
            config=config,
            modo_backtest=True,
            umbral_fase_1=self.umbral_fase_1
        )

        self._fase_analisis = AnalisisPorFase(
            mt5_connector=None,
            noticias=None,
            ml_optimizer=None,
            config=config,
            analysis_cache=self.cache,
            modo_backtest=True,
            modo_depuracion=self.modo_depuracion
        )
        self._fase_analisis.set_analysis_cache(self.cache)
        self._fase_analisis.set_analisis_capas(self.analisis_capas)

        self.sniper_checklist = create_sniper_checklist(
            pipeline=self.pipeline,
            config=config,
            almacen=self.almacen_simulado,
            mt5=None,
            noticias=None,
            patron_tracker=self.patron_tracker,
            ml_optimizer=None,
            analysis_cache=self.cache,
            modo_depuracion=self.modo_depuracion,
            modo_backtest=True
        )

        # ============================================================
        # 9. GESTOR DE STOPS
        # ============================================================

        self.gestor_stops = GestorStops(config=config, modo_backtest=True)

        # ============================================================
        # 10. DECISOR DE OPERABILIDAD
        # ============================================================

        self.decisor_operabilidad = create_decisor_operabilidad(
            config=config,
            horario=self.horario,
            modo_backtest=True
        )

        # ============================================================
        # 11. ESTADOS INTERNOS
        # ============================================================

        self.posiciones_abiertas = []
        self.trades = []
        self.equity_curve = [capital_inicial]
        self.timestamps = []
        self.ops_hoy = 0
        self.dia_actual = None
        self.equity_inicio_dia = capital_inicial
        self.simbolos_info = {}
        self.dataframes = {}
        self.fechas_comunes = []
        self._h4_precargados = {}
        self._d1_precargados = {}
        self.cooldowns_simbolos: Dict[str, datetime] = {}
        self._cb_hasta_simulado: Optional[datetime] = None
        self._ultima_limpieza_huérfanos: Optional[datetime] = None

        self.watchlist: Dict[str, datetime] = {}
        self.max_edad_horas = 2

        self._contexto_h1: Dict[str, Dict] = {}

        # ============================================================
        # 12. ESTADÍSTICAS
        # ============================================================

        self.estadisticas_analisis = {
            'evaluaciones_sniper': 0,
            'aprobados_sniper': 0,
            'rechazados_sniper': 0,
            'rechazados_pre_ejecucion': 0,
            'por_modo': defaultdict(lambda: {'evaluados': 0, 'aprobados': 0, 'rechazados': 0, 'ganadores': 0, 'perdedores': 0}),
            'por_regimen': defaultdict(lambda: {'evaluados': 0, 'aprobados': 0, 'rechazados': 0}),
            'por_simbolo': defaultdict(lambda: {'evaluados': 0, 'aprobados': 0, 'rechazados': 0}),
            'motivos_rechazo': defaultdict(int),
            'rechazos_por_regimen': defaultdict(int),
            'detalles_operaciones': [],
            'scores_promedio': {
                'h1': 0,
                'm15': 0,
                'm5': 0,
                'final': 0,
                'count': 0,
            },
            'rendimiento_por_modo': defaultdict(lambda: {'total': 0, 'ganadores': 0, 'perdedores': 0, 'pnl_total': 0}),
            'estadisticas_horario': {
                'por_calidad': defaultdict(int),
                'spread_promedio': 0,
                'spread_count': 0,
            }
        }
        self.analisis_modos = defaultdict(lambda: {'evaluados': 0, 'aprobados': 0, 'rechazados': 0})

        self.logger.info(f"   Riesgo por operación: {risk_per_trade:.1%}")
        self.logger.info(f"   Umbral F1: {umbral_fase_1}")
        self.logger.info(f"   Warmup: {dias_warmup} días")
        self.logger.info(f"   Modo backtest: ACTIVADO | Evaluación: {self.modo_evaluacion}")
        self.logger.info(f"   📊 Límite posiciones: {self.max_simultaneas}")
        self.logger.info(f"   📊 Límite operaciones/día: {self.max_ops_dia}")
        self.logger.info(f"   📊 Lote máximo absoluto: {self.max_lote_absoluto}")
        self.logger.info(f"   📦 Precarga de modos: {'ACTIVADA' if self.usar_precarga else 'DESACTIVADA'}")

    # ================================================================
    # MÉTODOS DE CONSISTENCIA CON BOT PRINCIPAL
    # ================================================================

    def _obtener_calidad_horario_para_backtest(self, simbolo: str, fecha: datetime) -> str:
        """
        Obtiene la calidad de horario DINÁMICA para backtest.
        IDÉNTICO al bot principal.
        """
        if fecha is None:
            fecha = datetime.now(timezone.utc)
        
        hora_utc = self.horario.hora_float(fecha)
        hora_col = (hora_utc - 5) % 24
        weekday = fecha.weekday()
        simbolo_upper = simbolo.upper()
        
        # CRIPTO - SIEMPRE EXCELENTE
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 'EXCELENTE'
        
        # SÁBADO - PÉSIMO
        if weekday == 5:
            return 'PESIMA'
        
        # DOMINGO - PÉSIMO hasta 22:00 UTC
        if weekday == 6 and hora_utc < 22.0:
            return 'PESIMA'
        
        # VIERNES - CIERRE POR TIPO DE ACTIVO
        if weekday == 4:
            if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']) or \
               any(x in simbolo_upper for x in ['XAU', 'XAG']):
                if hora_col >= 16.0:
                    return 'PESIMA'
                if 11.0 <= hora_col < 16.0:
                    return 'EXCELENTE'
            
            if hora_col >= 17.0:
                return 'PESIMA'
            if 11.0 <= hora_col < 16.0:
                return 'EXCELENTE'
        
        # LUNES TEMPRANO - NO OPERAR
        if weekday == 0 and hora_col < 2.0:
            return 'PESIMA'
        
        # ROLLOVER - PÉSIMO
        if 11.75 <= hora_col <= 12.5:
            return 'PESIMA'
        
        # AFTER-HOURS NY - BLOQUEADO
        if 16.0 <= hora_col <= 18.0:
            return 'PESIMA'
        
        # DETERMINAR CALIDAD POR TIPO DE ACTIVO
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            if 7.0 <= hora_col <= 11.0:
                return 'EXCELENTE'
            elif 11.0 <= hora_col < 16.0:
                return 'BUENA'
            elif 2.0 <= hora_col < 7.0:
                return 'REGULAR'
            else:
                return 'MALA'
        
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            if 7.0 <= hora_col <= 11.0:
                return 'EXCELENTE'
            elif 11.0 <= hora_col < 16.0:
                return 'BUENA'
            elif 2.0 <= hora_col < 7.0:
                return 'REGULAR'
            else:
                return 'MALA'
        
        # FOREX
        es_asiatico_par = any(c in simbolo_upper for c in ['JPY', 'AUD', 'NZD'])
        es_londres_par = any(c in simbolo_upper for c in ['GBP', 'EUR', 'CHF'])
        es_ny_par = 'CAD' in simbolo_upper
        
        if 7.0 <= hora_col <= 11.0:
            return 'EXCELENTE'
        elif 2.0 <= hora_col < 7.0:
            if es_londres_par:
                return 'EXCELENTE'
            elif es_asiatico_par:
                return 'REGULAR'
            else:
                return 'BUENA'
        elif 11.0 <= hora_col < 16.0:
            if es_ny_par or es_londres_par:
                return 'BUENA'
            elif es_asiatico_par:
                return 'REGULAR'
            else:
                return 'REGULAR'
        elif 18.0 <= hora_col <= 24.0 or 0.0 <= hora_col < 2.0:
            if es_asiatico_par:
                return 'BUENA'
            else:
                return 'MALA'
        
        return 'REGULAR'

    def _obtener_spread_simulado(self, simbolo: str, fecha: datetime) -> float:
        """Obtiene spread simulado realista."""
        simbolo_upper = simbolo.upper()
        hora_col = self._obtener_hora_colombia(fecha)
        
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            base_spread_pips = 20.0
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            base_spread_pips = 10.0
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            base_spread_pips = 1.0
        elif 'JPY' in simbolo_upper:
            base_spread_pips = 1.0
        else:
            base_spread_pips = 1.0
        
        calidad = self._obtener_calidad_horario_para_backtest(simbolo, fecha)
        factores = {
            'EXCELENTE': 0.8,
            'BUENA': 1.0,
            'REGULAR': 1.2,
            'MALA': 1.5,
            'PESIMA': 2.0,
        }
        factor = factores.get(calidad, 1.0)
        
        spread_pips = base_spread_pips * factor
        return min(20.0, spread_pips)

    def _obtener_hora_colombia(self, fecha: datetime) -> float:
        """Obtiene hora Colombia en formato float."""
        if fecha is None:
            fecha = datetime.now(timezone.utc)
        
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        
        hora_col = fecha.astimezone(self.horario.ZONAS['COLOMBIA'])
        return hora_col.hour + hora_col.minute / 60.0

    def _obtener_pip_value_por_lote(self, simbolo: str) -> float:
        """Obtiene el valor por pip para 1 lote estándar."""
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 10.0
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 10.0
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        else:
            return 10.0

    def _obtener_sl_minimo_por_activo(self, simbolo: str) -> float:
        """Obtiene SL mínimo por tipo de activo."""
        simbolo_upper = simbolo.upper()
        
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 80.0
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 60.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 35.0
        if any(x in simbolo_upper for x in ['JPY']):
            if any(x in simbolo_upper for x in ['GBP']):
                return 18.0
            elif any(x in simbolo_upper for x in ['EUR']):
                return 15.0
            else:
                return 15.0
        
        sl_min = {
            'EURUSD': 10, 'GBPUSD': 12, 'USDJPY': 10,
            'AUDUSD': 10, 'USDCAD': 10, 'USDCHF': 10,
            'EURGBP': 10, 'EURCHF': 12, 'GBPCHF': 15,
        }.get(simbolo_upper, 10)
        
        return max(20.0, float(sl_min))

    def _calcular_macd_desde_precios(self, df: pd.DataFrame) -> float:
        """Calcula MACD desde precios reales."""
        try:
            if df is None or len(df) < 26:
                return 0.0
            
            close = df['Close']
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = (macd_line - signal_line).iloc[-1]
            
            return float(macd_hist) if not pd.isna(macd_hist) else 0.0
        except Exception:
            return 0.0

    def _calcular_pnl_realista(self, simbolo: str, entrada: float, salida: float, 
                               lotes: float, direccion: str, spread_pips: float = 0) -> float:
        """Calcula PnL REALISTA con spread y slippage."""
        if lotes <= 0 or entrada <= 0 or salida <= 0:
            return 0.0
        
        # Obtener pip size
        if 'JPY' in simbolo:
            pip_size = 0.01
        elif 'XAU' in simbolo or 'XAG' in simbolo:
            pip_size = 0.10
        elif any(x in simbolo for x in ['US30', 'NAS100', 'US500']):
            pip_size = 1.0
        elif any(c in simbolo for c in ['BTC', 'ETH', 'SOL']):
            pip_size = 1.0
        else:
            pip_size = 0.0001
        
        # Calcular pips
        if direccion == 'COMPRA':
            pips = (salida - entrada) / pip_size
        else:
            pips = (entrada - salida) / pip_size
        
        # Valor por pip
        pip_value_per_lot = self._obtener_pip_value_por_lote(simbolo)
        pnl = pips * pip_value_per_lot * lotes
        
        # Comisión
        comision = self.comision_por_lote * lotes * 2
        
        # Spread
        if spread_pips > 0:
            spread_cost = (spread_pips * pip_value_per_lot * lotes) / 2
            pnl = pnl - spread_cost
        
        pnl_neto = pnl - comision
        
        return pnl_neto

    def _determinar_direccion_analisis(self, medio, pesado) -> str:
        """Determina dirección del análisis."""
        bullish = 0
        bearish = 0

        if medio.rsi > 60:
            bullish += 1
        elif medio.rsi < 40:
            bearish += 1

        if medio.macd_histogram > 0:
            bullish += 1
        elif medio.macd_histogram < 0:
            bearish += 1

        if medio.adx > 25:
            if medio.sma20 > medio.sma50:
                bullish += 2
            else:
                bearish += 2

        if medio.en_nivel_clave:
            if medio.soporte_cercano:
                bullish += 1
            if medio.resistencia_cercana:
                bearish += 1

        if pesado.divergencia_rsi == 'BULLISH':
            bullish += 2
        elif pesado.divergencia_rsi == 'BEARISH':
            bearish += 2

        if pesado.wyckoff_fase in ['ACUMULACION', 'SPRING']:
            bullish += 2
        elif pesado.wyckoff_fase in ['DISTRIBUCION', 'UPTHRUST']:
            bearish += 2

        if pesado.ob_cercano:
            if pesado.bull_ob:
                bullish += 1
            if pesado.bear_ob:
                bearish += 1

        if bullish > bearish + 2:
            return 'COMPRA'
        elif bearish > bullish + 2:
            return 'VENTA'
        return 'NEUTRAL'

    def _verificar_alineacion_regimen(self, direccion: str, regimen_objeto: Optional[RegimenMercado]) -> Tuple[bool, str]:
        """Verifica alineación con régimen."""
        if regimen_objeto is None:
            return True, "OK"
        
        if regimen_objeto in [RegimenMercado.TREND_ALCISTA_FUERTE, RegimenMercado.TREND_ALCISTA_DEBIL]:
            if direccion == 'VENTA':
                return False, "VENTA contra TREND_ALCISTA"
            return True, "OK"
        
        if regimen_objeto in [RegimenMercado.TREND_BAJISTA_FUERTE, RegimenMercado.TREND_BAJISTA_DEBIL]:
            if direccion == 'COMPRA':
                return False, "COMPRA contra TREND_BAJISTA"
            return True, "OK"
        
        return True, "OK"

    # ================================================================
    # MÉTODOS DE DESCARGA DE DATOS
    # ================================================================

    def _descargar_datos_con_logs(self, simbolo: str, inicio: datetime, fin: datetime) -> Optional[Dict[str, pd.DataFrame]]:
        """Descarga datos de MT5 con logs detallados."""
        self.logger.info(f"   📥 Descargando {simbolo}...")
        
        if not mt5.initialize():
            self.logger.error(f"   ❌ {simbolo}: No se pudo inicializar MT5")
            return None
        
        if not mt5.symbol_select(simbolo, True):
            self.logger.error(f"   ❌ {simbolo}: No existe en Market Watch")
            mt5.shutdown()
            return None
        
        if inicio >= fin:
            self.logger.error(f"   ❌ {simbolo}: Rango de fechas inválido")
            mt5.shutdown()
            return None
        
        dfs = {}
        tfs = {
            'H1': mt5.TIMEFRAME_H1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
            'M1': mt5.TIMEFRAME_M1,
        }
        
        for name, tf in tfs.items():
            try:
                rates = mt5.copy_rates_range(simbolo, tf, inicio, fin)
            except Exception as e:
                self.logger.error(f"      ❌ {simbolo} {name}: Error: {e}")
                continue
            
            if rates is None or len(rates) == 0:
                continue
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            df.index = df.index.tz_localize('UTC')
            df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low',
                'close': 'Close', 'tick_volume': 'Volume'
            }, inplace=True)
            
            dfs[name] = df
        
        mt5.shutdown()
        
        if len(dfs) < 2:
            self.logger.error(f"   ❌ {simbolo}: Datos insuficientes - {len(dfs)} timeframes")
            return None
        
        return dfs

    def _resamplear_h4(self, df_h1: pd.DataFrame) -> pd.DataFrame:
        """Resamplea H1 a H4."""
        if df_h1 is None or df_h1.empty:
            return pd.DataFrame()
        try:
            df_h4 = df_h1.resample('4h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min',
                'Close': 'last', 'Volume': 'sum'
            }).dropna()
            if df_h4.index.tzinfo is None:
                df_h4.index = df_h4.index.tz_localize('UTC')
            return df_h4
        except Exception:
            return pd.DataFrame()

    def _resamplear_d1(self, df_h1: pd.DataFrame) -> pd.DataFrame:
        """Resamplea H1 a D1."""
        if df_h1 is None or df_h1.empty:
            return pd.DataFrame()
        try:
            df_d1 = df_h1.resample('D').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min',
                'Close': 'last', 'Volume': 'sum'
            }).dropna()
            if df_d1.index.tzinfo is None:
                df_d1.index = df_d1.index.tz_localize('UTC')
            return df_d1
        except Exception:
            return pd.DataFrame()

    # ================================================================
    # MÉTODOS DE VALIDACIÓN FASE 2 Y SNIPER
    # ================================================================

    def _validar_fase_2_consistente(self, simbolo, fecha_m5, direccion_h1, regimen_h1, regimen_objeto):
        """Valida Fase 2 (M15) consistentemente."""
        df_m15 = self.dataframes.get(simbolo, {}).get('M15')
        if df_m15 is None or len(df_m15) < 20:
            return False, "Sin datos M15", None
        
        df_m15_hasta = df_m15.loc[:fecha_m5]
        if len(df_m15_hasta) < 20:
            return False, "Datos M15 insuficientes", None
        
        rapido_m15 = self.analisis_capas.analisis_rapido(df_m15_hasta, simbolo)
        if not rapido_m15.pasa_filtro:
            return False, f"Filtro rápido M15 falló - {rapido_m15.razon_rechazo}", None
        
        medio_m15 = self.analisis_capas.analisis_medio(df_m15_hasta, simbolo, rapido_m15, {})
        if not medio_m15.pasa_filtro:
            return False, f"Filtro medio M15 falló - {medio_m15.razon_rechazo}", None
        
        aprobado, motivo, contexto_m15 = self._fase_analisis.validar_fase_2(
            simbolo=simbolo,
            df_m15=df_m15_hasta,
            direccion_h1=direccion_h1,
            regimen_h1=regimen_h1,
            regimen_objeto=regimen_objeto,
            contexto_h1=None,
            force=False,
            analisis_rapido_m15=rapido_m15,
            analisis_medio_m15=medio_m15
        )
        
        return aprobado, motivo, contexto_m15

    def _evaluar_sniper_consistente(self, simbolo, estado, ctx, fecha_m5):
        """Evalúa sniper consistentemente."""
        contexto_m15 = estado.analisis_m15 if hasattr(estado, 'analisis_m15') else None
        
        df_m5 = self.dataframes.get(simbolo, {}).get('M5')
        if df_m5 is None or len(df_m5) < 50:
            return None
        
        df_m5_hasta = df_m5.loc[:fecha_m5]
        if len(df_m5_hasta) < 50:
            return None
        
        precio_actual = df_m5_hasta['Close'].iloc[-1]
        
        calidad_horario = self._obtener_calidad_horario_para_backtest(simbolo, fecha_m5)
        spread_pips = self._obtener_spread_simulado(simbolo, fecha_m5)
        
        # Actualizar estadísticas de horario
        self.estadisticas_analisis['estadisticas_horario']['por_calidad'][calidad_horario] += 1
        stats = self.estadisticas_analisis['estadisticas_horario']
        stats['spread_promedio'] = (stats['spread_promedio'] * stats['spread_count'] + spread_pips) / (stats['spread_count'] + 1)
        stats['spread_count'] += 1
        
        try:
            macd_correcto = self._calcular_macd_desde_precios(df_m5_hasta)
            
            rapido_m5 = self.analisis_capas.analisis_rapido(df_m5_hasta, simbolo)
            if not rapido_m5.pasa_filtro:
                return None
            
            niveles = self.almacen_simulado.niveles.get(simbolo, {'soportes': [], 'resistencias': []})
            medio_m5 = self.analisis_capas.analisis_medio(df_m5_hasta, simbolo, rapido_m5, niveles)
            if not medio_m5.pasa_filtro:
                return None
            
            medio_m5.macd_histogram = macd_correcto
            
        except Exception as e:
            self.logger.debug(f"Error en análisis M5 de {simbolo}: {e}")
            return None
        
        ejecutar_pesado = medio_m5.adx_fuerte or medio_m5.en_nivel_clave or (estado and estado.score_acumulado > 40)
        
        try:
            info_tick_simulado = {
                'bid': precio_actual - (spread_pips * 0.0001 / 2),
                'ask': precio_actual + (spread_pips * 0.0001 / 2),
                'spread': spread_pips * 0.0001,
                'spread_pips': spread_pips
            }
            
            disparo = self.sniper_checklist.evaluar_sniper_optimizado(
                simbolo=simbolo,
                df_m5=df_m5_hasta,
                precio_actual=precio_actual,
                direccion=estado.direccion,
                estado_pipeline=estado,
                analisis_rapido=rapido_m5,
                analisis_medio=medio_m5,
                ejecutar_pesado=ejecutar_pesado,
                contexto_h1=ctx,
                df_m15=contexto_m15,
                info_tick=info_tick_simulado,
                spread_pips=spread_pips,
                regimen_objeto=ctx.get('regimen_objeto'),
                calidad_horario=calidad_horario,
                fecha_vela=fecha_m5
            )
        except Exception as e:
            self.logger.error(f"❌ Error evaluando sniper {simbolo}: {e}")
            return None
        
        return disparo

    # ================================================================
    # MÉTODOS DE VALIDACIÓN Y LIMPIEZA
    # ================================================================

    def _verificar_circuit_breaker(self, fecha_actual: datetime) -> bool:
        """Verifica si el Circuit Breaker está activo."""
        if self.risk_manager is None:
            return False
        
        if hasattr(self.risk_manager, 'circuit_breaker'):
            return self.risk_manager.circuit_breaker.verificar()
        
        if hasattr(self.risk_manager, 'circuit_breaker_activo'):
            if self.risk_manager.circuit_breaker_activo:
                if self._cb_hasta_simulado is None or fecha_actual >= self._cb_hasta_simulado:
                    self.risk_manager.circuit_breaker_activo = False
                    self._cb_hasta_simulado = None
                    return False
                return True
        
        return False

    def _limpiar_watchlist_timeout(self, fecha_actual: datetime):
        """Limpia watchlist antigua."""
        for simbolo in list(self.watchlist.keys()):
            ts = self.watchlist.get(simbolo)
            if ts and (fecha_actual - ts).total_seconds() > self.max_edad_horas * 3600:
                del self.watchlist[simbolo]
        
        if len(self.watchlist) > self.MAX_WATCHLIST_SIZE:
            sorted_items = sorted(self.watchlist.items(), key=lambda x: x[1])
            for simbolo, _ in sorted_items[:-self.MAX_WATCHLIST_SIZE]:
                del self.watchlist[simbolo]

    def _limpiar_contexto_antiguo(self, fecha_actual: datetime):
        """Limpia contexto H1 antiguo."""
        for simbolo in list(self._contexto_h1.keys()):
            ctx = self._contexto_h1.get(simbolo)
            if ctx:
                ts = ctx.get('timestamp')
                if ts and (fecha_actual - ts).total_seconds() > 24 * 3600:
                    del self._contexto_h1[simbolo]
        
        if len(self._contexto_h1) > self.MAX_CONTEXTO_H1_SIZE:
            sorted_items = sorted(
                [(s, ctx.get('timestamp', datetime.min)) for s, ctx in self._contexto_h1.items()],
                key=lambda x: x[1]
            )
            for simbolo, _ in sorted_items[:-self.MAX_CONTEXTO_H1_SIZE]:
                del self._contexto_h1[simbolo]

    def _validar_condiciones_pre_ejecucion(self, simbolo: str, disparo: Dict[str, Any], fecha_m5: datetime) -> Tuple[bool, str]:
        """Valida condiciones pre-ejecución."""
        if self.modo_forzado:
            modo_disparo = disparo.get('modo', '').upper()
            modo_forzado_upper = self.modo_forzado.upper()
            if modo_disparo != modo_forzado_upper:
                return False, f"Modo {modo_disparo} != {self.modo_forzado}"

        cooldown_hasta = self.cooldowns_simbolos.get(simbolo)
        if cooldown_hasta and fecha_m5 < cooldown_hasta:
            return False, f"Cooldown hasta {cooldown_hasta}"

        if self.ops_hoy >= self.max_ops_dia:
            return False, f"Límite diario {self.max_ops_dia}"

        if self.equity_inicio_dia > 0:
            dd_actual = (self.equity_inicio_dia - self.capital_actual) / self.equity_inicio_dia
            if dd_actual > self.max_daily_drawdown:
                return False, f"Drawdown {dd_actual:.2%} > {self.max_daily_drawdown:.2%}"

        if any(p['simbolo'] == simbolo for p in self.posiciones_abiertas):
            return False, "Ya hay posición abierta"

        if len(self.posiciones_abiertas) >= self.max_simultaneas:
            return False, f"Límite {self.max_simultaneas} alcanzado"

        score = disparo.get('score_final', disparo.get('score', 50))
        if score > 80:
            factor_noticias = 1.1
        elif score < 60:
            factor_noticias = 0.9
        else:
            factor_noticias = 1.0
        
        disparo['lote_factor_noticias'] = factor_noticias

        return True, "OK"

    # ================================================================
    # MÉTODOS DE EJECUCIÓN DE OPERACIONES
    # ================================================================

    def _ejecutar_operacion_sniper(self, simbolo, disparo, dfs, fecha):
        """Ejecuta una operación sniper."""
        if self.ops_hoy >= self.max_ops_dia:
            return
        
        if len(self.posiciones_abiertas) >= self.max_simultaneas:
            return
        
        direccion = disparo['direccion']
        precio_entrada = disparo['entry_price']
        sl_propuesto = disparo.get('sl_propuesto', 0.0)
        tp_propuesto = disparo.get('tp_propuesto', 0.0)
        tp2_propuesto = disparo.get('tp2', 0.0)
        modo = disparo.get('modo', 'RETEST')
        score_final = disparo.get('score_final', disparo.get('score', 30))
        regimen = disparo.get('regimen', 'UNCERTAIN')
        regimen_objeto_val = disparo.get('regimen_objeto')
        es_reversal = disparo.get('es_reversal', False)
        atr_entrada = disparo.get('atr_calculado', 0.001)
        atr_medio = disparo.get('atr_medio_calculado', atr_entrada)
        lote_factor = disparo.get('lote_factor', 1.0)
        spread_entrada = disparo.get('spread_entrada', 0)

        # Determinar pip value y digits
        if 'JPY' in simbolo:
            pip_val = 0.01
            digits = 3
        elif 'XAU' in simbolo or 'XAG' in simbolo:
            pip_val = 0.10
            digits = 2
        elif any(x in simbolo for x in ['US30', 'NAS100', 'US500']):
            pip_val = 1.0
            digits = 2
        elif any(c in simbolo for c in ['BTC', 'ETH', 'SOL']):
            pip_val = 1.0
            digits = 2
        else:
            pip_val = 0.0001
            digits = 5

        info = self.simbolos_info.get(simbolo, {
            'tick_value': 1.0,
            'tick_size': 0.00001,
            'point': 0.00001,
            'stops_level': 0,
            'spread': 0.0005,
            'digits': digits
        })
        spread_real = info.get('spread', 0.0005)

        # Precio de ejecución con slippage
        df_m5 = dfs.get('M5')
        try:
            idx_actual = df_m5.index.get_loc(fecha)
            if idx_actual + 1 < len(df_m5):
                precio_base = df_m5.iloc[idx_actual + 1]['Open']
            else:
                precio_base = df_m5.iloc[idx_actual]['Close']
        except (KeyError, IndexError):
            precio_base = precio_entrada

        slippage_actual = max(0.0, min(
            np.random.normal(self.slippage_pips * pip_val, (self.slippage_pips * pip_val) * 0.5),
            (self.slippage_pips * pip_val) * 2.0
        ))
        precio_ejecucion = precio_base + slippage_actual if direccion == 'COMPRA' else precio_base - slippage_actual
        precio_ejecucion += (spread_real / 2.0) if direccion == 'COMPRA' else -(spread_real / 2.0)

        # Validar SL/TP
        valido, razon, sl_final, tp_final, tp2_final = self.gestor_stops.validar_sl_tp(
            simbolo=simbolo,
            entry_price=precio_ejecucion,
            sl=sl_propuesto,
            tp=tp_propuesto,
            tp2=tp2_propuesto,
            direccion=direccion,
            info_simbolo=None,
            regimen=regimen,
            modo=modo,
            es_reversal=es_reversal,
            en_nivel_clave=False,
            atr=atr_entrada,
            calidad_horario=self._obtener_calidad_horario_para_backtest(simbolo, fecha)
        )

        if not valido:
            self.estadisticas_analisis['motivos_rechazo'][f"SL_TP_INVALIDO_{modo}"] += 1
            self.estadisticas_analisis['rechazados_pre_ejecucion'] += 1
            return

        # Calcular SL distancia y aplicar mínimo
        sl_dist_pips = abs(precio_ejecucion - sl_final) / pip_val if pip_val > 0 else 1
        
        sl_min_activo = self._obtener_sl_minimo_por_activo(simbolo)
        sl_min_pips_absoluto = max(20.0, sl_min_activo)
        
        if sl_dist_pips < sl_min_pips_absoluto:
            if direccion == 'COMPRA':
                sl_final = precio_ejecucion - (sl_min_pips_absoluto * pip_val)
            else:
                sl_final = precio_ejecucion + (sl_min_pips_absoluto * pip_val)
            sl_dist_pips = sl_min_pips_absoluto

        # Calcular lotes
        riesgo_max_usd = self.capital_actual * self.risk_per_trade
        pip_value_per_lot_estandar = self._obtener_pip_value_por_lote(simbolo)
        pip_value_por_0_01_lote = pip_value_per_lot_estandar * 0.01
        
        if sl_dist_pips > 0 and pip_value_por_0_01_lote > 0:
            lotes_teoricos = riesgo_max_usd / (sl_dist_pips * pip_value_por_0_01_lote)
        else:
            lotes_teoricos = 0.01
        
        factor_confianza = min(1.5, max(0.5, score_final / 50.0))
        lotes_teoricos = lotes_teoricos * factor_confianza * lote_factor
        
        lote_minimo = 0.001
        lote_maximo = self.max_lote_absoluto
        
        lotes = max(lote_minimo, min(lote_maximo, lotes_teoricos))
        lotes = round(lotes, 3)

        # Crear operación
        sl_dist = abs(precio_ejecucion - sl_final)
        tp_dist = abs(tp_final - precio_ejecucion)
        rr_final = tp_dist / sl_dist if sl_dist > 0 else 0
        
        op = {
            'simbolo': simbolo,
            'direccion': direccion,
            'entrada': precio_ejecucion,
            'sl': sl_final,
            'sl_original': sl_final,
            'tp': tp_final,
            'tp2': tp2_final,
            'lotes': lotes,
            'fecha_entrada': fecha,
            'estado': 'ABIERTA',
            'ticket': len(self.trades) + 1,
            'score': score_final,
            'modo': modo,
            'regimen': regimen,
            'regimen_objeto': regimen_objeto_val,
            'spread_entrada': spread_entrada,
            'contexto_apertura': {
                'regimen': regimen,
                'es_reversal': es_reversal,
                'modo': modo,
                'lote_factor': lote_factor,
                'usa_nivel_real': disparo.get('usa_nivel_real', False),
                'sl_min_pips_usado': sl_min_pips_absoluto,
                'rr_objetivo': rr_final,
                'sl_dist_pips': sl_dist_pips,
                'rr_esperado': rr_final,
                'capital_actual': self.capital_actual,
                'spread_pips': spread_entrada,
            },
            'tp1_realizado': False,
            'tp2_realizado': False,
            'tp3_realizado': False,
            'lotes_iniciales': lotes,
            'pnl_acumulado': 0.0,
            'sl_movido_breakeven': False,
            'max_beneficio_alcanzado': 0.0,
            'atr_entrada': atr_entrada,
            'atr_medio': atr_medio,
        }

        self.posiciones_abiertas.append(op)
        self.ops_hoy += 1

        self.logger.info(
            f"📈 ENTRADA {simbolo} {direccion} @ {precio_ejecucion:.{digits}f} | "
            f"SL: {sl_final:.{digits}f} ({sl_dist_pips:.1f}pips) | "
            f"TP: {tp_final:.{digits}f} | "
            f"R:R: {rr_final:.2f} | Lotes: {lotes:.3f} | "
            f"Spread: {spread_entrada:.1f}pips | "
            f"Modo: {modo} | Score: {score_final:.0f}"
        )

    def _cerrar_posicion(self, pos, fecha, df, precio_salida=None, motivo_cierre=None):
        """Cierra una posición."""
        if pos['estado'] != 'ABIERTA':
            return

        if precio_salida is None and df is not None:
            precio_salida = df.loc[:fecha]['Close'].iloc[-1]
        if precio_salida is None:
            return

        # Determinar pip value
        simbolo = pos['simbolo']
        if 'JPY' in simbolo:
            pip_val = 0.01
        elif 'XAU' in simbolo:
            pip_val = 0.10
        elif any(x in simbolo for x in ['US30', 'NAS100', 'US500']):
            pip_val = 1.0
        elif any(c in simbolo for c in ['BTC', 'ETH', 'SOL']):
            pip_val = 1.0
        else:
            pip_val = 0.0001

        spread_real = 0.0005
        slippage = self.slippage_pips * pip_val

        if pos['direccion'] == 'COMPRA':
            precio_cierre = precio_salida - (slippage + spread_real / 2)
        else:
            precio_cierre = precio_salida + (slippage + spread_real / 2)

        spread_pips = pos.get('spread_entrada', 0)
        pnl = self._calcular_pnl_realista(
            pos['simbolo'], 
            pos['entrada'], 
            precio_cierre, 
            pos['lotes'], 
            pos['direccion'],
            spread_pips
        )
        
        self.capital_actual += pnl
        pos['pnl_acumulado'] += pnl
        pos['pnl'] = pos['pnl_acumulado']

        if motivo_cierre is None:
            if pos['direccion'] == 'COMPRA':
                if precio_salida <= pos['sl']:
                    motivo_cierre = "SL"
                elif precio_salida >= pos['tp']:
                    motivo_cierre = "TP1"
                else:
                    motivo_cierre = "TRAILING"
            else:
                if precio_salida >= pos['sl']:
                    motivo_cierre = "SL"
                elif precio_salida <= pos['tp']:
                    motivo_cierre = "TP1"
                else:
                    motivo_cierre = "TRAILING"

        pos['estado'] = 'CERRADA'
        pos['precio_salida'] = precio_cierre
        pos['motivo_cierre'] = motivo_cierre

        self.trades.append(pos.copy())
        self.posiciones_abiertas.remove(pos)
        self.pipeline.liberar_simbolo(pos['simbolo'])

        modo = pos.get('modo', 'DESCONOCIDO')
        if modo not in self.estadisticas_analisis['rendimiento_por_modo']:
            self.estadisticas_analisis['rendimiento_por_modo'][modo] = {
                'total': 0, 'ganadores': 0, 'perdedores': 0, 'pnl_total': 0
            }
        
        self.estadisticas_analisis['rendimiento_por_modo'][modo]['total'] += 1
        self.estadisticas_analisis['rendimiento_por_modo'][modo]['pnl_total'] += pnl
        if pnl > 0:
            self.estadisticas_analisis['rendimiento_por_modo'][modo]['ganadores'] += 1
        else:
            self.estadisticas_analisis['rendimiento_por_modo'][modo]['perdedores'] += 1

        self.cooldowns_simbolos[pos['simbolo']] = fecha + timedelta(hours=2 if pos['pnl'] < 0 else 0.5)

        self.logger.info(
            f"📊 CIERRE {pos['simbolo']} {pos['direccion']} @ {precio_cierre:.{5 if pip_val == 0.0001 else 3}f} | "
            f"PnL: ${pnl:.2f} | Motivo: {motivo_cierre} | Equity: ${self.capital_actual:.2f}"
        )

    def _actualizar_stop(self, pos, fecha, df):
        """Actualiza el stop loss con trailing."""
        if pos['estado'] != 'ABIERTA':
            return
        
        if df is None or len(df) < 14:
            return

        df_futuro = df.loc[pos['fecha_entrada']:fecha]
        if len(df_futuro) < 2:
            return

        p_ent = pos['entrada']
        sl_act = pos['sl']
        tp = pos['tp']
        simbolo = pos['simbolo']
        precio_actual = df_futuro['Close'].iloc[-1]

        # Determinar pip value
        if 'JPY' in simbolo:
            pip_val = 0.01
            digits = 3
        elif 'XAU' in simbolo:
            pip_val = 0.10
            digits = 2
        elif any(x in simbolo for x in ['US30', 'NAS100', 'US500']):
            pip_val = 1.0
            digits = 2
        elif any(c in simbolo for c in ['BTC', 'ETH', 'SOL']):
            pip_val = 1.0
            digits = 2
        else:
            pip_val = 0.0001
            digits = 5

        # Calcular ganancia
        if pos['direccion'] == 'COMPRA':
            ganancia_pips = (precio_actual - p_ent) / pip_val if pip_val > 0 else 0
        else:
            ganancia_pips = (p_ent - precio_actual) / pip_val if pip_val > 0 else 0

        # Verificar SL/TP alcanzados
        if pos['direccion'] == 'COMPRA':
            if df_futuro['Low'].min() <= sl_act:
                self._cerrar_posicion(pos, fecha, df, sl_act, "SL")
                return
            if df_futuro['High'].max() >= tp:
                self._cerrar_posicion(pos, fecha, df, tp, "TP1")
                return
        else:
            if df_futuro['High'].max() >= sl_act:
                self._cerrar_posicion(pos, fecha, df, sl_act, "SL")
                return
            if df_futuro['Low'].min() <= tp:
                self._cerrar_posicion(pos, fecha, df, tp, "TP1")
                return

        # Trailing stop simplificado
        if ganancia_pips > 20:
            nuevo_sl = None
            if pos['direccion'] == 'COMPRA':
                nuevo_sl = precio_actual - (15 * pip_val)
            else:
                nuevo_sl = precio_actual + (15 * pip_val)
            
            if nuevo_sl is not None:
                if pos['direccion'] == 'COMPRA' and nuevo_sl > sl_act:
                    pos['sl'] = round(nuevo_sl, digits)
                elif pos['direccion'] == 'VENTA' and nuevo_sl < sl_act:
                    pos['sl'] = round(nuevo_sl, digits)

    # ================================================================
    # MÉTODO PRINCIPAL RUN
    # ================================================================

    def run(self, fecha_inicio: datetime, fecha_fin: datetime) -> Dict[str, Any]:
        """Ejecuta el backtest principal."""
        start_time = time.time()

        self.logger.info(f"🚀 INICIANDO BACKTEST V9.0 REFACTORIZADO")
        self.logger.info(f"📅 Rango: {fecha_inicio} → {fecha_fin}")

        if fecha_inicio.tzinfo is None:
            fecha_inicio = fecha_inicio.replace(tzinfo=timezone.utc)
        if fecha_fin.tzinfo is None:
            fecha_fin = fecha_fin.replace(tzinfo=timezone.utc)

        # Descargar datos
        self.logger.info("📥 DESCARGANDO DATOS DESDE MT5...")
        
        for simbolo in self.simbolos:
            dfs = self._descargar_datos_con_logs(simbolo, fecha_inicio, fecha_fin)
            if dfs is None:
                self.logger.error(f"❌ {simbolo}: DESCARGA FALLIDA")
                continue
            
            self.dataframes[simbolo] = dfs
            
            if 'H4' not in dfs or len(dfs['H4']) < 20:
                self._h4_precargados[simbolo] = self._resamplear_h4(dfs.get('H1', pd.DataFrame()))
            else:
                self._h4_precargados[simbolo] = dfs['H4']

            if 'D1' not in dfs or len(dfs['D1']) < 20:
                self._d1_precargados[simbolo] = self._resamplear_d1(dfs.get('H1', pd.DataFrame()))
            else:
                self._d1_precargados[simbolo] = dfs['D1']

            self.simbolos_info[simbolo] = {
                'tick_value': 1.0,
                'tick_size': 0.00001,
                'digits': 5,
                'point': 0.00001,
                'stops_level': 0,
                'spread': 0.0005,
                'trade_mode': 0
            }

        if not self.dataframes:
            self.logger.error("❌ No se descargaron datos de ningún símbolo")
            return {'error': 'No data'}

        # Calcular fechas comunes
        fechas_h1 = None
        fechas_m5 = None
        
        for simbolo, dfs in self.dataframes.items():
            self.logger.info(f"📊 {simbolo}: H1={len(dfs.get('H1', pd.DataFrame()))} velas, M5={len(dfs.get('M5', pd.DataFrame()))} velas")
            if 'H1' in dfs:
                self.logger.info(f"   H1 columns: {dfs['H1'].columns.tolist()}")
                self.logger.info(f"   H1 sample: {dfs['H1'].head(2)}")
            df_h1 = dfs.get('H1', pd.DataFrame())
            df_m5 = dfs.get('M5', pd.DataFrame())
            
            if fechas_h1 is None:
                fechas_h1 = df_h1.index
                fechas_m5 = df_m5.index
            else:
                fechas_h1 = fechas_h1.intersection(df_h1.index)
                fechas_m5 = fechas_m5.intersection(df_m5.index)

        self.fechas_comunes = sorted(fechas_h1)
        fechas_m5_comunes = sorted(fechas_m5)
        set_fechas_h1 = set(self.fechas_comunes)
        pos_h1 = {f: i for i, f in enumerate(self.fechas_comunes)}

        self.logger.info(f"📊 Fechas comunes H1: {len(self.fechas_comunes)}")
        self.logger.info(f"📊 Fechas comunes M5: {len(fechas_m5_comunes)}")

        if len(self.fechas_comunes) < 20:
            return {'error': 'Fechas H1 insuficientes'}

        self.equity_curve = [self.capital_inicial]
        self.timestamps = [fechas_m5_comunes[0]] if fechas_m5_comunes else [fecha_inicio]

        self._contexto_h1 = {}
        ultima_hora_h1_procesada = None

        total_velas = len(fechas_m5_comunes)

        # Bucle principal
        for idx, fecha_m5 in enumerate(fechas_m5_comunes):
            if idx % 500 == 0 and idx > 0:
                elapsed = time.time() - start_time
                self.logger.info(f"⏳ Progreso: {idx/total_velas*100:.1f}% | "
                           f"Ops: {len(self.trades)} | Equity: ${self.capital_actual:.2f}")

            if fecha_m5.tzinfo is None:
                fecha_m5 = fecha_m5.replace(tzinfo=timezone.utc)

            if self._verificar_circuit_breaker(fecha_m5):
                continue

            fecha_h1_actual = fecha_m5.floor('h')
            idx_h1 = pos_h1.get(fecha_h1_actual)
            
            if idx_h1 is None or idx_h1 < 20:
                continue

            # Reset diario
            if self.dia_actual != fecha_m5.date():
                self.dia_actual = fecha_m5.date()
                self.ops_hoy = 0
                self.equity_inicio_dia = self.capital_actual

            self._limpiar_watchlist_timeout(fecha_m5)
            self._limpiar_contexto_antiguo(fecha_m5)

            # Procesar nueva vela H1
            hay_h1_nueva = (ultima_hora_h1_procesada is None or fecha_h1_actual > ultima_hora_h1_procesada) and fecha_h1_actual in set_fechas_h1

            if hay_h1_nueva:
                ultima_hora_h1_procesada = fecha_h1_actual
                
                for simbolo, dfs in self.dataframes.items():
                    df_h1_hasta = dfs.get('H1', pd.DataFrame()).loc[:fecha_h1_actual]
                    
                    if len(df_h1_hasta) < 20:
                        continue
                    
                    df_h4 = self._h4_precargados.get(simbolo, pd.DataFrame()).loc[:fecha_h1_actual]
                    df_d1 = self._d1_precargados.get(simbolo, pd.DataFrame()).loc[:fecha_h1_actual]
                    
                    # Régimen
                    try:
                        regimen_data = self.regimen_filter.clasificar(
                            simbolo=simbolo,
                            df_h4=df_h4 if len(df_h4) >= 20 else pd.DataFrame(),
                            df_h1=df_h1_hasta
                        )
                        self.regimen_mercado[simbolo] = regimen_data
                        regimen = regimen_data.regimen.value
                        regimen_objeto = regimen_data.regimen
                        direccion_regimen = regimen_data.direccion_favor
                        confianza_regimen = regimen_data.confianza
                    except Exception as e:
                        self.logger.debug(f"Error en régimen para {simbolo}: {e}")
                        regimen = 'INCERTO'
                        regimen_objeto = RegimenMercado.INCERTO
                        direccion_regimen = 'NONE'
                        confianza_regimen = 0
                    
                    # Análisis con NivelTracker
                    try:
                        rapido = self.analisis_capas.analisis_rapido(df_h1_hasta, simbolo)
                        if not rapido.pasa_filtro:
                            continue
                        
                        niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
                            simbolo=simbolo,
                            df=df_h1_hasta,
                            precio_actual=df_h1_hasta['Close'].iloc[-1]
                        )
                        
                        medio = self.analisis_capas.analisis_medio(
                            df_h1_hasta, simbolo, rapido, niveles
                        )
                        
                        if not medio.pasa_filtro:
                            continue
                        
                        pesado = self.analisis_capas.analisis_pesado(
                            df_h1_hasta, simbolo, df_h4, df_d1, niveles, medio
                        )
                        
                        direccion = self._determinar_direccion_analisis(medio, pesado)
                        
                    except Exception as e:
                        self.logger.debug(f"Error en análisis de {simbolo}: {e}")
                        continue
                    
                    if direccion == 'NEUTRAL':
                        continue
                    
                    alineado, razon_alineacion = self._verificar_alineacion_regimen(
                        direccion=direccion,
                        regimen_objeto=regimen_objeto
                    )
                    
                    if not alineado:
                        continue
                    
                    # Score H1
                    score_h1 = self.score_engine.calcular_score_h1(
                        score_estructura=pesado.score_estructura,
                        score_momentum=pesado.score_momentum,
                        score_confluencia=pesado.score_confluencia,
                        score_institucional=pesado.score_institucional,
                        simbolo=simbolo
                    ).score
                    
                    # Actualizar pipeline
                    try:
                        estado = self.pipeline.actualizar_fase_1(
                            simbolo=simbolo,
                            analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
                            score=score_h1,
                            direccion=direccion,
                            regimen=regimen,
                            direccion_regimen=direccion_regimen,
                            confianza_regimen=confianza_regimen,
                            tendencia_h4='ALCISTA' if medio.adx > 25 and medio.sma20 > medio.sma50 else 'BAJISTA' if medio.adx > 25 else 'LATERAL'
                        )
                    except Exception as e:
                        self.logger.debug(f"Error actualizando pipeline para {simbolo}: {e}")
                        continue
                    
                    if estado is None:
                        continue
                    
                    # Guardar contexto
                    self._contexto_h1[simbolo] = {
                        'estado': estado,
                        'regimen': regimen,
                        'regimen_objeto': regimen_objeto,
                        'atr_macro': medio.atr,
                        'analisis': {'rapido': rapido, 'medio': medio, 'pesado': pesado},
                        'rapido': rapido,
                        'medio': medio,
                        'pesado': pesado,
                        'score': score_h1,
                        'direccion': direccion,
                        'timestamp': fecha_h1_actual,
                        'df_h1': df_h1_hasta,
                        'df_h4': df_h4,
                        'df_d1': df_d1,
                        'niveles': niveles,
                    }

            # SNIPER EVALUATION
            posiciones_actuales = len(self.posiciones_abiertas)
            if posiciones_actuales >= self.max_simultaneas:
                continue

            if self.ops_hoy >= self.max_ops_dia:
                continue

            for simbolo in list(self._contexto_h1.keys()):
                en_watchlist = simbolo in self.watchlist
                ctx = self._contexto_h1.get(simbolo)
                if not ctx:
                    continue

                score_h1 = ctx.get('score', 0)
                direccion_h1 = ctx.get('direccion', 'NEUTRAL')
                regimen_h1 = ctx.get('regimen', 'UNCERTAIN')
                regimen_objeto = ctx.get('regimen_objeto')

                if score_h1 < self.umbral_fase_1 and not en_watchlist:
                    continue

                cooldown_hasta = self.cooldowns_simbolos.get(simbolo)
                if cooldown_hasta and fecha_m5 < cooldown_hasta:
                    continue

                if any(p['simbolo'] == simbolo for p in self.posiciones_abiertas):
                    continue

                # FASE 2
                if not en_watchlist:
                    aprobado, motivo, contexto_m15 = self._validar_fase_2_consistente(
                        simbolo=simbolo,
                        fecha_m5=fecha_m5,
                        direccion_h1=direccion_h1,
                        regimen_h1=regimen_h1,
                        regimen_objeto=regimen_objeto
                    )

                    if not aprobado:
                        continue

                    score_m15 = contexto_m15.get('score_m15', 0) if contexto_m15 else 0

                    if len(self.watchlist) >= self.MAX_WATCHLIST_SIZE:
                        continue

                    self.watchlist[simbolo] = fecha_m5

                    estado = self.pipeline.obtener_estado(simbolo)
                    if estado:
                        estado.fase_actual = FaseOportunidad.FASE_3
                        estado.analisis_m15 = contexto_m15
                        estado.score_m15 = score_m15
                        self.pipeline.estados[simbolo] = estado
                        
                        if simbolo in self._contexto_h1:
                            self._contexto_h1[simbolo]['estado'] = estado
                            self._contexto_h1[simbolo]['m15_analisis'] = contexto_m15
                            self._contexto_h1[simbolo]['score_m15'] = score_m15

                    continue

                # FASE 3 - SNIPER
                if en_watchlist:
                    estado = self.pipeline.obtener_estado(simbolo)
                    
                    if not estado or estado.fase_actual != FaseOportunidad.FASE_3:
                        continue

                    disparo = self._evaluar_sniper_consistente(
                        simbolo=simbolo,
                        estado=estado,
                        ctx=ctx,
                        fecha_m5=fecha_m5
                    )

                    self.estadisticas_analisis['evaluaciones_sniper'] += 1

                    if not disparo:
                        self.estadisticas_analisis['rechazados_sniper'] += 1
                        continue

                    self.estadisticas_analisis['aprobados_sniper'] += 1
                    modo_aprobado = disparo.get('modo', 'DESCONOCIDO')
                    self.estadisticas_analisis['por_modo'][modo_aprobado]['aprobados'] += 1

                    score_m15 = estado.score_m15 if hasattr(estado, 'score_m15') else 0
                    score_m5 = disparo.get('score_m5', 0)
                    calificacion_m15 = ctx.get('m15_analisis', {}).get('calificacion', 'NEUTRO') if ctx.get('m15_analisis') else 'NEUTRO'

                    score_final = disparo.get('score_final', disparo.get('score', 0))
                    if not score_final:
                        score_final = self.score_engine.calcular_score_final(
                            score_h1=score_h1,
                            score_m15=score_m15,
                            score_m5=score_m5,
                            regimen=regimen_h1,
                            calificacion_m15=calificacion_m15,
                            simbolo=simbolo
                        ).score

                    # Actualizar estadísticas de scores
                    stats = self.estadisticas_analisis['scores_promedio']
                    stats['h1'] = (stats['h1'] * stats['count'] + score_h1) / (stats['count'] + 1)
                    stats['m15'] = (stats['m15'] * stats['count'] + score_m15) / (stats['count'] + 1)
                    stats['m5'] = (stats['m5'] * stats['count'] + score_m5) / (stats['count'] + 1)
                    stats['final'] = (stats['final'] * stats['count'] + score_final) / (stats['count'] + 1)
                    stats['count'] += 1

                    # Decisión de operabilidad
                    hora_utc = fecha_m5.hour + fecha_m5.minute / 60.0
                    
                    decision = self.decisor_operabilidad.decidir(
                        simbolo=simbolo,
                        score_final=score_final,
                        regimen=regimen_h1,
                        hora_utc=hora_utc,
                        score_h1=score_h1,
                        score_m15=score_m15,
                        score_m5=score_m5,
                        es_reversal=ctx.get('es_reversal', False),
                        en_nivel_clave=ctx.get('medio', {}).en_nivel_clave if ctx.get('medio') else False,
                        volumen_relativo=ctx.get('rapido', {}).volumen_relativo if ctx.get('rapido') else 1.0,
                        adx_h1=ctx.get('adx', 0),
                        patron_calidad=ctx.get('pesado', {}).calidad_patron if ctx.get('pesado') else 0,
                        ob_cercano=ctx.get('ob_cercano', False),
                        wyckoff_confianza=ctx.get('wyckoff_confianza', 0),
                        modo=modo_aprobado
                    )
                    
                    if not decision.operable:
                        self.estadisticas_analisis['motivos_rechazo'][f"OPERABILIDAD: {decision.razon}"] += 1
                        continue

                    disparo['score'] = score_final
                    disparo['score_final'] = score_final
                    disparo['spread_entrada'] = self._obtener_spread_simulado(simbolo, fecha_m5)

                    # Pre-ejecución
                    valido, motivo = self._validar_condiciones_pre_ejecucion(simbolo, disparo, fecha_m5)
                    if not valido:
                        self.estadisticas_analisis['rechazados_pre_ejecucion'] += 1
                        self.estadisticas_analisis['motivos_rechazo'][motivo] += 1
                        continue

                    # Ejecutar operación
                    self._ejecutar_operacion_sniper(simbolo, disparo, self.dataframes.get(simbolo, {}), fecha_m5)

                    self.pipeline.marcar_ejecutada(simbolo)
                    if simbolo in self.watchlist:
                        del self.watchlist[simbolo]
                    
                    if simbolo in self._contexto_h1:
                        del self._contexto_h1[simbolo]

                    self.cooldowns_simbolos[simbolo] = fecha_m5 + timedelta(hours=2)

                    self.logger.info(f"🎯 {simbolo}: OPERACIÓN EJECUTADA - {disparo.get('modo', 'DESCONOCIDO')} | "
                               f"Score Final: {score_final:.0f} | Equity: ${self.capital_actual:.2f}")

            # Actualizar stops
            for pos in self.posiciones_abiertas[:]:
                df_m5_simbolo = self.dataframes.get(pos['simbolo'], {}).get('M5')
                if df_m5_simbolo is not None:
                    self._actualizar_stop(pos, fecha_m5, df_m5_simbolo)

        # FIN DEL BACKTEST
        elapsed = time.time() - start_time

        self.logger.info("")
        self.logger.info(f"📊 BACKTEST COMPLETADO EN {elapsed:.2f}s")
        self.logger.info(f"💰 Capital final: ${self.capital_actual:.2f}")

        return self._calcular_metricas()

    # ================================================================
    # MÉTRICAS
    # ================================================================

    def _calcular_metricas(self):
        """Calcula métricas del backtest."""
        if not self.trades:
            return {
                'mensaje': 'Sin operaciones',
                'capital_final': self.capital_actual,
                'total_operaciones': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'net_profit': 0,
                'total_return': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'modo_evaluacion': self.modo_evaluacion,
                'fidelidad_real': self.fidelidad_real,
                'estadisticas_sniper': self.sniper_checklist.get_stats(),
                'estadisticas_analisis': dict(self.estadisticas_analisis),
                'scores_promedio': self.estadisticas_analisis['scores_promedio'],
                'rendimiento_por_modo': dict(self.estadisticas_analisis['rendimiento_por_modo']),
                'estadisticas_horario': dict(self.estadisticas_analisis.get('estadisticas_horario', {})),
            }

        df_trades = pd.DataFrame(self.trades)
        total = len(df_trades)
        ganadoras = df_trades[df_trades['pnl'] > 0]
        win_rate = len(ganadoras) / total * 100 if total > 0 else 0
        gross_profit = ganadoras['pnl'].sum() if not ganadoras.empty else 0
        gross_loss = abs(df_trades[df_trades['pnl'] < 0]['pnl'].sum()) if not df_trades[df_trades['pnl'] < 0].empty else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
        total_return = (self.capital_actual / self.capital_inicial - 1) * 100
        
        # Drawdown
        peak = self.capital_inicial
        max_dd = 0.0
        for val in self.equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd = max(0.0, (peak - val) / peak * 100)
                if dd > max_dd:
                    max_dd = dd

        # Sharpe Ratio
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

        rendimiento_por_modo = {}
        for modo, data in self.estadisticas_analisis['rendimiento_por_modo'].items():
            total_modo = data['total']
            if total_modo > 0:
                rendimiento_por_modo[modo] = {
                    'total': total_modo,
                    'ganadores': data['ganadores'],
                    'perdedores': data['perdedores'],
                    'winrate': data['ganadores'] / total_modo * 100,
                    'pnl_total': data['pnl_total'],
                    'pnl_promedio': data['pnl_total'] / total_modo,
                }

        return {
            'total_operaciones': total,
            'ganadoras': len(ganadoras),
            'perdedoras': total - len(ganadoras),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'net_profit': gross_profit - gross_loss,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'sharpe_ratio': sharpe,
            'capital_final': self.capital_actual,
            'trades': self.trades,
            'equity_curve': self.equity_curve,
            'modo_evaluacion': self.modo_evaluacion,
            'fidelidad_real': self.fidelidad_real,
            'estadisticas_sniper': self.sniper_checklist.get_stats(),
            'estadisticas_analisis': dict(self.estadisticas_analisis),
            'scores_promedio': self.estadisticas_analisis['scores_promedio'],
            'rendimiento_por_modo': rendimiento_por_modo,
            'estadisticas_horario': dict(self.estadisticas_analisis.get('estadisticas_horario', {})),
        }

    def guardar_reporte(self, ruta: Path):
        """Guarda reporte en JSON."""
        metricas = self._calcular_metricas()
        
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(metricas, f, indent=2, default=str)

    def guardar_equity_curve(self, ruta: Path):
        """Guarda equity curve en CSV."""
        import csv
        if not self.equity_curve or not self.timestamps:
            return

        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'equity'])
            for ts, eq in zip(self.timestamps, self.equity_curve):
                writer.writerow([ts.isoformat(), eq])


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_backtester(config: Config,
                      simbolos: List[str],
                      capital_inicial: float = 300.0,
                      **kwargs) -> BacktesterV2:
    """Crea una instancia del backtester."""
    return BacktesterV2(
        config=config,
        simbolos=simbolos,
        capital_inicial=capital_inicial,
        **kwargs
    )