#!/usr/bin/env python3
"""
utils/helpers.py (V9.1 - REFACTORIZADO)
Utilidades generales para el bot.
"""

import json
import os
import re
import decimal
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union, List, Tuple
from pathlib import Path

try:
    from utils.logger_persistente import LoggerPersistente
    _logger = LoggerPersistente()
    logger = _logger.get_logger()
except ImportError:
    import logging
    logger = logging.getLogger('BotTrading.Helpers')


# ============================================================
# CONSTANTES
# ============================================================

TIPOS_ACTIVOS = {
    'FOREX': ['EUR', 'GBP', 'USD', 'CHF', 'JPY', 'AUD', 'CAD', 'NZD'],
    'CRYPTO': ['BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOT', 'LINK', 'UNI', 'MATIC'],
    'INDICES': ['US30', 'NAS100', 'US500', 'GER40', 'UK100', 'SP500', 'SPX', 'DAX'],
    'METALES': ['XAU', 'XAG', 'XPT', 'XPD'],
}

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE
)

_CONTROL_CHARS_PATTERN = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')
_SIMBOLO_PATTERN = re.compile(r'^[A-Z0-9]{3,7}$')


# ============================================================
# LIMPIEZA DE TEXTO
# ============================================================

def limpiar_emojis(texto: str) -> str:
    if not isinstance(texto, str):
        return str(texto)
    texto_limpio = _EMOJI_PATTERN.sub('', texto)
    texto_limpio = _CONTROL_CHARS_PATTERN.sub('', texto_limpio)
    return texto_limpio


def limpiar_texto(texto: str, max_len: Optional[int] = None) -> str:
    if not isinstance(texto, str):
        return str(texto)
    texto = limpiar_emojis(texto)
    texto = re.sub(r'\s+', ' ', texto)
    texto = texto.strip()
    if max_len and len(texto) > max_len:
        texto = texto[:max_len - 3] + '...'
    return texto


def normalizar_texto(texto: str) -> str:
    if not isinstance(texto, str):
        return ''
    return texto.upper().strip().replace(' ', '')


# ============================================================
# JSON (CON SOPORTE PARA SQLITE)
# ============================================================

def _json_serializer(obj: Any) -> Any:
    if isinstance(obj, bool):
        return bool(obj)
    if obj is None:
        return None
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, Path):
        return str(obj)
    try:
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient='records')
        if isinstance(obj, pd.Series):
            return obj.to_list()
    except ImportError:
        pass
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    if hasattr(obj, '__dataclass_fields__'):
        return obj.__dict__
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    if hasattr(obj, 'value'):
        return obj.value if hasattr(obj.value, 'value') else str(obj.value)
    try:
        return str(obj)
    except Exception:
        return None


def serializar_para_json(datos: Any) -> Any:
    if datos is None:
        return None
    if isinstance(datos, (str, int, float, bool)):
        return datos
    if isinstance(datos, (list, tuple)):
        return [serializar_para_json(item) for item in datos]
    if isinstance(datos, dict):
        return {key: serializar_para_json(value) for key, value in datos.items()}
    if isinstance(datos, datetime):
        return datos.isoformat()
    if isinstance(datos, decimal.Decimal):
        return float(datos)
    if isinstance(datos, Path):
        return str(datos)
    try:
        return _json_serializer(datos)
    except Exception:
        return str(datos)


def cargar_json(archivo: Union[str, Path], usar_sqlite: bool = True) -> Dict[str, Any]:
    ruta = Path(archivo)
    if usar_sqlite:
        try:
            from data.almacenamiento_sqlite import AlmacenamientoSQLite
            almacen = AlmacenamientoSQLite()
            config = almacen.obtener_configuracion()
            key = ruta.stem
            if key in config:
                return config[key]
        except Exception as e:
            logger.debug(f"Error cargando desde SQLite: {e}")
    if not ruta.exists():
        return {}
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(f"⚠️ Archivo JSON corrupto: {archivo} - {e}")
        return {}
    except Exception as e:
        logger.error(f"Error cargando {archivo}: {e}")
        return {}


def guardar_json(archivo: Union[str, Path], datos: Any, indent: int = 2,
                 usar_sqlite: bool = True) -> bool:
    ruta = Path(archivo)
    if usar_sqlite:
        try:
            from data.almacenamiento_sqlite import AlmacenamientoSQLite
            almacen = AlmacenamientoSQLite()
            config = almacen.obtener_configuracion()
            key = ruta.stem
            config[key] = datos
            almacen.guardar_configuracion(config)
            return True
        except Exception as e:
            logger.debug(f"Error guardando en SQLite: {e}")
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(
                datos, 
                f, 
                indent=indent, 
                ensure_ascii=False, 
                default=_json_serializer
            )
        return True
    except Exception as e:
        logger.error(f"Error guardando {archivo}: {e}")
        return False


# ============================================================
# FORMATO DE DATOS
# ============================================================

def formatear_dinero(valor: Union[int, float, decimal.Decimal]) -> str:
    try:
        valor_float = float(valor)
        if valor_float >= 0:
            return f"+${valor_float:,.2f}"
        return f"-${abs(valor_float):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def formatear_porcentaje(valor: Union[int, float, decimal.Decimal], decimales: int = 1) -> str:
    try:
        valor_float = float(valor)
        if abs(valor_float) > 1:
            pct = valor_float
        else:
            pct = valor_float * 100
        if pct >= 0:
            return f"+{pct:.{decimales}f}%"
        return f"-{abs(pct):.{decimales}f}%"
    except (ValueError, TypeError):
        return "0.0%"


def formatear_fecha(fecha: Optional[datetime] = None,
                    formato: str = '%Y-%m-%d %H:%M:%S') -> str:
    if fecha is None:
        fecha = datetime.now(timezone.utc)
    return fecha.strftime(formato)


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def fecha_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def truncar_texto(texto: str, max_len: int = 100, sufijo: str = "...") -> str:
    if not isinstance(texto, str):
        return str(texto)
    if len(texto) <= max_len:
        return texto
    return texto[:max_len - len(sufijo)] + sufijo


def normalizar_simbolo(simbolo: str) -> str:
    if not simbolo:
        return ''
    simbolo = simbolo.upper().strip()
    if len(simbolo) == 6:
        return f"{simbolo[:3]}/{simbolo[3:]}"
    elif len(simbolo) == 7:
        return f"{simbolo[:4]}/{simbolo[4:]}"
    elif len(simbolo) > 6:
        for i in range(3, len(simbolo) - 2):
            if simbolo[i] in TIPOS_ACTIVOS['FOREX']:
                return f"{simbolo[:i]}/{simbolo[i:]}"
    return simbolo


# ============================================================
# VALIDACIONES DE SÍMBOLOS
# ============================================================

def es_simbolo_valido(simbolo: str) -> bool:
    if not simbolo or not isinstance(simbolo, str):
        return False
    simbolo_limpio = simbolo.upper().strip()
    return bool(_SIMBOLO_PATTERN.match(simbolo_limpio))


def es_forex(simbolo: str) -> bool:
    if not es_simbolo_valido(simbolo):
        return False
    simbolo = simbolo.upper()
    if len(simbolo) != 6:
        return False
    base = simbolo[:3]
    quote = simbolo[3:]
    return base in TIPOS_ACTIVOS['FOREX'] and quote in TIPOS_ACTIVOS['FOREX']


def es_crypto(simbolo: str) -> bool:
    if not es_simbolo_valido(simbolo):
        return False
    simbolo = simbolo.upper()
    for crypto in TIPOS_ACTIVOS['CRYPTO']:
        if crypto in simbolo:
            return True
    return False


def es_indice(simbolo: str) -> bool:
    if not es_simbolo_valido(simbolo):
        return False
    simbolo = simbolo.upper()
    for indice in TIPOS_ACTIVOS['INDICES']:
        if indice in simbolo:
            return True
    return False


def es_metal(simbolo: str) -> bool:
    if not es_simbolo_valido(simbolo):
        return False
    simbolo = simbolo.upper()
    for metal in TIPOS_ACTIVOS['METALES']:
        if metal in simbolo:
            return True
    return False


def get_tipo_activo(simbolo: str) -> str:
    if es_crypto(simbolo):
        return 'CRYPTO'  # ✅ CORREGIDO: Coincide con umbrales.py
    elif es_indice(simbolo):
        return 'INDICES_US'
    elif es_metal(simbolo):
        return 'METALES'
    elif es_forex(simbolo):
        return 'FOREX'
    else:
        return 'DESCONOCIDO'


def get_base_quote(simbolo: str) -> Tuple[str, str]:
    if not simbolo:
        return '', ''
    simbolo = simbolo.upper().strip()
    if len(simbolo) == 6:
        return simbolo[:3], simbolo[3:]
    elif len(simbolo) == 7:
        return simbolo[:4], simbolo[4:]
    else:
        for i in range(3, len(simbolo) - 2):
            if simbolo[i:] in TIPOS_ACTIVOS['FOREX'] or simbolo[i:] in TIPOS_ACTIVOS['CRYPTO']:
                return simbolo[:i], simbolo[i:]
        return simbolo, 'USD'


# ============================================================
# PIP VALUE Y DIGITS POR SÍMBOLO (NUEVO)
# ============================================================

def get_pip_val(simbolo: str, precio: float = 0.0) -> float:
    """
    Obtiene el valor de un pip para el símbolo.
    V9.1 - CORREGIDO: XAUUSD usa 0.01, XAGUSD usa 0.1
    """
    simbolo_upper = simbolo.upper()
    if 'JPY' in simbolo_upper:
        return 0.01
    if 'XAU' in simbolo_upper:
        return 0.01  # ✅ CORREGIDO: Oro usa point = 0.01
    if 'XAG' in simbolo_upper:
        return 0.1   # ✅ CORREGIDO: Plata usa point = 0.001, pip = 0.1
    if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
        return 1.0
    if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
        return 1.0
    return 0.0001


def get_digits(simbolo: str) -> int:
    """
    Obtiene el número de dígitos del símbolo.
    V9.1 - CORREGIDO: XAGUSD usa 3, índices usan 1
    """
    simbolo_upper = simbolo.upper()
    if 'JPY' in simbolo_upper:
        return 3
    if 'XAU' in simbolo_upper:
        return 2
    if 'XAG' in simbolo_upper:
        return 3  # ✅ CORREGIDO: Plata usa 3 dígitos
    if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
        return 1  # ✅ CORREGIDO: Índices usan 1 dígito
    if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
        return 2
    return 5


# ============================================================
# CONVERSIONES SEGURAS
# ============================================================

def safe_float(valor: Any, default: float = 0.0) -> float:
    if valor is None:
        return default
    try:
        return float(valor)
    except (ValueError, TypeError):
        return default


def safe_int(valor: Any, default: int = 0) -> int:
    if valor is None:
        return default
    try:
        return int(valor)
    except (ValueError, TypeError):
        return default


def safe_decimal(valor: Any, default: decimal.Decimal = decimal.Decimal('0.0')) -> decimal.Decimal:
    if valor is None:
        return default
    try:
        return decimal.Decimal(str(valor))
    except (ValueError, TypeError, decimal.InvalidOperation):
        return default


def safe_str(valor: Any, default: str = '') -> str:
    if valor is None:
        return default
    try:
        return str(valor)
    except Exception:
        return default


def safe_bool(valor: Any, default: bool = False) -> bool:
    if valor is None:
        return default
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    if isinstance(valor, str):
        return valor.lower() in ('true', '1', 'yes', 'on', 'y', 'si')
    return default


# ============================================================
# NORMALIZACIÓN DE DATOS
# ============================================================

def normalizar_precio(precio: float, digits: int = 5) -> float:
    if not precio or precio <= 0:
        return 0.0
    return round(precio, digits)


def normalizar_lotes(lotes: float, paso: float = 0.01) -> float:
    if not lotes or lotes <= 0:
        return 0.0
    if paso <= 0:
        return lotes
    return round(lotes / paso) * paso


def normalizar_porcentaje(valor: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    if valor is None:
        return min_val
    return max(min_val, min(max_val, float(valor)))


# ============================================================
# DIAGNÓSTICO Y VALIDACIÓN
# ============================================================

def es_numero(valor: Any) -> bool:
    if valor is None:
        return False
    return isinstance(valor, (int, float, decimal.Decimal))


def es_entero(valor: Any) -> bool:
    if not es_numero(valor):
        return False
    try:
        return float(valor).is_integer()
    except Exception:
        return False


def comparar_simbolos(s1: str, s2: str) -> bool:
    if not s1 or not s2:
        return False
    return normalizar_texto(s1) == normalizar_texto(s2)


# ============================================================
# MÉTODOS DE COMPATIBILIDAD (LEGACY)
# ============================================================

def log_info(msg: str):
    logger.info(msg)


def log_exito(msg: str):
    logger.info(f"✅ {msg}")


def log_error(msg: str):
    logger.error(msg)


def log_alerta(msg: str):
    logger.warning(msg)


def log_debug(msg: str):
    logger.debug(msg)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando módulo helpers...")
    
    print("\n1. Limpieza de texto:")
    texto = "Hola 👋 Mundo 🌍!  Test  "
    print(f"  Original: {texto}")
    print(f"  Limpio: {limpiar_texto(texto)}")
    print(f"  Normalizado: {normalizar_texto(texto)}")
    
    print("\n2. Formateo:")
    print(f"  Dinero: {formatear_dinero(1234.56)}")
    print(f"  Dinero negativo: {formatear_dinero(-1234.56)}")
    print(f"  Porcentaje: {formatear_porcentaje(0.75)}")
    print(f"  Fecha: {formatear_fecha()}")
    
    print("\n3. Símbolos:")
    simbolos = ['EURUSD', 'BTCUSD', 'US30', 'XAUUSD', 'EURGBP']
    for s in simbolos:
        print(f"  {s}:")
        print(f"    Forex: {es_forex(s)}")
        print(f"    Crypto: {es_crypto(s)}")
        print(f"    Índice: {es_indice(s)}")
        print(f"    Metal: {es_metal(s)}")
        print(f"    Tipo: {get_tipo_activo(s)}")
        print(f"    Normalizado: {normalizar_simbolo(s)}")
        print(f"    Base/Quote: {get_base_quote(s)}")
    
    print("\n4. Conversiones seguras:")
    print(f"  safe_float('123.45'): {safe_float('123.45')}")
    print(f"  safe_float(None): {safe_float(None)}")
    print(f"  safe_int('123'): {safe_int('123')}")
    print(f"  safe_bool('true'): {safe_bool('true')}")
    
    print("\n5. Normalizaciones:")
    print(f"  normalizar_precio(1.234567, 5): {normalizar_precio(1.234567, 5)}")
    print(f"  normalizar_lotes(0.123, 0.01): {normalizar_lotes(0.123, 0.01)}")
    print(f"  normalizar_porcentaje(150): {normalizar_porcentaje(150)}")
    
    print("\n✅ Prueba completada")


def get_mt5_path() -> Optional[str]:
    try:
        from config.settings import Config
        if hasattr(Config, 'MT5_PATH'):
            return Config.MT5_PATH
    except:
        pass
    import os
    mt5_path = os.getenv('MT5_PATH')
    if mt5_path:
        return mt5_path
    import platform
    if platform.system() == 'Windows':
        paths = [
            "C:/Program Files/Pepperstone MetaTrader 5/terminal64.exe",
            "C:/Program Files/MetaTrader 5/terminal64.exe",
            "C:/Program Files (x86)/MetaTrader 5/terminal64.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                return p
    return None