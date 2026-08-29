#!/usr/bin/env python3
"""
tests/test_trailing_dinamico.py (V1.1 - CORREGIDO)
Valida que el trailing SL se mueve correctamente según la estructura del mercado.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from trading.trailing import TrailingEngine
from trading.monitoreo import MonitorPosiciones


class TestTrailingDinamico:
    """
    Validación del trailing dinámico con datos reales de mercado.
    """
    
    def setup_method(self):
        """Configura el motor de trailing y el monitor."""
        self.engine = TrailingEngine(modo_backtest=True, modo_depuracion=True)
        
        # Configurar el orquestador mock
        self.orquestador_mock = MagicMock()
        self.orquestador_mock.modo_backtest = True
        self.orquestador_mock.estado.posiciones_abiertas = {}
        
        # Configurar el conector MT5 mock
        self.mt5_mock = MagicMock()
        self.mt5_mock.obtener_precio.return_value = {
            'bid': 1.0850,
            'ask': 1.0855,
            'spread_pips': 1.0,
            'digits': 5,
            'point': 0.00001,
            'pip_size': 0.0001
        }
        self.mt5_mock.obtener_info_simbolo.return_value = MagicMock(
            digits=5,
            point=0.00001,
            trade_tick_size=0.00001,
            trade_tick_value=1.0,
            trade_contract_size=100000
        )
        
        # Configurar gestión de riesgo
        self.gestion_riesgo_mock = MagicMock()
        self.gestion_riesgo_mock.capital_actual = 1000.0
        
        # Crear monitor
        self.monitor = MonitorPosiciones(
            orquestador=self.orquestador_mock,
            mt5=self.mt5_mock,
            gestion_riesgo=self.gestion_riesgo_mock,
            trailing_engine=self.engine,
            decisor_cierre=MagicMock()
        )
    
    def _crear_df_h1_tendencia_alcista(self, precio_actual: float = 1.0850) -> pd.DataFrame:
        """
        Crea un DataFrame H1 con tendencia alcista y soportes/resistencias.
        """
        np.random.seed(42)
        n = 100
        
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='1h',
            tz='UTC'
        )
        
        # Tendencia alcista
        precio_base = 1.0800
        tendencia = np.linspace(0, 0.005, n)
        ruido = np.random.randn(n) * 0.0005
        
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
        
        # ✅ Ajustar la última vela para que el precio actual sea 1.0850
        df.loc[df.index[-1], 'Close'] = precio_actual
        df.loc[df.index[-1], 'High'] = precio_actual + 0.0005
        df.loc[df.index[-1], 'Low'] = precio_actual - 0.0003
        
        return df
    
    def test_breakeven_compra_con_ganancia(self):
        """
        Valida que el SL se mueve a breakeven cuando hay ganancia.
        """
        # Crear posición con ganancia
        pos = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': 1.0800,
            'sl': 1.0780,
            'tp': 1.0900,
            'lotes': 0.01,
            'nivel_usado': 1.0780,
            'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=1)
        }
        
        # Precio actual: 1.0820 (ganancia de 20 pips)
        precio_actual = 1.0820
        df_h1 = self._crear_df_h1_tendencia_alcista(precio_actual)
        
        # Calcular decisión de trailing
        decision = self.engine.calcular_movimiento_sl(
            pos=pos,
            df_h1=df_h1,
            precio_actual=precio_actual,
            fecha=datetime.now(timezone.utc),
            regimen='TREND_ALCISTA_FUERTE',
            modo='RETEST'
        )
        
        # ✅ Validar que se mueve el SL
        assert decision.mover_sl is True
        assert decision.nuevo_sl is not None
        
        # ✅ Validar que el SL es >= entrada (breakeven)
        assert decision.nuevo_sl >= pos['entrada']
        
        # ✅ Validar que la razón indica breakeven
        assert 'BREAKEVEN' in decision.razon.upper()
    
    def test_trailing_suave_con_ganancia_media(self):
        """
        Valida que el SL se mueve detrás del precio cuando hay ganancia media.
        """
        # Crear posición con ganancia media
        pos = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': 1.0800,
            'sl': 1.0780,
            'tp': 1.0900,
            'lotes': 0.01,
            'nivel_usado': 1.0780,
            'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=2)
        }
        
        # Precio actual: 1.0850 (ganancia de 50 pips)
        precio_actual = 1.0850
        df_h1 = self._crear_df_h1_tendencia_alcista(precio_actual)
        
        # Calcular decisión de trailing
        decision = self.engine.calcular_movimiento_sl(
            pos=pos,
            df_h1=df_h1,
            precio_actual=precio_actual,
            fecha=datetime.now(timezone.utc),
            regimen='TREND_ALCISTA_FUERTE',
            modo='RETEST'
        )
        
        # ✅ Validar que se mueve el SL
        assert decision.mover_sl is True
        assert decision.nuevo_sl is not None
        
        # ✅ Validar que el SL está detrás del precio
        assert decision.nuevo_sl < precio_actual
        
        # ✅ Validar que el SL está por encima de la entrada (ganancia asegurada)
        assert decision.nuevo_sl > pos['entrada']
    
    def test_no_mover_sl_sin_ganancia(self):
        """
        Valida que NO se mueve el SL si no hay ganancia suficiente.
        """
        # Crear posición sin ganancia
        pos = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': 1.0800,
            'sl': 1.0780,
            'tp': 1.0900,
            'lotes': 0.01,
            'nivel_usado': 1.0780,
            'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=1)
        }
        
        # Precio actual: 1.0805 (ganancia de solo 5 pips)
        precio_actual = 1.0805
        df_h1 = self._crear_df_h1_tendencia_alcista(precio_actual)
        
        # Calcular decisión de trailing
        decision = self.engine.calcular_movimiento_sl(
            pos=pos,
            df_h1=df_h1,
            precio_actual=precio_actual,
            fecha=datetime.now(timezone.utc),
            regimen='TREND_ALCISTA_FUERTE',
            modo='RETEST'
        )
        
        # ✅ Validar que NO se mueve el SL
        assert decision.mover_sl is False
        assert decision.nuevo_sl is None
    
    def test_no_mover_sl_con_perdida(self):
        """
        Valida que NO se mueve el SL si hay pérdida.
        """
        # Crear posición con pérdida
        pos = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': 1.0800,
            'sl': 1.0780,
            'tp': 1.0900,
            'lotes': 0.01,
            'nivel_usado': 1.0780,
            'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=1)
        }
        
        # Precio actual: 1.0790 (pérdida de 10 pips)
        precio_actual = 1.0790
        df_h1 = self._crear_df_h1_tendencia_alcista(precio_actual)
        
        # Calcular decisión de trailing
        decision = self.engine.calcular_movimiento_sl(
            pos=pos,
            df_h1=df_h1,
            precio_actual=precio_actual,
            fecha=datetime.now(timezone.utc),
            regimen='TREND_ALCISTA_FUERTE',
            modo='RETEST'
        )
        
        # ✅ Validar que NO se mueve el SL
        assert decision.mover_sl is False
        assert decision.nuevo_sl is None
    
    def test_cierre_por_estructura_rota(self):
        """
        Valida que el sistema cierra si la estructura se rompe.
        """
        # Crear posición
        pos = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': 1.0800,
            'sl': 1.0780,
            'tp': 1.0900,
            'lotes': 0.01,
            'nivel_usado': 1.0780,
            'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=1)
        }
        
        # Crear DataFrame con estructura rota (precio cayendo)
        np.random.seed(42)
        n = 100
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq='1h', tz='UTC')
        
        # Tendencia BAJISTA (precio cae)
        precio_base = 1.0800
        tendencia = np.linspace(0, -0.005, n)  # CAE
        ruido = np.random.randn(n) * 0.0005
        
        close = precio_base + tendencia + ruido
        
        df_h1 = pd.DataFrame({
            'Open': close - np.random.randn(n) * 0.0002,
            'High': close + np.abs(np.random.randn(n)) * 0.0003,
            'Low': close - np.abs(np.random.randn(n)) * 0.0003,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        
        df_h1['High'] = df_h1[['Open', 'Close', 'High']].max(axis=1)
        df_h1['Low'] = df_h1[['Open', 'Close', 'Low']].min(axis=1)
        
        # Precio actual: 1.0790 (pérdida, pero estructura rota)
        precio_actual = 1.0790
        
        # Calcular decisión de trailing
        decision = self.engine.calcular_movimiento_sl(
            pos=pos,
            df_h1=df_h1,
            precio_actual=precio_actual,
            fecha=datetime.now(timezone.utc),
            regimen='TREND_ALCISTA_FUERTE',
            modo='RETEST'
        )
        
        # ✅ Validar que se cierra la posición
        assert decision.cerrar is True
        assert decision.motivo_cierre is not None
        assert "estructura" in decision.motivo_cierre.lower() or "soporte" in decision.motivo_cierre.lower()
    
    def test_integracion_monitor_con_trailing(self):
        """
        Valida la integración completa del monitor con el trailing.
        """
        # Configurar posición en el estado del orquestador
        ticket = 12345
        self.orquestador_mock.estado.posiciones_abiertas[ticket] = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': 1.0800,
            'sl': 1.0780,
            'tp': 1.0900,
            'lotes': 0.01,
            'nivel_usado': 1.0780,
            'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=1)
        }
        
        # Configurar posición de MT5
        self.mt5_mock.obtener_posiciones.return_value = [
            {
                'ticket': ticket,
                'simbolo': 'EURUSD',
                'tipo': 'BUY',
                'precio_apertura': 1.0800,
                'precio_actual': 1.0820,  # Ganancia de 20 pips
                'sl': 1.0780,
                'tp': 1.0900,
                'volumen': 0.01,
                'magic': 123456,
                'time': int(datetime.now(timezone.utc).timestamp())
            }
        ]
        
        # ✅ CORRECCIÓN: Mockear _obtener_precio_simulado para que retorne 1.0820
        with patch.object(self.monitor, '_obtener_precio_simulado', return_value=1.0820):
            # ✅ Patch del análisis para que no interfiera
            with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                    # ✅ Patch del cierre para que NO cierre (queremos ver el movimiento del SL)
                    with patch.object(self.monitor, '_cerrar_posicion') as mock_cerrar:
                        # Ejecutar procesamiento de la posición
                        self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                        
                        # ✅ Verificar que NO se cerró la posición (SL invertido no debe ocurrir)
                        mock_cerrar.assert_not_called()
        
        # ✅ Verificar que el SL se actualizó en el estado del orquestador
        sl_actualizado = self.orquestador_mock.estado.posiciones_abiertas[ticket]['sl']
        assert sl_actualizado >= 1.0800  # Breakeven o mejor