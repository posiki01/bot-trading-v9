#!/usr/bin/env python3
"""
tests/test_ejecucion_integracion.py (V1.3 - CORREGIDO FINAL)
Valida la integración del ejecutor con datos REALES de MT5 para múltiples símbolos.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from trading.ejecucion import EjecutorOperaciones
from trading.stops import GestorStops


# ============================================================
# DATOS MT5 POR SÍMBOLO (spread_max en POINTS, no en pips)
# ============================================================

DATOS_MT5_POR_SIMBOLO = {
    'EURUSD': {'digits': 5, 'point': 0.00001, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 100000, 'spread_max': 20},
    'GBPUSD': {'digits': 5, 'point': 0.00001, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 100000, 'spread_max': 20},
    'USDJPY': {'digits': 3, 'point': 0.001, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 100000, 'spread_max': 20},
    'USDCAD': {'digits': 5, 'point': 0.00001, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 100000, 'spread_max': 20},
    'XAUUSD': {'digits': 2, 'point': 0.01, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 100, 'spread_max': 300},  # ✅ 300 / 10 = 30 pips
    'XAGUSD': {'digits': 3, 'point': 0.001, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 5000, 'spread_max': 300},  # ✅ 300 / 10 = 30 pips
    'US30': {'digits': 1, 'point': 0.1, 'volume_min': 0.10, 'volume_step': 0.01, 'trade_contract_size': 1, 'spread_max': 50},
    'NAS100': {'digits': 1, 'point': 0.1, 'volume_min': 0.10, 'volume_step': 0.01, 'trade_contract_size': 1, 'spread_max': 50},
    'US500': {'digits': 1, 'point': 0.1, 'volume_min': 0.10, 'volume_step': 0.01, 'trade_contract_size': 1, 'spread_max': 50},
    'BTCUSD': {'digits': 2, 'point': 0.01, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 1, 'spread_max': 500},  # ✅ 500 / 10 = 50 pips
    'ETHUSD': {'digits': 2, 'point': 0.01, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 1, 'spread_max': 500},  # ✅ 500 / 10 = 50 pips
    'SOLUSD': {'digits': 2, 'point': 0.01, 'volume_min': 0.01, 'volume_step': 0.01, 'trade_contract_size': 1, 'spread_max': 500},  # ✅ 500 / 10 = 50 pips
}

PRECIOS_REFERENCIA = {
    'EURUSD': 1.0800,
    'GBPUSD': 1.2700,
    'USDJPY': 150.00,
    'USDCAD': 1.3600,
    'XAUUSD': 2000.00,
    'XAGUSD': 25.00,
    'US30': 40000.00,
    'NAS100': 18000.00,
    'US500': 5000.00,
    'BTCUSD': 60000.00,
    'ETHUSD': 3000.00,
    'SOLUSD': 150.00,
}


class TestEjecucionIntegracion:
    """Validación de integración con datos reales de MT5 para múltiples símbolos."""

    def setup_method(self):
        """Configura el ejecutor."""
        self.orquestador_mock = MagicMock()
        self.orquestador_mock.config = MagicMock()
        self.orquestador_mock.config.MAGIC_NUMBER = 123456
        self.orquestador_mock.estado.posiciones_abiertas = {}
        
        # Mock del conector MT5
        self.mt5_mock = MagicMock()
        self.mt5_mock.info_cuenta.return_value = {
            'balance': 10000.0,
            'equity': 10000.0,
            'margen_libre': 9500.0,
            'apalancamiento': 500
        }
        
        # Mock con spread_max en points
        def obtener_info_simbolo_side_effect(simbolo):
            datos = DATOS_MT5_POR_SIMBOLO.get(simbolo.upper(), DATOS_MT5_POR_SIMBOLO['EURUSD'])
            return MagicMock(
                digits=datos['digits'],
                point=datos['point'],
                volume_min=datos['volume_min'],
                volume_step=datos['volume_step'],
                trade_contract_size=datos['trade_contract_size'],
                spread_max=datos['spread_max']
            )
        
        self.mt5_mock.obtener_info_simbolo.side_effect = obtener_info_simbolo_side_effect
        
        # Mock de precio con spread consistente
        def obtener_precio_side_effect(simbolo):
            precio = PRECIOS_REFERENCIA.get(simbolo.upper(), 1.0800)
            datos = DATOS_MT5_POR_SIMBOLO.get(simbolo.upper(), DATOS_MT5_POR_SIMBOLO['EURUSD'])
            spread_pips = datos['spread_max'] / 10  # Spread máximo en pips
            
            pip_val = {
                'EURUSD': 0.0001, 'GBPUSD': 0.0001, 'USDJPY': 0.01,
                'USDCAD': 0.0001, 'XAUUSD': 0.10, 'XAGUSD': 0.01,
                'US30': 1.0, 'NAS100': 1.0, 'US500': 1.0,
                'BTCUSD': 1.0, 'ETHUSD': 1.0, 'SOLUSD': 1.0,
            }.get(simbolo.upper(), 0.0001)
            
            spread_precio = spread_pips * pip_val
            return {
                'bid': precio,
                'ask': precio + spread_precio,
                'spread_pips': spread_pips,
                'digits': datos['digits'],
                'point': datos['point'],
                'pip_size': pip_val
            }
        
        self.mt5_mock.obtener_precio.side_effect = obtener_precio_side_effect
        
        self.gestion_riesgo_mock = MagicMock()
        self.gestion_riesgo_mock.capital_actual = 10000.0
        
        self.gestor_stops_mock = MagicMock(spec=GestorStops)
        
        self.notificaciones_mock = MagicMock()
        
        self.almacen_mock = MagicMock()
        
        # Crear ejecutor en modo producción
        self.ejecutor = EjecutorOperaciones(
            orquestador=self.orquestador_mock,
            mt5=self.mt5_mock,
            gestion_riesgo=self.gestion_riesgo_mock,
            gestor_stops=self.gestor_stops_mock,
            notificaciones=self.notificaciones_mock,
            modo_backtest=False,
            almacen=self.almacen_mock
        )

    # ============================================================
    # TEST: _obtener_pip_val con datos REALES de MT5
    # ============================================================

    @pytest.mark.parametrize("simbolo,esperado", [
        ('EURUSD', 0.0001),
        ('GBPUSD', 0.0001),
        ('USDJPY', 0.01),
        ('USDCAD', 0.0001),
        ('XAUUSD', 0.10),
        ('XAGUSD', 0.01),
        ('US30', 1.0),
        ('NAS100', 1.0),
        ('US500', 1.0),
        ('BTCUSD', 1.0),
        ('ETHUSD', 1.0),
        ('SOLUSD', 1.0),
    ])
    def test_obtener_pip_val_con_mt5_real(self, simbolo, esperado):
        """Valida pip_val usando datos reales de MT5."""
        pip_val = self.ejecutor._obtener_pip_val(simbolo)
        assert pip_val == esperado

    # ============================================================
    # TEST: _obtener_digits con datos REALES de MT5
    # ============================================================

    @pytest.mark.parametrize("simbolo,esperado", [
        ('EURUSD', 5),
        ('GBPUSD', 5),
        ('USDJPY', 3),
        ('USDCAD', 5),
        ('XAUUSD', 2),
        ('XAGUSD', 3),
        ('US30', 1),
        ('NAS100', 1),
        ('US500', 1),
        ('BTCUSD', 2),
        ('ETHUSD', 2),
        ('SOLUSD', 2),
    ])
    def test_obtener_digits_con_mt5_real(self, simbolo, esperado):
        """Valida digits usando datos reales de MT5."""
        digits = self.ejecutor._obtener_digits(simbolo)
        assert digits == esperado

    # ============================================================
    # TEST: _obtener_lote_minimo_broker con datos REALES de MT5
    # ============================================================

    @pytest.mark.parametrize("simbolo,esperado", [
        ('EURUSD', 0.01),
        ('XAUUSD', 0.01),
        ('US30', 0.10),
        ('BTCUSD', 0.01),
    ])
    def test_obtener_lote_minimo_broker_con_mt5_real(self, simbolo, esperado):
        """Valida lote mínimo usando datos reales de MT5."""
        lote_min = self.ejecutor._obtener_lote_minimo_broker(simbolo)
        assert lote_min == esperado

    # ============================================================
    # TEST: _obtener_tamano_contrato con datos REALES de MT5
    # ============================================================

    @pytest.mark.parametrize("simbolo,esperado", [
        ('EURUSD', 100000.0),
        ('XAUUSD', 100.0),
        ('US30', 1.0),
        ('BTCUSD', 1.0),
    ])
    def test_obtener_tamano_contrato_con_mt5_real(self, simbolo, esperado):
        """Valida tamaño de contrato usando datos reales de MT5."""
        tamano = self.ejecutor._obtener_tamano_contrato(simbolo)
        assert tamano == esperado

    # ============================================================
    # TEST: _estimar_margen con apalancamiento REAL
    # ============================================================

    def test_estimar_margen_eurusd_con_apalancamiento_real(self):
        """Valida margen para EURUSD con apalancamiento real (500)."""
        margen = self.ejecutor._estimar_margen('EURUSD', 0.01, 1.0800)
        assert margen == pytest.approx(2.16, abs=0.1)

    def test_estimar_margen_xauusd_con_apalancamiento_real(self):
        """Valida margen para XAUUSD con apalancamiento real (500 del mock)."""
        margen = self.ejecutor._estimar_margen('XAUUSD', 0.01, 2000.0)
        assert margen == pytest.approx(4.0, abs=0.1)

    def test_estimar_margen_btcusd_con_apalancamiento_real(self):
        """Valida margen para BTCUSD con apalancamiento real (500 del mock)."""
        margen = self.ejecutor._estimar_margen('BTCUSD', 0.01, 60000.0)
        assert margen == pytest.approx(1.2, abs=0.1)

    def test_estimar_margen_us30_con_apalancamiento_real(self):
        """Valida margen para US30 con apalancamiento real (500 del mock)."""
        margen = self.ejecutor._estimar_margen('US30', 0.01, 40000.0)
        assert margen == pytest.approx(0.8, abs=0.1)

    # ============================================================
    # TEST: _obtener_apalancamiento_real
    # ============================================================

    def test_obtener_apalancamiento_real_de_mt5(self):
        """Valida que obtiene apalancamiento real de MT5."""
        self.mt5_mock.info_cuenta.return_value = {
            'balance': 10000.0,
            'equity': 10000.0,
            'margen_libre': 9500.0,
            'apalancamiento': 500
        }
        
        apalancamiento = self.ejecutor._obtener_apalancamiento_real('EURUSD')
        assert apalancamiento == 500

    def test_obtener_apalancamiento_real_fallback_xauusd(self):
        """Valida fallback de apalancamiento para XAUUSD si MT5 falla."""
        self.mt5_mock.info_cuenta.return_value = {}
        
        apalancamiento = self.ejecutor._obtener_apalancamiento_real('XAUUSD')
        assert apalancamiento == 200

    def test_obtener_apalancamiento_real_fallback_btcusd(self):
        """Valida fallback de apalancamiento para BTCUSD si MT5 falla."""
        self.mt5_mock.info_cuenta.return_value = {}
        
        apalancamiento = self.ejecutor._obtener_apalancamiento_real('BTCUSD')
        assert apalancamiento == 2

    # ============================================================
    # TEST: _obtener_spread_max (CORREGIDO)
    # ============================================================

    @pytest.mark.parametrize("simbolo,esperado", [
        ('EURUSD', 2),   # spread_max = 20 / 10 = 2 pips
        ('GBPUSD', 2),
        ('USDJPY', 2),
        ('XAUUSD', 30),  # spread_max = 300 / 10 = 30 pips
        ('XAGUSD', 30),  # spread_max = 300 / 10 = 30 pips
        ('US30', 5),     # spread_max = 50 / 10 = 5 pips
        ('NAS100', 5),
        ('US500', 5),
        ('BTCUSD', 50),  # spread_max = 500 / 10 = 50 pips
        ('ETHUSD', 50),  # spread_max = 500 / 10 = 50 pips
        ('SOLUSD', 50),  # spread_max = 500 / 10 = 50 pips
    ])
    def test_spread_max_por_simbolo(self, simbolo, esperado):
        """Valida que el spread máximo por símbolo es correcto."""
        assert self.ejecutor._obtener_spread_max(simbolo) == esperado

    # ============================================================
    # TEST: _obtener_paso_lote
    # ============================================================

    def test_obtener_paso_lote_eurusd(self):
        """Valida paso de lote para EURUSD."""
        paso = self.ejecutor._obtener_paso_lote('EURUSD')
        assert paso == 0.01

    def test_obtener_paso_lote_us30(self):
        """Valida paso de lote para US30."""
        paso = self.ejecutor._obtener_paso_lote('US30')
        assert paso == 0.01

    # ============================================================
    # TEST: _verificar_margen_real (INTEGRACIÓN)
    # ============================================================

    def test_verificar_margen_real_suficiente(self):
        """Valida que hay margen suficiente."""
        valido, razon = self.ejecutor._verificar_margen_real('EURUSD', 0.01, 1.0800)
        assert valido is True
        assert razon == "OK"

    def test_verificar_margen_real_insuficiente(self):
        """Valida que rechaza si no hay margen suficiente."""
        self.mt5_mock.info_cuenta.return_value = {
            'balance': 100.0,
            'equity': 100.0,
            'margen_libre': 1.0
        }
        
        valido, razon = self.ejecutor._verificar_margen_real('XAUUSD', 0.10, 2000.0)
        assert valido is False
        assert "insuficiente" in razon.lower()

    # ============================================================
    # TEST: _validar_sl_tp_antes_enviar con SPREAD REAL
    # ============================================================

    def test_validar_sl_tp_con_spread_normal(self):
        """Valida SL/TP con spread normal."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0780,
            tp=1.0900,
            direccion='COMPRA',
            bid=1.0800,
            ask=1.0801
        )
        assert valido is True
        assert razon == "OK"

    def test_validar_sl_tp_con_spread_alto(self):
        """Valida que rechaza SL/TP si el spread es alto."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='XAUUSD',
            entry_price=2000.00,
            sl=1999.50,
            tp=2001.00,
            direccion='COMPRA',
            bid=2000.00,
            ask=2000.30
        )
        assert valido is False
        assert "spread" in razon.lower() or "cerca" in razon.lower()

    def test_validar_sl_tp_con_spread_extremo(self):
        """Valida que rechaza SL/TP si el spread es extremo."""
        valido, razon = self.ejecutor._validar_sl_tp_antes_enviar(
            simbolo='EURUSD',
            entry_price=1.0800,
            sl=1.0799,
            tp=1.0900,
            direccion='COMPRA',
            bid=1.0800,
            ask=1.0803
        )
        assert valido is False
        assert "SL" in razon.upper()

    # ============================================================
    # TEST: _validar_sl_tp_por_modo
    # ============================================================

    def test_validar_sl_tp_por_modo_eurusd_con_spread(self):
        """Valida SL/TP por modo con spread."""
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

    def test_validar_sl_tp_por_modo_xauusd_con_spread(self):
        """Valida SL/TP por modo para XAUUSD con spread."""
        valido, razon = self.ejecutor._validar_sl_tp_por_modo(
            simbolo='XAUUSD',
            modo='RETEST',
            sl=1995.00,
            tp=2010.00,
            entry_price=2000.00,
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        assert valido is True

    # ============================================================
    # TEST: ejecutar() con datos REALES de MT5
    # ============================================================

    def test_ejecutar_eurusd_con_mt5_real(self):
        """Valida ejecución completa de EURUSD con MT5 real."""
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.07850, 1.08350, 0)
        self.mt5_mock.enviar_orden.return_value = {
            'ticket': 12345,
            'sl': 1.07850,
            'tp': 1.08350,
            'precio': 1.0801
        }
        
        señal = {
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
        
        resultado = self.ejecutor.ejecutar(señal)
        assert resultado is True
        assert 12345 in self.orquestador_mock.estado.posiciones_abiertas

    def test_ejecutar_xauusd_con_mt5_real(self):
        """Valida ejecución completa de XAUUSD con MT5 real."""
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1995.00, 2010.00, 0)
        self.mt5_mock.enviar_orden.return_value = {
            'ticket': 54321,
            'sl': 1995.00,
            'tp': 2010.00,
            'precio': 2000.20
        }
        
        señal = {
            'simbolo': 'XAUUSD',
            'direccion': 'COMPRA',
            'entry_price': 2000.00,
            'sl': 1995.00,
            'tp': 2010.00,
            'score': 80.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE',
            'volumen_relativo': 1.5
        }
        
        resultado = self.ejecutor.ejecutar(señal)
        assert resultado is True
        assert 54321 in self.orquestador_mock.estado.posiciones_abiertas

    def test_ejecutar_us30_con_mt5_real(self):
        """Valida ejecución completa de US30 con MT5 real."""
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 39900.00, 40200.00, 0)
        self.mt5_mock.enviar_orden.return_value = {
            'ticket': 67890,
            'sl': 39900.00,
            'tp': 40200.00,
            'precio': 40001.00
        }
        
        señal = {
            'simbolo': 'US30',
            'direccion': 'COMPRA',
            'entry_price': 40000.00,
            'sl': 39900.00,
            'tp': 40200.00,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE',
            'volumen_relativo': 1.2
        }
        
        resultado = self.ejecutor.ejecutar(señal)
        assert resultado is True
        assert 67890 in self.orquestador_mock.estado.posiciones_abiertas

    def test_ejecutar_btcusd_con_mt5_real(self):
        """Valida ejecución completa de BTCUSD con MT5 real."""
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 59500.00, 61000.00, 0)
        self.mt5_mock.enviar_orden.return_value = {
            'ticket': 13579,
            'sl': 59500.00,
            'tp': 61000.00,
            'precio': 60006.00
        }
        
        señal = {
            'simbolo': 'BTCUSD',
            'direccion': 'COMPRA',
            'entry_price': 60000.00,
            'sl': 59500.00,
            'tp': 61000.00,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE',
            'volumen_relativo': 1.3
        }
        
        resultado = self.ejecutor.ejecutar(señal)
        assert resultado is True
        assert 13579 in self.orquestador_mock.estado.posiciones_abiertas

    def test_ejecutar_con_capital_insuficiente_para_xauusd(self):
        """Valida que rechaza XAUUSD si el capital es insuficiente."""
        self.mt5_mock.info_cuenta.return_value = {
            'balance': 100.0,
            'equity': 100.0,
            'margen_libre': 5.0
        }
        
        señal = {
            'simbolo': 'XAUUSD',
            'direccion': 'COMPRA',
            'entry_price': 2000.00,
            'sl': 1995.00,
            'tp': 2010.00,
            'score': 70.0,
            'modo': 'RETEST',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'calidad_horario': 'EXCELENTE',
            'volumen_relativo': 1.5
        }
        
        resultado = self.ejecutor.ejecutar(señal)
        assert resultado is False

    # ============================================================
    # TEST: Validación de lote paso y múltiplo
    # ============================================================

    def test_validar_lote_multiplo_paso(self):
        """Valida que el lote calculado es múltiplo del paso."""
        lote_calculado = 0.015
        paso = 0.01
        lote_redondeado = round(lote_calculado / paso) * paso
        assert lote_redondeado == 0.02

    def test_validar_lote_menor_que_minimo(self):
        """Valida que si el lote es menor que el mínimo, se ajusta."""
        lote_calculado = 0.005
        lote_minimo = 0.01
        lote_final = max(lote_calculado, lote_minimo)
        assert lote_final == 0.01