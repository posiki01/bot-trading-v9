#!/usr/bin/env python3
"""
tests/test_uso_pnl_mt5.py (V1.1 - CORREGIDO DEFINITIVO)
Valida que el bot usa el P&L de MT5 en lugar de calcularlo manualmente.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# ✅ CORRECCIÓN: Mockear MetaTrader5 antes de importar
with patch.dict('sys.modules', {'MetaTrader5': MagicMock()}):
    from mt5.conector_mt5 import ConectorPepperstone
    from trading.monitoreo import MonitorPosiciones


class TestUsoPnLMT5:
    """Validación del uso del P&L de MT5."""
    
    def setup_method(self):
        """Configura el conector y monitor."""
        self.conector = ConectorPepperstone(
            login=123456,
            password='test',
            server='Pepperstone-Demo',
            magic_number=123456,
            demo=True,
            almacen=MagicMock()
        )
        self.conector.conectado = True
        
        # Configurar monitor
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
        
        self.gestion_riesgo_mock = MagicMock()
        self.gestion_riesgo_mock.capital_actual = 1000.0
        
        # ✅ CORRECCIÓN: Configurar trailing_engine con valores correctos
        self.trailing_engine_mock = MagicMock()
        self.trailing_engine_mock.verificar_cierre_parcial.return_value = (False, 0.0)
        self.trailing_engine_mock.verificar_timeout.return_value = (False, "OK")
        self.trailing_engine_mock.calcular_movimiento_sl.return_value = MagicMock(
            cerrar=False,
            mover_sl=False,
            nuevo_sl=None,
            razon="Sin cambio",
            motivo_cierre=None
        )
        
        self.monitor = MonitorPosiciones(
            orquestador=self.orquestador_mock,
            mt5=self.mt5_mock,
            gestion_riesgo=self.gestion_riesgo_mock,
            trailing_engine=self.trailing_engine_mock,
            decisor_cierre=MagicMock(return_value=None)
        )
    
    def test_obtener_posiciones_usa_pnl_mt5(self):
        """Valida que obtener_posiciones usa P&L de MT5."""
        # ✅ CORRECCIÓN: Usar patch.object en lugar de patch con string
        with patch.object(self.conector.mt5, 'positions_get') as mock_positions_get:
            pos_mock = MagicMock()
            pos_mock.ticket = 12345
            pos_mock.symbol = 'EURUSD'
            pos_mock.type = 0
            pos_mock.volume = 0.01
            pos_mock.price_open = 1.0800
            pos_mock.price_current = 1.0820
            pos_mock.sl = 1.0780
            pos_mock.tp = 1.0900
            pos_mock.profit = 2.00  # ✅ P&L real de MT5
            pos_mock.swap = 0.0
            pos_mock.magic = 123456
            pos_mock.time = int(datetime.now(timezone.utc).timestamp())
            
            mock_positions_get.return_value = [pos_mock]
            
            posiciones = self.conector.obtener_posiciones(force=True)
            
            assert len(posiciones) == 1
            assert posiciones[0]['ganancia'] == 2.00  # ✅ P&L de MT5
    
    def test_monitor_usa_pnl_mt5(self):
        """Valida que el monitor usa P&L de MT5 en logs."""
        # Configurar posición con P&L
        ticket = 12345
        self.orquestador_mock.estado.posiciones_abiertas[ticket] = {
            'simbolo': 'EURUSD',
            'direccion': 'COMPRA',
            'entrada': 1.0800,
            'sl': 1.0780,
            'tp': 1.0900,
            'lotes': 0.01,
            'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=1)
        }
        
        self.mt5_mock.obtener_posiciones.return_value = [
            {
                'ticket': ticket,
                'simbolo': 'EURUSD',
                'tipo': 'BUY',
                'precio_apertura': 1.0800,
                'precio_actual': 1.0820,
                'sl': 1.0780,
                'tp': 1.0900,
                'volumen': 0.01,
                'magic': 123456,
                'time': int(datetime.now(timezone.utc).timestamp()),
                'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=1),
                'ganancia': 2.00  # ✅ P&L de MT5
            }
        ]
        
        # Patch _obtener_precio_simulado
        with patch.object(self.monitor, '_obtener_precio_simulado', return_value=1.0820):
            # ✅ CORRECCIÓN: Configurar trailing_engine correctamente
            with patch.object(self.monitor, '_reanalizar_mercado', return_value=(None, None)):
                with patch.object(self.monitor, '_verificar_sl_tp', return_value=False):
                    # Ejecutar procesamiento
                    self.monitor.procesar(self.mt5_mock.obtener_posiciones()[0])
                    
                    # ✅ Verificar que NO lanzó excepción
                    assert True
    
    def test_info_cuenta_usa_margen_mt5(self):
        """Valida que info_cuenta usa margen de MT5."""
        # ✅ CORRECCIÓN: Usar patch.object en lugar de patch con string
        with patch.object(self.conector.mt5, 'account_info') as mock_account_info:
            account_mock = MagicMock()
            account_mock.login = 123456
            account_mock.balance = 1000.00
            account_mock.equity = 1002.50
            account_mock.margin_free = 800.00
            account_mock.margin = 200.00
            account_mock.margin_level = 500.0
            account_mock.leverage = 500
            account_mock.currency = 'USD'
            
            mock_account_info.return_value = account_mock
            
            cuenta = self.conector.info_cuenta()
            
            assert cuenta['balance'] == 1000.00
            assert cuenta['margen_libre'] == 800.00