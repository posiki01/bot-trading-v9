#!/usr/bin/env python3
"""
utils/construir_timeframes.py (V1.1 - CORREGIDO)
Construye timeframes mayores a partir de M5 cuando el broker no los tiene.

CORRECCIONES V1.1:
- ✅ Valida FRESCURA, no solo cantidad. Si H1 del broker es viejo (>3x TF), construye desde M5
- ✅ Helper _esta_fresco() y _edad_minutos()
- ✅ Prioriza datos frescos sobre datos completos pero viejos
- ✅ Fallback a SQLite al final
"""

import logging
import pandas as pd
from typing import Dict, Optional, List, Any
from datetime import datetime, timezone, timedelta

logger = logging.getLogger('BotTrading.ConstruirTimeframes')


# ============================================================
# MAPEO DE TIMEFRAMES
# ============================================================

REGLAS_AGRUPACION = {
    5: '5min',
    15: '15min',
    30: '30min',
    60: '1h',
    240: '4h',
    1440: '1D',
    10080: '1W',
    43200: '1M',
}

TIMEFRAMES_CONSTRUIBLES = [15, 30, 60, 240, 1440]

VELAS_M5_NECESARIAS = {
    15: 3,
    30: 6,
    60: 12,
    240: 48,
    1440: 288,
}


# ============================================================
# HELPERS DE FRESCURA
# ============================================================

def _edad_minutos(df: pd.DataFrame) -> float:
    """Edad de la última vela en minutos."""
    if df is None or len(df) == 0:
        return float('inf')
    try:
        ultima = df.index[-1]
        if ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        ahora = datetime.now(timezone.utc)
        return (ahora - ultima).total_seconds() / 60
    except Exception:
        return float('inf')


def _esta_fresco(df: pd.DataFrame, timeframe_min: int, tolerancia_mult: float = 3.0) -> bool:
    """
    Verifica si la última vela es reciente.
    Rechaza timestamps en el futuro (edad < 0).
    """
    edad = _edad_minutos(df)
    if edad < 0:
        return False   # ✅ Futuro = inválido
    return edad <= (timeframe_min * tolerancia_mult)


# ============================================================
# CONSTRUCCIÓN
# ============================================================

def construir_desde_m5(df_m5: pd.DataFrame, timeframes_deseados: List[int] = None) -> Dict[int, pd.DataFrame]:
    """
    Construye timeframes mayores a partir de datos M5.
    """
    if df_m5 is None or len(df_m5) < 10:
        logger.warning("⚠️ Datos M5 insuficientes para construir timeframes")
        return {}

    if timeframes_deseados is None:
        timeframes_deseados = TIMEFRAMES_CONSTRUIBLES

    resultados = {}

    # Asegurar índice datetime
    if not isinstance(df_m5.index, pd.DatetimeIndex):
        try:
            df_m5.index = pd.to_datetime(df_m5.index)
        except Exception:
            logger.warning("⚠️ No se pudo convertir índice a datetime")
            return {}

    # Asegurar timezone
    if df_m5.index.tz is None:
        df_m5.index = df_m5.index.tz_localize('UTC')

    # Ordenar
    df_m5 = df_m5.sort_index()

    for tf in timeframes_deseados:
        regla = REGLAS_AGRUPACION.get(tf)
        if not regla:
            logger.debug(f"⚠️ TF{tf}: No hay regla de agrupación definida")
            continue

        try:
            df_tf = df_m5.resample(regla).agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

            if len(df_tf) > 0:
                resultados[tf] = df_tf
                logger.debug(f"✅ TF{tf}: Construido desde M5 ({len(df_tf)} velas)")
        except Exception as e:
            logger.warning(f"⚠️ Error construyendo TF{tf}: {e}")

    return resultados


def construir_h1_desde_m5(df_m5: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Construye H1 a partir de M5."""
    resultado = construir_desde_m5(df_m5, [60])
    return resultado.get(60)


def construir_h4_desde_m5(df_m5: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Construye H4 a partir de M5."""
    resultado = construir_desde_m5(df_m5, [240])
    return resultado.get(240)


def construir_d1_desde_m5(df_m5: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Construye D1 a partir de M5."""
    resultado = construir_desde_m5(df_m5, [1440])
    return resultado.get(1440)


# ============================================================
# MÉTODO PRINCIPAL INTELIGENTE
# ============================================================

def obtener_timeframe_inteligente(
    simbolo: str,
    timeframe: int,
    df_m5: Optional[pd.DataFrame] = None,
    conector: Optional[Any] = None,
    almacen: Optional[Any] = None,
    n_velas: int = 2500,
    forzar_descarga: bool = False,
) -> Optional[pd.DataFrame]:
    """
    V1.2 - Prioridad clara:
    1. Broker fresco → usar
    2. Construir desde M5 fresco → usar
    3. Broker viejo como fallback → usar si no hay otra
    4. SQLite → último recurso
    """
    logger.debug(f"🔍 {simbolo} TF{timeframe}: Obteniendo datos...")

    # ============================================================
    # 1. BROKER
    # ============================================================
    df_broker = None
    if conector is not None:
        try:
            df_broker = conector.obtener_datos(simbolo, n_velas=n_velas, timeframe=timeframe)
        except Exception as e:
            logger.debug(f"⚠️ {simbolo} TF{timeframe}: Error broker: {e}")

    broker_fresco = (
        df_broker is not None
        and len(df_broker) > 0
        and _esta_fresco(df_broker, timeframe)
    )

    if broker_fresco:
        edad = _edad_minutos(df_broker)
        logger.debug(
            f"✅ {simbolo} TF{timeframe}: BROKER fresco "
            f"({len(df_broker)} velas, edad: {edad:.0f} min)"
        )
        return df_broker

    # ============================================================
    # 2. CONSTRUIR DESDE M5
    # ============================================================
    df_construido = None
    if df_m5 is not None and len(df_m5) > 0:
        try:
            velas_necesarias = VELAS_M5_NECESARIAS.get(timeframe, 12)
            if len(df_m5) >= velas_necesarias:
                resultado = construir_desde_m5(df_m5, [timeframe])
                df_c = resultado.get(timeframe)

                if df_c is not None and len(df_c) > 0:
                    edad_c = _edad_minutos(df_c)
                    construido_fresco = (edad_c >= 0 and _esta_fresco(df_c, timeframe))

                    if construido_fresco:
                        logger.info(
                            f"✅ {simbolo} TF{timeframe}: CONSTRUIDO desde M5 "
                            f"({len(df_c)} velas, edad: {edad_c:.0f} min)"
                        )
                        # Guardar en SQLite (reemplaza)
                        if almacen is not None:
                            try:
                                almacen.guardar_datos_historicos(simbolo, timeframe, df_c)
                            except Exception:
                                pass
                        return df_c
                    else:
                        df_construido = df_c  # guardar para posible fallback
        except Exception as e:
            logger.debug(f"⚠️ {simbolo} TF{timeframe}: Error construyendo: {e}")

    # ============================================================
    # 3. SI CONSTRUIDO MEJOR QUE BROKER, USAR CONSTRUIDO
    # ============================================================
    if df_construido is not None and len(df_construido) > 0:
        if df_broker is None or len(df_construido) > len(df_broker):
            edad_c = _edad_minutos(df_construido)
            logger.warning(
                f"⚠️ {simbolo} TF{timeframe}: Usando CONSTRUIDO no fresco "
                f"({len(df_construido)} velas, edad: {edad_c:.0f} min)"
            )
            return df_construido

    # ============================================================
    # 4. BROKER VIEJO COMO FALLBACK
    # ============================================================
    if df_broker is not None and len(df_broker) > 0:
        edad = _edad_minutos(df_broker)
        logger.warning(
            f"⚠️ {simbolo} TF{timeframe}: BROKER VIEJO como fallback "
            f"({len(df_broker)} velas, edad: {edad:.0f} min)"
        )
        return df_broker

    # ============================================================
    # 5. SQLITE
    # ============================================================
    if almacen is not None:
        try:
            df_sqlite = almacen.obtener_datos_historicos(simbolo, timeframe)
            if df_sqlite is not None and len(df_sqlite) > 0:
                logger.info(f"✅ {simbolo} TF{timeframe}: SQLITE ({len(df_sqlite)} velas)")
                return df_sqlite
        except Exception:
            pass

    logger.warning(f"⚠️ {simbolo} TF{timeframe}: Sin datos de ninguna fuente")
    return None


# ============================================================
# VALIDACIÓN DE FRESCURA (COMPATIBILIDAD)
# ============================================================

def validar_frescura_datos(df: pd.DataFrame, timeframe: int, tolerancia_multiplo: int = 2) -> bool:
    """Valida si los datos están frescos."""
    if df is None or len(df) == 0:
        return False

    try:
        edad = _edad_minutos(df)
        tiempo_maximo = timeframe * tolerancia_multiplo
        if edad > tiempo_maximo:
            logger.warning(f"⚠️ Datos desactualizados (edad: {edad:.0f} min > {tiempo_maximo} min)")
            return False
        return True
    except Exception as e:
        logger.warning(f"⚠️ Error validando frescura: {e}")
        return False


# ============================================================
# LIMPIEZA DE CACHÉ
# ============================================================

def limpiar_cache_timeframe(conector: Any, simbolo: str, timeframe: int):
    """Limpia la caché del conector para un símbolo/timeframe."""
    if conector is not None:
        try:
            if hasattr(conector, '_cache_simbolos_data'):
                cache_key = (simbolo, timeframe)
                if cache_key in conector._cache_simbolos_data:
                    del conector._cache_simbolos_data[cache_key]
                    logger.debug(f"🧹 {simbolo} TF{timeframe}: Caché limpiada")
        except Exception as e:
            logger.debug(f"⚠️ Error limpiando caché: {e}")


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import numpy as np

    print("🧪 Probando construir_timeframes V1.1...")

    # Crear M5 de prueba (hasta AHORA)
    n = 2000
    ahora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    fechas = pd.date_range(end=ahora, periods=n, freq='5min', tz='UTC')

    df_m5 = pd.DataFrame({
        'Open': np.random.randn(n) * 0.001 + 1.1,
        'High': np.random.randn(n) * 0.001 + 1.101,
        'Low': np.random.randn(n) * 0.001 + 1.099,
        'Close': np.random.randn(n) * 0.001 + 1.1,
        'Volume': np.random.randint(100, 1000, n),
    }, index=fechas)

    print(f"✅ M5 creado: {len(df_m5)} velas, última: {df_m5.index[-1]}")

    # Construir H1
    df_h1 = construir_h1_desde_m5(df_m5)
    if df_h1 is not None:
        edad = _edad_minutos(df_h1)
        fresco = _esta_fresco(df_h1, 60)
        print(f"✅ H1: {len(df_h1)} velas, edad: {edad:.0f} min, fresco: {fresco}")

    # H4
    df_h4 = construir_h4_desde_m5(df_m5)
    if df_h4 is not None:
        edad = _edad_minutos(df_h4)
        print(f"✅ H4: {len(df_h4)} velas, edad: {edad:.0f} min")

    # D1
    df_d1 = construir_d1_desde_m5(df_m5)
    if df_d1 is not None:
        edad = _edad_minutos(df_d1)
        print(f"✅ D1: {len(df_d1)} velas, edad: {edad:.0f} min")

    print("\n✅ Test completado")