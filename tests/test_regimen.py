#!/usr/bin/env python3
"""
tests/test_regimen.py (V1.0)
Valida la clasificación de régimen de mercado.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from analysis.regimen import MarketRegimeFilter, RegimenMercado, RegimenData


class TestRegimen:
    """Validación de la clasificación de régimen."""
    
    def setup_method(self):
        """Configura el filtro de régimen."""
        self.filter = MarketRegimeFilter(modo_backtest=True)
    
    def _crear_df_tendencia_alcista(self, n=100, precio_base=1.0800):
        """Crea DataFrame con tendencia alcista fuerte."""
        np.random.seed(42)
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='1h',
            tz='UTC'
        )
        
        tendencia = np.linspace(0, 0.02, n)  # Tendencia alcista fuerte
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
    
    def _crear_df_rango(self, n=100, precio_base=1.0800):
        """Crea DataFrame en rango (sin tendencia)."""
        np.random.seed(42)
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='1h',
            tz='UTC'
        )
        
        # Rango: precio oscila entre 1.0790 y 1.0810
        close = precio_base + np.random.randn(n) * 0.0005
        
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
    
    def test_clasificar_tendencia_alcista(self):
        """Valida clasificación de tendencia alcista."""
        df_h1 = self._crear_df_tendencia_alcista()
        df_h4 = self._crear_df_tendencia_alcista(n=50, precio_base=1.0780)
        
        resultado = self.filter.clasificar('EURUSD', df_h4, df_h1)
        
        assert resultado.regimen in [RegimenMercado.TREND_ALCISTA_FUERTE, RegimenMercado.TREND_ALCISTA_DEBIL]
        assert resultado.confianza > 30
    
    def test_clasificar_rango(self):
        """Valida clasificación de rango."""
        df_h1 = self._crear_df_rango()
        df_h4 = self._crear_df_rango(n=50)
        
        resultado = self.filter.clasificar('EURUSD', df_h4, df_h1)
        
        assert resultado.regimen in [RegimenMercado.RANGO_AMPLIO, RegimenMercado.RANGO_APRETADO]
    
    def test_direccion_favor_alcista(self):
        """Valida que la dirección favorita es alcista en tendencia alcista."""
        df_h1 = self._crear_df_tendencia_alcista()
        df_h4 = self._crear_df_tendencia_alcista(n=50, precio_base=1.0780)
        
        resultado = self.filter.clasificar('EURUSD', df_h4, df_h1)
        
        assert resultado.direccion_favor in ['ALCISTA', 'NONE']
        assert resultado.direccion_favor != 'BAJISTA'
    
    def test_direccion_favor_bajista(self):
        """Valida que la dirección favorita es bajista en tendencia bajista."""
        # Crear tendencia bajista
        np.random.seed(42)
        n = 100
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq='1h', tz='UTC')
        tendencia = np.linspace(0, -0.02, n)  # Tendencia bajista
        close = 1.0800 + tendencia
        
        df_h1 = pd.DataFrame({
            'Open': close - 0.0001,
            'High': close + 0.0002,
            'Low': close - 0.0002,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        df_h1['High'] = df_h1[['Open', 'Close', 'High']].max(axis=1)
        df_h1['Low'] = df_h1[['Open', 'Close', 'Low']].min(axis=1)
        
        # H4 también bajista
        np.random.seed(43)
        n_h4 = 50
        fechas_h4 = pd.date_range(end=datetime.now(timezone.utc), periods=n_h4, freq='4h', tz='UTC')
        tendencia_h4 = np.linspace(0, -0.015, n_h4)
        close_h4 = 1.0780 + tendencia_h4
        
        df_h4 = pd.DataFrame({
            'Open': close_h4 - 0.0001,
            'High': close_h4 + 0.0002,
            'Low': close_h4 - 0.0002,
            'Close': close_h4,
            'Volume': np.random.randint(100, 1000, n_h4)
        }, index=fechas_h4)
        df_h4['High'] = df_h4[['Open', 'Close', 'High']].max(axis=1)
        df_h4['Low'] = df_h4[['Open', 'Close', 'Low']].min(axis=1)
        
        resultado = self.filter.clasificar('EURUSD', df_h4, df_h1)
        
        assert resultado.direccion_favor in ['BAJISTA', 'NONE']
        assert resultado.direccion_favor != 'ALCISTA'
    
    def test_crear_regimen_incierto(self):
        """Valida la creación de régimen incierto."""
        resultado = self.filter._crear_regimen_incierto(30)
        
        assert resultado.regimen == RegimenMercado.INCERTO
        assert resultado.confianza == 30
    
    def test_get_pesos_por_fase(self):
        """Valida los pesos por fase para diferentes regímenes."""
        pesos_tendencia = self.filter.get_pesos_por_fase(RegimenMercado.TREND_ALCISTA_FUERTE)
        pesos_rango = self.filter.get_pesos_por_fase(RegimenMercado.RANGO_APRETADO)
        
        assert abs(sum(pesos_tendencia.values()) - 1.0) < 0.01
        assert abs(sum(pesos_rango.values()) - 1.0) < 0.01
    
    def test_get_ajustes_para_modo(self):
        """Valida los ajustes por modo."""
        ajustes = self.filter.get_ajustes_para_modo('RETEST', RegimenMercado.TREND_ALCISTA_FUERTE)
        
        assert 'sl_mult' in ajustes
        assert 'tp_mult' in ajustes
        assert 'lote_factor' in ajustes
    
    def test_get_umbrales_para_fase2(self):
        """Valida los umbrales para Fase 2."""
        umbrales = self.filter.get_umbrales_para_fase2(RegimenMercado.TREND_ALCISTA_FUERTE)
        
        assert 'adx_minimo' in umbrales
        assert 'vol_minimo' in umbrales
        assert 'rsi_tolerancia' in umbrales
    
    def test_votacion(self):
        """Valida el sistema de votación."""
        indicadores = {
            'adx_h1': 30.0,
            'adx_h4': 25.0,
            'er_kaufman': 0.4,
            'bb_width': 15.0,
            'estructura': 'ALCISTA',
            'chop_index': 35.0,
        }
        
        regimen, confianza, votos, confianzas, ponderados = self.filter._votar(indicadores)
        
        assert regimen is not None
        assert confianza > 0
        assert isinstance(votos, dict)
        assert len(votos) > 0
    
    def test_clasificar_con_fallback(self):
        """Valida que clasifica con fallback si no hay suficientes datos."""
        # DataFrame con menos de 50 velas
        df_h1 = pd.DataFrame({'Close': [1.0] * 30, 'High': [1.0] * 30, 'Low': [1.0] * 30})
        df_h4 = None
        
        resultado = self.filter.clasificar('EURUSD', df_h4, df_h1)
        
        assert resultado is not None
        assert resultado.regimen is not None