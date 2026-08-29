#!/usr/bin/env python3
"""
tests/test_tiempo.py (V1.1 - CORREGIDO)
Valida el sistema de horarios de mercado.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from utils.tiempo import HorarioMercado


class TestHorarioMercado:
    """Validación del sistema de horarios."""
    
    def setup_method(self):
        """Configura el horario."""
        self.horario = HorarioMercado(
            zona_usuario='COLOMBIA',
            modo_backtest=True
        )
    
    def test_hora_utc(self):
        """Valida que retorna hora UTC."""
        hora = self.horario.ahora_utc()
        
        assert hora.tzinfo is not None
        assert hora.tzinfo.utcoffset(hora) == timedelta(0)
    
    def test_hora_usuario(self):
        """Valida que retorna hora en zona usuario."""
        hora = self.horario.ahora_usuario()
        
        # Colombia es UTC-5
        assert hora.tzinfo is not None
        assert hora.tzinfo.utcoffset(hora) == timedelta(hours=-5)
    
    def test_mercado_abierto_lunes(self):
        """Valida que el mercado está abierto el lunes."""
        # Lunes 10:00 UTC
        fecha = datetime(2024, 1, 8, 10, 0, tzinfo=timezone.utc)
        
        abierto = self.horario.mercado_abierto(fecha)
        
        assert abierto is True
    
    def test_mercado_cerrado_sabado(self):
        """Valida que el mercado está cerrado el sábado."""
        # Sábado 10:00 UTC
        fecha = datetime(2024, 1, 13, 10, 0, tzinfo=timezone.utc)
        
        abierto = self.horario.mercado_abierto(fecha)
        
        assert abierto is False
    
    def test_mercado_cerrado_domingo_temprano(self):
        """Valida que el mercado está cerrado el domingo temprano."""
        # Domingo 10:00 UTC (antes de las 22:00 UTC)
        fecha = datetime(2024, 1, 14, 10, 0, tzinfo=timezone.utc)
        
        abierto = self.horario.mercado_abierto(fecha)
        
        assert abierto is False
    
    def test_mercado_abierto_domingo_tarde(self):
        """Valida que el mercado está abierto el domingo tarde."""
        # Domingo 23:00 UTC (después de las 22:00 UTC)
        fecha = datetime(2024, 1, 14, 23, 0, tzinfo=timezone.utc)
        
        abierto = self.horario.mercado_abierto(fecha)
        
        assert abierto is True
    
    def test_es_horario_operativo_cripto(self):
        """Valida que cripto siempre es operativo."""
        # Sábado
        fecha_sabado = datetime(2024, 1, 13, 10, 0, tzinfo=timezone.utc)
        
        operativo, razon = self.horario.es_horario_operativo('BTCUSD', fecha_sabado)
        
        assert operativo is True
        assert '24/7' in razon
    
    def test_es_horario_operativo_forex_sabado(self):
        """Valida que forex NO es operativo el sábado."""
        # Sábado
        fecha_sabado = datetime(2024, 1, 13, 10, 0, tzinfo=timezone.utc)
        
        operativo, razon = self.horario.es_horario_operativo('EURUSD', fecha_sabado)
        
        assert operativo is False
        assert 'Sábado' in razon
    
    def test_es_horario_operativo_forex_domingo_tarde(self):
        """Valida que forex es operativo el domingo tarde."""
        # Domingo 23:00 UTC = 18:00 COT
        fecha_domingo = datetime(2024, 1, 14, 23, 0, tzinfo=timezone.utc)
        
        operativo, razon = self.horario.es_horario_operativo('EURUSD', fecha_domingo)
        
        assert operativo is True
    
    def test_obtener_calidad_horario_overlap(self):
        """Valida la calidad del horario en overlap LDN-NY."""
        # ✅ CORRECCIÓN: 12:00 UTC = 07:00 COT (inicio de overlap)
        fecha = datetime(2024, 1, 8, 12, 0, tzinfo=timezone.utc)
        
        calidad = self.horario.obtener_calidad_horario('EURUSD', fecha)
        
        assert calidad['calidad'] == 'EXCELENTE'
        assert calidad['puntaje'] == 100
    
    def test_obtener_calidad_horario_asiatico(self):
        """Valida la calidad del horario asiático."""
        # Lunes 23:00 UTC = 18:00 COT (asiático)
        fecha = datetime(2024, 1, 8, 23, 0, tzinfo=timezone.utc)
        
        calidad = self.horario.obtener_calidad_horario('EURUSD', fecha)
        
        assert calidad['calidad'] in ['REGULAR', 'MALA']
    
    def test_obtener_estado_mercado(self):
        """Valida la obtención de estado de mercado para múltiples símbolos."""
        simbolos = ['EURUSD', 'BTCUSD', 'XAUUSD', 'US30']
        
        estado = self.horario.obtener_estado_mercado(simbolos)
        
        assert 'operables' in estado
        assert 'no_operables' in estado
        assert 'razones' in estado
    
    def test_hora_float(self):
        """Valida la conversión a hora float."""
        fecha = datetime(2024, 1, 8, 14, 30, tzinfo=timezone.utc)
        
        hora = self.horario.hora_float(fecha)
        
        assert 14.0 <= hora <= 15.0
    
    def test_hora_colombia_float(self):
        """Valida la conversión a hora Colombia float."""
        fecha = datetime(2024, 1, 8, 14, 30, tzinfo=timezone.utc)
        
        hora_col = self.horario.hora_colombia_float(fecha)
        
        # Colombia es UTC-5, así que 14:30 UTC = 09:30 COT
        assert 9.0 <= hora_col <= 10.0