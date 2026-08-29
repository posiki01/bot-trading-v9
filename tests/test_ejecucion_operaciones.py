#!/usr/bin/env python3
"""
tests/test_ejecucion_operaciones.py (V1.2 - CORREGIDO)
Valida la ejecución de operaciones.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from trading.ejecucion import EjecutorOperaciones


class TestEjecucionOperaciones:
    """Validación del ejecutor de operaciones."""

    def setup_method(self):
        """Configura el ejecutor para cada test."""
        self.mt5_mock = MagicMock()
        self.gestion_riesgo_mock = MagicMock()
        self.gestor_stops_mock = MagicMock()
        self.notificaciones_mock = MagicMock()
        
        # Configurar mocks básicos
        self.gestion_riesgo_mock.capital_actual = 1000.0
        self.gestion_riesgo_mock.puede_operar.return_value = (True, "OK")
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.07850, 1.08350, 0)
        self.mt5_mock.obtener_precio.return_value = {'bid': 1.0800, 'ask': 1.0805, 'spread_pips': 1.0}
        self.mt5_mock.info_cuenta.return_value = {'balance': 1000.0, 'margen_libre': 800.0, 'apalancamiento': 500}
        self.mt5_mock.obtener_margen.return_value = 5.0
        self.mt5_mock.obtener_posiciones.return_value = []
        self.mt5_mock.obtener_info_simbolo.return_value = MagicMock(
            digits=5,
            point=0.00001,
            trade_tick_size=0.00001,
            trade_tick_value=1.0,
            trade_contract_size=100000
        )
        
        # Crear ejecutor
        self.ejecutor = EjecutorOperaciones(
            orquestador=MagicMock(),
            mt5=self.mt5_mock,
            gestion_riesgo=self.gestion_riesgo_mock,
            gestor_stops=self.gestor_stops_mock,
            notificaciones=self.notificaciones_mock,
            modo_backtest=True
        )

    def test_ejecutar_compra_valida(self):
        """Valida que ejecuta COMPRA con SL/TP correctos."""
        senal = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entry_price': 1.0805,
            'sl': 1.07850,
            'tp': 1.08350,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE'
        }
        
        self.mt5_mock.enviar_orden.return_value = {
            'retcode': 10009,
            'ticket': 12345,
            'precio': 1.0805,
            'sl': 1.07850,
            'tp': 1.08350,
            'comentario': 'OK'
        }
        
        with patch.object(self.ejecutor, '_obtener_pip_val', return_value=0.0001):
            with patch.object(self.ejecutor, '_validar_sl_tp_por_modo', return_value=(True, "OK")):
                resultado = self.ejecutor.ejecutar(senal)
        
        assert resultado is True
        self.mt5_mock.enviar_orden.assert_called_once()

    def test_ejecutar_venta_valida(self):
        """Valida que ejecuta VENTA con SL/TP correctos."""
        senal = {
            'simbolo': 'EURUSD',
            'direccion': 'VENTA',
            'entry_price': 1.0845,
            'sl': 1.08650,
            'tp': 1.08150,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_BAJISTA_FUERTE',
            'calidad_horario': 'EXCELENTE'
        }
        
        # ✅ CORRECCIÓN: Configurar gestor_stops con valores correctos para VENTA
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.08650, 1.08150, 0)
        
        self.mt5_mock.enviar_orden.return_value = {
            'retcode': 10009,
            'ticket': 12346,
            'precio': 1.0845,
            'sl': 1.08650,
            'tp': 1.08150,
            'comentario': 'OK'
        }
        
        with patch.object(self.ejecutor, '_obtener_pip_val', return_value=0.0001):
            with patch.object(self.ejecutor, '_validar_sl_tp_por_modo', return_value=(True, "OK")):
                resultado = self.ejecutor.ejecutar(senal)
        
        assert resultado is True
        self.mt5_mock.enviar_orden.assert_called_once()

    def test_rechaza_sl_invertido_compra(self):
        """Valida que rechaza SL >= precio para COMPRA."""
        senal = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entry_price': 1.0805,
            'sl': 1.0805,
            'tp': 1.08350,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE'
        }
        
        with patch.object(self.ejecutor, '_obtener_pip_val', return_value=0.0001):
            resultado = self.ejecutor.ejecutar(senal)
        
        assert resultado is False
        self.mt5_mock.enviar_orden.assert_not_called()

    def test_rechaza_sl_invertido_venta(self):
        """Valida que rechaza SL <= precio para VENTA."""
        senal = {
            'simbolo': 'EURUSD',
            'direccion': 'VENTA',
            'entry_price': 1.0845,
            'sl': 1.0845,
            'tp': 1.08150,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_BAJISTA_FUERTE',
            'calidad_horario': 'EXCELENTE'
        }
        
        with patch.object(self.ejecutor, '_obtener_pip_val', return_value=0.0001):
            resultado = self.ejecutor.ejecutar(senal)
        
        assert resultado is False
        self.mt5_mock.enviar_orden.assert_not_called()

    def test_rechaza_rr_insuficiente(self):
        """Valida que rechaza R:R < 1.5."""
        senal = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entry_price': 1.0805,
            'sl': 1.0800,
            'tp': 1.0807,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE'
        }
        
        with patch.object(self.ejecutor, '_obtener_pip_val', return_value=0.0001):
            with patch.object(self.ejecutor, '_validar_sl_tp_por_modo', return_value=(False, "R:R insuficiente para RETEST (0.17 < 1.2)")):
                resultado = self.ejecutor.ejecutar(senal)
        
        assert resultado is False
        self.mt5_mock.enviar_orden.assert_not_called()

    def test_rechaza_posicion_duplicada(self):
        """Valida que rechaza posiciones duplicadas."""
        # ✅ CORRECCIÓN: Configurar posición existente en MT5
        self.mt5_mock.obtener_posiciones.return_value = [
            {'simbolo': 'EURUSD', 'tipo': 'BUY', 'ticket': 111}
        ]
        
        # ✅ CORRECCIÓN: Usar modo_backtest=False para que _verificar_posiciones_existentes se ejecute
        self.ejecutor.modo_backtest = False
        
        senal = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entry_price': 1.0805,
            'sl': 1.07850,
            'tp': 1.08350,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE'
        }
        
        with patch.object(self.ejecutor, '_obtener_pip_val', return_value=0.0001):
            resultado = self.ejecutor.ejecutar(senal)
        
        assert resultado is False
        self.mt5_mock.enviar_orden.assert_not_called()

    def test_rechaza_capital_insuficiente(self):
        """Valida que rechaza si capital insuficiente."""
        self.gestion_riesgo_mock.capital_actual = 50.0
        
        senal = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entry_price': 1.0805,
            'sl': 1.07850,
            'tp': 1.08350,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE'
        }
        
        with patch.object(self.ejecutor, '_obtener_pip_val', return_value=0.0001):
            with patch.object(self.ejecutor, '_validar_capital_minimo', return_value=(False, "Capital insuficiente para EURUSD ($50.00 < $100.00)")):
                resultado = self.ejecutor.ejecutar(senal)
        
        assert resultado is False
        self.mt5_mock.enviar_orden.assert_not_called()

    def test_rechaza_direccion_invalida(self):
        """Valida que rechaza dirección inválida."""
        senal = {
            'simbolo': 'EURUSD',
            'direccion': 'DESCONOCIDA',
            'entry_price': 1.0805,
            'sl': 1.07850,
            'tp': 1.08350,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE'
        }
        
        with patch.object(self.ejecutor, '_obtener_pip_val', return_value=0.0001):
            resultado = self.ejecutor.ejecutar(senal)
        
        assert resultado is False
        self.mt5_mock.enviar_orden.assert_not_called()