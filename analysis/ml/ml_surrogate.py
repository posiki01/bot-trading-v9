#!/usr/bin/env python3
"""
analysis/ml/ml_surrogate.py (V2.0 - DEPRECADO)
Este módulo fue eliminado. El ML ahora aprende de operaciones REALES.

Si algún import lo referencia, se devuelve un stub vacío.
"""
import logging

logger = logging.getLogger('BotTrading.ML.Surrogate')
logger.warning("⚠️ ml_surrogate.py está DEPRECADO. Usa ml_dataset.py")


class SurrogateTrader:
    """Stub de compatibilidad. Ya no se usa."""

    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ SurrogateTrader DEPRECADO - no generar simulaciones")

    def generar_simulaciones(self, *args, **kwargs) -> list:
        return []