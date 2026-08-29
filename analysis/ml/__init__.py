#!/usr/bin/env python3
"""Módulo de Machine Learning para el bot."""

# ============================================================
# ORQUESTADOR PRINCIPAL
# ============================================================

from .ml_optimizer import MLOptimizer, create_ml_optimizer

# ============================================================
# SUBMÓDULOS (IMPORT CORRECTO)
# ============================================================

from .ml_entrenamiento import EntrenadorML
from .ml_surrogate import SurrogateTrader
from .ml_mining import HardNegativeMiner
from .ml_drift import DriftDetector
from .ml_persistencia import MLCache
from .ml_prediccion import PredictorML

# ============================================================
# EXPORTAR TODO
# ============================================================

__all__ = [
    'MLOptimizer',
    'create_ml_optimizer',
    'EntrenadorML',
    'SurrogateTrader',
    'HardNegativeMiner',
    'DriftDetector',
    'MLCache',
    'PredictorML',
]