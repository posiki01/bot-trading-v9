#!/usr/bin/env python3
"""
tests/test_capas_rapido.py (V1.2 - CORREGIDO DEFINITIVO)
Valida el análisis rápido (Capa 1) del sistema de análisis por capas.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from analysis.capas_rapido import AnalisisRapidoEngine


class TestAnalisisRapido:
    """Validación del análisis rápido (Capa 1)."""
    
    def setup_method(self):
        """Configura el motor."""
        self.umbrales = {
            'volumen_minimo': 0.10,
            'rsi_extremo_superior': 80,
            'rsi_extremo_inferior': 20,
            'cambio_minimo_vela': 0.01,
            'adx_minimo': 10,
            'adx_fuerte': 20,
            'distancia_nivel_max': 3.0,
            'score_minimo': 20,
            'confianza_wyckoff_min': 30,
        }
        
        self.engine = AnalisisRapidoEngine(
            umbrales=self.umbrales,
            modo_backtest=True
        )
    
    def _crear_df_tendencia_alcista(self, n=100, precio_base=1.0800):
        """Crea un DataFrame con tendencia alcista perfecta (sin ruido)."""
        np.random.seed(42)
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='1h',
            tz='UTC'
        )
        
        # ✅ CORRECCIÓN: Tendencia perfectamente alcista (sin ruido)
        tendencia = np.linspace(0, 0.015, n)
        close = precio_base + tendencia
        
        df = pd.DataFrame({
            'Open': close - 0.0001,
            'High': close + 0.0002,
            'Low': close - 0.0002,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        
        df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
        df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
        
        return df
    
    def test_df_insuficiente(self):
        """Valida que rechaza DataFrame con menos de 20 velas."""
        df = pd.DataFrame({'Close': [1.0] * 10})
        
        resultado = self.engine.ejecutar(df, 'EURUSD')
        
        assert resultado.valido is False
        assert resultado.pasa_filtro is False
    
    def test_df_none(self):
        """Valida que rechaza DataFrame None."""
        resultado = self.engine.ejecutar(None, 'EURUSD')
        
        assert resultado.valido is False
        assert resultado.pasa_filtro is False
    
    def test_calcular_rsi_valido(self):
        """Valida el cálculo de RSI con datos válidos."""
        df = self._crear_df_tendencia_alcista()
        
        rsi = self.engine._calcular_rsi_corregido(df['Close'], 'EURUSD')
        
        assert 0 <= rsi <= 100
        assert rsi > 50  # Tendencia alcista = RSI > 50
    
    def test_calcular_rsi_nan(self):
        """Valida que RSI retorna 50 si hay NaN."""
        precios = pd.Series([np.nan] * 20)
        
        rsi = self.engine._calcular_rsi_corregido(precios, 'EURUSD')
        
        assert rsi == 50.0
    
    def test_calcular_rsi_constante(self):
        """Valida que RSI retorna 50 si todos los precios son iguales."""
        precios = pd.Series([1.0] * 20)
        
        rsi = self.engine._calcular_rsi_corregido(precios, 'EURUSD')
        
        assert rsi == 50.0
    
    def test_calcular_atr(self):
        """Valida el cálculo de ATR."""
        df = self._crear_df_tendencia_alcista()
        
        atr = self.engine._calcular_atr(df)
        
        assert atr > 0
    
    def test_pasa_filtro_con_tendencia(self):
        """Valida que pasa el filtro con tendencia clara y volumen."""
        df = self._crear_df_tendencia_alcista()
        df.iloc[-1, df.columns.get_loc('Close')] = 1.0830  # Última vela con movimiento
        
        # Añadir volumen alto en la última vela
        df.iloc[-1, df.columns.get_loc('Volume')] = 5000
        
        resultado = self.engine.ejecutar(df, 'EURUSD')
        
        assert resultado.valido is True
        assert resultado.pasa_filtro is True
    
    def test_precio_actual_override(self):
        """Valida que usa el precio actual si se proporciona."""
        df = self._crear_df_tendencia_alcista()
        
        resultado = self.engine.ejecutar(df, 'EURUSD', precio_actual=1.0850)
        
        assert resultado.precio_actual == 1.0850
    
    def test_tendencia_alcista(self):
        """Valida que detecta tendencia alcista."""
        df = self._crear_df_tendencia_alcista()
        
        resultado = self.engine.ejecutar(df, 'EURUSD')
        
        # ✅ Verificar que la tendencia es ALCISTA
        assert resultado.tendencia_corta == 'ALCISTA'
    
    def test_volumen_relativo(self):
        """Valida el cálculo de volumen relativo."""
        df = self._crear_df_tendencia_alcista()
        df.iloc[-1, df.columns.get_loc('Volume')] = 5000  # Volumen alto
        
        resultado = self.engine.ejecutar(df, 'EURUSD')
        
        assert resultado.volumen_relativo > 1.0