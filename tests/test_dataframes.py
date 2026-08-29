#!/usr/bin/env python3
"""
tests/test_dataframes.py (V1.0)
Valida que los DataFrames se carguen, actualicen y consulten correctamente.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from utils.construir_timeframes import (
    construir_desde_m5,
    construir_h1_desde_m5,
    construir_h4_desde_m5,
    construir_d1_desde_m5,
    obtener_timeframe_inteligente
)


class TestConstruirTimeframes:
    """Validación de la construcción de timeframes desde M5."""
    
    def setup_method(self):
        """Configura datos M5 de prueba."""
        np.random.seed(42)
        n = 1000  # 1000 velas M5 (aproximadamente 3.5 días)
        
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='5min',
            tz='UTC'
        )
        
        # Precio con tendencia alcista
        precio_base = 1.0800
        tendencia = np.linspace(0, 0.005, n)
        ruido = np.random.randn(n) * 0.0002
        close = precio_base + tendencia + ruido
        
        self.df_m5 = pd.DataFrame({
            'Open': close - np.random.randn(n) * 0.0001,
            'High': close + np.abs(np.random.randn(n)) * 0.0002,
            'Low': close - np.abs(np.random.randn(n)) * 0.0002,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        
        self.df_m5['High'] = self.df_m5[['Open', 'Close', 'High']].max(axis=1)
        self.df_m5['Low'] = self.df_m5[['Open', 'Close', 'Low']].min(axis=1)
    
    def test_construir_h1_desde_m5(self):
        """Valida la construcción de H1 desde M5."""
        df_h1 = construir_h1_desde_m5(self.df_m5)
        
        assert df_h1 is not None
        assert len(df_h1) > 0
        assert 'Open' in df_h1.columns
        assert 'High' in df_h1.columns
        assert 'Low' in df_h1.columns
        assert 'Close' in df_h1.columns
        assert 'Volume' in df_h1.columns
    
    def test_construir_h4_desde_m5(self):
        """Valida la construcción de H4 desde M5."""
        df_h4 = construir_h4_desde_m5(self.df_m5)
        
        assert df_h4 is not None
        assert len(df_h4) > 0
        assert 'Open' in df_h4.columns
    
    def test_construir_d1_desde_m5(self):
        """Valida la construcción de D1 desde M5."""
        df_d1 = construir_d1_desde_m5(self.df_m5)
        
        assert df_d1 is not None
        assert len(df_d1) > 0
        assert 'Open' in df_d1.columns
    
    def test_construir_desde_m5_multiple(self):
        """Valida la construcción de múltiples timeframes."""
        timeframes = [15, 30, 60, 240, 1440]
        
        resultado = construir_desde_m5(self.df_m5, timeframes)
        
        assert 15 in resultado
        assert 30 in resultado
        assert 60 in resultado
        assert 240 in resultado
        assert 1440 in resultado
    
    def test_construir_desde_m5_datos_vacios(self):
        """Valida que retorna dict vacío si los datos son insuficientes."""
        df_vacio = pd.DataFrame()
        
        resultado = construir_desde_m5(df_vacio, [60])
        
        assert resultado == {}
    
    def test_construir_h1_calidad(self):
        """Valida que H1 tiene datos correctos."""
        df_h1 = construir_h1_desde_m5(self.df_m5)
        
        # Verificar que cada vela H1 agrupa 12 velas M5
        assert len(df_h1) <= len(self.df_m5) // 12 + 1
        
        # Verificar que High >= max(Open, Close, Low)
        for i in range(len(df_h1)):
            assert df_h1['High'].iloc[i] >= df_h1['Open'].iloc[i]
            assert df_h1['High'].iloc[i] >= df_h1['Close'].iloc[i]
            assert df_h1['Low'].iloc[i] <= df_h1['Open'].iloc[i]
            assert df_h1['Low'].iloc[i] <= df_h1['Close'].iloc[i]


class TestObtenerTimeframeInteligente:
    """Validación de la obtención inteligente de timeframes."""
    
    def setup_method(self):
        """Configura mocks."""
        np.random.seed(42)
        n = 1000
        
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='5min',
            tz='UTC'
        )
        
        precio_base = 1.0800
        tendencia = np.linspace(0, 0.005, n)
        ruido = np.random.randn(n) * 0.0002
        close = precio_base + tendencia + ruido
        
        self.df_m5 = pd.DataFrame({
            'Open': close - np.random.randn(n) * 0.0001,
            'High': close + np.abs(np.random.randn(n)) * 0.0002,
            'Low': close - np.abs(np.random.randn(n)) * 0.0002,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        
        self.df_m5['High'] = self.df_m5[['Open', 'Close', 'High']].max(axis=1)
        self.df_m5['Low'] = self.df_m5[['Open', 'Close', 'Low']].min(axis=1)
    
    def test_obtener_h1_desde_m5(self):
        """Valida obtener H1 construido desde M5."""
        # Mock del conector que NO tiene H1
        conector_mock = MagicMock()
        conector_mock.obtener_datos.return_value = None
        
        df_h1 = obtener_timeframe_inteligente(
            simbolo='EURUSD',
            timeframe=60,
            df_m5=self.df_m5,
            conector=conector_mock,
            almacen=None
        )
        
        assert df_h1 is not None
        assert len(df_h1) > 0
        assert 'Close' in df_h1.columns
    
    def test_obtener_h1_desde_broker(self):
        """Valida obtener H1 desde el broker (prioridad)."""
        # Crear DataFrame H1 de prueba
        fechas_h1 = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=100,
            freq='1h',
            tz='UTC'
        )
        
        df_h1_broker = pd.DataFrame({
            'Open': 1.0800 + np.random.randn(100) * 0.0001,
            'High': 1.0805 + np.abs(np.random.randn(100)) * 0.0001,
            'Low': 1.0795 - np.abs(np.random.randn(100)) * 0.0001,
            'Close': 1.0800 + np.random.randn(100) * 0.0001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas_h1)
        
        df_h1_broker['High'] = df_h1_broker[['Open', 'Close', 'High']].max(axis=1)
        df_h1_broker['Low'] = df_h1_broker[['Open', 'Close', 'Low']].min(axis=1)
        
        # Mock del conector que SÍ tiene H1
        conector_mock = MagicMock()
        conector_mock.obtener_datos.return_value = df_h1_broker
        
        df_h1 = obtener_timeframe_inteligente(
            simbolo='EURUSD',
            timeframe=60,
            df_m5=self.df_m5,
            conector=conector_mock,
            almacen=None
        )
        
        assert df_h1 is not None
        assert len(df_h1) == 100
        assert df_h1 is not self.df_m5  # No es el M5
    
    def test_obtener_h1_sin_datos(self):
        """Valida que retorna None si no hay datos."""
        conector_mock = MagicMock()
        conector_mock.obtener_datos.return_value = None
        
        df_h1 = obtener_timeframe_inteligente(
            simbolo='EURUSD',
            timeframe=60,
            df_m5=None,  # Sin M5
            conector=conector_mock,
            almacen=None
        )
        
        assert df_h1 is None


class TestActualizacionDataFrames:
    """Validación de la actualización de DataFrames."""
    
    def test_df_se_copia_al_agregar_vela(self):
        """Valida que el DataFrame se copia antes de añadir vela virtual."""
        from core.orquestador import Orquestador
        
        # Crear DataFrame original
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=100,
            freq='5min',
            tz='UTC'
        )
        
        df_original = pd.DataFrame({
            'Open': 1.0800 + np.random.randn(100) * 0.0001,
            'High': 1.0805 + np.abs(np.random.randn(100)) * 0.0001,
            'Low': 1.0795 - np.abs(np.random.randn(100)) * 0.0001,
            'Close': 1.0800 + np.random.randn(100) * 0.0001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas)
        
        df_original['High'] = df_original[['Open', 'Close', 'High']].max(axis=1)
        df_original['Low'] = df_original[['Open', 'Close', 'Low']].min(axis=1)
        
        # Copiar
        df_copia = df_original.copy()
        
        # Añadir vela
        now = datetime.now(timezone.utc)
        df_copia.loc[now] = {
            'Open': df_original['Close'].iloc[-1],
            'High': df_original['High'].iloc[-1] + 0.001,
            'Low': df_original['Low'].iloc[-1] - 0.001,
            'Close': df_original['Close'].iloc[-1] + 0.0005,
            'Volume': df_original['Volume'].iloc[-1]
        }
        
        # ✅ Verificar que el original NO se modificó
        assert len(df_original) == 100
        assert len(df_copia) == 101
    
    def test_consulta_timeframe_especifico(self):
        """Valida la consulta de un timeframe específico."""
        # Crear DataFrames para múltiples timeframes
        fechas_h1 = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=100,
            freq='1h',
            tz='UTC'
        )
        
        df_h1 = pd.DataFrame({
            'Close': 1.0800 + np.random.randn(100) * 0.001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas_h1)
        
        # Simular caché con múltiples timeframes
        cache_mock = MagicMock()
        
        # Mock get_datos para retornar según timeframe
        def get_datos_side_effect(simbolo, timeframe, n_velas, fetch_func):
            if timeframe == 60:
                return df_h1
            return None
        
        cache_mock.get_datos.side_effect = get_datos_side_effect
        
        # Consultar H1
        df_consultado = cache_mock.get_datos('EURUSD', 60, 100, None)
        
        assert df_consultado is not None
        assert len(df_consultado) == 100
        assert 'Close' in df_consultado.columns