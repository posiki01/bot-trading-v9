#!/usr/bin/env python3
"""
analysis/ml/ml_drift.py (V2.0 - DRIFT HONESTO)
Detección de drift basada en performance REAL del modelo.

NO USAR MSE de scores ficticios. Usar:
- Win rate reciente del modelo vs histórico
- Divergencia de distribución de probabilidades
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger('BotTrading.ML.Drift')


class DriftDetector:
    """
    Detector de drift con criterios honestos.

    CRITERIOS:
    1. Si el modelo predice > 0.6 de prob pero la operación pierde → BAD
    2. Si la tasa de aciertos reciente < 45% y el modelo dice > 60% → DRIFT
    3. Si la calibración (prob media vs win rate real) diverge mucho → DRIFT
    """

    VENTANA_OPS = 30              # Últimas N operaciones
    MIN_OPS_PARA_EVALUAR = 15
    UMBRAL_DIVERGENCIA = 0.20     # 20% de divergencia → drift
    PROB_ALTA = 0.60
    PROB_BAJA = 0.40

    def __init__(self):
        self.logger = logging.getLogger('BotTrading.ML.Drift')

    # ============================================================
    # API PRINCIPAL
    # ============================================================

    def detectar(
        self,
        operaciones: List[Dict[str, Any]],
        predictor: Any,
    ) -> bool:
        """
        Detecta drift comparando predicciones del modelo con resultados reales.

        Args:
            operaciones: Lista de operaciones cerradas recientes (con contexto)
            predictor: PredictorML cargado

        Returns:
            True si hay drift
        """
        if not predictor.tiene_modelo():
            return False

        if len(operaciones) < self.MIN_OPS_PARA_EVALUAR:
            return False

        # Últimas N operaciones
        recientes = operaciones[-self.VENTANA_OPS:]

        # Recopilar: prob predicha vs resultado real
        probs = []
        resultados = []

        extractor = predictor.extractor

        for op in recientes:
            # Solo operaciones cerradas
            if op.get('estado') != 'CERRADA':
                continue

            ganancia = op.get('ganancia_neta')
            if ganancia is None:
                continue

            try:
                ganancia = float(ganancia)
            except (ValueError, TypeError):
                continue

            # Extraer features
            if extractor is None:
                continue

            features = extractor.extraer(op)
            if features is None:
                continue

            prob = predictor.predecir(features)
            if prob is None:
                continue

            probs.append(prob)
            resultados.append(1 if ganancia > 0 else 0)

        if len(probs) < self.MIN_OPS_PARA_EVALUAR:
            self.logger.debug(f"⚠️ Insuficientes predicciones válidas: {len(probs)}")
            return False

        probs = np.array(probs)
        resultados = np.array(resultados)

        # ============================================================
        # Criterio 1: Calibración
        # ============================================================
        prob_media = float(np.mean(probs))
        win_rate_real = float(np.mean(resultados))
        divergencia = abs(prob_media - win_rate_real)

        if divergencia > self.UMBRAL_DIVERGENCIA:
            self.logger.warning(
                f"🌊 DRIFT (calibración): prob_media={prob_media:.3f} "
                f"vs win_rate={win_rate_real:.3f} (div={divergencia:.3f})"
            )
            return True

        # ============================================================
        # Criterio 2: Aciertos cuando el modelo está muy seguro
        # ============================================================
        mask_alta = probs >= self.PROB_ALTA
        if np.sum(mask_alta) >= 5:
            win_rate_alta = float(np.mean(resultados[mask_alta]))
            if win_rate_alta < 0.40:
                self.logger.warning(
                    f"🌊 DRIFT (alta confianza falla): "
                    f"prob>{self.PROB_ALTA} → win_rate={win_rate_alta:.3f}"
                )
                return True

        # ============================================================
        # Criterio 3: Rechazos cuando el modelo está seguro de perder
        # ============================================================
        mask_baja = probs <= self.PROB_BAJA
        if np.sum(mask_baja) >= 5:
            win_rate_baja = float(np.mean(resultados[mask_baja]))
            if win_rate_baja > 0.65:
                self.logger.warning(
                    f"🌊 DRIFT (rechazos ganadores): "
                    f"prob<{self.PROB_BAJA} → win_rate={win_rate_baja:.3f}"
                )
                return True

        self.logger.debug(
            f"✅ Sin drift: prob_media={prob_media:.3f}, "
            f"win_rate={win_rate_real:.3f}, n={len(probs)}"
        )
        return False

    def obtener_metricas(self, operaciones: List[Dict], predictor: Any) -> Dict[str, Any]:
        """Obtiene métricas de calibración sin decidir drift."""
        if not predictor.tiene_modelo() or len(operaciones) < self.MIN_OPS_PARA_EVALUAR:
            return {'n': 0}

        extractor = predictor.extractor
        probs = []
        resultados = []

        for op in operaciones[-self.VENTANA_OPS:]:
            if op.get('estado') != 'CERRADA':
                continue
            try:
                ganancia = float(op.get('ganancia_neta', 0))
            except (ValueError, TypeError):
                continue

            features = extractor.extraer(op) if extractor else None
            if features is None:
                continue
            prob = predictor.predecir(features)
            if prob is None:
                continue

            probs.append(prob)
            resultados.append(1 if ganancia > 0 else 0)

        if len(probs) < 5:
            return {'n': len(probs)}

        probs = np.array(probs)
        resultados = np.array(resultados)

        return {
            'n': len(probs),
            'prob_media': float(np.mean(probs)),
            'win_rate_real': float(np.mean(resultados)),
            'divergencia': float(abs(np.mean(probs) - np.mean(resultados))),
        }