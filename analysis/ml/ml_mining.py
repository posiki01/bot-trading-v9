#!/usr/bin/env python3
"""
analysis/ml/ml_mining.py (V9.0)
Hard Negative Mining - Ajuste por rechazos de alta calidad.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger('BotTrading.ML.Mining')


class HardNegativeMiner:
    """
    Hard Negative Mining - Analiza rechazos y ajusta bias.
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self,
                 bias_max_abs: float = 15.0,
                 modo_backtest: bool = False):
        """
        Inicializa el miner.
        
        Args:
            bias_max_abs: Máximo bias
            modo_backtest: Modo backtest
        """
        self.bias_max_abs = bias_max_abs
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.ML.Mining')
    
    def ejecutar(self, oportunidades: List[Dict],
                 pesos_actuales: Dict[str, float]) -> Dict[str, Any]:
        """
        Ejecuta Hard Negative Mining.
        
        Args:
            oportunidades: Oportunidades rechazadas
            pesos_actuales: Pesos actuales
        
        Returns:
            Diccionario con resultados
        """
        if not oportunidades:
            return {'ajustado': False, 'pesos': pesos_actuales, 'ajuste': 0}
        
        # Filtrar rechazos de alta calidad
        rechazos_bajoscore = [
            op for op in oportunidades
            if op.get('motivo_rechazo') == 'BAJO_SCORE' and op.get('puntuacion', 0) > 70
        ]
        
        if not rechazos_bajoscore:
            return {'ajustado': False, 'pesos': pesos_actuales, 'ajuste': 0}
        
        n_rechazos = len(rechazos_bajoscore)
        n_total = len(oportunidades)
        
        if n_rechazos > 5 and (n_rechazos / n_total) > 0.3:
            scores = [op.get('puntuacion', 70) for op in rechazos_bajoscore]
            score_promedio = sum(scores) / len(scores)
            
            ajuste = min(5.0, (score_promedio - 70) * 0.1)
            
            pesos_actualizados = pesos_actuales.copy()
            pesos_actualizados['bias'] = max(
                -self.bias_max_abs,
                min(self.bias_max_abs, pesos_actuales.get('bias', 0) + ajuste)
            )
            
            self.logger.info(f"🧠 Hard Negative: {n_rechazos} rechazos de alta calidad "
                           f"(promedio {score_promedio:.1f}). Bias ajustado +{ajuste:.2f}")
            
            return {
                'ajustado': True,
                'pesos': pesos_actualizados,
                'ajuste': ajuste,
                'n_rechazos': n_rechazos,
                'score_promedio': score_promedio,
            }
        
        return {'ajustado': False, 'pesos': pesos_actuales, 'ajuste': 0}