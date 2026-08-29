#!/usr/bin/env python3
"""
tests/conftest.py
Fixtures compartidas para los tests del sniper.
"""

import sys
import os
from pathlib import Path

# ============================================================
# ✅ CRÍTICO: Añadir directorio raíz al PYTHONPATH
# ============================================================

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent

if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

# ============================================================
# IMPORTS PARA FIXTURES
# ============================================================

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# ============================================================
# FIXTURES DE DATOS
# ============================================================

@pytest.fixture
def df_m5_eurusd():
    """Genera datos M5 de EURUSD sintéticos."""
    np.random.seed(42)
    n = 200
    
    fechas = pd.date_range(
        end=datetime.now(timezone.utc),
        periods=n,
        freq='5min',
        tz='UTC'
    )
    
    precio_base = 1.0850
    trend = np.linspace(0, 0.003, n)
    noise = np.random.randn(n) * 0.0005
    
    close = precio_base + trend + noise
    
    df = pd.DataFrame({
        'Open': close - np.random.randn(n) * 0.0002,
        'High': close + np.abs(np.random.randn(n)) * 0.0003,
        'Low': close - np.abs(np.random.randn(n)) * 0.0003,
        'Close': close,
        'Volume': np.random.randint(100, 1000, n)
    }, index=fechas)
    
    df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
    df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
    
    return df

@pytest.fixture
def df_m5_xauusd():
    """Genera datos M5 de XAUUSD sintéticos."""
    np.random.seed(123)
    n = 200
    
    fechas = pd.date_range(
        end=datetime.now(timezone.utc),
        periods=n,
        freq='5min',
        tz='UTC'
    )
    
    precio_base = 2000.0
    trend = np.linspace(0, 5.0, n)
    noise = np.random.randn(n) * 1.5
    
    close = precio_base + trend + noise
    
    df = pd.DataFrame({
        'Open': close - np.random.randn(n) * 0.5,
        'High': close + np.abs(np.random.randn(n)) * 0.8,
        'Low': close - np.abs(np.random.randn(n)) * 0.8,
        'Close': close,
        'Volume': np.random.randint(50, 500, n)
    }, index=fechas)
    
    df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
    df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
    
    return df

@pytest.fixture
def df_m5_btcusd():
    """Genera datos M5 de BTCUSD sintéticos."""
    np.random.seed(456)
    n = 200
    
    fechas = pd.date_range(
        end=datetime.now(timezone.utc),
        periods=n,
        freq='5min',
        tz='UTC'
    )
    
    precio_base = 60000.0
    trend = np.linspace(0, 300.0, n)
    noise = np.random.randn(n) * 100.0
    
    close = precio_base + trend + noise
    
    df = pd.DataFrame({
        'Open': close - np.random.randn(n) * 30,
        'High': close + np.abs(np.random.randn(n)) * 50,
        'Low': close - np.abs(np.random.randn(n)) * 50,
        'Close': close,
        'Volume': np.random.randint(100, 2000, n)
    }, index=fechas)
    
    df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
    df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
    
    return df

@pytest.fixture
def contexto_h1():
    """Contexto H1 para tests."""
    return {
        'score': 65.0,
        'direccion': 'COMPRA',
        'regimen': 'TREND_ALCISTA_FUERTE',
        'en_nivel_clave': True,
        'soporte_cercano': 1.0800,
        'resistencia_cercana': 1.0900,
        'soporte_hits': 3,
        'resistencia_hits': 2,
        'adx': 28.5,
        'rsi': 62.0,
        'patron_principal': 'ENGULFING_ALCISTA',
        'wyckoff_fase': 'ACUMULACION',
        'divergencia_rsi': None,
        'divergencia_macd': None,
        'niveles': {
            'soportes': [
                {'precio': 1.0800, 'hits': 3, 'fuerza': 60},
                {'precio': 1.0750, 'hits': 2, 'fuerza': 40}
            ],
            'resistencias': [
                {'precio': 1.0900, 'hits': 2, 'fuerza': 50},
                {'precio': 1.0950, 'hits': 1, 'fuerza': 30}
            ]
        }
    }

@pytest.fixture
def instancias_sniper(tmp_path):
    """Instancia las dependencias del sniper."""
    try:
        from config.settings import Config
        from analysis.scoring import ScoreEngine
        from analysis.regimen import MarketRegimeFilter
        from analysis.niveles import NivelTracker
        from analysis.pipeline import PipelineOportunidades
        from trading.stops import GestorStops
        from trading.timer import EntryTimer
        from trading.modos import ModoSelector
        from trading.sniper.sniper_checklist import SniperChecklist
    except ImportError as e:
        print(f"❌ Error importando módulos en fixture: {e}")
        raise
    
    config = Config()
    score_engine = ScoreEngine(modo_backtest=True)
    regimen_filter = MarketRegimeFilter(modo_backtest=True)
    nivel_tracker = NivelTracker(modo_backtest=True)
    
    pipeline = PipelineOportunidades(
        config=config,
        umbral_fase_1=30,
        umbral_fase_2=40,
        umbral_fase_3=50,
        modo_backtest=True
    )
    
    gestor_stops = GestorStops(config=config, modo_backtest=True)
    entry_timer = EntryTimer(config=config, modo_backtest=True, modo_depuracion=True)
    modo_selector = ModoSelector(config=config, modo_backtest=True, modo_depuracion=True)
    
    sniper = SniperChecklist(
        pipeline=pipeline,
        analisis_capas=None,
        modo_selector=modo_selector,
        entry_timer=entry_timer,
        gestor_stops=gestor_stops,
        config=config,
        modo_depuracion=True,
        modo_backtest=True
    )
    
    return {
        'config': config,
        'score_engine': score_engine,
        'regimen_filter': regimen_filter,
        'nivel_tracker': nivel_tracker,
        'pipeline': pipeline,
        'gestor_stops': gestor_stops,
        'entry_timer': entry_timer,
        'modo_selector': modo_selector,
        'sniper': sniper
    }