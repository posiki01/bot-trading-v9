#!/usr/bin/env python3
"""
analysis/ml/ml_prediccion.py (V9.0)
Predicción de puntuación con ML.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger('BotTrading.ML.Prediccion')


class PredictorML:
    """
    Predictor de puntuación con ML.
    V9.0 - COMPLETO.
    """
    
    def __init__(self, score_engine: Optional[Any] = None,
                 pesos: Optional[Dict] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el predictor.
        
        Args:
            score_engine: ScoreEngine
            pesos: Pesos optimizados
            modo_backtest: Modo backtest
        """
        self.score_engine = score_engine
        self.pesos = pesos or {}
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.ML.Prediccion')
    
    def predecir(self, analisis_raw: Dict, sentimiento_noticias: float,
                 reporte_cot: float, sniper_confirmado: bool = False,
                 regimen: Optional[str] = None,
                 fase: Optional[int] = None) -> float:
        """
        Predice la puntuación.
        
        Args:
            analisis_raw: Análisis crudo
            sentimiento_noticias: Sentimiento de noticias
            reporte_cot: Reporte COT
            sniper_confirmado: Sniper confirmado
            regimen: Régimen
            fase: Fase
        
        Returns:
            Puntuación predicha
        """
        try:
            if self.score_engine is None:
                return 50.0
            
            if regimen is None:
                regimen = analisis_raw.get('regimen', 'UNCERTAIN')
            if fase is None:
                fase = analisis_raw.get('fase', 1)
            
            score = self.score_engine.calcular_puntuacion_maestra(
                analisis_raw=analisis_raw,
                sentimiento_noticias=sentimiento_noticias,
                reporte_cot=reporte_cot,
                sniper_confirmado=sniper_confirmado,
                regimen=regimen,
                fase=fase
            )
            
            return float(score) if score is not None else 50.0
            
        except Exception as e:
            self.logger.error(f"❌ Error en predicción ML: {e}")
            return 50.0