#!/usr/bin/env python3
"""
config/validacion.py (V9.0)
Validación de configuración y umbrales.
"""

import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger('BotTrading.Config')


class ConfiguracionValidador:
    """Valida la configuración del sistema."""
    
    @classmethod
    def validar(cls, config: Any) -> Tuple[bool, List[str]]:
        """
        Valida la configuración completa.
        
        Returns:
            (es_valido, lista_errores)
        """
        errores = []
        advertencias = []
        
        # 1. Capital
        if config.CAPITAL_INICIAL <= 0:
            errores.append(f"CAPITAL_INICIAL inválido: {config.CAPITAL_INICIAL}")
        elif config.CAPITAL_INICIAL < 100:
            advertencias.append(f"CAPITAL_INICIAL bajo: ${config.CAPITAL_INICIAL}")
        
        # 2. Riesgo
        if not 0.001 <= config.MAX_RISK_PER_TRADE_PCT <= 0.05:
            advertencias.append(f"MAX_RISK_PER_TRADE_PCT inusual: {config.MAX_RISK_PER_TRADE_PCT:.2%}")
        
        if not 0.01 <= config.MAX_DAILY_DRAWDOWN_PCT <= 0.20:
            advertencias.append(f"MAX_DAILY_DRAWDOWN_PCT inusual: {config.MAX_DAILY_DRAWDOWN_PCT:.2%}")
        
        # 3. Lotes
        if config.MAX_LOTE_ABSOLUTO <= 0:
            errores.append(f"MAX_LOTE_ABSOLUTO inválido: {config.MAX_LOTE_ABSOLUTO}")
        
        if config.MIN_LOTE_ABSOLUTO <= 0:
            errores.append(f"MIN_LOTE_ABSOLUTO inválido: {config.MIN_LOTE_ABSOLUTO}")
        
        if config.MIN_LOTE_ABSOLUTO > config.MAX_LOTE_ABSOLUTO:
            errores.append(f"MIN_LOTE_ABSOLUTO ({config.MIN_LOTE_ABSOLUTO}) > MAX_LOTE_ABSOLUTO ({config.MAX_LOTE_ABSOLUTO})")
        
        # 4. Operaciones
        if config.MAX_OPERATIONS_PER_DAY <= 0:
            errores.append(f"MAX_OPERATIONS_PER_DAY inválido: {config.MAX_OPERATIONS_PER_DAY}")
        
        if config.MAX_SIMULTANEAS <= 0:
            errores.append(f"MAX_SIMULTANEAS inválido: {config.MAX_SIMULTANEAS}")
        
        # 5. Horarios
        if not 0 <= config.HORA_INICIO_OPERACIONES <= 24:
            errores.append(f"HORA_INICIO_OPERACIONES inválido: {config.HORA_INICIO_OPERACIONES}")
        
        if not 0 <= config.HORA_FIN_OPERACIONES <= 24:
            errores.append(f"HORA_FIN_OPERACIONES inválido: {config.HORA_FIN_OPERACIONES}")
        
        if config.HORA_INICIO_OPERACIONES >= config.HORA_FIN_OPERACIONES:
            errores.append(f"HORA_INICIO ({config.HORA_INICIO_OPERACIONES}) >= HORA_FIN ({config.HORA_FIN_OPERACIONES})")
        
        # 6. MT5
        if not config.MT5_LOGIN:
            errores.append("MT5_LOGIN no configurado")
        
        if not config.MT5_PASSWORD:
            errores.append("MT5_PASSWORD no configurado")
        
        if not config.MT5_SERVER:
            errores.append("MT5_SERVER no configurado")
        
        # 7. Símbolos
        if not config.SIMBOLOS_COMPLETOS:
            errores.append("SIMBOLOS_COMPLETOS vacío")
        
        # 8. Circuit Breaker
        if config.CIRCUIT_BREAKER_COOLDOWN_HOURS < 0:
            errores.append(f"CIRCUIT_BREAKER_COOLDOWN_HOURS inválido: {config.CIRCUIT_BREAKER_COOLDOWN_HOURS}")
        
        # 9. R:R
        if hasattr(config, 'MIN_RR'):
            if config.MIN_RR < 0.5:
                advertencias.append(f"MIN_RR bajo: {config.MIN_RR}")
        
        # 10. SL
        if hasattr(config, 'SL_MIN_PIPS'):
            if config.SL_MIN_PIPS < 5:
                advertencias.append(f"SL_MIN_PIPS bajo: {config.SL_MIN_PIPS}")
        
        # Logs
        for error in errores:
            logger.error(f"   ❌ {error}")
        
        for advertencia in advertencias:
            logger.warning(f"   ⚠️ {advertencia}")
        
        return len(errores) == 0, errores + advertencias