#!/usr/bin/env python3
"""
Módulo de Machine Learning para el bot (V2.0 - APRENDIZAJE REAL).

CAMBIOS V2.0:
- ✅ El ML ahora aprende de operaciones REALES del bot
- ✅ Features ricas (contexto completo del setup)
- ✅ Target honesto (¿fue ganadora?)
- ✅ Walk-forward temporal (sin data leakage)
- ✅ Calibración de probabilidades
- ✅ Predicción de probabilidad + expectancy

ARQUITECTURA:
    ml_features.py   → Feature engineering (contexto → vector)
    ml_dataset.py    → Construcción del dataset (operaciones → X, y)
    ml_entrenamiento.py → Entrenamiento + validación walk-forward
    ml_prediccion.py → Inferencia (probabilidad de ganar)
    ml_drift.py      → Detección de degradación
    ml_persistencia.py → Persistencia (mantiene)
    ml_optimizer.py  → Orquestación del ciclo completo
"""

from .ml_optimizer import MLOptimizer, create_ml_optimizer
from .ml_entrenamiento import EntrenadorML
from .ml_features import FeatureExtractor
from .ml_dataset import DatasetBuilder
from .ml_prediccion import PredictorML
from .ml_drift import DriftDetector
from .ml_persistencia import MLCache

__all__ = [
    'MLOptimizer',
    'create_ml_optimizer',
    'EntrenadorML',
    'FeatureExtractor',
    'DatasetBuilder',
    'PredictorML',
    'DriftDetector',
    'MLCache',
]