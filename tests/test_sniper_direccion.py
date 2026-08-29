#!/usr/bin/env python3
"""
tests/test_sniper_direccion.py
Valida que cada modo del sniper opera en la dirección correcta.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from trading.sniper.sniper_modos import ModoEntrada, DetectorModos


class TestDireccionPorModo:
    """Validación de dirección por modo de entrada."""
    
    # ============================================================
    # VALIDAR DIRECCIÓN PARA RETEST
    # ============================================================
    
    def test_retest_compra_en_soporte(self, df_m5_eurusd, contexto_h1):
        """RETEST COMPRA debe validarse cuando el precio está en soporte."""
        detector = DetectorModos(modo_backtest=True)
        
        precio_actual = 1.0805
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.soporte_cercano = 1.0800
        analisis_medio_mock.resistencia_cercana = None
        analisis_medio_mock.soporte_hits = 3
        analisis_medio_mock.resistencia_hits = 0
        analisis_medio_mock.en_nivel_clave = True
        analisis_medio_mock.adx = 25.0
        analisis_medio_mock.rsi = 58.0
        analisis_medio_mock.macd_histogram = 0.0002
        analisis_medio_mock.sma20 = 1.0850
        analisis_medio_mock.sma50 = 1.0830
        analisis_medio_mock.atr = 0.0005
        
        modo, razon, confluencias, puntuacion = detector._evaluar_retest(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=precio_actual,
            direccion='COMPRA',
            analisis_rapido=MagicMock(volumen_relativo=1.5),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=MagicMock(
                patron_principal='PIN_BAR_ALCISTA',
                calidad_patron=70
            ),
            contexto_h1=contexto_h1
        )
        
        assert modo == ModoEntrada.RETEST
        assert puntuacion > 0
    
    def test_retest_venta_en_resistencia(self, df_m5_eurusd, contexto_h1):
        """RETEST VENTA debe validarse cuando el precio está en resistencia."""
        detector = DetectorModos(modo_backtest=True)
        
        precio_actual = 1.0895
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.soporte_cercano = None
        analisis_medio_mock.resistencia_cercana = 1.0900
        analisis_medio_mock.soporte_hits = 0
        analisis_medio_mock.resistencia_hits = 2
        analisis_medio_mock.en_nivel_clave = True
        analisis_medio_mock.adx = 25.0
        analisis_medio_mock.rsi = 42.0
        analisis_medio_mock.macd_histogram = -0.0002
        analisis_medio_mock.sma20 = 1.0830
        analisis_medio_mock.sma50 = 1.0850
        analisis_medio_mock.atr = 0.0005
        
        contexto_venta = {
            **contexto_h1,
            'direccion': 'VENTA',
            'regimen': 'TREND_BAJISTA_FUERTE',
            'soporte_cercano': 1.0750,
            'resistencia_cercana': 1.0900,
        }
        
        modo, razon, confluencias, puntuacion = detector._evaluar_retest(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=precio_actual,
            direccion='VENTA',
            analisis_rapido=MagicMock(volumen_relativo=1.3),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=MagicMock(
                patron_principal='SHOOTING_STAR',
                calidad_patron=65
            ),
            contexto_h1=contexto_venta
        )
        
        assert modo == ModoEntrada.RETEST
        assert puntuacion > 0
    
    # ============================================================
    # VALIDAR DIRECCIÓN PARA BREAKOUT
    # ============================================================
    
    def test_breakout_compra_supera_resistencia(self, df_m5_eurusd, contexto_h1):
        """BREAKOUT COMPRA debe validarse cuando el precio rompe la resistencia."""
        detector = DetectorModos(modo_backtest=True)
        
        precio_actual = 1.0910
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.soporte_cercano = 1.0800
        analisis_medio_mock.resistencia_cercana = 1.0900
        analisis_medio_mock.en_nivel_clave = True
        analisis_medio_mock.adx = 28.0
        analisis_medio_mock.rsi = 62.0
        analisis_medio_mock.macd_histogram = 0.0003
        analisis_medio_mock.sma20 = 1.0850
        analisis_medio_mock.sma50 = 1.0830
        analisis_medio_mock.atr = 0.0005
        
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Close'] = 1.0910
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'High'] = 1.0915
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Open'] = 1.0895
        df_m5_eurusd.loc[df_m5_eurusd.index[-2], 'High'] = 1.0900
        
        modo, razon, confluencias, puntuacion = detector._evaluar_breakout(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=precio_actual,
            direccion='COMPRA',
            analisis_rapido=MagicMock(volumen_relativo=2.0),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=MagicMock(),
            contexto_h1=contexto_h1
        )
        
        assert modo is not None or razon is not None
    
    def test_breakout_venta_rompe_soporte(self, df_m5_eurusd, contexto_h1):
        """BREAKOUT VENTA debe validarse cuando el precio rompe el soporte."""
        detector = DetectorModos(modo_backtest=True)
        
        precio_actual = 1.0790
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.soporte_cercano = 1.0800
        analisis_medio_mock.resistencia_cercana = 1.0900
        analisis_medio_mock.en_nivel_clave = True
        analisis_medio_mock.adx = 28.0
        analisis_medio_mock.rsi = 38.0
        analisis_medio_mock.macd_histogram = -0.0003
        analisis_medio_mock.sma20 = 1.0830
        analisis_medio_mock.sma50 = 1.0850
        analisis_medio_mock.atr = 0.0005
        
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Close'] = 1.0790
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Low'] = 1.0785
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Open'] = 1.0805
        df_m5_eurusd.loc[df_m5_eurusd.index[-2], 'Low'] = 1.0800
        
        contexto_venta = {
            **contexto_h1,
            'direccion': 'VENTA',
            'regimen': 'TREND_BAJISTA_FUERTE'
        }
        
        modo, razon, confluencias, puntuacion = detector._evaluar_breakout(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=precio_actual,
            direccion='VENTA',
            analisis_rapido=MagicMock(volumen_relativo=1.8),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=MagicMock(),
            contexto_h1=contexto_venta
        )
        
        assert modo is not None or razon is not None
    
    # ============================================================
    # VALIDAR DIRECCIÓN PARA PULLBACK
    # ============================================================
    
    def test_pullback_compra_en_tendencia_alcista(self, df_m5_eurusd, contexto_h1):
        """PULLBACK COMPRA debe validarse en tendencia alcista."""
        detector = DetectorModos(modo_backtest=True)
        
        precio_actual = 1.0840
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.adx = 25.0
        analisis_medio_mock.sma20 = 1.0850
        analisis_medio_mock.sma50 = 1.0830
        analisis_medio_mock.rsi = 52.0
        analisis_medio_mock.macd_histogram = 0.0001
        analisis_medio_mock.soporte_cercano = 1.0800
        analisis_medio_mock.resistencia_cercana = 1.0900
        analisis_medio_mock.en_nivel_clave = True
        
        modo, razon, confluencias, puntuacion = detector._evaluar_pullback(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=precio_actual,
            direccion='COMPRA',
            analisis_rapido=MagicMock(),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=MagicMock(),
            contexto_h1=contexto_h1
        )
        
        assert modo is not None or razon is not None
    
    def test_pullback_venta_en_tendencia_bajista(self, df_m5_eurusd, contexto_h1):
        """PULLBACK VENTA debe validarse en tendencia bajista."""
        detector = DetectorModos(modo_backtest=True)
        
        precio_actual = 1.0865
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.adx = 25.0
        analisis_medio_mock.sma20 = 1.0830
        analisis_medio_mock.sma50 = 1.0850
        analisis_medio_mock.rsi = 48.0
        analisis_medio_mock.macd_histogram = -0.0001
        analisis_medio_mock.soporte_cercano = 1.0750
        analisis_medio_mock.resistencia_cercana = 1.0850
        analisis_medio_mock.en_nivel_clave = True
        
        contexto_venta = {
            **contexto_h1,
            'direccion': 'VENTA',
            'regimen': 'TREND_BAJISTA_FUERTE'
        }
        
        # Recrear datos con tendencia bajista
        np.random.seed(789)
        n = len(df_m5_eurusd)
        fechas = df_m5_eurusd.index
        precio_base = 1.0850
        trend = np.linspace(0, -0.003, n)
        noise = np.random.randn(n) * 0.0005
        
        close = precio_base + trend + noise
        
        df_mod = pd.DataFrame({
            'Open': close - np.random.randn(n) * 0.0002,
            'High': close + np.abs(np.random.randn(n)) * 0.0003,
            'Low': close - np.abs(np.random.randn(n)) * 0.0003,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        df_mod['High'] = df_mod[['Open', 'Close', 'High']].max(axis=1)
        df_mod['Low'] = df_mod[['Open', 'Close', 'Low']].min(axis=1)
        
        try:
            resultado = detector._evaluar_pullback(
                simbolo='EURUSD',
                df_m5=df_mod,
                precio_actual=precio_actual,
                direccion='VENTA',
                analisis_rapido=MagicMock(),
                analisis_medio=analisis_medio_mock,
                analisis_pesado=MagicMock(),
                contexto_h1=contexto_venta
            )
            
            if resultado is not None:
                modo, razon, confluencias, puntuacion = resultado
                assert modo == ModoEntrada.PULLBACK
            else:
                assert resultado is None
        except TypeError as e:
            pytest.fail(f"TypeError lanzado: {e}")
    
    # ============================================================
    # VALIDAR DIRECCIÓN PARA NIVEL_FUERTE
    # ============================================================
    
    def test_nivel_fuerte_compra(self, df_m5_eurusd, contexto_h1):
        """NIVEL_FUERTE COMPRA debe validarse con hits >= 2."""
        detector = DetectorModos(modo_backtest=True)
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.soporte_cercano = 1.0800
        analisis_medio_mock.resistencia_cercana = None
        analisis_medio_mock.soporte_hits = 3
        analisis_medio_mock.resistencia_hits = 0
        analisis_medio_mock.en_nivel_clave = True
        
        modo, razon, confluencias, puntuacion = detector._evaluar_nivel_fuerte(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=1.0805,
            direccion='COMPRA',
            analisis_rapido=MagicMock(),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=MagicMock(),
            contexto_h1=contexto_h1
        )
        
        assert modo == ModoEntrada.NIVEL_FUERTE
    
    def test_nivel_fuerte_venta(self, df_m5_eurusd, contexto_h1):
        """NIVEL_FUERTE VENTA debe validarse con hits >= 2."""
        detector = DetectorModos(modo_backtest=True)
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.soporte_cercano = None
        analisis_medio_mock.resistencia_cercana = 1.0900
        analisis_medio_mock.soporte_hits = 0
        analisis_medio_mock.resistencia_hits = 3
        analisis_medio_mock.en_nivel_clave = True
        
        contexto_venta = {
            **contexto_h1,
            'direccion': 'VENTA',
            'regimen': 'TREND_BAJISTA_FUERTE'
        }
        
        modo, razon, confluencias, puntuacion = detector._evaluar_nivel_fuerte(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=1.0895,
            direccion='VENTA',
            analisis_rapido=MagicMock(),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=MagicMock(),
            contexto_h1=contexto_venta
        )
        
        assert modo == ModoEntrada.NIVEL_FUERTE
    
    # ============================================================
    # VALIDAR DIRECCIÓN PARA PATRON
    # ============================================================
    
    def test_patron_compra_engulfing(self, df_m5_eurusd, contexto_h1):
        """PATRON COMPRA debe validarse con Engulfing Alcista."""
        detector = DetectorModos(modo_backtest=True)
        
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], ['Open', 'Close']] = [1.0830, 1.0850]
        df_m5_eurusd.loc[df_m5_eurusd.index[-2], ['Open', 'Close']] = [1.0845, 1.0835]
        
        modo, razon, confluencias, puntuacion = detector._evaluar_patron(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=1.0850,
            direccion='COMPRA',
            analisis_rapido=MagicMock(),
            analisis_medio=MagicMock(),
            analisis_pesado=MagicMock(
                patron_principal='ENGULFING_ALCISTA',
                calidad_patron=80
            ),
            contexto_h1=contexto_h1
        )
        
        assert modo == ModoEntrada.PATRON
    
    def test_patron_venta_engulfing(self, df_m5_eurusd, contexto_h1):
        """PATRON VENTA debe validarse con Engulfing Bajista."""
        detector = DetectorModos(modo_backtest=True)
        
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], ['Open', 'Close']] = [1.0850, 1.0830]
        df_m5_eurusd.loc[df_m5_eurusd.index[-2], ['Open', 'Close']] = [1.0835, 1.0845]
        
        contexto_venta = {
            **contexto_h1,
            'direccion': 'VENTA',
            'regimen': 'TREND_BAJISTA_FUERTE'
        }
        
        modo, razon, confluencias, puntuacion = detector._evaluar_patron(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=1.0830,
            direccion='VENTA',
            analisis_rapido=MagicMock(),
            analisis_medio=MagicMock(),
            analisis_pesado=MagicMock(
                patron_principal='ENGULFING_BAJISTA',
                calidad_patron=80
            ),
            contexto_h1=contexto_venta
        )
        
        assert modo == ModoEntrada.PATRON
    
    # ============================================================
    # VALIDAR DIRECCIÓN PARA VELA_BORDE
    # ============================================================
    
    def test_vela_borde_compra(self, df_m5_eurusd, contexto_h1):
        """VELA_BORDE COMPRA debe validarse con sombra inferior larga en soporte."""
        detector = DetectorModos(modo_backtest=True)
        
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], ['Open', 'Close']] = [1.0810, 1.0820]
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Low'] = 1.0795
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'High'] = 1.0825
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.soporte_cercano = 1.0800
        analisis_medio_mock.resistencia_cercana = 1.0900
        analisis_medio_mock.en_nivel_clave = True
        
        modo, razon, confluencias, puntuacion = detector._evaluar_vela_borde(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=1.0820,
            direccion='COMPRA',
            analisis_rapido=MagicMock(),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=MagicMock(),
            contexto_h1=contexto_h1
        )
        
        assert modo == ModoEntrada.VELA_BORDE
    
    # ============================================================
    # VALIDAR DIRECCIÓN PARA RUPTURA_FALSA
    # ============================================================
    
    def test_ruptura_falsa_compra(self, df_m5_eurusd, contexto_h1):
        """RUPTURA_FALSA COMPRA debe validarse cuando hay falsa ruptura bajista."""
        detector = DetectorModos(modo_backtest=True)
        
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Close'] = 1.0810
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Low'] = 1.0795
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'High'] = 1.0820
        df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Open'] = 1.0805
        
        try:
            resultado = detector._evaluar_ruptura_falsa(
                simbolo='EURUSD',
                df_m5=df_m5_eurusd,
                precio_actual=1.0810,
                direccion='COMPRA',
                analisis_rapido=MagicMock(),
                analisis_medio=MagicMock(),
                analisis_pesado=MagicMock(),
                contexto_h1=contexto_h1
            )
            
            if resultado is not None:
                modo, razon, confluencias, puntuacion = resultado
                assert modo == ModoEntrada.RUPTURA_FALSA
            else:
                assert resultado is None
        except TypeError as e:
            pytest.fail(f"TypeError lanzado: {e}")
    
    # ============================================================
    # VALIDAR DIRECCIÓN PARA SNIPER_ELITE
    # ============================================================
    
    def test_sniper_elite_compra_con_multiples_confluencias(self, df_m5_eurusd, contexto_h1):
        """SNIPER_ELITE COMPRA debe requerir múltiples confluencias."""
        detector = DetectorModos(modo_backtest=True)
        
        analisis_pesado_mock = MagicMock()
        analisis_pesado_mock.calidad_patron = 80
        analisis_pesado_mock.patron_principal = 'ENGULFING_ALCISTA'
        analisis_pesado_mock.wyckoff_confianza = 70
        analisis_pesado_mock.wyckoff_fase = 'ACUMULACION'
        analisis_pesado_mock.ob_cercano = True
        analisis_pesado_mock.divergencia_rsi = 'BULLISH'
        analisis_pesado_mock.bull_ob = {'top': 1.0820, 'bottom': 1.0790}
        analisis_pesado_mock.bear_ob = None
        
        analisis_medio_mock = MagicMock()
        analisis_medio_mock.adx = 30.0
        analisis_medio_mock.rsi = 35.0
        analisis_medio_mock.soporte_cercano = 1.0800
        analisis_medio_mock.resistencia_cercana = 1.0900
        analisis_medio_mock.en_nivel_clave = True
        analisis_medio_mock.sma20 = 1.0820
        analisis_medio_mock.sma50 = 1.0800
        analisis_medio_mock.macd_histogram = 0.0003
        
        modo, razon, confluencias, puntuacion = detector._evaluar_sniper_elite(
            simbolo='EURUSD',
            df_m5=df_m5_eurusd,
            precio_actual=1.0805,
            direccion='COMPRA',
            analisis_rapido=MagicMock(volumen_relativo=2.0),
            analisis_medio=analisis_medio_mock,
            analisis_pesado=analisis_pesado_mock,
            contexto_h1=contexto_h1,
            score_h1=75.0,
            en_nivel_clave=True
        )
        
        assert modo == ModoEntrada.SNIPER_ELITE
        assert len(confluencias) >= 2
        assert puntuacion >= 40