#!/usr/bin/env python3
"""
tests/test_monitoreo_v974.py (V1.0)
Valida el monitor de posiciones V9.74 - con protección contra retrocesos.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from trading.monitoreo import MonitorPosiciones
from trading.trailing import TrailingEngine


class TestMonitorV974:
    """Validación del monitor V9.74 con protección contra retrocesos."""
    
    def setup_method(self):
        """Configura el monitor."""
        self.orquestador_mock = MagicMock()
        self.orquestador_mock.modo_backtest = True
        self.orquestador_mock.estado.posiciones_abiertas = {}
        
        # Mock de caché
        self.cache_mock = MagicMock()
        self.orquestador_mock.cache = self.cache_mock
        
        # Mock del conector MT5
        self.mt5_mock = MagicMock()
        self.mt5_mock.obtener_precio.return_value = {
            'bid': 1.0805,
            'ask': 1.0810,
            'spread_pips': 0.5,
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
        
        # Mock de gestión de riesgo
        self.gestion_riesgo_mock = MagicMock()
        self.gestion_riesgo_mock.capital_actual = 1000.0
        
        # Crear monitor SIN DecisorCierre
        self.monitor = MonitorPosiciones(
            orquestador=self.orquestador_mock,
            mt5=self.mt5_mock,
            gestion_riesgo=self.gestion_riesgo_mock,
            trailing_engine=TrailingEngine(modo_backtest=True),
            decisor_cierre=None  # ✅ SIN DecisorCierre
        )
    
    def _configurar_posicion_compra(self, ticket=12345, entrada=1.0800, sl=1.0780, tp=1.0900, lotes=0.01):
        """Configura una posición de COMPRA."""
        fecha_entrada = datetime.now(timezone.utc) - timedelta(hours=1)
        
        self.orquestador_mock.estado.posiciones_abiertas[ticket] = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': entrada,
            'sl': sl,
            'tp': tp,
            'lotes': lotes,
            'nivel_usado': sl,
            'fecha_entrada': fecha_entrada,
            'modo': 'RETEST'
        }
        
        self.mt5_mock.obtener_posiciones.return_value = [
            {
                'ticket': ticket,
                'simbolo': 'EURUSD',
                'tipo': 'BUY',
                'precio_apertura': entrada,
                'precio_actual': entrada + 0.0020,
                'sl': sl,
                'tp': tp,
                'volumen': lotes,
                'magic': 123456,
                'time': int(fecha_entrada.timestamp()),
                'fecha_entrada': fecha_entrada
            }
        ]
    
    def test_no_mueve_sl_sin_ganancia_suficiente(self):
        """
        Valida que NO mueve SL si la ganancia es menor a 2x ATR.
        """
        # Configurar ATR mock (8 pips)
        with patch.object(self.monitor, '_obtener_atr_pips', return_value=8.0):
            # Configurar posición con ganancia de 5 pips (menos que 2x ATR=16)
            self._configurar_posicion_compra()
            precio_actual = 1.0805  # Ganancia de 5 pips
            
            with patch.object(self.monitor, '_obtener_precio_simulado', return_value=precio_actual):
                with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                    with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                        with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover_sl:
                            self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                            
                            mock_mover_sl.assert_not_called()
    
    def test_mueve_sl_breakeven_con_ganancia_suficiente(self):
        """
        Valida que MUEVE SL a breakeven si la ganancia >= 2x ATR.
        """
        # Configurar ATR mock (8 pips)
        with patch.object(self.monitor, '_obtener_atr_pips', return_value=8.0):
            # Configurar posición con ganancia de 20 pips (>= 2x ATR=16)
            self._configurar_posicion_compra()
            precio_actual = 1.0820  # Ganancia de 20 pips
            
            with patch.object(self.monitor, '_obtener_precio_simulado', return_value=precio_actual):
                with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                    with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                        with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover_sl:
                            self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                            
                            mock_mover_sl.assert_called()
                            nuevo_sl = mock_mover_sl.call_args[0][1]
                            assert nuevo_sl >= 1.0800  # Breakeven (entrada + 2 pips)
    
    def test_no_mueve_sl_si_retroceso_normal(self):
        """
        Valida que NO mueve SL si hay un retroceso normal (menos de 1.5x ATR).
        """
        # Configurar ATR mock (8 pips)
        with patch.object(self.monitor, '_obtener_atr_pips', return_value=8.0):
            # Configurar posición con ganancia de 20 pips pero SL ya movido
            self._configurar_posicion_compra()
            
            # SL actual = 1.0810 (ya movido a breakeven + 10 pips)
            self.orquestador_mock.estado.posiciones_abiertas[12345]['sl'] = 1.0810
            self.mt5_mock.obtener_posiciones.return_value[0]['sl'] = 1.0810
            
            # Precio actual = 1.0820 (retroceso de 10 pips desde 1.0830)
            precio_actual = 1.0820
            
            with patch.object(self.monitor, '_obtener_precio_simulado', return_value=precio_actual):
                with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                    with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                        with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover_sl:
                            self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                            
                            # ✅ Verificar que NO se mueve el SL (retroceso normal)
                            mock_mover_sl.assert_not_called()
    
    def test_no_cierra_por_decision_sin_decisor(self):
        """
        Valida que NO cierra por decisión si no hay DecisorCierre.
        """
        # Configurar posición con ganancia de 20 pips
        self._configurar_posicion_compra()
        precio_actual = 1.0820
        
        with patch.object(self.monitor, '_obtener_precio_simulado', return_value=precio_actual):
            # Configurar análisis con RSI sobrecompra (pero NO hay DecisorCierre)
            analisis_rapido_mock = SimpleNamespace(rsi=80.0)
            analisis_medio_mock = SimpleNamespace(
                rsi=85.0,
                resistencia_cercana=1.0900,
                soporte_cercano=1.0780,
                macd_histogram=0.0003,
                adx=25.0,
                en_nivel_clave=True
            )
            
            with patch.object(self.monitor, '_reanalizar_mercado', 
                            return_value=(analisis_rapido_mock, analisis_medio_mock)):
                with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                    with patch.object(self.monitor, '_cerrar_posicion') as mock_cerrar:
                        self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                        
                        # ✅ Verificar que NO se cierra por decisión (no hay DecisorCierre)
                        mock_cerrar.assert_not_called()
    
    def test_calcular_umbrales_trailing_por_atr(self):
        """
        Valida el cálculo de umbrales basados en ATR.
        """
        # Configurar ATR mock (10 pips)
        with patch.object(self.monitor, '_obtener_atr_pips', return_value=10.0):
            lotes = 0.02
            umbrales = self.monitor._calcular_umbrales_trailing('EURUSD', lotes, 10.0)
            
            # Verificar umbrales
            assert umbrales['breakeven_umbral'] >= 20  # 2x ATR
            assert umbrales['trailing_umbral'] >= 30   # 3x ATR
            assert umbrales['trailing_agresivo_umbral'] >= 40  # 4x ATR
    
    def test_calcular_distancia_trailing(self):
        """
        Valida el cálculo de la distancia del trailing basada en ATR.
        """
        distancia = self.monitor._calcular_distancia_trailing('EURUSD', 10.0)
        
        assert distancia >= 15  # Mínimo 15 pips
        assert distancia == pytest.approx(15.0)  # 1.5x ATR = 15 pips
    
    def test_debe_mover_sl(self):
        """
        Valida la regla de "No Tocar" durante retrocesos normales.
        """
        # Ganancia de 20 pips, ATR = 10 pips
        debe_mover, razon = self.monitor._debe_mover_sl(
            simbolo='EURUSD',
            ganancia_pips=20.0,
            sl_actual=1.0800,
            precio_actual=1.0820,
            direccion='COMPRA',
            atr_pips=10.0
        )
        
        assert debe_mover is True
        assert razon == "OK"
    
    def test_no_mover_sl_si_retroceso(self):
        """
        Valida que NO mueve SL si el precio retrocedió.
        """
        # SL a 1.0810, precio actual a 1.0820 (distancia 10 pips)
        # ATR = 10 pips, distancia mínima = 15 pips
        debe_mover, razon = self.monitor._debe_mover_sl(
            simbolo='EURUSD',
            ganancia_pips=20.0,
            sl_actual=1.0810,
            precio_actual=1.0820,
            direccion='COMPRA',
            atr_pips=10.0
        )
        
        assert debe_mover is False
        assert "cerca" in razon.lower()
