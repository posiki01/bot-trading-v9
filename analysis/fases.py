#!/usr/bin/env python3
"""
analysis/fases.py (V9.0 - COMPLETO)
Sistema de análisis por fases H1 → M15 → M5 con caché.
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone

import pandas as pd
import numpy as np

# ============================================================
# IMPORTS
# ============================================================

from config.umbrales import Umbrales
from analysis.regimen import RegimenMercado, MarketRegimeFilter
from analysis.capas import AnalisisPorCapas, AnalisisRapido, AnalisisMedio
from utils.cache import CacheUnificado
from utils.helpers import safe_float
from utils.logger_latencia import medir_latencia

logger = logging.getLogger('BotTrading.Fases')


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class AnalisisPorFase:
    """
    Sistema de análisis por fases H1 → M15 → M5.
    V9.0 - COMPLETO.
    """
    
    def __init__(self,
                 mt5_connector: Optional[Any] = None,
                 noticias: Optional[Any] = None,
                 ml_optimizer: Optional[Any] = None,
                 config: Optional[Any] = None,
                 analysis_cache: Optional[CacheUnificado] = None,
                 analisis_capas: Optional[AnalisisPorCapas] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el sistema de análisis por fases.
        """
        self.mt5 = mt5_connector
        self.noticias = noticias
        self.ml_optimizer = ml_optimizer
        self.config = config
        self.analysis_cache = analysis_cache
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Fases')
        
        self.analisis_capas = analisis_capas
        self.regimen_filter = MarketRegimeFilter(config=config)
        
        self.umbral_fase_3 = 25 if modo_backtest else 40
        
        self._stats = {
            'fase2_validaciones': 0,
            'fase2_aprobadas': 0,
            'fase2_rechazadas': 0,
            'fase2_por_regimen': {},
            'scores_m15_promedio': 0,
            'scores_m15_count': 0,
        }
        
        self.logger.info(f"📊 AnalisisPorFase V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Depuración: {modo_depuracion}")
    
    def set_analisis_capas(self, analisis_capas: AnalisisPorCapas):
        """Inyecta el análisis por capas."""
        self.analisis_capas = analisis_capas
    
    def set_analysis_cache(self, analysis_cache: CacheUnificado):
        """Inyecta la caché de análisis."""
        self.analysis_cache = analysis_cache
    
    def set_modo_backtest(self, modo: bool = True):
        """Activa modo backtest."""
        self.modo_backtest = modo
        self.umbral_fase_3 = 20 if modo else 40
        self.logger.info(f"🔧 Modo backtest: {'ACTIVADO' if modo else 'DESACTIVADO'}")
    
    @medir_latencia("fase1_analisis", plataforma="ANALISIS")
    def analizar_fase_1(self,
                        simbolo: str,
                        df_h1: pd.DataFrame,
                        df_h4: Optional[pd.DataFrame] = None,
                        df_d1: Optional[pd.DataFrame] = None,
                        regimen: str = 'UNCERTAIN',
                        direccion_regimen: str = 'NONE',
                        confianza_regimen: float = 0,
                        force: bool = False) -> Optional[Dict[str, Any]]:
        """Análisis de Fase 1 (H1) con caché."""
        if self.analisis_capas is None:
            self.logger.warning("⚠️ AnalisisPorCapas no disponible")
            return None
        
        rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
        if not rapido.pasa_filtro:
            return None
        
        niveles = {}
        medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
        if not medio.pasa_filtro:
            return None
        
        pesado = self.analisis_capas.analisis_pesado(
            df_h1, simbolo, df_h4, df_d1, niveles, medio
        )
        
        score_min = 25 if self.modo_backtest else 50
        if pesado.score_total < score_min:
            return None
        
        direccion = self._determinar_direccion(medio, pesado)
        
        return {
            'direccion': direccion,
            'score_ajustado': pesado.score_total,
            'score_h1': pesado.score_total,
            'analisis': {
                'rapido': rapido.__dict__ if hasattr(rapido, '__dict__') else {},
                'medio': medio.__dict__ if hasattr(medio, '__dict__') else {},
                'pesado': pesado.__dict__ if hasattr(pesado, '__dict__') else {},
            },
            'es_reversal': 'REVERSAL' in pesado.patron_principal if pesado.patron_principal else False,
            'tendencia_h4': 'ALCISTA' if medio.adx > 25 and medio.sma20 > medio.sma50 else 'BAJISTA' if medio.adx > 25 else 'LATERAL',
            'regimen': regimen,
            'direccion_regimen': direccion_regimen,
            'confianza_regimen': confianza_regimen,
            'pts_estructura': pesado.score_estructura,
            'pts_momentum': pesado.score_momentum,
            'pts_confluencia': pesado.score_confluencia,
            'pts_institucional': pesado.score_institucional,
            'soporte_hits': 0,
            'resistencia_hits': 0,
            'volumen_ok': rapido.volumen_ok,
            'chartismo': pesado.patron_principal,
            'atr': medio.atr,
            'atr_medio': medio.atr * 0.7,
            'rsi': medio.rsi,
            'adx': medio.adx,
            'soporte_cercano': medio.soporte_cercano,
            'resistencia_cercana': medio.resistencia_cercana,
            'en_nivel_clave': medio.en_nivel_clave,
            'smart_money': {
                'wyckoff': pesado.wyckoff_fase,
                'confianza': pesado.wyckoff_confianza,
                'ob_cercano': pesado.ob_cercano,
            }
        }
    
    def _determinar_direccion(self, medio: AnalisisMedio, pesado: Any) -> str:
        """Determina la dirección del análisis."""
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
    
    @medir_latencia("fase2_validacion", plataforma="ANALISIS")
    def validar_fase_2(self,
                       simbolo: str,
                       df_m15: pd.DataFrame,
                       direccion_h1: str,
                       regimen_h1: str = 'UNCERTAIN',
                       regimen_objeto: Optional[RegimenMercado] = None,
                       contexto_h1: Optional[Dict] = None,
                       force: bool = False,
                       analisis_rapido_m15: Optional[AnalisisRapido] = None,
                       analisis_medio_m15: Optional[AnalisisMedio] = None) -> Tuple[bool, str, Optional[Dict]]:
        """Valida la Fase 2 (M15)."""
        self._stats['fase2_validaciones'] += 1
        
        try:
            if df_m15 is None or len(df_m15) < 30:
                return False, f"Datos M15 insuficientes ({len(df_m15) if df_m15 is not None else 0} velas)", None
            
            if self.analisis_capas is None:
                return False, "AnalisisPorCapas no disponible", None
            
            if analisis_rapido_m15 is not None and analisis_medio_m15 is not None:
                rapido_m15 = analisis_rapido_m15
                medio_m15 = analisis_medio_m15
            else:
                rapido_m15 = self.analisis_capas.analisis_rapido(df_m15, simbolo)
                if not rapido_m15.pasa_filtro:
                    return False, f"Filtro rápido M15 falló - {rapido_m15.razon_rechazo}", None
                
                medio_m15 = self.analisis_capas.analisis_medio(df_m15, simbolo, rapido_m15, {})
                if not medio_m15.pasa_filtro:
                    return False, f"Filtro medio M15 falló - {medio_m15.razon_rechazo}", None
            
            umbrales = self._obtener_umbrales_fase2(regimen_h1, regimen_objeto)
            direccion_m15 = self._determinar_direccion_m15(medio_m15)
            
            if direccion_m15 != direccion_h1 and direccion_m15 != 'NEUTRAL':
                score_h1 = contexto_h1.get('score', 0) if contexto_h1 else 0
                if score_h1 >= 75:
                    self.logger.debug(f"⚠️ {simbolo}: M15 {direccion_m15} vs H1 {direccion_h1}, pero H1 confianza alta")
                else:
                    return False, f"Dirección M15 ({direccion_m15}) != H1 ({direccion_h1})", None
            
            valido, motivo = self._validar_condiciones_m15(
                simbolo, medio_m15, rapido_m15, direccion_h1, regimen_h1, umbrales, contexto_h1
            )
            
            if not valido:
                return False, motivo, None
            
            score_m15 = self._calcular_score_m15(
                medio_m15, rapido_m15, direccion_h1, contexto_h1 or {},
                self._calificar_alineacion_m15(medio_m15, rapido_m15, regimen_h1, direccion_h1)
            )
            
            contexto_m15 = self._construir_contexto_m15(
                simbolo, direccion_m15, medio_m15, rapido_m15, score_m15, regimen_h1, umbrales
            )
            
            self._stats['fase2_aprobadas'] += 1
            reg_key = regimen_h1 if regimen_h1 else 'UNKNOWN'
            if reg_key not in self._stats['fase2_por_regimen']:
                self._stats['fase2_por_regimen'][reg_key] = {'aprobadas': 0, 'rechazadas': 0}
            self._stats['fase2_por_regimen'][reg_key]['aprobadas'] += 1
            
            return True, "Fase 2 validada", contexto_m15
            
        except Exception as e:
            self._stats['fase2_rechazadas'] += 1
            self.logger.error(f"❌ Error en Fase 2 {simbolo}: {e}")
            return False, f"Error en Fase 2: {e}", None
    
    def _obtener_umbrales_fase2(self, regimen_h1: str, regimen_objeto: Optional[RegimenMercado]) -> Dict[str, float]:
        """Obtiene umbrales adaptativos para Fase 2."""
        if self.modo_backtest:
            umbrales = {'adx_minimo': 3, 'vol_minimo': 0.05, 'rsi_tolerancia': 20}
        else:
            umbrales = {'adx_minimo': 10, 'vol_minimo': 0.15, 'rsi_tolerancia': 10}
        
        if regimen_objeto is not None and hasattr(self.regimen_filter, 'get_umbrales_para_fase2'):
            ajustes = self.regimen_filter.get_umbrales_para_fase2(regimen_objeto)
            umbrales.update(ajustes)
        
        if regimen_h1 in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
            umbrales['adx_minimo'] = max(3, umbrales.get('adx_minimo', 10) * 0.3)
            umbrales['vol_minimo'] = max(0.05, umbrales.get('vol_minimo', 0.15) * 0.3)
        elif regimen_h1 in ['RANGO_APRETADO']:
            umbrales['adx_minimo'] = max(5, umbrales.get('adx_minimo', 10) * 0.5)
        
        return umbrales
    
    def _determinar_direccion_m15(self, medio_m15: AnalisisMedio) -> str:
        """Determina la dirección M15."""
        if medio_m15.rsi > 55 and medio_m15.macd_histogram > 0 and medio_m15.adx > 3:
            return 'COMPRA'
        elif medio_m15.rsi < 45 and medio_m15.macd_histogram < 0 and medio_m15.adx > 3:
            return 'VENTA'
        return 'NEUTRAL'
    
    def _validar_condiciones_m15(self, simbolo, medio_m15, rapido_m15, direccion_h1,
                                 regimen_h1, umbrales, contexto_h1) -> Tuple[bool, str]:
        """Valida condiciones específicas de M15."""
        adx_min = umbrales.get('adx_minimo', 10)
        if medio_m15.adx < adx_min:
            return False, f"ADX M15 bajo ({medio_m15.adx:.0f} < {adx_min:.0f})"
        
        vol_min = umbrales.get('vol_minimo', 0.15)
        if rapido_m15.volumen_relativo < vol_min:
            if medio_m15.en_nivel_clave or medio_m15.adx > 30 or abs(medio_m15.macd_histogram) > 0.0005:
                self.logger.debug(f"⚠️ {simbolo}: volumen bajo ({rapido_m15.volumen_relativo:.1f}x) pero permitido")
            else:
                return False, f"Volumen M15 bajo ({rapido_m15.volumen_relativo:.1f}x < {vol_min:.1f}x)"
        
        rsi_tol = umbrales.get('rsi_tolerancia', 10)
        if direccion_h1 == 'COMPRA' and medio_m15.rsi > (80 + rsi_tol):
            return False, f"RSI M15 sobrecompra ({medio_m15.rsi:.0f} > {80 + rsi_tol:.0f})"
        if direccion_h1 == 'VENTA' and medio_m15.rsi < (20 - rsi_tol):
            return False, f"RSI M15 sobreventa ({medio_m15.rsi:.0f} < {20 - rsi_tol:.0f})"
        
        return True, "OK"
    
    def _calificar_alineacion_m15(self, medio_m15, rapido_m15, regimen_h1, direccion_h1) -> str:
        """Califica la alineación de M15 con H1."""
        fortalece = 0
        contradice = 0
        
        if medio_m15.adx > 20:
            fortalece += 1
        if rapido_m15.volumen_relativo > 1.5:
            fortalece += 1
        if direccion_h1 == 'COMPRA' and medio_m15.macd_histogram > 0:
            fortalece += 1
        elif direccion_h1 == 'VENTA' and medio_m15.macd_histogram < 0:
            fortalece += 1
        if direccion_h1 == 'COMPRA' and medio_m15.rsi > 50:
            fortalece += 1
        elif direccion_h1 == 'VENTA' and medio_m15.rsi < 50:
            fortalece += 1
        if direccion_h1 == 'COMPRA' and medio_m15.macd_histogram < 0:
            contradice += 1
        elif direccion_h1 == 'VENTA' and medio_m15.macd_histogram > 0:
            contradice += 1
        if direccion_h1 == 'COMPRA' and medio_m15.rsi < 40:
            contradice += 1
        elif direccion_h1 == 'VENTA' and medio_m15.rsi > 60:
            contradice += 1
        
        if fortalece >= 3:
            return 'FORTALECE'
        elif contradice >= 2:
            return 'CONTRAINDICA'
        elif fortalece >= 1:
            return 'CONFIRMA'
        else:
            return 'NEUTRO'
    
    def _calcular_score_m15(self, medio_m15, rapido_m15, direccion_h1, contexto_h1, calificacion) -> float:
        """Calcula el score de la Fase 2 (M15)."""
        score = 0.0
        
        # ADX (0-20)
        if medio_m15.adx > 40:
            score += 20
        elif medio_m15.adx > 30:
            score += 16
        elif medio_m15.adx > 20:
            score += 12
        elif medio_m15.adx > 15:
            score += 8
        elif medio_m15.adx > 10:
            score += 5
        elif medio_m15.adx > 5:
            score += 3
        
        # Volumen (0-15)
        if rapido_m15.volumen_relativo > 3.0:
            score += 15
        elif rapido_m15.volumen_relativo > 2.0:
            score += 12
        elif rapido_m15.volumen_relativo > 1.5:
            score += 8
        elif rapido_m15.volumen_relativo > 1.0:
            score += 5
        elif rapido_m15.volumen_relativo > 0.5:
            score += 3
        
        # Alineación (0-30)
        rsi_m15 = medio_m15.rsi
        macd_m15 = medio_m15.macd_histogram
        
        if direccion_h1 == 'COMPRA':
            if rsi_m15 > 55 and macd_m15 > 0.0001:
                score += 30
            elif rsi_m15 > 50 and macd_m15 > 0:
                score += 22
            elif rsi_m15 > 45:
                score += 12
            elif rsi_m15 < 40:
                score -= 8
            else:
                score += 5
        elif direccion_h1 == 'VENTA':
            if rsi_m15 < 45 and macd_m15 < -0.0001:
                score += 30
            elif rsi_m15 < 50 and macd_m15 < 0:
                score += 22
            elif rsi_m15 < 55:
                score += 12
            elif rsi_m15 > 60:
                score -= 8
            else:
                score += 5
        else:
            score += 15
        
        # Calidad de vela (0-15)
        if direccion_h1 == 'COMPRA' and medio_m15.rsi < 30:
            score += 8
        elif direccion_h1 == 'VENTA' and medio_m15.rsi > 70:
            score += 8
        
        if abs(medio_m15.macd_histogram) > 0.0005:
            score += 5
        elif abs(medio_m15.macd_histogram) > 0.0002:
            score += 3
        
        if medio_m15.bb_width_pct > 20:
            score += 2
        
        # Nivel clave (0-10)
        if medio_m15.en_nivel_clave:
            score += 10
        
        # Reversal (0-10)
        if contexto_h1.get('es_reversal', False):
            if (direccion_h1 == 'COMPRA' and medio_m15.rsi < 35) or \
               (direccion_h1 == 'VENTA' and medio_m15.rsi > 65):
                score += 10
            elif (direccion_h1 == 'COMPRA' and medio_m15.rsi < 45) or \
                 (direccion_h1 == 'VENTA' and medio_m15.rsi > 55):
                score += 5
        
        # Calificación
        if calificacion == 'FORTALECE':
            score += 5
        elif calificacion == 'CONFIRMA':
            score += 3
        elif calificacion == 'CONTRAINDICA':
            score = max(0, score - 20)
        
        self._stats['scores_m15_count'] += 1
        self._stats['scores_m15_promedio'] = (
            (self._stats['scores_m15_promedio'] * (self._stats['scores_m15_count'] - 1) + score)
            / self._stats['scores_m15_count']
        )
        
        return min(100.0, max(0.0, score))
    
    def _construir_contexto_m15(self, simbolo, direccion_m15, medio_m15, rapido_m15,
                                score_m15, regimen_h1, umbrales) -> Dict[str, Any]:
        """Construye el contexto de M15."""
        return {
            'direccion': direccion_m15,
            'adx': medio_m15.adx,
            'rsi': medio_m15.rsi,
            'volumen_relativo': rapido_m15.volumen_relativo,
            'en_nivel_clave': medio_m15.en_nivel_clave,
            'calificacion': self._calificar_alineacion_m15(
                medio_m15, rapido_m15, regimen_h1, direccion_m15
            ),
            'atr': medio_m15.atr,
            'macd_histogram': medio_m15.macd_histogram,
            'bb_width_pct': medio_m15.bb_width_pct,
            'score_m15': score_m15,
            'medio': medio_m15,
            'rapido': rapido_m15,
            'soporte_cercano': medio_m15.soporte_cercano,
            'resistencia_cercana': medio_m15.resistencia_cercana,
            'umbrales_usados': umbrales,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas."""
        stats = self._stats.copy()
        total = stats['fase2_validaciones']
        if total > 0:
            stats['tasa_aprobacion'] = stats['fase2_aprobadas'] / total * 100
            stats['tasa_rechazo'] = stats['fase2_rechazadas'] / total * 100
        else:
            stats['tasa_aprobacion'] = 0
            stats['tasa_rechazo'] = 0
        return stats


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_analisis_por_fase(mt5_connector: Optional[Any] = None,
                             noticias: Optional[Any] = None,
                             ml_optimizer: Optional[Any] = None,
                             config: Optional[Any] = None,
                             analysis_cache: Optional[CacheUnificado] = None,
                             modo_backtest: bool = False,
                             modo_depuracion: bool = False) -> AnalisisPorFase:
    """Crea una instancia de AnalisisPorFase."""
    return AnalisisPorFase(
        mt5_connector=mt5_connector,
        noticias=noticias,
        ml_optimizer=ml_optimizer,
        config=config,
        analysis_cache=analysis_cache,
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion
    )