#!/usr/bin/env python3
"""
analysis/ml/__init__.py (V9.0)
Módulo de Machine Learning.
"""

# Importar desde ml_optimizer.py
from .ml_optimizer import MLOptimizer, create_ml_optimizer

# También importar los submódulos si existen
try:
    from .ml_entrenamiento import EntrenadorML
except ImportError:
    EntrenadorML = None

try:
    from .ml_surrogate import SurrogateTrader
except ImportError:
    SurrogateTrader = None

try:
    from .ml_mining import HardNegativeMiner
except ImportError:
    HardNegativeMiner = None

__all__ = [
    'MLOptimizer',
    'create_ml_optimizer',
    'EntrenadorML',
    'SurrogateTrader',
    'HardNegativeMiner',
]