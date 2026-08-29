#!/usr/bin/env python3
"""
tests/test_operabilidad.py (V1.2 - CORREGIDO)
Valida la decisión de operabilidad.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from trading.operabilidad import DecisorOperabilidad, NivelOperabilidad


class TestDecisorOperabilidad:
    """Validación del decisor de operabilidad."""
    
    def setup_method(self):
        """Configura el decisor."""
        # ✅ CORRECCIÓN: Mockear horario para que siempre esté abierto
        with patch('utils.tiempo.HorarioMercado') as mock_horario_cls:
            mock_horario = MagicMock()
            mock_horario.mercado_abierto.return_value = True
            mock_horario.es_horario_operativo.return_value = (True, "Test")
            mock_horario.obtener_calidad_horario.return_value = {
                'calidad': 'EXCELENTE',
                'puntaje': 100,
                'razon': 'Test',
                'es_optimo': True,
                'score_minimo': 0
            }
            mock_horario_cls.return_value = mock_horario
            
            self.decisor = DecisorOperabilidad(
                config=MagicMock(),
                horario=mock_horario,  # ✅ Pasar mock
                modo_backtest=True
            )
    
    def test_decidir_operable_score_alto(self):
        """Valida que decide operable con score alto."""
        decision = self.decisor.decidir(
            simbolo='EURUSD',
            score_final=80.0,
            regimen='TREND_ALCISTA_FUERTE',
            hora_utc=14.0,
            score_h1=80.0,
            score_m15=60.0,
            score_m5=50.0,
            en_nivel_clave=True,
            volumen_relativo=1.5
        )
        
        assert decision.operable is True
        assert decision.nivel in [NivelOperabilidad.ELITE, NivelOperabilidad.OPTIMO]
    
    def test_decidir_no_operable_score_bajo(self):
        """Valida que decide NO operable con score bajo."""
        decision = self.decisor.decidir(
            simbolo='EURUSD',
            score_final=10.0,
            regimen='TREND_ALCISTA_FUERTE',
            hora_utc=14.0,
            score_h1=10.0,
            score_m15=5.0,
            score_m5=0.0
        )
        
        assert decision.operable is False
        assert decision.nivel == NivelOperabilidad.NO_OPERABLE
    
    def test_decidir_operable_con_confianza(self):
        """Valida que decide operable con confianza suficiente."""
        decision = self.decisor.decidir(
            simbolo='EURUSD',
            score_final=60.0,
            regimen='TREND_ALCISTA_FUERTE',
            hora_utc=14.0,
            score_h1=60.0,
            score_m15=50.0,
            score_m5=40.0,
            en_nivel_clave=True,
            volumen_relativo=1.5,
            adx_h1=25.0
        )
        
        assert decision.operable is True
        assert decision.confianza >= 40
    
    def test_obtener_umbrales_para_modo(self):
        """Valida la obtención de umbrales para un modo."""
        umbrales = self.decisor.obtener_umbrales_para_modo('RETEST', 'TREND_ALCISTA_FUERTE')
        
        assert 'elite' in umbrales
        assert 'optimo' in umbrales
        assert 'operable' in umbrales
        assert 'marginal' in umbrales
    
    def test_set_modo_backtest(self):
        """Valida la activación del modo backtest."""
        self.decisor.set_modo_backtest(True)
        
        assert self.decisor.modo_backtest is True