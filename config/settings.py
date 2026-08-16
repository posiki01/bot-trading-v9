#!/usr/bin/env python3
"""
config/settings.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Configuración central del sistema.

CAMBIOS V9.0:
- Separación de umbrales a config/umbrales.py
- Soporte para entornos (dev, prod, backtest)
- Validación automática
- Importación dinámica de entorno
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any, Optional, List

# ============================================================
# CARGA DE .ENV
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / '.env'
load_dotenv(dotenv_path=ENV_PATH)

logger = logging.getLogger('BotTrading.Config')


# ============================================================
# UTILIDADES DE ENV
# ============================================================

def _get_env(key: str, default: Any = None) -> str:
    return os.getenv(key, default)


def _get_env_int(key: str, default: int) -> int:
    val = os.getenv(key, str(default))
    try:
        return int(val)
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    val = os.getenv(key, str(default))
    try:
        return float(val)
    except ValueError:
        return default


def _get_env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ('true', '1', 'yes', 'on', 'y') if val else default


# ============================================================
# SELECCIÓN DE ENTORNO
# ============================================================

ENTORNO_ACTIVO = _get_env('ENTORNO', 'produccion').lower()


# ============================================================
# CLASE PRINCIPAL DE CONFIGURACIÓN
# ============================================================

class Config:
    """
    Configuración central del sistema.
    V9.0 - REFACTORIZADO.
    """
    
    # ============================================================
    # 1. ENTORNO
    # ============================================================
    
    ENTORNO = ENTORNO_ACTIVO
    ES_DESARROLLO = ENTORNO == 'desarrollo'
    ES_PRODUCCION = ENTORNO == 'produccion'
    ES_BACKTEST = ENTORNO == 'backtest'
    
    # ============================================================
    # 2. MT5 / CONEXIÓN
    # ============================================================
    
    MT5_LOGIN = _get_env_int('MT5_LOGIN', 0)
    MT5_PASSWORD = _get_env('MT5_PASSWORD', '')
    MT5_SERVER = _get_env('MT5_SERVER', 'Pepperstone-Demo')
    MT5_DEMO = _get_env_bool('MT5_DEMO', True)
    MAGIC_NUMBER = _get_env_int('MAGIC_NUMBER', 123456)
    
    # ============================================================
    # 3. CAPITAL Y RIESGO (según entorno)
    # ============================================================
    
    if ES_DESARROLLO:
        from config.entornos import EntornoDesarrollo as _Entorno
    elif ES_BACKTEST:
        from config.entornos import EntornoBacktest as _Entorno
    else:
        from config.entornos import EntornoProduccion as _Entorno
    
    CAPITAL_INICIAL = _get_env_float('CAPITAL_INICIAL', _Entorno.CAPITAL_INICIAL)
    APORTE_MENSUAL = _get_env_float('APORTE_MENSUAL', _Entorno.APORTE_MENSUAL)
    MAX_RISK_PER_TRADE_PCT = _get_env_float('MAX_RISK_PER_TRADE_PCT', _Entorno.MAX_RISK_PER_TRADE_PCT)
    MAX_DAILY_DRAWDOWN_PCT = _get_env_float('MAX_DAILY_DRAWDOWN_PCT', _Entorno.MAX_DAILY_DRAWDOWN_PCT)
    MAX_CONSECUTIVE_LOSSES = _get_env_int('MAX_CONSECUTIVE_LOSSES', _Entorno.MAX_CONSECUTIVE_LOSSES)
    MAX_OPERATIONS_PER_DAY = _get_env_int('MAX_OPERATIONS_PER_DAY', _Entorno.MAX_OPERATIONS_PER_DAY)
    MAX_SIMULTANEAS = _get_env_int('MAX_SIMULTANEAS', _Entorno.MAX_SIMULTANEAS)
    MAX_LOTE_ABSOLUTO = _get_env_float('MAX_LOTE_ABSOLUTO', _Entorno.MAX_LOTE_ABSOLUTO)
    MIN_LOTE_ABSOLUTO = _get_env_float('MIN_LOTE_ABSOLUTO', _Entorno.MIN_LOTE_ABSOLUTO)
    
    # ============================================================
    # 4. CIRCUIT BREAKER
    # ============================================================
    
    CIRCUIT_BREAKER_COOLDOWN_HOURS = _get_env_int(
        'CIRCUIT_BREAKER_COOLDOWN_HOURS', 
        _Entorno.CIRCUIT_BREAKER_COOLDOWN_HOURS
    )
    
    # ============================================================
    # 5. TIMEFRAME Y HORARIO
    # ============================================================
    
    TIMEFRAME = _get_env_int('TIMEFRAME', 5)
    HORA_INICIO_OPERACIONES = _get_env_int('HORA_INICIO_OPERACIONES', 2)
    HORA_FIN_OPERACIONES = _get_env_int('HORA_FIN_OPERACIONES', 16)
    CIERRE_VIERNES_HORA = _get_env_int('CIERRE_VIERNES_HORA', 16)
    APERTURA_LUNES_HORA = _get_env_int('APERTURA_LUNES_HORA', 2)
    APERTURA_DOMINGO_HORA = _get_env_int('APERTURA_DOMINGO_HORA', 17)
    
    # ============================================================
    # 6. LOGS
    # ============================================================
    
    LOG_LEVEL = _get_env('LOG_LEVEL', _Entorno.LOG_LEVEL)
    CONSOLE_LOG_LEVEL = _get_env('CONSOLE_LOG_LEVEL', _Entorno.CONSOLE_LOG_LEVEL)
    
    # ============================================================
    # 7. SÍMBOLOS
    # ============================================================
    
    SIMBOLOS_COMPLETOS = [
        'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD',
        'USDCHF', 'EURJPY', 'GBPJPY', 'AUDJPY', 'EURGBP',
        'EURNZD', 'GBPAUD', 'EURCHF', 'GBPCHF',
        'XAUUSD', 'XAGUSD',
        'US30', 'NAS100', 'US500',
        'BTCUSD', 'ETHUSD', 'SOLUSD'
    ]
    
    if ES_DESARROLLO and _Entorno.SIMBOLOS:
        SIMBOLOS_OPERABLES = _Entorno.SIMBOLOS
    else:
        SIMBOLOS_OPERABLES = [
            'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD',
            'USDCHF', 'EURJPY', 'GBPJPY', 'AUDJPY', 'EURGBP',
            'US30', 'NAS100', 'US500', 'XAUUSD'
        ]
    
    # ============================================================
    # 8. NOTIFICACIONES
    # ============================================================
    
    DISCORD_WEBHOOK = _get_env('DISCORD_WEBHOOK', '')
    TELEGRAM_TOKEN = _get_env('TELEGRAM_TOKEN', '')
    TELEGRAM_CHAT_ID = _get_env('TELEGRAM_CHAT_ID', '')
    
    # ============================================================
    # 9. MT5 RENDIMIENTO
    # ============================================================
    
    MT5_MAX_RETRIES = _get_env_int('MT5_MAX_RETRIES', 4)
    MT5_RETRY_BACKOFF_BASE = _get_env_float('MT5_RETRY_BACKOFF_BASE', 0.2)
    MT5_RATE_LIMIT_PER_SEC = _get_env_int('MT5_RATE_LIMIT_PER_SEC', 5)
    MAX_SPREAD_PROMEDIO_PIPS = _get_env_float('MAX_SPREAD_PROMEDIO_PIPS', 3.0)
    MAX_SLIPPAGE_PCT = _get_env_float('MAX_SLIPPAGE_PCT', 0.005)
    
    # ============================================================
    # 10. API KEYS
    # ============================================================
    
    FMP_API_KEY = _get_env('FMP_API_KEY', '')
    FINNHUB_API_KEY = _get_env('FINNHUB_API_KEY', '')
    
    # ============================================================
    # 11. MODO DE OPERACIÓN
    # ============================================================
    
    USE_API_REST = _get_env_bool('USE_API_REST', False)
    API_REST_TOKEN = _get_env('API_REST_TOKEN', '')
    API_REST_URL = _get_env('API_REST_URL', '')
    MODO_CONSERVADOR = _get_env_bool('MODO_CONSERVADOR', False)
    PROBABILIDAD_MINIMA = _get_env_int('PROBABILIDAD_MINIMA', 40)
    
    # ============================================================
    # 12. HORARIOS POR ACTIVO
    # ============================================================
    
    HORARIOS_POR_ACTIVO = {
        'EURUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'GBPUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'USDJPY': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'AUDUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'USDCAD': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'USDCHF': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'EURJPY': {'inicio': 18, 'fin': 2, 'dias': [0, 1, 2, 3, 4]},
        'GBPJPY': {'inicio': 18, 'fin': 2, 'dias': [0, 1, 2, 3, 4]},
        'AUDJPY': {'inicio': 18, 'fin': 2, 'dias': [0, 1, 2, 3, 4]},
        'EURGBP': {'inicio': 2, 'fin': 7, 'dias': [0, 1, 2, 3, 4]},
        'XAUUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'US30': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'NAS100': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'US500': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'BTCUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
        'ETHUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
        'SOLUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
    }
    
    # ============================================================
    # 13. CONFIGURACIÓN DE ACTIVOS
    # ============================================================
    
    CONFIG_ACTIVOS = {
        'EURUSD': {'spread_max': 2.0, 'sesion': 'LDN_NY', 'pts_min': 50},
        'GBPUSD': {'spread_max': 2.0, 'sesion': 'LDN_NY', 'pts_min': 50},
        'USDJPY': {'spread_max': 2.0, 'sesion': 'TOK_NY', 'pts_min': 50},
        'AUDUSD': {'spread_max': 2.0, 'sesion': 'LDN_NY', 'pts_min': 50},
        'USDCAD': {'spread_max': 2.0, 'sesion': 'NY', 'pts_min': 50},
        'USDCHF': {'spread_max': 2.0, 'sesion': 'LDN_NY', 'pts_min': 50},
        'EURJPY': {'spread_max': 3.0, 'sesion': 'TOK_LDN', 'pts_min': 50},
        'GBPJPY': {'spread_max': 3.0, 'sesion': 'TOK_LDN', 'pts_min': 50},
        'AUDJPY': {'spread_max': 3.0, 'sesion': 'TOK_LDN', 'pts_min': 50},
        'EURGBP': {'spread_max': 2.0, 'sesion': 'LDN', 'pts_min': 50},
        'XAUUSD': {'spread_max': 30.0, 'sesion': 'LDN_NY', 'pts_min': 55},
        'US30': {'spread_max': 5.0, 'sesion': 'NY', 'pts_min': 55},
        'NAS100': {'spread_max': 5.0, 'sesion': 'NY', 'pts_min': 55},
        'US500': {'spread_max': 5.0, 'sesion': 'NY', 'pts_min': 55},
        'BTCUSD': {'spread_max': 50.0, 'sesion': '24/7', 'pts_min': 60},
        'ETHUSD': {'spread_max': 5.0, 'sesion': '24/7', 'pts_min': 60},
        'SOLUSD': {'spread_max': 0.5, 'sesion': '24/7', 'pts_min': 60},
    }
    
    # ============================================================
    # 14. SL MÍNIMO POR ACTIVO
    # ============================================================
    
    SL_MIN_PIPS_POR_ACTIVO = {
        'EURUSD': 10, 'GBPUSD': 12, 'USDJPY': 10,
        'AUDUSD': 10, 'USDCAD': 10, 'USDCHF': 10,
        'EURGBP': 10, 'EURJPY': 15, 'GBPJPY': 18,
        'AUDJPY': 15, 'EURNZD': 18, 'GBPAUD': 18,
        'EURCHF': 12, 'GBPCHF': 15,
        'XAUUSD': 60, 'XAGUSD': 80,
        'US30': 40, 'NAS100': 45, 'US500': 35,
        'BTCUSD': 80, 'ETHUSD': 60, 'SOLUSD': 40,
    }
    
    # ============================================================
    # 15. MÉTODOS DE UTILIDAD
    # ============================================================
    
    @classmethod
    def verificar_env(cls) -> bool:
        """Verifica la configuración."""
        from config.validacion import ConfiguracionValidador
        valido, mensajes = ConfiguracionValidador.validar(cls)
        return valido
    
    @classmethod
    def mostrar_resumen(cls) -> str:
        """Muestra un resumen de la configuración."""
        lines = [
            "=" * 60,
            f"🔧 CONFIGURACIÓN V9.0 - {cls.ENTORNO.upper()}",
            "=" * 60,
            f"  MT5 Server: {cls.MT5_SERVER}",
            f"  MT5 Demo: {cls.MT5_DEMO}",
            f"  Capital Inicial: ${cls.CAPITAL_INICIAL:.2f}",
            f"  Riesgo por operación: {cls.MAX_RISK_PER_TRADE_PCT:.1%}",
            f"  Lote máximo: {cls.MAX_LOTE_ABSOLUTO}",
            f"  Drawdown máximo: {cls.MAX_DAILY_DRAWDOWN_PCT:.1%}",
            f"  Símbolos: {len(cls.SIMBOLOS_COMPLETOS)}",
            f"  Operaciones máximas/día: {cls.MAX_OPERATIONS_PER_DAY}",
            f"  Operaciones simultáneas: {cls.MAX_SIMULTANEAS}",
            f"  Notificaciones: {'✅' if cls.DISCORD_WEBHOOK or cls.TELEGRAM_TOKEN else '❌'}",
            "=" * 60,
        ]
        return "\n".join(lines)
    
    @classmethod
    def get_umbrales(cls):
        """Obtiene todos los umbrales."""
        from config.umbrales import Umbrales
        return Umbrales.obtener_todos()
    
    @classmethod
    def get_umbrales_sniper(cls):
        """Obtiene umbrales para el sniper."""
        from config.umbrales import Umbrales
        return Umbrales.obtener_para_sniper()


# ============================================================
# VALIDACIÓN AL IMPORTAR
# ============================================================

if __name__ != "__main__":
    # Solo validar si no estamos ejecutando directamente
    try:
        if not Config.verificar_env():
            logger.warning("⚠️ Configuración con advertencias")
    except Exception as e:
        logger.warning(f"⚠️ Error validando configuración: {e}")


# ============================================================
# EXPORTAR CONFIGURACIÓN
# ============================================================

if __name__ == "__main__":
    Config.verificar_env()
    print(Config.mostrar_resumen())