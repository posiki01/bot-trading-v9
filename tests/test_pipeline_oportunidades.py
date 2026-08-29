#!/usr/bin/env python3
"""
tests/test_pipeline_oportunidades.py
Valida el pipeline de oportunidades.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from analysis.pipeline import PipelineOportunidades, FaseOportunidad, EstadoOportunidad


class TestPipelineOportunidades:
    """Validación del pipeline de oportunidades."""

    def setup_method(self):
        """Configura el pipeline."""
        self.pipeline = PipelineOportunidades(
            umbral_fase_1=30,
            umbral_fase_2=40,
            umbral_fase_3=50,
            modo_backtest=True
        )

    def test_crear_oportunidad_fase1(self):
        """Valida creación en FASE_1."""
        estado = self.pipeline.actualizar_fase_1(
            simbolo='EURUSD',
            analisis={},
            score=35.0,
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert estado is not None
        assert estado.simbolo == 'EURUSD'
        assert estado.fase_actual == FaseOportunidad.FASE_1
        assert estado.direccion == 'COMPRA'
        assert estado.score_acumulado == 35.0

    def test_promover_fase2_con_score(self):
        """Valida promoción a FASE_2."""
        estado = self.pipeline.actualizar_fase_1(
            simbolo='EURUSD',
            analisis={},
            score=45.0,  # >= umbral_fase_2 (40)
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert estado is not None
        assert estado.fase_actual == FaseOportunidad.FASE_2

    def test_promover_fase3_con_score(self):
        """Valida promoción a FASE_3."""
        estado = self.pipeline.actualizar_fase_1(
            simbolo='EURUSD',
            analisis={},
            score=55.0,  # >= umbral_fase_3 (50)
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        assert estado is not None
        assert estado.fase_actual == FaseOportunidad.FASE_3

    def test_degradar_por_tiempo(self):
        """Valida degradación por tiempo."""
        # Crear oportunidad
        estado = self.pipeline.actualizar_fase_1(
            simbolo='EURUSD',
            analisis={},
            score=45.0,
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        # Simular que pasó mucho tiempo en FASE_2
        estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc) - timedelta(hours=2)
        
        # Intentar degradar
        self.pipeline._degradar_oportunidad(
            'EURUSD',
            razon="Tiempo excedido en Fase 2 (2.0h)"
        )
        
        # Verificar degradación
        estado_actualizado = self.pipeline.estados.get('EURUSD')
        assert estado_actualizado is not None
        assert estado_actualizado.fase_actual == FaseOportunidad.FASE_1

    def test_marcar_ejecutada(self):
        """Valida marcar como ejecutada."""
        # Crear oportunidad
        self.pipeline.actualizar_fase_1(
            simbolo='EURUSD',
            analisis={},
            score=55.0,
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        # Marcar como ejecutada
        self.pipeline.marcar_ejecutada('EURUSD')
        
        # Verificar
        estado = self.pipeline.estados.get('EURUSD')
        assert estado is not None
        assert estado.fase_actual == FaseOportunidad.EJECUTADA

    def test_marcar_cancelada(self):
        """Valida marcar como cancelada."""
        # Crear oportunidad
        self.pipeline.actualizar_fase_1(
            simbolo='EURUSD',
            analisis={},
            score=35.0,
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        # Marcar como cancelada
        self.pipeline.marcar_cancelada('EURUSD', "Régimen no favorable")
        
        # Verificar
        estado = self.pipeline.estados.get('EURUSD')
        assert estado is not None
        assert estado.fase_actual == FaseOportunidad.CANCELADA

    def test_obtener_activos(self):
        """Valida obtención de oportunidades activas."""
        # Crear varias oportunidades
        self.pipeline.actualizar_fase_1('EURUSD', {}, 35.0, 'COMPRA')
        self.pipeline.actualizar_fase_1('GBPUSD', {}, 45.0, 'COMPRA')
        
        # Marcar una como ejecutada
        self.pipeline.marcar_ejecutada('EURUSD')
        
        # Obtener activas
        activas = self.pipeline.obtener_activos()
        
        assert len(activas) == 1
        assert activas[0].simbolo == 'GBPUSD'

    def test_obtener_por_fase(self):
        """Valida obtención por fase."""
        # Crear oportunidades
        self.pipeline.actualizar_fase_1('EURUSD', {}, 35.0, 'COMPRA')
        self.pipeline.actualizar_fase_1('GBPUSD', {}, 55.0, 'COMPRA')
        
        # Obtener por fase
        fase3 = self.pipeline.obtener_por_fase(FaseOportunidad.FASE_3)
        fase1 = self.pipeline.obtener_por_fase(FaseOportunidad.FASE_1)
        
        assert len(fase3) == 1
        assert fase3[0].simbolo == 'GBPUSD'
        assert len(fase1) == 1
        assert fase1[0].simbolo == 'EURUSD'

    def test_limpiar_antiguos(self):
        """Valida limpieza de oportunidades antiguas."""
        # Crear oportunidad
        estado = self.pipeline.actualizar_fase_1(
            simbolo='EURUSD',
            analisis={},
            score=35.0,
            direccion='COMPRA',
            regimen='TREND_ALCISTA_FUERTE'
        )
        
        # Hacer que sea muy antigua
        estado.timestamp_creacion = datetime.now(timezone.utc) - timedelta(hours=100)
        
        # Limpiar
        eliminados = self.pipeline.limpiar_antiguos(horas=48)
        
        assert eliminados >= 1
        assert 'EURUSD' not in self.pipeline.estados