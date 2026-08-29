#!/usr/bin/env python3
"""
tests/test_gestion_sl_correcta.py (V1.0)
Valida que el SL se mueve SOLO cuando hay ganancia significativa.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from trading.monitoreo import MonitorPosiciones
from trading.trailing import TrailingEngine


class TestGestionSLCorrecta:
    """Validación de la gestión correcta del SL."""
    
    def setup_method(self):
        """Configura el monitor."""
        self.orquestador_mock = MagicMock()
        self.orquestador_mock.modo_backtest = True
        self.orquestador_mock.estado.posiciones_abiertas = {}
        
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
        
        self.gestion_riesgo_mock = MagicMock()
        self.gestion_riesgo_mock.capital_actual = 1000.0
        
        self.monitor = MonitorPosiciones(
            orquestador=self.orquestador_mock,
            mt5=self.mt5_mock,
            gestion_riesgo=self.gestion_riesgo_mock,
            trailing_engine=TrailingEngine(modo_backtest=True),
            decisor_cierre=MagicMock(return_value=None)
        )
    
    def _configurar_posicion(self, ticket=12345, entrada=1.0800, sl=1.0780, tp=1.0900):
        """Configura posición COMPRA."""
        fecha_entrada = datetime.now(timezone.utc) - timedelta(hours=1)
        
        self.orquestador_mock.estado.posiciones_abiertas[ticket] = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': entrada,
            'sl': sl,
            'tp': tp,
            'lotes': 0.01,
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
                'volumen': 0.01,
                'magic': 123456,
                'time': int(fecha_entrada.timestamp()),
                'fecha_entrada': fecha_entrada
            }
        ]
    
    def test_no_mover_sl_con_ganancia_pequena(self):
        """Valida que NO mueve SL con ganancia de solo 2 pips."""
        self._configurar_posicion()
        
        # Precio con ganancia de 2 pips (1.0802)
        with patch.object(self.monitor, '_obtener_precio_simulado', return_value=1.0802):
            with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                    with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover_sl:
                        self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                        
                        # ✅ NO debe mover SL
                        mock_mover_sl.assert_not_called()
    
    def test_no_mover_sl_con_ganancia_10_pips(self):
        """Valida que NO mueve SL con ganancia de 10 pips."""
        self._configurar_posicion()
        
        # Precio con ganancia de 10 pips (1.0810)
        with patch.object(self.monitor, '_obtener_precio_simulado', return_value=1.0810):
            with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                    with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover_sl:
                        self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                        
                        # ✅ NO debe mover SL (menos de 20 pips)
                        mock_mover_sl.assert_not_called()
    
    def test_mover_sl_con_ganancia_25_pips(self):
        """Valida que SÍ mueve SL con ganancia de 25 pips."""
        self._configurar_posicion()
        
        # Precio con ganancia de 25 pips (1.0825)
        with patch.object(self.monitor, '_obtener_precio_simulado', return_value=1.0825):
            with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                    with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover_sl:
                        self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                        
                        # ✅ SÍ debe mover SL (25 >= 20 pips)
                        mock_mover_sl.assert_called()
    
    def test_mover_sl_a_breakeven(self):
        """Valida que mueve SL a breakeven (entrada + 2 pips)."""
        self._configurar_posicion()
        
        with patch.object(self.monitor, '_obtener_precio_simulado', return_value=1.0825):
            with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                    with patch.object(self.monitor, '_mover_sl', return_value=True) as mock_mover_sl:
                        self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                        
                        # ✅ Verificar que el nuevo SL es >= entrada
                        nuevo_sl = mock_mover_sl.call_args[0][1]
                        assert nuevo_sl >= 1.0800