#!/usr/bin/env python3
"""
tests/test_scoring.py (V1.0)
Valida el motor de puntuación (ScoreEngine).
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from analysis.scoring import ScoreEngine, ScoreResultado


class TestScoreEngine:
    """Validación del motor de puntuación."""
    
    def setup_method(self):
        """Configura el motor."""
        self.engine = ScoreEngine(modo_backtest=True)
    
    def test_calcular_score_h1_valido(self):
        """Valida el cálculo de score H1."""
        resultado = self.engine.calcular_score_h1(
            score_estructura=25.0,
            score_momentum=30.0,
            score_confluencia=28.0,
            score_institucional=20.0,
            simbolo='EURUSD'
        )
        
        assert resultado.score >= 0
        assert resultado.score <= 100
        assert 'estructura' in resultado.detalles
    
    def test_calcular_score_h1_rangos(self):
        """Valida que el score H1 se limita a 0-100."""
        resultado = self.engine.calcular_score_h1(
            score_estructura=100.0,  # Fuera de rango
            score_momentum=100.0,
            score_confluencia=100.0,
            score_institucional=100.0,
            simbolo='EURUSD'
        )
        
        assert resultado.score <= 100
    
    def test_calcular_score_h1_valores_bajos(self):
        """Valida el cálculo con valores bajos."""
        resultado = self.engine.calcular_score_h1(
            score_estructura=0.0,
            score_momentum=0.0,
            score_confluencia=0.0,
            score_institucional=0.0,
            simbolo='EURUSD'
        )
        
        assert resultado.score >= 0
    
    def test_calcular_score_final(self):
        """Valida el cálculo de score final."""
        resultado = self.engine.calcular_score_final(
            score_h1=70.0,
            score_m15=60.0,
            score_m5=50.0,
            regimen='TREND_ALCISTA_FUERTE',
            calificacion_m15='FORTALECE',
            simbolo='EURUSD'
        )
        
        assert resultado.score >= 0
        assert resultado.score <= 100
        assert 'pesos' in resultado.detalles
    
    def test_calcular_score_final_rango(self):
        """Valida el cálculo de score final en rango."""
        resultado = self.engine.calcular_score_final(
            score_h1=50.0,
            score_m15=50.0,
            score_m5=50.0,
            regimen='RANGO_APRETADO',
            calificacion_m15='NEUTRO',
            simbolo='EURUSD'
        )
        
        assert resultado.score >= 0
        assert resultado.score <= 100
    
    def test_calcular_score_final_contraindica(self):
        """Valida que CONTRAINDICA reduce el score."""
        resultado_normal = self.engine.calcular_score_final(
            score_h1=70.0,
            score_m15=60.0,
            score_m5=50.0,
            regimen='TREND_ALCISTA_FUERTE',
            calificacion_m15='NEUTRO',
            simbolo='EURUSD'
        )
        
        resultado_contra = self.engine.calcular_score_final(
            score_h1=70.0,
            score_m15=60.0,
            score_m5=50.0,
            regimen='TREND_ALCISTA_FUERTE',
            calificacion_m15='CONTRAINDICA',
            simbolo='EURUSD'
        )
        
        assert resultado_contra.score < resultado_normal.score
    
    def test_calcular_score_m5(self):
        """Valida el cálculo de score M5."""
        resultado = self.engine.calcular_score_m5(
            modo='SNIPER_ELITE',
            volumen_relativo=2.0,
            en_nivel_clave=True,
            patron_calidad=70.0,
            adx=30.0,
            rsi=35.0,
            direccion='COMPRA',
            simbolo='EURUSD'
        )
        
        assert resultado.score >= 0
        assert resultado.score <= 100
        assert 'modo' in resultado.detalles
    
    def test_calcular_score_m5_retest(self):
        """Valida el cálculo de score M5 para RETEST."""
        resultado = self.engine.calcular_score_m5(
            modo='RETEST',
            volumen_relativo=1.0,
            en_nivel_clave=True,
            patron_calidad=50.0,
            simbolo='EURUSD'
        )
        
        assert resultado.score >= 0
        assert resultado.score <= 100
    
    def test_validar_score(self):
        """Valida la función de validación de scores."""
        assert self.engine._validar_score(150.0, 0, 100) == 100
        assert self.engine._validar_score(-10.0, 0, 100) == 0
        assert self.engine._validar_score(50.0, 0, 100) == 50
        assert self.engine._validar_score(None, 0, 100) == 0
    
    def test_calcular_score_h1_legacy(self):
        """Valida la versión legacy de calcular_score_h1."""
        score = self.engine.calcular_score_h1_legacy(
            score_estructura=25.0,
            score_momentum=30.0,
            score_confluencia=28.0,
            score_institucional=20.0
        )
        
        assert score >= 0
        assert score <= 100
    
    def test_calcular_score_final_legacy(self):
        """Valida la versión legacy de calcular_score_final."""
        score = self.engine.calcular_score_final_legacy(
            score_h1=70.0,
            score_m15=60.0,
            score_m5=50.0,
            regimen='TREND_ALCISTA_FUERTE',
            calificacion_m15='FORTALECE'
        )
        
        assert score >= 0
        assert score <= 100
    
    def test_calcular_score_m5_legacy(self):
        """Valida la versión legacy de calcular_score_m5."""
        score = self.engine.calcular_score_m5_legacy(
            modo='SNIPER_ELITE',
            volumen_relativo=2.0,
            en_nivel_clave=True,
            patron_calidad=70.0
        )
        
        assert score >= 0
        assert score <= 100
    
    def test_get_stats(self):
        """Valida la obtención de estadísticas."""
        stats = self.engine.get_stats()
        
        assert 'total_calculos' in stats
        assert 'cache_hit_rate' in stats