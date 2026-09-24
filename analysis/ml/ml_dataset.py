#!/usr/bin/env python3
"""
analysis/ml/ml_dataset.py (V2.0 - NUEVO)
Construcción del dataset de entrenamiento del ML.

OBJETIVO:
Extraer, limpiar y balancear operaciones reales cerradas para entrenar
el modelo. NO usar operaciones simuladas.

FILOSOFÍA:
- Solo operaciones CERRADAS y con resultado conocido
- Excluir operaciones con comisiones > ganancia bruta
- Balancear clases (más perdedoras que ganadoras naturalmente)
- Persistir el dataset para auditoría
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

from .ml_features import FeatureExtractor

logger = logging.getLogger('BotTrading.ML.Dataset')


# ============================================================
# CONFIGURACIÓN
# ============================================================

MIN_OPERACIONES_PARA_ENTRENAR = 30        # Mínimo para considerar entrenamiento
MIN_GANADORAS_PARA_ENTRENAR = 5           # Mínimo de positivas
MIN_PERDEDORAS_PARA_ENTRENAR = 5          # Mínimo de negativas
MAX_RATIO_DESBALANCE = 0.4                # Máx 40% vs 60% entre clases
LOOKBACK_DIAS_DEFAULT = 180               # Solo últimos 6 meses
OUTLIER_SIGMAS = 4.0                       # Excluir operaciones extremas (>4σ)
MIN_PNL_ABS = 0.01                         # Ignorar operaciones casi nulas


# ============================================================
# CONSTRUCTOR DE DATASET
# ============================================================

class DatasetBuilder:
    """
    Construye el dataset de entrenamiento desde operaciones reales.
    """

    def __init__(self, feature_extractor: Optional[FeatureExtractor] = None):
        self.extractor = feature_extractor or FeatureExtractor()
        self.logger = logging.getLogger('BotTrading.ML.Dataset')

    # ============================================================
    # API PÚBLICA
    # ============================================================

    def construir(
        self,
        operaciones: List[Dict[str, Any]],
        lookback_dias: int = LOOKBACK_DIAS_DEFAULT,
        balancear: bool = True,
    ) -> Optional[Tuple[np.ndarray, np.ndarray, List[str]]]:
        """
        Construye X (features), y (target) desde operaciones.

        Args:
            operaciones: Lista de operaciones cerradas
            lookback_dias: Solo considerar operaciones recientes
            balancear: Balancear clases (subsampling)

        Returns:
            (X, y, nombres_features) o None si insuficientes datos
        """
        if not operaciones:
            self.logger.warning("⚠️ Sin operaciones para construir dataset")
            return None

        # 1. Filtrar operaciones válidas
        filtradas = self._filtrar_operaciones(operaciones, lookback_dias)
        if len(filtradas) < MIN_OPERACIONES_PARA_ENTRENAR:
            self.logger.info(
                f"⚠️ Operaciones insuficientes: {len(filtradas)} < {MIN_OPERACIONES_PARA_ENTRENAR}"
            )
            return None

        # 2. Extraer features + target
        X_list, y_list, meta_list = self._extraer_matrices(filtradas)

        if len(X_list) < MIN_OPERACIONES_PARA_ENTRENAR:
            self.logger.warning(f"⚠️ Solo {len(X_list)} features extraídas")
            return None

        X = np.vstack(X_list)
        y = np.array(y_list, dtype=np.int32)

        # 3. Verificar balance
        n_pos = int(np.sum(y == 1))
        n_neg = int(np.sum(y == 0))

        if n_pos < MIN_GANADORAS_PARA_ENTRENAR or n_neg < MIN_PERDEDORAS_PARA_ENTRENAR:
            self.logger.warning(
                f"⚠️ Balance insuficiente: {n_pos} ganadoras, {n_neg} perdedoras"
            )
            return None

        # 4. Balancear si aplica
        if balancear:
            X, y = self._balancear(X, y)

        # 5. Remover outliers (por retorno muy extremo)
        X, y = self._remover_outliers_pnl(X, y, meta_list)

        self.logger.info(
            f"✅ Dataset construido: X={X.shape}, "
            f"positivas={int(np.sum(y == 1))}, "
            f"negativas={int(np.sum(y == 0))}"
        )

        return X, y, self.extractor.nombres_features()

    def guardar_dataset(
        self,
        X: np.ndarray,
        y: np.ndarray,
        nombres: List[str],
        ruta: str,
    ):
        """Guarda el dataset para auditoría."""
        try:
            df = pd.DataFrame(X, columns=nombres)
            df['target'] = y
            df.to_csv(ruta, index=False)
            self.logger.info(f"💾 Dataset guardado: {ruta} ({len(df)} filas)")
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando dataset: {e}")

    # ============================================================
    # FILTRADO
    # ============================================================

    def _filtrar_operaciones(
        self,
        operaciones: List[Dict],
        lookback_dias: int,
    ) -> List[Dict]:
        """Filtra operaciones aptas para entrenamiento."""
        ahora = datetime.now(timezone.utc)
        cutoff = ahora - timedelta(days=lookback_dias)

        filtradas = []
        for op in operaciones:
            # Debe estar cerrada
            if op.get('estado') != 'CERRADA':
                continue

            # Debe tener ganancia conocida
            ganancia = op.get('ganancia_neta')
            if ganancia is None:
                continue
            try:
                ganancia = float(ganancia)
            except (ValueError, TypeError):
                continue

            # Ignorar operaciones casi nulas
            if abs(ganancia) < MIN_PNL_ABS:
                continue

            # Debe ser reciente
            ts = self._parse_ts(op.get('timestamp') or op.get('timestamp_salida'))
            if ts and ts < cutoff:
                continue

            # Debe tener dirección conocida
            if not op.get('direccion') or op.get('direccion') not in ('COMPRA', 'VENTA'):
                continue

            filtradas.append(op)

        return filtradas

    def _parse_ts(self, valor) -> Optional[datetime]:
        if isinstance(valor, datetime):
            return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
        if isinstance(valor, str):
            try:
                dt = datetime.fromisoformat(valor.replace('Z', '+00:00'))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        return None

    # ============================================================
    # EXTRACCIÓN
    # ============================================================

    def _extraer_matrices(
        self,
        operaciones: List[Dict],
    ) -> Tuple[List[np.ndarray], List[int], List[Dict]]:
        """Extrae features + target."""
        X_list: List[np.ndarray] = []
        y_list: List[int] = []
        meta_list: List[Dict] = []

        for op in operaciones:
            # Extraer features
            features = self.extractor.extraer(op)
            if features is None:
                continue

            # Target: ganancia > 0 → 1, else 0
            ganancia = float(op.get('ganancia_neta', 0))
            target = 1 if ganancia > 0 else 0

            X_list.append(features)
            y_list.append(target)
            meta_list.append({
                'simbolo': op.get('simbolo', '?'),
                'ganancia': ganancia,
                'timestamp': op.get('timestamp'),
            })

        return X_list, y_list, meta_list

    # ============================================================
    # BALANCEO
    # ============================================================

    def _balancear(self, X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Balancea clases por subsampling de la mayoritaria.
        NO sobremuestrea (evita overfitting).
        """
        n_pos = int(np.sum(y == 1))
        n_neg = int(np.sum(y == 0))

        if n_pos == 0 or n_neg == 0:
            return X, y

        ratio = min(n_pos, n_neg) / max(n_pos, n_neg)

        # Si el balance es aceptable, dejar como está
        if ratio >= MAX_RATIO_DESBALANCE:
            return X, y

        # Subsamplear la clase mayoritaria
        objetivo = min(n_pos, n_neg)

        pos_idx = np.where(y == 1)[0]
        neg_idx = np.where(y == 0)[0]

        if n_pos > n_neg:
            seleccionados_pos = np.random.choice(pos_idx, size=objetivo, replace=False)
            seleccionados = np.concatenate([seleccionados_pos, neg_idx])
        else:
            seleccionados_neg = np.random.choice(neg_idx, size=objetivo, replace=False)
            seleccionados = np.concatenate([pos_idx, seleccionados_neg])

        np.random.shuffle(seleccionados)
        return X[seleccionados], y[seleccionados]

    # ============================================================
    # OUTLIERS
    # ============================================================

    def _remover_outliers_pnl(
        self,
        X: np.ndarray,
        y: np.ndarray,
        meta: List[Dict],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Remueve operaciones con PnL extremo (outliers).
        Estos suelen ser slippage, gaps, errores de ejecución.
        """
        if not meta or len(meta) != len(y):
            return X, y

        ganancias = np.array([m.get('ganancia', 0) for m in meta], dtype=np.float64)

        if len(ganancias) < 10:
            return X, y

        media = np.mean(ganancias)
        std = np.std(ganancias)

        if std <= 0:
            return X, y

        # Mantener los que estén dentro del rango
        umbral = OUTLIER_SIGMAS * std
        mask = np.abs(ganancias - media) <= umbral

        X_filtrado = X[mask]
        y_filtrado = y[mask]

        eliminados = len(y) - len(y_filtrado)
        if eliminados > 0:
            self.logger.info(f"🧹 Eliminados {eliminados} outliers de PnL")

        return X_filtrado, y_filtrado