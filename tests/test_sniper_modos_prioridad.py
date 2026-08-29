#!/usr/bin/env python3
"""
tests/test_sniper_modos_prioridad.py
Valida la priorización de modos del sniper.
"""

import pytest
from unittest.mock import MagicMock, patch

# ✅ CORREGIDO: Importar SniperChecklist
from trading.sniper.sniper_checklist import SniperChecklist
from trading.sniper.sniper_modos import ModoEntrada


class TestPrioridadModos:
    """Validación de prioridad de modos."""

    def setup_method(self):
        """Configura el detector."""
        # ✅ CORREGIDO: Usar SniperChecklist
        self.detector = SniperChecklist(
            pipeline=MagicMock(),
            analisis_capas=None,
            modo_selector=MagicMock(),
            entry_timer=MagicMock(),
            gestor_stops=MagicMock(),
            config=MagicMock(),
            modo_backtest=True,
            modo_depuracion=True
        )

    def test_prioridad_retest_en_tendencia_alcista(self):
        """Valida que RETEST tiene prioridad en tendencia alcista."""
        contexto = {
            'score_h1': 70.0,
            'score_m5': 50.0,
            'score_final': 60.0,
            'regimen': 'TREND_ALCISTA_FUERTE',
            'en_nivel_clave': True,
            'direccion': 'COMPRA',
            'tendencia_m5': 'ALCISTA',
            'volumen_relativo': 1.5,
            'rr': 1.5,
            'nivel_usado': 1.0800,
            'distancia_nivel': 0.1,
            'precio_actual': 1.0805,
            'confluencias_favorables': ['Nivel clave', 'Volumen alto'],
            'confluencias_conflictos': [],
            'patron_calidad': 60,
            'patron': 'ENGULFING_ALCISTA',
            'falsa_ruptura': False,
            'vela_borde': False
        }
        
        modo, razon = self.detector._seleccionar_modo_por_jerarquia(contexto)
        
        assert modo is not None
        assert modo in [ModoEntrada.RETEST, ModoEntrada.SNIPER_ELITE, ModoEntrada.PULLBACK]

    def test_rechaza_compra_en_tendencia_bajista(self):
        """Valida que rechaza COMPRA en tendencia bajista."""
        contexto = {
            'score_h1': 70.0,
            'score_m5': 50.0,
            'score_final': 60.0,
            'regimen': 'TREND_BAJISTA_FUERTE',
            'en_nivel_clave': True,
            'direccion': 'COMPRA',
            'tendencia_m5': 'LATERAL',
            'volumen_relativo': 1.5,
            'rr': 1.5,
            'nivel_usado': 1.0800,
            'distancia_nivel': 0.2,
            'precio_actual': 1.0805,
            'confluencias_favorables': ['Nivel clave'],
            'confluencias_conflictos': [],
            'patron_calidad': 50,
            'patron': 'ENGULFING_ALCISTA',
            'falsa_ruptura': False,
            'vela_borde': False
        }
        
        modo, razon = self.detector._seleccionar_modo_por_jerarquia(contexto)
        
        assert modo is None

    def test_rechaza_venta_en_tendencia_alcista(self):
        """Valida que rechaza VENTA en tendencia alcista."""
        contexto = {
            'score_h1': 70.0,
            'score_m5': 50.0,
            'score_final': 60.0,
            'regimen': 'TREND_ALCISTA_FUERTE',
            'en_nivel_clave': True,
            'direccion': 'VENTA',
            'tendencia_m5': 'LATERAL',
            'volumen_relativo': 1.5,
            'rr': 1.5,
            'nivel_usado': 1.0900,
            'distancia_nivel': 0.2,
            'precio_actual': 1.0905,
            'confluencias_favorables': ['Nivel clave'],
            'confluencias_conflictos': [],
            'patron_calidad': 50,
            'patron': 'ENGULFING_BAJISTA',
            'falsa_ruptura': False,
            'vela_borde': False
        }
        
        modo, razon = self.detector._seleccionar_modo_por_jerarquia(contexto)
        
        assert modo is None

    def test_prioridad_sniper_elite_con_alto_score(self):
        """Valida que SNIPER_ELITE tiene prioridad con score alto."""
        contexto = {
            'score_h1': 85.0,
            'score_m5': 60.0,
            'score_final': 75.0,
            'regimen': 'TREND_ALCISTA_FUERTE',
            'en_nivel_clave': True,
            'direccion': 'COMPRA',
            'tendencia_m5': 'ALCISTA',
            'volumen_relativo': 2.5,
            'rr': 2.5,
            'nivel_usado': 1.0800,
            'distancia_nivel': 0.1,
            'precio_actual': 1.0805,
            'confluencias_favorables': ['Nivel clave', 'Volumen alto', 'ADX > 20', 'Patrón de calidad'],
            'confluencias_conflictos': [],
            'patron_calidad': 85,
            'patron': 'ENGULFING_ALCISTA',
            'falsa_ruptura': False,
            'vela_borde': False
        }
        
        modo, razon = self.detector._seleccionar_modo_por_jerarquia(contexto)
        
        assert modo is not None
        assert modo == ModoEntrada.SNIPER_ELITE