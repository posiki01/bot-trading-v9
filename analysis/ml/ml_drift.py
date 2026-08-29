#!/usr/bin/env python3
"""
analysis/ml/ml_drift.py (V9.0)
Detección de drift y reentrenamiento del modelo ML.
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sklearn.metrics import mean_squared_error, r2_score

logger = logging.getLogger('BotTrading.ML.Drift')


class DriftDetector:
    """
    Detector de drift para el modelo ML.
    V9.0 - COMPLETO.
    """
    
    def __init__(self,
                 metricas_referencia: Dict,
                 pesos_optimizados: Dict,
                 score_engine: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el detector de drift.
        
        Args:
            metricas_referencia: Métricas de referencia
            pesos_optimizados: Pesos actuales
            score_engine: ScoreEngine
            modo_backtest: Modo backtest
        """
        self.metricas_referencia = metricas_referencia
        self.pesos_optimizados = pesos_optimizados
        self.score_engine = score_engine
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.ML.Drift')
        
        # Umbrales
        self.UMBRAL_MSE = 2.0  # MSE actual > baseline * 2 = drift
        self.UMBRAL_R2 = -0.1  # R2 < -0.1 = drift
    
    def actualizar_metricas(self, metricas: Dict):
        """Actualiza métricas de referencia."""
        self.metricas_referencia = metricas
    
    def detectar(self, operaciones: List[Dict],
                 pesos_actuales: Dict) -> bool:
        """
        Detecta drift en el modelo.
        
        Args:
            operaciones: Lista de operaciones recientes
            pesos_actuales: Pesos actuales
        
        Returns:
            True si hay drift
        """
        if not self.metricas_referencia or not operaciones:
            return False
        
        # Obtener operaciones recientes (últimas 15)
        recientes = [op for op in operaciones if op.get('estado') == 'CERRADA']
        recientes = recientes[-15:]
        
        if len(recientes) < 10:
            return False
        
        # Calcular MSE actual
        mse_actual = self._calcular_mse(recientes, pesos_actuales)
        
        if mse_actual is None:
            return False
        
        baseline_mse = self.metricas_referencia.get('mse', 100.0)
        
        # Verificar drift por MSE
        if mse_actual > (baseline_mse * self.UMBRAL_MSE):
            self.logger.info(f"📊 Drift detectado (MSE: {mse_actual:.2f} vs {baseline_mse:.2f})")
            return True
        
        # Verificar drift por R2
        r2_actual = self._calcular_r2(recientes, pesos_actuales)
        if r2_actual is not None and r2_actual < self.UMBRAL_R2:
            self.logger.info(f"📊 Drift detectado (R2: {r2_actual:.4f} < {self.UMBRAL_R2})")
            return True
        
        return False
    
    def _calcular_mse(self, operaciones: List[Dict],
                      pesos: Dict) -> Optional[float]:
        """Calcula MSE en operaciones recientes."""
        if len(operaciones) < 5:
            return None
        
        try:
            preds = []
            reales = []
            
            for op in operaciones:
                # Extraer features
                pts_est = op.get('pts_estructura', 50)
                pts_mom = op.get('pts_momentum', 50)
                pts_conf = op.get('pts_confluencia', 50)
                pts_inst = op.get('pts_institucional', 50)
                
                # Score H1
                score_h1 = (pts_est * 0.35 + pts_mom * 0.30 + 
                           pts_conf * 0.20 + pts_inst * 0.15)
                
                # Score M15 y M5 (simplificado)
                score_m15 = 50
                score_m5 = 50
                regimen = op.get('regimen', 'INCERTO')
                
                # Score final
                score_final = self._calcular_score_final(score_h1, score_m15, score_m5, regimen)
                
                preds.append(score_final)
                reales.append(op.get('ganancia_neta', 0))
            
            if len(preds) < 5:
                return None
            
            # Normalizar reales
            reales_np = np.array(reales)
            if reales_np.max() == reales_np.min():
                return 0.0
            
            reales_norm = (reales_np - reales_np.min()) / (reales_np.max() - reales_np.min() + 0.001) * 100
            
            from sklearn.metrics import mean_squared_error
            return float(mean_squared_error(reales_norm, preds))
            
        except Exception as e:
            self.logger.debug(f"Error calculando MSE: {e}")
            return None
    
    def _calcular_r2(self, operaciones: List[Dict],
                     pesos: Dict) -> Optional[float]:
        """Calcula R2 en operaciones recientes."""
        if len(operaciones) < 5:
            return None
        
        try:
            preds = []
            reales = []
            
            for op in operaciones:
                pts_est = op.get('pts_estructura', 50)
                pts_mom = op.get('pts_momentum', 50)
                pts_conf = op.get('pts_confluencia', 50)
                pts_inst = op.get('pts_institucional', 50)
                
                score_h1 = (pts_est * 0.35 + pts_mom * 0.30 + 
                           pts_conf * 0.20 + pts_inst * 0.15)
                
                score_m15 = 50
                score_m5 = 50
                regimen = op.get('regimen', 'INCERTO')
                
                score_final = self._calcular_score_final(score_h1, score_m15, score_m5, regimen)
                
                preds.append(score_final)
                reales.append(op.get('ganancia_neta', 0))
            
            if len(preds) < 5:
                return None
            
            reales_np = np.array(reales)
            if reales_np.max() == reales_np.min():
                return 0.0
            
            reales_norm = (reales_np - reales_np.min()) / (reales_np.max() - reales_np.min() + 0.001) * 100
            
            from sklearn.metrics import r2_score
            return float(r2_score(reales_norm, preds))
            
        except Exception as e:
            self.logger.debug(f"Error calculando R2: {e}")
            return None
    
    def _calcular_score_final(self, score_h1: float, score_m15: float,
                              score_m5: float, regimen: str) -> float:
        """Calcula score final (simplificado)."""
        pesos = {
            'TREND_ALCISTA_FUERTE': {'h1': 0.55, 'm15': 0.20, 'm5': 0.25},
            'TREND_BAJISTA_FUERTE': {'h1': 0.55, 'm15': 0.20, 'm5': 0.25},
            'TREND_ALCISTA_DEBIL': {'h1': 0.45, 'm15': 0.25, 'm5': 0.30},
            'TREND_BAJISTA_DEBIL': {'h1': 0.45, 'm15': 0.25, 'm5': 0.30},
            'RANGO_AMPLIO': {'h1': 0.30, 'm15': 0.35, 'm5': 0.35},
            'RANGO_APRETADO': {'h1': 0.30, 'm15': 0.35, 'm5': 0.35},
            'CHOP_VOLATIL': {'h1': 0.20, 'm15': 0.30, 'm5': 0.50},
            'BREAKOUT_INMINENTE': {'h1': 0.35, 'm15': 0.25, 'm5': 0.40},
            'INCERTO': {'h1': 0.40, 'm15': 0.30, 'm5': 0.30},
        }
        
        p = pesos.get(regimen, pesos['INCERTO'])
        return (score_h1 * p['h1']) + (score_m15 * p['m15']) + (score_m5 * p['m5'])