#!/usr/bin/env python3
"""Módulo de backtesting del bot."""

# Importaciones diferidas (los módulos se crean en bloques posteriores)
__all__ = [
    'BacktesterV10',
    'ConectorSimulado',
    'MetricasBacktest',
    'Telemetria',
]


def __getattr__(name):
    """Importación perezosa."""
    if name == 'BacktesterV10':
        from .backtester_v10 import BacktesterV10
        return BacktesterV10
    if name == 'ConectorSimulado':
        from .conector_simulado import ConectorSimulado
        return ConectorSimulado
    if name == 'MetricasBacktest':
        from .metricas import MetricasBacktest
        return MetricasBacktest
    if name == 'Telemetria':
        from .telemetria import Telemetria
        return Telemetria
    raise AttributeError(f"module 'backtesting' has no attribute '{name}'")