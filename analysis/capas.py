#!/usr/bin/env python3
"""
analysis/capas.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Sistema de análisis por capas para optimizar rendimiento.

RESPONSABILIDADES:
- Orquestar las 3 capas de análisis
- Coordinar detección de niveles
- Integrar con módulos refactorizados

ESTRUCTURA:
- Capa 1: Análisis rápido (filtro inicial)
- Capa 2: Análisis medio (con niveles)
- Capa 3: Análisis pesado (patrones, Wyckoff, etc.)

MEJORAS V9.0:
- Separación de responsabilidades en submódulos
- Integración con umbrales centralizados
- Uso de NivelTracker para detección de niveles
- Tipado completo
- Logs más informativos
- Caché de resultados
"""

import time
import logging
import warnings
from utils.logger_latencia import medir_latencia
from typing import Dict, Any, Optional, List, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import pandas as pd
import numpy as np

# ============================================================
# IMPORTS REFACTORIZADOS
# ============================================================

# Configuración
from config.umbrales import Umbrales

# Análisis
from analysis.regimen import RegimenMercado
from analysis.scoring import ScoreEngine, ScoreResultado
from analysis.niveles import NivelTracker
from analysis.tecnico import AnalisisTecnico

# Utilidades
from utils.logger_persistente import LoggerPersistente
from utils.helpers import safe_float, safe_int

# ============================================================
# DATACLASSES
# ============================================================

class FiltroResultado(Enum):
    """Resultado del filtro."""
    PASA = "PASA"
    RECHAZA = "RECHAZA"
    CONTINUA = "CONTINUA"


@dataclass
class AnalisisRapido:
    """Resultado del análisis rápido (Capa 1)."""
    valido: bool
    simbolo: str
    precio_actual: float
    precio_anterior: float
    cambio_vela_pct: float
    volumen_relativo: float
    rsi: float
    ema9: float
    ema21: float
    tendencia_corta: str
    atr: float
    timestamp: float = field(default_factory=time.time)
    volumen_ok: bool = False
    rsi_extremo: bool = False
    tendencia_fuerte: bool = False
    pasa_filtro: bool = False
    razon_rechazo: str = ""
    _datos_extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalisisMedio:
    """Resultado del análisis medio (Capa 2)."""
    valido: bool
    simbolo: str
    rsi: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    bb_upper: float
    bb_lower: float
    bb_middle: float
    bb_width_pct: float
    adx: float
    atr: float
    sma20: float
    sma50: float
    sma200: Optional[float]
    soporte_cercano: Optional[float]
    resistencia_cercana: Optional[float]
    distancia_soporte_pct: float
    distancia_resistencia_pct: float
    soporte_hits: int = 0
    resistencia_hits: int = 0
    adx_fuerte: bool = False
    en_nivel_clave: bool = False
    tendencia_alineada: bool = False
    pasa_filtro: bool = False
    razon_rechazo: str = ""
    timestamp: float = field(default_factory=time.time)
    _datos_extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalisisPesado:
    """Resultado del análisis pesado (Capa 3)."""
    valido: bool
    simbolo: str
    patrones_encontrados: List[str]
    patron_principal: str
    calidad_patron: float
    bull_ob: Optional[Dict]
    bear_ob: Optional[Dict]
    ob_cercano: bool
    wyckoff_fase: str
    wyckoff_confianza: float
    divergencia_rsi: Optional[str]
    divergencia_macd: Optional[str]
    score_estructura: float
    score_momentum: float
    score_confluencia: float
    score_institucional: float
    timestamp: float = field(default_factory=time.time)
    score_total: float = 0.0  # Calculado al final


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class AnalisisPorCapas:
    """
    Sistema de análisis por capas optimizado.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    def __init__(self,
                 analisis_tecnico: Optional[AnalisisTecnico] = None,
                 config: Optional[Any] = None,
                 score_engine: Optional[ScoreEngine] = None,
                 nivel_tracker: Optional[NivelTracker] = None,
                 umbrales: Optional[Dict[str, float]] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el sistema de análisis por capas.
        
        Args:
            analisis_tecnico: Analizador técnico
            config: Configuración
            score_engine: Motor de puntuación
            nivel_tracker: Tracker de niveles
            umbrales: Umbrales personalizados
            modo_backtest: Modo backtest
            modo_depuracion: Modo depuración
        """
        self.config = config
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Capas')
        
        # Inicializar dependencias
        self.analisis_tecnico = analisis_tecnico or AnalisisTecnico()
        self.score_engine = score_engine or ScoreEngine(
            config=config,
            modo_backtest=modo_backtest
        )
        self.nivel_tracker = nivel_tracker
        
        # Cargar umbrales
        self.umbrales = self._cargar_umbrales(umbrales)
        
        # Caché de niveles
        self._cache_niveles: Dict[str, Dict] = {}
        self._cache_ttl = 60
        
        # Estadísticas
        self._stats = {
            'rapidos': 0, 'rapidos_pasan': 0,
            'medios': 0, 'medios_pasan': 0,
            'pesados': 0, 'pesados_pasan': 0,
            'tiempo_rapido': 0, 'tiempo_medio': 0, 'tiempo_pesado': 0,
            'niveles_detectados': 0,
        }
        
        self.logger.info(f"📊 AnalisisPorCapas V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Depuración: {modo_depuracion}")
    
    # ============================================================
    # CARGA DE CONFIGURACIÓN
    # ============================================================
    
    def _cargar_umbrales(self, personalizados: Optional[Dict]) -> Dict[str, float]:
        """
        Carga umbrales desde configuración centralizada.
        
        Args:
            personalizados: Umbrales personalizados
        
        Returns:
            Diccionario con umbrales
        """
        umbrales = {
            'volumen_minimo': 0.10,
            'rsi_extremo_superior': 80,
            'rsi_extremo_inferior': 20,
            'cambio_minimo_vela': 0.01,
            'adx_minimo': 10,
            'adx_fuerte': 20,
            'distancia_nivel_max': 3.0,
            'score_minimo': 20,
            'confianza_wyckoff_min': 30,
        }
        
        # Cargar desde Umbrales centralizados
        if Umbrales is not None:
            if hasattr(Umbrales, 'SCORES'):
                umbrales['score_minimo'] = Umbrales.SCORES.get('score_minimo_general', 20)
            if hasattr(Umbrales, 'VOLUMEN'):
                umbrales['volumen_minimo'] = Umbrales.VOLUMEN.get('volumen_minimo_general', 0.10)
            if hasattr(Umbrales, 'ADX'):
                umbrales['adx_minimo'] = Umbrales.ADX.get('adx_minimo_general', 10)
            if hasattr(Umbrales, 'RSI'):
                umbrales['rsi_extremo_superior'] = Umbrales.RSI.get('rsi_maximo', 80)
                umbrales['rsi_extremo_inferior'] = Umbrales.RSI.get('rsi_minimo', 20)
        
        # Aplicar personalizados
        if personalizados:
            umbrales.update(personalizados)
        
        # Ajustes para backtest
        if self.modo_backtest:
            umbrales['volumen_minimo'] = max(0.01, umbrales['volumen_minimo'] * 0.3)
            umbrales['score_minimo'] = max(5, umbrales['score_minimo'] * 0.3)
        
        return umbrales
    
    # ============================================================
    # MÉTODOS PRINCIPALES
    # ============================================================
    
    @medir_latencia("capas_rapido", plataforma="ANALISIS")
    def analisis_rapido(self, df: pd.DataFrame, simbolo: str,
                        precio_actual: Optional[float] = None) -> AnalisisRapido:
        """
        Ejecuta el análisis rápido (Capa 1).
        
        Args:
            df: DataFrame con datos
            simbolo: Símbolo
            precio_actual: Precio actual (opcional)
        
        Returns:
            AnalisisRapido
        """
        from analysis.capas_rapido import AnalisisRapidoEngine
        
        engine = AnalisisRapidoEngine(
            umbrales=self.umbrales,
            config=self.config,
            modo_backtest=self.modo_backtest
        )
        
        resultado = engine.ejecutar(df, simbolo, precio_actual)
        
        # Actualizar estadísticas
        self._stats['rapidos'] += 1
        if resultado.pasa_filtro:
            self._stats['rapidos_pasan'] += 1
        
        return resultado
    
    @medir_latencia("capas_medio", plataforma="ANALISIS")
    def analisis_medio(self, df: pd.DataFrame, simbolo: str,
                       rapido: Optional[AnalisisRapido] = None,
                       niveles_historicos: Optional[Dict] = None,
                       score_h1: float = 0) -> AnalisisMedio:
        """
        Ejecuta el análisis medio (Capa 2) con detección de niveles.
        
        Args:
            df: DataFrame con datos
            simbolo: Símbolo
            rapido: Resultado del análisis rápido
            niveles_historicos: Niveles históricos
            score_h1: Score H1
        
        Returns:
            AnalisisMedio
        """
        from analysis.capas_medio import AnalisisMedioEngine
        
        engine = AnalisisMedioEngine(
            umbrales=self.umbrales,
            config=self.config,
            nivel_tracker=self.nivel_tracker,
            modo_backtest=self.modo_backtest,
            modo_depuracion=self.modo_depuracion
        )
        
        resultado = engine.ejecutar(
            df=df,
            simbolo=simbolo,
            rapido=rapido,
            niveles_historicos=niveles_historicos,
            score_h1=score_h1
        )
        
        # Actualizar estadísticas
        self._stats['medios'] += 1
        if resultado.pasa_filtro:
            self._stats['medios_pasan'] += 1
        
        return resultado
    
    @medir_latencia("capas_pesado", plataforma="ANALISIS")
    def analisis_pesado(self, df: pd.DataFrame, simbolo: str,
                        df_h4: Optional[pd.DataFrame] = None,
                        df_d1: Optional[pd.DataFrame] = None,
                        niveles_historicos: Optional[Dict] = None,
                        medio: Optional[AnalisisMedio] = None) -> AnalisisPesado:
        """
        Ejecuta el análisis pesado (Capa 3).
        
        Args:
            df: DataFrame con datos
            simbolo: Símbolo
            df_h4: DataFrame H4
            df_d1: DataFrame D1
            niveles_historicos: Niveles históricos
            medio: Resultado del análisis medio
        
        Returns:
            AnalisisPesado
        """
        from analysis.capas_pesado import AnalisisPesadoEngine
        
        engine = AnalisisPesadoEngine(
            analisis_tecnico=self.analisis_tecnico,
            umbrales=self.umbrales,
            config=self.config,
            modo_backtest=self.modo_backtest
        )
        
        resultado = engine.ejecutar(
            df=df,
            simbolo=simbolo,
            df_h4=df_h4,
            df_d1=df_d1,
            niveles_historicos=niveles_historicos,
            medio=medio
        )
        
        # Calcular score total
        if self.score_engine:
            score_h1 = self.score_engine.calcular_score_h1(
                score_estructura=resultado.score_estructura,
                score_momentum=resultado.score_momentum,
                score_confluencia=resultado.score_confluencia,
                score_institucional=resultado.score_institucional,
                simbolo=simbolo
            )
            resultado.score_total = score_h1.score
        
        # Actualizar estadísticas
        self._stats['pesados'] += 1
        if resultado.score_total > self.umbrales.get('score_minimo', 20):
            self._stats['pesados_pasan'] += 1
        
        return resultado
    
    # ============================================================
    # MÉTODOS DE NIVELES
    # ============================================================
    
    def detectar_niveles_profundos(self, df: pd.DataFrame, simbolo: str,
                                   nivel_tracker: Optional[NivelTracker] = None) -> Dict[str, Any]:
        """
        Detecta niveles con hits acumulados.
        
        Args:
            df: DataFrame con datos
            simbolo: Símbolo
            nivel_tracker: NivelTracker (opcional)
        
        Returns:
            Diccionario con soportes y resistencias
        """
        if df is None or len(df) < 50:
            return {'soportes': [], 'resistencias': []}
        
        # Usar NivelTracker si está disponible
        tracker = nivel_tracker or self.nivel_tracker
        
        if tracker is not None:
            try:
                precio_actual = df['Close'].iloc[-1]
                niveles = tracker.detectar_y_actualizar_niveles(
                    simbolo=simbolo,
                    df=df,
                    precio_actual=precio_actual,
                    timeframe='H1'
                )
                
                # Guardar en caché
                self._cache_niveles[simbolo] = {
                    'soportes': niveles.get('soportes', []),
                    'resistencias': niveles.get('resistencias', []),
                    'timestamp': time.time()
                }
                
                return niveles
            except Exception as e:
                self.logger.warning(f"Error usando NivelTracker: {e}")
        
        # Fallback: detección local
        return self._detectar_niveles_local(df, simbolo)
    
    def _detectar_niveles_local(self, df: pd.DataFrame, simbolo: str) -> Dict[str, Any]:
        """
        Detección local de niveles (fallback).
        
        Args:
            df: DataFrame con datos
            simbolo: Símbolo
        
        Returns:
            Diccionario con soportes y resistencias
        """
        from analysis.capas_deteccion import DetectorNivelesLocal
        
        detector = DetectorNivelesLocal(umbrales=self.umbrales)
        return detector.detectar(df, simbolo)
    
    def obtener_niveles_cached(self, simbolo: str, df_h1: pd.DataFrame,
                               forzar_actualizacion: bool = False) -> Dict[str, Any]:
        """
        Obtiene niveles desde caché o los detecta.
        
        Args:
            simbolo: Símbolo
            df_h1: DataFrame H1
            forzar_actualizacion: Forzar actualización
        
        Returns:
            Diccionario con soportes y resistencias
        """
        if not forzar_actualizacion and simbolo in self._cache_niveles:
            cached = self._cache_niveles[simbolo]
            if time.time() - cached.get('timestamp', 0) < self._cache_ttl:
                self.logger.debug(f"📊 {simbolo}: Usando niveles en caché")
                return {
                    'soportes': cached['soportes'],
                    'resistencias': cached['resistencias']
                }
        
        niveles = self.detectar_niveles_profundos(df_h1, simbolo)
        self._cache_niveles[simbolo] = {
            'soportes': niveles['soportes'],
            'resistencias': niveles['resistencias'],
            'timestamp': time.time()
        }
        return niveles
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del análisis."""
        stats = self._stats.copy()
        
        if stats['rapidos'] > 0:
            stats['tasa_paso_rapido'] = stats['rapidos_pasan'] / stats['rapidos'] * 100
        else:
            stats['tasa_paso_rapido'] = 0
        
        if stats['medios'] > 0:
            stats['tasa_paso_medio'] = stats['medios_pasan'] / stats['medios'] * 100
        else:
            stats['tasa_paso_medio'] = 0
        
        if stats['pesados'] > 0:
            stats['tasa_paso_pesado'] = stats['pesados_pasan'] / stats['pesados'] * 100
        else:
            stats['tasa_paso_pesado'] = 0
        
        if stats['rapidos'] > 0:
            stats['tiempo_rapido_avg'] = stats['tiempo_rapido'] / stats['rapidos']
        else:
            stats['tiempo_rapido_avg'] = 0
        
        if stats['medios'] > 0:
            stats['tiempo_medio_avg'] = stats['tiempo_medio'] / stats['medios']
        else:
            stats['tiempo_medio_avg'] = 0
        
        if stats['pesados'] > 0:
            stats['tiempo_pesado_avg'] = stats['tiempo_pesado'] / stats['pesados']
        else:
            stats['tiempo_pesado_avg'] = 0
        
        return stats
    
    def reset_stats(self):
        """Reinicia estadísticas."""
        for key in self._stats:
            self._stats[key] = 0
    
    def limpiar_cache(self):
        """Limpia la caché de niveles."""
        self._cache_niveles.clear()
        self.logger.debug("🧹 Caché de niveles limpiada")


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_analisis_por_capas(analisis_tecnico: Optional[AnalisisTecnico] = None,
                              config: Optional[Any] = None,
                              score_engine: Optional[ScoreEngine] = None,
                              nivel_tracker: Optional[NivelTracker] = None,
                              modo_backtest: bool = False,
                              modo_depuracion: bool = False) -> AnalisisPorCapas:
    """
    Crea una instancia de AnalisisPorCapas.
    
    Args:
        analisis_tecnico: Analizador técnico
        config: Configuración
        score_engine: Motor de puntuación
        nivel_tracker: Tracker de niveles
        modo_backtest: Modo backtest
        modo_depuracion: Modo depuración
    
    Returns:
        AnalisisPorCapas
    """
    return AnalisisPorCapas(
        analisis_tecnico=analisis_tecnico,
        config=config,
        score_engine=score_engine,
        nivel_tracker=nivel_tracker,
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion
    )