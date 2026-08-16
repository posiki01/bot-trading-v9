#!/usr/bin/env python3
"""
trading/sniper/sniper_validacion.py (V9.0)
Validaciones básicas para el sniper.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger('BotTrading.SniperValidacion')


class SniperValidador:
    """
    Validaciones básicas para el sniper.
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self, config: Optional[Any] = None, modo_backtest: bool = False):
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.SniperValidacion')
    
    def validar_datos_basicos(self, df_m5: Any, direccion: str, simbolo: str) -> Tuple[bool, str]:
        """Valida datos básicos."""
        if df_m5 is None or len(df_m5) < 20:
            return False, f"Datos insuficientes ({len(df_m5) if df_m5 is not None else 0} velas)"
        
        if direccion not in ['COMPRA', 'VENTA']:
            return False, f"Dirección inválida: {direccion}"
        
        return True, "OK"
    
    def validar_contexto_h1(self, contexto_h1: Dict, direccion: str, simbolo: str) -> Tuple[bool, str, Dict]:
        """Valida contexto H1."""
        if not contexto_h1:
            return False, "Sin contexto H1", {}
        
        score_h1 = contexto_h1.get('score', 0)
        direccion_h1 = contexto_h1.get('direccion', 'NEUTRAL')
        regimen_h1 = contexto_h1.get('regimen', 'UNCERTAIN')
        
        # Score mínimo
        score_min = 15 if self.modo_backtest else 25
        if score_h1 < score_min:
            return False, f"Score H1 bajo ({score_h1:.1f} < {score_min})", {}
        
        # Dirección
        if direccion_h1 != direccion and direccion_h1 != 'NEUTRAL':
            return False, f"H1 ({direccion_h1}) != Sniper ({direccion})", {}
        
        return True, "OK", {
            'score_h1': score_h1,
            'direccion_h1': direccion_h1,
            'regimen_h1': regimen_h1,
        }
    
    def validar_direccion_por_regimen(self, direccion: str, regimen: str) -> Tuple[bool, str]:
        """Valida dirección por régimen."""
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            if direccion == 'VENTA':
                return False, "VENTA en contra de tendencia alcista"
        elif regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            if direccion == 'COMPRA':
                return False, "COMPRA en contra de tendencia bajista"
        
        return True, "OK"
    
    def validar_capacidad(self, mt5: Any, simbolo: str, gestion_riesgo: Any) -> Tuple[bool, str]:
        """Valida capacidad de operar."""
        # Verificar posición abierta
        posiciones = mt5.obtener_posiciones() if mt5 else []
        if posiciones and any(p.get('simbolo') == simbolo for p in posiciones):
            return False, "Ya hay posición abierta"
        
        # Verificar circuito breaker
        if gestion_riesgo and hasattr(gestion_riesgo, 'circuit_breaker'):
            if gestion_riesgo.circuit_breaker.verificar():
                return False, "Circuit breaker activo"
        
        return True, "OK"