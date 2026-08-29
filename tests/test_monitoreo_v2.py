#!/usr/bin/env python3
"""
tests/test_monitoreo_v2.py (V1.1 - CORREGIDO)
Valida el monitor de posiciones V9.74 con protección contra retrocesos.
Enfocado en métodos críticos: ATR, umbrales dinámicos, trailing, y recuperación de datos.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from trading.monitoreo import MonitorPosiciones
from trading.trailing import TrailingEngine


class TestMonitorV2:
    """Validación de métodos críticos del monitor V9.74."""

    def setup_method(self):
        """Configura el monitor."""
        self.orquestador_mock = MagicMock()
        self.orquestador_mock.modo_backtest = True
        self.orquestador_mock.estado.posiciones_abiertas = {}
        self.orquestador_mock.config = MagicMock()
        self.orquestador_mock.config.MAGIC_NUMBER = 123456

        # Mock de caché
        self.cache_mock = MagicMock()
        self.cache_mock.get_datos.return_value = None
        self.orquestador_mock.cache = self.cache_mock

        # Mock del conector MT5
        self.mt5_mock = MagicMock()
        self.mt5_mock.obtener_precio.return_value = {
            'bid': 1.0805,
            'ask': 1.0810,
            'spread_pips': 0.5,
            'digits': 5,
            'point': 0.00001,
            'pip_size': 0.0001
        }
        self.mt5_mock.obtener_info_simbolo.return_value = MagicMock(
            digits=5,
            point=0.00001,
            trade_tick_size=0.00001,
            trade_tick_value=1.0,
            trade_contract_size=100000
        )

        # Mock de gestión de riesgo
        self.gestion_riesgo_mock = MagicMock()
        self.gestion_riesgo_mock.capital_actual = 1000.0

        # Crear monitor SIN DecisorCierre (V9.74)
        self.monitor = MonitorPosiciones(
            orquestador=self.orquestador_mock,
            mt5=self.mt5_mock,
            gestion_riesgo=self.gestion_riesgo_mock,
            trailing_engine=TrailingEngine(modo_backtest=True),
            decisor_cierre=None  # ✅ SIN DecisorCierre
        )

    # ============================================================
    # TEST: _calcular_atr
    # ============================================================

    def test_calcular_atr_con_datos(self):
        """Valida el cálculo de ATR con datos válidos."""
        # Crear DataFrame M5 con volatilidad conocida
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq='5min', tz='UTC')
        
        # ✅ CORRECCIÓN: Precios con rango de 0.001 (10 pips en EURUSD)
        df_m5 = pd.DataFrame({
            'Open': np.linspace(1.0800, 1.0800, 50),
            'High': np.linspace(1.0805, 1.0805, 50),  # ✅ 10 pips por encima
            'Low': np.linspace(1.0795, 1.0795, 50),   # ✅ 10 pips por debajo
            'Close': np.linspace(1.0800, 1.0800, 50),
            'Volume': np.random.randint(100, 1000, 50)
        }, index=fechas)

        self.cache_mock.get_datos.return_value = df_m5

        # Ejecutar
        atr_pips = self.monitor._calcular_atr('EURUSD', timeframe=5, n_velas=50)

        # ✅ Validar que ATR es razonable (10-12 pips)
        assert atr_pips >= 8.0
        assert atr_pips <= 12.0

    def test_calcular_atr_sin_datos(self):
        """Valida que retorna fallback si no hay datos."""
        self.cache_mock.get_datos.return_value = None

        atr_pips = self.monitor._calcular_atr('EURUSD')

        assert atr_pips == 15.0  # Fallback

    def test_calcular_atr_datos_insuficientes(self):
        """Valida que retorna fallback si hay pocos datos."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=10, freq='5min', tz='UTC')
        df_m5 = pd.DataFrame({
            'High': np.random.randn(10) * 0.001,
            'Low': np.random.randn(10) * 0.001,
            'Close': np.random.randn(10) * 0.001
        }, index=fechas)

        self.cache_mock.get_datos.return_value = df_m5

        atr_pips = self.monitor._calcular_atr('EURUSD')

        assert atr_pips == 15.0  # Fallback por datos insuficientes

    # ============================================================
    # TEST: _calcular_valor_pip_usd
    # ============================================================

    def test_calcular_valor_pip_usd_eurusd(self):
        """Valida el valor de 1 pip en USD para EURUSD."""
        valor_pip = self.monitor._calcular_valor_pip_usd('EURUSD', 0.01)
        
        # EURUSD: 100000 * 0.0001 * 0.01 = $0.10
        assert valor_pip == pytest.approx(0.10, abs=0.001)

    def test_calcular_valor_pip_usd_xauusd(self):
        """Valida el valor de 1 pip en USD para XAUUSD."""
        valor_pip = self.monitor._calcular_valor_pip_usd('XAUUSD', 0.01)
        
        # XAUUSD: 100 * 0.10 * 0.01 = $0.10
        assert valor_pip == pytest.approx(0.10, abs=0.001)

    # ============================================================
    # TEST: _calcular_umbrales_trailing
    # ============================================================

    def test_calcular_umbrales_trailing_por_atr(self):
        """Valida umbrales dinámicos basados en ATR."""
        lotes = 0.02
        atr_pips = 10.0

        umbrales = self.monitor._calcular_umbrales_trailing('EURUSD', lotes, atr_pips)

        # ✅ Validar que los umbrales son razonables
        assert umbrales['breakeven_umbral'] >= 20  # 2x ATR
        assert umbrales['trailing_umbral'] >= 30   # 3x ATR
        assert umbrales['trailing_agresivo_umbral'] >= 40  # 4x ATR

        # ✅ Validar que breakeven < trailing < agresivo
        assert umbrales['breakeven_umbral'] < umbrales['trailing_umbral']
        assert umbrales['trailing_umbral'] < umbrales['trailing_agresivo_umbral']

    def test_calcular_umbrales_con_lotes_pequenos(self):
        """Valida que con lotes pequeños, los umbrales se ajustan por USD."""
        lotes = 0.01  # Lotes pequeños
        atr_pips = 8.0

        umbrales = self.monitor._calcular_umbrales_trailing('EURUSD', lotes, atr_pips)

        # ✅ Con 0.01 lotes, 1 pip = $0.10, mínimo $1 USD = 10 pips
        # ATR = 8, breakeven = max(16, 10) = 16, pero mínimo 20
        assert umbrales['breakeven_umbral'] >= 20

    def test_calcular_umbrales_con_lotes_grandes(self):
        """Valida que con lotes grandes, los umbrales se ajustan por ATR."""
        lotes = 0.10  # Lotes grandes
        atr_pips = 10.0

        umbrales = self.monitor._calcular_umbrales_trailing('EURUSD', lotes, atr_pips)

        # ✅ Con 0.10 lotes, 1 pip = $1.00, mínimo $1 USD = 1 pip
        # ATR = 10, breakeven = max(20, 1) = 20
        assert umbrales['breakeven_umbral'] >= 20

    # ============================================================
    # TEST: _calcular_distancia_trailing
    # ============================================================

    def test_calcular_distancia_trailing(self):
        """Valida la distancia del trailing basada en ATR."""
        distancia = self.monitor._calcular_distancia_trailing('EURUSD', 10.0)

        # ✅ 1.5x ATR = 15 pips
        assert distancia == pytest.approx(15.0, abs=0.5)

    def test_calcular_distancia_trailing_minima(self):
        """Valida que la distancia nunca sea menor a 15 pips."""
        distancia = self.monitor._calcular_distancia_trailing('EURUSD', 5.0)

        # ✅ Mínimo 15 pips (aunque ATR sea 5)
        assert distancia >= 15.0

    # ============================================================
    # TEST: _debe_mover_sl
    # ============================================================

    def test_debe_mover_sl_ok(self):
        """Valida que se debe mover SL cuando hay ganancia suficiente."""
        debe_mover, razon = self.monitor._debe_mover_sl(
            simbolo='EURUSD',
            ganancia_pips=20.0,
            sl_actual=1.0800,
            precio_actual=1.0820,
            direccion='COMPRA',
            atr_pips=10.0
        )

        assert debe_mover is True
        assert razon == "OK"

    def test_debe_mover_sl_ganancia_insuficiente(self):
        """Valida que NO se mueve SL si la ganancia es menor a 2x ATR."""
        debe_mover, razon = self.monitor._debe_mover_sl(
            simbolo='EURUSD',
            ganancia_pips=10.0,  # Menos de 2x ATR (20)
            sl_actual=1.0800,
            precio_actual=1.0810,
            direccion='COMPRA',
            atr_pips=10.0
        )

        assert debe_mover is False
        assert "insuficiente" in razon.lower()

    def test_debe_mover_sl_retroceso(self):
        """Valida que NO se mueve SL si está demasiado cerca del precio."""
        debe_mover, razon = self.monitor._debe_mover_sl(
            simbolo='EURUSD',
            ganancia_pips=20.0,
            sl_actual=1.0815,  # SL muy cerca del precio
            precio_actual=1.0820,
            direccion='COMPRA',
            atr_pips=10.0
        )

        # Distancia SL-precio = 5 pips < 15 pips (1.5x ATR)
        assert debe_mover is False
        assert "cerca" in razon.lower()

    # ============================================================
    # TEST: _aplicar_trailing_sl
    # ============================================================

    def test_aplicar_trailing_sl_mejora(self):
        """Valida que mueve SL si mejora."""
        ticket = 12345
        self.orquestador_mock.estado.posiciones_abiertas[ticket] = {
            'simbolo': 'EURUSD',
            'sl': 1.0800
        }

        # Mock de _mover_sl
        with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover:
            nuevo_sl = self.monitor._aplicar_trailing_sl(
                ticket=ticket,
                simbolo='EURUSD',
                direccion='COMPRA',
                sl_actual=1.0800,
                nuevo_sl=1.0810,  # Mejora (más alto para COMPRA)
                fase="BREAKEVEN",
                ganancia_pips=20.0
            )

        assert nuevo_sl == 1.0810
        mock_mover.assert_called_once()

    def test_aplicar_trailing_sl_no_mejora(self):
        """Valida que NO mueve SL si no mejora."""
        ticket = 12345
        self.orquestador_mock.estado.posiciones_abiertas[ticket] = {
            'simbolo': 'EURUSD',
            'sl': 1.0820  # SL ya está más alto
        }

        with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover:
            nuevo_sl = self.monitor._aplicar_trailing_sl(
                ticket=ticket,
                simbolo='EURUSD',
                direccion='COMPRA',
                sl_actual=1.0820,
                nuevo_sl=1.0810,  # NO mejora (más bajo para COMPRA)
                fase="BREAKEVEN",
                ganancia_pips=20.0
            )

        # ✅ No debe mover, retorna el SL actual
        assert nuevo_sl == 1.0820
        mock_mover.assert_not_called()

    # ============================================================
    # TEST: _obtener_datos_m5_recuperable
    # ============================================================

    def test_obtener_datos_m5_desde_cache(self):
        """Valida que obtiene M5 desde caché."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='5min', tz='UTC')
        df_m5 = pd.DataFrame({
            'Close': 1.0800 + np.random.randn(100) * 0.0001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas)

        self.cache_mock.get_datos.return_value = df_m5

        df_resultado = self.monitor._obtener_datos_m5_recuperable('EURUSD')

        assert df_resultado is not None
        assert len(df_resultado) == 100

    def test_obtener_datos_m5_desde_mt5(self):
        """Valida que obtiene M5 desde MT5 si caché falla."""
        # Caché retorna None
        self.cache_mock.get_datos.return_value = None

        # MT5 retorna datos
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='5min', tz='UTC')
        df_m5 = pd.DataFrame({
            'Close': 1.0800 + np.random.randn(100) * 0.0001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas)

        self.mt5_mock.obtener_datos.return_value = df_m5

        df_resultado = self.monitor._obtener_datos_m5_recuperable('EURUSD')

        assert df_resultado is not None
        assert len(df_resultado) == 100

    def test_obtener_datos_m5_sin_datos(self):
        """Valida que retorna DataFrame sintético si no hay datos en ninguna fuente."""
        self.cache_mock.get_datos.return_value = None
        self.mt5_mock.obtener_datos.return_value = None

        # Sin almacen
        self.orquestador_mock.almacen = None

        # ✅ CORRECCIÓN: El monitor crea datos sintéticos como fallback
        df_resultado = self.monitor._obtener_datos_m5_recuperable('EURUSD')

        assert df_resultado is not None
        assert len(df_resultado) > 0
        assert 'Close' in df_resultado.columns

    # ============================================================
    # TEST: _obtener_datos_h1_recuperable
    # ============================================================

    def test_obtener_datos_h1_desde_cache(self):
        """Valida que obtiene H1 desde caché."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='1h', tz='UTC')
        df_h1 = pd.DataFrame({
            'Close': 1.0800 + np.random.randn(100) * 0.0001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas)

        self.cache_mock.get_datos.return_value = df_h1

        df_resultado = self.monitor._obtener_datos_h1_recuperable('EURUSD')

        assert df_resultado is not None
        assert len(df_resultado) == 100

    def test_obtener_datos_h1_desde_mt5(self):
        """Valida que obtiene H1 desde MT5 si caché falla."""
        self.cache_mock.get_datos.return_value = None

        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='1h', tz='UTC')
        df_h1 = pd.DataFrame({
            'Close': 1.0800 + np.random.randn(100) * 0.0001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas)

        self.mt5_mock.obtener_datos.return_value = df_h1

        df_resultado = self.monitor._obtener_datos_h1_recuperable('EURUSD')

        assert df_resultado is not None
        assert len(df_resultado) == 100

    def test_obtener_datos_h1_sin_datos(self):
        """Valida que retorna None si no hay datos en ninguna fuente."""
        self.cache_mock.get_datos.return_value = None
        self.mt5_mock.obtener_datos.return_value = None
        self.orquestador_mock.almacen = None

        df_resultado = self.monitor._obtener_datos_h1_recuperable('EURUSD')

        assert df_resultado is None

    # ============================================================
    # TEST: _determinar_direccion
    # ============================================================

    def test_determinar_direccion_compra(self):
        """Valida determinación de dirección COMPRA."""
        pos = {'tipo': 'BUY'}
        meta = {}

        direccion = self.monitor._determinar_direccion(pos, meta)

        assert direccion == 'COMPRA'

    def test_determinar_direccion_venta(self):
        """Valida determinación de dirección VENTA."""
        pos = {'tipo': 'SELL'}
        meta = {}

        direccion = self.monitor._determinar_direccion(pos, meta)

        assert direccion == 'VENTA'

    def test_determinar_direccion_desde_meta(self):
        """Valida determinación de dirección desde meta."""
        pos = {}
        meta = {'direccion': 'VENTA'}

        direccion = self.monitor._determinar_direccion(pos, meta)

        assert direccion == 'VENTA'

    # ============================================================
    # TEST: _verificar_sl_tp
    # ============================================================

    def test_verificar_sl_tp_compra_sl_tocado(self):
        """Valida que detecta SL tocado para COMPRA."""
        pos = {
            'simbolo': 'EURUSD',
            'tipo': 'BUY',
            'sl': 1.0780,
            'tp': 1.0900,
            'precio_apertura': 1.0800
        }

        # Precio por debajo del SL
        with patch.object(self.monitor, '_cerrar_posicion') as mock_cerrar:
            resultado = self.monitor._verificar_sl_tp(pos, 12345, -20.0, 1.0775)

        assert resultado is True
        mock_cerrar.assert_called_once_with(12345, "SL alcanzado")

    def test_verificar_sl_tp_compra_tp_tocado(self):
        """Valida que detecta TP tocado para COMPRA."""
        pos = {
            'simbolo': 'EURUSD',
            'tipo': 'BUY',
            'sl': 1.0780,
            'tp': 1.0900,
            'precio_apertura': 1.0800
        }

        with patch.object(self.monitor, '_cerrar_posicion') as mock_cerrar:
            resultado = self.monitor._verificar_sl_tp(pos, 12345, 100.0, 1.0905)

        assert resultado is True
        mock_cerrar.assert_called_once_with(12345, "TP alcanzado")

    def test_verificar_sl_tp_no_tocado(self):
        """Valida que NO detecta SL/TP si no han sido tocados."""
        pos = {
            'simbolo': 'EURUSD',
            'tipo': 'BUY',
            'sl': 1.0780,
            'tp': 1.0900,
            'precio_apertura': 1.0800
        }

        with patch.object(self.monitor, '_cerrar_posicion') as mock_cerrar:
            resultado = self.monitor._verificar_sl_tp(pos, 12345, 20.0, 1.0820)

        assert resultado is False
        mock_cerrar.assert_not_called()