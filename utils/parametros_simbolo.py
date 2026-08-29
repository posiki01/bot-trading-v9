#!/usr/bin/env python3
"""
utils/parametros_simbolo.py (V1.0 - DEFINITIVO)
Parámetros unificados por símbolo: digits, pip_val, point.
"""

import logging
from typing import Dict, Optional, Any

logger = logging.getLogger('BotTrading.ParametrosSimbolo')


class ParametrosSimbolo:
    """
    Parámetros unificados para cada símbolo.
    V1.0 - DEFINITIVO.
    """
    
    PARAMETROS_POR_SIMBOLO = {
        # Forex
        'EURUSD': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'GBPUSD': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'USDJPY': {'digits': 3, 'pip_val': 0.01, 'point': 0.001},
        'AUDUSD': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'USDCAD': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'USDCHF': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'EURGBP': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'EURJPY': {'digits': 3, 'pip_val': 0.01, 'point': 0.001},
        'GBPJPY': {'digits': 3, 'pip_val': 0.01, 'point': 0.001},
        'AUDJPY': {'digits': 3, 'pip_val': 0.01, 'point': 0.001},
        
        # Metales
        'XAUUSD': {'digits': 2, 'pip_val': 0.10, 'point': 0.01},  # ✅ CORREGIDO: 0.10
        'XAGUSD': {'digits': 3, 'pip_val': 0.01, 'point': 0.001},
        
        # Índices
        'US30': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},
        'NAS100': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},
        'US500': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},
        
        # Cripto
        'BTCUSD': {'digits': 2, 'pip_val': 1.0, 'point': 0.01},
        'ETHUSD': {'digits': 2, 'pip_val': 1.0, 'point': 0.01},
        'SOLUSD': {'digits': 2, 'pip_val': 1.0, 'point': 0.01},
    }
    
    def __init__(self, mt5: Optional[Any] = None):
        self.mt5 = mt5
        self._cache: Dict[str, Dict[str, float]] = {}
    
    def obtener_parametros(self, simbolo: str) -> Dict[str, float]:
        """Obtiene parámetros para un símbolo."""
        simbolo_upper = simbolo.upper()
        
        if simbolo_upper in self._cache:
            return self._cache[simbolo_upper]
        
        # 1. Intentar desde MT5
        if self.mt5 is not None:
            try:
                info = self.mt5.obtener_info_simbolo(simbolo_upper)
                if info is not None:
                    digits = int(getattr(info, 'digits', 5))
                    point = float(getattr(info, 'point', 0.00001))
                    pip_val = self._calcular_pip_val(simbolo_upper, digits, point)
                    
                    parametros = {'digits': digits, 'pip_val': pip_val, 'point': point}
                    self._cache[simbolo_upper] = parametros
                    return parametros
            except Exception:
                pass
        
        # 2. Fallback: mapa por símbolo
        if simbolo_upper in self.PARAMETROS_POR_SIMBOLO:
            parametros = self.PARAMETROS_POR_SIMBOLO[simbolo_upper]
            self._cache[simbolo_upper] = parametros
            return parametros
        
        # 3. Fallback por tipo
        if 'JPY' in simbolo_upper:
            parametros = {'digits': 3, 'pip_val': 0.01, 'point': 0.001}
        elif 'XAU' in simbolo_upper:
            parametros = {'digits': 2, 'pip_val': 0.10, 'point': 0.01}
        elif 'XAG' in simbolo_upper:
            parametros = {'digits': 3, 'pip_val': 0.01, 'point': 0.001}
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            parametros = {'digits': 1, 'pip_val': 1.0, 'point': 0.1}
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            parametros = {'digits': 2, 'pip_val': 1.0, 'point': 0.01}
        else:
            parametros = {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001}
        
        self._cache[simbolo_upper] = parametros
        return parametros
    
    def _calcular_pip_val(self, simbolo: str, digits: int, point: float) -> float:
        """Calcula pip_val."""
        simbolo_upper = simbolo.upper()
        
        if len(simbolo_upper) == 6:
            if 'JPY' in simbolo_upper:
                return 0.01
            return 0.0001
        
        if 'XAU' in simbolo_upper:
            return 0.10  # ✅ CORREGIDO
        if 'XAG' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if 'BTC' in simbolo_upper:
            return 1.0
        if 'ETH' in simbolo_upper:
            return 1.0
        if 'SOL' in simbolo_upper:
            return 1.0
        return 0.0001
    
    def obtener_digits(self, simbolo: str) -> int:
        return int(self.obtener_parametros(simbolo)['digits'])
    
    def obtener_pip_val(self, simbolo: str) -> float:
        return float(self.obtener_parametros(simbolo)['pip_val'])
    
    def obtener_point(self, simbolo: str) -> float:
        return float(self.obtener_parametros(simbolo)['point'])
    
    def limpiar_cache(self):
        self._cache.clear()


# Instancia global
_parametros = ParametrosSimbolo()


def get_parametros_simbolo(simbolo: str, mt5: Optional[Any] = None) -> Dict[str, float]:
    """Obtiene parámetros para un símbolo."""
    global _parametros
    if mt5 is not None:
        _parametros.mt5 = mt5
        _parametros.limpiar_cache()
    return _parametros.obtener_parametros(simbolo)


def get_digits(simbolo: str, mt5: Optional[Any] = None) -> int:
    """Obtiene digits para un símbolo."""
    return int(get_parametros_simbolo(simbolo, mt5)['digits'])


def get_pip_val(simbolo: str, mt5: Optional[Any] = None) -> float:
    """Obtiene pip_val para un símbolo."""
    return float(get_parametros_simbolo(simbolo, mt5)['pip_val'])


def get_point(simbolo: str, mt5: Optional[Any] = None) -> float:
    """Obtiene point para un símbolo."""
    return float(get_parametros_simbolo(simbolo, mt5)['point'])