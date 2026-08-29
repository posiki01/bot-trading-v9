#!/usr/bin/env python3
"""
backtesting/backtesting_bot.py (V9.2 - REFACTORIZADO COMPLETAMENTE)
Backtesting Engine que usa EXACTAMENTE el mismo código del bot real.
VERSIÓN REFACTORIZADA CON TODAS LAS DEPENDENCIAS INYECTADAS.
"""

import time
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import logging
import MetaTrader5 as mt5
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from collections import defaultdict
import json

# Agregar raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Config

# ============================================================
# IMPORTS DEL BOT REAL (V9.0) - EXACTAMENTE LOS MISMOS
# ============================================================

from analysis.tecnico import AnalisisTecnico
from analysis.capas import create_analisis_por_capas, AnalisisPorCapas
from analysis.fases import AnalisisPorFase
from analysis.pipeline import PipelineOportunidades, FaseOportunidad
from analysis.regimen import MarketRegimeFilter, RegimenMercado, RegimenData
from analysis.niveles import NivelTracker
from analysis.scoring import ScoreEngine, ScoreResultado
from trading.trailing import TrailingEngine, create_trailing_engine
from trading.riesgo import GestionRiesgo
from trading.stops import GestorStops, StopResultado
from trading.sniper import create_sniper_checklist, SniperChecklist, ModoEntrada
from trading.operabilidad import create_decisor_operabilidad, DecisorOperabilidad, DecisionOperabilidad
from trading.modos import ModoSelector
from trading.timer import EntryTimer
from trading.ejecucion import EjecutorOperaciones

from utils.tiempo import HorarioMercado
from utils.cache import CacheUnificado
from utils.logger_persistente import LoggerPersistente
from utils.helpers import safe_float, normalizar_precio

logger = logging.getLogger('BotTrading.BacktestingBot')


# ============================================================
# ALMACENAMIENTO MOCK (IDÉNTICO AL REAL PARA BACKTEST)
# ============================================================

class AlmacenMock:
    """Mock de almacenamiento para backtesting - SIMULA SQLite."""
    
    def __init__(self):
        self.niveles = {}
        self.operaciones = []
        self.configuracion = {}
        self.watchlist = {}
        self.directorio_base = Path("data/backtest")
        self.directorio_base.mkdir(parents=True, exist_ok=True)

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

    def guardar_oportunidad_no_tomada(self, op):
        pass

    def cerrar(self):
        pass


# ============================================================
# CLASE PRINCIPAL - BACKTESTER BOT (V9.2)
# ============================================================

class BacktesterBot:
    """
    Backtesting Engine que usa EXACTAMENTE el mismo código del bot real.
    V9.2 - REFACTORIZADO CON TODAS LAS DEPENDENCIAS INYECTADAS.
    """
    
    MAX_WATCHLIST_SIZE = 10
    MAX_CONTEXTO_H1_SIZE = 20

    def __init__(
        self,
        config: Config,
        simbolos: List[str],
        capital_inicial: float = 300.0,
        comision_por_lote: float = 1.0,
        slippage_pips: float = 0.5,
        max_simultaneas: int = 3,
        max_ops_dia: int = 10,
        risk_per_trade: float = 0.01,
        max_daily_drawdown: float = 0.06,
        sl_pips: int = 35,
        rr_objetivo: float = 1.5,
        umbral_fase_1: int = 20,
        modo_depuracion: bool = True,
        max_lote_absoluto: float = 0.005,
        dias_warmup: int = 5,
        use_ml: bool = False,
        **kwargs
    ):
        """Inicializa el backtester con los mismos módulos del bot real."""
        
        self.config = config
        self.simbolos = simbolos
        self.modo_forzado = kwargs.get('modo_forzado')
        self.dias_warmup = dias_warmup
        self.capital_inicial = capital_inicial
        self.capital_actual = capital_inicial
        self.comision_por_lote = comision_por_lote
        self.slippage_pips = slippage_pips
        self.max_simultaneas = max_simultaneas
        self.max_ops_dia = max_ops_dia
        self.risk_per_trade = risk_per_trade
        self.max_daily_drawdown = max_daily_drawdown
        self.umbral_fase_1 = umbral_fase_1
        self.modo_depuracion = modo_depuracion  # ✅ Guardado como atributo
        self.sl_pips = sl_pips
        self.rr_objetivo = rr_objetivo
        self.max_lote_absoluto = max_lote_absoluto
        self.use_ml = use_ml
        self.modo_backtest = True

        self.logger = logging.getLogger('BotTrading.BacktestingBot')
        self.almacen_simulado = AlmacenMock()

        # ============================================================
        # 1. INICIALIZAR MÓDULOS DEL BOT (IDÉNTICO AL BOT REAL)
        # ============================================================
        
        self.logger.info("🔧 Inicializando módulos del bot (V9.0)...")
        
        # Análisis
        self.analisis_tecnico = AnalisisTecnico()
        self.horario = HorarioMercado(zona_usuario='COLOMBIA', modo_backtest=True)
        self.cache = CacheUnificado(max_size=200, modo_backtest=True)
        
        # Score Engine
        self.score_engine = ScoreEngine(
            config=config,
            analysis_cache=self.cache,
            modo_backtest=True
        )
        
        # Análisis por Capas (✅ con analysis_cache)
        self.analisis_capas = create_analisis_por_capas(
            analisis_tecnico=self.analisis_tecnico,
            config=config,
            score_engine=self.score_engine,
            analysis_cache=self.cache,  # ✅ NUEVO
            modo_backtest=True
        )
        
        # Régimen de Mercado
        self.regimen_filter = MarketRegimeFilter(
            config=config, 
            modo_backtest=True
        )
        self.regimen_mercado = {}
        
        # Nivel Tracker
        self.nivel_tracker = NivelTracker(
            almacen=self.almacen_simulado,
            config=config,
            modo_backtest=True
        )
        
        # Pipeline de Oportunidades
        self.pipeline = PipelineOportunidades(
            config=config,
            modo_backtest=True,
            umbral_fase_1=umbral_fase_1
        )
        
        # Análisis por Fases
        self.analisis_fases = AnalisisPorFase(
            mt5_connector=None,
            noticias=None,
            config=config,
            analysis_cache=self.cache,
            modo_backtest=True,
            modo_depuracion=modo_depuracion
        )
        self.analisis_fases.set_analisis_capas(self.analisis_capas)
        
        # Modo Selector
        self.modo_selector = ModoSelector(
            config=config,
            modo_backtest=True,
            modo_depuracion=modo_depuracion
        )
        
        # Entry Timer
        self.entry_timer = EntryTimer(
            config=config,
            modo_backtest=True,
            modo_depuracion=modo_depuracion
        )
        self.modo_selector.set_entry_timer(self.entry_timer)
        
        # Gestor Stops
        self.gestor_stops = GestorStops(
            config=config, 
            modo_backtest=True
        )
        
        # Sniper Checklist (✅ CON TODAS LAS DEPENDENCIAS)
        self.sniper_checklist = create_sniper_checklist(
            pipeline=self.pipeline,
            analisis_capas=self.analisis_capas,
            modo_selector=self.modo_selector,
            entry_timer=self.entry_timer,
            gestor_stops=self.gestor_stops,
            analysis_cache=self.cache,  # ✅ NUEVO
            config=config,
            almacen=self.almacen_simulado,
            mt5=None,
            noticias=None,
            patron_tracker=None,
            ml_optimizer=None,
            modo_depuracion=modo_depuracion,
            modo_backtest=True
        )
        
        # Decisor de Operabilidad
        self.decisor_operabilidad = create_decisor_operabilidad(
            config=config,
            horario=self.horario,
            modo_backtest=True
        )

        self.trailing_engine = create_trailing_engine(
            config=config,
            modo_backtest=True,
            modo_depuracion=modo_depuracion
        )
        
        # Gestión de Riesgo
        self.gestion_riesgo = GestionRiesgo(
            capital_inicial=capital_inicial,
            almacen=self.almacen_simulado,
            modo_backtest=True
        )
        
        # Ejecutor de Operaciones (Mock para backtest)
        self.ejecutor = self._create_ejecutor_mock()
        
        self.logger.info("✅ Módulos del bot inicializados correctamente")

        # ============================================================
        # 2. ESTADOS INTERNOS
        # ============================================================
        
        self.posiciones_abiertas = []
        self.trades = []
        self.equity_curve = [capital_inicial]
        self.timestamps = []
        self.ops_hoy = 0
        self.dia_actual = None
        self.equity_inicio_dia = capital_inicial
        self.dataframes = {}
        self._contexto_h1 = {}
        self.watchlist = {}
        self.cooldowns_simbolos = {}
        self._h4_precargados = {}
        self._d1_precargados = {}
        self._ultima_limpieza_huérfanos = None
        self._factor_lote_noticias = 1.0

        # ============================================================
        # 3. ESTADÍSTICAS
        # ============================================================
        
        self.estadisticas = {
            'evaluaciones_sniper': 0,
            'aprobados_sniper': 0,
            'rechazados_sniper': 0,
            'por_modo': defaultdict(int),
            'motivos_rechazo': defaultdict(int),
            'scores_promedio': {'h1': 0, 'm15': 0, 'm5': 0, 'final': 0, 'count': 0},
            'analisis_realizados': 0,
            'senales_generadas': 0,
            'operaciones_ejecutadas': 0,
            'direcciones_por_modo': defaultdict(lambda: {'COMPRA': 0, 'VENTA': 0}),
            'trailing_metrics': {},
        }

        self.logger.info(f"📊 BacktesterBot V9.2 REFACTORIZADO")
        self.logger.info(f"   Símbolos: {len(simbolos)}")
        self.logger.info(f"   Capital: ${capital_inicial:.2f}")
        self.logger.info(f"   SL: {sl_pips}pips | R:R: {rr_objetivo}")
        self.logger.info(f"   Risk per trade: {risk_per_trade:.1%}")
        self.logger.info(f"   Max ops/día: {max_ops_dia} | Max simultáneas: {max_simultaneas}")

    # ================================================================
    # 4. CREAR EJECUTOR MOCK (PARA BACKTEST)
    # ================================================================

    def _create_ejecutor_mock(self):
        """Crea un ejecutor mock para backtest."""
        class EjecutorMock:
            def __init__(self, parent):
                self.parent = parent
            
            def ejecutar(self, op):
                return self.parent._ejecutar_operacion_backtest(op)
        
        return EjecutorMock(self)

    # ================================================================
    # 5. DESCARGA DE DATOS
    # ================================================================

    def _descargar_datos(self, simbolo: str, inicio: datetime, fin: datetime) -> Optional[Dict[str, pd.DataFrame]]:
        """Descarga datos de MT5."""
        self.logger.info(f"   📥 Descargando {simbolo}...")
        
        if not mt5.initialize():
            self.logger.error(f"   ❌ {simbolo}: No se pudo inicializar MT5")
            return None
        
        if not mt5.symbol_select(simbolo, True):
            self.logger.error(f"   ❌ {simbolo}: No existe en Market Watch")
            mt5.shutdown()
            return None
        
        dfs = {}
        tfs = {
            'H1': mt5.TIMEFRAME_H1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
        }
        
        for name, tf in tfs.items():
            try:
                rates = mt5.copy_rates_range(simbolo, tf, inicio, fin)
            except Exception as e:
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
            self.logger.error(f"   ❌ {simbolo}: Datos insuficientes")
            return None
        
        self.logger.info(f"   ✅ {simbolo}: {len(dfs)} timeframes descargados")
        return dfs

    def _resamplear_h4(self, df_h1: pd.DataFrame) -> pd.DataFrame:
        if df_h1 is None or df_h1.empty:
            return pd.DataFrame()
        return df_h1.resample('4h').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min',
            'Close': 'last', 'Volume': 'sum'
        }).dropna()

    def _resamplear_d1(self, df_h1: pd.DataFrame) -> pd.DataFrame:
        if df_h1 is None or df_h1.empty:
            return pd.DataFrame()
        return df_h1.resample('D').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min',
            'Close': 'last', 'Volume': 'sum'
        }).dropna()

    # ================================================================
    # 6. DETERMINAR DIRECCIÓN (IDÉNTICO AL BOT REAL)
    # ================================================================

    def _determinar_direccion_mejorado(self, medio, pesado, df_h4=None, df_h1=None, regimen: Optional[str] = None) -> str:
        """
        Determina la dirección basada en análisis técnico y RÉGIMEN.
        """
        # ✅ PRIORIDAD 1: Régimen claro
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            return 'COMPRA'
        
        if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            return 'VENTA'
        
        # ✅ PRIORIDAD 2: Análisis técnico (si el régimen no es claro)
        bullish = 0
        bearish = 0
        
        if medio:
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
        
        if pesado:
            if pesado.divergencia_rsi == 'BULLISH':
                bullish += 2
            elif pesado.divergencia_rsi == 'BEARISH':
                bearish += 2
            
            if pesado.wyckoff_fase in ['ACUMULACION', 'SPRING']:
                bullish += 2
            elif pesado.wyckoff_fase in ['DISTRIBUCION', 'UPTHRUST']:
                bearish += 2
        
        if bullish > bearish + 1:
            return 'COMPRA'
        elif bearish > bullish + 1:
            return 'VENTA'
        return 'NEUTRAL'

    # ================================================================
    # 7. CLASIFICAR RÉGIMEN (IDÉNTICO AL BOT REAL)
    # ================================================================

    def _clasificar_regimen(self, simbolo: str, df_h4: pd.DataFrame, df_h1: pd.DataFrame) -> RegimenData:
        """Clasifica régimen usando el filtro real del bot."""
        try:
            return self.regimen_filter.clasificar(simbolo, df_h4, df_h1)
        except Exception as e:
            self.logger.debug(f"Error clasificando régimen {simbolo}: {e}")
            # Fallback por EMAs
            if df_h1 is not None and len(df_h1) >= 50:
                close = df_h1['Close']
                ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
                ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
                
                if ema20 > ema50 * 1.01:
                    return RegimenData(
                        regimen=RegimenMercado.TREND_ALCISTA_DEBIL,
                        confianza=50,
                        adx_h4=0, adx_h1=0, er_kaufman=0,
                        bb_width_pct=50, atr_pct=0.5,
                        estructura_swings='ALCISTA',
                        direccion_favor='ALCISTA'
                    )
                elif ema20 < ema50 * 0.99:
                    return RegimenData(
                        regimen=RegimenMercado.TREND_BAJISTA_DEBIL,
                        confianza=50,
                        adx_h4=0, adx_h1=0, er_kaufman=0,
                        bb_width_pct=50, atr_pct=0.5,
                        estructura_swings='BAJISTA',
                        direccion_favor='BAJISTA'
                    )
            
            return RegimenData(
                regimen=RegimenMercado.INCERTO,
                confianza=30,
                adx_h4=0, adx_h1=0, er_kaufman=0,
                bb_width_pct=50, atr_pct=0.5,
                estructura_swings='DESCONOCIDO',
                direccion_favor='NONE'
            )

    # ================================================================
    # 8. EJECUCIÓN DE OPERACIONES EN BACKTEST
    # ================================================================

    def _ejecutar_operacion_backtest(self, disparo: Dict) -> bool:
        """
        Ejecuta una operación en backtest.
        V9.2 - REFACTORIZADO CON VALIDACIONES ROBUSTAS Y GESTOR STOPS REAL.
        
        Args:
            disparo: Diccionario con la señal del sniper
            
        Returns:
            True si la operación se ejecutó correctamente
        """
        simbolo = disparo.get('simbolo', '')
        direccion = disparo.get('direccion', 'NEUTRAL')
        precio = disparo.get('entry_price', 0)
        modo = disparo.get('modo', 'RETEST')
        score = disparo.get('score_final', disparo.get('score', 50))
        
        # ============================================================
        # 1. VALIDACIONES BÁSICAS
        # ============================================================
        
        if direccion == 'NEUTRAL' or precio <= 0:
            self.estadisticas['motivos_rechazo']['direccion_invalida'] += 1
            self.logger.debug(f"   ⏭️ {simbolo}: Dirección inválida o precio 0")
            return False
        
        # Verificar límites
        if len(self.posiciones_abiertas) >= self.max_simultaneas:
            self.estadisticas['motivos_rechazo']['limite_simultaneas'] += 1
            self.logger.debug(f"   ⏭️ {simbolo}: Límite simultáneas alcanzado")
            return False
        
        if self.ops_hoy >= self.max_ops_dia:
            self.estadisticas['motivos_rechazo']['limite_diario'] += 1
            self.logger.debug(f"   ⏭️ {simbolo}: Límite diario alcanzado")
            return False
        
        # ============================================================
        # 2. OBTENER PARÁMETROS DEL SÍMBOLO
        # ============================================================
        
        pip_val = self._obtener_pip_val(simbolo)
        digits = self._obtener_digits(simbolo)
        
        # Obtener régimen del contexto
        regimen = 'INCERTO'
        contexto = self._contexto_h1.get(simbolo, {})
        if contexto and 'regimen' in contexto:
            regimen = contexto.get('regimen', 'INCERTO')
        
        # Calidad de horario
        calidad_horario = disparo.get('calidad_horario', 'REGULAR')
        en_nivel_clave = disparo.get('en_nivel_clave', False)
        es_reversal = disparo.get('es_reversal', False)
        
        # ============================================================
        # 3. CALCULAR SL/TP CON PARÁMETROS DINÁMICOS
        # ============================================================
        
        # ✅ OBTENER SL MÍNIMO POR ACTIVO
        sl_min_activo = self._obtener_sl_minimo_por_activo(simbolo)
        
        # ✅ USAR SL_PIPS DEL CONSTRUCTOR (o valor por defecto)
        sl_pips_usar = getattr(self, 'sl_pips', 35)
        sl_dist_pips = max(sl_min_activo, sl_pips_usar)
        
        # ✅ CALCULAR SL INICIAL
        if direccion == 'COMPRA':
            sl = precio - (sl_dist_pips * pip_val)
        else:
            sl = precio + (sl_dist_pips * pip_val)
        
        # ✅ CALCULAR TP INICIAL CON RR_OBJETIVO DEL CONSTRUCTOR
        rr_objetivo = getattr(self, 'rr_objetivo', 1.5)
        
        # Ajustar R:R según régimen
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
            rr_objetivo = rr_objetivo * 1.1
        elif regimen in ['RANGO_APRETADO', 'CHOP_VOLATIL']:
            rr_objetivo = rr_objetivo * 0.9
        
        if direccion == 'COMPRA':
            tp = precio + (sl_dist_pips * rr_objetivo * pip_val)
        else:
            tp = precio - (sl_dist_pips * rr_objetivo * pip_val)
        
        # ============================================================
        # 4. VALIDAR CON GESTOR STOPS REAL
        # ============================================================
        
        if self.gestor_stops:
            valido, razon, sl_validado, tp_validado, tp2_validado = self.gestor_stops.validar_sl_tp(
                simbolo=simbolo,
                entry_price=precio,
                sl=sl,
                tp=tp,
                tp2=0,
                direccion=direccion,
                regimen=regimen,
                modo=modo,
                es_reversal=es_reversal,
                en_nivel_clave=en_nivel_clave,
                calidad_horario=calidad_horario
            )
            
            if valido:
                sl = sl_validado
                tp = tp_validado
                tp2 = tp2_validado if tp2_validado else 0
                self.logger.debug(f"   ✅ {simbolo}: GestorStops validó SL/TP")
            else:
                # Fallback con parámetros del constructor
                self.estadisticas['motivos_rechazo']['gestor_stops_rechazo'] += 1
                self.logger.debug(f"   ⚠️ {simbolo}: GestorStops falló ({razon}), usando fallback")
                sl, tp = self._calcular_sl_tp_fallback(simbolo, precio, direccion, modo)
        else:
            # Si no hay gestor_stops, usar valores calculados
            self.logger.debug(f"   ⚠️ {simbolo}: Sin GestorStops, usando valores calculados")
            tp2 = 0
        
        # ============================================================
        # 5. CALCULAR R:R FINAL Y VALIDAR (CON UMBRAL DINÁMICO)
        # ============================================================
        
        sl_dist = abs(precio - sl)
        tp_dist = abs(tp - precio)
        rr = tp_dist / sl_dist if sl_dist > 0 else 0
        sl_dist_pips_final = sl_dist / pip_val if pip_val > 0 else 0
        
        # ✅ UMBRAL R:R DINÁMICO (igual al bot real)
        rr_min = 0.80 if self.modo_backtest else 1.0
        
        # Ajuste por régimen
        if regimen in ['RANGO_APRETADO', 'CHOP_VOLATIL']:
            rr_min = rr_min * 0.9
        
        if rr < rr_min:
            self.estadisticas['motivos_rechazo']['rr_insuficiente'] += 1
            self.logger.debug(f"   ⏭️ {simbolo}: R:R insuficiente ({rr:.2f} < {rr_min})")
            return False
        
        # ============================================================
        # 6. CALCULAR LOTES (con gestión de riesgo real)
        # ============================================================
        
        riesgo_max_usd = self.capital_actual * self.risk_per_trade
        pip_value_per_lot = self._obtener_pip_value_por_lote(simbolo)
        pip_value_por_0_01 = pip_value_per_lot * 0.01
        
        if sl_dist_pips_final > 0 and pip_value_por_0_01 > 0:
            lotes = riesgo_max_usd / (sl_dist_pips_final * pip_value_por_0_01)
        else:
            lotes = 0.01
        
        # Factor de confianza (Kelly simplificado)
        if score >= 80:
            factor_confianza = 1.2
        elif score >= 65:
            factor_confianza = 1.0
        else:
            factor_confianza = 0.7
        
        lotes = lotes * factor_confianza
        lotes = max(0.001, min(self.max_lote_absoluto, lotes))
        lotes = round(lotes, 3)
        
        # ============================================================
        # 7. VERIFICAR CAPITAL SUFICIENTE
        # ============================================================
        
        margen_requerido = lotes * 100  # Estimación simple
        if self.capital_actual < margen_requerido:
            self.estadisticas['motivos_rechazo']['capital_insuficiente'] += 1
            self.logger.debug(f"   ⏭️ {simbolo}: Capital insuficiente para {lotes:.3f} lotes")
            return False
        
        # ============================================================
        # 8. CREAR OPERACIÓN
        # ============================================================
        
        op = {
            'simbolo': simbolo,
            'direccion': direccion,
            'entrada': precio,
            'sl': sl,
            'tp': tp,
            'tp2': tp2 or 0,
            'lotes': lotes,
            'fecha_entrada': self._fecha_actual,
            'estado': 'ABIERTA',
            'ticket': len(self.trades) + 1,
            'score': score,
            'modo': modo,
            'regimen': regimen,
            'sl_original': sl,
            'pnl_acumulado': 0.0,
            'tp1_realizado': False,
            'tp2_realizado': False,
            'es_reversal': es_reversal,
            'en_nivel_clave': en_nivel_clave,
            'calidad_horario': calidad_horario,
            'sl_dist_pips': sl_dist_pips_final,
            'rr': rr,
            'rr_min_umbral': rr_min,
            'precio_entrada': precio,
            'precio_salida': None,
            'pips': 0,
            'pnl': 0,
            'motivo_cierre': None,
            'fecha_salida': None,
            # ✅ Guardar contexto de entrada completo
            'contexto_entrada': {
                'score_h1': contexto.get('score', 0),
                'score_m5': disparo.get('score_m5', 0),
                'regimen': regimen,
                'modo': modo,
                'calidad_horario': calidad_horario,
                'en_nivel_clave': en_nivel_clave,
                'es_reversal': es_reversal,
                'volumen_relativo': disparo.get('volumen_relativo', 1.0),
                'adx_h1': contexto.get('medio', {}).get('adx', 0) if contexto.get('medio') else 0,
            }
        }
        
        # ============================================================
        # 9. EJECUTAR (Añadir a posiciones abiertas)
        # ============================================================
        
        self.posiciones_abiertas.append(op)
        self.ops_hoy += 1
        
        # ✅ Registrar por modo para estadísticas
        self.estadisticas['por_modo'][modo] += 1
        self.estadisticas['direcciones_por_modo'][modo][direccion] += 1
        
        # ============================================================
        # 10. LOG DETALLADO DE ENTRADA
        # ============================================================
        
        self.logger.info(
            f"📈 ENTRADA {simbolo} {direccion} @ {precio:.{digits}f} | "
            f"SL: {sl:.{digits}f} ({sl_dist_pips_final:.1f}pips) | "
            f"TP: {tp:.{digits}f} | "
            f"R:R: {rr:.2f} (mín: {rr_min}) | "
            f"Lotes: {lotes:.3f} | "
            f"Score: {score:.0f} | "
            f"Modo: {modo} | "
            f"Régimen: {regimen} | "
            f"Calidad: {calidad_horario}"
        )
        
        return True


    def _calcular_sl_tp_fallback(self, simbolo: str, precio: float, direccion: str, modo: str) -> tuple:
        """
        Fallback para SL/TP usando parámetros del constructor.
        """
        pip_val = self._obtener_pip_val(simbolo)
        digits = self._obtener_digits(simbolo)
        
        sl_pips_usar = getattr(self, 'sl_pips', 35)
        sl_min = self._obtener_sl_minimo_por_activo(simbolo)
        sl_pips = max(sl_min, sl_pips_usar)
        
        rr_usar = getattr(self, 'rr_objetivo', 1.5)
        
        if direccion == 'COMPRA':
            sl = precio - (sl_pips * pip_val)
            tp = precio + (sl_pips * rr_usar * pip_val)
        else:
            sl = precio + (sl_pips * pip_val)
            tp = precio - (sl_pips * rr_usar * pip_val)
        
        return round(sl, digits), round(tp, digits)

    def _obtener_sl_minimo_por_activo(self, simbolo: str) -> float:
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
            return 15.0
        return 20.0

    def _obtener_pip_value_por_lote(self, simbolo: str) -> float:
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 10.0
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 10.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 10.0

    # ================================================================
    # 9. ACTUALIZAR POSICIONES CON TRAILING ENGINE REAL
    # ================================================================

    def _actualizar_posiciones(self, fecha: datetime):
        """
        Actualiza posiciones abiertas usando el TRAILING ENGINE REAL.
        """
        if not self.posiciones_abiertas:
            return
        
        for pos in self.posiciones_abiertas[:]:
            if pos['estado'] != 'ABIERTA':
                continue
            
            simbolo = pos['simbolo']
            df_m5 = self.dataframes.get(simbolo, {}).get('M5')
            if df_m5 is None:
                continue
            
            df_hasta = df_m5.loc[:fecha]
            if len(df_hasta) < 2:
                continue
            
            precio_actual = df_hasta['Close'].iloc[-1]
            pip_val = self._obtener_pip_val(simbolo)
            
            # Verificar SL/TP (primero, antes del trailing)
            if pos['direccion'] == 'COMPRA':
                if df_hasta['Low'].min() <= pos['sl']:
                    self._cerrar_posicion(pos, fecha, pos['sl'], "SL")
                    continue
                if df_hasta['High'].max() >= pos['tp']:
                    self._cerrar_posicion(pos, fecha, pos['tp'], "TP")
                    continue
            else:
                if df_hasta['High'].max() >= pos['sl']:
                    self._cerrar_posicion(pos, fecha, pos['sl'], "SL")
                    continue
                if df_hasta['Low'].min() <= pos['tp']:
                    self._cerrar_posicion(pos, fecha, pos['tp'], "TP")
                    continue
            
            # ============================================================
            # ✅ USAR TRAILING ENGINE REAL
            # ============================================================
            
            # Calcular ganancia en pips
            if pos['direccion'] == 'COMPRA':
                ganancia_pips = (precio_actual - pos['entrada']) / pip_val if pip_val > 0 else 0
            else:
                ganancia_pips = (pos['entrada'] - precio_actual) / pip_val if pip_val > 0 else 0
            
            # Obtener régimen
            regimen = pos.get('regimen', 'INCERTO')
            modo = pos.get('modo', 'RETEST')
            
            # Obtener H1 para reanálisis
            df_h1 = self.dataframes.get(simbolo, {}).get('H1')
            if df_h1 is not None:
                df_h1_hasta = df_h1.loc[:fecha]
            else:
                df_h1_hasta = None
            
            # Crear estructura de posición para el trailing engine
            pos_data = {
                'simbolo': simbolo,
                'direccion': pos['direccion'],
                'entrada': pos['entrada'],
                'sl': pos['sl'],
                'fecha_entrada': pos['fecha_entrada'],
                'nivel_usado': pos.get('nivel_usado', 0),
            }
            
            # Calcular decisión de trailing
            decision = self.trailing_engine.calcular_movimiento_sl(
                pos=pos_data,
                df_h1=df_h1_hasta,
                precio_actual=precio_actual,
                fecha=fecha,
                regimen=regimen,
                modo=modo
            )
            
            # Aplicar decisión
            if decision.cerrar:
                self._cerrar_posicion(pos, fecha, precio_actual, decision.motivo_cierre or decision.razon)
                continue
            
            if decision.mover_sl and decision.nuevo_sl:
                # Guardar SL anterior para análisis
                pos['sl_anterior'] = pos['sl']
                
                # Validar que mejora el SL
                if pos['direccion'] == 'COMPRA' and decision.nuevo_sl > pos['sl']:
                    pos['sl'] = decision.nuevo_sl
                    
                    # ✅ ANALIZAR Y ACUMULAR
                    self._analizar_trailing_y_acumular(
                        pos=pos,
                        fecha=fecha,
                        precio_actual=precio_actual,
                        decision=decision,
                        ganancia_pips=ganancia_pips
                    )
                    
                    if self.modo_depuracion:
                        self.logger.debug(f"   🔄 {simbolo}: SL movido a {decision.nuevo_sl:.5f} ({decision.razon})")
                
                elif pos['direccion'] == 'VENTA' and decision.nuevo_sl < pos['sl']:
                    pos['sl'] = decision.nuevo_sl
                    
                    # ✅ ANALIZAR Y ACUMULAR
                    self._analizar_trailing_y_acumular(
                        pos=pos,
                        fecha=fecha,
                        precio_actual=precio_actual,
                        decision=decision,
                        ganancia_pips=ganancia_pips
                    )
                    
                    if self.modo_depuracion:
                        self.logger.debug(f"   🔄 {simbolo}: SL movido a {decision.nuevo_sl:.5f} ({decision.razon})")
            
            # ============================================================
            # VERIFICAR TIMEOUT (también del trailing engine)
            # ============================================================
            
            debe_cerrar, motivo = self.trailing_engine.verificar_timeout(
                pos=pos_data,
                fecha=fecha,
                ganancia_pips=ganancia_pips,
                modo=modo
            )
            
            if debe_cerrar:
                self._cerrar_posicion(pos, fecha, precio_actual, motivo)
                continue
            
            # ============================================================
            # VERIFICAR CIERRE PARCIAL (TP1)
            # ============================================================
            
            debe_cerrar_parcial, volumen_a_cerrar = self.trailing_engine.verificar_cierre_parcial(
                pos=pos_data,
                ganancia_pips=ganancia_pips,
                modo=modo
            )
            
            if debe_cerrar_parcial and not pos.get('tp1_realizado', False):
                if self.modo_depuracion:
                    self.logger.debug(
                        f"   🎯 {simbolo}: Cierre parcial {volumen_a_cerrar:.3f} lotes "
                        f"({ganancia_pips:.1f}pips)"
                    )
                # En backtest, cerramos parcialmente ajustando el lote
                pos['tp1_realizado'] = True
                pos['lotes'] = max(0.001, pos['lotes'] - volumen_a_cerrar)

    def _cerrar_posicion(self, pos, fecha, precio_salida, motivo):
        """Cierra una posición y guarda estadísticas de trailing."""
        if pos['estado'] != 'ABIERTA':
            return
        
        simbolo = pos['simbolo']
        pip_val = self._obtener_pip_val(simbolo)
        pip_value_per_lot = self._obtener_pip_value_por_lote(simbolo)
        
        if pos['direccion'] == 'COMPRA':
            pips = (precio_salida - pos['entrada']) / pip_val if pip_val > 0 else 0
        else:
            pips = (pos['entrada'] - precio_salida) / pip_val if pip_val > 0 else 0
        
        pnl = pips * pip_value_per_lot * pos['lotes']
        pnl = pnl - (self.comision_por_lote * pos['lotes'] * 2)
        
        self.capital_actual += pnl
        pos['pnl'] = pnl
        pos['estado'] = 'CERRADA'
        pos['precio_salida'] = precio_salida
        pos['motivo_cierre'] = motivo
        pos['fecha_salida'] = fecha
        
        # ✅ REGISTRAR ESTADÍSTICAS FINALES DE TRAILING
        if simbolo in self.estadisticas.get('trailing_metrics', {}):
            stats = self.estadisticas['trailing_metrics'][simbolo]
            pos['trailing_stats'] = {
                'total_movimientos': stats['total_movimientos'],
                'movimientos_exitosos': stats['movimientos_exitosos'],
                'total_pips_protegidos': stats['total_pips_protegidos'],
                'fases_alcanzadas': dict(stats['fases_alcanzadas']),
            }
        
        self.trades.append(pos.copy())
        self.posiciones_abiertas.remove(pos)
        self.equity_curve.append(self.capital_actual)
        self.timestamps.append(fecha)
        
        self.logger.info(
            f"📊 CIERRE {simbolo} {pos['direccion']} | "
            f"PnL: ${pnl:.2f} | Motivo: {motivo} | Equity: ${self.capital_actual:.2f}"
        )
    # ================================================================
    # 10. UTILIDADES
    # ================================================================

    def _obtener_pip_val(self, simbolo: str) -> float:
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 0.10
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001

    def _obtener_pip_value_por_lote(self, simbolo: str) -> float:
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 10.0
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 10.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 10.0

    def _obtener_digits(self, simbolo: str) -> int:
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 3
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 2
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 2
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 2
        return 5

    # ================================================================
    # 11. LIMPIEZAS
    # ================================================================

    def _limpiar_watchlist_timeout(self, fecha_actual: datetime):
        for simbolo in list(self.watchlist.keys()):
            ts = self.watchlist.get(simbolo)
            if ts and (fecha_actual - ts).total_seconds() > 2 * 3600:
                del self.watchlist[simbolo]
        
        if len(self.watchlist) > self.MAX_WATCHLIST_SIZE:
            sorted_items = sorted(self.watchlist.items(), key=lambda x: x[1])
            for simbolo, _ in sorted_items[:-self.MAX_WATCHLIST_SIZE]:
                del self.watchlist[simbolo]

    def _limpiar_contexto_antiguo(self, fecha_actual: datetime):
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

    # ================================================================
    # 12. MÉTODO PRINCIPAL RUN
    # ================================================================

    def run(self, fecha_inicio: datetime, fecha_fin: datetime) -> Dict[str, Any]:
        """Ejecuta el backtest usando el bot real."""
        start_time = time.time()

        self.logger.info(f"🚀 INICIANDO BACKTEST CON BOT REAL V9.2 REFACTORIZADO")
        self.logger.info(f"📅 Rango: {fecha_inicio} → {fecha_fin}")

        # ============================================================
        # 1. DESCARGAR DATOS
        # ============================================================
        
        self.logger.info("📥 DESCARGANDO DATOS...")
        
        for simbolo in self.simbolos:
            dfs = self._descargar_datos(simbolo, fecha_inicio, fecha_fin)
            if dfs is None:
                self.logger.error(f"❌ {simbolo}: DESCARGA FALLIDA")
                continue
            
            self.dataframes[simbolo] = dfs
            self._h4_precargados[simbolo] = self._resamplear_h4(dfs.get('H1', pd.DataFrame()))
            self._d1_precargados[simbolo] = self._resamplear_d1(dfs.get('H1', pd.DataFrame()))

        if not self.dataframes:
            self.logger.error("❌ No se descargaron datos")
            return {'error': 'No data'}

        # ============================================================
        # 2. CALCULAR FECHAS COMUNES
        # ============================================================

        fechas_h1 = None
        fechas_m5 = None
        
        for simbolo, dfs in self.dataframes.items():
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

        # ============================================================
        # 3. BUCLE PRINCIPAL
        # ============================================================

        for idx, fecha_m5 in enumerate(fechas_m5_comunes):
            self._fecha_actual = fecha_m5
            
            if idx % 500 == 0 and idx > 0:
                elapsed = time.time() - start_time
                self.logger.info(f"⏳ Progreso: {idx/total_velas*100:.1f}% | "
                        f"Ops: {len(self.trades)} | Equity: ${self.capital_actual:.2f}")

            if fecha_m5.tzinfo is None:
                fecha_m5 = fecha_m5.replace(tzinfo=timezone.utc)

            # Reset diario
            if self.dia_actual != fecha_m5.date():
                self.dia_actual = fecha_m5.date()
                self.ops_hoy = 0
                self.equity_inicio_dia = self.capital_actual

            # Procesar nueva vela H1
            fecha_h1_actual = fecha_m5.floor('h')
            idx_h1 = pos_h1.get(fecha_h1_actual)
            
            if idx_h1 is None or idx_h1 < 20:
                continue

            hay_h1_nueva = (ultima_hora_h1_procesada is None or fecha_h1_actual > ultima_hora_h1_procesada) and fecha_h1_actual in set_fechas_h1

            if hay_h1_nueva:
                ultima_hora_h1_procesada = fecha_h1_actual
                self.estadisticas['analisis_realizados'] += 1
                
                for simbolo, dfs in self.dataframes.items():
                    df_h1_hasta = dfs.get('H1', pd.DataFrame()).loc[:fecha_h1_actual]
                    
                    # ✅ VERIFICAR DATOS SUFICIENTES
                    if len(df_h1_hasta) < 50:
                        self.logger.debug(f"⏭️ {simbolo}: Datos insuficientes ({len(df_h1_hasta)} < 50)")
                        continue
                    
                    df_h4 = self._h4_precargados.get(simbolo, pd.DataFrame()).loc[:fecha_h1_actual]
                    df_d1 = self._d1_precargados.get(simbolo, pd.DataFrame()).loc[:fecha_h1_actual]
                    
                    try:
                        # ============================================================
                        # ANÁLISIS CAPA 1: RÁPIDO
                        # ============================================================
                        
                        rapido = self.analisis_capas.analisis_rapido(df_h1_hasta, simbolo)
                        if not rapido.pasa_filtro:
                            self.logger.debug(f"⏭️ {simbolo}: filtro rápido falló - {rapido.razon_rechazo}")
                            continue
                        
                        # ============================================================
                        # DETECCIÓN DE NIVELES
                        # ============================================================
                        
                        precio_actual = df_h1_hasta['Close'].iloc[-1]
                        niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
                            simbolo=simbolo,
                            df=df_h1_hasta,
                            precio_actual=precio_actual
                        )
                        
                        soportes = niveles.get('soportes', [])
                        resistencias = niveles.get('resistencias', [])
                        
                        # ============================================================
                        # ANÁLISIS CAPA 2: MEDIO
                        # ============================================================
                        
                        medio = self.analisis_capas.analisis_medio(
                            df_h1_hasta, simbolo, rapido, niveles
                        )
                        
                        if medio is None:
                            self.logger.debug(f"⏭️ {simbolo}: análisis medio devolvió None")
                            continue
                        
                        # ✅ VERIFICAR QUE medio TENGA ATRIBUTOS
                        if not hasattr(medio, 'rsi') or medio.rsi is None:
                            self.logger.debug(f"⏭️ {simbolo}: medio.rsi es None")
                            continue
                        if not hasattr(medio, 'macd_histogram') or medio.macd_histogram is None:
                            self.logger.debug(f"⏭️ {simbolo}: medio.macd_histogram es None")
                            continue
                        if not hasattr(medio, 'adx') or medio.adx is None:
                            self.logger.debug(f"⏭️ {simbolo}: medio.adx es None")
                            continue
                        if not hasattr(medio, 'sma20') or medio.sma20 is None:
                            self.logger.debug(f"⏭️ {simbolo}: medio.sma20 es None")
                            continue
                        if not hasattr(medio, 'sma50') or medio.sma50 is None:
                            self.logger.debug(f"⏭️ {simbolo}: medio.sma50 es None")
                            continue
                        
                        if not medio.pasa_filtro:
                            self.logger.debug(f"⏭️ {simbolo}: filtro medio falló - {medio.razon_rechazo}")
                            continue
                        
                        # ============================================================
                        # ANÁLISIS CAPA 3: PESADO
                        # ============================================================
                        
                        pesado = self.analisis_capas.analisis_pesado(
                            df_h1_hasta, simbolo, df_h4, df_d1, niveles, medio
                        )
                        
                        if pesado is None:
                            self.logger.debug(f"⏭️ {simbolo}: análisis pesado devolvió None")
                            continue
                        
                        # ✅ VERIFICAR QUE pesado TENGA ATRIBUTOS
                        if not hasattr(pesado, 'divergencia_rsi'):
                            self.logger.debug(f"⏭️ {simbolo}: pesado.divergencia_rsi no existe")
                            continue
                        if not hasattr(pesado, 'wyckoff_fase'):
                            self.logger.debug(f"⏭️ {simbolo}: pesado.wyckoff_fase no existe")
                            continue
                        
                        # ============================================================
                        # CALCULAR SCORE H1
                        # ============================================================
                        
                        score_h1 = self.score_engine.calcular_score_h1(
                            score_estructura=pesado.score_estructura,
                            score_momentum=pesado.score_momentum,
                            score_confluencia=pesado.score_confluencia,
                            score_institucional=pesado.score_institucional,
                            simbolo=simbolo
                        ).score
                        
                        # ============================================================
                        # CLASIFICAR RÉGIMEN
                        # ============================================================
                        
                        regimen_data = self._clasificar_regimen(simbolo, df_h4, df_h1_hasta)
                        regimen = regimen_data.regimen.value
                        self.regimen_mercado[simbolo] = regimen_data
                        
                        # ============================================================
                        # DETERMINAR DIRECCIÓN - VERSIÓN MEJORADA
                        # ============================================================
                        
                        direccion = self._determinar_direccion_mejorado(
                            medio, 
                            pesado, 
                            df_h4=df_h4, 
                            df_h1=df_h1_hasta,
                            regimen=regimen
                        )
                        
                        # ============================================================
                        # LOG DE DIAGNÓSTICO
                        # ============================================================
                        
                        if self.modo_depuracion and direccion != 'NEUTRAL':
                            self.logger.info(
                                f"🔍 {simbolo}: DIRECCIÓN DETECTADA = {direccion} | "
                                f"Score={score_h1:.1f} | "
                                f"Régimen={regimen}"
                            )
                        
                        # ============================================================
                        # SI ES NEUTRAL, NO GUARDAR
                        # ============================================================
                        
                        if direccion == 'NEUTRAL':
                            if simbolo in self._contexto_h1:
                                del self._contexto_h1[simbolo]
                            continue
                        
                        # ============================================================
                        # ACTUALIZAR PIPELINE (SOLO CON DIRECCIÓN VÁLIDA)
                        # ============================================================
                        
                        estado = self.pipeline.actualizar_fase_1(
                            simbolo=simbolo,
                            analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
                            score=score_h1,
                            direccion=direccion,
                            regimen=regimen,
                            direccion_regimen=regimen_data.direccion_favor,
                            confianza_regimen=regimen_data.confianza,
                            tendencia_h4='ALCISTA' if medio.adx > 25 and medio.sma20 > medio.sma50 else 'BAJISTA' if medio.adx > 25 else 'LATERAL'
                        )
                        
                        # ============================================================
                        # ✅ GUARDAR CONTEXTO H1 SIEMPRE
                        # ============================================================
                        
                        if direccion != 'NEUTRAL':
                            self._contexto_h1[simbolo] = {
                                'estado': estado,
                                'score': score_h1,
                                'direccion': direccion,
                                'regimen': regimen,
                                'rapido': rapido,
                                'medio': medio,
                                'pesado': pesado,
                                'niveles': niveles,
                                'timestamp': fecha_h1_actual,
                                'regimen_data': regimen_data,
                                'en_nivel_clave': medio.en_nivel_clave if hasattr(medio, 'en_nivel_clave') else False,
                                'soporte_cercano': medio.soporte_cercano if hasattr(medio, 'soporte_cercano') else None,
                                'resistencia_cercana': medio.resistencia_cercana if hasattr(medio, 'resistencia_cercana') else None,
                                'pipeline_estado': estado,
                                'score_h1': score_h1,
                            }
                        
                        # ============================================================
                        # INCREMENTAR ESTADÍSTICAS
                        # ============================================================
                        
                        self.estadisticas['senales_generadas'] += 1
                        
                    except Exception as e:
                        self.logger.debug(f"⚠️ Error en análisis de {simbolo}: {e}")
                        import traceback
                        self.logger.debug(traceback.format_exc())
                        continue

            # ============================================================
            # 4. LIMPIEZAS
            # ============================================================
            
            self._limpiar_watchlist_timeout(fecha_m5)
            self._limpiar_contexto_antiguo(fecha_m5)

            # ============================================================
            # 5. SNIPER EVALUATION (SOLO SI HAY CUPO)
            # ============================================================

            if len(self.posiciones_abiertas) >= self.max_simultaneas:
                continue

            if self.ops_hoy >= self.max_ops_dia:
                continue

            for simbolo in list(self._contexto_h1.keys()):
                ctx = self._contexto_h1.get(simbolo)
                if not ctx:
                    continue

                pipeline_estado = ctx.get('pipeline_estado')
                if not pipeline_estado:
                    if ctx.get('score_h1', 0) < 25:
                        continue

                # Cooldown
                if simbolo in self.cooldowns_simbolos:
                    if fecha_m5 < self.cooldowns_simbolos[simbolo]:
                        continue

                # Posición abierta
                if any(p['simbolo'] == simbolo for p in self.posiciones_abiertas):
                    continue

                # ============================================================
                # 5a. VERIFICAR QUE LA DIRECCIÓN SIGUE SIENDO VÁLIDA
                # ============================================================
                
                direccion_actual = ctx.get('direccion', 'NEUTRAL')
                if direccion_actual == 'NEUTRAL':
                    continue

                # ============================================================
                # 5b. EVALUACIÓN DEL SNIPER
                # ============================================================
                
                df_m5 = self.dataframes.get(simbolo, {}).get('M5')
                if df_m5 is not None and len(df_m5) >= 50:
                    df_m5_hasta = df_m5.loc[:fecha_m5]
                    if len(df_m5_hasta) >= 50:
                        precio_actual = df_m5_hasta['Close'].iloc[-1]
                        
                        try:
                            # Análisis rápido M5
                            rapido_m5 = self.analisis_capas.analisis_rapido(df_m5_hasta, simbolo)
                            if rapido_m5.pasa_filtro:
                                # Análisis medio M5
                                medio_m5 = self.analisis_capas.analisis_medio(df_m5_hasta, simbolo, rapido_m5, {})
                                if medio_m5.pasa_filtro:
                                    # ✅ EJECUTAR SNIPER
                                    disparo = self.sniper_checklist.evaluar_sniper_optimizado(
                                        simbolo=simbolo,
                                        df_m5=df_m5_hasta,
                                        precio_actual=precio_actual,
                                        direccion=direccion_actual,
                                        estado_pipeline=pipeline_estado,
                                        analisis_rapido=rapido_m5,
                                        analisis_medio=medio_m5,
                                        ejecutar_pesado=True,
                                        contexto_h1=ctx,
                                        calidad_horario='REGULAR'
                                    )
                                    
                                    self.estadisticas['evaluaciones_sniper'] += 1
                                    
                                    if disparo:
                                        self.estadisticas['aprobados_sniper'] += 1
                                        
                                        # Decisión de operabilidad
                                        decision = self.decisor_operabilidad.decidir(
                                            simbolo=simbolo,
                                            score_final=disparo.get('score_final', disparo.get('score', 50)),
                                            regimen=ctx.get('regimen', 'INCERTO'),
                                            hora_utc=fecha_m5.hour + fecha_m5.minute / 60.0,
                                            score_h1=ctx.get('score', 0),
                                            en_nivel_clave=ctx.get('en_nivel_clave', False),
                                            modo=disparo.get('modo', 'RETEST')
                                        )
                                        
                                        # Ejecutar si es operable o score suficiente
                                        if decision.operable or disparo.get('score_final', 0) > 35:
                                            disparo['direccion'] = direccion_actual
                                            ejecutado = self._ejecutar_operacion_backtest(disparo)
                                            
                                            if ejecutado:
                                                self.pipeline.marcar_ejecutada(simbolo)
                                                if simbolo in self._contexto_h1:
                                                    del self._contexto_h1[simbolo]
                                                self.cooldowns_simbolos[simbolo] = fecha_m5 + timedelta(hours=2)
                                                self.estadisticas['operaciones_ejecutadas'] += 1
                                    else:
                                        self.estadisticas['rechazados_sniper'] += 1
                        except Exception as e:
                            self.logger.debug(f"Error evaluando sniper {simbolo}: {e}")
                            continue


            # ============================================================
            # 6. ACTUALIZAR OPERACIONES ABIERTAS
            # ============================================================

            self._actualizar_posiciones(fecha_m5)

        # ============================================================
        # 7. FIN DEL BACKTEST - CERRAR POSICIONES RESTANTES
        # ============================================================

        for pos in self.posiciones_abiertas[:]:
            if pos['estado'] == 'ABIERTA':
                precio_final = pos['entrada']
                self._cerrar_posicion(pos, fecha_fin, precio_final, "FIN_BACKTEST")

        elapsed = time.time() - start_time

        self.logger.info("")
        self.logger.info(f"📊 RESUMEN DE BACKTEST:")
        self.logger.info(f"   Análisis realizados: {self.estadisticas['analisis_realizados']}")
        self.logger.info(f"   Señales generadas: {self.estadisticas['senales_generadas']}")
        self.logger.info(f"   Evaluaciones sniper: {self.estadisticas['evaluaciones_sniper']}")
        self.logger.info(f"   Aprobados sniper: {self.estadisticas['aprobados_sniper']}")
        self.logger.info(f"   Rechazados sniper: {self.estadisticas['rechazados_sniper']}")
        self.logger.info(f"   Operaciones ejecutadas: {self.estadisticas['operaciones_ejecutadas']}")
        self.logger.info(f"   Operaciones totales: {len(self.trades)}")
        self.logger.info(f"   Capital final: ${self.capital_actual:.2f}")
        self.logger.info(f"   Tiempo: {elapsed:.2f}s")

        return self._calcular_metricas()

    # ================================================================
    # 13. MÉTRICAS
    # ================================================================

    def _calcular_metricas(self) -> Dict[str, Any]:
        """
        Calcula métricas detalladas del backtest con información enriquecida.
        """
        if not self.trades:
            return self._metricas_vacias()

        df_trades = pd.DataFrame(self.trades)
        
        # ============================================================
        # 1. MÉTRICAS BÁSICAS
        # ============================================================
        
        total = len(df_trades)
        ganadoras = df_trades[df_trades['pnl'] > 0]
        perdedoras = df_trades[df_trades['pnl'] < 0]
        ganadoras_pips = df_trades[df_trades['pips'] > 0] if 'pips' in df_trades.columns else ganadoras
        
        win_rate = len(ganadoras) / total * 100 if total > 0 else 0
        gross_profit = ganadoras['pnl'].sum() if not ganadoras.empty else 0
        gross_loss = abs(perdedoras['pnl'].sum()) if not perdedoras.empty else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
        total_return = (self.capital_actual / self.capital_inicial - 1) * 100
        
        # Drawdown
        peak = self.capital_inicial
        max_dd = 0.0
        dd_data = []
        for val in self.equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd = max(0.0, (peak - val) / peak * 100)
                if dd > max_dd:
                    max_dd = dd
                dd_data.append(dd)

        # Sharpe Ratio
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

        # ============================================================
        # 2. ANÁLISIS DE ENTRADAS
        # ============================================================
        
        entrada_analisis = {
            'sl_promedio_pips': df_trades['sl_dist_pips'].mean() if 'sl_dist_pips' in df_trades.columns else 0,
            'rr_promedio': df_trades['rr'].mean() if 'rr' in df_trades.columns else 0,
            'score_promedio': df_trades['score'].mean() if 'score' in df_trades.columns else 0,
            'lotes_promedio': df_trades['lotes'].mean() if 'lotes' in df_trades.columns else 0,
        }

        # ============================================================
        # 3. ANÁLISIS DE SALIDAS
        # ============================================================
        
        salida_analisis = {}
        if 'motivo_cierre' in df_trades.columns:
            motivos = df_trades['motivo_cierre'].value_counts()
            for motivo in motivos.index:
                df_m = df_trades[df_trades['motivo_cierre'] == motivo]
                salida_analisis[motivo] = {
                    'total': len(df_m),
                    'ganadoras': len(df_m[df_m['pnl'] > 0]),
                    'perdedoras': len(df_m[df_m['pnl'] < 0]),
                    'winrate': len(df_m[df_m['pnl'] > 0]) / len(df_m) * 100,
                    'pnl_total': df_m['pnl'].sum(),
                    'pips_promedio': df_m['pips'].mean() if 'pips' in df_m.columns else 0,
                }

        # ============================================================
        # 4. DISTRIBUCIÓN POR MODO
        # ============================================================
        
        por_modo = {}
        if 'modo' in df_trades.columns:
            for modo in df_trades['modo'].unique():
                df_m = df_trades[df_trades['modo'] == modo]
                total_m = len(df_m)
                ganadoras_m = len(df_m[df_m['pnl'] > 0])
                perdedoras_m = total_m - ganadoras_m
                por_modo[modo] = {
                    'total': total_m,
                    'ganadoras': ganadoras_m,
                    'perdedoras': perdedoras_m,
                    'winrate': ganadoras_m / total_m * 100 if total_m > 0 else 0,
                    'pnl_total': df_m['pnl'].sum(),
                    'pnl_promedio': df_m['pnl'].mean() if total_m > 0 else 0,
                    'pips_promedio': df_m['pips'].mean() if 'pips' in df_m.columns else 0,
                    'sl_promedio_pips': df_m['sl_dist_pips'].mean() if 'sl_dist_pips' in df_m.columns else 0,
                    'rr_promedio': df_m['rr'].mean() if 'rr' in df_m.columns else 0,
                    'score_promedio': df_m['score'].mean() if 'score' in df_m.columns else 0,
                }

        # ============================================================
        # 5. DISTRIBUCIÓN POR DIRECCIÓN
        # ============================================================
        
        por_direccion = {}
        if 'direccion' in df_trades.columns:
            for direccion in df_trades['direccion'].unique():
                df_d = df_trades[df_trades['direccion'] == direccion]
                total_d = len(df_d)
                ganadoras_d = len(df_d[df_d['pnl'] > 0])
                perdedoras_d = total_d - ganadoras_d
                por_direccion[direccion] = {
                    'total': total_d,
                    'ganadoras': ganadoras_d,
                    'perdedoras': perdedoras_d,
                    'winrate': ganadoras_d / total_d * 100 if total_d > 0 else 0,
                    'pnl_total': df_d['pnl'].sum(),
                    'pnl_promedio': df_d['pnl'].mean() if total_d > 0 else 0,
                    'pips_promedio': df_d['pips'].mean() if 'pips' in df_d.columns else 0,
                }

        # ============================================================
        # 6. DISTRIBUCIÓN POR RÉGIMEN
        # ============================================================
        
        por_regimen = {}
        if 'regimen' in df_trades.columns:
            for regimen in df_trades['regimen'].unique():
                df_r = df_trades[df_trades['regimen'] == regimen]
                total_r = len(df_r)
                ganadoras_r = len(df_r[df_r['pnl'] > 0])
                perdedoras_r = total_r - ganadoras_r
                por_regimen[regimen] = {
                    'total': total_r,
                    'ganadoras': ganadoras_r,
                    'perdedoras': perdedoras_r,
                    'winrate': ganadoras_r / total_r * 100 if total_r > 0 else 0,
                    'pnl_total': df_r['pnl'].sum(),
                    'pnl_promedio': df_r['pnl'].mean() if total_r > 0 else 0,
                    'pips_promedio': df_r['pips'].mean() if 'pips' in df_r.columns else 0,
                    'sl_promedio_pips': df_r['sl_dist_pips'].mean() if 'sl_dist_pips' in df_r.columns else 0,
                    'rr_promedio': df_r['rr'].mean() if 'rr' in df_r.columns else 0,
                    'score_promedio': df_r['score'].mean() if 'score' in df_r.columns else 0,
                }

        # ============================================================
        # 7. ANÁLISIS DE PÉRDIDAS (¿Por qué perdimos?)
        # ============================================================
        
        analisis_perdidas = {}
        if 'pnl' in df_trades.columns:
            df_perdidas = df_trades[df_trades['pnl'] < 0]
            if not df_perdidas.empty:
                # Por modo
                perdidas_por_modo = {}
                for modo in df_perdidas['modo'].unique() if 'modo' in df_perdidas.columns else []:
                    df_pm = df_perdidas[df_perdidas['modo'] == modo]
                    perdidas_por_modo[modo] = {
                        'total': len(df_pm),
                        'perdida_total': df_pm['pnl'].sum(),
                        'perdida_promedio': df_pm['pnl'].mean(),
                        'pips_promedio': df_pm['pips'].mean() if 'pips' in df_pm.columns else 0,
                    }
                analisis_perdidas['por_modo'] = perdidas_por_modo
                
                # Por motivo de cierre
                perdidas_por_motivo = {}
                if 'motivo_cierre' in df_perdidas.columns:
                    for motivo in df_perdidas['motivo_cierre'].unique():
                        df_pm = df_perdidas[df_perdidas['motivo_cierre'] == motivo]
                        perdidas_por_motivo[motivo] = {
                            'total': len(df_pm),
                            'perdida_total': df_pm['pnl'].sum(),
                            'perdida_promedio': df_pm['pnl'].mean(),
                            'pips_promedio': df_pm['pips'].mean() if 'pips' in df_pm.columns else 0,
                        }
                analisis_perdidas['por_motivo'] = perdidas_por_motivo
                
                # Por régimen
                perdidas_por_regimen = {}
                if 'regimen' in df_perdidas.columns:
                    for regimen in df_perdidas['regimen'].unique():
                        df_pr = df_perdidas[df_perdidas['regimen'] == regimen]
                        perdidas_por_regimen[regimen] = {
                            'total': len(df_pr),
                            'perdida_total': df_pr['pnl'].sum(),
                            'perdida_promedio': df_pr['pnl'].mean(),
                            'pips_promedio': df_pr['pips'].mean() if 'pips' in df_pr.columns else 0,
                        }
                analisis_perdidas['por_regimen'] = perdidas_por_regimen

        # ============================================================
        # 8. MÉTRICAS DE TRAILING
        # ============================================================
        
        trailing_metrics = {}
        if 'trailing_metrics' in self.estadisticas:
            for simbolo, stats in self.estadisticas['trailing_metrics'].items():
                total = stats['total_movimientos']
                exitosos = stats['movimientos_exitosos']
                trailing_metrics[simbolo] = {
                    'total_movimientos': total,
                    'exitosos': exitosos,
                    'tasa_exito': (exitosos / total * 100) if total > 0 else 0,
                    'pips_protegidos_promedio': stats['total_pips_protegidos'] / total if total > 0 else 0,
                    'pips_ganados_promedio': stats['total_pips_ganados'] / total if total > 0 else 0,
                    'fases_alcanzadas': dict(stats['fases_alcanzadas']),
                }

        # ============================================================
        # 9. MÉTRICAS DE SNIPER
        # ============================================================
        
        sniper_metrics = {}
        if 'estadisticas' in self.__dict__:
            sniper_metrics = {
                'evaluaciones_sniper': self.estadisticas.get('evaluaciones_sniper', 0),
                'aprobados_sniper': self.estadisticas.get('aprobados_sniper', 0),
                'rechazados_sniper': self.estadisticas.get('rechazados_sniper', 0),
                'tasa_aprobacion': (self.estadisticas.get('aprobados_sniper', 0) / 
                                max(1, self.estadisticas.get('evaluaciones_sniper', 1))) * 100,
                'analisis_realizados': self.estadisticas.get('analisis_realizados', 0),
                'senales_generadas': self.estadisticas.get('senales_generadas', 0),
                'operaciones_ejecutadas': self.estadisticas.get('operaciones_ejecutadas', 0),
            }

        # ============================================================
        # 10. ANÁLISIS DE FRAME (Régimen en cada dirección)
        # ============================================================
        
        frame_analisis = {}
        if 'regimen' in df_trades.columns and 'direccion' in df_trades.columns:
            # Agrupar por régimen y dirección
            agrupado = df_trades.groupby(['regimen', 'direccion'])
            for (regimen, direccion), df_f in agrupado:
                key = f"{regimen}_{direccion}"
                frame_analisis[key] = {
                    'regimen': regimen,
                    'direccion': direccion,
                    'total': len(df_f),
                    'ganadoras': len(df_f[df_f['pnl'] > 0]),
                    'perdedoras': len(df_f[df_f['pnl'] < 0]),
                    'winrate': len(df_f[df_f['pnl'] > 0]) / len(df_f) * 100,
                    'pnl_total': df_f['pnl'].sum(),
                    'pnl_promedio': df_f['pnl'].mean(),
                    'pips_promedio': df_f['pips'].mean() if 'pips' in df_f.columns else 0,
                    'score_promedio': df_f['score'].mean() if 'score' in df_f.columns else 0,
                    'rr_promedio': df_f['rr'].mean() if 'rr' in df_f.columns else 0,
                    'sl_promedio_pips': df_f['sl_dist_pips'].mean() if 'sl_dist_pips' in df_f.columns else 0,
                }

        # ============================================================
        # 11. OPERACIONES DETALLADAS (para análisis individual)
        # ============================================================
        
        operaciones_detalladas = []
        for trade in self.trades:
            op_detalle = {
                'ticket': trade.get('ticket', 0),
                'simbolo': trade.get('simbolo', ''),
                'direccion': trade.get('direccion', ''),
                'modo': trade.get('modo', ''),
                'regimen': trade.get('regimen', ''),
                'fecha_entrada': trade.get('fecha_entrada', '').isoformat() if isinstance(trade.get('fecha_entrada'), datetime) else trade.get('fecha_entrada', ''),
                'fecha_salida': trade.get('fecha_salida', '').isoformat() if isinstance(trade.get('fecha_salida'), datetime) else trade.get('fecha_salida', ''),
                'entrada': trade.get('entrada', 0),
                'salida': trade.get('precio_salida', 0),
                'sl': trade.get('sl', 0),
                'tp': trade.get('tp', 0),
                'sl_dist_pips': trade.get('sl_dist_pips', 0),
                'rr': trade.get('rr', 0),
                'lotes': trade.get('lotes', 0),
                'score': trade.get('score', 0),
                'pips': trade.get('pips', 0),
                'pnl': trade.get('pnl', 0),
                'motivo_cierre': trade.get('motivo_cierre', ''),
                'en_nivel_clave': trade.get('en_nivel_clave', False),
                'es_reversal': trade.get('es_reversal', False),
                'calidad_horario': trade.get('calidad_horario', ''),
                'trailing_stats': trade.get('trailing_stats', {}),
            }
            operaciones_detalladas.append(op_detalle)

        # ============================================================
        # 12. COMPOSICIÓN FINAL
        # ============================================================
        
        return {
            # Métricas básicas
            'total_operaciones': total,
            'ganadoras': len(ganadoras),
            'perdedoras': len(perdedoras),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'net_profit': gross_profit - gross_loss,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'sharpe_ratio': sharpe,
            'capital_final': self.capital_actual,
            'capital_inicial': self.capital_inicial,
            
            # Análisis de entradas
            'analisis_entradas': entrada_analisis,
            
            # Análisis de salidas
            'analisis_salidas': salida_analisis,
            
            # Distribuciones
            'por_modo': por_modo,
            'por_direccion': por_direccion,
            'por_regimen': por_regimen,
            
            # Análisis de pérdidas
            'analisis_perdidas': analisis_perdidas,
            
            # Frame analysis (régimen + dirección)
            'frame_analisis': frame_analisis,
            
            # Métricas de trailing
            'trailing_metrics': trailing_metrics,
            
            # Métricas de sniper
            'sniper_metrics': sniper_metrics,
            
            # Datos detallados
            'trades': operaciones_detalladas,
            'equity_curve': self.equity_curve,
            'timestamps': [ts.isoformat() for ts in self.timestamps] if self.timestamps else [],
            'estadisticas': self.estadisticas,
        }

    def _metricas_vacias(self) -> Dict[str, Any]:
        """Retorna métricas vacías cuando no hay operaciones."""
        return {
            'mensaje': 'Sin operaciones',
            'total_operaciones': 0,
            'ganadoras': 0,
            'perdedoras': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'net_profit': 0,
            'total_return': 0,
            'max_drawdown': 0,
            'sharpe_ratio': 0,
            'capital_final': self.capital_actual,
            'capital_inicial': self.capital_inicial,
            'analisis_entradas': {},
            'analisis_salidas': {},
            'por_modo': {},
            'por_direccion': {},
            'por_regimen': {},
            'analisis_perdidas': {},
            'frame_analisis': {},
            'trailing_metrics': {},
            'sniper_metrics': {},
            'trades': [],
            'equity_curve': self.equity_curve,
            'timestamps': [],
            'estadisticas': self.estadisticas,
        }

    def _analizar_trailing_y_acumular(self, pos: Dict, fecha: datetime, precio_actual: float,
                                  decision: Dict[str, Any], ganancia_pips: float) -> Dict[str, Any]:
        """
        Analiza un movimiento de trailing, determina si fue exitoso y acumula estadísticas
        para el símbolo operado.

        Criterios de "movimiento exitoso":
        - Mover SL a breakeven (ganancia > 0)
        - Mover SL a trailing suave (ganancia > 20 pips)
        - Mover SL a trailing agresivo (ganancia > 40 pips)
        - Cualquier movimiento que mejore la protección de capital

        Args:
            pos: Posición actual
            fecha: Fecha del movimiento
            precio_actual: Precio actual
            decision: Decisión del TrailingEngine (diccionario)
            ganancia_pips: Ganancia en pips en el momento del movimiento

        Returns:
            Diccionario con el análisis del movimiento
        """
        simbolo = pos['simbolo']
        direccion = pos['direccion']
        sl_anterior = pos.get('sl_anterior', pos['sl'])
        sl_nuevo = decision.get('nuevo_sl', 0)
        fase = decision.get('fase', 'NINGUNA')
        razon = decision.get('razon', '')
        
        # Inicializar métricas del símbolo si no existen
        if 'trailing_metrics' not in self.estadisticas:
            self.estadisticas['trailing_metrics'] = {}
        if simbolo not in self.estadisticas['trailing_metrics']:
            self.estadisticas['trailing_metrics'][simbolo] = {
                'total_movimientos': 0,
                'movimientos_exitosos': 0,
                'total_pips_protegidos': 0.0,
                'total_pips_ganados': 0.0,
                'fases_alcanzadas': defaultdict(int),
                'ultimo_movimiento': None,
            }
        
        stats = self.estadisticas['trailing_metrics'][simbolo]
        
        # Determinar si el movimiento fue exitoso
        exitoso = False
        pips_protegidos = 0.0
        pips_ganados = 0.0
        
        # Calcular mejora del SL (en pips)
        pip_val = self._obtener_pip_val(simbolo)
        if pip_val > 0:
            if direccion == 'COMPRA':
                mejora_pips = (sl_nuevo - sl_anterior) / pip_val if sl_nuevo > sl_anterior else 0
            else:
                mejora_pips = (sl_anterior - sl_nuevo) / pip_val if sl_nuevo < sl_anterior else 0
        else:
            mejora_pips = 0.0
        
        # Criterios de éxito
        if mejora_pips > 0:
            exitoso = True
            pips_protegidos = mejora_pips
            pips_ganados = ganancia_pips
        
        # Casos especiales de éxito
        if fase == 'BREAKEVEN' and ganancia_pips > 0:
            exitoso = True
            pips_protegidos = max(pips_protegidos, ganancia_pips)
        
        if fase in ['TRAILING_SUAVE', 'TRAILING_AGRESIVO'] and ganancia_pips > 20:
            exitoso = True
            pips_protegidos = max(pips_protegidos, ganancia_pips * 0.5)  # Estimación conservadora
        
        # ACUMULAR ESTADÍSTICAS
        if exitoso:
            stats['movimientos_exitosos'] += 1
            stats['total_pips_protegidos'] += pips_protegidos
            stats['total_pips_ganados'] += pips_ganados
            stats['fases_alcanzadas'][fase] += 1
        
        stats['total_movimientos'] += 1
        stats['ultimo_movimiento'] = {
            'fecha': fecha.isoformat(),
            'fase': fase,
            'razon': razon,
            'ganancia_pips': ganancia_pips,
            'mejora_pips': mejora_pips,
            'exitoso': exitoso,
            'sl_anterior': sl_anterior,
            'sl_nuevo': sl_nuevo,
        }
        
        return {
            'exitoso': exitoso,
            'pips_protegidos': pips_protegidos,
            'pips_ganados': pips_ganados,
            'mejora_pips': mejora_pips,
            'fase': fase,
            'razon': razon,
        }

    # ================================================================
    # 14. GUARDAR REPORTES
    # ================================================================

    def guardar_reporte(self, ruta: Path):
        metricas = self._calcular_metricas()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(metricas, f, indent=2, default=str)

    def guardar_equity_curve(self, ruta: Path):
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

def create_backtester_bot(config: Config, simbolos: List[str], **kwargs) -> BacktesterBot:
    """Crea una instancia del BacktesterBot."""
    return BacktesterBot(config=config, simbolos=simbolos, **kwargs)


# ============================================================
# EJECUCIÓN DIRECTA PARA PRUEBAS
# ============================================================

if __name__ == "__main__":
    print("🧪 BacktesterBot V9.2 - Prueba de inicialización")
    print("   (Requiere ejecución desde test_backtest_optimized.py)")