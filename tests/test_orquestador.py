# tests/test_orquestador.py
"""
Valida la inicialización y métodos principales del orquestador.
"""

import pytest
from unittest.mock import MagicMock, patch
from core.orquestador import Orquestador


class TestOrquestador:
    """Validación del orquestador."""
    
    def setup_method(self):
        """Configura orquestador mock."""
        with patch.object(Orquestador, '__init__', lambda self: None):
            self.orquestador = Orquestador.__new__(Orquestador)
            self.orquestador.modo_backtest = True
            self.orquestador.mt5 = MagicMock()
            self.orquestador.cache = MagicMock()
            self.orquestador.estado = MagicMock()
            self.orquestador.logger = MagicMock()
    
    def test_obtener_df_m5_con_precio_real(self):
        """Valida la obtención de DataFrame M5 con precio real."""
        # Configurar cache
        import pandas as pd
        import numpy as np
        from datetime import datetime, timezone
        
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=100,
            freq='5min',
            tz='UTC'
        )
        
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
            'bid': 1.0805,
            'ask': 1.0810,
            'spread_pips': 0.5,
            'digits': 5,
            'point': 0.00001,
            'pip_size': 0.0001
        }
        
        df_resultado = self.orquestador._obtener_df_m5_con_precio_real('EURUSD')
        
        assert df_resultado is not None
        assert len(df_resultado) > 0
        assert 'precio_tick' in df_resultado.attrs
    
    def test_obtener_df_m5_sin_tick(self):
        """Valida que si no hay tick, usa datos existentes."""
        import pandas as pd
        import numpy as np
        from datetime import datetime, timezone
        
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=100,
            freq='5min',
            tz='UTC'
        )
        
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
        self.orquestador.mt5.obtener_precio.return_value = None  # Sin tick
        
        df_resultado = self.orquestador._obtener_df_m5_con_precio_real('EURUSD')
        
        assert df_resultado is not None
        assert len(df_resultado) > 0