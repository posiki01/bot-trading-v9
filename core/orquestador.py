#!/usr/bin/env python3
"""
core/orquestador.py (V10.1 - ML CONECTADO)
Orquestador principal - Coordina todos los módulos del Bot de Trading.

CAMBIOS V10.1:
- ✅ FIX #1: M15 real se propaga al pipeline (direccion_m15 en analisis_m15)
- ✅ FIX #2: nivel_usado se calcula y propaga al contexto_h1
- ✅ FIX #3: Volumen de vela virtual corregido (20% del medio)
- ✅ FIX #4: Método _determinar_direccion_m15() nuevo
- ✅ ML CONECTADO:
    - Filtro ML en precarga (rechaza si prob < 0.35)
    - Buffer de operaciones cerradas
    - Método notificar_ml_operacion_cerrada()
- ✅ Nuevo método _obtener_contexto_ml() para predecir
- ✅ Stats incluye info ML

MANTIENE:
- Pipeline V10 con degradación por tiempo
- Circuit Breaker con scope
- Trailing engine V10
- Lock por símbolo
- Precarga incremental
"""

import os
import sys
import time
import signal
import pandas as pd
import numpy as np
import threading
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta

# ============================================================
# IMPORTS
# ============================================================

from config.settings import Config
from config.umbrales import Umbrales
from core.estados import EstadoGlobal

from utils.logger_persistente import LoggerPersistente
from utils.logger_latencia import medir_latencia, TemporizadorContexto
from utils.retry import retry
from utils.helpers import (
    limpiar_texto, formatear_dinero, formatear_porcentaje,
    es_forex, es_crypto, es_indice, es_metal, get_tipo_activo,
    safe_float, safe_int
)
from utils.tiempo import HorarioMercado, create_horario_mercado
from utils.cache import CacheUnificado, create_cache_unificado
from utils.reloj import now_utc

from analysis.regimen import MarketRegimeFilter, RegimenMercado, create_regime_filter
from analysis.scoring import ScoreEngine, create_score_engine
from analysis.niveles import NivelTracker, create_nivel_tracker
from analysis.patron_tracker import PatronTracker, create_patron_tracker
from analysis.capas import AnalisisPorCapas
from analysis.fases import AnalisisPorFase, create_analisis_por_fase
from analysis.pipeline import (
    PipelineOportunidades, FaseOportunidad, MotivoDegradacion,
)
from analysis.direccion import determinar_direccion, DireccionResultado
from analysis.ml.ml_optimizer import MLOptimizer, create_ml_optimizer

from trading.riesgo import GestionRiesgo, create_gestion_riesgo
from trading.stops import GestorStops, create_gestor_stops
from trading.trailing import TrailingEngine, create_trailing_engine
from trading.ejecucion import EjecutorOperaciones, create_ejecutor_operaciones
from trading.sniper.sniper_checklist import SniperChecklist, create_sniper_checklist
from trading.operabilidad import DecisorOperabilidad, create_decisor_operabilidad
from trading.modos import ModoSelector
from trading.timer import EntryTimer
from trading.monitoreo import MonitorPosiciones, create_monitor_posiciones

from reportes.informe_diario import InformeDiario, create_informe_diario

from data.almacenamiento_sqlite import AlmacenamientoSQLite
from mt5.conector_mt5 import ConectorPepperstone, ConectorHeadless
from notificaciones.alertas import Notificaciones
from noticias.sistema_noticias import SistemaNoticias

logger = logging.getLogger('BotTrading.Orquestador')


class Orquestador:
    """
    Orquestador principal del Bot de Trading.
    V10.1 - ML CONECTADO.
    """

    # ============================================================
    # CONSTANTES
    # ============================================================

    INTERVALO_ESCANEO = 1800       # 30 min
    INTERVALO_SNIPER = 30          # 30 s
    INTERVALO_SNIPER_CERRADO = 300 # 5 min si mercado cerrado
    INTERVALO_MONITOREO = 30       # 30 s
    INTERVALO_HEARTBEAT = 60       # 1 min
    INTERVALO_NOTICIAS = 900       # 15 min
    INTERVALO_INFORME = 1800       # 30 min
    INTERVALO_ANALISIS_COMPLETO = 300
    INTERVALO_DEGRADACION = 300    # 5 min

    # ML
    UMBRAL_ML_RECHAZO = 0.35       # Si prob < esto → rechazar en precarga
    UMBRAL_ML_CONFIANZA = 0.60     # Si prob > esto → bono en scoring

    def __init__(self, modo_backtest: bool = False, modo_depuracion: bool = False):
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion

        # ============================================================
        # 1. CONFIGURACIÓN Y LOGGING
        # ============================================================

        self.config = Config()
        self.logger_persistente = LoggerPersistente(
            directorio_logs=Path(__file__).parent.parent / "logs",
            nivel_log='DEBUG' if modo_depuracion else 'INFO',
            filter_emojis_consola=False,
        )
        self.logger = logging.getLogger('BotTrading.Orquestador')
        self.base_dir = Path(__file__).parent.parent

        # ============================================================
        # 2. ESTADO GLOBAL
        # ============================================================

        self.estado = EstadoGlobal()
        self.estado.modo_backtest = modo_backtest
        self.estado.modo_depuracion = modo_depuracion
        self._ejecutando = False
        self._threads: List[threading.Thread] = []
        self._hora_inicio = now_utc()

        # Lock por símbolo
        self._locks_simbolo: Dict[str, threading.Lock] = {}
        self._locks_simbolo_guard = threading.Lock()

        # Buffer de operaciones cerradas para ML
        self._ops_cerradas_buffer: List[Dict[str, Any]] = []

        # ============================================================
        # 3. ALMACENAMIENTO
        # ============================================================

        self.almacen = AlmacenamientoSQLite(
            base_dir=self.base_dir / "data",
            modo_backup=True,
        )

        # ============================================================
        # 4. NOTIFICACIONES
        # ============================================================

        self.notificaciones = Notificaciones(
            discord_webhook=self.config.DISCORD_WEBHOOK,
            telegram_token=self.config.TELEGRAM_TOKEN,
            telegram_chat=self.config.TELEGRAM_CHAT_ID,
            almacen=self.almacen,
        )

        # ============================================================
        # 5. CONECTOR MT5
        # ============================================================

        self.mt5 = self._inicializar_conector()

        # ============================================================
        # 6. CACHÉ
        # ============================================================

        self.cache = create_cache_unificado(
            config=self.config,
            persist_dir=self.base_dir / "data" / "cache",
            modo_backtest=modo_backtest,
            almacen=self.almacen,
        )

        # ============================================================
        # 7. HORARIO
        # ============================================================

        self.horario = create_horario_mercado(
            zona_usuario='COLOMBIA',
            config_activos=self.config.CONFIG_ACTIVOS,
            modo_backtest=modo_backtest,
        )

        # ============================================================
        # 8. NOTICIAS
        # ============================================================

        self.noticias = SistemaNoticias(
            config=self.config,
            notificador=self.notificaciones,
            almacen=self.almacen,
            data_cache=self.cache,
        )

        # ============================================================
        # 9. MÓDULOS DE ANÁLISIS
        # ============================================================

        self._inicializar_analisis()

        # ============================================================
        # 10. MÓDULOS DE TRADING
        # ============================================================

        self._inicializar_trading()

        # ============================================================
        # 11. UTILIDADES (escaneo)
        # ============================================================

        self._inicializar_utilidades()

        # ============================================================
        # 12. SNIPER
        # ============================================================

        self._inicializar_sniper()

        # ============================================================
        # 13. MONITOR DE POSICIONES
        # ============================================================

        self._inicializar_monitor()

        # ============================================================
        # 14. INFORME DIARIO
        # ============================================================

        self._inicializar_informe_diario()

        # ============================================================
        # 15. SEÑALES DEL SISTEMA
        # ============================================================

        signal.signal(signal.SIGINT, self._manejar_senal)
        signal.signal(signal.SIGTERM, self._manejar_senal)

        # ============================================================
        # 16. LOG INICIAL
        # ============================================================

        self._log_inicio()
        self.logger.info("🚀 Orquestador V10.1 ML-CONECTADO inicializado")

    # ============================================================
    # INICIALIZACIÓN DE MÓDULOS
    # ============================================================

    def _inicializar_conector(self):
        """Inicializa el conector MT5."""
        if self.config.USE_API_REST:
            return ConectorHeadless(
                token=self.config.API_REST_TOKEN,
                url_base=self.config.API_REST_URL,
            )
        return ConectorPepperstone(
            login=self.config.MT5_LOGIN,
            password=self.config.MT5_PASSWORD,
            server=self.config.MT5_SERVER,
            magic_number=self.config.MAGIC_NUMBER,
            demo=self.config.MT5_DEMO,
            almacen=self.almacen,
        )

    def _inicializar_analisis(self):
        """Inicializa módulos de análisis (incluye ML)."""
        # Régimen
        self.regimen_filter = create_regime_filter(
            config=self.config,
            modo_backtest=self.modo_backtest,
        )

        # Score Engine
        self.score_engine = create_score_engine(
            config=self.config,
            analysis_cache=self.cache,
            modo_backtest=self.modo_backtest,
        )

        # Nivel Tracker
        self.nivel_tracker = create_nivel_tracker(
            almacen=self.almacen,
            config=self.config,
            modo_backtest=self.modo_backtest,
        )

        # Patron Tracker
        self.patron_tracker = create_patron_tracker(
            almacen=self.almacen,
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion,
        )

        # ============================================================
        # ✅ ML OPTIMIZER (V2.0 - aprendizaje real)
        # ============================================================
        self.ml_optimizer = create_ml_optimizer(
            almacen=self.almacen,
            notificador=self.notificaciones,
            config=self.config,
            modo_backtest=self.modo_backtest,
        )

        # Análisis por capas
        self.analisis_capas = AnalisisPorCapas(
            analisis_tecnico=None,
            config=self.config,
            score_engine=self.score_engine,
            nivel_tracker=self.nivel_tracker,
            modo_backtest=self.modo_backtest,
        )

        # Análisis por fases
        self.analisis_fases = AnalisisPorFase(
            mt5_connector=self.mt5,
            noticias=self.noticias,
            config=self.config,
            analysis_cache=self.cache,
            modo_backtest=self.modo_backtest,
        )
        self.analisis_fases.set_analisis_capas(self.analisis_capas)

        # Pipeline V10
        self.pipeline = PipelineOportunidades(
            config=self.config,
            umbral_fase_1=getattr(self.config, 'PIPELINE_UMBRAL_FASE_1', 50),
            umbral_fase_2=getattr(self.config, 'PIPELINE_UMBRAL_FASE_2', 55),
            umbral_fase_3=getattr(self.config, 'PIPELINE_UMBRAL_FASE_3', 60),
            modo_backtest=self.modo_backtest,
            almacen=self.almacen,
        )

        self.logger.info("📊 Módulos de análisis inicializados")
        if self.ml_optimizer.debe_predecir():
            self.logger.info("🧠 ML: modelo cargado y activo")
        else:
            self.logger.info("🧠 ML: sin modelo (aprenderá con operaciones reales)")

    def _inicializar_trading(self):
        """Inicializa módulos de trading."""
        self.gestion_riesgo = create_gestion_riesgo(
            capital_inicial=self.config.CAPITAL_INICIAL,
            aporte_mensual=self.config.APORTE_MENSUAL,
            almacen=self.almacen,
            notificador=self.notificaciones,
            config=self.config,
            modo_backtest=self.modo_backtest,
            mt5=self.mt5,
        )

        self.gestor_stops = create_gestor_stops(
            config=self.config,
            modo_backtest=self.modo_backtest,
            mt5=self.mt5,
        )

        self.trailing_engine = create_trailing_engine(
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion,
        )

        self.decisor_operabilidad = create_decisor_operabilidad(
            config=self.config,
            horario=self.horario,
            modo_backtest=self.modo_backtest,
        )

        self.modo_selector = ModoSelector(
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion,
            almacen=self.almacen,
        )

        self.entry_timer = EntryTimer(
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion,
        )
        self.modo_selector.set_entry_timer(self.entry_timer)

        self.ejecutor = create_ejecutor_operaciones(
            orquestador=self,
            mt5=self.mt5,
            gestion_riesgo=self.gestion_riesgo,
            gestor_stops=self.gestor_stops,
            notificaciones=self.notificaciones,
            modo_backtest=self.modo_backtest,
            almacen=self.almacen,
        )

        self.logger.info("📈 Módulos de trading inicializados")

    def _inicializar_utilidades(self):
        """Inicializa escaneador."""
        from analysis.escaneo import Escaneador

        self.escaneador = Escaneador(
            orquestador=self,
            analisis_capas=self.analisis_capas,
            regimen_filter=self.regimen_filter,
            nivel_tracker=self.nivel_tracker,
            horario=self.horario,
            score_engine=self.score_engine,
            pipeline=self.pipeline,
        )
        self.logger.info("🔍 Escaneador V9.1 inicializado")

    def _inicializar_sniper(self):
        """Inicializa el sniper checklist."""
        self.sniper_checklist = create_sniper_checklist(
            pipeline=self.pipeline,
            analisis_capas=self.analisis_capas,
            modo_selector=self.modo_selector,
            entry_timer=self.entry_timer,
            gestor_stops=self.gestor_stops,
            config=self.config,
            almacen=self.almacen,
            mt5=self.mt5,
            noticias=self.noticias,
            patron_tracker=self.patron_tracker,
            ml_optimizer=self.ml_optimizer,
            analysis_cache=self.cache,
            modo_depuracion=self.modo_depuracion,
            modo_backtest=self.modo_backtest,
        )
        self.sniper_checklist.set_modo_backtest(self.modo_backtest)
        self.logger.info("🎯 SniperChecklist inicializado")

    def _inicializar_monitor(self):
        """Inicializa monitor de posiciones."""
        self.monitor_posiciones = create_monitor_posiciones(
            orquestador=self,
            mt5=self.mt5,
            gestion_riesgo=self.gestion_riesgo,
            trailing_engine=self.trailing_engine,
            monitorear_manuales=False,
        )
        self.logger.info("🔍 MonitorPosiciones V10.0 inicializado")

    def _inicializar_informe_diario(self):
        """Inicializa el generador de informes diarios."""
        self.informe_diario: InformeDiario = create_informe_diario(
            almacen=self.almacen,
            notificaciones=self.notificaciones,
            gestion_riesgo=self.gestion_riesgo,
            config=self.config,
            directorio_reportes=self.base_dir / "data" / "reportes",
        )
        self._ultimo_informe_fecha = None
        self.logger.info("📊 InformeDiario inicializado")

    def _log_inicio(self):
        """Log de inicio."""
        self.logger.info("=" * 60)
        self.logger.info("🚀 ORQUESTADOR V10.1 ML-CONECTADO INICIADO")
        self.logger.info("=" * 60)
        self.logger.info(f"   Entorno: {self.config.ENTORNO}")
        self.logger.info(f"   Backtest: {self.modo_backtest}")
        self.logger.info(f"   Depuración: {self.modo_depuracion}")
        self.logger.info(f"   Capital: ${self.config.CAPITAL_INICIAL:.2f}")
        self.logger.info(f"   Símbolos: {len(self.config.SIMBOLOS_COMPLETOS)}")
        self.logger.info(f"   MT5 Demo: {self.config.MT5_DEMO}")
        self.logger.info(f"   Módulos: Dirección estructura ✅ | Pipeline V10 ✅")
        self.logger.info(f"   Módulos: Trailing/Stops/Riesgo V10 ✅ | Informe ✅")
        self.logger.info(f"   ML: {'✅ Modelo activo' if self.ml_optimizer.debe_predecir() else '⏳ Aprendiendo'}")
        self.logger.info("=" * 60)

    # ============================================================
    # LOCKS POR SÍMBOLO
    # ============================================================

    def _obtener_lock(self, simbolo: str) -> threading.Lock:
        """Obtiene (creando si no existe) el lock de un símbolo."""
        with self._locks_simbolo_guard:
            if simbolo not in self._locks_simbolo:
                self._locks_simbolo[simbolo] = threading.Lock()
            return self._locks_simbolo[simbolo]

    # ============================================================
    # MANEJO DE SEÑALES
    # ============================================================

    def _manejar_senal(self, signum, frame):
        self.logger.info(f"🛑 Señal {signum} recibida, deteniendo...")
        self.detener()

    # ============================================================
    # DIAGNÓSTICO
    # ============================================================

    def diagnosticar_base_datos(self):
        """Diagnóstico de SQLite."""
        self.logger.info("🔍 DIAGNÓSTICO DE BASE DE DATOS:")
        self.logger.info("=" * 60)

        simbolos = self.config.SIMBOLOS_COMPLETOS[:5]

        for simbolo in simbolos:
            try:
                df_h1 = self.almacen.obtener_datos_historicos(simbolo, 60)
                df_m5 = self.almacen.obtener_datos_historicos(simbolo, 5)

                if df_h1 is not None:
                    self.logger.info(f"   {simbolo} H1: {len(df_h1)} velas")
                else:
                    self.logger.info(f"   {simbolo} H1: ❌ Sin datos")

                if df_m5 is not None:
                    self.logger.info(f"   {simbolo} M5: {len(df_m5)} velas")
                else:
                    self.logger.info(f"   {simbolo} M5: ❌ Sin datos")
            except Exception as e:
                self.logger.warning(f"   {simbolo}: Error - {e}")

        self.logger.info("=" * 60)

    # ============================================================
    # PRECARGA INCREMENTAL
    # ============================================================

    def _precargar_analisis_completo(self):
        """Precarga INCREMENTAL de análisis."""
        simbolos_operables = self._obtener_simbolos_operables()

        self.logger.info(f"🚀 Precarga incremental: {len(simbolos_operables)} símbolos")

        for simbolo in simbolos_operables:
            try:
                self._precargar_simbolo(simbolo)
            except Exception as e:
                self.logger.warning(f"⚠️ Error precargando {simbolo}: {e}")

        self.logger.info(
            f"✅ Precarga finalizada: "
            f"{len(self.pipeline.estados)} estados en pipeline"
        )

    def _precargar_simbolo(self, simbolo: str):
        """
        Precarga un símbolo con análisis completo.
        ✅ V10.1: incluye nivel_usado y filtro ML.
        """
        self.logger.debug(f"📊 Precargando {simbolo}...")

        # M5 con cache
        df_m5 = self.cache.get_datos(
            simbolo=simbolo,
            timeframe=5,
            n_velas=500,
            fetch_func=self.mt5.obtener_datos,
        )

        if df_m5 is None or len(df_m5) < 100:
            self.logger.debug(f"⚠️ {simbolo}: M5 insuficiente")
            return

        # H1 con cache
        from utils.construir_timeframes import obtener_timeframe_inteligente

        df_h1 = obtener_timeframe_inteligente(
            simbolo=simbolo,
            timeframe=60,
            df_m5=df_m5,
            conector=self.mt5,
            almacen=self.almacen,
        )

        if df_h1 is None or len(df_h1) < 50:
            self.logger.debug(f"⚠️ {simbolo}: H1 insuficiente")
            return

        # H4 con cache
        df_h4 = obtener_timeframe_inteligente(
            simbolo=simbolo,
            timeframe=240,
            df_m5=df_m5,
            conector=self.mt5,
            almacen=self.almacen,
        )

        # D1 con cache
        df_d1 = obtener_timeframe_inteligente(
            simbolo=simbolo,
            timeframe=1440,
            df_m5=df_m5,
            conector=self.mt5,
            almacen=self.almacen,
        )

        # Análisis rápido
        rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
        if not rapido.pasa_filtro:
            self._guardar_contexto_pipeline(simbolo, rapido, None, None)
            return

        # Niveles
        precio_actual = float(df_h1['Close'].iloc[-1])
        niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
            simbolo=simbolo,
            df=df_h1,
            precio_actual=precio_actual,
        )

        # Medio
        medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
        if medio is None or not medio.pasa_filtro:
            self._guardar_contexto_pipeline(simbolo, rapido, medio, None)
            return

        # Pesado
        pesado = self.analisis_capas.analisis_pesado(
            df_h1, simbolo, df_h4, df_d1, niveles, medio,
        )
        if pesado is None:
            return

        # Score H1
        score_h1 = self.score_engine.calcular_score_h1(
            score_estructura=pesado.score_estructura,
            score_momentum=pesado.score_momentum,
            score_confluencia=pesado.score_confluencia,
            score_institucional=pesado.score_institucional,
            simbolo=simbolo,
        ).score

        # Régimen
        try:
            regimen_data = self.regimen_filter.clasificar(simbolo, df_h4, df_h1)
            regimen = regimen_data.regimen.value
            direccion_regimen = regimen_data.direccion_favor
            confianza_regimen = regimen_data.confianza
        except Exception as e:
            self.logger.warning(f"⚠️ {simbolo}: Error régimen: {e}")
            regimen = 'UNCERTAIN'
            direccion_regimen = 'NONE'
            confianza_regimen = 0

        # Dirección por estructura
        direccion_result = self._determinar_direccion_estructura(
            df_h4=df_h4,
            df_h1=df_h1,
            regimen=regimen,
            en_nivel_clave=getattr(medio, 'en_nivel_clave', False),
            soporte_cercano=getattr(medio, 'soporte_cercano', None),
            resistencia_cercana=getattr(medio, 'resistencia_cercana', None),
            precio_actual=precio_actual,
        )
        direccion = direccion_result.direccion

        # ============================================================
        # ✅ FIX #2: Calcular nivel_usado según dirección
        # ============================================================
        nivel_usado = None
        if direccion == 'COMPRA':
            nivel_usado = getattr(medio, 'soporte_cercano', None)
        elif direccion == 'VENTA':
            nivel_usado = getattr(medio, 'resistencia_cercana', None)

        # ============================================================
        # ✅ FILTRO ML (V10.1)
        # ============================================================
        prob_ml = None
        if direccion in ('COMPRA', 'VENTA'):
            contexto_ml = self._obtener_contexto_ml(
                simbolo=simbolo,
                direccion=direccion,
                regimen=regimen,
                score_h1=score_h1,
                medio=medio,
                pesado=pesado,
                rapido=rapido,
                contexto_h1={'nivel_usado': nivel_usado},
            )
            prob_ml = self.ml_optimizer.predecir_probabilidad(contexto_ml)

            if prob_ml is not None:
                if prob_ml < self.UMBRAL_ML_RECHAZO:
                    self.logger.info(
                        f"🧠 {simbolo}: RECHAZADO por ML "
                        f"(prob={prob_ml:.2f} < {self.UMBRAL_ML_RECHAZO})"
                    )
                    return

        # Contexto
        contexto_h1 = {
            'score': score_h1,
            'direccion': direccion,
            'direccion_confianza': direccion_result.confianza,
            'direccion_razon': direccion_result.razon,
            'regimen': regimen,
            'direccion_regimen': direccion_regimen,
            'confianza_regimen': confianza_regimen,
            'en_nivel_clave': getattr(medio, 'en_nivel_clave', False),
            'soporte_cercano': getattr(medio, 'soporte_cercano', None),
            'resistencia_cercana': getattr(medio, 'resistencia_cercana', None),
            'soporte_hits': getattr(medio, 'soporte_hits', 0),
            'resistencia_hits': getattr(medio, 'resistencia_hits', 0),
            # ✅ FIX #2: nivel_usado
            'nivel_usado': nivel_usado,
            'adx': getattr(medio, 'adx', 0),
            'rsi': getattr(medio, 'rsi', 50),
            'patron_principal': getattr(pesado, 'patron_principal', None),
            'wyckoff_fase': getattr(pesado, 'wyckoff_fase', None),
            'divergencia_rsi': getattr(pesado, 'divergencia_rsi', None),
            'divergencia_macd': getattr(pesado, 'divergencia_macd', None),
            # ✅ ML
            'prob_ml': prob_ml,
            'niveles': {
                'soportes': niveles.get('soportes', []),
                'resistencias': niveles.get('resistencias', []),
            },
        }

        # Guardar en pipeline
        try:
            self.pipeline.actualizar_fase_1(
                simbolo=simbolo,
                analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
                score=score_h1,
                direccion=direccion,
                regimen=regimen,
                direccion_regimen=direccion_regimen,
                confianza_regimen=confianza_regimen,
                tendencia_h4=self._inferir_tendencia_h4(medio),
                contexto_h1=contexto_h1,
                analisis_pesado=pesado,
            )
        except Exception as e:
            self.logger.warning(f"⚠️ {simbolo}: Error actualizando pipeline: {e}")

        ml_info = f", ML={prob_ml:.2f}" if prob_ml is not None else ""
        self.logger.debug(f"✅ {simbolo}: score={score_h1:.1f}, dir={direccion}{ml_info}")

    def _obtener_contexto_ml(
        self,
        simbolo: str,
        direccion: str,
        regimen: str,
        score_h1: float,
        medio: Any,
        pesado: Any,
        rapido: Any,
        contexto_h1: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        ✅ V10.1: Construye el contexto para predicción ML.
        Formato compatible con las features esperadas por el modelo.
        """
        contexto_h1 = contexto_h1 or {}

        # Distancia al nivel
        nivel_usado = contexto_h1.get('nivel_usado')
        precio_actual = getattr(rapido, 'precio_actual', 0) or 0
        distancia_pips = 100.0
        if nivel_usado and precio_actual > 0:
            try:
                from utils.helpers import get_pip_val
                pip = get_pip_val(simbolo)
                if pip > 0:
                    distancia_pips = abs(precio_actual - nivel_usado) / pip
            except Exception:
                pass

        return {
            'simbolo': simbolo,
            'direccion': direccion,
            'regimen': regimen,
            'score_h1': score_h1,
            'score_m15': 0,   # aún no calculado
            'score_m5': 0,    # aún no calculado
            'score_final': score_h1,
            'pts_estructura': getattr(pesado, 'score_estructura', 0),
            'pts_momentum': getattr(pesado, 'score_momentum', 0),
            'pts_confluencia': getattr(pesado, 'score_confluencia', 0),
            'pts_institucional': getattr(pesado, 'score_institucional', 0),
            'adx': getattr(medio, 'adx', 0),
            'rsi': getattr(medio, 'rsi', 50),
            'volumen_relativo': getattr(rapido, 'volumen_relativo', 1.0),
            'atr_pct': getattr(medio, 'atr', 0.001) * 100 if getattr(medio, 'atr', 0) else 0.5,
            'distancia_nivel_pips': distancia_pips,
            'en_nivel_clave': getattr(medio, 'en_nivel_clave', False),
            'soporte_hits': getattr(medio, 'soporte_hits', 0),
            'resistencia_hits': getattr(medio, 'resistencia_hits', 0),
            'patron_calidad': getattr(pesado, 'calidad_patron', 0),
            'ob_cercano': getattr(pesado, 'ob_cercano', False),
            'wyckoff_confianza': getattr(pesado, 'wyckoff_confianza', 0),
            'wyckoff_fase': getattr(pesado, 'wyckoff_fase', 'NEUTRAL'),
            'divergencia_rsi': getattr(pesado, 'divergencia_rsi', None),
            'divergencia_macd': getattr(pesado, 'divergencia_macd', None),
            'calidad_horario': 'REGULAR',
            'rr': 1.5,
            'confianza_regimen': contexto_h1.get('confianza_regimen', 0),
            'direccion_m15': 'NEUTRAL',
            'timestamp': now_utc().isoformat(),
        }

    def _inferir_tendencia_h4(self, medio) -> str:
        """Infiere tendencia H4 desde análisis medio."""
        if not medio:
            return 'LATERAL'
        try:
            adx = getattr(medio, 'adx', 0)
            sma20 = getattr(medio, 'sma20', 0)
            sma50 = getattr(medio, 'sma50', 0)
            if adx > 25 and sma20 > sma50:
                return 'ALCISTA'
            if adx > 25 and sma20 < sma50:
                return 'BAJISTA'
        except Exception:
            pass
        return 'LATERAL'

    def _guardar_contexto_pipeline(self, simbolo, rapido=None, medio=None, pesado=None):
        """Guarda contexto aunque el símbolo no pase filtros."""
        if not self.pipeline:
            return
        try:
            self.pipeline.actualizar_fase_1(
                simbolo=simbolo,
                analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
                score=0,
                direccion='NEUTRAL',
                regimen='UNCERTAIN',
                contexto_h1={},
            )
        except Exception as e:
            self.logger.debug(f"⚠️ {simbolo}: Error guardando contexto: {e}")

    # ============================================================
    # DIRECCIÓN POR ESTRUCTURA
    # ============================================================

    def _determinar_direccion_estructura(
        self,
        df_h4=None,
        df_h1=None,
        df_m15=None,
        regimen: str = 'INCERTO',
        en_nivel_clave: bool = False,
        soporte_cercano: Optional[float] = None,
        resistencia_cercana: Optional[float] = None,
        precio_actual: Optional[float] = None,
    ) -> DireccionResultado:
        """Determina dirección por estructura de mercado."""
        return determinar_direccion(
            df_h4=df_h4,
            df_h1=df_h1,
            df_m15=df_m15,
            regimen=regimen,
            en_nivel_clave=en_nivel_clave,
            soporte_cercano=soporte_cercano,
            resistencia_cercana=resistencia_cercana,
            precio_actual=precio_actual,
            modo_backtest=self.modo_backtest,
        )

    def _determinar_direccion_mejorado(self, medio, pesado, df_h4=None, df_h1=None, regimen=None):
        """Compatibilidad con código antiguo."""
        try:
            resultado = self._determinar_direccion_estructura(
                df_h4=df_h4,
                df_h1=df_h1,
                regimen=regimen or 'INCERTO',
                en_nivel_clave=getattr(medio, 'en_nivel_clave', False) if medio else False,
                soporte_cercano=getattr(medio, 'soporte_cercano', None) if medio else None,
                resistencia_cercana=getattr(medio, 'resistencia_cercana', None) if medio else None,
                precio_actual=getattr(medio, 'precio_actual', None) if medio else None,
            )
            return resultado.direccion
        except Exception as e:
            self.logger.warning(f"⚠️ Error determinando dirección: {e}")
            return 'NEUTRAL'

    # ============================================================
    # ✅ NUEVO V10.1: DIRECCIÓN M15 REAL
    # ============================================================

    def _determinar_direccion_m15(self, rapido, medio) -> str:
        """
        ✅ V10.1: Determina la dirección REAL de M15.
        Usa RSI + MACD + ADX para decidir.

        Returns:
            'COMPRA' | 'VENTA' | 'NEUTRAL'
        """
        if medio is None or rapido is None:
            return 'NEUTRAL'

        try:
            rsi = getattr(medio, 'rsi', 50)
            macd = getattr(medio, 'macd_histogram', 0)
            adx = getattr(medio, 'adx', 0)

            # ADX bajo → sin tendencia clara
            if adx < 8:
                # Solo decidir con RSI extremo
                if rsi < 30:
                    return 'COMPRA'
                if rsi > 70:
                    return 'VENTA'
                return 'NEUTRAL'

            # ADX alto → decidir por confluencia RSI + MACD
            if rsi > 55 and macd > 0:
                return 'COMPRA'
            if rsi < 45 and macd < 0:
                return 'VENTA'

            # Zona neutral
            if 45 <= rsi <= 55:
                return 'NEUTRAL'

            # RSI direccional pero MACD contradice → débil
            return 'NEUTRAL'

        except Exception as e:
            self.logger.debug(f"⚠️ Error determinando dirección M15: {e}")
            return 'NEUTRAL'

    # ============================================================
    # ✅ V10.1: NOTIFICAR ML CUANDO SE CIERRA UNA OPERACIÓN
    # ============================================================

    def notificar_ml_operacion_cerrada(self, operacion: Dict[str, Any]):
        """
        ✅ V10.1: Notifica al ML que se cerró una operación.
        El ML acumula y entrena cuando tiene suficientes datos.

        Llamado desde monitor_posiciones._cerrar_posicion().
        """
        if not self.ml_optimizer:
            return

        try:
            # Asegurar campos mínimos
            op_completa = dict(operacion)
            op_completa['estado'] = 'CERRADA'

            # Añadir régimen y modo desde metadata de la posición si no vienen
            if 'regimen' not in op_completa:
                try:
                    meta = self.estado.posiciones_abiertas.get(
                        operacion.get('ticket'), {}
                    )
                    op_completa['regimen'] = meta.get('regimen', 'INCERTO')
                    op_completa['modo'] = meta.get('modo', 'RETEST')
                    op_completa['score_h1'] = meta.get('score', 0)
                except Exception:
                    pass

            # Registrar en el ML
            self.ml_optimizer.registrar_operacion_cerrada(op_completa)

            # Buffer local también
            self._ops_cerradas_buffer.append(op_completa)
            if len(self._ops_cerradas_buffer) > 500:
                self._ops_cerradas_buffer = self._ops_cerradas_buffer[-500:]

            self.logger.debug(
                f"🧠 ML notificado: op cerrada {operacion.get('simbolo', '?')} "
                f"(PnL: {operacion.get('ganancia_neta', 0):.2f})"
            )

        except Exception as e:
            self.logger.warning(f"⚠️ Error notificando ML: {e}")

    # ============================================================
    # CICLO PRINCIPAL
    # ============================================================

    def iniciar(self):
        """Inicia el bot."""
        self.logger.info("🚀 Iniciando Bot V10.1...")
        self._hora_inicio = now_utc()

        # 1. Verificar config
        if not self.config.verificar_env():
            self.logger.error("❌ Configuración inválida")
            self.notificaciones.enviar(
                "❌ CONFIGURACIÓN INVÁLIDA",
                "Verifica las variables de entorno",
                tipo='error',
            )
            return

        # 2. Conectar MT5
        if not self.modo_backtest:
            self.logger.info("🔌 Conectando a MT5...")
            if not self.mt5.conectar():
                self.logger.error("❌ No se pudo conectar a MT5")
                self.notificaciones.enviar(
                    "❌ FALLO CRÍTICO",
                    "No se pudo conectar a MT5",
                    tipo='error',
                )
                return
            self.logger.info("✅ Conectado a MT5")
            self.mt5._tick_cache.clear()

        # 3. Sincronizar estado
        if not self.modo_backtest:
            self._sincronizar_estado_inicial()

        # 4. Validar frescura pipeline
        self._validar_frescura_pipeline()

        # 5. Actualizar noticias
        self._actualizar_noticias()

        # 6. Precarga incremental
        self._precargar_analisis_completo()

        # 7. Diagnóstico
        self.diagnosticar_base_datos()

        # 8. Iniciar threads
        self._ejecutando = True
        self.estado.operando = True
        self._iniciar_threads()

        # 9. Notificar
        self.notificaciones.enviar(
            "🚀 BOT INICIADO",
            f"Capital: ${float(self.gestion_riesgo.capital_actual):,.2f}\n"
            f"Modo: {'BACKTEST' if self.modo_backtest else 'REAL'}\n"
            f"Entorno: {self.config.ENTORNO}\n"
            f"ML: {'✅ Activo' if self.ml_optimizer.debe_predecir() else '⏳ Aprendiendo'}",
            tipo='exito',
        )

        self.logger.info("✅ Bot iniciado correctamente")

        # 10. Bucle principal
        try:
            while self._ejecutando:
                time.sleep(1)

                # Reconexión MT5
                if not self.modo_backtest and not self.mt5.verificar_conexion():
                    self.logger.warning("⚠️ Conexión MT5 perdida, reconectando...")
                    if not self.mt5.conectar():
                        self.logger.warning("⚠️ Reconexión fallida")
                        time.sleep(10)
                        continue
                    self.mt5._tick_cache.clear()

                # Bloqueo de emergencia
                if self.estado.bloqueo_emergencia_hasta:
                    ahora = now_utc()
                    if ahora < self.estado.bloqueo_emergencia_hasta:
                        continue
                    self.estado.bloqueo_emergencia_hasta = None
                    self.logger.info("✅ Bloqueo de emergencia expirado")

                # Capacidad de operar
                if not self._verificar_capacidad():
                    continue

        except KeyboardInterrupt:
            self.logger.info("🛑 Interrupción recibida")
        except Exception as e:
            self.logger.error(f"❌ Error en bucle principal: {e}", exc_info=True)
            self.notificaciones.enviar(
                "❌ ERROR EN BUCLE PRINCIPAL",
                f"{str(e)[:500]}",
                tipo='error',
            )
        finally:
            self.detener()

    def detener(self):
        """Detiene el bot."""
        if not self._ejecutando:
            return

        self.logger.info("🛑 Deteniendo bot...")
        self._ejecutando = False
        self.estado.operando = False

        self._guardar_ultima_actualizacion_pipeline()

        # ✅ Intentar entrenar el ML antes de salir si hay suficientes datos
        try:
            if self.ml_optimizer and len(self._ops_cerradas_buffer) >= 30:
                self.logger.info("🧠 Entrenando ML antes de detener...")
                self.ml_optimizer.entrenar()
        except Exception as e:
            self.logger.debug(f"⚠️ Error entrenando ML al salir: {e}")

        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)

        if not self.modo_backtest:
            try:
                self.mt5.desconectar()
            except Exception:
                pass

        try:
            self.cache.stop()
        except Exception:
            pass

        self.almacen.cerrar()

        self.notificaciones.enviar(
            "🛑 BOT DETENIDO",
            f"Hora: {now_utc().strftime('%H:%M:%S')} UTC",
            tipo='info',
        )

        self.logger.info("✅ Bot detenido correctamente")

    # ============================================================
    # THREADS
    # ============================================================

    def _iniciar_threads(self):
        """Inicia threads."""
        threads_config = [
            ('Escaneo', self._thread_escaneo, self.INTERVALO_ESCANEO),
            ('Sniper', self._thread_sniper, self.INTERVALO_SNIPER),
            ('Monitoreo', self._thread_monitoreo, self.INTERVALO_MONITOREO),
            ('Heartbeat', self._thread_heartbeat, self.INTERVALO_HEARTBEAT),
            ('Noticias', self._thread_noticias, self.INTERVALO_NOTICIAS),
            ('InformeDiario', self._thread_informe_diario, self.INTERVALO_INFORME),
            ('Degradacion', self._thread_degradacion, self.INTERVALO_DEGRADACION),
        ]

        for nombre, func, intervalo in threads_config:
            t = threading.Thread(
                target=self._thread_loop,
                args=(func, nombre, intervalo),
                daemon=True,
                name=f"Bot-{nombre}",
            )
            t.start()
            self._threads.append(t)
            self.logger.info(f"🧵 Hilo '{nombre}' iniciado (intervalo: {intervalo}s)")

    def _thread_loop(self, func, nombre: str, intervalo: int):
        """Bucle genérico de thread."""
        while self._ejecutando:
            try:
                func()
            except Exception as e:
                self.logger.error(f"❌ Error en thread {nombre}: {e}", exc_info=True)

            for _ in range(intervalo):
                if not self._ejecutando:
                    return
                time.sleep(1)

    # ============================================================
    # THREAD: ESCANEO
    # ============================================================

    def _thread_escaneo(self):
        """Escaneo de mercado y promoción."""
        simbolos_operables = self._obtener_simbolos_operables()
        if not simbolos_operables:
            self.logger.debug("📭 Sin símbolos operables")
            return

        self.logger.info(f"📊 Escaneando {len(simbolos_operables)} símbolos...")
        self._ejecutar_escaneo()
        self._promover_oportunidades()

    def _ejecutar_escaneo(self):
        """Ejecuta escaneo."""
        if not self._ejecutando:
            return

        simbolos_operables = self._obtener_simbolos_operables()
        if not simbolos_operables:
            return

        if hasattr(self, 'escaneador') and self.escaneador is not None:
            try:
                resultados = self.escaneador.ejecutar_escaneo(simbolos=simbolos_operables)
                if resultados:
                    self.logger.info(f"📈 {len(resultados)} oportunidades encontradas")
            except Exception as e:
                self.logger.error(f"❌ Error en escaneo: {e}", exc_info=True)

    # ============================================================
    # THREAD: SNIPER
    # ============================================================

    def _thread_sniper(self):
        """Sniper principal."""
        # Limpiar terminales antiguos
        if self.pipeline:
            self.pipeline.limpiar_antiguos(horas=1)

        # Actualizar F2 con M15 fresco
        self._actualizar_oportunidades_fase2()

        # Promover
        self._promover_oportunidades()

        # Verificar niveles esperados
        if self.pipeline:
            self._verificar_niveles_esperados()

        # Ejecutar sniper con vela virtual
        self._ejecutar_sniper_con_vela_virtual()

    # ============================================================
    # THREAD: DEGRADACIÓN POR TIEMPO
    # ============================================================

    def _thread_degradacion(self):
        """Degrada oportunidades atascadas."""
        if not self.pipeline:
            return

        try:
            self.pipeline.degradar_por_tiempo()
        except Exception as e:
            self.logger.warning(f"⚠️ Error en degradación por tiempo: {e}")

        self._verificar_antiguedad_fase3()

    def _verificar_antiguedad_fase3(self):
        """Re-analiza las que llevan > 30 min en F3."""
        if not self.pipeline:
            return

        ahora = now_utc()
        limite = timedelta(minutes=30)

        for simbolo, estado in list(self.pipeline.estados.items()):
            if estado.fase_actual != FaseOportunidad.FASE_3:
                continue

            ts = estado.timestamp_ultima_actualizacion
            if ts is None:
                continue

            if ahora - ts > limite:
                minutos = (ahora - ts).total_seconds() / 60
                self.logger.info(
                    f"⏳ {simbolo}: {minutos:.0f}min en F3 → re-analizando"
                )
                self.pipeline._degradar_oportunidad(
                    simbolo,
                    razon=f"{minutos:.0f}min en F3 sin ejecutar",
                    motivo=MotivoDegradacion.TIEMPO_EXCEDIDO,
                )
                self._precargar_simbolo(simbolo)

    # ============================================================
    # THREAD: MONITOREO
    # ============================================================

    def _thread_monitoreo(self):
        """Monitoreo de posiciones abiertas."""
        if self.modo_backtest:
            return

        try:
            self.monitor_posiciones.ejecutar_ciclo()
        except Exception as e:
            self.logger.error(f"❌ Error en monitoreo: {e}", exc_info=True)

    # ============================================================
    # THREAD: HEARTBEAT
    # ============================================================

    def _thread_heartbeat(self):
        """Heartbeat."""
        self._enviar_heartbeat()

    def _enviar_heartbeat(self):
        if not self._ejecutando:
            return

        try:
            stats = self.gestion_riesgo.estadisticas()
            posiciones = len(self.estado.posiciones_abiertas)
            ml_info = "activo" if self.ml_optimizer.debe_predecir() else "aprendiendo"
            self.logger.debug(
                f"💓 Heartbeat: capital=${stats.get('capital_actual', 0):.2f}, "
                f"posiciones={posiciones}, "
                f"ops_hoy={stats.get('operaciones_hoy', 0)}, "
                f"ML={ml_info}"
            )
        except Exception:
            pass

    # ============================================================
    # THREAD: NOTICIAS
    # ============================================================

    def _thread_noticias(self):
        """Actualiza noticias."""
        if not self._ejecutando:
            return
        self._actualizar_noticias()

    def _actualizar_noticias(self):
        try:
            self.noticias.actualizar()
        except Exception as e:
            self.logger.warning(f"⚠️ Error actualizando noticias: {e}")

    # ============================================================
    # THREAD: INFORME DIARIO
    # ============================================================

    def _thread_informe_diario(self):
        """Genera el informe diario a las 00:00 UTC."""
        if not hasattr(self, 'informe_diario') or self.informe_diario is None:
            return

        ahora = now_utc()

        if ahora.hour != 0:
            return

        hoy = ahora.date()
        if self._ultimo_informe_fecha == hoy:
            return

        try:
            self.logger.info("📊 Generando informe diario automático...")

            fecha_informe = hoy - timedelta(days=1)

            informe = self.informe_diario.generar(fecha=fecha_informe)
            self.informe_diario.guardar(informe)
            self.informe_diario.enviar(informe)

            self._ultimo_informe_fecha = hoy
            self.logger.info("✅ Informe diario generado y enviado")

            # Reset diario de gestión de riesgo
            self.gestion_riesgo.reset_diario(current_time=ahora)

            # ✅ V10.1: Evaluar drift del ML (reentrena si aplica)
            try:
                if self.ml_optimizer and self.ml_optimizer.debe_predecir():
                    self.logger.info("🧠 Evaluando drift ML...")
                    if self.ml_optimizer.evaluar_drift():
                        self.logger.info("🌊 Drift detectado → modelo reentrenado")
            except Exception as e:
                self.logger.debug(f"⚠️ Error evaluando drift: {e}")

        except Exception as e:
            self.logger.error(f"❌ Error generando informe diario: {e}", exc_info=True)

    # ============================================================
    # ACTUALIZAR OPORTUNIDADES F2 (con M15 fresco)
    # ============================================================

    def _actualizar_oportunidades_fase2(self):
        """Actualiza F2 con M15 fresco."""
        if not self.pipeline:
            return

        oportunidades_fase2 = [
            o for o in self.pipeline.estados.values()
            if o.fase_actual == FaseOportunidad.FASE_2
        ]

        if not oportunidades_fase2:
            return

        for estado in oportunidades_fase2:
            simbolo = estado.simbolo
            try:
                df_m15 = self.cache.get_datos(
                    simbolo=simbolo,
                    timeframe=15,
                    n_velas=200,
                    fetch_func=self.mt5.obtener_datos,
                )

                if df_m15 is None or len(df_m15) < 50:
                    continue

                analisis_rapido = self.analisis_capas.analisis_rapido(df_m15, simbolo)
                if not analisis_rapido.pasa_filtro:
                    continue

                analisis_medio = self.analisis_capas.analisis_medio(
                    df_m15, simbolo, analisis_rapido, {}
                )
                if not analisis_medio.pasa_filtro:
                    continue

                score_m15 = self._calcular_score_m15_simple(analisis_medio, analisis_rapido)

                # ✅ FIX #1: calcular dirección real de M15
                direccion_m15 = self._determinar_direccion_m15(
                    analisis_rapido, analisis_medio
                )

                self.pipeline.actualizar_fase_2(
                    simbolo=simbolo,
                    analisis_m15={
                        'rapido': getattr(analisis_rapido, '__dict__', {}),
                        'medio': getattr(analisis_medio, '__dict__', {}),
                        'score': score_m15,
                        'direccion': direccion_m15,
                        'adx': getattr(analisis_medio, 'adx', 0),
                        'rsi': getattr(analisis_medio, 'rsi', 50),
                    },
                    score=score_m15,
                )
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error F2 update: {e}")

    def _calcular_score_m15_simple(self, analisis_medio, analisis_rapido) -> float:
        """Score M15 simplificado."""
        score = 50.0

        if analisis_medio.adx > 30:
            score += 15
        elif analisis_medio.adx > 20:
            score += 10
        elif analisis_medio.adx > 10:
            score += 5

        if analisis_rapido.volumen_relativo > 2.0:
            score += 15
        elif analisis_rapido.volumen_relativo > 1.5:
            score += 10
        elif analisis_rapido.volumen_relativo > 1.0:
            score += 5

        if abs(analisis_medio.macd_histogram) > 0.0005:
            score += 10
        elif abs(analisis_medio.macd_histogram) > 0.0002:
            score += 5

        if analisis_medio.en_nivel_clave:
            score += 10

        return min(100.0, max(0.0, score))

    # ============================================================
    # PROMOVER OPORTUNIDADES
    # ============================================================

    def _promover_oportunidades(self):
        """Promueve oportunidades."""
        if not self.pipeline:
            return
        self._diagnosticar_pipeline()
        self.pipeline.promover_automaticamente()

    def _diagnosticar_pipeline(self):
        """Diagnóstico del pipeline."""
        if not self.pipeline:
            return

        activos = self.pipeline.obtener_activos()
        f1 = sum(1 for e in activos if e.fase_actual == FaseOportunidad.FASE_1)
        f2 = sum(1 for e in activos if e.fase_actual == FaseOportunidad.FASE_2)
        f3 = sum(1 for e in activos if e.fase_actual == FaseOportunidad.FASE_3)

        if f1 + f2 + f3 > 0:
            self.logger.debug(f"📊 Pipeline: F1:{f1} F2:{f2} F3:{f3}")

    # ============================================================
    # VERIFICAR NIVELES ESPERADOS
    # ============================================================

    def _verificar_niveles_esperados(self):
        """Espera activa: verifica si el precio llegó al nivel esperado."""
        if not self.pipeline:
            return

        activos = self.pipeline.obtener_activos()

        for estado in activos:
            simbolo = estado.simbolo
            ctx_h1 = estado.contexto_h1 if estado.contexto_h1 else {}

            nivel_esperado = ctx_h1.get('nivel_usado')
            if not nivel_esperado:
                continue

            precio_actual = self._obtener_precio_para_verificacion(simbolo)
            if not precio_actual:
                continue

            distancia = abs(precio_actual - nivel_esperado) / precio_actual * 100
            if distancia < 0.5:
                self.logger.info(
                    f"🎯 {simbolo}: Precio en nivel esperado ({nivel_esperado:.5f})"
                )

    def _obtener_precio_para_verificacion(self, simbolo: str) -> Optional[float]:
        try:
            tick = self.mt5.obtener_precio(simbolo)
            if tick and tick.get('bid'):
                return float(tick['bid'])
        except Exception:
            pass
        return None

    # ============================================================
    # SNIPER CON VELA VIRTUAL
    # ============================================================

    def _ejecutar_sniper_con_vela_virtual(self):
        """Ejecuta el sniper."""
        if not self._ejecutando:
            return

        oportunidades = self.pipeline.obtener_activos() if self.pipeline else []
        oportunidades_f3 = [
            o for o in oportunidades if o.fase_actual == FaseOportunidad.FASE_3
        ]

        if not oportunidades_f3:
            return

        # Filtrar operables
        elegibles = []
        for estado in oportunidades_f3:
            es_operativo, _ = self.horario.es_horario_operativo(estado.simbolo)
            if es_operativo:
                elegibles.append(estado)

        if not elegibles:
            return

        # Ordenar y limitar
        elegibles.sort(key=lambda x: x.score_acumulado, reverse=True)

        for estado in elegibles[:5]:
            if not self._ejecutando:
                break
            self._evaluar_oportunidad_con_vela_virtual(estado)

    def _obtener_df_m5_con_precio_real(self, simbolo: str) -> Optional[pd.DataFrame]:
        """
        M5 con vela virtual actualizada al precio actual.
        ✅ FIX #3: volumen estimado realista.
        """
        df_m5 = self.cache.get_datos(
            simbolo=simbolo,
            timeframe=5,
            n_velas=150,
            fetch_func=self.mt5.obtener_datos,
        )
        if df_m5 is None or len(df_m5) < 50:
            return None

        df_m5 = df_m5.copy()

        try:
            tick = self.mt5.obtener_precio(simbolo)
        except Exception:
            tick = None

        if not tick:
            return df_m5

        bid = tick.get('bid', 0)
        ask = tick.get('ask', 0)
        if bid <= 0 or ask <= 0:
            return df_m5

        precio_actual = (bid + ask) / 2
        now = now_utc()
        ultima = df_m5.iloc[-1]

        # ✅ FIX #3: volumen estimado (20% del medio de últimas 5 velas)
        try:
            volumen_medio_5 = float(df_m5['Volume'].iloc[-5:].mean())
            volumen_virtual = max(1.0, volumen_medio_5 * 0.2)
        except Exception:
            volumen_virtual = max(1.0, float(ultima.get('Volume', 100)) * 0.2)

        vela = {
            'Open': float(ultima['Close']),
            'High': max(float(ultima['High']), bid, ask),
            'Low': min(float(ultima['Low']), bid, ask),
            'Close': precio_actual,
            'Volume': volumen_virtual,
        }
        df_m5.loc[now] = vela
        df_m5.attrs['precio_tick'] = tick
        df_m5.attrs['precio_analisis'] = precio_actual
        df_m5.attrs['precio_entrada_compra'] = ask
        df_m5.attrs['precio_entrada_venta'] = bid
        df_m5.attrs['es_vela_virtual'] = True

        return df_m5

    def _evaluar_oportunidad_con_vela_virtual(self, estado):
        """Evalúa oportunidad con vela virtual."""
        simbolo = estado.simbolo

        lock = self._obtener_lock(simbolo)
        if not lock.acquire(blocking=False):
            self.logger.debug(f"⏭️ {simbolo}: ya hay evaluación en curso")
            return

        try:
            if estado.fase_actual != FaseOportunidad.FASE_3:
                return

            puede, razon = self.gestion_riesgo.puede_operar_simbolo(simbolo)
            if not puede:
                self.logger.debug(f"⏭️ {simbolo}: {razon}")
                return

            if not self.modo_backtest:
                try:
                    posiciones = self.mt5.obtener_posiciones()
                    if posiciones and any(p['simbolo'] == simbolo for p in posiciones):
                        return
                except Exception:
                    pass

            if estado.direccion == 'NEUTRAL':
                return

            contexto_h1 = estado.contexto_h1 if estado.contexto_h1 else {}

            df_m5 = self._obtener_df_m5_con_precio_real(simbolo)
            if df_m5 is None or len(df_m5) < 50:
                return

            df_h1 = self.cache.get_datos(
                simbolo=simbolo,
                timeframe=60,
                n_velas=250,
                fetch_func=self.mt5.obtener_datos,
            )

            analisis_h1 = None
            if df_h1 is not None and len(df_h1) > 50:
                try:
                    ar = self.analisis_capas.analisis_rapido(df_h1, simbolo)
                    if ar.pasa_filtro:
                        analisis_h1 = self.analisis_capas.analisis_medio(
                            df_h1, simbolo, ar, contexto_h1.get('niveles', {})
                        )
                except Exception as e:
                    self.logger.debug(f"⚠️ {simbolo}: Error H1: {e}")

            precio_actual = float(df_m5['Close'].iloc[-1])
            tick_data = df_m5.attrs.get('precio_tick')
            precio_entrada = precio_actual
            if tick_data:
                precio_entrada = float(
                    tick_data.get('ask' if estado.direccion == 'COMPRA' else 'bid', precio_actual)
                )

            # Ejecutar sniper
            try:
                resultado = self.sniper_checklist.evaluar_sniper_optimizado(
                    simbolo=simbolo,
                    df_m5=df_m5,
                    precio_actual=precio_actual,
                    direccion=estado.direccion,
                    estado_pipeline=estado,
                    analisis_rapido=None,
                    analisis_medio=analisis_h1,
                    ejecutar_pesado=False,
                    contexto_h1=contexto_h1,
                    calidad_horario='REGULAR',
                    tick_data=tick_data,
                    precio_entrada=precio_entrada,
                )
            except Exception as e:
                self.logger.warning(f"⚠️ {simbolo}: Error sniper: {e}")
                resultado = None

            if resultado:
                self.logger.info(f"🎯 {simbolo}: ¡OPORTUNIDAD! Modo: {resultado.get('modo', '?')}")

                try:
                    exito = self.ejecutor.ejecutar(resultado)
                except Exception as e:
                    self.logger.error(f"❌ {simbolo}: Error ejecutando: {e}")
                    exito = False

                if exito:
                    self.pipeline.marcar_ejecutada(simbolo)
                    estado.metadata['sniper_fallos'] = 0
                    self.logger.info(f"✅ {simbolo}: EJECUTADA")
                else:
                    estado.metadata['sniper_fallos'] = estado.metadata.get('sniper_fallos', 0) + 1
                    estado.timestamp_ultima_actualizacion = now_utc()
            else:
                fallos = estado.metadata.get('sniper_fallos', 0) + 1
                estado.metadata['sniper_fallos'] = fallos
                estado.timestamp_ultima_actualizacion = now_utc()

                if fallos >= 10:
                    self.pipeline._degradar_oportunidad(
                        simbolo,
                        razon=f"Demasiados fallos de sniper ({fallos})",
                        motivo=MotivoDegradacion.SNIPER_FALLOS,
                    )

        finally:
            lock.release()

    # ============================================================
    # SÍMBOLOS OPERABLES
    # ============================================================

    def _obtener_simbolos_operables(self) -> List[str]:
        """Obtiene símbolos operables."""
        ahora = now_utc()
        operables = []

        for simbolo in self.config.SIMBOLOS_COMPLETOS:
            es_operativo, _ = self.horario.es_horario_operativo(simbolo, ahora)
            if es_operativo:
                operables.append(simbolo)

        return operables

    # ============================================================
    # UTILIDADES
    # ============================================================

    def _verificar_capacidad(self) -> bool:
        """Verifica capacidad de operar."""
        if self.modo_backtest:
            return True

        try:
            if self.gestion_riesgo.circuit_breaker.verificar():
                return False
            if self.gestion_riesgo.capital_actual <= 0:
                return False

            posiciones = self.mt5.obtener_posiciones()
            max_sim = self.gestion_riesgo.obtener_max_simultaneas()
            if posiciones and len(posiciones) >= max_sim:
                return False
        except Exception:
            return False

        return True

    def _sincronizar_estado_inicial(self):
        """Sincroniza estado al arrancar."""
        self.logger.info("🔄 Sincronizando estado inicial...")

        try:
            posiciones = self.mt5.obtener_posiciones()
        except Exception:
            posiciones = []

        for pos in posiciones:
            ticket = pos['ticket']
            magic = pos.get('magic', 0)
            es_bot = magic == self.config.MAGIC_NUMBER

            self.estado.posiciones_abiertas[ticket] = {
                'simbolo': pos['simbolo'],
                'direccion': pos['tipo'],
                'entrada': pos['precio_apertura'],
                'volumen': pos['volumen'],
                'sl': pos.get('sl', 0),
                'tp': pos.get('tp', 0),
                'timestamp_apertura': datetime.fromtimestamp(
                    pos.get('time', 0), tz=timezone.utc
                ),
                'es_manual': not es_bot,
                'es_bot': es_bot,
            }

            if self.almacen:
                try:
                    if not self.almacen.obtener_operacion_por_ticket(ticket):
                        self.almacen.guardar_operacion({
                            'ticket': ticket,
                            'simbolo': pos['simbolo'],
                            'direccion': 'COMPRA' if pos['tipo'] == 0 else 'VENTA',
                            'entrada': pos['precio_apertura'],
                            'lotes': pos['volumen'],
                            'sl': pos.get('sl', 0),
                            'tp': pos.get('tp', 0),
                            'timestamp': datetime.fromtimestamp(
                                pos.get('time', 0), tz=timezone.utc
                            ).isoformat(),
                            'estado': 'ABIERTA',
                            'es_bot': es_bot,
                            'modo': 'RECUPERADO',
                        })
                except Exception as e:
                    self.logger.debug(f"⚠️ Error recuperando {ticket}: {e}")

        self.logger.info(
            f"✅ {len(self.estado.posiciones_abiertas)} posiciones sincronizadas"
        )

    def _validar_frescura_pipeline(self):
        """Valida frescura del pipeline."""
        if not self.pipeline:
            return

        ultima = self._obtener_ultima_actualizacion_pipeline()
        if ultima is None:
            return

        ahora = now_utc()
        horas = (ahora - ultima).total_seconds() / 3600

        if (ahora - self._hora_inicio).total_seconds() < 60:
            return
        if horas < 1.0:
            return
        if horas < 6.0:
            self.logger.info(f"⚠️ Pipeline {horas:.1f}h antiguo → degradando F2/F3")
            for s, e in self.pipeline.estados.items():
                if e.fase_actual in (FaseOportunidad.FASE_2, FaseOportunidad.FASE_3):
                    self.pipeline._degradar_oportunidad(
                        s, razon=f"Pipeline antiguo ({horas:.1f}h)",
                        motivo=MotivoDegradacion.TIEMPO_EXCEDIDO,
                    )
        else:
            if (ahora - self._hora_inicio).total_seconds() > 6 * 3600:
                self.logger.info("❌ Pipeline muy antiguo → limpiando")
                self.pipeline.estados.clear()
                self.pipeline._guardar_estados_en_sqlite()

    def _obtener_ultima_actualizacion_pipeline(self) -> Optional[datetime]:
        """Última actualización del pipeline."""
        try:
            config = self.almacen.obtener_configuracion()
            data = config.get('pipeline_estados', {})
            if not data:
                return None

            timestamps = []
            for s, d in data.items():
                ts_str = d.get('timestamp_actualizacion')
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        timestamps.append(ts)
                    except Exception:
                        continue

            return max(timestamps) if timestamps else None
        except Exception:
            return None

    def _guardar_ultima_actualizacion_pipeline(self):
        """Guarda timestamp."""
        try:
            config = self.almacen.obtener_configuracion()
            ultima = self._obtener_ultima_actualizacion_pipeline()
            if ultima:
                config['ultima_actualizacion_pipeline'] = ultima.isoformat()
            else:
                config['ultima_actualizacion_pipeline'] = datetime.now(
                    timezone.utc
                ).isoformat()
            self.almacen.guardar_configuracion(config)
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando última actualización: {e}")

    # ============================================================
    # ESTADÍSTICAS
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """Estadísticas del bot."""
        try:
            stats = {
                'orquestador': {
                    'ejecutando': self._ejecutando,
                    'modo_backtest': self.modo_backtest,
                    'modo_depuracion': self.modo_depuracion,
                    'threads_activos': len([t for t in self._threads if t.is_alive()]),
                    'locks_simbolo': len(self._locks_simbolo),
                    'ops_cerradas_buffer': len(self._ops_cerradas_buffer),
                },
                'riesgo': self.gestion_riesgo.estadisticas(),
                'cache': self.cache.get_stats(),
                'pipeline': self.pipeline.get_stats() if self.pipeline else {},
                'monitor': self.monitor_posiciones.get_stats()
                    if hasattr(self, 'monitor_posiciones') else {},
            }

            # ✅ V10.1: stats ML
            if self.ml_optimizer:
                stats['ml'] = self.ml_optimizer.get_info()

            return stats
        except Exception as e:
            return {'error': str(e)}

    def print_stats(self):
        """Imprime estadísticas legibles."""
        stats = self.get_stats()

        print("\n" + "=" * 60)
        print("📊 ESTADÍSTICAS DEL ORQUESTADOR V10.1")
        print("=" * 60)

        orq = stats.get('orquestador', {})
        print(f"Ejecutando: {orq.get('ejecutando')}")
        print(f"Threads activos: {orq.get('threads_activos')}")
        print(f"Ops en buffer ML: {orq.get('ops_cerradas_buffer')}")

        riesgo = stats.get('riesgo', {})
        print(f"\n💰 Riesgo:")
        print(f"  Capital: ${riesgo.get('capital_actual', 0):.2f}")
        print(f"  Win rate: {riesgo.get('win_rate', 0):.1f}%")
        print(f"  Ops totales: {riesgo.get('total_operaciones', 0)}")

        ml = stats.get('ml', {})
        if ml:
            print(f"\n🧠 ML:")
            print(f"  Modelo: {'✅' if ml.get('tiene_modelo') else '⏳'}")
            print(f"  Último entreno: {ml.get('ultima_fecha_entreno', 'Nunca')}")
            print(f"  Ops desde entreno: {ml.get('ops_desde_ultimo_entreno', 0)}")
            metricas = ml.get('metricas', {})
            if metricas:
                test = metricas.get('test', {})
                print(f"  AUC: {test.get('roc_auc', 0):.3f}")
                print(f"  Accuracy: {test.get('accuracy', 0):.3f}")

        print("\n" + "=" * 60)


# ============================================================
# FACTORY
# ============================================================

def create_orquestador(
    modo_backtest: bool = False,
    modo_depuracion: bool = False,
) -> Orquestador:
    """Crea una instancia del orquestador."""
    return Orquestador(modo_backtest=modo_backtest, modo_depuracion=modo_depuracion)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Inicializando orquestador V10.1 ML-CONECTADO...")

    orq = Orquestador(modo_backtest=True, modo_depuracion=True)

    print(f"\n✅ Orquestador V10.1 inicializado")
    print(f"   Backtest: {orq.modo_backtest}")
    print(f"   Depuración: {orq.modo_depuracion}")
    print(f"   Capital: ${orq.config.CAPITAL_INICIAL:.2f}")
    print(f"   Símbolos: {len(orq.config.SIMBOLOS_COMPLETOS)}")
    print(f"   InformeDiario: {'✅' if hasattr(orq, 'informe_diario') else '❌'}")
    print(f"   Pipeline: {'✅' if orq.pipeline else '❌'}")
    print(f"   ML Optimizer: {'✅' if orq.ml_optimizer else '❌'}")
    print(f"   ML con modelo: {'✅' if orq.ml_optimizer and orq.ml_optimizer.debe_predecir() else '⏳ Aprendiendo'}")

    # Test método nuevo
    print("\n📊 Test _determinar_direccion_m15:")

    class MockMedio:
        rsi = 60
        macd_histogram = 0.001
        adx = 25

    class MockRapido:
        volumen_relativo = 1.5

    dir_m15 = orq._determinar_direccion_m15(MockRapido(), MockMedio())
    print(f"   RSI=60, MACD>0, ADX=25 → {dir_m15}")

    class MockMedio2:
        rsi = 40
        macd_histogram = -0.001
        adx = 25

    dir_m15 = orq._determinar_direccion_m15(MockRapido(), MockMedio2())
    print(f"   RSI=40, MACD<0, ADX=25 → {dir_m15}")

    class MockMedio3:
        rsi = 50
        macd_histogram = 0
        adx = 5

    dir_m15 = orq._determinar_direccion_m15(MockRapido(), MockMedio3())
    print(f"   RSI=50, MACD=0, ADX=5 → {dir_m15}")

    # Stats
    print("\n📊 Estadísticas:")
    orq.print_stats()

    print("\n✅ Prueba completada")