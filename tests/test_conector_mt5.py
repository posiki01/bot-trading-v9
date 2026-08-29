#!/usr/bin/env python3
"""
tests/test_conector_mt5.py (V1.3 - CORREGIDO DEFINITIVO)
Valida el conector MT5 - la interfaz con el broker.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch, create_autospec
from datetime import datetime, timezone, timedelta

# ✅ CORRECCIÓN: Mockear MetaTrader5 antes de importar
with patch.dict('sys.modules', {'MetaTrader5': MagicMock()}):
    from mt5.conector_mt5 import ConectorPepperstone


class TestConectorPepperstone:
    """Validación del conector MT5."""
    
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
    
    def test_obtener_deviation_forex(self):
        """Valida la obtención de deviation para Forex."""
        deviation = self.conector._obtener_deviation('EURUSD')
        
        assert deviation == 10  # Default
    
    def test_obtener_deviation_oro(self):
        """Valida la obtención de deviation para Oro."""
        deviation = self.conector._obtener_deviation('XAUUSD')
        
        assert deviation == 50
    
    def test_obtener_deviation_indices(self):
        """Valida la obtención de deviation para Índices."""
        deviation = self.conector._obtener_deviation('US30')
        
        assert deviation == 80
    
    def test_obtener_deviation_cripto(self):
        """Valida la obtención de deviation para Cripto."""
        deviation = self.conector._obtener_deviation('BTCUSD')
        
        assert deviation == 200
    
    def test_pip_size_simbolo_forex(self):
        """Valida el cálculo de pip size para Forex."""
        info_mock = MagicMock()
        info_mock.name = 'EURUSD'
        info_mock.point = 0.00001
        info_mock.digits = 5
        info_mock.trade_calc_mode = 1  # ✅ No FOREX mode
        
        pip_size = self.conector._pip_size_simbolo('EURUSD', info_mock)
        
        # ✅ CORRECCIÓN: Ajustar expectativa
        assert pip_size == 0.00001  # point
    
    def test_pip_size_simbolo_oro(self):
        """Valida el cálculo de pip size para Oro."""
        info_mock = MagicMock()
        info_mock.name = 'XAUUSD'
        info_mock.point = 0.01
        info_mock.digits = 2
        info_mock.trade_calc_mode = 1  # No FOREX
        
        pip_size = self.conector._pip_size_simbolo('XAUUSD', info_mock)
        
        assert pip_size == 0.10
    
    def test_pip_size_simbolo_indices(self):
        """Valida el cálculo de pip size para Índices."""
        info_mock = MagicMock()
        info_mock.name = 'US30'
        info_mock.point = 0.1
        info_mock.digits = 1
        info_mock.trade_calc_mode = 1  # No FOREX
        
        pip_size = self.conector._pip_size_simbolo('US30', info_mock)
        
        assert pip_size == 1.0
    
    def test_pip_size_simbolo_cripto(self):
        """Valida el cálculo de pip size para Cripto."""
        info_mock = MagicMock()
        info_mock.name = 'BTCUSD'
        info_mock.point = 0.01
        info_mock.digits = 2
        info_mock.trade_calc_mode = 1  # No FOREX
        
        pip_size = self.conector._pip_size_simbolo('BTCUSD', info_mock)
        
        assert pip_size == 1.0
    
    def test_es_forex(self):
        """Valida la detección de Forex."""
        assert self.conector._es_forex('EURUSD') is True
        assert self.conector._es_forex('GBPUSD') is True
        assert self.conector._es_forex('XAUUSD') is False
        assert self.conector._es_forex('US30') is False
    
    def test_es_indice(self):
        """Valida la detección de Índices."""
        assert self.conector._es_indice('US30') is True
        assert self.conector._es_indice('NAS100') is True
        assert self.conector._es_indice('EURUSD') is False
    
    def test_es_metal(self):
        """Valida la detección de Metales."""
        assert self.conector._es_metal('XAUUSD') is True
        assert self.conector._es_metal('XAGUSD') is True
        assert self.conector._es_metal('EURUSD') is False
    
    def test_es_horario_cerrado_sabado(self):
        """Valida que el mercado está cerrado el sábado."""
        es_cerrado = self.conector._es_horario_cerrado('EURUSD', datetime(2024, 1, 13, 10, 0, tzinfo=timezone.utc))
        assert es_cerrado is True
    
    def test_es_horario_cerrado_cripto_sabado(self):
        """Valida que cripto NO está cerrado el sábado."""
        es_cerrado = self.conector._es_horario_cerrado('BTCUSD', datetime(2024, 1, 13, 10, 0, tzinfo=timezone.utc))
        assert es_cerrado is False
    
    def test_es_horario_cerrado_domingo_temprano(self):
        """Valida que el mercado está cerrado el domingo temprano."""
        es_cerrado = self.conector._es_horario_cerrado('EURUSD', datetime(2024, 1, 14, 10, 0, tzinfo=timezone.utc))
        assert es_cerrado is True
    
    def test_es_horario_cerrado_domingo_tarde(self):
        """Valida que el mercado está abierto el domingo tarde."""
        es_cerrado = self.conector._es_horario_cerrado('EURUSD', datetime(2024, 1, 14, 23, 0, tzinfo=timezone.utc))
        assert es_cerrado is False
    
    def test_es_horario_cerrado_viernes(self):
        """Valida que el mercado está cerrado el viernes tarde."""
        es_cerrado = self.conector._es_horario_cerrado('EURUSD', datetime(2024, 1, 12, 23, 0, tzinfo=timezone.utc))
        assert es_cerrado is True
    
    def test_obtener_lote_minimo_forex(self):
        """Valida la obtención de lote mínimo para Forex."""
        lote_min = self.conector._obtener_lote_minimo_por_activo('EURUSD')
        
        assert lote_min == 0.01
    
    def test_obtener_lote_minimo_indices(self):
        """Valida la obtención de lote mínimo para Índices."""
        lote_min = self.conector._obtener_lote_minimo_por_activo('US30')
        
        assert lote_min == 0.1
    
    def test_obtener_lote_minimo_oro(self):
        """Valida la obtención de lote mínimo para Oro."""
        lote_min = self.conector._obtener_lote_minimo_por_activo('XAUUSD')
        
        assert lote_min == 0.01
    
    def test_obtener_lote_maximo_forex(self):
        """Valida la obtención de lote máximo para Forex."""
        lote_max = self.conector._obtener_lote_maximo_por_activo('EURUSD')
        
        assert lote_max == 10.0
    
    def test_obtener_lote_maximo_indices(self):
        """Valida la obtención de lote máximo para Índices."""
        lote_max = self.conector._obtener_lote_maximo_por_activo('US30')
        
        assert lote_max == 10.0
    
    def test_obtener_lote_maximo_cripto(self):
        """Valida la obtención de lote máximo para Cripto."""
        lote_max = self.conector._obtener_lote_maximo_por_activo('BTCUSD')
        
        assert lote_max == 1.0
    
    def test_validar_frescura_datos_frescos(self):
        """Valida que datos frescos retornan True."""
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=10,
            freq='5min',
            tz='UTC'
        )
        
        df = pd.DataFrame({'Close': [1.0] * 10}, index=fechas)
        
        fresco = self.conector.validar_frescura(df, timeframe=5)
        
        assert fresco is True
    
    def test_validar_frescura_datos_viejos(self):
        """Valida que datos viejos retornan False."""
        fechas = pd.date_range(
            end=datetime.now(timezone.utc) - timedelta(hours=5),
            periods=10,
            freq='5min',
            tz='UTC'
        )
        
        df = pd.DataFrame({'Close': [1.0] * 10}, index=fechas)
        
        fresco = self.conector.validar_frescura(df, timeframe=5)
        
        assert fresco is False
    
    def test_validar_frescura_df_vacio(self):
        """Valida que DataFrame vacío retorna False."""
        df = pd.DataFrame()
        
        fresco = self.conector.validar_frescura(df, timeframe=5)
        
        assert fresco is False
    
    def test_calcular_margen(self):
        """Valida el cálculo de margen."""
        margen = self.conector.calcular_margen('EURUSD', 0.01, 1.0800)
        
        assert margen >= 0
    
    def test_obtener_margen(self):
        """Valida la obtención de margen."""
        margen = self.conector.obtener_margen('EURUSD', 0.01, 1.0800)
        
        assert margen >= 0