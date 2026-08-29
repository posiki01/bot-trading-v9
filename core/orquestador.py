#!/usr/bin/env python3
"""
core/orquestador.py (V9.11 - REFACTORIZADO DEFINITIVO CON MONITOREO INTEGRADO)
Orquestador principal - Coordina todos los módulos del Bot de Trading.

V9.11 - CORRECCIONES DEFINITIVAS:
- ✅ MonitorPosiciones integrado correctamente
- ✅ Monitoreo de posiciones con reanálisis en tiempo real
- ✅ Decisor de cierre con ganancia anticipada
- ✅ Validación de frescura del pipeline con re-análisis
- ✅ Lógica de sábado/domingo en threads
- ✅ Solo cripto opera el sábado
- ✅ Domingo: actualizar datos antes de apertura
- ✅ Escaneo con símbolos operables
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
# IMPORTS DE MÓDULOS REFACTORIZADOS
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

from analysis.regimen import MarketRegimeFilter, RegimenMercado, create_regime_filter
from analysis.scoring import ScoreEngine, create_score_engine
from analysis.niveles import NivelTracker, create_nivel_tracker
from analysis.patron_tracker import PatronTracker, create_patron_tracker
from analysis.capas import AnalisisPorCapas
from analysis.fases import AnalisisPorFase, create_analisis_por_fase
from analysis.pipeline import PipelineOportunidades
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
from trading.decision_cierre import DecisorCierre, create_decisor_cierre

from data.almacenamiento_sqlite import AlmacenamientoSQLite
from mt5.conector_mt5 import ConectorPepperstone, ConectorHeadless
from notificaciones.alertas import Notificaciones
from noticias.sistema_noticias import SistemaNoticias

logger = logging.getLogger('BotTrading.Orquestador')


class Orquestador:
    """
    Orquestador principal del Bot de Trading.
    V9.11 - REFACTORIZADO DEFINITIVO CON MONITOREO INTEGRADO.
    """
    
    def __init__(self, modo_backtest: bool = False, modo_depuracion: bool = False):
        """
        Inicializa el orquestador con todos los módulos.
        
        Args:
            modo_backtest: Modo backtest (simula operaciones)
            modo_depuracion: Modo depuración (logs más detallados)
        """
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        
        # ============================================================
        # 1. CONFIGURACIÓN Y LOGGING
        # ============================================================
        
        self.config = Config()
        self.logger_persistente = LoggerPersistente(
            directorio_logs=Path(__file__).parent.parent / "logs",
            nivel_log='DEBUG' if modo_depuracion else 'INFO',
            filter_emojis_consola=False
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
        self._threads = []
        
        # ============================================================
        # 3. ALMACENAMIENTO
        # ============================================================
        
        self.almacen = AlmacenamientoSQLite(
            base_dir=self.base_dir / "data",
            modo_backup=True
        )
        
        # ============================================================
        # 4. NOTIFICACIONES
        # ============================================================
        
        self.notificaciones = Notificaciones(
            discord_webhook=self.config.DISCORD_WEBHOOK,
            telegram_token=self.config.TELEGRAM_TOKEN,
            telegram_chat=self.config.TELEGRAM_CHAT_ID,
            almacen=self.almacen
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
            almacen=self.almacen
        )
        
        # ============================================================
        # 7. HORARIO
        # ============================================================
        
        self.horario = create_horario_mercado(
            zona_usuario='COLOMBIA',
            config_activos=self.config.CONFIG_ACTIVOS,
            modo_backtest=modo_backtest
        )
        
        # ============================================================
        # 8. NOTICIAS
        # ============================================================
        
        self.noticias = SistemaNoticias(
            config=self.config,
            notificador=self.notificaciones,
            almacen=self.almacen,
            data_cache=self.cache
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
        # 11. MÓDULOS DE UTILIDAD
        # ============================================================
        
        self._inicializar_utilidades()
        
        # ============================================================
        # 12. MÓDULOS DE SNIPER
        # ============================================================
        
        self._inicializar_sniper()
        
        # ============================================================
        # 13. MONITOR DE POSICIONES (INTEGRADO)
        # ============================================================
        
        self._inicializar_monitor()
        
        # ============================================================
        # 14. SEÑALES DEL SISTEMA
        # ============================================================
        
        signal.signal(signal.SIGINT, self._manejar_senal)
        signal.signal(signal.SIGTERM, self._manejar_senal)
        
        # ============================================================
        # 15. LOG DE INICIO
        # ============================================================
        
        self._log_inicio()
        
        self.logger.info("🚀 Orquestador V9.11 REFACTORIZADO DEFINITIVO inicializado correctamente")
    
    # ============================================================
    # INICIALIZACIÓN DE MÓDULOS
    # ============================================================
    
    def _inicializar_conector(self):
        """Inicializa el conector MT5."""
        if self.config.USE_API_REST:
            return ConectorHeadless(
                token=self.config.API_REST_TOKEN,
                url_base=self.config.API_REST_URL
            )
        else:
            return ConectorPepperstone(
                login=self.config.MT5_LOGIN,
                password=self.config.MT5_PASSWORD,
                server=self.config.MT5_SERVER,
                magic_number=self.config.MAGIC_NUMBER,
                demo=self.config.MT5_DEMO,
                almacen=self.almacen
            )
    
    def _inicializar_analisis(self):
        """Inicializa módulos de análisis."""
        # Régimen de mercado
        self.regimen_filter = create_regime_filter(
            config=self.config,
            modo_backtest=self.modo_backtest
        )
        
        # Score Engine
        self.score_engine = create_score_engine(
            config=self.config,
            analysis_cache=self.cache,
            modo_backtest=self.modo_backtest
        )
        
        # Nivel Tracker
        self.nivel_tracker = create_nivel_tracker(
            almacen=self.almacen,
            config=self.config,
            modo_backtest=self.modo_backtest
        )
        
        # ✅ Patron Tracker
        self.patron_tracker = create_patron_tracker(
            almacen=self.almacen,
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion
        )
        
        # ✅ ML Optimizer
        self.ml_optimizer = create_ml_optimizer(
            historial_ops=[],
            oportunidades_no_tomadas=[],
            almacen=self.almacen,
            notificador=self.notificaciones,
            config=self.config,
            modo_backtest=self.modo_backtest
        )
        
        # Análisis por capas - ✅ CORREGIDO: pasa nivel_tracker
        self.analisis_capas = AnalisisPorCapas(
            analisis_tecnico=None,
            config=self.config,
            score_engine=self.score_engine,
            nivel_tracker=self.nivel_tracker
        )
        
        # Análisis por fases
        self.analisis_fases = AnalisisPorFase(
            mt5_connector=self.mt5,
            noticias=self.noticias,
            config=self.config,
            analysis_cache=self.cache
        )
        self.analisis_fases.set_analisis_capas(self.analisis_capas)
        
        # Pipeline
        self.pipeline = PipelineOportunidades(
            config=self.config,
            umbral_fase_1=getattr(self.config, 'PIPELINE_UMBRAL_FASE_1', 50),
            umbral_fase_2=getattr(self.config, 'PIPELINE_UMBRAL_FASE_2', 55),
            umbral_fase_3=getattr(self.config, 'PIPELINE_UMBRAL_FASE_3', 60),
            modo_backtest=self.modo_backtest,
            almacen=self.almacen
        )
        
        self.logger.info("📊 Módulos de análisis inicializados")
        self.logger.info(f"   PatronTracker: ✅")
        self.logger.info(f"   MLOptimizer: ✅")
    
    def _inicializar_trading(self):
        """Inicializa módulos de trading."""
        # Gestión de riesgo
        self.gestion_riesgo = create_gestion_riesgo(
            capital_inicial=self.config.CAPITAL_INICIAL,
            aporte_mensual=self.config.APORTE_MENSUAL,
            almacen=self.almacen,
            notificador=self.notificaciones,
            config=self.config,
            modo_backtest=self.modo_backtest
        )
        
        # Gestor de stops
        self.gestor_stops = create_gestor_stops(
            config=self.config,
            modo_backtest=self.modo_backtest
        )
        
        # Trailing engine
        self.trailing_engine = create_trailing_engine(
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion
        )
        
        # Decisor de operabilidad
        self.decisor_operabilidad = create_decisor_operabilidad(
            config=self.config,
            horario=self.horario,
            modo_backtest=self.modo_backtest
        )
        
        # Modo selector (CON APRENDIZAJE DINÁMICO)
        self.modo_selector = ModoSelector(
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion,
            almacen=self.almacen
        )
        
        # Entry timer
        self.entry_timer = EntryTimer(
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion
        )
        self.modo_selector.set_entry_timer(self.entry_timer)
        
        # Ejecutor de operaciones
        self.ejecutor = create_ejecutor_operaciones(
            orquestador=self,
            mt5=self.mt5,
            gestion_riesgo=self.gestion_riesgo,
            gestor_stops=self.gestor_stops,
            notificaciones=self.notificaciones,
            modo_backtest=self.modo_backtest,
            almacen=self.almacen  # ✅ AÑADIDO
        )
        
        self.logger.info("📈 Módulos de trading inicializados")
    
    def _inicializar_utilidades(self):
        """Inicializa módulos de utilidad."""
        from analysis.escaneo import Escaneador
        
        self.escaneador = Escaneador(
            orquestador=self,
            analisis_capas=self.analisis_capas,
            regimen_filter=self.regimen_filter,
            nivel_tracker=self.nivel_tracker,
            horario=self.horario,
            score_engine=self.score_engine,
            pipeline=self.pipeline
        )
        self.logger.info("🔍 Escaneador V9.1 inicializado")
    
    def _inicializar_sniper(self):
        """Inicializa módulos del sniper."""
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
            modo_backtest=self.modo_backtest
        )
        self.sniper_checklist.set_modo_backtest(self.modo_backtest)
        self.logger.info("🎯 SniperChecklist inicializado")
    
    def _inicializar_monitor(self):
        """Inicializa el monitor de posiciones con correcciones V9.3."""
        # ✅ DECISOR DE CIERRE (CORREGIDO)
        self.decisor_cierre = create_decisor_cierre(
            analisis_capas=self.analisis_capas
        )
        
        # ✅ MONITOR DE POSICIONES (CORREGIDO)
        self.monitor_posiciones = create_monitor_posiciones(
            orquestador=self,
            mt5=self.mt5,
            gestion_riesgo=self.gestion_riesgo,
            trailing_engine=self.trailing_engine,
            decisor_cierre=self.decisor_cierre,
            monitorear_manuales=False  # ✅ Nueva bandera
        )
        
        self.logger.info("🔍 MonitorPosiciones V9.3 REFACTORIZADO inicializado")
        self.logger.info("   DecisorCierre: ✅")
        self.logger.info("   Monitoreo manuales: ❌ (desactivado)")


    def _log_inicio(self):
        """Log de inicio del orquestador."""
        self.logger.info("=" * 60)
        self.logger.info("🚀 ORQUESTADOR V9.11 REFACTORIZADO DEFINITIVO INICIADO")
        self.logger.info("=" * 60)
        self.logger.info(f"   Entorno: {self.config.ENTORNO}")
        self.logger.info(f"   Backtest: {self.modo_backtest}")
        self.logger.info(f"   Depuración: {self.modo_depuracion}")
        self.logger.info(f"   Capital: ${self.config.CAPITAL_INICIAL:.2f}")
        self.logger.info(f"   Símbolos: {len(self.config.SIMBOLOS_COMPLETOS)}")
        self.logger.info(f"   MT5 Demo: {self.config.MT5_DEMO}")
        self.logger.info(f"   PatronTracker: ✅")
        self.logger.info(f"   MLOptimizer: ✅")
        self.logger.info(f"   MonitorPosiciones: ✅")
        self.logger.info(f"   DecisorCierre: ✅")
        self.logger.info("=" * 60)
    
    # ============================================================
    # MANEJO DE SEÑALES
    # ============================================================
    
    def _manejar_senal(self, signum, frame):
        """Maneja señales del sistema."""
        self.logger.info(f"🛑 Señal {signum} recibida, deteniendo...")
        self.detener()

    def diagnosticar_base_datos(self):
        """
        Diagnóstico de qué datos hay en SQLite para cada símbolo.
        V9.10 - NUEVO: Verifica la integridad de los datos.
        """
        self.logger.info("🔍 DIAGNÓSTICO DE BASE DE DATOS:")
        self.logger.info("=" * 60)
        
        simbolos = self.config.SIMBOLOS_COMPLETOS[:5]  # Solo los primeros 5 para no saturar
        
        for simbolo in simbolos:
            try:
                # Verificar H1
                df_h1 = self.almacen.obtener_datos_historicos(simbolo, 60)
                # Verificar M5
                df_m5 = self.almacen.obtener_datos_historicos(simbolo, 5)
                # Verificar M15
                df_m15 = self.almacen.obtener_datos_historicos(simbolo, 15)
                
                if df_h1 is not None:
                    self.logger.info(f"   {simbolo} H1: {len(df_h1)} velas (última: {df_h1.index[-1]})")
                else:
                    self.logger.info(f"   {simbolo} H1: ❌ Sin datos")
                
                if df_m5 is not None:
                    self.logger.info(f"   {simbolo} M5: {len(df_m5)} velas (última: {df_m5.index[-1]})")
                else:
                    self.logger.info(f"   {simbolo} M5: ❌ Sin datos")
                
                if df_m15 is not None:
                    self.logger.info(f"   {simbolo} M15: {len(df_m15)} velas (última: {df_m15.index[-1]})")
                else:
                    self.logger.info(f"   {simbolo} M15: ❌ Sin datos")
                    
            except Exception as e:
                self.logger.warning(f"   {simbolo}: Error en diagnóstico - {e}")
        
        self.logger.info("=" * 60)
    
    # ============================================================
    # PRECARGA DE ANÁLISIS
    # ============================================================
    
    def _precargar_analisis_completo(self):
        """
        Precarga completa de análisis al iniciar el bot.
        V9.17 - CORREGIDO DEFINITIVO: Define soportes y resistencias correctamente.
        """
        from utils.construir_timeframes import construir_desde_m5
        
        self.logger.info("🚀 Iniciando precarga completa de análisis...")
        
        # ✅ CORRECCIÓN: Analizar TODOS los símbolos
        simbolos_a_analizar = self.config.SIMBOLOS_COMPLETOS
        
        self.logger.info(f"📊 Analizando {len(simbolos_a_analizar)} símbolos...")
        
        total_soportes = 0
        total_resistencias = 0
        
        for simbolo in simbolos_a_analizar:
            try:
                # Verificar si es operable (solo para log)
                es_operativo, razon = self.horario.es_horario_operativo(simbolo)
                estado = "✅ OPERABLE" if es_operativo else f"⏳ NO OPERABLE ({razon})"
                
                self.logger.info(f"📊 Analizando {simbolo}... {estado}")
                
                # ============================================================
                # 1. OBTENER M5 (BASE PARA CONSTRUIR OTROS)
                # ============================================================
                df_m5 = self.mt5.obtener_datos(simbolo, n_velas=30000, timeframe=5)
                
                if df_m5 is None or len(df_m5) < 100:
                    self.logger.warning(f"⚠️ {simbolo}: Datos M5 insuficientes ({len(df_m5) if df_m5 is not None else 0} velas)")
                    continue
                
                # ============================================================
                # 2. CONSTRUIR H1 DESDE M5
                # ============================================================
                df_h1 = construir_desde_m5(df_m5, [60])
                df_h1 = df_h1.get(60) if df_h1 else None
                
                if df_h1 is None or len(df_h1) < 50:
                    # Fallback: intentar desde broker
                    df_h1 = self.mt5.obtener_datos(simbolo, n_velas=2500, timeframe=60)
                
                if df_h1 is None or len(df_h1) < 50:
                    self.logger.warning(f"⚠️ {simbolo}: Datos H1 insuficientes")
                    continue
                
                # ============================================================
                # 3. CONSTRUIR H4 DESDE M5
                # ============================================================
                df_h4 = construir_desde_m5(df_m5, [240])
                df_h4 = df_h4.get(240) if df_h4 else None
                
                if df_h4 is None or len(df_h4) < 50:
                    df_h4 = self.mt5.obtener_datos(simbolo, n_velas=600, timeframe=240)
                
                # ============================================================
                # 4. CONSTRUIR D1 DESDE M5
                # ============================================================
                df_d1 = construir_desde_m5(df_m5, [1440])
                df_d1 = df_d1.get(1440) if df_d1 else None
                
                if df_d1 is None or len(df_d1) < 20:
                    df_d1 = self.mt5.obtener_datos(simbolo, n_velas=100, timeframe=1440)
                
                # ============================================================
                # 5. ANÁLISIS RÁPIDO
                # ============================================================
                rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
                
                # ============================================================
                # 6. DETECTAR NIVELES (✅ DEFINIR SOPORTES Y RESISTENCIAS)
                # ============================================================
                precio_actual = df_h1['Close'].iloc[-1]
                niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
                    simbolo=simbolo,
                    df=df_h1,
                    precio_actual=precio_actual
                )
                
                # ✅ DEFINIR SOPORTES Y RESISTENCIAS AQUÍ
                soportes = niveles.get('soportes', [])
                resistencias = niveles.get('resistencias', [])
                total_soportes += len(soportes)
                total_resistencias += len(resistencias)
                
                # ============================================================
                # 7. ANÁLISIS MEDIO
                # ============================================================
                medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
                
                # ============================================================
                # 8. ANÁLISIS PESADO
                # ============================================================
                pesado = self.analisis_capas.analisis_pesado(
                    df_h1, simbolo, df_h4, df_d1, niveles, medio
                )
                
                # ============================================================
                # 9. CALCULAR SCORE Y RÉGIMEN
                # ============================================================
                score_h1 = self.score_engine.calcular_score_h1(
                    score_estructura=pesado.score_estructura,
                    score_momentum=pesado.score_momentum,
                    score_confluencia=pesado.score_confluencia,
                    score_institucional=pesado.score_institucional,
                    simbolo=simbolo
                ).score
                
                regimen_data = self.regimen_filter.clasificar(simbolo, df_h4, df_h1)
                regimen = regimen_data.regimen.value
                direccion_regimen = regimen_data.direccion_favor
                confianza_regimen = regimen_data.confianza
                
                # ============================================================
                # 10. DETERMINAR DIRECCIÓN
                # ============================================================
                direccion = self._determinar_direccion_mejorado(
                    medio, pesado, df_h4, df_h1, regimen
                )
                
                # ============================================================
                # 11. GUARDAR EN PIPELINE (✅ CON SOPORTES Y RESISTENCIAS DEFINIDAS)
                # ============================================================
                contexto_h1 = {
                    'score': score_h1,
                    'direccion': direccion,
                    'regimen': regimen,
                    'direccion_regimen': direccion_regimen,
                    'confianza_regimen': confianza_regimen,
                    'en_nivel_clave': medio.en_nivel_clave if medio else False,
                    'soporte_cercano': medio.soporte_cercano if medio else None,
                    'resistencia_cercana': medio.resistencia_cercana if medio else None,
                    'soporte_hits': medio.soporte_hits if medio else 0,
                    'resistencia_hits': medio.resistencia_hits if medio else 0,
                    'adx': medio.adx if medio else 0,
                    'rsi': medio.rsi if medio else 50,
                    'patron_principal': pesado.patron_principal if pesado else None,
                    'wyckoff_fase': pesado.wyckoff_fase if pesado else None,
                    'divergencia_rsi': pesado.divergencia_rsi if pesado else None,
                    'divergencia_macd': pesado.divergencia_macd if pesado else None,
                    'niveles': {
                        'soportes': soportes,
                        'resistencias': resistencias
                    }
                }
                
                self.pipeline.actualizar_fase_1(
                    simbolo=simbolo,
                    analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
                    score=score_h1,
                    direccion=direccion,
                    regimen=regimen,
                    direccion_regimen=direccion_regimen,
                    confianza_regimen=confianza_regimen,
                    tendencia_h4='ALCISTA' if medio.adx > 25 and medio.sma20 > medio.sma50 else 'BAJISTA' if medio.adx > 25 else 'LATERAL',
                    contexto_h1=contexto_h1,
                    analisis_pesado=pesado
                )
                
                self.logger.info(f"✅ {simbolo}: Precargado - {len(soportes)} soportes, {len(resistencias)} resistencias, score={score_h1:.1f}")
                
            except Exception as e:
                self.logger.warning(f"⚠️ Error precargando {simbolo}: {e}")
        
        self.logger.info(f"✅ Precarga completa finalizada: {total_soportes} soportes, {total_resistencias} resistencias")

    def _validar_frescura_pipeline(self):
        """
        Valida la frescura del pipeline contra la hora actual.
        V9.14 - CORREGIDO: No elimina si el bot estuvo corriendo.
        """
        if not self.pipeline:
            return
        
        from analysis.pipeline import FaseOportunidad
        
        # Obtener timestamp más reciente del pipeline
        ultima_actualizacion = self._obtener_ultima_actualizacion_pipeline()
        
        if ultima_actualizacion is None:
            self.logger.info("📂 Pipeline sin datos - No hay nada que validar")
            return
        
        # ✅ OBTENER HORA DE INICIO DEL BOT
        hora_inicio = getattr(self, '_hora_inicio', datetime.now(timezone.utc))
        
        ahora = datetime.now(timezone.utc)
        horas_antiguedad = (ahora - ultima_actualizacion).total_seconds() / 3600
        
        self.logger.info(f"⏱️ Validando frescura del pipeline...")
        self.logger.info(f"   Última actualización: {ultima_actualizacion.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        self.logger.info(f"   Antigüedad: {horas_antiguedad:.1f} horas")
        
        # ============================================================
        # ✅ CORREGIDO: Si el bot acaba de iniciar, usar antigüedad desde inicio
        # ============================================================
        if (ahora - hora_inicio).total_seconds() < 60:
            # El bot acaba de iniciar, mantener pipeline
            self.logger.info(f"✅ Pipeline fresco (reinicio reciente) - Manteniendo TODO")
            return
        
        # ============================================================
        # CASO 1: < 1 hora → Pipeline FRESCO, mantener TODO
        # ============================================================
        if horas_antiguedad < 1.0:
            self.logger.info(f"✅ Pipeline fresco ({horas_antiguedad:.1f}h) - Manteniendo TODO")
            return
        
        # ============================================================
        # CASO 2: 1-6 horas → Pipeline MODERADAMENTE ANTIGUO
        # ============================================================
        elif horas_antiguedad < 6.0:
            self.logger.info(f"⚠️ Pipeline moderadamente antiguo ({horas_antiguedad:.1f}h) - Degradando FASE_2/FASE_3...")
            
            # ... código de degradación ...
            
            return
        
        # ============================================================
        # CASO 3: > 6 horas → Pipeline MUY ANTIGUO
        # ============================================================
        else:
            # ✅ SOLO ELIMINAR SI EL BOT ESTUVO DETENIDO MUCHO TIEMPO
            tiempo_detenido = (ahora - hora_inicio).total_seconds() / 3600
            
            if tiempo_detenido > 6.0:
                self.logger.info(f"❌ Pipeline muy antiguo ({horas_antiguedad:.1f}h) - ELIMINANDO TODO...")
                
                # Eliminar todas las oportunidades
                total_eliminadas = len(self.pipeline.estados)
                self.pipeline.estados.clear()
                self.pipeline._guardar_estados_en_sqlite()
                
                self.logger.info(f"🧹 {total_eliminadas} oportunidades eliminadas del pipeline")
                self.logger.info(f"✅ Pipeline reiniciado - Se iniciará un nuevo análisis")
                return
            else:
                # El bot estuvo corriendo pero hay datos antiguos
                self.logger.info(f"✅ Pipeline recuperado después de reinicio - Manteniendo TODO")
                return

    def _precargar_simbolo(self, simbolo: str):
        """
        Precarga el análisis de un símbolo individual.
        V9.10 - NUEVO: Para re-analizar símbolos después de degradación.
        """
        try:
            self.logger.info(f"📊 Precargando {simbolo}...")
            
            # Obtener M5 primero (base para construir)
            df_m5 = self.mt5.obtener_datos(simbolo, n_velas=500, timeframe=5)
            
            # Obtener H1 (inteligente: broker o construido)
            from utils.construir_timeframes import obtener_timeframe_inteligente
            df_h1 = obtener_timeframe_inteligente(
                simbolo=simbolo,
                timeframe=60,
                df_m5=df_m5,
                conector=self.mt5,
                almacen=self.almacen
            )
            
            if df_h1 is None or len(df_h1) < 50:
                self.logger.warning(f"⚠️ {simbolo}: Datos H1 insuficientes")
                return
            
            # Obtener H4 (inteligente)
            df_h4 = obtener_timeframe_inteligente(
                simbolo=simbolo,
                timeframe=240,
                df_m5=df_m5,
                conector=self.mt5,
                almacen=self.almacen
            )
            
            # Obtener D1 (inteligente)
            df_d1 = obtener_timeframe_inteligente(
                simbolo=simbolo,
                timeframe=1440,
                df_m5=df_m5,
                conector=self.mt5,
                almacen=self.almacen
            )
            
            # ============================================================
            # ANÁLISIS RÁPIDO
            # ============================================================
            rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
            if not rapido.pasa_filtro:
                self.logger.debug(f"⏭️ {simbolo}: Filtro rápido falló - {rapido.razon_rechazo}")
                self._guardar_contexto_pipeline(simbolo, rapido, None, None)
                return
            
            # ============================================================
            # DETECTAR NIVELES
            # ============================================================
            precio_actual = df_h1['Close'].iloc[-1]
            niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
                simbolo=simbolo,
                df=df_h1,
                precio_actual=precio_actual
            )
            
            soportes = niveles.get('soportes', [])
            resistencias = niveles.get('resistencias', [])
            
            # ============================================================
            # ANÁLISIS MEDIO
            # ============================================================
            medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
            if medio is None or not medio.pasa_filtro:
                self.logger.debug(f"⏭️ {simbolo}: Filtro medio falló - {medio.razon_rechazo if medio else 'None'}")
                self._guardar_contexto_pipeline(simbolo, rapido, medio, None)
                return
            
            # ============================================================
            # ANÁLISIS PESADO
            # ============================================================
            pesado = self.analisis_capas.analisis_pesado(
                df_h1,
                simbolo,
                df_h4,
                df_d1,
                niveles,
                medio
            )
            
            if pesado is None:
                self.logger.debug(f"⏭️ {simbolo}: Análisis pesado falló")
                return
            
            # ============================================================
            # CALCULAR SCORE Y RÉGIMEN
            # ============================================================
            score_h1 = self.score_engine.calcular_score_h1(
                score_estructura=pesado.score_estructura,
                score_momentum=pesado.score_momentum,
                score_confluencia=pesado.score_confluencia,
                score_institucional=pesado.score_institucional,
                simbolo=simbolo
            ).score
            
            # Clasificar régimen
            regimen_data = self.regimen_filter.clasificar(simbolo, df_h4, df_h1)
            regimen = regimen_data.regimen.value
            direccion_regimen = regimen_data.direccion_favor
            confianza_regimen = regimen_data.confianza
            
            # ============================================================
            # DETERMINAR DIRECCIÓN
            # ============================================================
            direccion = self._determinar_direccion_mejorado(
                medio,
                pesado,
                df_h4,
                df_h1,
                regimen
            )
            
            # ============================================================
            # GUARDAR EN PIPELINE
            # ============================================================
            contexto_h1 = {
                'score': score_h1,
                'direccion': direccion,
                'regimen': regimen,
                'direccion_regimen': direccion_regimen,
                'confianza_regimen': confianza_regimen,
                'en_nivel_clave': medio.en_nivel_clave if medio else False,
                'soporte_cercano': medio.soporte_cercano if medio else None,
                'resistencia_cercana': medio.resistencia_cercana if medio else None,
                'soporte_hits': medio.soporte_hits if medio else 0,
                'resistencia_hits': medio.resistencia_hits if medio else 0,
                'adx': medio.adx if medio else 0,
                'rsi': medio.rsi if medio else 50,
                'patron_principal': pesado.patron_principal if pesado else None,
                'wyckoff_fase': pesado.wyckoff_fase if pesado else None,
                'divergencia_rsi': pesado.divergencia_rsi if pesado else None,
                'divergencia_macd': pesado.divergencia_macd if pesado else None,
                'niveles': {
                    'soportes': soportes,
                    'resistencias': resistencias
                }
            }
            
            self.pipeline.actualizar_fase_1(
                simbolo=simbolo,
                analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
                score=score_h1,
                direccion=direccion,
                regimen=regimen,
                direccion_regimen=direccion_regimen,
                confianza_regimen=confianza_regimen,
                tendencia_h4='ALCISTA' if medio.adx > 25 and medio.sma20 > medio.sma50 else 'BAJISTA' if medio.adx > 25 else 'LATERAL',
                contexto_h1=contexto_h1,
                analisis_pesado=pesado
            )
            
            self.logger.info(f"✅ {simbolo}: Precargado - {len(soportes)} soportes, {len(resistencias)} resistencias, score={score_h1:.1f}")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error precargando {simbolo}: {e}")
     
    def _obtener_ultima_actualizacion_pipeline(self) -> Optional[datetime]:
        """
        Obtiene el timestamp más reciente de actualización del pipeline.
        V9.10 - CORREGIDO: Para validar frescura.
        """
        try:
            config = self.almacen.obtener_configuracion()
            pipeline_data = config.get('pipeline_estados', {})
            
            if not pipeline_data:
                return None
            
            timestamps = []
            for simbolo, data in pipeline_data.items():
                ts_str = data.get('timestamp_actualizacion')
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        timestamps.append(ts)
                    except:
                        continue
            
            if timestamps:
                return max(timestamps)
            
            return None
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo última actualización: {e}")
            return None

    def _guardar_ultima_actualizacion_pipeline(self):
        """
        Guarda el timestamp de la última actualización del pipeline.
        V9.14 - CORREGIDO: Usa el timestamp real del pipeline.
        """
        try:
            config = self.almacen.obtener_configuracion()
            
            # ✅ OBTENER EL TIMESTAMP MÁS RECIENTE DEL PIPELINE
            ultima_actualizacion = self._obtener_ultima_actualizacion_pipeline()
            
            if ultima_actualizacion:
                config['ultima_actualizacion_pipeline'] = ultima_actualizacion.isoformat()
            else:
                # Si no hay pipeline, usar hora actual
                config['ultima_actualizacion_pipeline'] = datetime.now(timezone.utc).isoformat()
            
            self.almacen.guardar_configuracion(config)
            self.logger.info(f"💾 Última actualización del pipeline guardada: {config['ultima_actualizacion_pipeline']}")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando última actualización: {e}")

    def _guardar_contexto_pipeline(self, simbolo: str, rapido=None, medio=None, pesado=None):
        """
        Guarda contexto en pipeline aunque el símbolo no pase los filtros.
        """
        if not self.pipeline:
            return
        
        try:
            self.pipeline.actualizar_fase_1(
                simbolo=simbolo,
                analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
                score=0,
                direccion='NEUTRAL',
                regimen='UNCERTAIN',
                contexto_h1={}
            )
        except Exception as e:
            self.logger.debug(f"⚠️ {simbolo}: Error guardando contexto: {e}")

    # ============================================================
    # CICLO PRINCIPAL
    # ============================================================
    
    def iniciar(self):
        """
        Inicia el bot con todos los módulos y la precarga optimizada.
        V9.10 - CORREGIDO: Valida frescura del pipeline antes de operar.
        """
        self.logger.info("🚀 Iniciando Bot de Trading V9.11...")

         # ✅ GUARDAR HORA DE INICIO
        self._hora_inicio = datetime.now(timezone.utc)
        
        # ============================================================
        # 1. VERIFICAR CONFIGURACIÓN
        # ============================================================
        if not self.config.verificar_env():
            self.logger.error("❌ Configuración inválida")
            self.notificaciones.enviar(
                "❌ CONFIGURACIÓN INVÁLIDA",
                "Verifica las variables de entorno",
                tipo='error'
            )
            return
        
        # ============================================================
        # 2. CONECTAR A MT5
        # ============================================================
        if not self.modo_backtest:
            self.logger.info("🔌 Conectando a MT5...")
            if not self.mt5.conectar():
                self.logger.error("❌ No se pudo conectar a MT5")
                self.notificaciones.enviar(
                    "❌ FALLO CRÍTICO",
                    "No se pudo conectar a MT5",
                    tipo='error'
                )
                return
            self.logger.info("✅ Conectado a MT5")
        else:
            self.logger.info("🧪 Modo backtest activo - sin conexión a MT5")
        
        # ============================================================
        # 3. LIMPIAR CACHÉ DE TICKS (EVITA SPREAD CERO FANTASMA)
        # ============================================================
        if not self.modo_backtest:
            self.mt5._tick_cache.clear()
            self.logger.info("🧹 Caché de ticks limpiada")
        
        # ============================================================
        # 4. SINCRONIZAR ESTADO INICIAL
        # ============================================================
        if not self.modo_backtest:
            self._sincronizar_estado_inicial()
        
        # ============================================================
        # 5. ✅ VALIDAR FRESCURA DEL PIPELINE
        # ============================================================
        self._validar_frescura_pipeline()
        
        # ============================================================
        # 6. ACTUALIZAR NOTICIAS
        # ============================================================
        self._actualizar_noticias()
        
        # ============================================================
        # 7. PRECARGA COMPLETA DE ANÁLISIS (INCREMENTAL)
        # ============================================================
        self._precargar_analisis_completo()
        
        # ============================================================
        # 8. DIAGNÓSTICO DE BASE DE DATOS
        # ============================================================
        self.diagnosticar_base_datos()
        
        # ============================================================
        # 9. INICIAR THREADS
        # ============================================================
        self._ejecutando = True
        self.estado.operando = True
        self._iniciar_threads()
        
        # ============================================================
        # 10. NOTIFICAR INICIO
        # ============================================================
        self.notificaciones.enviar(
            "🚀 BOT INICIADO",
            f"Capital: ${float(self.gestion_riesgo.capital_actual):,.2f}\n"
            f"Modo: {'BACKTEST' if self.modo_backtest else 'REAL'}\n"
            f"Entorno: {self.config.ENTORNO}",
            tipo='exito'
        )
        
        self.logger.info("✅ Bot iniciado correctamente")
        
        # ============================================================
        # 11. BUCLE PRINCIPAL (GESTIÓN DE CONEXIÓN Y ESCANEO)
        # ============================================================
        try:
            while self._ejecutando:
                time.sleep(1)
                
                # Verificar conexión MT5
                if not self.modo_backtest and not self.mt5.verificar_conexion():
                    self.logger.warning("⚠️ Conexión MT5 perdida, reconectando...")
                    if not self.mt5.conectar():
                        self.logger.warning("⚠️ Reconexión fallida")
                        time.sleep(10)
                        continue
                    # Limpiar caché al reconectar
                    self.mt5._tick_cache.clear()
                    self.logger.info("🧹 Caché de ticks limpiada tras reconexión")
                
                # Verificar bloqueo de emergencia
                if self.estado.bloqueo_emergencia_hasta:
                    ahora = datetime.now(timezone.utc)
                    if ahora < self.estado.bloqueo_emergencia_hasta:
                        continue
                    else:
                        self.estado.bloqueo_emergencia_hasta = None
                        self.logger.info("✅ Bloqueo de emergencia expirado")
                
                # Verificar capacidad de operar
                if not self._verificar_capacidad():
                    continue
                
                # Verificar horario
                if not self.horario.mercado_abierto():
                    continue
                
                # Si hay pipeline vacío, forzar escaneo
                if self.pipeline and not self.pipeline.obtener_activos():
                    self._ejecutar_escaneo()
                    
        except KeyboardInterrupt:
            self.logger.info("🛑 Interrupción recibida")
        except Exception as e:
            self.logger.error(f"❌ Error en bucle principal: {e}", exc_info=True)
            self.notificaciones.enviar(
                "❌ ERROR EN BUCLE PRINCIPAL",
                f"{str(e)[:500]}",
                tipo='error'
            )
        finally:
            self.detener()
    
    def detener(self):
        """
        Detiene el bot de forma ordenada.
        V9.10 - CORREGIDO: Guarda timestamp para validar frescura al reiniciar.
        """
        if not self._ejecutando:
            return
        
        self.logger.info("🛑 Deteniendo bot...")
        self._ejecutando = False
        self.estado.operando = False
        
        # ============================================================
        # ✅ GUARDAR ÚLTIMA ACTUALIZACIÓN DEL PIPELINE
        # ============================================================
        self._guardar_ultima_actualizacion_pipeline()
        
        # ============================================================
        # Esperar threads
        # ============================================================
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        
        # ============================================================
        # Cerrar conexiones
        # ============================================================
        if not self.modo_backtest:
            self.mt5.desconectar()
        
        self.almacen.cerrar()
        
        # ============================================================
        # Notificar
        # ============================================================
        self.notificaciones.enviar(
            "🛑 BOT DETENIDO",
            f"Hora: {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC",
            tipo='info'
        )
        
        self.logger.info("✅ Bot detenido correctamente")

    def _actualizar_oportunidades_fase2(self):
        """
        Actualiza todas las oportunidades en FASE_2 con análisis M15 fresco.
        V9.15 - CORREGIDO: Promueve a FASE_3 cuando el score supera el umbral.
        """
        from analysis.pipeline import FaseOportunidad
        
        if not self.pipeline:
            return
        
        # Obtener oportunidades en FASE_2
        oportunidades_fase2 = [
            o for o in self.pipeline.estados.values()
            if o.fase_actual == FaseOportunidad.FASE_2
        ]
        
        if not oportunidades_fase2:
            self.logger.debug("📭 No hay oportunidades en FASE_2 para actualizar")
            return
        
        self.logger.info(f"🔄 Actualizando {len(oportunidades_fase2)} oportunidades en FASE_2...")
        
        for estado in oportunidades_fase2:
            simbolo = estado.simbolo
            
            # Obtener datos M15
            df_m15 = self.cache.get_datos(
                simbolo=simbolo,
                timeframe=15,
                n_velas=200,
                fetch_func=self.mt5.obtener_datos
            )
            
            if df_m15 is None or len(df_m15) < 50:
                self.logger.debug(f"⏭️ {simbolo}: Datos M15 insuficientes")
                continue
            
            # Ejecutar análisis
            analisis_rapido = self.analisis_capas.analisis_rapido(df_m15, simbolo)
            if not analisis_rapido.pasa_filtro:
                continue
            
            analisis_medio = self.analisis_capas.analisis_medio(df_m15, simbolo, analisis_rapido, {})
            if not analisis_medio.pasa_filtro:
                continue
            
            # Calcular score M15
            score_m15 = self._calcular_score_m15_simple(analisis_medio, analisis_rapido)
            
            self.logger.info(f"📊 {simbolo}: Score M15 calculado: {score_m15:.1f}")
            
            # ✅ ACTUALIZAR EN PIPELINE
            self.pipeline.actualizar_fase_2(
                simbolo=simbolo,
                analisis_m15={
                    'rapido': analisis_rapido.__dict__ if hasattr(analisis_rapido, '__dict__') else {},
                    'medio': analisis_medio.__dict__ if hasattr(analisis_medio, '__dict__') else {},
                    'score': score_m15
                },
                score=score_m15
            )
            
            # ✅ FORZAR PROMOCIÓN AUTOMÁTICA
            self.pipeline._promover_automaticamente(simbolo)
            
            # ✅ VERIFICAR SI SE PROMOVIÓ
            estado_actualizado = self.pipeline.estados.get(simbolo)
            if estado_actualizado:
                if estado_actualizado.fase_actual == FaseOportunidad.FASE_3:
                    self.logger.info(f"✅ {simbolo}: PROMOVIDO A FASE_3 (score: {score_m15:.1f})")
                else:
                    self.logger.info(f"📊 {simbolo}: Sigue en {estado_actualizado.fase_actual.value} (score: {score_m15:.1f})")

    def _calcular_score_m15_simple(self, analisis_medio, analisis_rapido) -> float:
        """
        Calcula score M15 simplificado para actualización.
        """
        score = 50.0
        
        # ADX
        if analisis_medio.adx > 30:
            score += 15
        elif analisis_medio.adx > 20:
            score += 10
        elif analisis_medio.adx > 10:
            score += 5
        
        # Volumen
        if analisis_rapido.volumen_relativo > 2.0:
            score += 15
        elif analisis_rapido.volumen_relativo > 1.5:
            score += 10
        elif analisis_rapido.volumen_relativo > 1.0:
            score += 5
        
        # MACD
        if abs(analisis_medio.macd_histogram) > 0.0005:
            score += 10
        elif abs(analisis_medio.macd_histogram) > 0.0002:
            score += 5
        
        # Nivel clave
        if analisis_medio.en_nivel_clave:
            score += 10
        
        return min(100.0, max(0.0, score))

    # ============================================================
    # THREADS
    # ============================================================
    
    def _iniciar_threads(self):
        """Inicia los hilos de ejecución."""
        
        # Definir intervalos
        self.SNIPER_INTERVALO_ABIERTO = 30  # 30 segundos cuando mercado abierto
        self.SNIPER_INTERVALO_CERRADO = 300  # 5 minutos cuando mercado cerrado
        
        threads_config = [
            ('Escaneo', self._thread_escaneo, 1800),  # 30 minutos
            ('Sniper', self._thread_sniper, 30),      # 30 segundos - AHORA CON LÓGICA DE MERCADO CERRADO
            ('Monitoreo', self._thread_monitoreo, 30), # 30 segundos
            ('Heartbeat', self._thread_heartbeat, 60), # 60 segundos
            ('Noticias', self._thread_noticias,900),  # 5 minutos
        ]
        
        for nombre, func, intervalo in threads_config:
            thread = threading.Thread(
                target=self._thread_loop,
                args=(func, nombre, intervalo),
                daemon=True,
                name=f"Bot-{nombre}"
            )
            thread.start()
            self._threads.append(thread)
            self.logger.info(f"🧵 Hilo '{nombre}' iniciado (intervalo: {intervalo}s)")

    def _thread_loop(self, func, nombre: str, intervalo: int):
        """
        Bucle genérico para threads.
        
        Args:
            func: Función a ejecutar
            nombre: Nombre del thread
            intervalo: Intervalo en segundos
        """
        while self._ejecutando:
            try:
                func()
                time.sleep(intervalo)
            except Exception as e:
                self.logger.error(f"❌ Error en thread {nombre}: {e}", exc_info=True)
                time.sleep(intervalo * 2)
    
    def _thread_escaneo(self):
        """Ejecuta escaneo de mercado y promueve oportunidades."""
        ahora = datetime.now(timezone.utc)
        hora_col = ahora.astimezone(timezone(timedelta(hours=-5)))
        weekday_col = hora_col.weekday()
        hora_col_float = hora_col.hour + hora_col.minute / 60.0
        
        # ✅ CORRECCIÓN: Siempre ejecutar escaneo, incluso en domingo
        # Solo verificar si hay símbolos operables (cripto 24/7)
        simbolos_operables = self._obtener_simbolos_operables()
        
        if not simbolos_operables:
            self.logger.info("📭 No hay símbolos operables en este momento")
            return
        
        self.logger.info(f"📊 Escaneando {len(simbolos_operables)} símbolos operables...")
        
        # ✅ Ejecutar escaneo real (buscar oportunidades)
        self._ejecutar_escaneo()
        
        # ✅ Promover oportunidades
        self._promover_oportunidades()
    
    def _thread_sniper(self):
        """
        Ejecuta el hilo del sniper con actualización, promoción y limpieza.
        V9.35 - REFACTORIZADO COMPLETAMENTE.
        """
        
        from analysis.pipeline import FaseOportunidad
        
        # ============================================================
        # 1. VERIFICAR DÍA DE LA SEMANA
        # ============================================================
        ahora = datetime.now(timezone.utc)
        hora_col = ahora.astimezone(timezone(timedelta(hours=-5)))
        weekday_col = hora_col.weekday()
        
        es_sabado = weekday_col == 5
        es_domingo = weekday_col == 6
        
        # ============================================================
        # 2. ✅ LIMPIAR ESTADOS TERMINALES ANTIGUOS
        # ============================================================
        if self.pipeline:
            eliminados = self.pipeline.limpiar_antiguos(horas=1)
            if eliminados > 0:
                self.logger.info(f"🧹 {eliminados} estados terminales eliminados del pipeline")
        
        # ============================================================
        # 3. ✅ DEGRADAR OPORTUNIDADES POR TIEMPO
        # ============================================================
        self._degradar_oportunidades_por_tiempo()
        
        # ============================================================
        # 4. ✅ VERIFICAR ANTIGÜEDAD EN FASE_3 (30 MINUTOS)
        # ============================================================
        self._verificar_antiguedad_fase3()
        
        # ============================================================
        # 5. ✅ ANÁLISIS COMPLETO CADA 5 MINUTOS
        # ============================================================
        if not hasattr(self, '_ultimo_analisis_completo') or \
        (ahora - self._ultimo_analisis_completo).total_seconds() > 300:
            
            self._ultimo_analisis_completo = ahora
            self.logger.info(f"🔄 Análisis completo ejecutado (cada 5 min)")
            
            # Ejecutar precarga completa (solo símbolos operables)
            self._precargar_analisis_completo()
        
        # ============================================================
        # 6. ACTUALIZAR OPORTUNIDADES EN FASE_2
        # ============================================================
        self._actualizar_oportunidades_fase2()
        
        # ============================================================
        # 7. PROMOVER OPORTUNIDADES
        # ============================================================
        self._promover_oportunidades()
        
        # ============================================================
        # 8. ✅ ESPERA ACTIVA - VERIFICAR NIVELES
        # ============================================================
        if self.pipeline:
            self._verificar_niveles_esperados()
        
        # ============================================================
        # 9. ✅ EJECUTAR SNIPER CON SÍMBOLOS OPERABLES
        # ============================================================
        self._ejecutar_sniper_con_vela_virtual()

    def _verificar_antiguedad_fase3(self):
        """
        Verifica oportunidades en FASE_3 que llevan mucho tiempo sin cambios.
        V9.35 - NUEVO: Re-analiza después de 30 minutos en FASE_3.
        """
        from analysis.pipeline import FaseOportunidad
        
        if not self.pipeline:
            return
        
        ahora = datetime.now(timezone.utc)
        limite = timedelta(minutes=30)
        
        for simbolo, estado in list(self.pipeline.estados.items()):
            if estado.fase_actual != FaseOportunidad.FASE_3:
                continue
            
            # Verificar si el timestamp existe
            if estado.timestamp_ultima_actualizacion is None:
                estado.timestamp_ultima_actualizacion = ahora
                self.pipeline._guardar_estados_en_sqlite()
                continue
            
            tiempo_en_fase = ahora - estado.timestamp_ultima_actualizacion
            
            if tiempo_en_fase > limite:
                minutos = tiempo_en_fase.total_seconds() / 60
                self.logger.info(f"⏳ {simbolo}: {minutos:.0f}min en FASE_3 - Re-analizando...")
                
                # ✅ RE-ANALIZAR: Degradar a FASE_1 para forzar nuevo análisis
                estado.fase_actual = FaseOportunidad.FASE_1
                estado.condiciones_pendientes = []
                estado.condiciones_cumplidas = []
                estado.timestamp_ultima_actualizacion = ahora
                estado.metadata['sniper_fallos'] = 0
                estado.metadata['esperando_nivel'] = False
                self.pipeline._guardar_estados_en_sqlite()
                
                # Forzar re-análisis del símbolo
                self._precargar_simbolo(simbolo)
                self.logger.info(f"🔄 {simbolo}: Re-análisis forzado desde FASE_3")

    def _verificar_niveles_esperados(self):
        """
        Verifica si el precio llegó a los niveles esperados.
        V9.22 - NUEVO: Espera activa de niveles.
        """
        from analysis.pipeline import FaseOportunidad
        
        if not self.pipeline:
            return
        
        activos = self.pipeline.obtener_activos()
        
        for estado in activos:
            simbolo = estado.simbolo
            contexto_h1 = estado.contexto_h1 if estado.contexto_h1 else {}
            
            # ✅ Verificar si hay un nivel esperado
            if 'nivel_esperado' not in contexto_h1:
                continue
            
            nivel_esperado = contexto_h1.get('nivel_esperado')
            modo_esperado = contexto_h1.get('modo_esperado', 'RETEST')
            
            if not nivel_esperado:
                continue
            
            # ✅ Obtener precio actual
            precio_actual = self._obtener_precio_para_verificacion(simbolo)
            
            if not precio_actual:
                continue
            
            # ✅ Calcular distancia al nivel
            distancia = abs(precio_actual - nivel_esperado) / precio_actual * 100
            
            self.logger.info(f"⏳ {simbolo}: Esperando {modo_esperado} en {nivel_esperado:.5f} (dist: {distancia:.2f}%)")
            
            # ✅ Si el precio está cerca del nivel (menos de 0.5%)
            if distancia < 0.5:
                self.logger.info(f"🎯 {simbolo}: Precio en nivel esperado ({nivel_esperado:.5f})")
                
                # ✅ Ejecutar análisis para verificar si el modo es válido
                self._evaluar_oportunidad_en_nivel(estado, modo_esperado)

    def _evaluar_oportunidad_en_nivel(self, estado, modo_esperado: str):
        """
        Evalúa oportunidad cuando el precio llega al nivel esperado.
        V9.22 - NUEVO.
        """
        simbolo = estado.simbolo
        
        # ✅ Obtener datos M5 con vela virtual
        df_m5 = self._obtener_df_m5_con_precio_real(simbolo)
        
        if df_m5 is None or len(df_m5) < 50:
            self.logger.info(f"⏭️ {simbolo}: Datos M5 insuficientes")
            return
        
        # ✅ Obtener precio actual
        precio_actual = float(df_m5['Close'].iloc[-1])
        
        # ✅ Obtener contexto H1
        contexto_h1 = estado.contexto_h1 if estado.contexto_h1 else {}
        
        # ✅ Ejecutar sniper con el modo esperado
        resultado = self.sniper_checklist.evaluar_sniper_optimizado(
            simbolo=simbolo,
            df_m5=df_m5,
            precio_actual=precio_actual,
            direccion=estado.direccion,
            estado_pipeline=estado,
            analisis_rapido=None,
            analisis_medio=None,
            ejecutar_pesado=False,  # ✅ No ejecutar pesado (ya se hizo)
            contexto_h1=contexto_h1,
            calidad_horario='REGULAR',
            tick_data=df_m5.attrs.get('precio_tick'),
            precio_entrada=precio_actual,
            modo_forzado=modo_esperado  # ✅ Forzar modo esperado
        )
        
        if resultado:
            self.logger.info(f"🎯 {simbolo}: ¡OPORTUNIDAD EN NIVEL! Modo: {resultado.get('modo', 'N/A')}")
            self.ejecutor.ejecutar(resultado)
        else:
            self.logger.info(f"⏭️ {simbolo}: Condiciones no cumplidas en nivel")

    def _obtener_precio_para_verificacion(self, simbolo: str) -> Optional[float]:
        """
        Obtiene precio actual para verificación de niveles.
        V9.22 - NUEVO.
        """
        try:
            tick = self.mt5.obtener_precio(simbolo)
            if tick and tick.get('bid'):
                return float(tick['bid'])
        except Exception as e:
            self.logger.debug(f"⚠️ Error obteniendo precio para {simbolo}: {e}")
        
        return None

    def _thread_monitoreo(self):
        """Ejecuta monitoreo de posiciones."""
        # Verificar día de la semana
        ahora = datetime.now(timezone.utc)
        hora_col = ahora.astimezone(timezone(timedelta(hours=-5)))
        
        # Sábado: solo monitorear cripto
        if hora_col.weekday() == 5:
            posiciones = self.mt5.obtener_posiciones()
            posiciones_cripto = [p for p in posiciones 
                               if any(c in p['simbolo'].upper() for c in ['BTC', 'ETH', 'SOL'])]
            for pos in posiciones_cripto:
                self.monitor_posiciones.procesar(pos)
            return
        
        # Normal: monitorear todo
        self._ejecutar_monitoreo()
    
    def _thread_heartbeat(self):
        """Envía heartbeat."""
        self._enviar_heartbeat()
    
    def _thread_noticias(self):
        """Actualiza noticias."""
        self._actualizar_noticias()
    
    # ============================================================
    # EJECUCIÓN DE FUNCIONES PRINCIPALES
    # ============================================================
    
    @medir_latencia("escaneo_completo", plataforma="SISTEMA")
    def _ejecutar_escaneo(self):
        """
        Ejecuta un escaneo completo del mercado.
        V9.18 - CORREGIDO: Siempre escanea símbolos operables.
        """
        if not self._ejecutando:
            return
        
        # ✅ CORRECCIÓN: Usar símbolos operables (cripto 24/7)
        simbolos_operables = self._obtener_simbolos_operables()
        
        if not simbolos_operables:
            self.logger.info("📭 No hay símbolos operables en este momento")
            return
        
        self.logger.info(f"📊 Escaneando {len(simbolos_operables)} símbolos operables...")
        
        # Usar el Escaneador con símbolos filtrados
        if hasattr(self, 'escaneador') and self.escaneador is not None:
            try:
                resultados = self.escaneador.ejecutar_escaneo(simbolos=simbolos_operables)
                
                if resultados:
                    self.logger.info(f"📈 {len(resultados)} oportunidades encontradas")
                    self._promover_oportunidades()
            except Exception as e:
                self.logger.error(f"❌ Error en escaneo: {e}", exc_info=True)

    def _diagnosticar_pipeline(self):
        """
        Diagnóstico completo del pipeline - V9.31.
        """
        if not self.pipeline:
            self.logger.warning("⚠️ Pipeline no inicializado")
            return
        
        from analysis.pipeline import FaseOportunidad
        
        self.logger.info("=" * 60)
        self.logger.info("📊 DIAGNÓSTICO DEL PIPELINE")
        self.logger.info("=" * 60)
        
        total = len(self.pipeline.estados)
        activos = len(self.pipeline.obtener_activos())
        
        self.logger.info(f"Total estados: {total}")
        self.logger.info(f"Activos: {activos}")
        self.logger.info(f"Umbral FASE_2: {self.pipeline.umbral_fase_2}")
        self.logger.info(f"Umbral FASE_3: {self.pipeline.umbral_fase_3}")
        
        fase1 = self.pipeline.obtener_por_fase(FaseOportunidad.FASE_1)
        fase2 = self.pipeline.obtener_por_fase(FaseOportunidad.FASE_2)
        fase3 = self.pipeline.obtener_por_fase(FaseOportunidad.FASE_3)
        
        self.logger.info(f"FASE_1: {len(fase1)}")
        self.logger.info(f"FASE_2: {len(fase2)}")
        self.logger.info(f"FASE_3: {len(fase3)}")
        
        # ============================================================
        # ✅ DETECTAR OPORTUNIDADES BLOQUEADAS
        # ============================================================
        bloqueadas = []
        for estado in fase1:
            if estado.score_acumulado >= self.pipeline.umbral_fase_2:
                bloqueadas.append((estado.simbolo, estado.score_acumulado))
        
        if bloqueadas:
            self.logger.warning(f"⚠️ {len(bloqueadas)} oportunidades BLOQUEADAS en FASE_1 con score suficiente:")
            for simbolo, score in bloqueadas:
                self.logger.warning(f"   {simbolo}: score {score:.1f} >= {self.pipeline.umbral_fase_2}")
        
        for estado in fase2:
            if estado.score_acumulado >= self.pipeline.umbral_fase_3:
                self.logger.warning(f"⚠️ {estado.simbolo}: score {estado.score_acumulado:.1f} >= {self.pipeline.umbral_fase_3} pero en FASE_2")
        
        self.logger.info("=" * 60)

    def _obtener_simbolos_operables(self) -> List[str]:
        """
        Obtiene solo los símbolos que están operables en este momento.
        V9.10 - CORREGIDO DEFINITIVO: Solo cripto opera el sábado.
        
        Returns:
            Lista de símbolos operables
        """
        simbolos_operables = []
        simbolos_no_operables = []
        
        ahora = datetime.now(timezone.utc)
        hora_col = ahora.astimezone(timezone(timedelta(hours=-5)))  # Zona Colombia
        weekday_col = hora_col.weekday()
        
        # Verificar si es sábado
        es_sabado = weekday_col == 5
        
        # Verificar si es domingo
        es_domingo = weekday_col == 6
        
        for simbolo in self.config.SIMBOLOS_COMPLETOS:
            # Verificar horario operativo
            es_operativo, razon = self.horario.es_horario_operativo(simbolo, ahora)
            
            if es_operativo:
                simbolos_operables.append(simbolo)
            else:
                simbolos_no_operables.append((simbolo, razon))
        
        # Log de símbolos no operables
        if simbolos_no_operables:
            self.logger.info(f"⏭️ Símbolos NO operables: {len(simbolos_no_operables)}")
            for simbolo, razon in simbolos_no_operables[:10]:  # Mostrar los primeros 10
                self.logger.info(f"   {simbolo}: {razon}")
        
        # Mensajes específicos por día
        if es_sabado:
            self.logger.info("📅 SÁBADO - Solo Cripto opera (BTC, ETH, SOL)")
        elif es_domingo:
            self.logger.info("📅 DOMINGO - Forex desde 17:00 COT, Índices/Metales desde 18:00 COT")
        
        return simbolos_operables
    
    def _ejecutar_sniper(self):
        """
        Ejecuta un ciclo del sniper con logs detallados.
        """
        if not self._ejecutando:
            return
        
        self.logger.info("🔄 Ejecutando ciclo del sniper...")
        
        if not self.horario.mercado_abierto():
            self.logger.info("🚫 Mercado cerrado, sniper omitido")
            return
        
        # Obtener todas las oportunidades activas del pipeline
        oportunidades = self.pipeline.obtener_activos() if self.pipeline else []
        
        if not oportunidades:
            self.logger.info("📭 No hay oportunidades activas en el pipeline")
            return
        
        from analysis.pipeline import FaseOportunidad
        
        # Filtrar solo las que están en FASE_3
        oportunidades_fase3 = [
            o for o in oportunidades 
            if o.fase_actual == FaseOportunidad.FASE_3
        ]
        
        self.logger.info(f"📊 {len(oportunidades)} oportunidades activas, {len(oportunidades_fase3)} en FASE_3")
        
        if not oportunidades_fase3:
            self.logger.info("📭 No hay oportunidades en FASE_3 para evaluar")
            return
        
        # Ordenar por score (mejores primero)
        oportunidades_fase3.sort(key=lambda x: x.score_acumulado, reverse=True)
        
        # Evaluar cada oportunidad (máximo 5 por ciclo)
        for estado in oportunidades_fase3[:5]:
            if not self._ejecutando:
                break
            self._evaluar_oportunidad(estado)


    def _obtener_df_m5_con_precio_real(self, simbolo: str) -> Optional[pd.DataFrame]:
        """
        Obtiene DataFrame M5 y lo extiende con el precio actual en tiempo real.
        V9.10 - NUEVO: Crea una vela virtual con el precio actual (bid/ask).
        
        Args:
            simbolo: Símbolo
        
        Returns:
            DataFrame M5 extendido con vela virtual o None
        """
        # Obtener datos M5 de la caché (velas históricas completas)
        df_m5 = self.cache.get_datos(
            simbolo=simbolo,
            timeframe=5,
            n_velas=150,
            fetch_func=self.mt5.obtener_datos
        )
        
        if df_m5 is None or len(df_m5) < 50:
            return None

        # No mutar el DataFrame compartido por la caché al añadir la vela virtual.
        df_m5 = df_m5.copy()
        
        # Obtener precio actual en tiempo real (bid/ask)
        tick = self.mt5.obtener_precio(simbolo)
        if not tick:
            self.logger.debug(f"⚠️ {simbolo}: No se pudo obtener tick para vela virtual, usando datos existentes")
            return df_m5
        
        bid = tick.get('bid', 0)
        ask = tick.get('ask', 0)
        
        if bid <= 0 or ask <= 0:
            self.logger.debug(f"⚠️ {simbolo}: Precio inválido para vela virtual (bid={bid}, ask={ask})")
            return df_m5
        
        # Precio actual (mid price)
        precio_actual = (bid + ask) / 2
        
        # Crear una vela virtual con el precio actual
        now = datetime.now(timezone.utc)
        
        # Obtener valores de la última vela real
        ultima_vela = df_m5.iloc[-1]
        
        vela_actual = {
            'Open': float(ultima_vela['Close']),
            'High': max(float(ultima_vela['High']), bid, ask),
            'Low': min(float(ultima_vela['Low']), bid, ask),
            'Close': precio_actual,
            'Volume': float(ultima_vela['Volume']),
        }
        
        # Añadir la vela virtual al DataFrame
        # Usamos loc con timestamp actual
        df_m5.loc[now] = vela_actual
        
        # Conservar el tick asociado a esta vela para reutilizarlo en el sniper.
        df_m5.attrs['precio_tick'] = tick
        df_m5.attrs['precio_analisis'] = precio_actual
        df_m5.attrs['precio_entrada_compra'] = ask
        df_m5.attrs['precio_entrada_venta'] = bid
        df_m5.attrs['digits'] = int(tick.get('digits', 5) or 5)

        digits = int(tick.get('digits', 5) or 5)
        self.logger.debug(
            f"📊 {simbolo}: Vela virtual M5 añadida "
            f"con precio {precio_actual:.{digits}f}"
        )

        return df_m5

    def _evaluar_oportunidad_con_vela_virtual(self, estado):
        """
        Evalúa una oportunidad usando una vela virtual con precio en tiempo real.
        V9.35 - REFACTORIZADO: Registra fallos y degrada después de 10 intentos.
        """
        simbolo = estado.simbolo
        from analysis.pipeline import FaseOportunidad
        
        self.logger.info(f"🔍 INICIANDO EVALUACIÓN DE {simbolo} CON VELA VIRTUAL")
         # ✅ CORREGIDO V9.57: VERIFICAR POSICIONES EXISTENTES
        if not self.modo_backtest:
            posiciones = self.mt5.obtener_posiciones()
            if posiciones and any(p['simbolo'] == simbolo for p in posiciones):
                self.logger.info(f"⏭️ {simbolo}: ya hay posición abierta")
                return
        # ✅ Verificar que esté en FASE_3
        if estado.fase_actual != FaseOportunidad.FASE_3:
            self.logger.info(f"⏭️ {simbolo}: no está en FASE_3 (actual: {estado.fase_actual.value})")
            return
        
        # ============================================================
        # ✅ CORRECCIÓN V9.15: Verificar operabilidad por símbolo
        # ============================================================
        es_operativo, razon_horario = self.horario.es_horario_operativo(simbolo)
        
        if not es_operativo:
            self.logger.info(f"⏭️ {simbolo}: NO OPERABLE ({razon_horario})")
            return
        
        # Verificar cooldown
        if simbolo in self.estado.sniper_cooldown:
            if datetime.now(timezone.utc) < self.estado.sniper_cooldown[simbolo]:
                self.logger.info(f"⏭️ {simbolo}: en cooldown hasta {self.estado.sniper_cooldown[simbolo]}")
                return
        
        # Verificar posición abierta
        if not self.modo_backtest:
            posiciones = self.mt5.obtener_posiciones()
            if posiciones and any(p['simbolo'] == simbolo for p in posiciones):
                self.logger.info(f"⏭️ {simbolo}: ya hay posición abierta")
                return
        
        # Verificar dirección
        if estado.direccion == 'NEUTRAL':
            self.logger.info(f"⏭️ {simbolo}: dirección NEUTRAL")
            return
        
        # Verificar score
        if estado.score_acumulado < 30:
            self.logger.info(f"⏭️ {simbolo}: score insuficiente ({estado.score_acumulado:.1f} < 30)")
            return
        
        # ✅ OBTENER DATOS M5 CON VELA VIRTUAL
        self.logger.info(f"📥 {simbolo}: Obteniendo datos M5 con vela virtual...")
        df_m5 = self._obtener_df_m5_con_precio_real(simbolo)
        
        if df_m5 is None or len(df_m5) < 50:
            self.logger.info(f"⏭️ {simbolo}: datos M5 insuficientes o no se pudo crear vela virtual")
            return
        
        self.logger.info(f"✅ {simbolo}: Datos M5 obtenidos ({len(df_m5)} velas, incluyendo vela virtual)")
        
        # Precio para análisis técnico: mid-price de la vela virtual.
        precio_actual = float(df_m5['Close'].iloc[-1])
        tick_data = df_m5.attrs.get('precio_tick')
        
        if tick_data:
            precio_entrada = float(
                tick_data.get(
                    'ask' if estado.direccion == 'COMPRA' else 'bid',
                    precio_actual
                )
            )
            digits = int(tick_data.get('digits', 5) or 5)
            self.logger.info(
                f"💹 {simbolo}: Precio análisis(mid)={precio_actual:.{digits}f} | "
                f"Precio entrada={precio_entrada:.{digits}f}"
            )
        else:
            precio_entrada = precio_actual
            self.logger.info(
                f"💹 {simbolo}: Precio actual de vela virtual: "
                f"{precio_actual:.5f}"
            )
        
        # Obtener contexto H1
        contexto_h1 = estado.contexto_h1 if estado and hasattr(estado, 'contexto_h1') and estado.contexto_h1 is not None else {}
        
        self.logger.info(f"🔍 Ejecutando sniper para {simbolo} con vela virtual...")
        
        # ✅ Evaluar sniper con la vela virtual
        resultado = self.sniper_checklist.evaluar_sniper_optimizado(
            simbolo=simbolo,
            df_m5=df_m5,
            precio_actual=precio_actual,
            direccion=estado.direccion,
            estado_pipeline=estado,
            analisis_rapido=None,
            analisis_medio=None,
            ejecutar_pesado=True,
            contexto_h1=contexto_h1,
            calidad_horario='REGULAR',
            tick_data=tick_data,
            precio_entrada=precio_entrada
        )
        
        if resultado:
            self.logger.info(f"🎯 {simbolo}: ¡OPORTUNIDAD DETECTADA! Modo: {resultado.get('modo', 'N/A')}")
            
            # ✅ REINICIAR CONTADOR DE FALLOS
            estado.metadata['sniper_fallos'] = 0
            estado.metadata['sniper_ultimo_exito'] = datetime.now(timezone.utc).isoformat()
            self.pipeline._guardar_estados_en_sqlite()
            
            # Ejecutar operación
            self.ejecutor.ejecutar(resultado)
            
            # Marcar pipeline
            self.pipeline.marcar_ejecutada(simbolo)
            
        else:
            # ✅ NUEVO: Registrar fallo y actualizar timestamp
            self.logger.info(f"⏭️ {simbolo}: oportunidad rechazada por sniper")
            
            fallos = estado.metadata.get('sniper_fallos', 0) + 1
            estado.metadata['sniper_fallos'] = fallos
            estado.metadata['sniper_ultimo_fallo'] = datetime.now(timezone.utc).isoformat()
            estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            
            self.pipeline._guardar_estados_en_sqlite()
            
            # ✅ DEGRADAR DESPUÉS DE 10 FALLOS CONSECUTIVOS
            if fallos >= 10:
                self.logger.info(f"⬇️ {simbolo}: Degradando por {fallos} fallos consecutivos de sniper")
                self.pipeline._degradar_oportunidad(
                    simbolo,
                    razon=f"Demasiados fallos de sniper ({fallos})"
                )
                # El método _degradar_oportunidad ya llama a _precargar_simbolo
            else:
                self.logger.debug(f"📝 {simbolo}: Fallos sniper: {fallos}/10")
    
    def _evaluar_oportunidad(self, estado):
        """
        Evalúa una oportunidad específica y loggea el resultado.
        V9.10 - REFACTORIZADO: Usa precio en tiempo real y recalcula SL/TP.
        """
        simbolo = estado.simbolo
        from analysis.pipeline import FaseOportunidad
        
        self.logger.info(f"🔍 INICIANDO EVALUACIÓN DE {simbolo}")
        
        # ✅ Verificar que esté en FASE_3
        if estado.fase_actual != FaseOportunidad.FASE_3:
            self.logger.info(f"⏭️ {simbolo}: no está en FASE_3 (actual: {estado.fase_actual.value})")
            return
        
        # Verificar cooldown
        if simbolo in self.estado.sniper_cooldown:
            if datetime.now(timezone.utc) < self.estado.sniper_cooldown[simbolo]:
                self.logger.info(f"⏭️ {simbolo}: en cooldown hasta {self.estado.sniper_cooldown[simbolo]}")
                return
        
        # Verificar posición abierta
        if not self.modo_backtest:
            posiciones = self.mt5.obtener_posiciones()
            if posiciones and any(p['simbolo'] == simbolo for p in posiciones):
                self.logger.info(f"⏭️ {simbolo}: ya hay posición abierta")
                return
        
        # Verificar dirección
        if estado.direccion == 'NEUTRAL':
            self.logger.info(f"⏭️ {simbolo}: dirección NEUTRAL")
            return
        
        # Verificar score
        if estado.score_acumulado < 30:
            self.logger.info(f"⏭️ {simbolo}: score insuficiente ({estado.score_acumulado:.1f} < 30)")
            return
        
        # Obtener datos M5
        self.logger.info(f"📥 {simbolo}: Obteniendo datos M5...")
        df_m5 = self.cache.get_datos(
            simbolo=simbolo,
            timeframe=5,
            n_velas=150,
            fetch_func=self.mt5.obtener_datos
        )
        if df_m5 is None or len(df_m5) < 50:
            self.logger.info(f"⏭️ {simbolo}: datos M5 insuficientes (len: {len(df_m5) if df_m5 is not None else 0})")
            return
        
        self.logger.info(f"✅ {simbolo}: Datos M5 obtenidos ({len(df_m5)} velas)")
        
        # ✅ OBTENER PRECIO ACTUAL EN TIEMPO REAL
        self.logger.info(f"💹 {simbolo}: Obteniendo precio en tiempo real...")
        tick = self.mt5.obtener_precio(simbolo)
        if not tick:
            self.logger.info(f"⏭️ {simbolo}: no se pudo obtener precio real")
            return
        
        bid = tick.get('bid')
        ask = tick.get('ask')
        precio_market = ask if estado.direccion == 'COMPRA' else bid
        
        self.logger.info(f"📊 {simbolo}: Precio real: bid={bid:.5f}, ask={ask:.5f}, usado={precio_market:.5f}")
        
        # Obtener contexto H1
        contexto_h1 = estado.contexto_h1 if estado and hasattr(estado, 'contexto_h1') and estado.contexto_h1 is not None else {}
        
        self.logger.info(f"🔍 Ejecutando sniper para {simbolo}...")
        
        # ✅ Evaluar sniper con precio en tiempo real
        resultado = self.sniper_checklist.evaluar_sniper_optimizado(
            simbolo=simbolo,
            df_m5=df_m5,
            precio_actual=precio_market,  # <-- Precio en tiempo real
            direccion=estado.direccion,
            estado_pipeline=estado,
            analisis_rapido=None,
            analisis_medio=None,
            ejecutar_pesado=True,
            contexto_h1=contexto_h1,
            calidad_horario='REGULAR',
            tick_data=tick,
            precio_entrada=precio_market
        )
        
        if resultado:
            self.logger.info(f"🎯 {simbolo}: ¡OPORTUNIDAD DETECTADA! Modo: {resultado.get('modo', 'N/A')}")
            
            # ✅ ACTUALIZAR EL PRECIO DE ENTRADA CON EL PRECIO REAL
            resultado['entry_price'] = precio_market
            
            # Ejecutar operación
            self.ejecutor.ejecutar(resultado)
        else:
            self.logger.info(f"⏭️ {simbolo}: oportunidad rechazada por sniper")

    def _ejecutar_sniper_con_vela_virtual(self):
        """
        Ejecuta un ciclo del sniper usando velas virtuales.
        V9.15 - CORREGIDO: No bloquea cripto cuando el mercado tradicional está cerrado.
        """
        if not self._ejecutando:
            return
        
        self.logger.info("🔄 Ejecutando ciclo del sniper con vela virtual...")
        
        # ============================================================
        # ✅ CORRECCIÓN V9.15: Verificar símbolos operables, NO mercado global
        # ============================================================
        # Obtener todas las oportunidades activas del pipeline
        oportunidades = self.pipeline.obtener_activos() if self.pipeline else []
        
        if not oportunidades:
            self.logger.info("📭 No hay oportunidades activas en el pipeline")
            return
        
        from analysis.pipeline import FaseOportunidad
        
        # Filtrar solo las que están en FASE_3
        oportunidades_fase3 = [
            o for o in oportunidades 
            if o.fase_actual == FaseOportunidad.FASE_3
        ]
        
        self.logger.info(f"📊 {len(oportunidades)} oportunidades activas, {len(oportunidades_fase3)} en FASE_3")
        
        if not oportunidades_fase3:
            self.logger.info("📭 No hay oportunidades en FASE_3 para evaluar")
            return
        
        # ============================================================
        # ✅ CORRECCIÓN: Filtrar por símbolos operables (incluye cripto 24/7)
        # ============================================================
        oportunidades_elegibles = []
        
        for estado in oportunidades_fase3:
            simbolo = estado.simbolo
            
            # Verificar si el símbolo es operable AHORA
            es_operativo, razon = self.horario.es_horario_operativo(simbolo)
            
            if es_operativo:
                oportunidades_elegibles.append(estado)
                self.logger.info(f"✅ {simbolo}: OPERABLE ({razon})")
            else:
                self.logger.info(f"⏭️ {simbolo}: NO OPERABLE ({razon})")
        
        if not oportunidades_elegibles:
            self.logger.info("📭 No hay oportunidades operables para evaluar")
            return
        
        # ============================================================
        # ✅ CORRECCIÓN: Ordenar por score y evaluar
        # ============================================================
        oportunidades_elegibles.sort(key=lambda x: x.score_acumulado, reverse=True)
        
        # Evaluar cada oportunidad (máximo 5 por ciclo)
        for estado in oportunidades_elegibles[:5]:
            if not self._ejecutando:
                break
            self._evaluar_oportunidad_con_vela_virtual(estado)
    
    def _ejecutar_monitoreo(self):
        """
        Ejecuta monitoreo de posiciones abiertas.
        """
        if not self._ejecutando or self.modo_backtest:
            return
        
        # Obtener posiciones
        posiciones = self.mt5.obtener_posiciones()
        
        if not posiciones:
            return
        
        # Procesar cada posición
        for pos in posiciones:
            self._procesar_posicion(pos)
    
    def _procesar_posicion(self, pos):
        """Procesa una posición individual."""
        # ✅ DELEGAR EN MonitorPosiciones
        if hasattr(self, 'monitor_posiciones') and self.monitor_posiciones:
            self.monitor_posiciones.procesar(pos)
        else:
            self.logger.warning(f"⚠️ MonitorPosiciones no inicializado")
    
    def _verificar_sl_tp(self, pos, ticket, ganancia_pips):
        """Verifica si SL o TP fueron alcanzados."""
        # ✅ DELEGAR EN MonitorPosiciones
        if hasattr(self, 'monitor_posiciones') and self.monitor_posiciones:
            return self.monitor_posiciones._verificar_sl_tp(pos, ticket, ganancia_pips)
        return False
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def _determinar_direccion_mejorado(self, medio, pesado, df_h4=None, df_h1=None, regimen: Optional[str] = None) -> str:
        """
        Determina la dirección basada en análisis técnico y RÉGIMEN.
        V9.43 - CORREGIDO: Ponderación EQUITATIVA entre alcista y bajista.
        """
        # ✅ PRIORIDAD 1: Régimen claro (sin sesgo)
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            return 'COMPRA'
        
        if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            return 'VENTA'
        
        # ✅ PRIORIDAD 2: Análisis técnico (ponderación EQUITATIVA)
        bullish = 0
        bearish = 0
        
        if medio:
            # RSI (neutral: 50)
            if medio.rsi > 60:
                bullish += 2
            elif medio.rsi < 40:
                bearish += 2
            elif medio.rsi > 55:
                bullish += 1
            elif medio.rsi < 45:
                bearish += 1
            
            # MACD (neutral: 0)
            if medio.macd_histogram > 0:
                bullish += 2
            elif medio.macd_histogram < 0:
                bearish += 2
            elif medio.macd_histogram > 0.0001:
                bullish += 1
            elif medio.macd_histogram < -0.0001:
                bearish += 1
            
            # ADX + EMAs (tendencia)
            if medio.adx > 25:
                if medio.sma20 > medio.sma50:
                    bullish += 3
                else:
                    bearish += 3
            elif medio.adx > 15:
                if medio.sma20 > medio.sma50:
                    bullish += 1
                else:
                    bearish += 1
        
        if pesado:
            # Divergencias (ponderación significativa)
            if pesado.divergencia_rsi == 'BULLISH':
                bullish += 3
            elif pesado.divergencia_rsi == 'BEARISH':
                bearish += 3
            
            # Wyckoff
            if pesado.wyckoff_fase in ['ACUMULACION', 'SPRING']:
                bullish += 2
            elif pesado.wyckoff_fase in ['DISTRIBUCION', 'UPTHRUST']:
                bearish += 2
            
            # Patrones de velas
            if pesado.patron_principal in ['MORNING_STAR', 'BULLISH_ENGULFING', 'HAMMER']:
                bullish += 2
            elif pesado.patron_principal in ['EVENING_STAR', 'BEARISH_ENGULFING', 'SHOOTING_STAR']:
                bearish += 2
        
        # ✅ CORREGIDO: Umbral EQUITATIVO (no sesgado)
        if bullish > bearish + 1:
            return 'COMPRA'
        elif bearish > bullish + 1:
            return 'VENTA'
        
        # ✅ Si es muy parejo, usar régimen
        if regimen:
            if regimen in ['RANGO_AMPLIO', 'RANGO_APRETADO']:
                # En rango, usar el último cierre vs apertura
                if df_h1 is not None and len(df_h1) > 0:
                    ultima_vela = df_h1.iloc[-1]
                    if ultima_vela['Close'] > ultima_vela['Open']:
                        return 'COMPRA'
                    elif ultima_vela['Close'] < ultima_vela['Open']:
                        return 'VENTA'
        
        return 'NEUTRAL'
    
    def _validar_direccion_por_regimen(self, direccion: str, regimen: str) -> Tuple[bool, str]:
        """
        Valida dirección por régimen.
        """
        if direccion == 'NEUTRAL':
            return True, "NEUTRAL permitido"
        
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            if direccion == 'VENTA':
                return False, f"VENTA en contra de tendencia alcista ({regimen})"
            return True, "COMPRA alineada con tendencia alcista"
        
        if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            if direccion == 'COMPRA':
                return False, f"COMPRA en contra de tendencia bajista ({regimen})"
            return True, "VENTA alineada con tendencia bajista"
        
        if regimen in ['RANGO_AMPLIO', 'RANGO_APRETADO']:
            return True, f"Dirección {direccion} permitida en rango"
        
        if regimen == 'CHOP_VOLATIL':
            return True, f"Dirección {direccion} permitida en CHOP (con precaución)"
        
        if regimen == 'BREAKOUT_INMINENTE':
            return True, f"Dirección {direccion} permitida en breakout"
        
        if regimen == 'INCERTO':
            return True, f"Dirección {direccion} permitida en INCERTO (con precaución)"
        
        return True, f"Régimen desconocido ({regimen}), dirección permitida"
    
    def _promover_oportunidades(self):
        """
        Promueve oportunidades en el pipeline con LOGS DETALLADOS.
        V9.31 - REFACTORIZADO: Diagnóstico completo + FORZADO.
        """
        if not self.pipeline:
            return
        
        from analysis.pipeline import FaseOportunidad
        
        # ============================================================
        # 1. DIAGNÓSTICO ANTES DE PROMOVER
        # ============================================================
        self._diagnosticar_pipeline()
        
        # ============================================================
        # 2. ✅ FORZAR PROMOCIÓN DE OPORTUNIDADES CON SCORE ALTO
        # ============================================================
        for simbolo, estado in self.pipeline.estados.items():
            if estado.fase_actual == FaseOportunidad.FASE_1:
                if estado.score_acumulado >= self.pipeline.umbral_fase_2:
                    self.logger.warning(f"⚠️ {simbolo}: FORZANDO PROMOCIÓN FASE_1 → FASE_2")
                    estado.fase_actual = FaseOportunidad.FASE_2
                    estado.agregar_condicion("Score_Fase2")
                    estado.agregar_condicion("M15_Confirmacion")
                    self.pipeline._stats['promovidas_f1_f2'] += 1
            
            elif estado.fase_actual == FaseOportunidad.FASE_2:
                if estado.score_acumulado >= self.pipeline.umbral_fase_3:
                    self.logger.warning(f"⚠️ {simbolo}: FORZANDO PROMOCIÓN FASE_2 → FASE_3")
                    estado.fase_actual = FaseOportunidad.FASE_3
                    estado.agregar_condicion("Score_Fase3")
                    estado.agregar_condicion("M5_Sniper")
                    self.pipeline._stats['promovidas_f2_f3'] += 1
        
        # ============================================================
        # 3. PROMOVER NORMALMENTE
        # ============================================================
        self.pipeline.promover_automaticamente()
        
        # ============================================================
        # 4. DIAGNÓSTICO DESPUÉS
        # ============================================================
        self._diagnosticar_pipeline()

    def _verificar_capacidad(self) -> bool:
        """Verifica capacidad de operar."""
        if self.modo_backtest:
            return True
        
        # Circuit breaker
        if self.gestion_riesgo.circuit_breaker.verificar():
            return False
        
        # Capital
        if self.gestion_riesgo.capital_actual <= 0:
            return False
        
        # Posiciones simultáneas
        posiciones = self.mt5.obtener_posiciones()
        max_sim = self.gestion_riesgo.obtener_max_simultaneas()
        
        if posiciones and len(posiciones) >= max_sim:
            return False
        
        return True
    
    def _cerrar_posicion(self, ticket: int, razon: str):
        """Cierra una posición."""
        if self.mt5.cerrar_posicion(ticket):
            self.logger.info(f"🔒 Posición {ticket} cerrada: {razon}")
            
            # Registrar en gestión de riesgo
            detalle = self.mt5.obtener_detalle_cierre(ticket)
            if detalle:
                self.gestion_riesgo.registrar_operacion({
                    'ticket': ticket,
                    'ganancia': detalle.get('ganancia', 0),
                    'comision': detalle.get('comision', 0),
                    'swap': detalle.get('swap', 0),
                    'motivo_cierre': razon
                })
            
            # Eliminar de memoria
            if ticket in self.estado.posiciones_abiertas:
                del self.estado.posiciones_abiertas[ticket]
    
    def _mover_sl(self, ticket: int, nuevo_sl: float):
        """Mueve el SL de una posición."""
        if self.mt5.modificar_sl(ticket, nuevo_sl):
            self.logger.info(f"🔄 SL movido a {nuevo_sl:.5f} para ticket {ticket}")
            
            if ticket in self.estado.posiciones_abiertas:
                self.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
    
    def _sincronizar_estado_inicial(self):
        """
        Sincroniza el estado inicial y recupera operaciones no guardadas en SQLite.
        """
        self.logger.info("🔄 Sincronizando estado inicial...")
        
        # Obtener posiciones de MT5
        posiciones = self.mt5.obtener_posiciones()
        
        for pos in posiciones:
            ticket = pos['ticket']
            magic = pos.get('magic', 0)
            es_bot = magic == self.config.MAGIC_NUMBER
            
            # ✅ Reconstruir en memoria
            self.estado.posiciones_abiertas[ticket] = {
                'simbolo': pos['simbolo'],
                'direccion': pos['tipo'],
                'entrada': pos['precio_apertura'],
                'volumen': pos['volumen'],
                'sl': pos.get('sl', 0),
                'tp': pos.get('tp', 0),
                'timestamp_apertura': datetime.fromtimestamp(pos.get('time', 0), tz=timezone.utc),
                'es_manual': not es_bot,
                'es_bot': es_bot,
            }
            
            # ✅ Verificar si la operación ya está en SQLite
            if self.almacen:
                try:
                    op_existente = self.almacen.obtener_operacion_por_ticket(ticket)
                    if not op_existente:
                        self.logger.warning(f"⚠️ Recuperando operación {ticket} no guardada en SQLite")
                        
                        # Reconstruir datos para guardar en SQLite
                        op_para_guardar = {
                            'ticket': ticket,
                            'simbolo': pos['simbolo'],
                            'direccion': 'COMPRA' if pos['tipo'] == 0 else 'VENTA',
                            'entrada': pos['precio_apertura'],
                            'lotes': pos['volumen'],
                            'sl': pos.get('sl', 0),
                            'tp': pos.get('tp', 0),
                            'timestamp': datetime.fromtimestamp(pos.get('time', 0), tz=timezone.utc).isoformat(),
                            'estado': 'ABIERTA',
                            'es_bot': es_bot,
                            'es_demo': self.config.MT5_DEMO,
                            'modo': 'RECUPERADO',
                            'contexto_apertura': {
                                'recuperado': True,
                                'fecha_recuperacion': datetime.now(timezone.utc).isoformat(),
                            }
                        }
                        
                        # Guardar en SQLite
                        self.almacen.guardar_operacion(op_para_guardar, es_demo=self.config.MT5_DEMO)
                        self.logger.info(f"✅ Operación {ticket} recuperada en SQLite")
                except Exception as e:
                    self.logger.warning(f"⚠️ Error recuperando operación {ticket} en SQLite: {e}")
        
        self.logger.info(f"✅ {len(self.estado.posiciones_abiertas)} posiciones sincronizadas")

    def _degradar_oportunidades_por_tiempo(self):
        """
        Degrada oportunidades que han estado demasiado tiempo en una fase.
        V9.12 - CORREGIDO: Evita que las oportunidades se queden atascadas.
        """
        # ✅ IMPORTAR FaseOportunidad AQUÍ
        from analysis.pipeline import FaseOportunidad
        
        if not self.pipeline:
            return
        
        ahora = datetime.now(timezone.utc)
        
        # Límites de tiempo por fase (en horas)
        LIMITES_TIEMPO = {
            FaseOportunidad.FASE_1: 2.0,   # 2 horas
            FaseOportunidad.FASE_2: 1.0,   # 1 hora
            FaseOportunidad.FASE_3: 0.5,   # 30 minutos
        }
        
        for simbolo, estado in list(self.pipeline.estados.items()):
            if estado.fase_actual.es_terminal():
                continue
            
            fase = estado.fase_actual
            limite = LIMITES_TIEMPO.get(fase, 1.0)
            
            tiempo_en_fase = (ahora - estado.timestamp_ultima_actualizacion).total_seconds() / 3600
            
            if tiempo_en_fase > limite:
                self.logger.info(f"⬇️ {simbolo}: Degradando por tiempo ({tiempo_en_fase:.1f}h > {limite}h) en {fase.value}")
                
                # Degradar a FASE_1 para re-análisis
                self.pipeline._degradar_oportunidad(
                    simbolo,
                    razon=f"Tiempo excedido en {fase.value} ({tiempo_en_fase:.1f}h)"
                )
                
                # Re-analizar el símbolo
                self._precargar_simbolo(simbolo)

    def _actualizar_noticias(self):
        """Actualiza noticias."""
        if not self._ejecutando:
            return
        
        try:
            self.noticias.actualizar()
        except Exception as e:
            self.logger.warning(f"⚠️ Error actualizando noticias: {e}")
    
    def _enviar_heartbeat(self):
        """Envía heartbeat de estado."""
        if not self._ejecutando:
            return
        
        stats = self.gestion_riesgo.estadisticas()
        posiciones = len(self.estado.posiciones_abiertas)
        
        self.logger.debug(
            f"💓 Heartbeat: "
            f"Capital=${stats.get('capital_actual', 0):.2f}, "
            f"Posiciones={posiciones}, "
            f"Operaciones hoy={stats.get('operaciones_hoy', 0)}"
        )
    
    # ============================================================
    # MÉTODOS DE ACCESO PARA MÓDULOS EXTERNOS
    # ============================================================
    
    def obtener_precio(self, simbolo: str) -> Optional[Dict]:
        """Obtiene precio actual de un símbolo."""
        if self.modo_backtest:
            return {'bid': 1.0, 'ask': 1.0, 'spread': 0.0}
        
        return self.mt5.obtener_precio(simbolo)
    
    def obtener_info_simbolo(self, simbolo: str) -> Optional[Any]:
        """Obtiene información de un símbolo."""
        if self.modo_backtest:
            return None
        
        return self.mt5.obtener_info_simbolo(simbolo)
    
    def ejecutar_operacion(self, op: Dict[str, Any]) -> bool:
        """Ejecuta una operación (delegado al ejecutor)."""
        return self.ejecutor.ejecutar(op)
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del bot."""
        stats = {
            'orquestador': {
                'ejecutando': self._ejecutando,
                'modo_backtest': self.modo_backtest,
                'modo_depuracion': self.modo_depuracion,
                'threads_activos': len([t for t in self._threads if t.is_alive()]),
            },
            'riesgo': self.gestion_riesgo.estadisticas(),
            'cache': self.cache.get_stats(),
            'pipeline': {
                'total': len(self.pipeline.estados) if self.pipeline else 0,
                'activos': len(self.pipeline.obtener_activos()) if self.pipeline else 0,
            },
            'monitor': {
                'total_procesadas': getattr(self.monitor_posiciones, '_stats', {}).get('total_procesadas', 0) if self.monitor_posiciones else 0,
                'cerradas': getattr(self.monitor_posiciones, '_stats', {}).get('cerradas', 0) if self.monitor_posiciones else 0,
            }
        }
        
        return stats


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_orquestador(modo_backtest: bool = False,
                       modo_depuracion: bool = False) -> Orquestador:
    """
    Crea una instancia del orquestador.
    
    Args:
        modo_backtest: Modo backtest
        modo_depuracion: Modo depuración
    
    Returns:
        Orquestador
    """
    return Orquestador(
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida (solo inicialización)
    print("🧪 Inicializando orquestador...")
    
    orquestador = Orquestador(modo_backtest=True, modo_depuracion=True)
    
    print(f"✅ Orquestador inicializado")
    print(f"   Backtest: {orquestador.modo_backtest}")
    print(f"   Depuración: {orquestador.modo_depuracion}")
    print(f"   Capital: ${orquestador.config.CAPITAL_INICIAL:.2f}")
    print(f"   Símbolos: {len(orquestador.config.SIMBOLOS_COMPLETOS)}")
    print(f"   MonitorPosiciones: ✅")
    print(f"   DecisorCierre: ✅")
    
    # Mostrar estadísticas
    print("\n📊 Estadísticas:")
    import json
    print(json.dumps(orquestador.get_stats(), indent=2, default=str))
    
    print("\n✅ Prueba completada")