# backtesting/__init__.py - VERSIÓN SIMPLIFICADA

#!/usr/bin/env python3
"""Módulo de backtesting - Simulación y análisis de estrategias."""

# Importar solo lo que existe
from .backtesting_engine_v2 import BacktesterV2

# Si create_backtester no existe, crearlo aquí
def create_backtester(config, simbolos, capital_inicial=300.0, **kwargs):
    """Crea una instancia del backtester."""
    return BacktesterV2(
        config=config,
        simbolos=simbolos,
        capital_inicial=capital_inicial,
        **kwargs
    )

__all__ = [
    'BacktesterV2',
    'create_backtester',
]