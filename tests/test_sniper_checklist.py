#!/usr/bin/env python3
"""
tests/test_sniper_checklist.py (V1.3 - CORREGIDO DEFINITIVO)
Valida el checklist del sniper - el módulo más crítico.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch, create_autospec
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from trading.sniper.sniper_checklist import SniperChecklist
from trading.sniper.sniper_modos import ModoEntrada
from trading.stops import GestorStops
from trading.timer import EntryTimer
from trading.modos import ModoSelector


class TestSniperChecklist:
    """Validación del checklist del sniper."""
    
    def setup_method(self):
        """Configura el sniper."""
        # Mocks de dependencias
        self.pipeline_mock = MagicMock()
        self.analisis_capas_mock = MagicMock()
        self.modo_selector_mock = create_autospec(ModoSelector)
        self.entry_timer_mock = create_autospec(EntryTimer)
        self.gestor_stops_mock = create_autospec(GestorStops)
        self.mt5_mock = MagicMock()
        self.cache_mock = MagicMock()
        self.almacen_mock = MagicMock()
        self.noticias_mock = MagicMock()
        self.patron_tracker_mock = MagicMock()
        self.ml_optimizer_mock = MagicMock()
        
        # Configurar EntryTimer para validar momento OK
        self.entry_timer_mock.validar_momento_exacto.return_value = (True, "OK", {})
        
        # Configurar GestorStops (default para COMPRA)
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.07850, 1.08350, 0)
        
        # Configurar modo_selector
        self.modo_selector_mock.seleccionar_modo.return_value = (ModoEntrada.RETEST, "RETEST seleccionado", {})
        
        # Crear sniper
        self.sniper = SniperChecklist(
            pipeline=self.pipeline_mock,
            analisis_capas=self.analisis_capas_mock,
            modo_selector=self.modo_selector_mock,
            entry_timer=self.entry_timer_mock,
            gestor_stops=self.gestor_stops_mock,
            config=MagicMock(),
            almacen=self.almacen_mock,
            mt5=self.mt5_mock,
            noticias=self.noticias_mock,
            patron_tracker=self.patron_tracker_mock,
            ml_optimizer=self.ml_optimizer_mock,
            analysis_cache=self.cache_mock,
            modo_depuracion=True,
            modo_backtest=True
        )
        
        # ✅ CORRECCIÓN: Configurar orquestador con capital real
        self.orquestador_mock = MagicMock()
        self.orquestador_mock.gestion_riesgo = MagicMock()
        self.orquestador_mock.gestion_riesgo.capital_actual = 1000.0
        self.sniper.orquestador = self.orquestador_mock
        
        # ✅ CORRECCIÓN: Mockear horario para que siempre esté operativo
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
            self.sniper.horario = mock_horario
    
    def _crear_df_m5(self, n=100, precio_base=1.0800):
        """Crea DataFrame M5 de prueba."""
        np.random.seed(42)
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='5min',
            tz='UTC'
        )
        
        tendencia = np.linspace(0, 0.005, n)
        ruido = np.random.randn(n) * 0.0002
        close = precio_base + tendencia + ruido
        
        df = pd.DataFrame({
            'Open': close - np.random.randn(n) * 0.0001,
            'High': close + np.abs(np.random.randn(n)) * 0.0002,
            'Low': close - np.abs(np.random.randn(n)) * 0.0002,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        
        df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
        df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
        
        return df
    
    def _crear_contexto_h1(self):
        """Crea contexto H1 de prueba."""
        return {
            'score': 70.0,
            'direccion': 'COMPRA',
            'regimen': 'TREND_ALCISTA_FUERTE',
            'en_nivel_clave': True,
            'soporte_cercano': 1.0800,
            'resistencia_cercana': 1.0900,
            'soporte_hits': 3,
            'resistencia_hits': 2,
            'adx': 28.0,
            'rsi': 60.0,
            'patron_principal': 'ENGULFING_ALCISTA',
            'wyckoff_fase': 'ACUMULACION',
            'divergencia_rsi': None,
            'divergencia_macd': None,
            'niveles': {
                'soportes': [{'precio': 1.0800, 'hits': 3, 'fuerza': 60}],
                'resistencias': [{'precio': 1.0900, 'hits': 2, 'fuerza': 50}]
            }
        }
    
    def test_evaluar_sniper_compra_valida(self):
        """Valida evaluación exitosa de COMPRA."""
        df_m5 = self._crear_df_m5()
        contexto_h1 = self._crear_contexto_h1()
        
        # Configurar análisis rápido
        analisis_rapido_mock = SimpleNamespace(
            pasa_filtro=True,
            volumen_relativo=1.5,
            rsi=55.0,
            tendencia_corta='ALCISTA',
            cambio_vela_pct=0.5,
            rsi_extremo=False,
            tendencia_fuerte=True
        )
        
        # Configurar análisis medio
        analisis_medio_mock = SimpleNamespace(
            pasa_filtro=True,
            adx=28.0,
            rsi=58.0,
            macd_histogram=0.0002,
            sma20=1.0850,
            sma50=1.0830,
            en_nivel_clave=True,
            soporte_cercano=1.0800,
            resistencia_cercana=1.0900,
            atr=0.001
        )
        
        # Configurar análisis pesado
        analisis_pesado_mock = SimpleNamespace(
            score_estructura=25.0,
            score_momentum=28.0,
            score_confluencia=25.0,
            score_institucional=22.0,
            calidad_patron=75.0,
            patron_principal='ENGULFING_ALCISTA',
            wyckoff_fase='ACUMULACION',
            wyckoff_confianza=70.0,
            ob_cercano=True,
            bull_ob={'fuerza': 70},
            bear_ob=None,
            divergencia_rsi=None,
            divergencia_macd=None
        )
        
        # Patch de analisis_capas
        self.analisis_capas_mock.analisis_rapido.return_value = analisis_rapido_mock
        self.analisis_capas_mock.analisis_medio.return_value = analisis_medio_mock
        self.analisis_capas_mock.analisis_pesado.return_value = analisis_pesado_mock
        
        # Patch de _obtener_df_h1
        self.sniper._obtener_df_h1 = MagicMock(return_value=df_m5)
        
        # ✅ CORRECCIÓN: Patch _validar_capital_minimo para que retorne OK
        with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
            # Patch de _obtener_pip_val_universal y _obtener_digits_universal
            with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                    # ✅ CORRECCIÓN: Mockear _validar_horario_por_simbolo
                    with patch.object(self.sniper, '_validar_horario_por_simbolo', return_value=(True, 'EXCELENTE', 0)):
                        # Ejecutar evaluación
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0805,
                            direccion='COMPRA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=True,
                            contexto_h1=contexto_h1,
                            calidad_horario='EXCELENTE'
                        )
        
        assert resultado is not None
        assert resultado['direccion'] == 'COMPRA'
        assert resultado['simbolo'] == 'EURUSD'
        assert resultado['entry_price'] > 0
        assert resultado['sl'] < resultado['entry_price']
        assert resultado['tp'] > resultado['entry_price']
        assert resultado['rr'] >= 1.5 - 0.001
    
    def test_evaluar_sniper_venta_valida(self):
        """Valida evaluación exitosa de VENTA."""
        # ✅ CORRECCIÓN: Configurar gestor_stops con valores correctos para VENTA
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.08650, 1.08150, 0)
        
        df_m5 = self._crear_df_m5()
        contexto_h1 = {
            'score': 70.0,
            'direccion': 'VENTA',
            'regimen': 'TREND_BAJISTA_FUERTE',
            'en_nivel_clave': True,
            'soporte_cercano': 1.0750,
            'resistencia_cercana': 1.0850,
            'soporte_hits': 2,
            'resistencia_hits': 3,
            'adx': 28.0,
            'rsi': 42.0,
            'patron_principal': 'SHOOTING_STAR',
            'wyckoff_fase': 'DISTRIBUCION',
            'divergencia_rsi': 'BEARISH',
            'divergencia_macd': None,
            'niveles': {
                'soportes': [{'precio': 1.0750, 'hits': 2, 'fuerza': 40}],
                'resistencias': [{'precio': 1.0850, 'hits': 3, 'fuerza': 60}]
            }
        }
        
        # Configurar análisis rápido
        analisis_rapido_mock = SimpleNamespace(
            pasa_filtro=True,
            volumen_relativo=1.4,
            rsi=45.0,
            tendencia_corta='BAJISTA',
            cambio_vela_pct=-0.5,
            rsi_extremo=False,
            tendencia_fuerte=True
        )
        
        # Configurar análisis medio
        analisis_medio_mock = SimpleNamespace(
            pasa_filtro=True,
            adx=28.0,
            rsi=42.0,
            macd_histogram=-0.0002,
            sma20=1.0830,
            sma50=1.0850,
            en_nivel_clave=True,
            soporte_cercano=1.0750,
            resistencia_cercana=1.0850,
            atr=0.001
        )
        
        # Configurar análisis pesado
        analisis_pesado_mock = SimpleNamespace(
            score_estructura=22.0,
            score_momentum=25.0,
            score_confluencia=20.0,
            score_institucional=18.0,
            calidad_patron=70.0,
            patron_principal='SHOOTING_STAR',
            wyckoff_fase='DISTRIBUCION',
            wyckoff_confianza=65.0,
            ob_cercano=True,
            bull_ob=None,
            bear_ob={'fuerza': 70},
            divergencia_rsi='BEARISH',
            divergencia_macd=None
        )
        
        # Patch de analisis_capas
        self.analisis_capas_mock.analisis_rapido.return_value = analisis_rapido_mock
        self.analisis_capas_mock.analisis_medio.return_value = analisis_medio_mock
        self.analisis_capas_mock.analisis_pesado.return_value = analisis_pesado_mock
        
        # Patch de _obtener_df_h1
        self.sniper._obtener_df_h1 = MagicMock(return_value=df_m5)
        
        # ✅ CORRECCIÓN: Patch _validar_capital_minimo para que retorne OK
        with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
            # Patch de métodos auxiliares
            with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                    # ✅ CORRECCIÓN: Mockear _validar_horario_por_simbolo
                    with patch.object(self.sniper, '_validar_horario_por_simbolo', return_value=(True, 'EXCELENTE', 0)):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0845,
                            direccion='VENTA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=True,
                            contexto_h1=contexto_h1,
                            calidad_horario='EXCELENTE'
                        )
        
        assert resultado is not None
        assert resultado['direccion'] == 'VENTA'
        assert resultado['sl'] > resultado['entry_price']
        assert resultado['tp'] < resultado['entry_price']
        assert resultado['rr'] >= 1.5 - 0.001