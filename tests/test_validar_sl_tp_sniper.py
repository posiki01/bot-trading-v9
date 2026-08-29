#!/usr/bin/env python3
"""
tests/test_validar_sl_tp_sniper.py (V1.4 - CORREGIDO DEFINITIVO)
Valida que el SL/TP calculado por el sniper es correcto según la dirección.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch, create_autospec
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from contextlib import contextmanager

from trading.sniper.sniper_checklist import SniperChecklist
from trading.stops import GestorStops
from trading.timer import EntryTimer
from trading.modos import ModoSelector


class TestValidarSLTPSniper:
    """Validación del cálculo de SL/TP en el sniper."""
    
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
        
        # ✅ CORRECCIÓN: Configurar analisis_rapido con valores por defecto
        self.analisis_rapido_default = SimpleNamespace(
            pasa_filtro=True,
            volumen_relativo=1.5,
            rsi=55.0,
            tendencia_corta='ALCISTA',
            cambio_vela_pct=0.5,
            rsi_extremo=False,
            tendencia_fuerte=True
        )
        self.analisis_capas_mock.analisis_rapido.return_value = self.analisis_rapido_default
        
        # ✅ CORRECCIÓN: Configurar analisis_medio con valores por defecto
        self.analisis_medio_default = SimpleNamespace(
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
        self.analisis_capas_mock.analisis_medio.return_value = self.analisis_medio_default
        
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
        
        # ✅ Configurar orquestador con capital real
        self.orquestador_mock = MagicMock()
        self.orquestador_mock.gestion_riesgo = MagicMock()
        self.orquestador_mock.gestion_riesgo.capital_actual = 1000.0
        self.sniper.orquestador = self.orquestador_mock
    
    @contextmanager
    def _patch_horario(self):
        """Patch de HorarioMercado para que siempre sea válido."""
        with patch('utils.tiempo.HorarioMercado') as mock_horario_cls:
            mock_horario = MagicMock()
            mock_horario.ahora_usuario.return_value = datetime(2024, 1, 8, 14, 0)
            mock_horario.es_horario_operativo.return_value = (True, "Test")
            mock_horario.obtener_calidad_horario.return_value = {
                'calidad': 'EXCELENTE',
                'puntaje': 100,
                'razon': 'Test',
                'es_optimo': True,
                'score_minimo': 0
            }
            mock_horario_cls.return_value = mock_horario
            yield
    
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
    
    def _crear_contexto_compra(self):
        """Crea contexto H1 para COMPRA."""
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
            'niveles': {
                'soportes': [{'precio': 1.0800, 'hits': 3, 'fuerza': 60}],
                'resistencias': [{'precio': 1.0900, 'hits': 2, 'fuerza': 50}]
            }
        }
    
    def _crear_contexto_venta(self):
        """Crea contexto H1 para VENTA."""
        return {
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
            'niveles': {
                'soportes': [{'precio': 1.0750, 'hits': 2, 'fuerza': 40}],
                'resistencias': [{'precio': 1.0850, 'hits': 3, 'fuerza': 60}]
            }
        }
    
    def test_sl_compra_debajo_entrada(self):
        """Valida que SL para COMPRA está DEBAJO de la entrada."""
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_compra()
        
        with self._patch_horario():
            with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
                with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                    with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0805,
                            direccion='COMPRA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=False,
                            contexto_h1=contexto,
                            calidad_horario='EXCELENTE',
                            modo_forzado='RETEST'
                        )
        
        assert resultado is not None
        assert resultado['sl'] < resultado['entry_price']
        assert resultado['tp'] > resultado['entry_price']
    
    def test_sl_venta_arriba_entrada(self):
        """Valida que SL para VENTA está ARRIBA de la entrada."""
        # ✅ Configurar gestor_stops con valores correctos para VENTA
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.08650, 1.08150, 0)
        
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_venta()
        
        with self._patch_horario():
            with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
                with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                    with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0845,
                            direccion='VENTA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=False,
                            contexto_h1=contexto,
                            calidad_horario='EXCELENTE',
                            modo_forzado='RETEST'
                        )
        
        assert resultado is not None
        assert resultado['sl'] > resultado['entry_price']
        assert resultado['tp'] < resultado['entry_price']
    
    def test_tp_compra_arriba_entrada(self):
        """Valida que TP para COMPRA está ARRIBA de la entrada."""
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_compra()
        
        with self._patch_horario():
            with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
                with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                    with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0805,
                            direccion='COMPRA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=False,
                            contexto_h1=contexto,
                            calidad_horario='EXCELENTE',
                            modo_forzado='RETEST'
                        )
        
        assert resultado is not None
        assert resultado['tp'] > resultado['entry_price']
    
    def test_tp_venta_debajo_entrada(self):
        """Valida que TP para VENTA está DEBAJO de la entrada."""
        # ✅ Configurar gestor_stops con valores correctos para VENTA
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.08650, 1.08150, 0)
        
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_venta()
        
        with self._patch_horario():
            with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
                with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                    with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0845,
                            direccion='VENTA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=False,
                            contexto_h1=contexto,
                            calidad_horario='EXCELENTE',
                            modo_forzado='RETEST'
                        )
        
        assert resultado is not None
        assert resultado['tp'] < resultado['entry_price']
    
    def test_rr_minimo_compra(self):
        """Valida que R:R es >= 1.5 para COMPRA."""
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_compra()
        
        with self._patch_horario():
            with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
                with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                    with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0805,
                            direccion='COMPRA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=False,
                            contexto_h1=contexto,
                            calidad_horario='EXCELENTE',
                            modo_forzado='RETEST'
                        )
        
        assert resultado is not None
        rr = abs(resultado['tp'] - resultado['entry_price']) / abs(resultado['entry_price'] - resultado['sl'])
        assert rr >= 1.5 - 0.001
    
    def test_rr_minimo_venta(self):
        """Valida que R:R es >= 1.5 para VENTA."""
        # ✅ Configurar gestor_stops con valores correctos para VENTA
        self.gestor_stops_mock.validar_sl_tp.return_value = (True, "OK", 1.08650, 1.08150, 0)
        
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_venta()
        
        with self._patch_horario():
            with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
                with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                    with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0845,
                            direccion='VENTA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=False,
                            contexto_h1=contexto,
                            calidad_horario='EXCELENTE',
                            modo_forzado='RETEST'
                        )
        
        assert resultado is not None
        rr = abs(resultado['tp'] - resultado['entry_price']) / abs(resultado['entry_price'] - resultado['sl'])
        assert rr >= 1.5 - 0.001
    
    def test_distancia_sl_minima(self):
        """Valida que la distancia del SL es >= el mínimo permitido."""
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_compra()
        
        with self._patch_horario():
            with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
                with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                    with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0805,
                            direccion='COMPRA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=False,
                            contexto_h1=contexto,
                            calidad_horario='EXCELENTE',
                            modo_forzado='RETEST'
                        )
        
        assert resultado is not None
        sl_dist_pips = abs(resultado['entry_price'] - resultado['sl']) / 0.0001
        assert sl_dist_pips >= 10  # Mínimo 10 pips
    
    def test_distancia_tp_minima(self):
        """Valida que la distancia del TP es >= el mínimo permitido."""
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_compra()
        
        with self._patch_horario():
            with patch.object(self.sniper, '_validar_capital_minimo', return_value=(True, "OK")):
                with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
                    with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                        resultado = self.sniper.evaluar_sniper_optimizado(
                            simbolo='EURUSD',
                            df_m5=df_m5,
                            precio_actual=1.0805,
                            direccion='COMPRA',
                            estado_pipeline=MagicMock(metadata={}),
                            analisis_rapido=None,
                            analisis_medio=None,
                            ejecutar_pesado=False,
                            contexto_h1=contexto,
                            calidad_horario='EXCELENTE',
                            modo_forzado='RETEST'
                        )
        
        assert resultado is not None
        tp_dist_pips = abs(resultado['tp'] - resultado['entry_price']) / 0.0001
        assert tp_dist_pips >= 15  # Mínimo 15 pips
    
    def test_calcular_sl_tp_estructura_compra_correcto(self):
        """Valida que _calcular_sl_tp_estructura retorna SL/TP correctos para COMPRA."""
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_compra()
        
        with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
            with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                sl, tp, rr = self.sniper._calcular_sl_tp_estructura(
                    simbolo='EURUSD',
                    precio_actual=1.0805,
                    direccion='COMPRA',
                    modo='RETEST',
                    analisis_medio=None,
                    analisis_pesado=None,
                    contexto_h1=contexto,
                    df_m5=df_m5,
                    df_h1=df_m5,
                    atr_m5=10.0
                )
        
        assert sl < 1.0805  # SL debajo
        assert tp > 1.0805  # TP arriba
        assert rr >= 1.5 - 0.001
    
    def test_calcular_sl_tp_estructura_venta_correcto(self):
        """Valida que _calcular_sl_tp_estructura retorna SL/TP correctos para VENTA."""
        df_m5 = self._crear_df_m5()
        contexto = self._crear_contexto_venta()
        
        with patch.object(self.sniper, '_obtener_pip_val_universal', return_value=0.0001):
            with patch.object(self.sniper, '_obtener_digits_universal', return_value=5):
                sl, tp, rr = self.sniper._calcular_sl_tp_estructura(
                    simbolo='EURUSD',
                    precio_actual=1.0845,
                    direccion='VENTA',
                    modo='RETEST',
                    analisis_medio=None,
                    analisis_pesado=None,
                    contexto_h1=contexto,
                    df_m5=df_m5,
                    df_h1=df_m5,
                    atr_m5=10.0
                )
        
        assert sl > 1.0845  # SL arriba
        assert tp < 1.0845  # TP debajo
        assert rr >= 1.5 - 0.001