#!/usr/bin/env python3
"""
trading/sniper/sniper_scoring.py (V9.0)
Cálculo de scores para el sniper.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger('BotTrading.SniperScoring')


class CalculadorScoreSniper:
    """
    Calculador de scores para el sniper.
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self, config: Optional[Any] = None, modo_backtest: bool = False):
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.SniperScoring')
    
    def calcular_score_m5(self,
                          modo: str,
                          analisis_rapido: Any,
                          analisis_medio: Any,
                          analisis_pesado: Any,
                          df_m5: Any,
                          direccion: str) -> float:
        """
        Calcula el score M5.
        
        Returns:
            Score M5 (0-100)
        """
        score = self._score_base_por_modo(modo)
        
        # Patrón
        if analisis_pesado:
            if analisis_pesado.calidad_patron > 40:
                score += 15
            elif analisis_pesado.calidad_patron > 20:
                score += 8
        
        # Volumen
        if analisis_rapido:
            if analisis_rapido.volumen_relativo > 1.5:
                score += 10
            elif analisis_rapido.volumen_relativo > 1.0:
                score += 6
            elif analisis_rapido.volumen_relativo > 0.5:
                score += 3
        
        # Confirmación de retest
        if self._detectar_confirmacion_retest(df_m5, direccion):
            score += 10
        
        # Nivel clave
        if analisis_medio and analisis_medio.en_nivel_clave:
            score += 10
        
        # ADX
        if analisis_medio and analisis_medio.adx > 35:
            score += 8
        elif analisis_medio and analisis_medio.adx > 25:
            score += 5
        
        # RSI
        if analisis_rapido:
            if direccion == 'COMPRA' and analisis_rapido.rsi < 30:
                score += 5
            elif direccion == 'VENTA' and analisis_rapido.rsi > 70:
                score += 5
        
        return min(100.0, max(0.0, score))
    
    def _score_base_por_modo(self, modo: str) -> float:
        """Obtiene score base por modo."""
        base = {
            'SNIPER_ELITE': 50,
            'NIVEL_FUERTE': 45,
            'RETEST': 40,
            'PATRON': 40,
            'BREAKOUT': 35,
            'PULLBACK': 35,
            'RUPTURA_FALSA': 30,
            'VELA_BORDE': 30,
            'RETEST_FALLBACK': 25,
        }.get(modo, 30)
        
        if self.modo_backtest:
            base = max(20, base - 10)
        
        return float(base)
    
    def _detectar_confirmacion_retest(self, df_m5: Any, direccion: str) -> bool:
        """Detecta confirmación de retest."""
        if df_m5 is None or len(df_m5) < 2:
            return False
        
        vela = df_m5.iloc[-1]
        rango = vela['High'] - vela['Low']
        
        if rango == 0:
            return False
        
        if direccion == 'COMPRA':
            sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
            return sombra_inf / rango > 0.3
        else:
            sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
            return sombra_sup / rango > 0.3