#!/usr/bin/env python3
"""
utils/construir_timeframes.py (V1.0 - DEFINITIVO)
Construye timeframes mayores a partir de M5 cuando el broker no los tiene.

V1.0 - DEFINITIVO:
- Detecta automáticamente si el broker tiene el timeframe
- Construye desde M5 solo si el broker NO lo tiene
- No genera conflictos si ambos están disponibles
- Prioriza datos del broker sobre datos construidos
- Guarda en SQLite y caché
"""

import logging
import pandas as pd
from typing import Dict, Optional, List, Any
from datetime import datetime, timezone, timedelta

logger = logging.getLogger('BotTrading.ConstruirTimeframes')


# ============================================================
# MAPEO DE TIMEFRAMES A REGLAS DE AGRUPACIÓN
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

# Timeframes que se pueden construir desde M5
TIMEFRAMES_CONSTRUIBLES = [15, 30, 60, 240, 1440]

# Número de velas M5 necesarias para construir cada timeframe
VELAS_M5_NECESARIAS = {
    15: 3,      # 3 velas M5 = 1 vela M15
    30: 6,      # 6 velas M5 = 1 vela M30
    60: 12,     # 12 velas M5 = 1 vela H1
    240: 48,    # 48 velas M5 = 1 vela H4
    1440: 288,  # 288 velas M5 = 1 vela D1
}


# ============================================================
# DETECCIÓN DE DISPONIBILIDAD EN BROKER
# ============================================================

def verificar_disponibilidad_broker(mt5: Any, simbolo: str, timeframe: int) -> bool:
    """
    Verifica si el broker tiene datos para el timeframe especificado.
    
    Args:
        mt5: Módulo MetaTrader5 (o conector)
        simbolo: Símbolo
        timeframe: Timeframe en minutos
    
    Returns:
        True si el broker tiene datos, False si no
    """
    try:
        # Intentar obtener datos directamente del broker
        rates = mt5.copy_rates_from_pos(simbolo, timeframe, 0, 1)
        
        if rates is not None and len(rates) > 0:
            return True
        
        return False
        
    except Exception as e:
        logger.debug(f"Error verificando disponibilidad: {e}")
        return False


def verificar_disponibilidad_conector(conector: Any, simbolo: str, timeframe: int) -> bool:
    """
    Verifica si el conector tiene datos para el timeframe especificado.
    
    Args:
        conector: Conector MT5
        simbolo: Símbolo
        timeframe: Timeframe en minutos
    
    Returns:
        True si el conector puede obtener datos, False si no
    """
    try:
        # Intentar obtener datos del conector
        df = conector.obtener_datos(simbolo, n_velas=5, timeframe=timeframe)
        
        if df is not None and len(df) > 0:
            return True
        
        return False
        
    except Exception as e:
        logger.debug(f"Error verificando disponibilidad del conector: {e}")
        return False


# ============================================================
# CONSTRUCCIÓN DE TIMEFRAMES
# ============================================================

def construir_desde_m5(df_m5: pd.DataFrame, timeframes_deseados: List[int] = None) -> Dict[int, pd.DataFrame]:
    """
    Construye timeframes mayores a partir de datos M5.
    
    Args:
        df_m5: DataFrame con datos M5 (index: datetime, columns: Open, High, Low, Close, Volume)
        timeframes_deseados: Lista de timeframes a construir
    
    Returns:
        Diccionario {timeframe: DataFrame}
    """
    if df_m5 is None or len(df_m5) < 10:
        logger.warning("⚠️ Datos M5 insuficientes para construir timeframes")
        return {}
    
    if timeframes_deseados is None:
        timeframes_deseados = TIMEFRAMES_CONSTRUIBLES
    
    resultados = {}
    
    # Asegurar que el índice sea datetime
    if not isinstance(df_m5.index, pd.DatetimeIndex):
        try:
            df_m5.index = pd.to_datetime(df_m5.index)
        except Exception:
            logger.warning("⚠️ No se pudo convertir índice a datetime")
            return {}
    
    # Asegurar que el índice tenga zona horaria
    if df_m5.index.tz is None:
        df_m5.index = df_m5.index.tz_localize('UTC')
    
    # Ordenar por índice
    df_m5 = df_m5.sort_index()
    
    for tf in timeframes_deseados:
        regla = REGLAS_AGRUPACION.get(tf)
        if not regla:
            logger.debug(f"⚠️ TF{tf}: No hay regla de agrupación definida")
            continue
        
        try:
            # Construir timeframe
            df_tf = df_m5.resample(regla).agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
            
            if len(df_tf) > 0:
                resultados[tf] = df_tf
                logger.info(f"✅ TF{tf}: Construido desde M5 ({len(df_tf)} velas)")
            else:
                logger.debug(f"⚠️ TF{tf}: Construcción vacía")
                
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
# MÉTODO INTELIGENTE: PRIORIZA BROKER, CONSTRUYE SI FALTA
# ============================================================

def obtener_timeframe_inteligente(
    simbolo: str,
    timeframe: int,
    df_m5: Optional[pd.DataFrame] = None,
    conector: Optional[Any] = None,
    almacen: Optional[Any] = None,
    n_velas: int = 2500,
    forzar_descarga: bool = False
) -> Optional[pd.DataFrame]:
    """
    Obtiene datos de un timeframe de forma INTELIGENTE:
    1. Primero intenta desde el broker
    2. Si el broker tiene POCOS datos, construye desde M5
    3. Si el broker NO tiene, construye desde M5
    4. Si no hay M5, intenta desde SQLite
    
    V9.3 - CORREGIDO: Construye desde M5 cuando broker tiene pocos datos.
    
    Args:
        simbolo: Símbolo
        timeframe: Timeframe deseado
        df_m5: DataFrame M5 (opcional, para construir)
        conector: Conector MT5 (opcional)
        almacen: Almacenamiento SQLite (opcional)
        n_velas: Número de velas a obtener
        forzar_descarga: Forzar descarga desde broker
    
    Returns:
        DataFrame con datos del timeframe o None
    """
    logger.info(f"🔍 {simbolo} TF{timeframe}: Obteniendo datos de forma inteligente...")
    
    # ============================================================
    # 1. INTENTAR DESDE BROKER
    # ============================================================
    df_broker = None
    if conector is not None:
        try:
            df_broker = conector.obtener_datos(simbolo, n_velas=n_velas, timeframe=timeframe)
            
            if df_broker is not None and len(df_broker) > 0:
                logger.info(f"✅ {simbolo} TF{timeframe}: BROKER ({len(df_broker)} velas)")
                
                # ⚠️ VERIFICAR SI LOS DATOS DEL BROKER SON SUFICIENTES
                # Si tiene al menos 50% de lo pedido, usar broker
                if len(df_broker) >= n_velas * 0.5:
                    return df_broker
                else:
                    logger.warning(f"⚠️ {simbolo} TF{timeframe}: BROKER tiene pocos datos ({len(df_broker)} velas < {n_velas * 0.5:.0f})")
                    # Intentar construir desde M5
        except Exception as e:
            logger.debug(f"⚠️ {simbolo} TF{timeframe}: Error en broker: {e}")
    
    # ============================================================
    # 2. INTENTAR CONSTRUIR DESDE M5 (SI EL BROKER NO TIENE O TIENE POCOS)
    # ============================================================
    if df_m5 is not None and len(df_m5) > 0:
        try:
            # Verificar si M5 tiene suficientes velas para construir
            velas_necesarias = VELAS_M5_NECESARIAS.get(timeframe, 12)
            
            if len(df_m5) >= velas_necesarias:
                # Construir
                df_construido = construir_desde_m5(df_m5, [timeframe])
                
                if timeframe in df_construido and len(df_construido[timeframe]) > 0:
                    df_construido_tf = df_construido[timeframe]
                    logger.info(f"✅ {simbolo} TF{timeframe}: CONSTRUIDO desde M5 ({len(df_construido_tf)} velas)")
                    
                    # ✅ SI LO CONSTRUIDO ES MEJOR QUE EL BROKER, USARLO
                    if df_broker is None or len(df_construido_tf) > len(df_broker):
                        # Guardar en SQLite si está disponible
                        if almacen is not None:
                            try:
                                almacen.guardar_datos_historicos(simbolo, timeframe, df_construido_tf)
                            except Exception as e:
                                logger.debug(f"⚠️ Error guardando en SQLite: {e}")
                        
                        return df_construido_tf
                    else:
                        # Broker tiene más datos, usar broker
                        logger.info(f"✅ {simbolo} TF{timeframe}: Usando BROKER ({len(df_broker)} velas) - mejor que construido")
                        return df_broker
        except Exception as e:
            logger.debug(f"⚠️ {simbolo} TF{timeframe}: Error construyendo: {e}")
    
    # ============================================================
    # 3. SI BROKER TIENE DATOS, USARLOS
    # ============================================================
    if df_broker is not None and len(df_broker) > 0:
        return df_broker
    
    # ============================================================
    # 4. INTENTAR DESDE SQLITE (ÚLTIMO RECURSO)
    # ============================================================
    if almacen is not None:
        try:
            df_sqlite = almacen.obtener_datos_historicos(simbolo, timeframe)
            if df_sqlite is not None and len(df_sqlite) > 0:
                logger.info(f"✅ {simbolo} TF{timeframe}: SQLITE ({len(df_sqlite)} velas)")
                return df_sqlite
        except Exception as e:
            logger.debug(f"⚠️ Error en SQLite: {e}")
    
    # ============================================================
    # 5. NO HAY DATOS
    # ============================================================
    logger.warning(f"⚠️ {simbolo} TF{timeframe}: No se obtuvieron datos de ninguna fuente")
    return None
# ============================================================
# VERIFICAR FRESCURA
# ============================================================

def validar_frescura_datos(df: pd.DataFrame, timeframe: int, tolerancia_multiplo: int = 2) -> bool:
    """
    Valida si los datos están frescos (última vela cercana).
    
    Args:
        df: DataFrame con datos OHLCV
        timeframe: Timeframe en minutos
        tolerancia_multiplo: Multiplicador de tolerancia (2 = 2x el timeframe)
    
    Returns:
        True si los datos están frescos, False si están desactualizados
    """
    if df is None or len(df) == 0:
        return False
    
    try:
        # Obtener fecha de la última vela
        ultima_fecha = df.index[-1]
        
        # Convertir a UTC si no lo está
        if ultima_fecha.tzinfo is None:
            ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
        
        # Calcular tiempo máximo permitido
        tiempo_maximo = timedelta(minutes=timeframe * tolerancia_multiplo)
        
        # Obtener hora actual
        ahora = datetime.now(timezone.utc)
        
        # Calcular diferencia
        diferencia = ahora - ultima_fecha
        
        # Si la diferencia es mayor al máximo permitido, los datos están desactualizados
        if diferencia > tiempo_maximo:
            logger.warning(f"⚠️ Datos desactualizados (última: {ultima_fecha}, diff: {diferencia}, max: {tiempo_maximo})")
            return False
        
        return True
        
    except Exception as e:
        logger.warning(f"⚠️ Error validando frescura: {e}")
        return False


# ============================================================
# RESET DE CACHÉ PARA FUERZA RECARGA
# ============================================================

def limpiar_cache_timeframe(conector: Any, simbolo: str, timeframe: int):
    """
    Limpia la caché de un símbolo y timeframe específico.
    """
    if conector is not None:
        try:
            # Limpiar caché del conector
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
    print("🧪 Probando construir_timeframes...")
    
    # Crear datos M5 de prueba
    import numpy as np
    np.random.seed(42)
    
    n = 1000  # 1000 velas M5
    fechas = pd.date_range('2024-01-01', periods=n, freq='5T', tz='UTC')
    
    df_m5 = pd.DataFrame({
        'Open': np.random.randn(n) * 0.001 + 1.1,
        'High': np.random.randn(n) * 0.001 + 1.101,
        'Low': np.random.randn(n) * 0.001 + 1.099,
        'Close': np.random.randn(n) * 0.001 + 1.1,
        'Volume': np.random.randint(100, 1000, n)
    }, index=fechas)
    
    print(f"✅ Datos M5 creados: {len(df_m5)} velas")
    
    # Construir H1
    df_h1 = construir_h1_desde_m5(df_m5)
    print(f"✅ H1 construido: {len(df_h1) if df_h1 is not None else 0} velas")
    
    # Construir H4
    df_h4 = construir_h4_desde_m5(df_m5)
    print(f"✅ H4 construido: {len(df_h4) if df_h4 is not None else 0} velas")
    
    # Construir D1
    df_d1 = construir_d1_desde_m5(df_m5)
    print(f"✅ D1 construido: {len(df_d1) if df_d1 is not None else 0} velas")
    
    # Mostrar ejemplos
    if df_h1 is not None:
        print(f"\n📊 H1 (primeras 3 velas):")
        print(df_h1.head(3))
    
    print("\n✅ Prueba completada")