#!/usr/bin/env python3
"""
tests/test_sniper_entrada.py
Valida que el sniper evalúa correctamente las oportunidades.
"""

import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from trading.sniper.sniper_checklist import SniperChecklist
from trading.sniper.sniper_modos import ModoEntrada
from analysis.pipeline import FaseOportunidad


class TestSniperEntrada:
    """Validación del evaluador sniper."""
    
    def test_sniper_compra_en_soporte(self, instancias_sniper, df_m5_eurusd, contexto_h1):
        """Sniper debe disparar COMPRA cuando hay soporte cercano."""
        sniper = instancias_sniper['sniper']
        
        # Patch de HorarioMercado
        with patch('utils.tiempo.HorarioMercado') as mock_horario_cls:
            mock_horario = MagicMock()
            mock_horario.es_horario_operativo.return_value = (True, "Test")
            mock_horario.obtener_calidad_horario.return_value = {
                'calidad': 'EXCELENTE',
                'puntaje': 100,
                'razon': 'Test',
                'es_optimo': True,
                'score_minimo': 0
            }
            mock_horario_cls.return_value = mock_horario
            
            # Patch del EntryTimer para validar momento siempre OK
            with patch.object(sniper.entry_timer, 'validar_momento_exacto', return_value=(True, "OK", {})):
                # Modificar DataFrame para que la vela confirme
                df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Open'] = 1.0800
                df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Close'] = 1.0805
                df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'High'] = 1.0810
                df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Low'] = 1.0795
                
                # Patch de analisis_capas
                with patch.object(sniper, 'analisis_capas') as mock_analisis:
                    # Mock análisis rápido
                    mock_rapido = MagicMock()
                    mock_rapido.pasa_filtro = True
                    mock_rapido.volumen_relativo = 1.5
                    mock_rapido.rsi = 55.0
                    mock_rapido.tendencia_corta = 'ALCISTA'
                    mock_analisis.analisis_rapido.return_value = mock_rapido
                    
                    # Mock análisis medio
                    mock_medio = MagicMock()
                    mock_medio.pasa_filtro = True
                    mock_medio.adx = 25.0
                    mock_medio.rsi = 58.0
                    mock_medio.macd_histogram = 0.0002
                    mock_medio.sma20 = 1.0850
                    mock_medio.sma50 = 1.0830
                    mock_medio.en_nivel_clave = True
                    mock_medio.soporte_cercano = 1.0800
                    mock_medio.resistencia_cercana = 1.0900
                    mock_medio.atr = 0.001
                    mock_analisis.analisis_medio.return_value = mock_medio
                    
                    # Mock análisis pesado
                    mock_pesado = MagicMock()
                    mock_pesado.score_estructura = 25.0
                    mock_pesado.score_momentum = 28.0
                    mock_pesado.score_confluencia = 25.0
                    mock_pesado.score_institucional = 22.0
                    mock_pesado.calidad_patron = 75.0
                    mock_pesado.patron_principal = 'ENGULFING_ALCISTA'
                    mock_analisis.analisis_pesado.return_value = mock_pesado
                    
                    # Mock obtener_df_h1
                    sniper._obtener_df_h1 = MagicMock(return_value=df_m5_eurusd)
                    
                    # Ejecutar evaluador con modo_forzado RETEST
                    resultado = sniper.evaluar_sniper_optimizado(
                        simbolo='EURUSD',
                        df_m5=df_m5_eurusd,
                        precio_actual=1.0805,
                        direccion='COMPRA',
                        estado_pipeline=MagicMock(metadata={}),
                        analisis_rapido=None,
                        analisis_medio=None,
                        ejecutar_pesado=True,
                        contexto_h1=contexto_h1,
                        calidad_horario='EXCELENTE',
                        modo_forzado='RETEST'
                    )
                    
                    assert resultado is not None
                    assert resultado['direccion'] == 'COMPRA'
                    assert resultado['simbolo'] == 'EURUSD'
                    assert resultado['entry_price'] > 0
                    assert resultado['sl'] < resultado['entry_price']
                    assert resultado['tp'] > resultado['entry_price']
                    assert resultado['rr'] >= 1.5 - 0.001
    
    def test_sniper_venta_en_resistencia(self, instancias_sniper, df_m5_eurusd, contexto_h1):
        """Sniper debe disparar VENTA cuando hay resistencia cercana."""
        sniper = instancias_sniper['sniper']
        
        contexto_venta = {
            **contexto_h1,
            'direccion': 'VENTA',
            'regimen': 'TREND_BAJISTA_FUERTE',
            'soporte_cercano': 1.0750,
            'resistencia_cercana': 1.0850,
        }
        
        # ✅ PATCH DE utils.tiempo.HorarioMercado
        with patch('utils.tiempo.HorarioMercado') as mock_horario_cls:
            mock_horario = MagicMock()
            mock_horario.es_horario_operativo.return_value = (True, "Test")
            mock_horario.obtener_calidad_horario.return_value = {
                'calidad': 'EXCELENTE',
                'puntaje': 100,
                'razon': 'Test',
                'es_optimo': True,
                'score_minimo': 0
            }
            mock_horario_cls.return_value = mock_horario
            
            # ✅ PATCH DEL ENTRY_TIMER
            with patch.object(sniper.entry_timer, 'validar_momento_exacto', return_value=(True, "OK", {})):
                # ✅ MODIFICAR DATAFRAME
                df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Open'] = 1.0850
                df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Close'] = 1.0845
                df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'High'] = 1.0855
                df_m5_eurusd.loc[df_m5_eurusd.index[-1], 'Low'] = 1.0840
                
                with patch.object(sniper, 'analisis_capas') as mock_analisis:
                    mock_rapido = MagicMock()
                    mock_rapido.pasa_filtro = True
                    mock_rapido.volumen_relativo = 1.4
                    mock_rapido.rsi = 45.0
                    mock_rapido.tendencia_corta = 'BAJISTA'
                    mock_analisis.analisis_rapido.return_value = mock_rapido
                    
                    mock_medio = MagicMock()
                    mock_medio.pasa_filtro = True
                    mock_medio.adx = 25.0
                    mock_medio.rsi = 42.0
                    mock_medio.macd_histogram = -0.0002
                    mock_medio.sma20 = 1.0830
                    mock_medio.sma50 = 1.0850
                    mock_medio.en_nivel_clave = True
                    mock_medio.soporte_cercano = 1.0750
                    mock_medio.resistencia_cercana = 1.0850
                    mock_medio.atr = 0.001
                    mock_analisis.analisis_medio.return_value = mock_medio
                    
                    mock_pesado = MagicMock()
                    mock_pesado.score_estructura = 22.0
                    mock_pesado.score_momentum = 25.0
                    mock_pesado.score_confluencia = 20.0
                    mock_pesado.score_institucional = 18.0
                    mock_pesado.calidad_patron = 70.0
                    mock_pesado.patron_principal = 'SHOOTING_STAR'
                    mock_analisis.analisis_pesado.return_value = mock_pesado
                    
                    sniper._obtener_df_h1 = MagicMock(return_value=df_m5_eurusd)
                    
                    resultado = sniper.evaluar_sniper_optimizado(
                        simbolo='EURUSD',
                        df_m5=df_m5_eurusd,
                        precio_actual=1.0845,
                        direccion='VENTA',
                        estado_pipeline=MagicMock(metadata={}),
                        analisis_rapido=None,
                        analisis_medio=None,
                        ejecutar_pesado=True,
                        contexto_h1=contexto_venta,
                        calidad_horario='EXCELENTE',
                        modo_forzado='RETEST'
                    )
                    
                    assert resultado is not None
                    assert resultado['direccion'] == 'VENTA'
                    assert resultado['sl'] > resultado['entry_price']
                    assert resultado['tp'] < resultado['entry_price']
                    assert resultado['rr'] >= 1.5 - 0.001