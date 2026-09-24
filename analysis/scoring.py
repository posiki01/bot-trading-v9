#!/usr/bin/env python3
"""
analysis/scoring.py (V10.0 - REFACTORIZADO)
Motor Cuantitativo de Puntuación - ÚNICO LUGAR para cálculo de scores.

CORRECCIONES V10.0:
- ✅ Añadido calcular_puntuacion_maestra() (era invocado por ml_optimizer.py y no existía)
- ✅ Pesos dinámicos desde self.weights (ML puede ajustarlos)
- ✅ Logs de depuración fuera del hot path
- ✅ Métodos públicos preservados (compatibilidad total)
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

try:
    from config.umbrales import Umbrales
except ImportError:
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
    V10.0 - REFACTORIZADO.
    """

    # ============================================================
    # PESOS POR RÉGIMEN (para score final combinado H1 + M15 + M5)
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
    # PESOS DE COMPONENTES TÉCNICOS (para score H1)
    # ============================================================

    PESOS_TECNICOS = {
        'estructura': 0.35,
        'momentum': 0.30,
        'confluencia': 0.20,
        'institucional': 0.15,
    }

    # ============================================================
    # INIT
    # ============================================================

    def __init__(
        self,
        config: Optional[Any] = None,
        analysis_cache: Optional[Any] = None,
        pesos: Optional[Dict[str, float]] = None,
        modo_backtest: bool = False,
    ):
        self.config = config
        self.analysis_cache = analysis_cache
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Scoring')

        # Cargar pesos (para compatibilidad con MLOptimizer)
        self._cargar_pesos(pesos)

        # Cargar umbrales
        self._cargar_umbrales()

        # Caché interno (opcional, para evitar recalcular)
        self._cache: Dict[str, Tuple[float, float]] = {}
        self._cache_ttl = 60

        # Stats
        self._stats = {
            'total_calculos': 0,
            'tiempo_promedio': 0.0,
            'cache_hits': 0,
            'cache_misses': 0,
        }

        self.logger.info("📊 ScoreEngine V10.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Pesos técnicos: {self.PESOS_TECNICOS}")

    # ============================================================
    # CARGA DE CONFIGURACIÓN
    # ============================================================

    def _cargar_pesos(self, pesos: Optional[Dict[str, float]] = None):
        """
        Carga pesos. Acepta:
        - Dict pasado explícitamente (ej: desde MLOptimizer)
        - Dict desde config.SCORE_PESOS
        - Default
        """
        if pesos is not None:
            self.weights = dict(pesos)
            return

        if self.config and hasattr(self.config, 'SCORE_PESOS'):
            w = getattr(self.config, 'SCORE_PESOS', {})
            if w:
                self.weights = dict(w)
                return

        self.weights = {
            'w_tecnica': 0.35,
            'w_institucional': 0.45,
            'w_fundamental': 0.20,
            'bias': 0.0,
            'bias_compra': 0.0,
            'bias_venta': 0.0,
        }

    def _cargar_umbrales(self):
        """Carga umbrales centralizados."""
        if Umbrales is not None:
            self.SCORE_MIN_GENERAL = Umbrales.SCORES.get('score_minimo_general', 45)
            self.SCORE_MIN_BACKTEST = Umbrales.SCORES.get('score_minimo_backtest', 25)
            if hasattr(Umbrales, 'PESOS_TECNICOS'):
                self.PESOS_TECNICOS.update(Umbrales.PESOS_TECNICOS)
        else:
            self.SCORE_MIN_GENERAL = 45
            self.SCORE_MIN_BACKTEST = 25

    # ============================================================
    # PESOS (compatibilidad ML)
    # ============================================================

    def set_weights(self, pesos: Dict[str, float]):
        """Permite al MLOptimizer actualizar pesos en caliente."""
        self.weights.update(pesos)

    def get_weights(self) -> Dict[str, float]:
        """Retorna copia de los pesos actuales."""
        return dict(self.weights)

    def get_pesos_tecnicos(self) -> Dict[str, float]:
        return self.PESOS_TECNICOS.copy()

    def get_pesos_por_regimen(self, regimen: str) -> Dict[str, float]:
        return self.PESOS_POR_REGIMEN.get(regimen, self.PESOS_POR_REGIMEN['INCERTO']).copy()

    # ============================================================
    # SCORE H1
    # ============================================================

    def calcular_score_h1(
        self,
        score_estructura: float,
        score_momentum: float,
        score_confluencia: float,
        score_institucional: float,
        simbolo: Optional[str] = None,
    ) -> ScoreResultado:
        """
        Combina los 4 componentes técnicos en un score H1 (0-100).
        Cada componente debe venir en rango 0-35.
        """
        start = time.time()

        # Validación
        score_estructura = self._validar_score(score_estructura, 0, 35)
        score_momentum = self._validar_score(score_momentum, 0, 35)
        score_confluencia = self._validar_score(score_confluencia, 0, 35)
        score_institucional = self._validar_score(score_institucional, 0, 35)

        # Normalizar a 0-100
        norm_e = (score_estructura / 35.0) * 100.0
        norm_m = (score_momentum / 35.0) * 100.0
        norm_c = (score_confluencia / 35.0) * 100.0
        norm_i = (score_institucional / 35.0) * 100.0

        # Aplicar pesos técnicos
        score = (
            norm_e * self.PESOS_TECNICOS['estructura']
            + norm_m * self.PESOS_TECNICOS['momentum']
            + norm_c * self.PESOS_TECNICOS['confluencia']
            + norm_i * self.PESOS_TECNICOS['institucional']
        )

        # Clipping
        score = max(0.0, min(100.0, score))

        # Stats
        self._stats['total_calculos'] += 1
        elapsed = (time.time() - start) * 1000
        self._stats['tiempo_promedio'] = (
            (self._stats['tiempo_promedio'] * (self._stats['total_calculos'] - 1) + elapsed)
            / self._stats['total_calculos']
        )

        return ScoreResultado(
            score=score,
            detalles={
                'estructura': score_estructura,
                'momentum': score_momentum,
                'confluencia': score_confluencia,
                'institucional': score_institucional,
                'pesos': self.PESOS_TECNICOS.copy(),
                'tiempo_ms': elapsed,
            },
        )

    # ============================================================
    # SCORE FINAL (H1 + M15 + M5)
    # ============================================================

    def calcular_score_final(
        self,
        score_h1: float,
        score_m15: float,
        score_m5: float,
        regimen: str = 'INCERTO',
        calificacion_m15: str = 'NEUTRO',
        simbolo: Optional[str] = None,
    ) -> ScoreResultado:
        """
        Combina H1 + M15 + M5 con pesos por régimen.
        Retorna 0-100.
        """
        start = time.time()

        score_h1 = self._validar_score(score_h1, 0, 100)
        score_m15 = self._validar_score(score_m15, 0, 100)
        score_m5 = self._validar_score(score_m5, 0, 100)

        # Pesos por régimen
        pesos = self.PESOS_POR_REGIMEN.get(regimen, self.PESOS_POR_REGIMEN['INCERTO']).copy()

        # Ajuste por calificación M15
        if calificacion_m15 == 'FORTALECE':
            pesos['m15'] = min(0.50, pesos['m15'] * 1.3)
            total = sum(pesos.values())
            pesos = {k: v / total for k, v in pesos.items()}
        elif calificacion_m15 == 'CONTRAINDICA':
            pesos['m15'] = max(0.10, pesos['m15'] * 0.5)
            pesos['h1'] = min(0.60, pesos['h1'] * 1.2)
            total = sum(pesos.values())
            pesos = {k: v / total for k, v in pesos.items()}

        score = score_h1 * pesos['h1'] + score_m15 * pesos['m15'] + score_m5 * pesos['m5']

        # Bonos/penalizaciones
        if calificacion_m15 == 'FORTALECE':
            score = min(100, score * 1.05)
        elif calificacion_m15 == 'CONTRAINDICA':
            score = score * 0.90

        if self.modo_backtest:
            score = min(100, score * 1.10)

        score = max(0.0, min(100.0, score))

        self._stats['total_calculos'] += 1
        elapsed = (time.time() - start) * 1000

        return ScoreResultado(
            score=score,
            detalles={
                'score_h1': score_h1,
                'score_m15': score_m15,
                'score_m5': score_m5,
                'regimen': regimen,
                'calificacion_m15': calificacion_m15,
                'pesos': pesos,
                'tiempo_ms': elapsed,
            },
        )

    # ============================================================
    # SCORE M5 (sniper)
    # ============================================================

    def calcular_score_m5(
        self,
        modo: str,
        volumen_relativo: float,
        en_nivel_clave: bool = False,
        patron_calidad: float = 0,
        adx: float = 0,
        rsi: float = 50,
        direccion: str = 'NEUTRAL',
        simbolo: Optional[str] = None,
    ) -> ScoreResultado:
        """
        Score específico del sniper (score base por modo + bonos).
        """
        start = time.time()

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

        if patron_calidad > 40:
            score += 15
        elif patron_calidad > 20:
            score += 8

        if volumen_relativo > 1.5:
            score += 10
        elif volumen_relativo > 1.0:
            score += 6
        elif volumen_relativo > 0.5:
            score += 3

        if en_nivel_clave:
            score += 10

        if adx > 35:
            score += 8
        elif adx > 25:
            score += 5

        if direccion == 'COMPRA' and rsi < 30:
            score += 5
        elif direccion == 'VENTA' and rsi > 70:
            score += 5

        score = max(0.0, min(100.0, score))

        elapsed = (time.time() - start) * 1000
        return ScoreResultado(
            score=score,
            detalles={
                'modo': modo,
                'volumen_relativo': volumen_relativo,
                'en_nivel_clave': en_nivel_clave,
                'patron_calidad': patron_calidad,
                'score_base': score_base,
                'tiempo_ms': elapsed,
            },
        )

    # ============================================================
    # ✅ NUEVO V10.0: PUNTUACIÓN MAESTRA (usado por MLOptimizer)
    # ============================================================

    def calcular_puntuacion_maestra(
        self,
        analisis_raw: Dict[str, Any],
        sentimiento_noticias: float = 0.0,
        reporte_cot: float = 0.0,
        sniper_confirmado: bool = False,
        regimen: Optional[str] = None,
        fase: Optional[int] = None,
    ) -> float:
        """
        Calcula el score maestro (0-100) combinando:
        - Análisis técnico (estructura, momentum, confluencia, institucional)
        - Sentimiento de noticias (ajuste ±15 puntos)
        - Reporte COT (ajuste ±10 puntos)
        - Confirmación del sniper (bonus +10)
        - Pesos optimizados por ML (self.weights)

        Este método reemplaza la llamada inexistente en ml_optimizer.py.
        """
        try:
            # ------------------------------------------------
            # 1. Componentes técnicos desde el análisis
            # ------------------------------------------------
            pts_estructura = self._safe_float(analisis_raw.get('pts_estructura', 50), 50)
            pts_momentum = self._safe_float(analisis_raw.get('pts_momentum', 50), 50)
            pts_confluencia = self._safe_float(analisis_raw.get('pts_confluencia', 50), 50)
            pts_institucional = self._safe_float(analisis_raw.get('pts_institucional', 50), 50)

            # Normalizar a 0-100 (asumiendo entrada 0-35)
            norm_e = min(100.0, (pts_estructura / 35.0) * 100.0)
            norm_m = min(100.0, (pts_momentum / 35.0) * 100.0)
            norm_c = min(100.0, (pts_confluencia / 35.0) * 100.0)
            norm_i = min(100.0, (pts_institucional / 35.0) * 100.0)

            # Capa técnica combinada
            capa_tecnica = (
                norm_e * self.PESOS_TECNICOS['estructura']
                + norm_m * self.PESOS_TECNICOS['momentum']
                + norm_c * self.PESOS_TECNICOS['confluencia']
            )

            # ------------------------------------------------
            # 2. Capa institucional (COT)
            # ------------------------------------------------
            capa_institucional = norm_i
            if reporte_cot:
                # reporte_cot en [-1, 1]
                capa_institucional = max(0.0, min(100.0, capa_institucional + reporte_cot * 10))

            # ------------------------------------------------
            # 3. Capa fundamental (noticias)
            # ------------------------------------------------
            capa_fundamental = 50.0
            if sentimiento_noticias:
                # sentimiento_noticias en [-1, 1]
                capa_fundamental = 50.0 + (sentimiento_noticias * 25.0)
                capa_fundamental = max(0.0, min(100.0, capa_fundamental))

            # ------------------------------------------------
            # 4. Pesos (usar self.weights si están optimizados)
            # ------------------------------------------------
            w_tecnica = self._safe_float(self.weights.get('w_tecnica', 0.35), 0.35)
            w_institucional = self._safe_float(self.weights.get('w_institucional', 0.45), 0.45)
            w_fundamental = self._safe_float(self.weights.get('w_fundamental', 0.20), 0.20)

            # Normalizar pesos (por si no suman 1)
            total_w = w_tecnica + w_institucional + w_fundamental
            if total_w <= 0:
                w_tecnica, w_institucional, w_fundamental = 0.35, 0.45, 0.20
            else:
                w_tecnica /= total_w
                w_institucional /= total_w
                w_fundamental /= total_w

            # ------------------------------------------------
            # 5. Score base
            # ------------------------------------------------
            score = (
                capa_tecnica * w_tecnica
                + capa_institucional * w_institucional
                + capa_fundamental * w_fundamental
            )

            # ------------------------------------------------
            # 6. Sesgos por dirección
            # ------------------------------------------------
            direccion = str(analisis_raw.get('direccion', '')).upper()
            bias = self._safe_float(self.weights.get('bias', 0.0), 0.0)
            score += bias

            if direccion in ('COMPRA', 'BUY'):
                score += self._safe_float(self.weights.get('bias_compra', 0.0), 0.0)
            elif direccion in ('VENTA', 'SELL'):
                score += self._safe_float(self.weights.get('bias_venta', 0.0), 0.0)

            # ------------------------------------------------
            # 7. Bonus por confirmación sniper
            # ------------------------------------------------
            if sniper_confirmado:
                score += 10.0

            # ------------------------------------------------
            # 8. Ajuste por fase
            # ------------------------------------------------
            if fase == 3:
                score += 3.0   # Fase final avanzada, mejor contexto
            elif fase == 1:
                score -= 3.0   # Fase inicial, mayor incertidumbre

            # ------------------------------------------------
            # 9. Ajuste por régimen
            # ------------------------------------------------
            if regimen:
                if regimen in ('TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE'):
                    score += 5.0
                elif regimen == 'CHOP_VOLATIL':
                    score -= 5.0
                elif regimen == 'INCERTO':
                    score -= 3.0

            # ------------------------------------------------
            # 10. Modo backtest (más permisivo)
            # ------------------------------------------------
            if self.modo_backtest:
                score = score * 1.05

            # Clipping final
            score = max(0.0, min(100.0, score))

            self._stats['total_calculos'] += 1

            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(
                    f"🎯 Score maestro: {score:.1f} "
                    f"(tec: {capa_tecnica:.1f}×{w_tecnica:.2f} | "
                    f"inst: {capa_institucional:.1f}×{w_institucional:.2f} | "
                    f"fund: {capa_fundamental:.1f}×{w_fundamental:.2f} | "
                    f"sniper: {sniper_confirmado})"
                )

            return score

        except Exception as e:
            self.logger.error(f"❌ Error en calcular_puntuacion_maestra: {e}", exc_info=True)
            return 50.0

    # ============================================================
    # HELPERS
    # ============================================================

    def _validar_score(self, score: Any, min_val: float, max_val: float) -> float:
        """Valida y ajusta un score a un rango."""
        if score is None:
            return min_val
        try:
            return max(min_val, min(max_val, float(score)))
        except (ValueError, TypeError):
            return min_val

    def _safe_float(self, valor: Any, default: float = 0.0) -> float:
        """Conversión segura a float."""
        if valor is None:
            return default
        try:
            return float(valor)
        except (ValueError, TypeError):
            return default

    # ============================================================
    # ESTADÍSTICAS
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        stats = self._stats.copy()
        total = stats['cache_hits'] + stats['cache_misses']
        stats['cache_hit_rate'] = (stats['cache_hits'] / total * 100) if total > 0 else 0
        return stats

    def reset_stats(self):
        for k in self._stats:
            self._stats[k] = 0 if isinstance(self._stats[k], int) else 0.0

    def limpiar_cache(self):
        self._cache.clear()

    # ============================================================
    # COMPATIBILIDAD (LEGACY V8)
    # ============================================================

    def calcular_score_h1_legacy(self, score_estructura, score_momentum,
                                  score_confluencia, score_institucional) -> float:
        """Retorna solo el float (compatibilidad)."""
        return self.calcular_score_h1(
            score_estructura, score_momentum,
            score_confluencia, score_institucional
        ).score

    def calcular_score_final_legacy(self, score_h1, score_m15, score_m5,
                                     regimen='INCERTO',
                                     calificacion_m15='NEUTRO') -> float:
        return self.calcular_score_final(
            score_h1, score_m15, score_m5, regimen, calificacion_m15
        ).score

    def calcular_score_m5_legacy(self, modo, volumen_relativo,
                                  en_nivel_clave=False,
                                  patron_calidad=0) -> float:
        return self.calcular_score_m5(
            modo, volumen_relativo, en_nivel_clave, patron_calidad
        ).score


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_score_engine(config: Optional[Any] = None,
                        analysis_cache: Optional[Any] = None,
                        pesos: Optional[Dict[str, float]] = None,
                        modo_backtest: bool = False) -> ScoreEngine:
    return ScoreEngine(
        config=config,
        analysis_cache=analysis_cache,
        pesos=pesos,
        modo_backtest=modo_backtest,
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    engine = ScoreEngine(modo_backtest=True)

    # Score H1
    r1 = engine.calcular_score_h1(25, 30, 28, 20, simbolo="EURUSD")
    print(f"Score H1: {r1.score:.1f}")

    # Score final
    r2 = engine.calcular_score_final(r1.score, 45, 55, "TREND_ALCISTA_FUERTE", "FORTALECE")
    print(f"Score Final: {r2.score:.1f}")

    # Score M5
    r3 = engine.calcular_score_m5("SNIPER_ELITE", 2.0, True, 65)
    print(f"Score M5: {r3.score:.1f}")

    # ✅ NUEVO: puntuación maestra
    raw = {
        'pts_estructura': 30,
        'pts_momentum': 28,
        'pts_confluencia': 25,
        'pts_institucional': 22,
        'direccion': 'COMPRA',
    }
    r4 = engine.calcular_puntuacion_maestra(
        analisis_raw=raw,
        sentimiento_noticias=0.4,
        reporte_cot=0.6,
        sniper_confirmado=True,
        regimen="TREND_ALCISTA_FUERTE",
        fase=3,
    )
    print(f"Puntuación maestra: {r4:.1f}")

    print("\n✅ Prueba completada")