# services/market_data_service.py
from __future__ import annotations
from typing import Optional, Dict, Any
import time
import pandas as pd
from mt5.conector_mt5 import ConectorBase
from config.settings import Config
import logging

logger = logging.getLogger('BotTrading.MarketDataService')

class MarketDataService:
    """Servicio de datos de mercado con caché TTL y normalización de columnas."""

    def __init__(self, mt5: ConectorBase, cache_ttl_seconds: int = 60):
        self.mt5 = mt5
        self.cache_ttl = cache_ttl_seconds
        # Estructura de caché: clave (symbol, n_velas, timeframe) -> (timestamp, dataframe)
        self._cache: Dict[tuple, tuple] = {}

    def _normalizar_dataframe(self, df_raw: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Normaliza columnas a formato estándar (Open, High, Low, Close, Volume)."""
        if df_raw is None or df_raw.empty:
            return None
        # Convertir nombres de columnas a minúsculas para mapeo uniforme
        df = df_raw.copy()
        df.columns = df.columns.str.lower()
        # Mapear nombres
        rename_map = {
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'tick_volume': 'Volume',
            'volume': 'Volume'   # Por si el conector usa 'volume' en lugar de 'tick_volume'
        }
        df.rename(columns=rename_map, inplace=True)
        # Verificar que las columnas requeridas existan
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required):
            logger.warning(f"DataFrame faltan columnas requeridas: {list(df.columns)}")
            return None
        # Asegurar índice datetime
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
        return df

    def obtener_ohlc(
        self,
        symbol: str,
        n_velas: int,
        timeframe: int,
    ) -> Optional[pd.DataFrame]:
        """
        Devuelve un DataFrame con columnas estandarizadas (Open, High, Low, Close, Volume).
        Usa caché con TTL.
        """
        clave = (symbol, n_velas, timeframe)
        ahora = time.time()
        # Verificar caché
        if clave in self._cache:
            timestamp, df = self._cache[clave]
            if ahora - timestamp < self.cache_ttl:
                logger.debug(f"Cache hit para {symbol} TF{timeframe} ({n_velas} velas)")
                return df.copy() if df is not None else None
            else:
                logger.debug(f"Cache expirado para {symbol} TF{timeframe}")
                del self._cache[clave]

        # Obtener datos frescos
        df_raw = self.mt5.obtener_datos(symbol, n_velas=n_velas, timeframe=timeframe)
        if df_raw is None or df_raw.empty:
            logger.warning(f"No se pudieron obtener datos para {symbol} TF{timeframe}")
            # Almacenar None para evitar reintentos constantes (con TTL)
            self._cache[clave] = (ahora, None)
            return None

        df_norm = self._normalizar_dataframe(df_raw)
        if df_norm is None or len(df_norm) < n_velas:
            logger.warning(f"Datos insuficientes para {symbol}: {len(df_norm) if df_norm is not None else 0} < {n_velas}")
            self._cache[clave] = (ahora, None)
            return None

        # Guardar en caché
        self._cache[clave] = (ahora, df_norm)
        return df_norm.copy()

    def obtener_precio(self, symbol: str) -> Optional[dict]:
        """Obtiene precio en tiempo real desde el conector."""
        return self.mt5.obtener_precio(symbol)

    def invalidar_cache(self, symbol: Optional[str] = None, timeframe: Optional[int] = None):
        """Invalida la caché para un símbolo y/o timeframe específicos, o toda la caché."""
        if symbol is None and timeframe is None:
            self._cache.clear()
            logger.info("Caché de market_data invalidada completamente")
            return
        keys_to_delete = []
        for (sym, n, tf) in self._cache.keys():
            if (symbol is None or sym == symbol) and (timeframe is None or tf == timeframe):
                keys_to_delete.append((sym, n, tf))
        for k in keys_to_delete:
            del self._cache[k]
        logger.info(f"Cache invalidada para symbol={symbol}, timeframe={timeframe}")
