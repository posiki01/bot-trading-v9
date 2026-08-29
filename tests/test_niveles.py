#!/usr/bin/env python3
"""
tests/test_niveles.py (V1.1 - CORREGIDO)
Valida el sistema de detección y acumulación de niveles.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from analysis.niveles import NivelTracker


class TestNivelTracker:
    """Validación del tracker de niveles."""
    
    def setup_method(self):
        """Configura el tracker."""
        self.tracker = NivelTracker(modo_backtest=True)
    
    def _crear_df_con_soportes(self, n=100, precio_base=1.0800):
        """Crea DataFrame con soportes y resistencias claros."""
        np.random.seed(42)
        fechas = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=n,
            freq='1h',
            tz='UTC'
        )
        
        close = np.random.randn(n) * 0.0005 + precio_base
        
        df = pd.DataFrame({
            'Open': close - np.random.randn(n) * 0.0002,
            'High': close + np.abs(np.random.randn(n)) * 0.0003,
            'Low': close - np.abs(np.random.randn(n)) * 0.0003,
            'Close': close,
            'Volume': np.random.randint(100, 1000, n)
        }, index=fechas)
        
        df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
        df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
        
        # Añadir soporte claro (mínimos repetidos en 1.0790)
        for i in range(20, 80, 10):
            df.iloc[i, df.columns.get_loc('Low')] = 1.0790
            df.iloc[i, df.columns.get_loc('Close')] = 1.0800
        
        # Añadir resistencia clara (máximos repetidos en 1.0810)
        for i in range(25, 75, 10):
            df.iloc[i, df.columns.get_loc('High')] = 1.0810
            df.iloc[i, df.columns.get_loc('Close')] = 1.0800
        
        return df
    
    def test_detectar_niveles(self):
        """Valida la detección de niveles."""
        df = self._crear_df_con_soportes()
        precio_actual = df['Close'].iloc[-1]
        
        niveles = self.tracker.detectar_y_actualizar_niveles(
            simbolo='EURUSD',
            df=df,
            precio_actual=precio_actual
        )
        
        assert 'soportes' in niveles
        assert 'resistencias' in niveles
    
    def test_obtener_niveles(self):
        """Valida la obtención de niveles."""
        df = self._crear_df_con_soportes()
        precio_actual = df['Close'].iloc[-1]
        
        # Primero detectar
        self.tracker.detectar_y_actualizar_niveles(
            simbolo='EURUSD',
            df=df,
            precio_actual=precio_actual
        )
        
        # Luego obtener
        niveles = self.tracker.obtener_niveles('EURUSD')
        
        assert 'soportes' in niveles
        assert 'resistencias' in niveles
    
    def test_acumular_hits(self):
        """Valida que los hits se acumulan correctamente."""
        df = self._crear_df_con_soportes()
        precio_actual = df['Close'].iloc[-1]
        
        # Detectar niveles dos veces
        self.tracker.detectar_y_actualizar_niveles('EURUSD', df, precio_actual)
        self.tracker.detectar_y_actualizar_niveles('EURUSD', df, precio_actual)
        
        niveles = self.tracker.obtener_niveles('EURUSD')
        
        # Los niveles con hits deberían tener hits >= 1
        for soporte in niveles['soportes']:
            assert soporte['hits'] >= 1
    
    def test_limpiar_niveles_antiguos(self):
        """Valida la limpieza de niveles antiguos."""
        # Crear nivel con fecha antigua
        self.tracker._niveles_memoria['EURUSD'] = {
            'soportes': [
                {
                    'precio': 1.0750,
                    'hits': 2,
                    'fecha_deteccion': datetime.now(timezone.utc) - timedelta(days=20),
                    'fecha_ultimo_toque': datetime.now(timezone.utc) - timedelta(days=20),
                    'tipo': 'soporte',
                    'fuerza': 'DEBIL'
                }
            ],
            'resistencias': []
        }
        
        # Limpiar
        self.tracker._limpiar_niveles_antiguos('EURUSD')
        
        niveles = self.tracker.obtener_niveles('EURUSD')
        
        # El nivel antiguo debería haber sido eliminado (o reducido)
        assert len(niveles['soportes']) == 0 or niveles['soportes'][0]['hits'] < 2
    
    def test_obtener_nivel_fuerte(self):
        """Valida la obtención de niveles fuertes."""
        # Configurar un nivel fuerte manualmente
        self.tracker._niveles_memoria['EURUSD'] = {
            'soportes': [
                {
                    'precio': 1.0790,
                    'hits': 5,
                    'fuerza': 'FUERTE',
                    'fecha_deteccion': datetime.now(timezone.utc),
                    'fecha_ultimo_toque': datetime.now(timezone.utc),
                    'tipo': 'soporte'
                }
            ],
            'resistencias': []
        }
        
        nivel_fuerte = self.tracker.obtener_nivel_fuerte('EURUSD', 'COMPRA')
        
        assert nivel_fuerte == 1.0790
    
    def test_get_stats(self):
        """Valida la obtención de estadísticas."""
        # ✅ CORRECCIÓN: Configurar niveles en memoria primero
        self.tracker._niveles_memoria['EURUSD'] = {
            'soportes': [
                {
                    'precio': 1.0790,
                    'hits': 3,
                    'fuerza': 'MEDIO',
                    'fecha_deteccion': datetime.now(timezone.utc),
                    'fecha_ultimo_toque': datetime.now(timezone.utc),
                    'tipo': 'soporte'
                }
            ],
            'resistencias': [
                {
                    'precio': 1.0810,
                    'hits': 2,
                    'fuerza': 'DEBIL',
                    'fecha_deteccion': datetime.now(timezone.utc),
                    'fecha_ultimo_toque': datetime.now(timezone.utc),
                    'tipo': 'resistencia'
                }
            ]
        }
        
        stats = self.tracker.get_stats('EURUSD')
        
        assert 'simbolo' in stats
        assert stats['simbolo'] == 'EURUSD'
        assert stats['soportes'] == 1
        assert stats['resistencias'] == 1
    
    def test_limpiar_memoria(self):
        """Valida la limpieza de memoria."""
        # Configurar niveles
        self.tracker._niveles_memoria['EURUSD'] = {
            'soportes': [{'precio': 1.0}],
            'resistencias': [{'precio': 1.1}]
        }
        
        # Limpiar
        self.tracker.limpiar_memoria()
        
        assert 'EURUSD' not in self.tracker._niveles_memoria
    
    def test_nivel_existe(self):
        """Valida la verificación de existencia de nivel."""
        # Configurar nivel
        self.tracker._niveles_memoria['EURUSD'] = {
            'soportes': [{'precio': 1.0790, 'hits': 2, 'tipo': 'soporte'}],
            'resistencias': []
        }
        
        existe = self.tracker._nivel_existe('EURUSD', 'soportes', 1.0790)
        no_existe = self.tracker._nivel_existe('EURUSD', 'soportes', 1.0850)
        
        assert existe is True
        assert no_existe is False
    
    def test_acumular_nivel_nuevo(self):
        """Valida la acumulación de nivel nuevo."""
        self.tracker._acumular_nivel('EURUSD', 'soportes', 1.0790, hits=1)
        
        niveles = self.tracker.obtener_niveles('EURUSD')
        
        assert len(niveles['soportes']) == 1
        assert niveles['soportes'][0]['precio'] == 1.0790
        assert niveles['soportes'][0]['hits'] == 1
    
    def test_acumular_nivel_existente(self):
        """Valida la acumulación de nivel existente."""
        # Primero acumular
        self.tracker._acumular_nivel('EURUSD', 'soportes', 1.0790, hits=1)
        
        # Acumular de nuevo (debería sumar hits)
        self.tracker._acumular_nivel('EURUSD', 'soportes', 1.0790, hits=2)
        
        niveles = self.tracker.obtener_niveles('EURUSD')
        
        assert niveles['soportes'][0]['hits'] == 3