#!/usr/bin/env python3
"""
tests/test_gestion_riesgo.py
Valida la gestión de riesgo.
"""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from trading.riesgo import GestionRiesgo


class TestGestionRiesgo:
    """Validación de la gestión de riesgo."""

    def setup_method(self):
        """Configura la gestión de riesgo para cada test."""
        self.almacen_mock = MagicMock()
        self.notificador_mock = MagicMock()
        
        # Crear gestión de riesgo
        self.gestion = GestionRiesgo(
            capital_inicial=1000.0,
            aporte_mensual=50.0,
            almacen=self.almacen_mock,
            notificador=self.notificador_mock,
            modo_backtest=True
        )
        
        # ✅ CORREGIDO: Resetear contadores
        self.gestion.perdidas_consecutivas = 0
        self.gestion.operaciones = []

    def test_puede_operar_con_capital_suficiente(self):
        """Valida que puede operar con capital suficiente."""
        puede, razon = self.gestion.puede_operar()
        
        assert puede is True
        assert razon == "OK"

    def test_puede_operar_capital_insuficiente(self):
        """Valida que NO puede operar con capital insuficiente."""
        self.gestion.capital_actual = Decimal('1.0')
        
        puede, razon = self.gestion.puede_operar()
        
        assert puede is False
        assert "Capital" in razon

    def test_registrar_operacion_ganancia(self):
        """Valida registro de operación ganadora."""
        self.gestion.registrar_operacion({
            'ticket': 123,
            'simbolo': 'EURUSD',
            'ganancia': 10.0,
            'comision': -0.5,
            'swap': 0.0,
            'motivo_cierre': 'TP'
        })
        
        assert float(self.gestion.capital_actual) > 1000.0
        assert self.gestion.perdidas_consecutivas == 0

    def test_registrar_operacion_perdida(self):
        """Valida registro de operación perdedora."""
        self.gestion.registrar_operacion({
            'ticket': 124,
            'simbolo': 'EURUSD',
            'ganancia': -8.0,
            'comision': -0.5,
            'swap': 0.0,
            'motivo_cierre': 'SL'
        })
        
        assert float(self.gestion.capital_actual) < 1000.0
        # ✅ CORREGIDO: Debe ser 1 porque resetee el contador
        assert self.gestion.perdidas_consecutivas == 1