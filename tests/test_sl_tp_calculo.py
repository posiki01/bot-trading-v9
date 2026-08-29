#!/usr/bin/env python3
"""
tests/test_sl_tp_calculo.py
Valida el cálculo de SL/TP.
"""

import pytest
from unittest.mock import MagicMock, patch

from trading.stops import GestorStops


class TestGestorStops:
    """Validación del gestor de stops."""

    def setup_method(self):
        """Configura el gestor."""
        self.gestor = GestorStops(modo_backtest=True)

    def test_sl_compra_correcto(self):
        """Valida SL debajo para COMPRA."""
        valido, razon, sl, tp, tp2 = self.gestor.validar_sl_tp(
            simbolo='EURUSD',
            entry_price=1.0805,
            sl=1.07850,
            tp=1.08350,
            direccion='COMPRA',
            modo='RETEST',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert valido is True
        assert sl < 1.0805

    def test_tp_compra_correcto(self):
        """Valida TP arriba para COMPRA."""
        valido, razon, sl, tp, tp2 = self.gestor.validar_sl_tp(
            simbolo='EURUSD',
            entry_price=1.0805,
            sl=1.07850,
            tp=1.08350,
            direccion='COMPRA',
            modo='RETEST',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert valido is True
        assert tp > 1.0805

    def test_sl_venta_correcto(self):
        """Valida SL arriba para VENTA."""
        valido, razon, sl, tp, tp2 = self.gestor.validar_sl_tp(
            simbolo='EURUSD',
            entry_price=1.0845,
            sl=1.08650,
            tp=1.08150,
            direccion='VENTA',
            modo='RETEST',
            regimen='TREND_BAJISTA_FUERTE'
        )
        
        assert valido is True
        assert sl > 1.0845

    def test_tp_venta_correcto(self):
        """Valida TP abajo para VENTA."""
        valido, razon, sl, tp, tp2 = self.gestor.validar_sl_tp(
            simbolo='EURUSD',
            entry_price=1.0845,
            sl=1.08650,
            tp=1.08150,
            direccion='VENTA',
            modo='RETEST',
            regimen='TREND_BAJISTA_FUERTE'
        )
        
        assert valido is True
        assert tp < 1.0845

    def test_rr_minimo(self):
        """Valida R:R mínimo."""
        valido, razon, sl, tp, tp2 = self.gestor.validar_sl_tp(
            simbolo='EURUSD',
            entry_price=1.0805,
            sl=1.07850,
            tp=0,
            direccion='COMPRA',
            modo='RETEST',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert valido is True
        rr = abs(tp - 1.0805) / abs(1.0805 - sl)
        assert rr >= 1.2

    def test_tp_auto_calculado(self):
        """Valida cálculo automático de TP cuando tp=0."""
        valido, razon, sl, tp, tp2 = self.gestor.validar_sl_tp(
            simbolo='EURUSD',
            entry_price=1.0805,
            sl=1.07850,
            tp=0,
            direccion='COMPRA',
            modo='RETEST',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert valido is True
        assert tp > 0
        assert tp > 1.0805

    def test_sl_minimo_eurusd(self):
        """Valida SL mínimo para EURUSD."""
        valido, razon, sl, tp, tp2 = self.gestor.validar_sl_tp(
            simbolo='EURUSD',
            entry_price=1.0805,
            sl=1.0800,
            tp=0,
            direccion='COMPRA',
            modo='RETEST',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert valido is True
        sl_dist_pips = abs(1.0805 - sl) / 0.0001
        assert sl_dist_pips >= 10  # Mínimo 10 pips