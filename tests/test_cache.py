#!/usr/bin/env python3
"""
tests/test_cache.py (V1.1 - CORREGIDO)
Valida el sistema unificado de caché.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from utils.cache import CacheUnificado


class TestCacheUnificado:
    """Validación del sistema de caché."""
    
    def setup_method(self):
        """Configura la caché."""
        self.cache = CacheUnificado(
            max_size=100,
            default_ttl=60,
            modo_backtest=True
        )
        
        # ✅ CORRECCIÓN: Limpiar caché persistente para evitar datos antiguos
        self.cache._cache.clear()
        self.cache._indice_simbolo.clear()
        self.cache._indice_fase.clear()
    
    def test_set_get_valido(self):
        """Valida set y get con datos válidos."""
        self.cache.set(('EURUSD', 60, 100), {'datos': 'test'})
        
        resultado = self.cache.get(('EURUSD', 60, 100))
        
        assert resultado is not None
        assert resultado['datos'] == 'test'
    
    def test_get_no_existente(self):
        """Valida get cuando la clave no existe."""
        resultado = self.cache.get(('NOEXISTE', 60, 100))
        
        assert resultado is None
    
    def test_set_none(self):
        """Valida que set con None no guarda."""
        # ✅ CORRECCIÓN: Usar clave NUEVA que no exista
        self.cache.set(('NUEVA_KEY', 60, 100), None)
        
        resultado = self.cache.get(('NUEVA_KEY', 60, 100))
        
        assert resultado is None
    
    def test_get_or_compute(self):
        """Valida get_or_compute con función de cálculo."""
        def calcular():
            return {'resultado': 42}
        
        resultado = self.cache.get_or_compute(
            ('EURUSD', 'fase1', 'hash'),
            calcular,
            ttl=60
        )
        
        assert resultado is not None
        assert resultado['resultado'] == 42
    
    def test_get_or_compute_cache_hit(self):
        """Valida que get_or_compute usa la caché si ya existe."""
        # Primero calcular
        self.cache.set(('EURUSD', 'fase1', 'hash'), {'resultado': 42})
        
        # Luego intentar calcular de nuevo (debería usar caché)
        def calcular():
            return {'resultado': 99}
        
        resultado = self.cache.get_or_compute(
            ('EURUSD', 'fase1', 'hash'),
            calcular,
            ttl=60
        )
        
        assert resultado['resultado'] == 42  # Usa el valor de la caché, no el nuevo
    
    def test_invalidate(self):
        """Valida la invalidación de caché."""
        self.cache.set(('EURUSD', 60, 100), {'datos': 'test'})
        
        self.cache.invalidate(('EURUSD', 60, 100))
        
        resultado = self.cache.get(('EURUSD', 60, 100))
        
        assert resultado is None
    
    def test_invalidate_por_simbolo(self):
        """Valida la invalidación por símbolo."""
        self.cache.set(('EURUSD', 60, 100), {'datos': 'test1'})
        self.cache.set(('EURUSD', 240, 100), {'datos': 'test2'})
        self.cache.set(('GBPUSD', 60, 100), {'datos': 'test3'})
        
        self.cache.invalidate_por_simbolo('EURUSD')
        
        assert self.cache.get(('EURUSD', 60, 100)) is None
        assert self.cache.get(('EURUSD', 240, 100)) is None
        assert self.cache.get(('GBPUSD', 60, 100)) is not None
    
    def test_clear(self):
        """Valida la limpieza completa de caché."""
        self.cache.set(('EURUSD', 60, 100), {'datos': 'test'})
        self.cache.set(('GBPUSD', 60, 100), {'datos': 'test2'})
        
        self.cache.clear()
        
        assert self.cache.get(('EURUSD', 60, 100)) is None
        assert self.cache.get(('GBPUSD', 60, 100)) is None
    
    def test_get_datos(self):
        """Valida la obtención de datos."""
        df = pd.DataFrame({'Close': [1.0, 1.1, 1.2], 'Volume': [100, 200, 300]})
        df.index = pd.date_range(end=datetime.now(timezone.utc), periods=3, freq='1h')
        
        def fetch_func(simbolo, n_velas, timeframe):
            return df
        
        resultado = self.cache.get_datos('EURUSD', 60, 100, fetch_func)
        
        assert resultado is not None
        assert len(resultado) == 3
        assert isinstance(resultado, pd.DataFrame)
    
    def test_get_stats(self):
        """Valida la obtención de estadísticas."""
        stats = self.cache.get_stats()
        
        assert 'hits' in stats
        assert 'misses' in stats
        assert 'current_size' in stats
    
    def test_ttl_expirado(self):
        """Valida que los datos expiran según TTL."""
        self.cache.set(('EURUSD', 60, 100), {'datos': 'test'}, ttl=0)
        
        # Esperar un poco para que expire
        import time
        time.sleep(0.1)
        
        resultado = self.cache.get(('EURUSD', 60, 100))
        
        assert resultado is None
    
    def test_calcular_hash(self):
        """Valida el cálculo de hash."""
        df1 = pd.DataFrame({'Close': [1.0, 1.1, 1.2], 'Volume': [100, 200, 300]})
        df2 = pd.DataFrame({'Close': [1.0, 1.1, 1.2], 'Volume': [100, 200, 300]})
        
        hash1 = self.cache._calcular_hash(df1)
        hash2 = self.cache._calcular_hash(df2)
        
        assert hash1 == hash2
    
    def test_guardar_y_cargar_sqlite(self):
        """Valida el guardado y carga desde SQLite."""
        # Mock del almacenamiento
        almacen_mock = MagicMock()
        self.cache.almacen = almacen_mock
        
        df = pd.DataFrame({'Close': [1.0, 1.1, 1.2], 'Volume': [100, 200, 300]})
        
        self.cache._guardar_en_sqlite('EURUSD', 60, df)
        
        almacen_mock.guardar_datos_historicos.assert_called_once()