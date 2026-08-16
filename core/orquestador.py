#!/usr/bin/env python3
"""
core/orquestador.py (V9.0 - INTEGRACIÓN FINAL)
Orquestador principal - Coordina todos los módulos del Bot de Trading.

RESPONSABILIDADES:
- Inicializar todos los módulos
- Gestionar el ciclo de vida del bot
- Coordinar la comunicación entre módulos
- Manejar señales del sistema
- Proveer acceso centralizado a los módulos
- Gestionar el estado global

ESTRUCTURA:
1. Configuración y logging
2. Almacenamiento y persistencia
3. Conectores (MT5)
4. Módulos de análisis
5. Módulos de trading
6. Módulos de utilidad
7. Estado global
8. Ciclo principal
9. Gestión de señales
"""

import os
import sys
import time
import signal
import threading
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone

# ============================================================
# IMPORTS DE MÓDULOS REFACTORIZADOS
# ============================================================

# Configuración
from config.settings import Config
from config.umbrales import Umbrales

# Core
from core.estados import EstadoGlobal

# Utilidades
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

# Análisis
from analysis.regimen import MarketRegimeFilter, RegimenMercado, create_regime_filter
from analysis.scoring import ScoreEngine, create_score_engine
from analysis.niveles import NivelTracker, create_nivel_tracker
from analysis.capas import AnalisisPorCapas
from analysis.fases import AnalisisPorFase, create_analisis_por_fase
from analysis.pipeline import PipelineOportunidades


# Trading
from trading.riesgo import GestionRiesgo, create_gestion_riesgo
from trading.stops import GestorStops, create_gestor_stops
from trading.trailing import TrailingEngine, create_trailing_engine
from trading.ejecucion import EjecutorOperaciones, create_ejecutor_operaciones
from trading.sniper_checklist import SniperChecklist, create_sniper_checklist
from trading.operabilidad import DecisorOperabilidad, create_decisor_operabilidad
from trading.modos import ModoSelector
from trading.timer import EntryTimer

# Data
from data.almacenamiento_sqlite import AlmacenamientoSQLite

# MT5
from mt5.conector_mt5 import ConectorPepperstone, ConectorHeadless

# Notificaciones
from notificaciones.alertas import Notificaciones

# Noticias
from noticias.sistema_noticias import SistemaNoticias

logger = logging.getLogger('BotTrading.Orquestador')


class Orquestador:
    """
    Orquestador principal del Bot de Trading.
    V9.0 - INTEGRACIÓN FINAL.
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
            discord=self.config.DISCORD_WEBHOOK,
            tg_token=self.config.TELEGRAM_TOKEN,
            tg_chat=self.config.TELEGRAM_CHAT_ID,
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
            modo_backtest=modo_backtest
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
        # 13. SEÑALES DEL SISTEMA
        # ============================================================
        
        signal.signal(signal.SIGINT, self._manejar_senal)
        signal.signal(signal.SIGTERM, self._manejar_senal)
        
        # ============================================================
        # 14. LOG DE INICIO
        # ============================================================
        
        self._log_inicio()
        
        self.logger.info("🚀 Orquestador V9.0 inicializado correctamente")
    
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
                demo=self.config.MT5_DEMO
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
        
        # Análisis por capas
        self.analisis_capas = AnalisisPorCapas(
            analisis_tecnico=None,  # Se inicializará después
            config=self.config,
            score_engine=self.score_engine
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
            config=self.config
        )
    
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
        
        # Modo selector
        self.modo_selector = ModoSelector(
            config=self.config,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion
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
            modo_backtest=self.modo_backtest
        )
    
    def _inicializar_utilidades(self):
        """Inicializa módulos de utilidad."""
        # La caché ya está inicializada
        # El horario ya está inicializado
        pass
    
    def _inicializar_sniper(self):
        """Inicializa módulos del sniper."""
        self.sniper_checklist = create_sniper_checklist(
            pipeline=self.pipeline,
            config=self.config,
            almacen=self.almacen,
            mt5=self.mt5,
            noticias=self.noticias,
            patron_tracker=None,  # Se inicializará después
            ml_optimizer=None,    # Se inicializará después
            analysis_cache=self.cache,
            modo_depuracion=self.modo_depuracion,
            gestor_stops=self.gestor_stops
        )
        self.sniper_checklist.set_modo_backtest(self.modo_backtest)
    
    def _log_inicio(self):
        """Log de inicio del orquestador."""
        self.logger.info("=" * 60)
        self.logger.info("🚀 ORQUESTADOR V9.0 INICIADO")
        self.logger.info("=" * 60)
        self.logger.info(f"   Entorno: {self.config.ENTORNO}")
        self.logger.info(f"   Backtest: {self.modo_backtest}")
        self.logger.info(f"   Depuración: {self.modo_depuracion}")
        self.logger.info(f"   Capital: ${self.config.CAPITAL_INICIAL:.2f}")
        self.logger.info(f"   Símbolos: {len(self.config.SIMBOLOS_COMPLETOS)}")
        self.logger.info(f"   MT5 Demo: {self.config.MT5_DEMO}")
        self.logger.info("=" * 60)
    
    # ============================================================
    # MANEJO DE SEÑALES
    # ============================================================
    
    def _manejar_senal(self, signum, frame):
        """Maneja señales del sistema."""
        self.logger.info(f"🛑 Señal {signum} recibida, deteniendo...")
        self.detener()
    
    # ============================================================
    # CICLO PRINCIPAL
    # ============================================================
    
    def iniciar(self):
        """
        Inicia el bot con todos los módulos.
        """
        self.logger.info("🚀 Iniciando Bot de Trading V9.0...")
        
        # 1. Verificar configuración
        if not self.config.verificar_env():
            self.logger.error("❌ Configuración inválida")
            self.notificaciones.enviar(
                "❌ CONFIGURACIÓN INVÁLIDA",
                "Verifica las variables de entorno",
                tipo='error'
            )
            return
        
        # 2. Conectar a MT5
        if not self.modo_backtest:
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
        
        # 3. Sincronizar estado
        if not self.modo_backtest:
            self._sincronizar_estado_inicial()
        
        # 4. Actualizar noticias
        self._actualizar_noticias()
        
        # 5. Iniciar threads
        self._ejecutando = True
        self.estado.operando = True
        self._iniciar_threads()
        
        # 6. Notificar inicio
        self.notificaciones.enviar(
            "🚀 BOT INICIADO",
            f"Capital: ${float(self.gestion_riesgo.capital_actual):,.2f}\n"
            f"Modo: {'BACKTEST' if self.modo_backtest else 'REAL'}\n"
            f"Entorno: {self.config.ENTORNO}",
            tipo='exito'
        )
        
        self.logger.info("✅ Bot iniciado correctamente")
        
        # 7. Bucle principal
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
        """
        if not self._ejecutando:
            return
        
        self.logger.info("🛑 Deteniendo bot...")
        self._ejecutando = False
        self.estado.operando = False
        
        # Esperar threads
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        
        # Cerrar conexiones
        if not self.modo_backtest:
            self.mt5.desconectar()
        
        self.almacen.cerrar()
        
        # Notificar
        self.notificaciones.enviar(
            "🛑 BOT DETENIDO",
            f"Hora: {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC",
            tipo='info'
        )
        
        self.logger.info("✅ Bot detenido correctamente")
    
    # ============================================================
    # THREADS
    # ============================================================
    
    def _iniciar_threads(self):
        """Inicia los hilos de ejecución."""
        threads_config = [
            ('Escaneo', self._thread_escaneo, 1800),  # 30 minutos
            ('Sniper', self._thread_sniper, 30),      # 30 segundos
            ('Monitoreo', self._thread_monitoreo, 30), # 30 segundos
            ('Heartbeat', self._thread_heartbeat, 60), # 60 segundos
            ('Noticias', self._thread_noticias, 300),  # 5 minutos
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
        """Ejecuta escaneo de mercado."""
        self._ejecutar_escaneo()
    
    def _thread_sniper(self):
        """Ejecuta ciclo del sniper."""
        self._ejecutar_sniper()
    
    def _thread_monitoreo(self):
        """Ejecuta monitoreo de posiciones."""
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
        """
        if not self._ejecutando:
            return
        
        self.logger.info("🔍 Iniciando escaneo de mercado...")
        
        # Verificar horario
        if not self.horario.mercado_abierto():
            self.logger.info("🌙 Mercado cerrado, omitiendo escaneo")
            return
        
        # Obtener símbolos a escanear
        simbolos = self.config.SIMBOLOS_COMPLETOS
        
        if self.modo_backtest:
            simbolos = self.config.SIMBOLOS_OPERABLES
        
        self.logger.info(f"📋 Escaneando {len(simbolos)} símbolos...")
        
        # Escanear cada símbolo
        for simbolo in simbolos:
            if not self._ejecutando:
                break
            
            try:
                self._escanear_simbolo(simbolo)
            except Exception as e:
                self.logger.warning(f"⚠️ Error escaneando {simbolo}: {e}")
                continue
        
        # Promover oportunidades en pipeline
        self._promover_oportunidades()
        
        # Log de estado
        activos = self.pipeline.obtener_activos() if self.pipeline else []
        self.logger.info(f"✅ Escaneo completado. Pipeline: {len(activos)} oportunidades activas")
    
    def _escanear_simbolo(self, simbolo: str):
        """
        Escanea un símbolo individual.
        
        Args:
            simbolo: Símbolo a escanear
        """
        # 1. Obtener datos H1
        df_h1 = self._obtener_datos_cached(simbolo, n_velas=250, timeframe=60)
        if df_h1 is None or len(df_h1) < 100:
            return
        
        # 2. Análisis rápido
        rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
        if not rapido.pasa_filtro:
            return
        
        # 3. Detectar niveles
        precio_actual = df_h1['Close'].iloc[-1]
        niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
            simbolo=simbolo,
            df=df_h1,
            precio_actual=precio_actual,
            timeframe='H1'
        )
        
        # 4. Análisis medio
        medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
        if not medio.pasa_filtro:
            return
        
        # 5. Análisis pesado
        df_h4 = self._obtener_datos_cached(simbolo, n_velas=100, timeframe=240) if not self.modo_backtest else None
        df_d1 = self._obtener_datos_cached(simbolo, n_velas=50, timeframe=1440) if not self.modo_backtest else None
        
        pesado = self.analisis_capas.analisis_pesado(df_h1, simbolo, df_h4, df_d1, niveles, medio)
        
        # 6. Calcular score H1
        score_h1 = self.score_engine.calcular_score_h1(
            score_estructura=pesado.score_estructura,
            score_momentum=pesado.score_momentum,
            score_confluencia=pesado.score_confluencia,
            score_institucional=pesado.score_institucional,
            simbolo=simbolo
        ).score
        
        # 7. Determinar dirección
        direccion = self._determinar_direccion(medio, pesado)
        
        # 8. Clasificar régimen
        regimen_data = self.regimen_filter.clasificar(simbolo, df_h4, df_h1)
        regimen = regimen_data.regimen.value
        
        # 9. Validar dirección por régimen
        valido, razon = self._validar_direccion_por_regimen(direccion, regimen)
        if not valido:
            return
        
        # 10. Guardar en pipeline
        if self.pipeline:
            self.pipeline.actualizar_fase_1(
                simbolo=simbolo,
                analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
                score=score_h1,
                direccion=direccion,
                regimen=regimen,
                direccion_regimen=regimen_data.direccion_favor,
                confianza_regimen=regimen_data.confianza,
                tendencia_h4='ALCISTA' if medio.adx > 25 and medio.sma20 > medio.sma50 else 'BAJISTA' if medio.adx > 25 else 'LATERAL'
            )
    
    def _ejecutar_sniper(self):
        """
        Ejecuta un ciclo del sniper.
        """
        if not self._ejecutando:
            return
        
        # Verificar horario
        if not self.horario.mercado_abierto():
            return
        
        # Obtener oportunidades del pipeline
        oportunidades = self.pipeline.obtener_activos() if self.pipeline else []
        
        if not oportunidades:
            return
        
        # Ordenar por score
        oportunidades.sort(key=lambda x: x.score_acumulado, reverse=True)
        
        # Evaluar cada oportunidad
        for estado in oportunidades[:5]:  # Máximo 5 por ciclo
            if not self._ejecutando:
                break
            
            self._evaluar_oportunidad(estado)
    
    def _evaluar_oportunidad(self, estado):
        """
        Evalúa una oportunidad específica.
        
        Args:
            estado: Estado de la oportunidad
        """
        simbolo = estado.simbolo
        
        # Verificar cooldown
        if simbolo in self.estado.sniper_cooldown:
            if datetime.now(timezone.utc) < self.estado.sniper_cooldown[simbolo]:
                return
        
        # Verificar posición abierta
        if not self.modo_backtest:
            posiciones = self.mt5.obtener_posiciones()
            if posiciones and any(p['simbolo'] == simbolo for p in posiciones):
                return
        
        # Verificar dirección
        if estado.direccion == 'NEUTRAL':
            return
        
        # Verificar score
        if estado.score_acumulado < 30:
            return
        
        # Obtener datos M5
        df_m5 = self._obtener_datos_cached(simbolo, n_velas=150, timeframe=5)
        if df_m5 is None or len(df_m5) < 50:
            return
        
        # Obtener contexto H1
        contexto_h1 = self.estado.contexto_h1.get(simbolo, {})
        
        # Evaluar sniper
        resultado = self.sniper_checklist.evaluar_sniper_optimizado(
            simbolo=simbolo,
            df_m5=df_m5,
            precio_actual=df_m5['Close'].iloc[-1],
            direccion=estado.direccion,
            estado_pipeline=estado,
            analisis_rapido=None,
            analisis_medio=None,
            ejecutar_pesado=True,
            contexto_h1=contexto_h1,
            df_m15=getattr(estado, 'analisis_m15', None),
            info_tick=None,
            spread_pips=0,
            regimen_objeto=None,
            calidad_horario='REGULAR'
        )
        
        if resultado:
            # Ejecutar operación
            self.ejecutor.ejecutar(resultado)
    
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
            ticket = pos['ticket']
            simbolo = pos['simbolo']
            
            # Verificar si es manual
            meta = self.estado.posiciones_abiertas.get(ticket, {})
            if meta.get('es_manual', False):
                continue
            
            # Obtener datos H1
            df_h1 = self._obtener_datos_cached(simbolo, n_velas=50, timeframe=60)
            
            # Calcular decisión de trailing
            decision = self.trailing_engine.calcular_movimiento_sl(
                pos=pos,
                df_h1=df_h1,
                precio_actual=pos['precio_actual'],
                fecha=datetime.now(timezone.utc),
                regimen=meta.get('regimen', 'INCERTO'),
                modo=meta.get('modo', 'RETEST')
            )
            
            # Aplicar decisión
            if decision.cerrar:
                self._cerrar_posicion(ticket, decision.motivo_cierre or decision.razon)
            elif decision.mover_sl and decision.nuevo_sl:
                self._mover_sl(ticket, decision.nuevo_sl)
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def _obtener_datos_cached(self, simbolo: str, n_velas: int = 250,
                              timeframe: int = None) -> Optional[Any]:
        """
        Obtiene datos de mercado con caché.
        
        Args:
            simbolo: Símbolo
            n_velas: Número de velas
            timeframe: Timeframe (MT5 constante)
        
        Returns:
            DataFrame o None
        """
        if self.modo_backtest:
            # En backtest, usar datos simulados o desde archivo
            return None
        
        return self.cache.get_datos(
            simbolo=simbolo,
            timeframe=timeframe or self.config.TIMEFRAME,
            n_velas=n_velas,
            fetch_func=self.mt5.obtener_datos
        )
    
    def _determinar_direccion(self, medio, pesado) -> str:
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
        
        if bullish > bearish + 2:
            return 'COMPRA'
        elif bearish > bullish + 2:
            return 'VENTA'
        return 'NEUTRAL'
    
    def _validar_direccion_por_regimen(self, direccion: str, regimen: str) -> Tuple[bool, str]:
        """Valida dirección por régimen."""
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            if direccion == 'VENTA':
                return False, "VENTA en contra de tendencia alcista"
        elif regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            if direccion == 'COMPRA':
                return False, "COMPRA en contra de tendencia bajista"
        
        return True, "OK"
    
    def _promover_oportunidades(self):
        """Promueve oportunidades en el pipeline."""
        if not self.pipeline:
            return
        
        for simbolo, estado in list(self.pipeline.estados.items()):
            if estado.fase_actual.value == 'FASE_1':
                if estado.score_acumulado >= 50 and estado.direccion != 'NEUTRAL':
                    estado.fase_actual = self.pipeline.FaseOportunidad.FASE_2
                    self.logger.debug(f"⬆️ {simbolo}: promovido a FASE_2")
    
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
        """Sincroniza el estado inicial con el broker."""
        self.logger.info("🔄 Sincronizando estado inicial...")
        
        # Cargar posiciones abiertas
        posiciones = self.mt5.obtener_posiciones()
        
        for pos in posiciones:
            ticket = pos['ticket']
            
            # Verificar si es del bot (por magic number)
            magic = pos.get('magic', 0)
            es_bot = magic == self.config.MAGIC_NUMBER
            
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
        
        self.logger.info(f"✅ {len(self.estado.posiciones_abiertas)} posiciones sincronizadas")
    
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
    
    # Mostrar estadísticas
    print("\n📊 Estadísticas:")
    import json
    print(json.dumps(orquestador.get_stats(), indent=2, default=str))
    
    print("\n✅ Prueba completada")