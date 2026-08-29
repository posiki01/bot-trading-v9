#!/usr/bin/env python3
"""
tests/test_ejecucion_v2.py (V1.0)
Valida el ejecutor de operaciones V9.71 con validación completa de SL/TP.
Enfocado en: validaciones previas, cálculo de lotes, SL/TP, y envío de órdenes.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from decimal import Decimal

from trading.ejecucion import EjecutorOperaciones
from trading.stops import GestorStops


class TestEjecutorOperaciones:
    """Validación del ejecutor de operaciones."""

    def setup_method(self):
        """Configura el ejecutor."""
        # Mocks de dependencias
        self.orquestador_mock = MagicMock()
        self.orquestador_mock.config = MagicMock()
        self.orquestador_mock.config.MAGIC_NUMBER = 123456
        self.orquestador_mock.estado.posiciones_abiertas = {}
        
        self.mt5_mock = MagicMock()
        self.mt5_mock.obtener_info_simbolo.return_value = MagicMock(
            digits=5,
            point=0.00001,
            trade_tick_size=0.00001,
            trade_tick_value=1.0,
            trade_contract_size=100000
        )
        self.mt5_mock.info_cuenta.return_value = {
            'balance': 1000.0,
            'equity': 1000.0,
            'margen_libre': 900.0
        }
        
        self.gestion_riesgo_mock = MagicMock()
        self.gestion_riesgo_mock.capital_actual = 1000.0
        
        self.gestor_stops_mock = MagicMock(spec=GestorStops)
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.07850, 1.08350, 0)
        
        self.notificaciones_mock = MagicMock()
        
        self.almacen_mock = MagicMock()
        
        # Crear ejecutor
        self.ejecutor = EjecutorOperaciones(
            orquestador=self.orquestador_mock,
            mt5=self.mt5_mock,
            gestion_riesgo=self.gestion_riesgo_mock,
            gestor_stops=self.gestor_stops_mock,
            notificaciones=self.notificaciones_mock,
            modo_backtest=True,
            almacen=self.almacen_mock
        )
        
        # Señal válida de COMPRA
        self.señal_compra = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entry_price': 1.0800,
            'sl': 1.0780,
            'tp': 1.0900,
            'score': 75.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE',
            'volumen_relativo': 1.5
        }
        
        # Señal válida de VENTA
        self.señal_venta = {
            'simbolo': 'EURUSD',
            'direccion': 'VENTA',
            'entry_price': 1.0800,
            'sl': 1.0820,
            'tp': 1.0700,
            'score': 75.0,
            'modo': 'RETEST',
            'regimen': 'TREND_BAJISTA_FUERTE',
            'calidad_horario': 'EXCELENTE',
            'volumen_relativo': 1.5
        }

    # ============================================================
    # TEST: _obtener_pip_val
    # ============================================================

    def test_obtener_pip_val_eurusd(self):
        """Valida pip_val para EURUSD."""
        pip_val = self.ejecutor._obtener_pip_val('EURUSD')
        assert pip_val == 0.0001

    def test_obtener_pip_val_xauusd(self):
        """Valida pip_val para XAUUSD."""
        pip_val = self.ejecutor._obtener_pip_val('XAUUSD')
        assert pip_val == 0.10  # ✅ CORREGIDO: 0.10 para oro

    def test_obtener_pip_val_usdjpy(self):
        """Valida pip_val para USDJPY."""
        pip_val = self.ejecutor._obtener_pip_val('USDJPY')
        assert pip_val == 0.01

    def test_obtener_pip_val_btcusd(self):
        """Valida pip_val para BTCUSD."""
        pip_val = self.ejecutor._obtener_pip_val('BTCUSD')
        assert pip_val == 1.0

    # ============================================================
    # TEST: _obtener_digits
    # ============================================================

    def test_obtener_digits_eurusd(self):
        """Valida digits para EURUSD."""
        digits = self.ejecutor._obtener_digits('EURUSD')
        assert digits == 5

    def test_obtener_digits_xauusd(self):
        """Valida digits para XAUUSD."""
        digits = self.ejecutor._obtener_digits('XAUUSD')
        assert digits == 2

    def test_obtener_digits_usdjpy(self):
        """Valida digits para USDJPY."""
        digits = self.ejecutor._obtener_digits('USDJPY')
        assert digits == 3

    # ============================================================
    # TEST: _calcular_valor_pip y _obtener_tamano_contrato
    # ============================================================

    def test_obtener_tamano_contrato_forex(self):
        """Valida tamaño de contrato para Forex."""
        tamano = self.ejecutor._obtener_tamano_contrato('EURUSD')
        assert tamano == 100000.0

    def test_obtener_tamano_contrato_xauusd(self):
        """Valida tamaño de contrato para XAUUSD."""
        tamano = self.ejecutor._obtener_tamano_contrato('XAUUSD')
        assert tamano == 100.0

    def test_obtener_tamano_contrato_btcusd(self):
        """Valida tamaño de contrato para BTCUSD."""
        tamano = self.ejecutor._obtener_tamano_contrato('BTCUSD')
        assert tamano == 1.0

    def test_calcular_valor_pip_eurusd(self):
        """Valida valor de 1 pip para EURUSD."""
        valor = self.ejecutor._calcular_valor_pip('EURUSD')
        assert valor == pytest.approx(10.0, abs=0.1)  # 100000 * 0.0001

    # ============================================================
    # TEST: _validar_sl_tp_antes_enviar (NUEVA FUNCIÓN)
    # ============================================================

    def test_validar_sl_tp_antes_enviar_compra_ok(self):
        """Valida SL/TP válido para COMPRA."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0780,
            tp=1.0900,
            direccion='COMPRA'
        )
        
        assert valido is True
        assert razon == "OK"

    def test_validar_sl_tp_antes_enviar_compra_sl_invertido(self):
        """Valida que rechaza SL invertido para COMPRA."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0810,  # SL > Entry (invertido)
            tp=1.0900,
            direccion='COMPRA'
        )
        
        assert valido is False
        assert "SL" in razon.upper()

    def test_validar_sl_tp_antes_enviar_compra_tp_invertido(self):
        """Valida que rechaza TP invertido para COMPRA."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0780,
            tp=1.0790,  # TP < Entry (invertido)
            direccion='COMPRA'
        )
        
        assert valido is False
        assert "TP" in razon.upper()

    def test_validar_sl_tp_antes_enviar_venta_ok(self):
        """Valida SL/TP válido para VENTA."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0820,
            tp=1.0700,
            direccion='VENTA'
        )
        
        assert valido is True
        assert razon == "OK"

    def test_validar_sl_tp_antes_enviar_venta_sl_invertido(self):
        """Valida que rechaza SL invertido para VENTA."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0790,  # SL < Entry (invertido)
            tp=1.0700,
            direccion='VENTA'
        )
        
        assert valido is False
        assert "SL" in razon.upper()

    def test_validar_sl_tp_antes_enviar_sl_muy_cerca(self):
        """Valida que rechaza SL demasiado cerca del entry."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0799,  # Solo 1 pip de distancia
            tp=1.0900,
            direccion='COMPRA'
        )
        
        assert valido is False
        assert "cerca" in razon.lower()

    def test_validar_sl_tp_antes_enviar_tp_muy_cerca(self):
        """Valida que rechaza TP demasiado cerca del entry."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0780,
            tp=1.0801,  # Solo 1 pip de distancia
            direccion='COMPRA'
        )
        
        assert valido is False
        assert "TP" in razon.upper()

    def test_validar_sl_tp_antes_enviar_con_tick(self):
        """Valida que verifica contra tick actual."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0780,
            tp=1.0900,
            direccion='COMPRA',
            bid=1.0805,
            ask=1.0810
        )
        
        assert valido is True
        assert razon == "OK"

    # ============================================================
    # TEST: _verificar_posiciones_existentes
    # ============================================================

    def test_verificar_posiciones_sin_conflictos(self):
        """Valida que no hay conflictos si no hay posiciones."""
        self.mt5_mock.obtener_posiciones.return_value = []
        
        valido, razon = self.ejecutor._verificar_posiciones_existentes('EURUSD', 'COMPRA')
        
        assert valido is True
        assert razon == "Sin posiciones"

    def test_verificar_posiciones_misma_direccion(self):
        """Valida que rechaza si ya hay posición en la misma dirección."""
        self.mt5_mock.obtener_posiciones.return_value = [
            {'simbolo': 'EURUSD', 'tipo': 'BUY'}
        ]
        
        valido, razon = self.ejecutor._verificar_posiciones_existentes('EURUSD', 'COMPRA')
        
        assert valido is False
        assert "EXISTE" in razon.upper()

    def test_verificar_posiciones_direccion_opuesta(self):
        """Valida que permite si hay posición en dirección opuesta."""
        self.mt5_mock.obtener_posiciones.return_value = [
            {'simbolo': 'EURUSD', 'tipo': 'SELL'}
        ]
        
        valido, razon = self.ejecutor._verificar_posiciones_existentes('EURUSD', 'COMPRA')
        
        assert valido is True

    # ============================================================
    # TEST: _obtener_capital_real
    # ============================================================

    def test_obtener_capital_real_backtest(self):
        """Valida que en backtest usa capital de gestión de riesgo."""
        self.ejecutor.modo_backtest = True
        
        capital = self.ejecutor._obtener_capital_real()
        
        assert capital == 1000.0

    def test_obtener_capital_real_mt5(self):
        """Valida que en producción obtiene capital de MT5."""
        self.ejecutor.modo_backtest = False
        self.mt5_mock.info_cuenta.return_value = {'balance': 2500.0}
        
        capital = self.ejecutor._obtener_capital_real()
        
        assert capital == 2500.0

    # ============================================================
    # TEST: _estimar_margen
    # ============================================================

    def test_estimar_margen_forex(self):
        """Valida estimación de margen para Forex."""
        margen = self.ejecutor._estimar_margen('EURUSD', 0.01, 1.0800)
        
        # 0.01 * 100000 * 1.08 / 500 = $2.16
        assert margen == pytest.approx(2.16, abs=0.1)

    def test_estimar_margen_xauusd(self):
        """Valida estimación de margen para XAUUSD."""
        margen = self.ejecutor._estimar_margen('XAUUSD', 0.01, 2000.0)
        
        # 0.01 * 100 * 2000 / 20 = $10.00
        assert margen == pytest.approx(10.0, abs=0.5)

    # ============================================================
    # TEST: _obtener_lote_minimo_broker
    # ============================================================

    def test_obtener_lote_minimo_broker_eurusd(self):
        """Valida lote mínimo para EURUSD."""
        lote_min = self.ejecutor._obtener_lote_minimo_broker('EURUSD')
        assert lote_min == 0.01

    def test_obtener_lote_minimo_broker_us30(self):
        """Valida lote mínimo para US30."""
        lote_min = self.ejecutor._obtener_lote_minimo_broker('US30')
        assert lote_min == 0.10

    # ============================================================
    # TEST: _validar_sl_tp_por_modo
    # ============================================================

    def test_validar_sl_tp_por_modo_retest_ok(self):
        """Valida SL/TP para modo RETEST."""
        valido, razon = self.ejecutor._validar_sl_tp_por_modo(
            simbolo='EURUSD',
            modo='RETEST',
            sl=1.0780,
            tp=1.0900,
            entry_price=1.0800,
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert valido is True

    def test_validar_sl_tp_por_modo_breakout_sl_cerca(self):
        """Valida que rechaza SL demasiado cerca para BREAKOUT."""
        valido, razon = self.ejecutor._validar_sl_tp_por_modo(
            simbolo='EURUSD',
            modo='BREAKOUT',
            sl=1.0799,  # Solo 1 pip de distancia
            tp=1.0900,
            entry_price=1.0800,
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert valido is False
        assert "SL" in razon.upper()

    # ============================================================
    # TEST: ejecutar (FLUJO COMPLETO)
    # ============================================================

    def test_ejecutar_compra_exitosa(self):
        """Valida ejecución exitosa de COMPRA."""
        # Mock de envío de orden
        self.mt5_mock.enviar_orden.return_value = {
            'ticket': 12345,
            'sl': 1.0780,
            'tp': 1.0900,
            'precio': 1.0800
        }
        
        # Ejecutar
        resultado = self.ejecutor.ejecutar(self.señal_compra)
        
        assert resultado is True
        assert 12345 in self.orquestador_mock.estado.posiciones_abiertas

    def test_ejecutar_venta_exitosa(self):
        """Valida ejecución exitosa de VENTA."""
        # Configurar gestor_stops para VENTA
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.0820, 1.0700, 0)
        
        # Mock de envío de orden
        self.mt5_mock.enviar_orden.return_value = {
            'ticket': 12345,
            'sl': 1.0820,
            'tp': 1.0700,
            'precio': 1.0800
        }
        
        # Ejecutar
        resultado = self.ejecutor.ejecutar(self.señal_venta)
        
        assert resultado is True
        assert 12345 in self.orquestador_mock.estado.posiciones_abiertas

    def test_ejecutar_sin_simbolo(self):
        """Valida que rechaza señal sin símbolo."""
        señal_invalida = {'direccion': 'COMPRA', 'entry_price': 1.0800, 'sl': 1.0780, 'tp': 1.0900}
        
        resultado = self.ejecutor.ejecutar(señal_invalida)
        
        assert resultado is False

    def test_ejecutar_precios_invalidos(self):
        """Valida que rechaza precios inválidos."""
        señal_invalida = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entry_price': 0,
            'sl': 1.0780,
            'tp': 1.0900
        }
        
        resultado = self.ejecutor.ejecutar(señal_invalida)
        
        assert resultado is False

    def test_ejecutar_sl_invertido(self):
        """Valida que rechaza SL invertido."""
        señal_invalida = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entry_price': 1.0800,
            'sl': 1.0810,  # SL > Entry (invertido)
            'tp': 1.0900
        }
        
        resultado = self.ejecutor.ejecutar(señal_invalida)
        
        assert resultado is False

    def test_ejecutar_posicion_existente(self):
        """Valida que rechaza si ya hay posición."""
        self.mt5_mock.obtener_posiciones.return_value = [
            {'simbolo': 'EURUSD', 'tipo': 'BUY'}
        ]
        self.ejecutor.modo_backtest = False
        
        resultado = self.ejecutor.ejecutar(self.señal_compra)
        
        assert resultado is False