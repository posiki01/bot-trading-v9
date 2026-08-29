#!/usr/bin/env python3
"""
tests/test_vela_virtual.py (V1.2 - CORREGIDO DEFINITIVO)
Valida que la vela virtual siempre tenga el precio más actualizado.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from core.orquestador import Orquestador


class TestVelaVirtual:
    """Validación de la vela virtual con precio actualizado."""
    
    def setup_method(self):
        """Configura el orquestador mock."""
        self.orquestador = MagicMock(spec=Orquestador)
        self.orquestador.modo_backtest = True
        self.orquestador.config = MagicMock()
        self.orquestador.config.MAGIC_NUMBER = 123456
        
        # Mock del conector MT5
        self.orquestador.mt5 = MagicMock()
        self.orquestador.mt5.obtener_precio.return_value = {
            'bid': 1.0805,
            'ask': 1.0810,
            'spread_pips': 0.5,
            'digits': 5,
            'point': 0.00001,
            'pip_size': 0.0001
        }
        
        # Mock de la caché
        self.orquestador.cache = MagicMock()
        
        # Configurar datos M5 de la caché
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=100,
            freq='5min',
            tz='UTC'
        )
        
        df_m5 = pd.DataFrame({
            'Open': 1.0800 + np.random.randn(100) * 0.0001,
            'High': 1.0805 + np.abs(np.random.randn(100)) * 0.0001,
            'Low': 1.0795 - np.abs(np.random.randn(100)) * 0.0001,
            'Close': 1.0800 + np.random.randn(100) * 0.0001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas)
        
        df_m5['High'] = df_m5[['Open', 'Close', 'High']].max(axis=1)
        df_m5['Low'] = df_m5[['Open', 'Close', 'Low']].min(axis=1)
        
        self.orquestador.cache.get_datos.return_value = df_m5
    
    def _crear_orquestador(self):
        """Crea una instancia de Orquestador con atributos mínimos."""
        with patch.object(Orquestador, '__init__', lambda self: None):
            orquestador = Orquestador.__new__(Orquestador)
            orquestador.modo_backtest = True
            orquestador.mt5 = self.orquestador.mt5
            orquestador.cache = self.orquestador.cache
            orquestador.logger = MagicMock()  # ✅ AÑADIR LOGGER
            return orquestador
    
    def test_vela_virtual_precio_actual(self):
        """Valida que la vela virtual usa el precio actual del tick."""
        orquestador = self._crear_orquestador()
        
        df_resultado = orquestador._obtener_df_m5_con_precio_real('EURUSD')
        
        assert df_resultado is not None
        assert len(df_resultado) > 0
        
        # ✅ Verificar que la última vela tiene el precio del tick
        ultima_vela = df_resultado.iloc[-1]
        assert ultima_vela['Close'] == pytest.approx(1.08075, abs=0.00001)
        assert ultima_vela['High'] >= 1.0810
        assert ultima_vela['Low'] <= 1.0805
    
    def test_vela_virtual_attrs(self):
        """Valida que la vela virtual tiene los atributos correctos."""
        orquestador = self._crear_orquestador()
        
        df_resultado = orquestador._obtener_df_m5_con_precio_real('EURUSD')
        
        # ✅ Verificar atributos
        assert 'precio_tick' in df_resultado.attrs
        assert 'precio_analisis' in df_resultado.attrs
        assert 'precio_entrada_compra' in df_resultado.attrs
        assert 'precio_entrada_venta' in df_resultado.attrs
        assert 'digits' in df_resultado.attrs
        
        # ✅ Verificar valores
        assert df_resultado.attrs['precio_analisis'] == pytest.approx(1.08075, abs=0.00001)
        assert df_resultado.attrs['precio_entrada_compra'] == 1.0810
        assert df_resultado.attrs['precio_entrada_venta'] == 1.0805
        assert df_resultado.attrs['digits'] == 5
    
    def test_vela_virtual_sin_tick(self):
        """Valida que si no hay tick, usa los datos existentes."""
        with patch.object(Orquestador, '__init__', lambda self: None):
            orquestador = Orquestador.__new__(Orquestador)
            orquestador.modo_backtest = True
            orquestador.mt5 = MagicMock()
            orquestador.mt5.obtener_precio.return_value = None  # Sin tick
            orquestador.cache = self.orquestador.cache
            orquestador.logger = MagicMock()  # ✅ AÑADIR LOGGER
            
            df_resultado = orquestador._obtener_df_m5_con_precio_real('EURUSD')
            
            # ✅ Si no hay tick, retorna los datos existentes
            assert df_resultado is not None
            assert len(df_resultado) > 0
    
    def test_vela_virtual_precio_invalido(self):
        """Valida que si el precio es inválido, usa los datos existentes."""
        with patch.object(Orquestador, '__init__', lambda self: None):
            orquestador = Orquestador.__new__(Orquestador)
            orquestador.modo_backtest = True
            orquestador.mt5 = MagicMock()
            orquestador.mt5.obtener_precio.return_value = {
                'bid': 0,  # Precio inválido
                'ask': 0,
                'spread_pips': 0,
                'digits': 5,
                'point': 0.00001,
                'pip_size': 0.0001
            }
            orquestador.cache = self.orquestador.cache
            orquestador.logger = MagicMock()  # ✅ AÑADIR LOGGER
            
            df_resultado = orquestador._obtener_df_m5_con_precio_real('EURUSD')
            
            # ✅ Si el precio es inválido, retorna los datos existentes
            assert df_resultado is not None
            assert len(df_resultado) > 0
    
    def test_vela_virtual_actualiza_precio(self):
        """Valida que la vela virtual actualiza el precio en cada llamada."""
        orquestador = self._crear_orquestador()
        
        # Primera llamada: precio 1.08075
        df_1 = orquestador._obtener_df_m5_con_precio_real('EURUSD')
        precio_1 = df_1.iloc[-1]['Close']
        
        # Segunda llamada: precio cambia
        self.orquestador.mt5.obtener_precio.return_value = {
            'bid': 1.0808,
            'ask': 1.0813,
            'spread_pips': 0.5,
            'digits': 5,
            'point': 0.00001,
            'pip_size': 0.0001
        }
        
        df_2 = orquestador._obtener_df_m5_con_precio_real('EURUSD')
        precio_2 = df_2.iloc[-1]['Close']
        
        # ✅ Verificar que el precio se actualizó
        assert precio_1 == pytest.approx(1.08075, abs=0.00001)
        assert precio_2 == pytest.approx(1.08105, abs=0.00001)  # ✅ USAR APPROX
        assert precio_1 != precio_2
    
    def test_vela_virtual_con_pipeline(self):
        """Valida la integración de la vela virtual con el pipeline."""
        # Simular que el orquestador tiene un pipeline
        pipeline_mock = MagicMock()
        pipeline_mock.obtener_activos.return_value = []
        
        orquestador = self._crear_orquestador()
        orquestador.pipeline = pipeline_mock
        
        # Obtener DataFrame con vela virtual
        df_resultado = orquestador._obtener_df_m5_con_precio_real('EURUSD')
        
        assert df_resultado is not None
        assert len(df_resultado) > 0
        assert df_resultado.attrs['precio_tick'] is not None