#!/usr/bin/env python3
"""
analysis/ml/ml_prediccion.py (V2.0 - INFERENCIA)
Predicción de probabilidad de ganar usando el modelo entrenado.
"""

import logging
from typing import Dict, Any, Optional, List
import numpy as np

from .ml_features import FeatureExtractor

logger = logging.getLogger('BotTrading.ML.Prediccion')


class PredictorML:
    """
    Predictor de probabilidad de ganar.

    USO:
        predictor = PredictorML()
        predictor.set_modelo(modelo, extractor)
        prob = predictor.predecir(features)  # → float en [0,1]
    """

    def __init__(self):
        self.modelo = None
        self.extractor: Optional[FeatureExtractor] = None
        self._n_features_esperadas: Optional[int] = None
        self.logger = logging.getLogger('BotTrading.ML.Prediccion')

    # ============================================================
    # MODELO
    # ============================================================

    def set_modelo(self, modelo: Any, extractor: FeatureExtractor):
        """Establece el modelo y extractor."""
        self.modelo = modelo
        self.extractor = extractor
        if extractor is not None:
            self._n_features_esperadas = extractor.n_features()
        self.logger.info("✅ Modelo cargado en PredictorML")

    def cargar_modelo(self, modelo_data: Dict[str, Any], extractor: FeatureExtractor):
        """Carga modelo desde dict (resultado de MLCache.cargar_modelo)."""
        modelo = modelo_data.get('modelo')
        if modelo is not None:
            self.set_modelo(modelo, extractor)

    def tiene_modelo(self) -> bool:
        """Verifica si hay modelo cargado."""
        return self.modelo is not None

    # ============================================================
    # PREDICCIÓN
    # ============================================================

    def predecir(self, features: np.ndarray) -> Optional[float]:
        """
        Predice la probabilidad de que la operación sea ganadora.

        Args:
            features: Vector de features (1D array)

        Returns:
            Probabilidad en [0, 1] o None si error
        """
        if self.modelo is None:
            return None

        try:
            # Asegurar 2D
            if features.ndim == 1:
                features = features.reshape(1, -1)

            # Validar dimensión
            if self._n_features_esperadas is not None:
                if features.shape[1] != self._n_features_esperadas:
                    self.logger.error(
                        f"❌ Dimensión incorrecta: {features.shape[1]} != "
                        f"{self._n_features_esperadas}"
                    )
                    return None

            # Predecir
            probs = self.modelo.predict_proba(features)

            # Encontrar el índice de la clase 1
            if probs.shape[1] == 2:
                prob_positiva = float(probs[0, 1])
            else:
                # Modelo raro: usar el máximo
                prob_positiva = float(np.max(probs[0]))

            # Sanity check
            if not (0.0 <= prob_positiva <= 1.0):
                self.logger.warning(f"⚠️ Probabilidad fuera de rango: {prob_positiva}")
                prob_positiva = max(0.0, min(1.0, prob_positiva))

            return prob_positiva

        except Exception as e:
            self.logger.error(f"❌ Error en predicción: {e}", exc_info=True)
            return None

    def predecir_batch(self, X: np.ndarray) -> Optional[np.ndarray]:
        """Predice en lote."""
        if self.modelo is None:
            return None
        try:
            if X.ndim == 1:
                X = X.reshape(1, -1)
            probs = self.modelo.predict_proba(X)
            if probs.shape[1] == 2:
                return probs[:, 1]
            return probs.max(axis=1)
        except Exception as e:
            self.logger.error(f"❌ Error en predicción batch: {e}")
            return None