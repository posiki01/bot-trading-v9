#!/usr/bin/env python3
"""
analysis/ml/ml_entrenamiento.py (V2.0 - APRENDIZAJE REAL)
Entrenamiento del modelo ML con Gradient Boosting + Walk-Forward.

DIFERENCIAS VS V1.0:
- ❌ Antes: Ridge regression sobre 5 features de un score que no refleja la decisión
- ✅ Ahora: Gradient Boosting sobre features RICAS del contexto real
- ❌ Antes: Entrenaba un modelo que predecía un score ficticio
- ✅ Ahora: Predice P(ganadora) directamente
- ❌ Antes: Sin validación temporal
- ✅ Ahora: Walk-forward con TimeSeriesSplit

MODELO:
- HistGradientBoostingClassifier (rápido, robusto, buena con poco dato)
- Calibración con IsotonicRegression
- Umbral de decisión ajustable
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (
    roc_auc_score, accuracy_score, precision_score, recall_score, f1_score,
    brier_score_loss, log_loss,
)

logger = logging.getLogger('BotTrading.ML.Entrenamiento')


# ============================================================
# CONFIGURACIÓN
# ============================================================

MIN_MUESTRAS_HARD = 30            # Por debajo, no entrenar nunca
MIN_MUESTRAS_OPTIMO = 100         # A partir de aquí, umbrales más exigentes
MIN_ROC_AUC = 0.52                # Mínimo para considerar el modelo útil
MIN_ACCURACY = 0.52
MAX_BRIER = 0.28                  # Brier score máximo (0=perfecto, 0.25=random)

# Pesos de muestra (operaciones recientes pesan más)
DECAY_FACTOR = 0.995              # Factor de decaimiento por operación


# ============================================================
# ENTRENADOR
# ============================================================

class EntrenadorML:
    """
    Entrenador con Gradient Boosting + validación walk-forward.
    """

    def __init__(
        self,
        modo_backtest: bool = False,
        calibrar: bool = True,
        random_state: int = 42,
    ):
        self.modo_backtest = modo_backtest
        self.calibrar = calibrar
        self.random_state = random_state
        self.logger = logging.getLogger('BotTrading.ML.Entrenamiento')

        self._ultimo_modelo = None
        self._ultimas_metricas: Dict[str, Any] = {}

    # ============================================================
    # API PÚBLICA
    # ============================================================

    def ejecutar(
        self,
        X: np.ndarray,
        y: np.ndarray,
        nombres_features: Optional[List[str]] = None,
        forzado: bool = False,
    ) -> Dict[str, Any]:
        """
        Entrena el modelo con validación walk-forward.

        Args:
            X: Features (n_muestras, n_features)
            y: Labels (0=perdedora, 1=ganadora)
            nombres_features: Para logging
            forzado: Entrenar aunque no cumpla umbrales

        Returns:
            Dict con:
                'exito': bool
                'modelo': modelo entrenado (o None)
                'metricas': dict con AUC, accuracy, brier, etc.
                'razon': motivo de fallo (si exito=False)
        """
        # 1. Validaciones
        if X is None or y is None or len(X) == 0:
            return self._fallo("Sin datos")

        if len(X) != len(y):
            return self._fallo(f"X y Y desalineados: {len(X)} vs {len(y)}")

        n_muestras = len(X)
        n_pos = int(np.sum(y == 1))
        n_neg = int(np.sum(y == 0))

        if n_pos == 0 or n_neg == 0:
            return self._fallo(f"Una clase vacía: pos={n_pos}, neg={n_neg}")

        min_req = MIN_MUESTRAS_HARD if not forzado else 20
        if n_muestras < min_req:
            return self._fallo(f"Muestras insuficientes: {n_muestras} < {min_req}")

        self.logger.info(
            f"🧠 Entrenando modelo: n={n_muestras} (pos={n_pos}, neg={n_neg})"
        )

        # 2. Split temporal (último 20% para test)
        split_idx = max(int(n_muestras * 0.8), n_muestras - 20)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        if len(X_test) < 5:
            X_test = X[-min(10, n_muestras):]
            y_test = y[-min(10, n_muestras):]
            X_train = X[:-len(X_test)]
            y_train = y[:-len(y_test)]

        # 3. Walk-forward cross-validation
        metricas_cv = self._walk_forward(X_train, y_train)

        # 4. Entrenar modelo final
        modelo = self._entrenar_modelo(X_train, y_train)

        if modelo is None:
            return self._fallo("Error entrenando modelo base")

        # 5. Calibrar si aplica
        if self.calibrar and len(X_train) >= 50:
            modelo = self._calibrar_modelo(modelo, X_train, y_train)

        # 6. Evaluar en test
        metricas_test = self._evaluar(modelo, X_test, y_test)

        # 7. Verificar umbrales de calidad
        cumple_umbrales = (
            metricas_test.get('roc_auc', 0) >= MIN_ROC_AUC and
            metricas_test.get('accuracy', 0) >= MIN_ACCURACY and
            metricas_test.get('brier', 1.0) <= MAX_BRIER
        )

        if not cumple_umbrales and not forzado:
            return self._fallo(
                f"Modelo no cumple umbrales: "
                f"AUC={metricas_test.get('roc_auc', 0):.3f} "
                f"Acc={metricas_test.get('accuracy', 0):.3f} "
                f"Brier={metricas_test.get('brier', 1):.3f}"
            )

        # 8. Guardar modelo
        self._ultimo_modelo = modelo
        self._ultimas_metricas = {
            'train': metricas_cv,
            'test': metricas_test,
            'n_muestras': n_muestras,
            'n_pos': n_pos,
            'n_neg': n_neg,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

        self.logger.info(
            f"✅ Modelo entrenado | "
            f"AUC={metricas_test.get('roc_auc', 0):.3f} "
            f"Acc={metricas_test.get('accuracy', 0):.3f} "
            f"Brier={metricas_test.get('brier', 1):.3f}"
        )

        return {
            'exito': True,
            'modelo': modelo,
            'metricas': self._ultimas_metricas,
            'n_features': X.shape[1],
            'n_muestras': n_muestras,
        }

    def obtener_ultimo_modelo(self):
        return self._ultimo_modelo

    def obtener_metricas(self) -> Dict[str, Any]:
        return self._ultimas_metricas.copy()

    # ============================================================
    # WALK-FORWARD
    # ============================================================

    def _walk_forward(self, X: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
        """Evaluación walk-forward con TimeSeriesSplit."""
        try:
            n_splits = min(5, max(2, len(X) // 20))
            tscv = TimeSeriesSplit(n_splits=n_splits)

            aucs = []
            accs = []
            briers = []

            for train_idx, val_idx in tscv.split(X):
                X_t, X_v = X[train_idx], X[val_idx]
                y_t, y_v = y[train_idx], y[val_idx]

                if len(np.unique(y_t)) < 2 or len(np.unique(y_v)) < 2:
                    continue

                try:
                    modelo = self._entrenar_modelo(X_t, y_t)
                    if modelo is None:
                        continue

                    probs = modelo.predict_proba(X_v)[:, 1]
                    preds = (probs >= 0.5).astype(int)

                    aucs.append(roc_auc_score(y_v, probs))
                    accs.append(accuracy_score(y_v, preds))
                    briers.append(brier_score_loss(y_v, probs))
                except Exception as e:
                    self.logger.debug(f"Fold falló: {e}")
                    continue

            return {
                'auc_mean': float(np.mean(aucs)) if aucs else 0.5,
                'auc_std': float(np.std(aucs)) if aucs else 0.0,
                'acc_mean': float(np.mean(accs)) if accs else 0.5,
                'brier_mean': float(np.mean(briers)) if briers else 0.25,
                'n_folds': len(aucs),
            }
        except Exception as e:
            self.logger.warning(f"⚠️ Error en walk-forward: {e}")
            return {'auc_mean': 0.5, 'acc_mean': 0.5, 'n_folds': 0}

    # ============================================================
    # ENTRENAMIENTO
    # ============================================================

    def _entrenar_modelo(self, X: np.ndarray, y: np.ndarray):
        """Entrena HistGradientBoosting."""
        try:
            modelo = HistGradientBoostingClassifier(
                max_iter=200,
                max_depth=4,
                learning_rate=0.05,
                min_samples_leaf=5,
                l2_regularization=1.0,
                early_stopping=True,
                validation_fraction=0.15,
                n_iter_no_change=20,
                random_state=self.random_state,
            )
            # Pesos por antigüedad (más reciente = más peso)
            n = len(X)
            sample_weight = np.array([DECAY_FACTOR ** (n - i) for i in range(n)])
            sample_weight = sample_weight / sample_weight.sum() * n

            modelo.fit(X, y, sample_weight=sample_weight)
            return modelo
        except Exception as e:
            self.logger.error(f"❌ Error entrenando: {e}")
            return None

    def _calibrar_modelo(self, modelo, X: np.ndarray, y: np.ndarray):
        """Calibra probabilidades con Isotonic."""
        try:
            calibrado = CalibratedClassifierCV(
                modelo,
                method='isotonic',
                cv=3,
            )
            calibrado.fit(X, y)
            return calibrado
        except Exception as e:
            self.logger.debug(f"⚠️ Calibración falló, usando modelo base: {e}")
            return modelo

    # ============================================================
    # EVALUACIÓN
    # ============================================================

    def _evaluar(self, modelo, X: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        """Evalúa el modelo en test."""
        try:
            probs = modelo.predict_proba(X)[:, 1]
            preds = (probs >= 0.5).astype(int)

            metricas = {
                'roc_auc': float(roc_auc_score(y, probs)) if len(np.unique(y)) > 1 else 0.5,
                'accuracy': float(accuracy_score(y, preds)),
                'precision': float(precision_score(y, preds, zero_division=0)),
                'recall': float(recall_score(y, preds, zero_division=0)),
                'f1': float(f1_score(y, preds, zero_division=0)),
                'brier': float(brier_score_loss(y, probs)),
                'log_loss': float(log_loss(y, probs)),
                'mean_prob_pos': float(np.mean(probs[y == 1])) if np.sum(y == 1) > 0 else 0.0,
                'mean_prob_neg': float(np.mean(probs[y == 0])) if np.sum(y == 0) > 0 else 0.0,
                'n_test': int(len(y)),
            }
            return metricas
        except Exception as e:
            self.logger.warning(f"⚠️ Error evaluando: {e}")
            return {'roc_auc': 0.5, 'accuracy': 0.5, 'brier': 0.25}

    # ============================================================
    # HELPERS
    # ============================================================

    def _fallo(self, razon: str) -> Dict[str, Any]:
        self.logger.info(f"⚠️ Entrenamiento fallido: {razon}")
        return {
            'exito': False,
            'modelo': None,
            'razon': razon,
            'metricas': {},
        }