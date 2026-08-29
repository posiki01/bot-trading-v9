#!/usr/bin/env python3
"""Módulo de sniper - Validación y ejecución de entradas."""

# Importar desde sniper_checklist.py (no desde un subdirectorio)
from .sniper_checklist import SniperChecklist, create_sniper_checklist

# Importar submódulos si existen
try:
    from .sniper_validacion import SniperValidador
except ImportError:
    SniperValidador = None

try:
    from .sniper_modos import DetectorModos, ModoEntrada
except ImportError:
    DetectorModos = None
    ModoEntrada = None

try:
    from .sniper_sl_tp import CalculadorSLTP
except ImportError:
    CalculadorSLTP = None

try:
    from .sniper_scoring import CalculadorScoreSniper
except ImportError:
    CalculadorScoreSniper = None

try:
    from .sniper_quality import ValidadorCalidad
except ImportError:
    ValidadorCalidad = None

__all__ = [
    'SniperChecklist',
    'create_sniper_checklist',
    'SniperValidador',
    'DetectorModos',
    'ModoEntrada',
    'CalculadorSLTP',
    'CalculadorScoreSniper',
    'ValidadorCalidad',
]