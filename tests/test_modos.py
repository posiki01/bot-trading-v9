#!/usr/bin/env python3
"""
tests/test_modos.py (V1.0)
Valida la selección de modos de entrada.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from trading.modos import ModoSelector, ModoEntrada


class TestModoSelector:
    """Validación del selector de modos."""
    
    def setup_method(self):
        """Configura el selector."""
        self.selector = ModoSelector(
            config=MagicMock(),
            modo_backtest=True,
            modo_depuracion=True
        )
    
    def test_seleccionar_modo_retest_tendencia_alcista(self):
        """Valida selección de RETEST en tendencia alcista."""
        modo, razon, detalles = self.selector.seleccionar_modo(
            simbolo='EURUSD',
            regimen='TREND_ALCISTA_FUERTE',
            direccion='COMPRA',
            score_h1=70.0,
            en_nivel_clave=True,
            volumen_relativo=1.5
        )
        
        assert modo is not None
        assert modo.value in ['RETEST', 'PULLBACK', 'BREAKOUT', 'SNIPER_ELITE']
    
    def test_seleccionar_modo_retest_tendencia_bajista(self):
        """Valida selección de RETEST en tendencia bajista."""
        modo, razon, detalles = self.selector.seleccionar_modo(
            simbolo='EURUSD',
            regimen='TREND_BAJISTA_FUERTE',
            direccion='VENTA',
            score_h1=70.0,
            en_nivel_clave=True,
            volumen_relativo=1.5
        )
        
        assert modo is not None
        assert modo.value in ['RETEST', 'PULLBACK', 'BREAKOUT', 'SNIPER_ELITE']
    
    def test_rechaza_compra_en_tendencia_bajista(self):
        """Valida que rechaza COMPRA en tendencia bajista."""
        modo, razon, detalles = self.selector.seleccionar_modo(
            simbolo='EURUSD',
            regimen='TREND_BAJISTA_FUERTE',
            direccion='COMPRA',
            score_h1=70.0,
            en_nivel_clave=True
        )
        
        assert modo is None
    
    def test_rechaza_venta_en_tendencia_alcista(self):
        """Valida que rechaza VENTA en tendencia alcista."""
        modo, razon, detalles = self.selector.seleccionar_modo(
            simbolo='EURUSD',
            regimen='TREND_ALCISTA_FUERTE',
            direccion='VENTA',
            score_h1=70.0,
            en_nivel_clave=True
        )
        
        assert modo is None
    
    def test_score_minimo_retest(self):
        """Valida el score mínimo para RETEST."""
        score_min = self.selector.obtener_score_minimo(ModoEntrada.RETEST)
        
        assert score_min > 0
    
    def test_obtener_modos_prioritarios(self):
        """Valida la obtención de modos prioritarios."""
        modos = self.selector.obtener_modos_prioritarios('TREND_ALCISTA_FUERTE')
        
        assert isinstance(modos, list)
        assert len(modos) > 0
        assert 'RETEST' in modos
    
    def test_es_modo_valido_para_regimen(self):
        """Valida si un modo es válido para un régimen."""
        es_valido = self.selector.es_modo_valido_para_regimen(
            ModoEntrada.RETEST,
            'TREND_ALCISTA_FUERTE'
        )
        
        assert es_valido is True
    
    def test_seleccionar_modo_neutral(self):
        """Valida que rechaza dirección NEUTRAL."""
        modo, razon, detalles = self.selector.seleccionar_modo(
            simbolo='EURUSD',
            regimen='TREND_ALCISTA_FUERTE',
            direccion='NEUTRAL',
            score_h1=70.0,
            en_nivel_clave=True
        )
        
        assert modo is None
        assert 'NEUTRAL' in razon
    
    def test_seleccionar_modo_legacy(self):
        """Valida la versión legacy de seleccionar_modo."""
        modo_str, razon, detalles = self.selector.seleccionar_modo_legacy(
            simbolo='EURUSD',
            regimen='TREND_ALCISTA_FUERTE',
            direccion='COMPRA',
            score_h1=70.0,
            en_nivel_clave=True
        )
        
        assert modo_str is not None
        assert isinstance(modo_str, str)
    
    def test_set_entry_timer(self):
        """Valida la inyección del EntryTimer."""
        entry_timer_mock = MagicMock()
        
        self.selector.set_entry_timer(entry_timer_mock)
        
        assert self.selector.entry_timer is entry_timer_mock
    
    def test_get_stats_aprendizaje(self):
        """Valida la obtención de estadísticas de aprendizaje."""
        stats = self.selector.get_stats_aprendizaje()
        
        assert 'total_consultas' in stats
        assert 'cache_hits' in stats
        assert 'cache_misses' in stats