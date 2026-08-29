#!/usr/bin/env python3
"""
tests/test_pnl_mt5.py (V1.5 - CORREGIDO DEFINITIVO)
Valida que el bot consulta el P&L real de MT5.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# ✅ CORRECCIÓN: Mockear MetaTrader5 antes de importar
with patch.dict('sys.modules', {'MetaTrader5': MagicMock()}):
    from mt5.conector_mt5 import ConectorPepperstone


class TestPnLMT5:
    """Validación del cálculo de P&L desde MT5."""
    
    def setup_method(self):
        """Configura el conector."""
        self.conector = ConectorPepperstone(
            login=123456,
            password='test',
            server='Pepperstone-Demo',
            magic_number=123456,
            demo=True,
            almacen=MagicMock()
        )
        
        # ✅ CORRECCIÓN: Forzar conexión para que los métodos se ejecuten
        self.conector.conectado = True
    
    def test_obtener_posiciones_con_pnl(self):
        """Valida que obtener_posiciones devuelve P&L en USD."""
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
            pos_mock.profit = 2.00
            pos_mock.swap = 0.0
            pos_mock.magic = 123456
            pos_mock.time = int(datetime.now(timezone.utc).timestamp())
            
            mock_positions_get.return_value = [pos_mock]
            
            posiciones = self.conector.obtener_posiciones(force=True)
            
            assert len(posiciones) == 1
            assert posiciones[0]['ganancia'] == 2.00
            assert posiciones[0]['swap'] == 0.0
            assert posiciones[0]['ticket'] == 12345
    
    def test_obtener_detalle_cierre_con_pnl(self):
        """Valida que obtener_detalle_cierre devuelve P&L real."""
        with patch.object(self.conector.mt5, 'history_deals_get') as mock_history_get:
            deal_mock = MagicMock()
            deal_mock.profit = 5.00
            deal_mock.commission = -0.50
            deal_mock.swap = 0.0
            deal_mock.price = 1.0850
            deal_mock.time = int(datetime.now(timezone.utc).timestamp())
            deal_mock.entry = 1
            
            mock_history_get.return_value = [deal_mock]
            
            detalle = self.conector.obtener_detalle_cierre(12345)
            
            assert detalle is not None
            assert detalle['ganancia'] == 5.00
            assert detalle['comision'] == -0.50
            assert detalle['swap'] == 0.0
    
    def test_info_cuenta_con_balance(self):
        """Valida que info_cuenta devuelve balance y equity reales."""
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
            assert cuenta['equity'] == 1002.50
            assert cuenta['margen_libre'] == 800.00
    
    def test_obtener_historial_con_pnl(self):
        """Valida que obtener_historial_operaciones devuelve P&L real."""
        with patch.object(self.conector.mt5, 'history_deals_get') as mock_history_get:
            with patch.object(self.conector.mt5, 'positions_get', return_value=[]):
                with patch.object(self.conector.mt5, 'orders_get', return_value=[]):
                    # ✅ CORRECCIÓN: Configurar TODOS los atributos del deal
                    deal_mock = MagicMock()
                    deal_mock.order = 12345
                    deal_mock.deal = 67890
                    deal_mock.symbol = 'EURUSD'
                    deal_mock.type = 0  # BUY
                    deal_mock.entry = 1  # DEAL_ENTRY_OUT
                    deal_mock.price = 1.0800
                    deal_mock.volume = 0.01
                    deal_mock.profit = 2.00
                    deal_mock.commission = -0.50
                    deal_mock.swap = 0.0
                    deal_mock.time = int(datetime.now(timezone.utc).timestamp())  # ✅ Número
                    deal_mock.magic = 123456
                    
                    # ✅ CORRECCIÓN: Configurar constantes de MT5
                    self.conector.mt5.DEAL_TYPE_BUY = 0
                    self.conector.mt5.DEAL_TYPE_SELL = 1
                    self.conector.mt5.DEAL_TYPE_BUY_STOP = 2
                    self.conector.mt5.DEAL_TYPE_SELL_STOP = 3
                    self.conector.mt5.DEAL_TYPE_BUY_LIMIT = 4
                    self.conector.mt5.DEAL_TYPE_SELL_LIMIT = 5
                    
                    self.conector.mt5.DEAL_ENTRY_IN = 0
                    self.conector.mt5.DEAL_ENTRY_OUT = 1
                    self.conector.mt5.DEAL_ENTRY_INOUT = 2
                    self.conector.mt5.DEAL_ENTRY_OUT_BY = 3
                    
                    mock_history_get.return_value = [deal_mock]
                    
                    historial = self.conector.obtener_historial_operaciones()
                    
                    assert len(historial) == 1
                    assert historial[0]['ganancia'] == 2.00
                    assert historial[0]['comision'] == -0.50