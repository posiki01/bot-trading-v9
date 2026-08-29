#!/usr/bin/env python3
"""
tests/test_riesgo.py (V1.1 - CORREGIDO)
Valida la gestión de riesgo ampliada.
"""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from datetime import datetime, timezone, timedelta  # ✅ AÑADIR IMPORT

from trading.riesgo import GestionRiesgo


class TestGestionRiesgoAmpliado:
    """Validación ampliada de la gestión de riesgo."""
    
    def setup_method(self):
        """Configura la gestión."""
        self.almacen_mock = MagicMock()
        self.notificador_mock = MagicMock()
        
        self.gestion = GestionRiesgo(
            capital_inicial=1000.0,
            aporte_mensual=50.0,
            almacen=self.almacen_mock,
            notificador=self.notificador_mock,
            modo_backtest=True
        )
    
    def test_calcular_lotes_valido(self):
        """Valida el cálculo de lotes."""
        lotes = self.gestion.calcular_lotes(
            entrada=1.0800,
            stop_loss=1.0780,
            probabilidad=60.0,
            simbolo='EURUSD'
        )
        
        assert lotes > 0
        assert lotes <= 0.10
    
    def test_calcular_lotes_sl_cero(self):
        """Valida que retorna 0 si SL es inválido."""
        lotes = self.gestion.calcular_lotes(
            entrada=1.0800,
            stop_loss=1.0800,  # SL = entrada
            probabilidad=60.0,
            simbolo='EURUSD'
        )
        
        assert lotes == 0.0
    
    def test_obtener_capital_real(self):
        """Valida la obtención de capital real."""
        capital = self.gestion.obtener_capital_real()
        
        assert capital > 0
    
    def test_obtener_margen_libre(self):
        """Valida la obtención de margen libre."""
        margen = self.gestion.obtener_margen_libre()
        
        assert margen > 0
    
    def test_verificar_aporte(self):
        """Valida la verificación de aporte mensual."""
        # ✅ CORRECCIÓN: Configurar aporte_mensual manualmente
        self.gestion.aporte_mensual = Decimal('50.0')
        
        # Simular que pasó 30 días
        self.gestion.proximo_aporte = datetime.now(timezone.utc) - timedelta(days=1)
        
        resultado = self.gestion.verificar_aporte()
        
        assert resultado is True
        assert self.gestion.capital_actual > 1000.0
    
    def test_obtener_max_simultaneas(self):
        """Valida la obtención de máximas simultáneas."""
        max_sim = self.gestion.obtener_max_simultaneas()
        
        assert max_sim >= 1
        assert max_sim <= 5
    
    def test_obtener_etapa_actual(self):
        """Valida la obtención de etapa actual."""
        etapa = self.gestion.obtener_etapa_actual()
        
        assert etapa >= 1
        assert etapa <= 4
    
    def test_reset_diario(self):
        """Valida el reset diario."""
        self.gestion.reset_diario()
        
        assert self.gestion.operaciones_hoy == 0
        assert self.gestion.perdida_diaria == Decimal('0.0')
    
    def test_estadisticas_completas(self):
        """Valida la obtención de estadísticas completas."""
        stats = self.gestion.estadisticas()
        
        assert 'capital_actual' in stats
        assert 'ganancia_neta' in stats
        assert 'win_rate' in stats
        assert 'factor_beneficio' in stats
        assert 'total_operaciones' in stats
    
    def test_estimar_margen_forex(self):
        """Valida la estimación de margen para Forex."""
        margen = self.gestion._estimar_margen('EURUSD', 0.01, 1.0800)
        
        assert margen > 0
    
    def test_estimar_margen_oro(self):
        """Valida la estimación de margen para Oro."""
        margen = self.gestion._estimar_margen('XAUUSD', 0.01, 2000.0)
        
        assert margen > 0
    
    def test_estimar_margen_cripto(self):
        """Valida la estimación de margen para Cripto."""
        margen = self.gestion._estimar_margen('BTCUSD', 0.01, 50000.0)
        
        assert margen > 0