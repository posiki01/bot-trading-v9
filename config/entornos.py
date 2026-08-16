#!/usr/bin/env python3
"""
config/entornos.py (V9.0)
Configuración específica por entorno (desarrollo, producción, backtest).
"""

from typing import Dict, Any


class EntornoDesarrollo:
    """Configuración para entorno de desarrollo."""
    
    NOMBRE = "DESARROLLO"
    
    # Capital
    CAPITAL_INICIAL = 1000.0
    APORTE_MENSUAL = 0.0
    
    # Riesgo (más conservador)
    MAX_RISK_PER_TRADE_PCT = 0.005  # 0.5%
    MAX_DAILY_DRAWDOWN_PCT = 0.05   # 5%
    MAX_CONSECUTIVE_LOSSES = 2
    
    # Operaciones
    MAX_OPERATIONS_PER_DAY = 5
    MAX_SIMULTANEAS = 2
    
    # Lotes
    MAX_LOTE_ABSOLUTO = 0.02
    MIN_LOTE_ABSOLUTO = 0.01
    
    # Logs
    LOG_LEVEL = 'DEBUG'
    CONSOLE_LOG_LEVEL = 'DEBUG'
    
    # Circuit Breaker
    CIRCUIT_BREAKER_COOLDOWN_HOURS = 1
    
    # Modo backtest
    BACKTEST_MODE = False
    
    # Símbolos (reducidos para desarrollo)
    SIMBOLOS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD']


class EntornoProduccion:
    """Configuración para entorno de producción."""
    
    NOMBRE = "PRODUCCION"
    
    # Capital
    CAPITAL_INICIAL = 10000.0
    APORTE_MENSUAL = 500.0
    
    # Riesgo (estándar)
    MAX_RISK_PER_TRADE_PCT = 0.01   # 1%
    MAX_DAILY_DRAWDOWN_PCT = 0.06   # 6%
    MAX_CONSECUTIVE_LOSSES = 3
    
    # Operaciones
    MAX_OPERATIONS_PER_DAY = 8
    MAX_SIMULTANEAS = 4
    
    # Lotes
    MAX_LOTE_ABSOLUTO = 0.05
    MIN_LOTE_ABSOLUTO = 0.01
    
    # Logs
    LOG_LEVEL = 'INFO'
    CONSOLE_LOG_LEVEL = 'INFO'
    
    # Circuit Breaker
    CIRCUIT_BREAKER_COOLDOWN_HOURS = 24
    
    # Modo backtest
    BACKTEST_MODE = False
    
    # Símbolos (todos)
    SIMBOLOS = None  # Usar los de Config


class EntornoBacktest:
    """Configuración para backtesting."""
    
    NOMBRE = "BACKTEST"
    
    # Capital
    CAPITAL_INICIAL = 1000.0
    APORTE_MENSUAL = 0.0
    
    # Riesgo (más permisivo para pruebas)
    MAX_RISK_PER_TRADE_PCT = 0.015  # 1.5%
    MAX_DAILY_DRAWDOWN_PCT = 0.10   # 10%
    MAX_CONSECUTIVE_LOSSES = 5
    
    # Operaciones
    MAX_OPERATIONS_PER_DAY = 20
    MAX_SIMULTANEAS = 5
    
    # Lotes
    MAX_LOTE_ABSOLUTO = 0.03
    MIN_LOTE_ABSOLUTO = 0.01
    
    # Logs
    LOG_LEVEL = 'DEBUG'
    CONSOLE_LOG_LEVEL = 'INFO'
    
    # Circuit Breaker
    CIRCUIT_BREAKER_COOLDOWN_HOURS = 1
    
    # Modo backtest
    BACKTEST_MODE = True
    
    # Símbolos (todos para backtest)
    SIMBOLOS = None  # Usar los de Config


# Mapeo de entornos
ENTORNOS = {
    'desarrollo': EntornoDesarrollo,
    'produccion': EntornoProduccion,
    'backtest': EntornoBacktest,
}


def obtener_entorno(nombre: str = 'produccion'):
    """Obtiene la configuración de un entorno."""
    return ENTORNOS.get(nombre, EntornoProduccion)