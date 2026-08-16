#!/usr/bin/env python3
"""
backtesting/__init__.py (V9.0)
Módulo de backtesting - Simulación y análisis de estrategias.
"""

from .backtesting_engine_v2 import BacktesterV2, create_backtester

__all__ = [
    'BacktesterV2',
    'create_backtester',
]