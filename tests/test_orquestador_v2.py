#!/usr/bin/env python3
"""
tests/test_orquestador_v2.py (V1.2 - CORREGIDO DEFINITIVO)
Valida los métodos críticos del orquestador con foco en la vela virtual y la precarga.
"""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from core.orquestador import Orquestador


class TestOrquestadorV2:
    """Validación de métodos críticos del orquestador."""

    def setup_method(self):
        """Configura un orquestador simulado sin ejecutar el __init__ real."""
        with patch.object(Orquestador, '__init__', lambda self: None):
            self.orquestador = Orquestador.__new__(Orquestador)
            self.orquestador.modo_backtest = True
            self.orquestador.modo_depuracion = True
            
            # Mocks de dependencias
            self.orquestador.mt5 = MagicMock()
            self.orquestador.cache = MagicMock()
            self.orquestador.estado = MagicMock()
            self.orquestador.logger = MagicMock()
            self.orquestador.pipeline = MagicMock()
            self.orquestador.analisis_capas = MagicMock()
            self.orquestador.nivel_tracker = MagicMock()
            self.orquestador.regimen_filter = MagicMock()
            self.orquestador.score_engine = MagicMock()
            self.orquestador.horario = MagicMock()
            self.orquestador.almacen = MagicMock()
            self.orquestador.gestion_riesgo = MagicMock()

    # ============================================================
    # TEST: _obtener_df_m5_con_precio_real (VELA VIRTUAL)
    # ============================================================
    
    def test_vela_virtual_con_tick_valido(self):
        """Valida que crea vela virtual con precio real del tick."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='5min', tz='UTC')
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
        self.orquestador.mt5.obtener_precio.return_value = {
            'bid': 1.0805, 'ask': 1.0810, 'spread_pips': 0.5, 'digits': 5
        }

        df_resultado = self.orquestador._obtener_df_m5_con_precio_real('EURUSD')

        assert df_resultado is not None
        assert len(df_resultado) == 101
        assert 'precio_tick' in df_resultado.attrs
        assert df_resultado.attrs['precio_entrada_compra'] == 1.0810
        assert df_resultado.attrs['precio_entrada_venta'] == 1.0805

    def test_vela_virtual_sin_tick(self):
        """Valida que si no hay tick, NO se agrega vela virtual."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='5min', tz='UTC')
        df_m5 = pd.DataFrame({
            'Close': 1.0800 + np.random.randn(100) * 0.0001,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas)

        self.orquestador.cache.get_datos.return_value = df_m5
        self.orquestador.mt5.obtener_precio.return_value = None

        df_resultado = self.orquestador._obtener_df_m5_con_precio_real('EURUSD')

        assert df_resultado is not None
        assert len(df_resultado) == 100
        assert 'precio_tick' not in df_resultado.attrs

    def test_vela_virtual_con_precio_invalido(self):
        """Valida que si el precio es 0 o inválido, no agrega vela."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq='5min', tz='UTC')
        df_m5 = pd.DataFrame({
            'Close': 1.0800 + np.random.randn(50) * 0.0001,
            'Volume': np.random.randint(100, 1000, 50)
        }, index=fechas)

        self.orquestador.cache.get_datos.return_value = df_m5
        self.orquestador.mt5.obtener_precio.return_value = {'bid': 0, 'ask': 0}

        df_resultado = self.orquestador._obtener_df_m5_con_precio_real('EURUSD')

        assert df_resultado is not None
        assert len(df_resultado) == 50
        assert 'precio_tick' not in df_resultado.attrs

    # ============================================================
    # TEST: _precargar_simbolo (PRE CARGA DE ANÁLISIS)
    # ============================================================

    def test_precargar_simbolo_exitoso(self):
        """Valida que precarga un símbolo correctamente y actualiza el pipeline."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='5min', tz='UTC')
        df_m5 = pd.DataFrame({
            'Open': 1.0800, 'High': 1.0805, 'Low': 1.0795, 'Close': 1.0800,
            'Volume': np.random.randint(100, 1000, 100)
        }, index=fechas)

        self.orquestador.mt5.obtener_datos.return_value = df_m5
        
        rapido_mock = MagicMock()
        rapido_mock.pasa_filtro = True
        rapido_mock.razon_rechazo = ""
        
        medio_mock = MagicMock()
        medio_mock.pasa_filtro = True
        medio_mock.en_nivel_clave = True
        medio_mock.adx = 25.0
        medio_mock.sma20 = 1.0850
        medio_mock.sma50 = 1.0830
        medio_mock.soporte_cercano = 1.0800
        medio_mock.resistencia_cercana = 1.0900
        medio_mock.rsi = 60.0
        
        pesado_mock = MagicMock()
        pesado_mock.score_estructura = 25.0
        pesado_mock.score_momentum = 28.0
        pesado_mock.score_confluencia = 25.0
        pesado_mock.score_institucional = 22.0
        pesado_mock.patron_principal = 'ENGULFING_ALCISTA'
        pesado_mock.wyckoff_fase = 'ACUMULACION'
        pesado_mock.wyckoff_confianza = 70.0
        pesado_mock.divergencia_rsi = None
        pesado_mock.divergencia_macd = None

        self.orquestador.analisis_capas.analisis_rapido.return_value = rapido_mock
        self.orquestador.analisis_capas.analisis_medio.return_value = medio_mock
        self.orquestador.analisis_capas.analisis_pesado.return_value = pesado_mock
        
        self.orquestador.nivel_tracker.detectar_y_actualizar_niveles.return_value = {
            'soportes': [{'precio': 1.0800, 'hits': 3, 'fuerza': 60}],
            'resistencias': [{'precio': 1.0900, 'hits': 2, 'fuerza': 50}]
        }

        self.orquestador.score_engine.calcular_score_h1.return_value = MagicMock(score=80.0)
        
        regimen_data_mock = MagicMock()
        regimen_data_mock.regimen.value = 'TREND_ALCISTA_FUERTE'
        regimen_data_mock.direccion_favor = 'ALCISTA'
        regimen_data_mock.confianza = 85.0
        self.orquestador.regimen_filter.clasificar.return_value = regimen_data_mock

        self.orquestador._determinar_direccion_mejorado = MagicMock(return_value='COMPRA')
        
        with patch('utils.construir_timeframes.obtener_timeframe_inteligente', return_value=df_m5):
            self.orquestador._precargar_simbolo('EURUSD')

        self.orquestador.pipeline.actualizar_fase_1.assert_called_once()
        args = self.orquestador.pipeline.actualizar_fase_1.call_args
        assert args.kwargs['direccion'] == 'COMPRA'
        assert args.kwargs['score'] >= 80.0

    def test_precargar_simbolo_filtro_rapido_fallido(self):
        """Valida que si el filtro rápido falla, guarda contexto pero NO crea oportunidad."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq='5min', tz='UTC')
        df_m5 = pd.DataFrame({
            'Close': 1.0800, 'Volume': 1000
        }, index=fechas)

        self.orquestador.mt5.obtener_datos.return_value = df_m5

        rapido_mock = MagicMock()
        rapido_mock.pasa_filtro = False
        rapido_mock.razon_rechazo = "Volumen bajo"

        self.orquestador.analisis_capas.analisis_rapido.return_value = rapido_mock

        with patch('utils.construir_timeframes.obtener_timeframe_inteligente', return_value=df_m5):
            self.orquestador._precargar_simbolo('EURUSD')

        # ✅ CORRECCIÓN: El bot SÍ llama a actualizar_fase_1, pero con score=0 y dirección NEUTRAL
        self.orquestador.pipeline.actualizar_fase_1.assert_called_once()
        args = self.orquestador.pipeline.actualizar_fase_1.call_args
        assert args.kwargs['score'] == 0
        assert args.kwargs['direccion'] == 'NEUTRAL'

    def test_precargar_simbolo_sin_datos(self):
        """Valida que si no hay datos, retorna sin actualizar pipeline."""
        self.orquestador.mt5.obtener_datos.return_value = None

        with patch('utils.construir_timeframes.obtener_timeframe_inteligente', return_value=None):
            self.orquestador._precargar_simbolo('EURUSD')

        self.orquestador.pipeline.actualizar_fase_1.assert_not_called()

    # ============================================================
    # TEST: _precargar_analisis_completo
    # ============================================================

    def test_precargar_analisis_completo_basico(self):
        """Valida que itera sobre símbolos y no lanza excepción."""
        self.orquestador.config = MagicMock()
        self.orquestador.config.SIMBOLOS_COMPLETOS = ['EURUSD', 'GBPUSD']

        # ✅ CORRECCIÓN: Crear M5 con SUFICIENTES velas
        n = 700
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq='5min', tz='UTC')
        df_m5 = pd.DataFrame({
            'Open': np.linspace(1.0800, 1.0850, n),
            'High': np.linspace(1.0805, 1.0855, n),
            'Low': np.linspace(1.0795, 1.0845, n),
            'Close': np.linspace(1.0800, 1.0850, n),
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        df_m5['High'] = df_m5[['Open', 'Close', 'High']].max(axis=1)
        df_m5['Low'] = df_m5[['Open', 'Close', 'Low']].min(axis=1)

        # ✅ CORRECCIÓN: Mockear cache.get_datos para que retorne df_m5
        self.orquestador.cache.get_datos.return_value = df_m5

        # ✅ CORRECCIÓN: Mockear mt5.obtener_datos para que retorne df_m5
        self.orquestador.mt5.obtener_datos.return_value = df_m5

        # ✅ CORRECCIÓN: Mockear horario para que siempre esté operativo
        self.orquestador.horario.es_horario_operativo.return_value = (True, "Test")

        # ✅ CORRECCIÓN: Configurar análisis que pasan
        rapido_mock = MagicMock(pasa_filtro=True, razon_rechazo="")
        medio_mock = MagicMock(pasa_filtro=True, en_nivel_clave=True, adx=25.0, sma20=1.0850, sma50=1.0830, soporte_cercano=1.0800, resistencia_cercana=1.0900, rsi=60.0)
        pesado_mock = MagicMock(score_estructura=25.0, score_momentum=28.0, score_confluencia=25.0, score_institucional=22.0, patron_principal='ENGULFING_ALCISTA', wyckoff_fase='ACUMULACION', wyckoff_confianza=70.0, divergencia_rsi=None, divergencia_macd=None)

        self.orquestador.analisis_capas.analisis_rapido.return_value = rapido_mock
        self.orquestador.analisis_capas.analisis_medio.return_value = medio_mock
        self.orquestador.analisis_capas.analisis_pesado.return_value = pesado_mock

        self.orquestador.nivel_tracker.detectar_y_actualizar_niveles.return_value = {'soportes': [], 'resistencias': []}
        self.orquestador.score_engine.calcular_score_h1.return_value = MagicMock(score=70.0)

        regimen_data_mock = MagicMock()
        regimen_data_mock.regimen.value = 'TREND_ALCISTA_FUERTE'
        regimen_data_mock.direccion_favor = 'ALCISTA'
        regimen_data_mock.confianza = 80.0
        self.orquestador.regimen_filter.clasificar.return_value = regimen_data_mock
        self.orquestador._determinar_direccion_mejorado = MagicMock(return_value='COMPRA')

        # ✅ CORRECCIÓN: Simular H1 con más de 50 velas
        fechas_h1 = pd.date_range(end=datetime.now(timezone.utc), periods=60, freq='1h', tz='UTC')
        df_h1_simulado = pd.DataFrame({
            'Open': np.linspace(1.0800, 1.0850, 60),
            'High': np.linspace(1.0805, 1.0855, 60),
            'Low': np.linspace(1.0795, 1.0845, 60),
            'Close': np.linspace(1.0800, 1.0850, 60),
            'Volume': np.random.randint(100, 1000, 60)
        }, index=fechas_h1)

        # ✅ Parchear obtener_timeframe_inteligente (método que usa el orquestador)
        with patch('utils.construir_timeframes.obtener_timeframe_inteligente', return_value=df_h1_simulado):
            # Ejecutar
            self.orquestador._precargar_analisis_completo()

        assert self.orquestador.pipeline.actualizar_fase_1.call_count >= 2

    def test_precargar_analisis_completo_error_simbolo(self):
        """Valida que si un símbolo falla, continúa con el siguiente."""
        self.orquestador.config = MagicMock()
        self.orquestador.config.SIMBOLOS_COMPLETOS = ['EURUSD', 'GBPUSD']

        self.orquestador.mt5.obtener_datos.side_effect = [Exception("Error MT5"), None]
        self.orquestador.mt5.obtener_datos.return_value = None

        self.orquestador._precargar_analisis_completo()

        self.orquestador.pipeline.actualizar_fase_1.assert_not_called()