#!/usr/bin/env python3
"""Módulo de análisis - Indicadores, régimen, scoring y pipeline."""

# ============================================================
# RÉGIMEN
# ============================================================

from .regimen import MarketRegimeFilter, RegimenMercado, RegimenData, create_regime_filter

# ============================================================
# SCORING
# ============================================================

from .scoring import ScoreEngine, ScoreResultado, create_score_engine

# ============================================================
# NIVELES
# ============================================================

from .niveles import NivelTracker, create_nivel_tracker

# ============================================================
# CAPAS
# ============================================================

from .capas import AnalisisPorCapas, AnalisisRapido, AnalisisMedio, AnalisisPesado, create_analisis_por_capas

# ============================================================
# FASES
# ============================================================

from .fases import AnalisisPorFase, create_analisis_por_fase

# ============================================================
# PIPELINE
# ============================================================

from .pipeline import PipelineOportunidades, EstadoOportunidad, FaseOportunidad, create_pipeline

# ============================================================
# TÉCNICO
# ============================================================

from .tecnico import AnalisisTecnico

# ============================================================
# PATRON TRACKER
# ============================================================

from .patron_tracker import PatronTracker, create_patron_tracker

# ============================================================
# ML OPTIMIZER - ✅ CORREGIDO
# ============================================================

from .ml import MLOptimizer, create_ml_optimizer

# ============================================================
# EXPORTAR TODO
# ============================================================

__all__ = [
    # Régimen
    'MarketRegimeFilter',
    'RegimenMercado',
    'RegimenData',
    'create_regime_filter',
    
    # Scoring
    'ScoreEngine',
    'ScoreResultado',
    'create_score_engine',
    
    # Niveles
    'NivelTracker',
    'create_nivel_tracker',
    
    # Capas
    'AnalisisPorCapas',
    'AnalisisRapido',
    'AnalisisMedio',
    'AnalisisPesado',
    'create_analisis_por_capas',
    
    # Fases
    'AnalisisPorFase',
    'create_analisis_por_fase',
    
    # Pipeline
    'PipelineOportunidades',
    'EstadoOportunidad',
    'FaseOportunidad',
    'create_pipeline',
    
    # Técnico
    'AnalisisTecnico',
    
    # Patron Tracker
    'PatronTracker',
    'create_patron_tracker',
    
    # ML
    'MLOptimizer',
    'create_ml_optimizer',
]