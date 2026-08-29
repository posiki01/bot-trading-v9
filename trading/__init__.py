#!/usr/bin/env python3
"""Módulo de trading - Gestión de riesgo, ejecución y sniper."""

# ============================================================
# RIESGO
# ============================================================

from .riesgo import GestionRiesgo, create_gestion_riesgo

# ============================================================
# STOPS
# ============================================================

from .stops import GestorStops, create_gestor_stops

# ============================================================
# TRAILING
# ============================================================

from .trailing import TrailingEngine, create_trailing_engine

# ============================================================
# EJECUCIÓN
# ============================================================

from .ejecucion import EjecutorOperaciones, create_ejecutor_operaciones

# ============================================================
# SNIPER
# ============================================================

from .sniper import SniperChecklist, create_sniper_checklist

# ============================================================
# OPERABILIDAD
# ============================================================

from .operabilidad import DecisorOperabilidad, create_decisor_operabilidad

# ============================================================
# MODOS
# ============================================================

from .modos import ModoSelector, create_modo_selector

# ============================================================
# TIMER
# ============================================================

from .timer import EntryTimer, create_entry_timer

# ============================================================
# SNIPER SUBMÓDULOS (opcionales, para acceso directo)
# ============================================================

try:
    from .sniper import (
        SniperValidador,
        DetectorModos,
        ModoEntrada,
        CalculadorSLTP,
        CalculadorScoreSniper,
        ValidadorCalidad
    )
except ImportError:
    SniperValidador = None
    DetectorModos = None
    ModoEntrada = None
    CalculadorSLTP = None
    CalculadorScoreSniper = None
    ValidadorCalidad = None

# ============================================================
# EXPORTAR TODO
# ============================================================

__all__ = [
    # Riesgo
    'GestionRiesgo',
    'create_gestion_riesgo',
    
    # Stops
    'GestorStops',
    'create_gestor_stops',
    
    # Trailing
    'TrailingEngine',
    'create_trailing_engine',
    
    # Ejecución
    'EjecutorOperaciones',
    'create_ejecutor_operaciones',
    
    # Sniper
    'SniperChecklist',
    'create_sniper_checklist',
    
    # Operabilidad
    'DecisorOperabilidad',
    'create_decisor_operabilidad',
    
    # Modos
    'ModoSelector',
    'create_modo_selector',
    
    # Timer
    'EntryTimer',
    'create_entry_timer',
    
    # Sniper submódulos (opcionales)
    'SniperValidador',
    'DetectorModos',
    'ModoEntrada',
    'CalculadorSLTP',
    'CalculadorScoreSniper',
    'ValidadorCalidad',
]