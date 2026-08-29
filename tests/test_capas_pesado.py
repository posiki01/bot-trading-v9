#!/usr/bin/env python3
"""
tests/test_capas_pesado.py (V1.1 - CORREGIDO)
Valida el análisis pesado (Capa 3) del sistema de análisis por capas.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from analysis.capas_pesado import AnalisisPesadoEngine
from analysis.capas import AnalisisMedio


class TestAnalisisPesado:
    """Validación del análisis pesado (Capa 3)."""
    
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
        
        # Mock del análisis técnico
        self.analisis_tecnico_mock = MagicMock()
        
        self.engine = AnalisisPesadoEngine(
            analisis_tecnico=self.analisis_tecnico_mock,
            umbrales=self.umbrales,
            modo_backtest=True,
            modo_depuracion=True
        )
    
    def _crear_df_completo(self, n=150, precio_base=1.0800):
        """Crea un DataFrame completo."""
        np.random.seed(42)
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='1h',
            tz='UTC'
        )
        
        tendencia = np.linspace(0, 0.01, n)
        ruido = np.random.randn(n) * 0.0003
        close = precio_base + tendencia + ruido
        
        df = pd.DataFrame({
            'Open': close - np.random.randn(n) * 0.0002,
            'High': close + np.abs(np.random.randn(n)) * 0.0003,
            'Low': close - np.abs(np.random.randn(n)) * 0.0003,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        
        df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
        df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
        
        return df
    
    def test_df_insuficiente(self):
        """Valida que rechaza DataFrame con menos de 100 velas."""
        df = pd.DataFrame({'Close': [1.0] * 50})
        
        resultado = self.engine.ejecutar(df, 'EURUSD')
        
        assert resultado.valido is False
    
    def test_df_none(self):
        """Valida que rechaza DataFrame None."""
        resultado = self.engine.ejecutar(None, 'EURUSD')
        
        assert resultado.valido is False
    
    def test_detectar_patrones_pin_bar_alcista(self):
        """Valida la detección de Pin Bar Alcista."""
        df = self._crear_df_completo()
        
        # ✅ CORRECCIÓN: Sombra inferior MÁS larga para que sombra_inf/rango > 0.6
        df.iloc[-1, df.columns.get_loc('Open')] = 1.0810
        df.iloc[-1, df.columns.get_loc('Close')] = 1.0815
        df.iloc[-1, df.columns.get_loc('High')] = 1.0820
        df.iloc[-1, df.columns.get_loc('Low')] = 1.0790  # ✅ Bajar el Low para sombra más larga
        
        patrones, principal, calidad = self.engine._detectar_patrones_mejorado(df)
        
        assert 'PIN_BAR_ALCISTA' in patrones
        assert principal == 'PIN_BAR_ALCISTA'
        assert calidad > 0
    
    def test_detectar_patrones_engulfing_alcista(self):
        """Valida la detección de Engulfing Alcista."""
        df = self._crear_df_completo()
        
        # Vela anterior bajista
        df.iloc[-2, df.columns.get_loc('Open')] = 1.0820
        df.iloc[-2, df.columns.get_loc('Close')] = 1.0810
        df.iloc[-2, df.columns.get_loc('High')] = 1.0825
        df.iloc[-2, df.columns.get_loc('Low')] = 1.0805
        
        # Vela actual alcista que envuelve a la anterior
        df.iloc[-1, df.columns.get_loc('Open')] = 1.0805
        df.iloc[-1, df.columns.get_loc('Close')] = 1.0825
        df.iloc[-1, df.columns.get_loc('High')] = 1.0830
        df.iloc[-1, df.columns.get_loc('Low')] = 1.0800
        
        patrones, principal, calidad = self.engine._detectar_patrones_mejorado(df)
        
        assert 'ENGULFING_ALCISTA' in patrones
    
    def test_detectar_patrones_doji(self):
        """Valida la detección de Doji."""
        df = self._crear_df_completo()
        
        # Crear una vela Doji
        df.iloc[-1, df.columns.get_loc('Open')] = 1.0810
        df.iloc[-1, df.columns.get_loc('Close')] = 1.0810  # Mismo precio
        df.iloc[-1, df.columns.get_loc('High')] = 1.0820
        df.iloc[-1, df.columns.get_loc('Low')] = 1.0800
        
        patrones, principal, calidad = self.engine._detectar_patrones_mejorado(df)
        
        assert 'DOJI' in patrones
    
    def test_detectar_patrones_hammer(self):
        """Valida la detección de Hammer."""
        df = self._crear_df_completo()
        
        # Crear una vela Hammer
        df.iloc[-1, df.columns.get_loc('Open')] = 1.0810
        df.iloc[-1, df.columns.get_loc('Close')] = 1.0815
        df.iloc[-1, df.columns.get_loc('High')] = 1.0820
        df.iloc[-1, df.columns.get_loc('Low')] = 1.0790  # Sombra inferior larga
        
        # Vela anterior con cierre más bajo
        df.iloc[-2, df.columns.get_loc('Close')] = 1.0805
        
        patrones, principal, calidad = self.engine._detectar_patrones_mejorado(df)
        
        assert 'HAMMER' in patrones
    
    def test_detectar_order_blocks(self):
        """Valida la detección de Order Blocks."""
        df = self._crear_df_completo()
        
        bull_ob, bear_ob, ob_cercano = self.engine._detectar_order_blocks_corregido(df, None)
        
        # ✅ El resultado puede ser None si no hay OB, pero no debe fallar
        assert bull_ob is None or isinstance(bull_ob, dict)
        assert bear_ob is None or isinstance(bear_ob, dict)
    
    def test_detectar_wyckoff(self):
        """Valida la detección de Wyckoff."""
        df = self._crear_df_completo()
        
        fase, confianza = self.engine._detectar_wyckoff_mejorado(df)
        
        assert fase in ['NEUTRAL', 'ACUMULACION', 'DISTRIBUCION', 'SPRING', 'UPTHRUST', 'TENDENCIA_ALCISTA', 'TENDENCIA_BAJISTA']
        assert 0 <= confianza <= 100
    
    def test_calcular_scores(self):
        """Valida el cálculo de scores."""
        # Crear análisis medio mock
        medio_mock = MagicMock()
        medio_mock.rsi = 58.0
        medio_mock.adx = 25.0
        medio_mock.macd_histogram = 0.0002
        medio_mock.bb_width_pct = 15.0
        medio_mock.en_nivel_clave = True
        medio_mock.soporte_hits = 3
        medio_mock.resistencia_hits = 2
        medio_mock.sma20 = 1.0850
        medio_mock.sma50 = 1.0830
        
        # Calcular scores individuales
        score_estructura = self.engine._calcular_score_estructura_mejorado(
            ['PIN_BAR_ALCISTA', 'ENGULFING_ALCISTA'], True, 70.0, medio_mock
        )
        
        score_momentum = self.engine._calcular_score_momentum_mejorado(medio_mock)
        
        score_confluencia = self.engine._calcular_score_confluencia_mejorado(
            medio_mock, 'BULLISH', ['PIN_BAR_ALCISTA'], True
        )
        
        score_institucional = self.engine._calcular_score_institucional_mejorado(
            'ACUMULACION', True, {'fuerza': 70}, None
        )
        
        assert 0 <= score_estructura <= 35
        assert 0 <= score_momentum <= 35
        assert 0 <= score_confluencia <= 35
        assert 0 <= score_institucional <= 35
    
    def test_analisis_pesado_completo(self):
        """Valida el análisis pesado completo."""
        df = self._crear_df_completo()
        
        resultado = self.engine.ejecutar(df, 'EURUSD')
        
        assert resultado.valido is True
        assert isinstance(resultado.patrones_encontrados, list)
        assert resultado.score_estructura >= 0
        assert resultado.score_momentum >= 0
        assert resultado.score_confluencia >= 0
        assert resultado.score_institucional >= 0
    
    def test_calcular_rsi_serie(self):
        """Valida el cálculo de RSI como serie."""
        df = self._crear_df_completo()
        
        rsi_serie = self.engine._calcular_rsi_serie_corregido(df['Close'], 'EURUSD')
        
        assert rsi_serie is not None
        assert len(rsi_serie) == len(df)
    
    def test_calcular_macd_corregido(self):
        """Valida el cálculo de MACD corregido."""
        df = self._crear_df_completo()
        
        macd = self.engine._calcular_macd_corregido(df['Close'], 'EURUSD')
        
        assert macd['macd'] is not None
        assert macd['signal'] is not None
        assert macd['histogram'] is not None