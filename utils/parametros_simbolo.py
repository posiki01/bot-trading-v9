#!/usr/bin/env python3
"""
utils/parametros_simbolo.py (V1.1 - PIP CRIPTO CORREGIDO)
Parámetros unificados por símbolo: digits, pip_val, point.

CAMBIOS V1.1:
- ✅ pip_val cripto proporcional al precio típico
  - BTCUSD: 1.0 ($1 por pip, ~0.0012% del precio)
  - ETHUSD: 0.10 ($0.10 por pip, ~0.0037% del precio)
  - SOLUSD: 0.01 ($0.01 por pip, ~0.01% del precio)
- ✅ Default para altcoins desconocidas: 0.01
- ✅ Sin cambios en forex, metales, índices
"""

import logging
from typing import Dict, Optional, Any

logger = logging.getLogger('BotTrading.ParametrosSimbolo')


class ParametrosSimbolo:
    """
    Parámetros unificados para cada símbolo.
    V1.1 - PIP CRIPTO CORREGIDO.
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
        'EURNZD': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'GBPAUD': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'EURCHF': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'GBPCHF': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},

        # Metales
        'XAUUSD': {'digits': 2, 'pip_val': 0.10, 'point': 0.01},
        'XAGUSD': {'digits': 3, 'pip_val': 0.01, 'point': 0.001},

        # Índices
        'US30': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},
        'NAS100': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},
        'US500': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},

        # ✅ Cripto (V1.1: pip_val proporcional al precio típico)
        'BTCUSD': {'digits': 2, 'pip_val': 1.0, 'point': 0.01},   # $1/pip
        'ETHUSD': {'digits': 2, 'pip_val': 0.10, 'point': 0.01},  # $0.10/pip
        'SOLUSD': {'digits': 2, 'pip_val': 0.01, 'point': 0.01},  # $0.01/pip
    }

    def __init__(self, mt5: Optional[Any] = None):
        self.mt5 = mt5
        self._cache: Dict[str, Dict[str, float]] = {}

    def obtener_parametros(self, simbolo: str) -> Dict[str, float]:
        """Obtiene parámetros para un símbolo."""
        simbolo_upper = simbolo.upper()

        if simbolo_upper in self._cache:
            return self._cache[simbolo_upper]

        # 1. Intentar desde MT5 (solo point/digits; pip_val siempre por convención)
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
        parametros = self._inferir_por_tipo(simbolo_upper)
        self._cache[simbolo_upper] = parametros
        return parametros

    def _inferir_por_tipo(self, simbolo: str) -> Dict[str, float]:
        """Infiere parámetros por tipo de activo."""
        if 'JPY' in simbolo:
            return {'digits': 3, 'pip_val': 0.01, 'point': 0.001}
        if 'XAU' in simbolo:
            return {'digits': 2, 'pip_val': 0.10, 'point': 0.01}
        if 'XAG' in simbolo:
            return {'digits': 3, 'pip_val': 0.01, 'point': 0.001}
        if any(x in simbolo for x in ['US30', 'NAS100', 'US500']):
            return {'digits': 1, 'pip_val': 1.0, 'point': 0.1}

        # ✅ Cripto: proporcional al precio típico
        if 'BTC' in simbolo:
            return {'digits': 2, 'pip_val': 1.0, 'point': 0.01}
        if 'ETH' in simbolo:
            return {'digits': 2, 'pip_val': 0.10, 'point': 0.01}
        if 'SOL' in simbolo:
            return {'digits': 2, 'pip_val': 0.01, 'point': 0.01}
        # Otras cripto (XRP, ADA, DOT, etc.)
        if any(c in simbolo for c in ['XRP', 'ADA', 'DOT', 'LINK', 'UNI', 'MATIC']):
            return {'digits': 2, 'pip_val': 0.01, 'point': 0.01}

        # Default forex
        return {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001}

    def _calcular_pip_val(self, simbolo: str, digits: int, point: float) -> float:
        """
        Calcula pip_val según tipo de activo.
        ✅ V1.1: cripto proporcional al precio típico.
        """
        simbolo_upper = simbolo.upper()

        # Forex (5/3 dígitos)
        if len(simbolo_upper) == 6:
            if 'JPY' in simbolo_upper:
                return 0.01
            return 0.0001

        # Metales
        if 'XAU' in simbolo_upper:
            return 0.10
        if 'XAG' in simbolo_upper:
            return 0.01

        # Índices
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0

        # ✅ Cripto (V1.1)
        if 'BTC' in simbolo_upper:
            return 1.0
        if 'ETH' in simbolo_upper:
            return 0.10
        if 'SOL' in simbolo_upper:
            return 0.01
        # Altcoins
        if any(c in simbolo_upper for c in ['XRP', 'ADA', 'DOT', 'LINK', 'UNI', 'MATIC']):
            return 0.01

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
    global _parametros
    if mt5 is not None:
        _parametros.mt5 = mt5
    return _parametros.obtener_parametros(simbolo)


def get_digits(simbolo: str, mt5: Optional[Any] = None) -> int:
    return int(get_parametros_simbolo(simbolo, mt5)['digits'])


def get_pip_val(simbolo: str, mt5: Optional[Any] = None) -> float:
    return float(get_parametros_simbolo(simbolo, mt5)['pip_val'])


def get_point(simbolo: str, mt5: Optional[Any] = None) -> float:
    return float(get_parametros_simbolo(simbolo, mt5)['point'])


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if str(Path(__file__).parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent.parent))

    print("🧪 Probando parametros_simbolo V1.1...")

    test_simbolos = [
        'EURUSD', 'USDJPY', 'XAUUSD', 'XAGUSD',
        'US30', 'NAS100',
        'BTCUSD', 'ETHUSD', 'SOLUSD',
    ]

    print(f"\n{'Símbolo':<10} {'digits':>7} {'pip_val':>10} {'point':>10}")
    print("-" * 45)
    for s in test_simbolos:
        p = get_parametros_simbolo(s)
        print(f"{s:<10} {p['digits']:>7} {p['pip_val']:>10.5f} {p['point']:>10.5f}")

    # Verificaciones
    assert get_pip_val('BTCUSD') == 1.0
    assert get_pip_val('ETHUSD') == 0.10
    assert get_pip_val('SOLUSD') == 0.01
    assert get_pip_val('EURUSD') == 0.0001
    assert get_pip_val('USDJPY') == 0.01
    assert get_pip_val('XAUUSD') == 0.10

    print("\n✅ Todas las verificaciones pasan")