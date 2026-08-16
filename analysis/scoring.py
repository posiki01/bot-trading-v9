#!/usr/bin/env python3
"""
analysis/scoring.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Motor Cuantitativo de Puntuación - ÚNICO LUGAR para cálculo de scores.

RESPONSABILIDADES:
- Calcular score H1 a partir de componentes técnicos
- Calcular score final combinando H1, M15 y M5
- Aplicar pesos adaptativos por régimen
- Aplicar ajustes por modo y calificación

MEJORAS V9.0:
- Separación de responsabilidades en submódulos
- Integración con umbrales centralizados
- Caché de resultados
- Validación de rangos
- Logs más informativos
- Métodos de compatibilidad para migración
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# Importar umbrales centralizados
try:
    from config.umbrales import Umbrales
except ImportError:
    from config.settings import Config as _Config
    Umbrales = None

logger = logging.getLogger('BotTrading.Scoring')


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class ScoreResultado:
    """Resultado de un cálculo de score."""
    score: float
    detalles: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'score': self.score,
            'detalles': self.detalles,
            'timestamp': self.timestamp,
        }


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class ScoreEngine:
    """
    Motor de puntuación - ÚNICO LUGAR donde se calculan los scores.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # PESOS POR RÉGIMEN (PARA SCORE FINAL)
    # ============================================================
    
    PESOS_POR_REGIMEN = {
        'TREND_ALCISTA_FUERTE': {'h1': 0.55, 'm15': 0.20, 'm5': 0.25},
        'TREND_BAJISTA_FUERTE': {'h1': 0.55, 'm15': 0.20, 'm5': 0.25},
        'TREND_ALCISTA_DEBIL': {'h1': 0.45, 'm15': 0.25, 'm5': 0.30},
        'TREND_BAJISTA_DEBIL': {'h1': 0.45, 'm15': 0.25, 'm5': 0.30},
        'RANGO_AMPLIO': {'h1': 0.30, 'm15': 0.35, 'm5': 0.35},
        'RANGO_APRETADO': {'h1': 0.30, 'm15': 0.35, 'm5': 0.35},
        'CHOP_VOLATIL': {'h1': 0.20, 'm15': 0.30, 'm5': 0.50},
        'BREAKOUT_INMINENTE': {'h1': 0.35, 'm15': 0.25, 'm5': 0.40},
        'INCERTO': {'h1': 0.40, 'm15': 0.30, 'm5': 0.30},
    }
    
    # ============================================================
    # PESOS DE COMPONENTES TÉCNICOS (PARA SCORE H1)
    # ============================================================
    
    PESOS_TECNICOS = {
        'estructura': 0.35,
        'momentum': 0.30,
        'confluencia': 0.20,
        'institucional': 0.15,
    }
    
    def __init__(self, 
                 config: Optional[Any] = None,
                 analysis_cache: Optional[Any] = None,
                 pesos: Optional[Dict[str, float]] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el motor de puntuación.
        
        Args:
            config: Configuración (opcional)
            analysis_cache: Caché de análisis (opcional)
            pesos: Pesos personalizados (opcional)
            modo_backtest: Modo backtest
        """
        self.config = config
        self.analysis_cache = analysis_cache
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Scoring')
        
        # Cargar pesos
        self._cargar_pesos(pesos)
        
        # Cargar umbrales
        self._cargar_umbrales()
        
        # Caché
        self._cache: Dict[str, Tuple[float, float]] = {}
        self._cache_ttl = 60  # segundos
        
        # Estadísticas
        self._stats = {
            'total_calculos': 0,
            'tiempo_promedio': 0,
            'cache_hits': 0,
            'cache_misses': 0,
        }
        
        self.logger.info(f"📊 ScoreEngine V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Pesos técnicos: {self.PESOS_TECNICOS}")
    
    # ============================================================
    # CARGA DE CONFIGURACIÓN
    # ============================================================
    
    def _cargar_pesos(self, pesos: Optional[Dict[str, float]] = None):
        """Carga pesos desde parámetro, config o defaults."""
        if pesos is not None:
            self.weights = pesos
            return
        
        # Intentar desde config
        if self.config and hasattr(self.config, 'SCORE_PESOS'):
            self.weights = getattr(self.config, 'SCORE_PESOS', {}).copy()
            if self.weights:
                return
        
        # Pesos por defecto
        self.weights = {
            'w_tecnica': 0.35,
            'w_institucional': 0.45,
            'w_fundamental': 0.20,
            'bias': 0.0,
            'bias_compra': 0.0,
            'bias_venta': 0.0
        }
    
    def _cargar_umbrales(self):
        """Carga umbrales desde configuración centralizada."""
        if Umbrales is not None:
            # Usar umbrales centralizados
            self.SCORE_MIN_GENERAL = Umbrales.SCORES.get('score_minimo_general', 45)
            self.SCORE_MIN_BACKTEST = Umbrales.SCORES.get('score_minimo_backtest', 25)
            
            # Pesos técnicos desde umbrales (si existen)
            if hasattr(Umbrales, 'PESOS_TECNICOS'):
                self.PESOS_TECNICOS.update(Umbrales.PESOS_TECNICOS)
        else:
            # Fallback
            self.SCORE_MIN_GENERAL = 45
            self.SCORE_MIN_BACKTEST = 25
    
    # ============================================================
    # MÉTODOS DE COMPATIBILIDAD (V8)
    # ============================================================
    
    def get_pesos_tecnicos(self) -> Dict[str, float]:
        """Obtiene los pesos de componentes técnicos."""
        return self.PESOS_TECNICOS.copy()
    
    def get_pesos_por_regimen(self, regimen: str) -> Dict[str, float]:
        """Obtiene los pesos para un régimen específico."""
        return self.PESOS_POR_REGIMEN.get(regimen, self.PESOS_POR_REGIMEN['INCERTO']).copy()
    
    # ============================================================
    # CALCULAR SCORE H1 (NUEVO - V9.0)
    # ============================================================
    
    def calcular_score_h1(self,
                          score_estructura: float,
                          score_momentum: float,
                          score_confluencia: float,
                          score_institucional: float,
                          simbolo: Optional[str] = None) -> ScoreResultado:
        """
        Calcula el score H1 combinando los 4 componentes técnicos.
        V9.0 - REFACTORIZADO con validación.
        
        Args:
            score_estructura: 0-30 (puntaje de estructura)
            score_momentum: 0-35 (puntaje de momentum)
            score_confluencia: 0-35 (puntaje de confluencia)
            score_institucional: 0-35 (puntaje institucional)
            simbolo: Símbolo (para caché, opcional)
        
        Returns:
            ScoreResultado
        """
        # Verificar caché
        if simbolo:
            cache_key = f"h1_{simbolo}_{score_estructura}_{score_momentum}_{score_confluencia}_{score_institucional}"
            if cache_key in self._cache:
                score, timestamp = self._cache[cache_key]
                if time.time() - timestamp < self._cache_ttl:
                    self._stats['cache_hits'] += 1
                    return ScoreResultado(score=score, detalles={'cache': True})
        
        self._stats['total_calculos'] += 1
        self._stats['cache_misses'] += 1
        start_time = time.time()
        
        # 1. Validar rangos
        score_estructura = self._validar_score(score_estructura, 0, 30)
        score_momentum = self._validar_score(score_momentum, 0, 35)
        score_confluencia = self._validar_score(score_confluencia, 0, 35)
        score_institucional = self._validar_score(score_institucional, 0, 35)
        
        # 2. Normalizar a 0-100
        norm_estructura = (score_estructura / 30.0) * 100.0
        norm_momentum = (score_momentum / 35.0) * 100.0
        norm_confluencia = (score_confluencia / 35.0) * 100.0
        norm_institucional = (score_institucional / 35.0) * 100.0
        
        # 3. Aplicar pesos
        score_h1 = (
            (norm_estructura * self.PESOS_TECNICOS['estructura']) +
            (norm_momentum * self.PESOS_TECNICOS['momentum']) +
            (norm_confluencia * self.PESOS_TECNICOS['confluencia']) +
            (norm_institucional * self.PESOS_TECNICOS['institucional'])
        )
        
        # 4. Clipping
        score_h1 = max(0.0, min(100.0, score_h1))
        
        # 5. Guardar en caché
        if simbolo:
            self._cache[cache_key] = (score_h1, time.time())
        
        # 6. Estadísticas
        elapsed = (time.time() - start_time) * 1000
        self._stats['tiempo_promedio'] = (
            (self._stats['tiempo_promedio'] * (self._stats['total_calculos'] - 1) + elapsed)
            / self._stats['total_calculos']
        )
        
        return ScoreResultado(
            score=score_h1,
            detalles={
                'estructura': score_estructura,
                'momentum': score_momentum,
                'confluencia': score_confluencia,
                'institucional': score_institucional,
                'norm_estructura': norm_estructura,
                'norm_momentum': norm_momentum,
                'norm_confluencia': norm_confluencia,
                'norm_institucional': norm_institucional,
                'pesos': self.PESOS_TECNICOS,
                'tiempo_ms': elapsed,
                'cache': False,
            }
        )
    
    # ============================================================
    # CALCULAR SCORE FINAL (NUEVO - V9.0)
    # ============================================================
    
    def calcular_score_final(self,
                             score_h1: float,
                             score_m15: float,
                             score_m5: float,
                             regimen: str = 'INCERTO',
                             calificacion_m15: str = 'NEUTRO',
                             simbolo: Optional[str] = None) -> ScoreResultado:
        """
        Calcula el score final combinando las 3 fases.
        V9.0 - REFACTORIZADO con validación.
        
        Args:
            score_h1: Score H1 (0-100)
            score_m15: Score M15 (0-100)
            score_m5: Score M5 (0-100)
            regimen: Régimen de mercado
            calificacion_m15: 'FORTALECE', 'CONFIRMA', 'NEUTRO', 'CONTRAINDICA'
            simbolo: Símbolo (para caché, opcional)
        
        Returns:
            ScoreResultado
        """
        # Verificar caché
        if simbolo:
            cache_key = f"final_{simbolo}_{score_h1}_{score_m15}_{score_m5}_{regimen}_{calificacion_m15}"
            if cache_key in self._cache:
                score, timestamp = self._cache[cache_key]
                if time.time() - timestamp < self._cache_ttl:
                    self._stats['cache_hits'] += 1
                    return ScoreResultado(score=score, detalles={'cache': True})
        
        self._stats['total_calculos'] += 1
        self._stats['cache_misses'] += 1
        start_time = time.time()
        
        # 1. Validar rangos
        score_h1 = self._validar_score(score_h1, 0, 100)
        score_m15 = self._validar_score(score_m15, 0, 100)
        score_m5 = self._validar_score(score_m5, 0, 100)
        
        # 2. Obtener pesos por régimen
        pesos = self.PESOS_POR_REGIMEN.get(regimen, self.PESOS_POR_REGIMEN['INCERTO']).copy()
        
        # 3. Ajustar por calificación M15
        if calificacion_m15 == 'FORTALECE':
            pesos['m15'] = min(0.50, pesos['m15'] * 1.3)
            total = sum(pesos.values())
            pesos = {k: v/total for k, v in pesos.items()}
        elif calificacion_m15 == 'CONTRAINDICA':
            pesos['m15'] = max(0.10, pesos['m15'] * 0.5)
            pesos['h1'] = min(0.60, pesos['h1'] * 1.2)
            total = sum(pesos.values())
            pesos = {k: v/total for k, v in pesos.items()}
        
        # 4. Calcular score final ponderado
        score_final = (
            (score_h1 * pesos['h1']) +
            (score_m15 * pesos['m15']) +
            (score_m5 * pesos['m5'])
        )
        
        # 5. Bonos/penalizaciones
        if calificacion_m15 == 'FORTALECE':
            score_final = min(100, score_final * 1.05)
        elif calificacion_m15 == 'CONTRAINDICA':
            score_final = score_final * 0.90
        
        # 6. Ajuste por backtest (más permisivo)
        if self.modo_backtest:
            # En backtest, aplicar bono de +10%
            score_final = min(100, score_final * 1.10)
        
        # 7. Clipping
        score_final = max(0.0, min(100.0, score_final))
        
        # 8. Guardar en caché
        if simbolo:
            self._cache[cache_key] = (score_final, time.time())
        
        # 9. Estadísticas
        elapsed = (time.time() - start_time) * 1000
        self._stats['tiempo_promedio'] = (
            (self._stats['tiempo_promedio'] * (self._stats['total_calculos'] - 1) + elapsed)
            / self._stats['total_calculos']
        )
        
        return ScoreResultado(
            score=score_final,
            detalles={
                'score_h1': score_h1,
                'score_m15': score_m15,
                'score_m5': score_m5,
                'regimen': regimen,
                'calificacion_m15': calificacion_m15,
                'pesos': pesos,
                'tiempo_ms': elapsed,
                'cache': False,
            }
        )
    
    # ============================================================
    # CALCULAR SCORE M5 (NUEVO - V9.0)
    # ============================================================
    
    def calcular_score_m5(self,
                          modo: str,
                          volumen_relativo: float,
                          en_nivel_clave: bool = False,
                          patron_calidad: float = 0,
                          adx: float = 0,
                          rsi: float = 50,
                          direccion: str = 'NEUTRAL',
                          simbolo: Optional[str] = None) -> ScoreResultado:
        """
        Calcula el score M5 para el sniper.
        V9.0 - NUEVO.
        
        Args:
            modo: Modo de entrada
            volumen_relativo: Volumen relativo
            en_nivel_clave: Si está en nivel clave
            patron_calidad: Calidad del patrón (0-100)
            adx: ADX actual
            rsi: RSI actual
            direccion: Dirección
            simbolo: Símbolo (para caché)
        
        Returns:
            ScoreResultado
        """
        start_time = time.time()
        
        # 1. Score base por modo
        score_base = {
            'SNIPER_ELITE': 50,
            'NIVEL_FUERTE': 45,
            'RETEST': 40,
            'PATRON': 40,
            'BREAKOUT': 35,
            'PULLBACK': 35,
            'RUPTURA_FALSA': 30,
            'VELA_BORDE': 30,
            'RETEST_FALLBACK': 25,
        }.get(modo, 30)
        
        if self.modo_backtest:
            score_base = max(20, score_base - 10)
        
        score = float(score_base)
        
        # 2. Bono por patrón
        if patron_calidad > 40:
            score += 15
        elif patron_calidad > 20:
            score += 8
        
        # 3. Bono por volumen
        if volumen_relativo > 1.5:
            score += 10
        elif volumen_relativo > 1.0:
            score += 6
        elif volumen_relativo > 0.5:
            score += 3
        
        # 4. Bono por nivel clave
        if en_nivel_clave:
            score += 10
        
        # 5. Bono por ADX
        if adx > 35:
            score += 8
        elif adx > 25:
            score += 5
        
        # 6. Bono por RSI
        if direccion == 'COMPRA' and rsi < 30:
            score += 5
        elif direccion == 'VENTA' and rsi > 70:
            score += 5
        
        # 7. Clipping
        score = max(0.0, min(100.0, score))
        
        elapsed = (time.time() - start_time) * 1000
        
        return ScoreResultado(
            score=score,
            detalles={
                'modo': modo,
                'volumen_relativo': volumen_relativo,
                'en_nivel_clave': en_nivel_clave,
                'patron_calidad': patron_calidad,
                'adx': adx,
                'rsi': rsi,
                'direccion': direccion,
                'score_base': score_base,
                'tiempo_ms': elapsed,
            }
        )
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def _validar_score(self, score: float, min_val: float, max_val: float) -> float:
        """Valida y ajusta un score a un rango."""
        if score is None:
            return min_val
        try:
            return max(min_val, min(max_val, float(score)))
        except (ValueError, TypeError):
            return min_val
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas de uso."""
        stats = self._stats.copy()
        total = stats['cache_hits'] + stats['cache_misses']
        stats['cache_hit_rate'] = (stats['cache_hits'] / total * 100) if total > 0 else 0
        return stats
    
    def reset_stats(self):
        """Reinicia estadísticas."""
        for key in self._stats:
            self._stats[key] = 0
    
    def limpiar_cache(self):
        """Limpia la caché."""
        self._cache.clear()
        logger.debug("🧹 Caché de scoring limpiada")
    
    # ============================================================
    # MÉTODOS DE COMPATIBILIDAD (LEGACY V8)
    # ============================================================
    
    def calcular_score_h1_legacy(self, 
                                 score_estructura: float,
                                 score_momentum: float,
                                 score_confluencia: float,
                                 score_institucional: float) -> float:
        """
        Versión legacy de calcular_score_h1 (retorna float).
        DEPRECADO - Usar calcular_score_h1() en su lugar.
        """
        resultado = self.calcular_score_h1(
            score_estructura=score_estructura,
            score_momentum=score_momentum,
            score_confluencia=score_confluencia,
            score_institucional=score_institucional
        )
        return resultado.score
    
    def calcular_score_final_legacy(self,
                                    score_h1: float,
                                    score_m15: float,
                                    score_m5: float,
                                    regimen: str = 'INCERTO',
                                    calificacion_m15: str = 'NEUTRO') -> float:
        """
        Versión legacy de calcular_score_final (retorna float).
        DEPRECADO - Usar calcular_score_final() en su lugar.
        """
        resultado = self.calcular_score_final(
            score_h1=score_h1,
            score_m15=score_m15,
            score_m5=score_m5,
            regimen=regimen,
            calificacion_m15=calificacion_m15
        )
        return resultado.score
    
    def calcular_score_m5_legacy(self,
                                 modo: str,
                                 volumen_relativo: float,
                                 en_nivel_clave: bool = False,
                                 patron_calidad: float = 0) -> float:
        """
        Versión legacy de calcular_score_m5 (retorna float).
        DEPRECADO - Usar calcular_score_m5() en su lugar.
        """
        resultado = self.calcular_score_m5(
            modo=modo,
            volumen_relativo=volumen_relativo,
            en_nivel_clave=en_nivel_clave,
            patron_calidad=patron_calidad
        )
        return resultado.score


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_score_engine(config: Optional[Any] = None,
                        analysis_cache: Optional[Any] = None,
                        pesos: Optional[Dict[str, float]] = None,
                        modo_backtest: bool = False) -> ScoreEngine:
    """
    Crea una instancia de ScoreEngine.
    
    Args:
        config: Configuración
        analysis_cache: Caché de análisis
        pesos: Pesos personalizados
        modo_backtest: Modo backtest
    
    Returns:
        ScoreEngine
    """
    return ScoreEngine(
        config=config,
        analysis_cache=analysis_cache,
        pesos=pesos,
        modo_backtest=modo_backtest
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida
    engine = ScoreEngine(modo_backtest=True)
    
    # Probar score H1
    resultado_h1 = engine.calcular_score_h1(
        score_estructura=25,
        score_momentum=30,
        score_confluencia=28,
        score_institucional=20,
        simbolo="EURUSD"
    )
    print(f"Score H1: {resultado_h1.score:.1f}")
    print(f"Detalles: {resultado_h1.detalles}")
    
    # Probar score final
    resultado_final = engine.calcular_score_final(
        score_h1=resultado_h1.score,
        score_m15=45,
        score_m5=55,
        regimen="TREND_ALCISTA_FUERTE",
        calificacion_m15="FORTALECE",
        simbolo="EURUSD"
    )
    print(f"Score Final: {resultado_final.score:.1f}")
    print(f"Detalles: {resultado_final.detalles}")
    
    # Probar score M5
    resultado_m5 = engine.calcular_score_m5(
        modo="SNIPER_ELITE",
        volumen_relativo=2.0,
        en_nivel_clave=True,
        patron_calidad=65,
        simbolo="EURUSD"
    )
    print(f"Score M5: {resultado_m5.score:.1f}")
    print(f"Detalles: {resultado_m5.detalles}")
    
    # Estadísticas
    print(f"\nEstadísticas: {engine.get_stats()}")
    
    print("\n✅ Prueba completada")