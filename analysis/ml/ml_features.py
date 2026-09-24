#!/usr/bin/env python3
"""
analysis/ml/ml_features.py (V2.0 - NUEVO)
Feature engineering para el modelo ML.

OBJETIVO:
Convertir el contexto de una operación (H1 + M15 + M5 + régimen + nivel)
en un vector numérico que el modelo pueda aprender.

FILOSOFÍA:
- Cada feature debe ser ESTABLE entre train e inference
- No usar datos que no estarían disponibles en el momento de la decisión
- Normalizar todo a rangos predecibles
- Incluir el "por qué" (razones de decisión), no solo el "qué"
"""

import logging
import math
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger('BotTrading.ML.Features')


# ============================================================
# CATÁLOGOS (one-hot encoding)
# ============================================================

REGIMENES = [
    'TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE',
    'TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL',
    'RANGO_AMPLIO', 'RANGO_APRETADO',
    'BREAKOUT_INMINENTE', 'CHOP_VOLATIL', 'INCERTO',
]

MODOS = [
    'RETEST', 'BREAKOUT', 'PULLBACK', 'NIVEL_FUERTE',
    'PATRON', 'RUPTURA_FALSA', 'VELA_BORDE',
    'RETEST_FALLBACK', 'SNIPER_ELITE',
]

SESIONES = ['ASIAN', 'LONDON', 'NEW_YORK', 'OVERLAP_LDN_NY', 'CRYPTO']

CALIDAD_HORARIO = ['EXCELENTE', 'BUENA', 'REGULAR', 'MALA', 'PESIMA']

WYCKOFF_FASES = [
    'ACUMULACION', 'DISTRIBUCION', 'SPRING', 'UPTHRUST',
    'TENDENCIA_ALCISTA', 'TENDENCIA_BAJISTA', 'NEUTRAL',
]


# ============================================================
# EXTRACTOR DE FEATURES
# ============================================================

class FeatureExtractor:
    """
    Convierte el contexto de una operación en un vector de features.

    USO:
        extractor = FeatureExtractor()
        features = extractor.extraer(op_dict)  # → np.ndarray
        nombres = extractor.nombres_features()  # → List[str]
    """

    VERSION = "2.0"

    def __init__(self):
        self.logger = logging.getLogger('BotTrading.ML.Features')
        self._nombres_cache: Optional[List[str]] = None

    # ============================================================
    # API PÚBLICA
    # ============================================================

    def extraer(self, op: Dict[str, Any]) -> Optional[np.ndarray]:
        """
        Extrae el vector de features de una operación.

        Args:
            op: Diccionario con la operación. Debe tener al menos:
                - direccion: 'COMPRA'|'VENTA'
                - regimen: str
                - score_h1: float
                - modo: str
                - y opcionalmente: score_m15, score_m5, adx, rsi, etc.

        Returns:
            np.ndarray de features (o None si falta info esencial)
        """
        try:
            features: List[float] = []

            # ------------------------------------------------------
            # 1. DIRECCIÓN (1 feature)
            # ------------------------------------------------------
            direccion = str(op.get('direccion', '')).upper()
            if direccion in ('COMPRA', 'BUY', 'LONG'):
                features.append(1.0)
            elif direccion in ('VENTA', 'SELL', 'SHORT'):
                features.append(-1.0)
            else:
                features.append(0.0)

            # ------------------------------------------------------
            # 2. SCORES (normalizados 0-1)
            # ------------------------------------------------------
            features.append(self._norm01(op.get('score_h1', 50), 0, 100))
            features.append(self._norm01(op.get('score_m15', 50), 0, 100))
            features.append(self._norm01(op.get('score_m5', 50), 0, 100))
            features.append(self._norm01(op.get('score_final', 50), 0, 100))

            # ------------------------------------------------------
            # 3. COMPONENTES DEL SCORE H1
            # ------------------------------------------------------
            features.append(self._norm01(op.get('pts_estructura', 0), 0, 35))
            features.append(self._norm01(op.get('pts_momentum', 0), 0, 35))
            features.append(self._norm01(op.get('pts_confluencia', 0), 0, 35))
            features.append(self._norm01(op.get('pts_institucional', 0), 0, 35))

            # ------------------------------------------------------
            # 4. INDICADORES TÉCNICOS
            # ------------------------------------------------------
            # ADX normalizado (0-50)
            features.append(self._norm01(op.get('adx', 0), 0, 50))
            # RSI centrado (-1 a 1)
            rsi = float(op.get('rsi', 50))
            features.append((rsi - 50.0) / 50.0)
            # Volumen relativo (cap a 5x)
            features.append(min(5.0, float(op.get('volumen_relativo', 1.0))) / 5.0)
            # ATR normalizado (cap a 5%)
            features.append(min(5.0, float(op.get('atr_pct', 0.5))) / 5.0)

            # ------------------------------------------------------
            # 5. NIVELES
            # ------------------------------------------------------
            # Distancia al nivel (0 = encima, 1 = lejos)
            distancia = float(op.get('distancia_nivel_pips', 100))
            features.append(min(100.0, distancia) / 100.0)
            # ¿En nivel clave?
            features.append(1.0 if op.get('en_nivel_clave') else 0.0)
            # Hits del nivel (cap a 10)
            features.append(min(10.0, float(op.get('soporte_hits', 0) + op.get('resistencia_hits', 0))) / 10.0)

            # ------------------------------------------------------
            # 6. PATRONES Y ESTRUCTURA
            # ------------------------------------------------------
            features.append(self._norm01(op.get('patron_calidad', 0), 0, 100))
            features.append(1.0 if op.get('ob_cercano') else 0.0)
            features.append(self._norm01(op.get('wyckoff_confianza', 0), 0, 100))

            # Divergencias
            div_rsi = str(op.get('divergencia_rsi', '') or '').upper()
            features.append(1.0 if div_rsi == 'BULLISH' else 0.0)
            features.append(1.0 if div_rsi == 'BEARISH' else 0.0)

            div_macd = str(op.get('divergencia_macd', '') or '').upper()
            features.append(1.0 if div_macd == 'BULLISH' else 0.0)
            features.append(1.0 if div_macd == 'BEARISH' else 0.0)

            # ------------------------------------------------------
            # 7. DETECCIÓN DE MANIPULACIÓN (V10.1)
            # ------------------------------------------------------
            features.append(1.0 if op.get('stop_hunt_detectado') else 0.0)
            features.append(1.0 if op.get('rechazo_confirmado') else 0.0)

            # ------------------------------------------------------
            # 8. ONE-HOT: RÉGIMEN
            # ------------------------------------------------------
            regimen = str(op.get('regimen', 'INCERTO')).upper()
            for r in REGIMENES:
                features.append(1.0 if regimen == r else 0.0)

            # ------------------------------------------------------
            # 9. ONE-HOT: MODO
            # ------------------------------------------------------
            modo = str(op.get('modo', '')).upper()
            for m in MODOS:
                features.append(1.0 if modo == m else 0.0)

            # ------------------------------------------------------
            # 10. ONE-HOT: SESIÓN (según hora de la operación)
            # ------------------------------------------------------
            sesion = self._inferir_sesion(op.get('timestamp'))
            for s in SESIONES:
                features.append(1.0 if sesion == s else 0.0)

            # ------------------------------------------------------
            # 11. ONE-HOT: CALIDAD HORARIO
            # ------------------------------------------------------
            calidad = str(op.get('calidad_horario', 'REGULAR')).upper()
            for c in CALIDAD_HORARIO:
                features.append(1.0 if calidad == c else 0.0)

            # ------------------------------------------------------
            # 12. ONE-HOT: WYCKOFF
            # ------------------------------------------------------
            wyckoff = str(op.get('wyckoff_fase', 'NEUTRAL')).upper()
            for w in WYCKOFF_FASES:
                features.append(1.0 if wyckoff == w else 0.0)

            # ------------------------------------------------------
            # 13. CICLICIDAD TEMPORAL (hora + día)
            # ------------------------------------------------------
            hora_norm, dia_sin, dia_cos = self._codificacion_ciclica(op.get('timestamp'))
            features.append(hora_norm)   # 0-1
            features.append(dia_sin)     # -1 a 1
            features.append(dia_cos)     # -1 a 1

            # ------------------------------------------------------
            # 14. CONTEXTO H1 vs M15
            # ------------------------------------------------------
            # ¿La dirección H1 y M15 coinciden?
            dir_h1 = str(op.get('direccion', '')).upper()
            dir_m15 = str(op.get('direccion_m15', 'NEUTRAL')).upper()
            features.append(1.0 if dir_h1 == dir_m15 else 0.0)
            features.append(1.0 if dir_m15 == 'NEUTRAL' else 0.0)

            # ------------------------------------------------------
            # 15. RR Y RIESGO
            # ------------------------------------------------------
            rr = float(op.get('rr', 1.0))
            features.append(min(5.0, max(0.0, rr)) / 5.0)
            features.append(self._norm01(op.get('confianza_regimen', 0), 0, 100))

            # ------------------------------------------------------
            # Validar
            # ------------------------------------------------------
            arr = np.array(features, dtype=np.float32)
            if not np.all(np.isfinite(arr)):
                self.logger.warning(f"⚠️ Features con NaN/inf en {op.get('simbolo', '?')}")
                arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)

            return arr

        except Exception as e:
            self.logger.error(f"❌ Error extrayendo features: {e}", exc_info=True)
            return None

    def nombres_features(self) -> List[str]:
        """Retorna los nombres de las features en orden."""
        if self._nombres_cache is not None:
            return self._nombres_cache

        nombres = [
            'direccion',
            'score_h1', 'score_m15', 'score_m5', 'score_final',
            'pts_estructura', 'pts_momentum', 'pts_confluencia', 'pts_institucional',
            'adx_norm', 'rsi_centrado', 'volumen_rel', 'atr_norm',
            'distancia_nivel', 'en_nivel_clave', 'hits_nivel',
            'patron_calidad', 'ob_cercano', 'wyckoff_confianza',
            'div_rsi_bull', 'div_rsi_bear', 'div_macd_bull', 'div_macd_bear',
            'stop_hunt', 'rechazo_confirmado',
        ]
        nombres += [f'reg_{r}' for r in REGIMENES]
        nombres += [f'modo_{m}' for m in MODOS]
        nombres += [f'sesion_{s}' for s in SESIONES]
        nombres += [f'calidad_{c}' for c in CALIDAD_HORARIO]
        nombres += [f'wyckoff_{w}' for w in WYCKOFF_FASES]
        nombres += ['hora_norm', 'dia_sin', 'dia_cos']
        nombres += ['h1_m15_coinciden', 'm15_neutral']
        nombres += ['rr_norm', 'confianza_regimen']

        self._nombres_cache = nombres
        return nombres

    def n_features(self) -> int:
        """Retorna el número total de features."""
        return len(self.nombres_features())

    # ============================================================
    # HELPERS
    # ============================================================

    def _norm01(self, valor: Any, min_v: float, max_v: float) -> float:
        try:
            v = float(valor)
        except (ValueError, TypeError):
            return 0.0
        if max_v <= min_v:
            return 0.0
        return max(0.0, min(1.0, (v - min_v) / (max_v - min_v)))

    def _inferir_sesion(self, timestamp: Any) -> str:
        """Infiere la sesión desde el timestamp."""
        try:
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            elif isinstance(timestamp, datetime):
                dt = timestamp
            else:
                return 'LONDON'
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hora = dt.astimezone(timezone.utc).hour + dt.minute / 60.0
        except Exception:
            return 'LONDON'

        # Cripto: siempre
        # Rangos UTC
        if 0 <= hora < 8:
            return 'ASIAN'
        if 13 <= hora < 16:
            return 'OVERLAP_LDN_NY'
        if 8 <= hora < 16:
            return 'LONDON'
        if 16 <= hora < 22:
            return 'NEW_YORK'
        return 'ASIAN'

    def _codificacion_ciclica(self, timestamp: Any) -> tuple:
        """Codificación cíclica de hora y día (para que el modelo vea continuidad)."""
        try:
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            elif isinstance(timestamp, datetime):
                dt = timestamp
            else:
                dt = datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)

        # Hora: 0-24 → 0-1
        hora_norm = (dt.hour + dt.minute / 60.0) / 24.0

        # Día: 0-6 → sin/cos (para que sábado y domingo sean "cercanos")
        angulo = 2 * math.pi * dt.weekday() / 7.0
        dia_sin = math.sin(angulo)
        dia_cos = math.cos(angulo)

        return hora_norm, dia_sin, dia_cos