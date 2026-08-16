#!/usr/bin/env python3
"""
core/data_cache.py
Sistema unificado de caché de datos de mercado con persistencia en disco.
"""

import time
import threading
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
import pandas as pd
import hashlib

logger = logging.getLogger('BotTrading.DataCache')


@dataclass
class CacheEntry:
    """Entrada de caché con metadata."""
    data: pd.DataFrame
    timestamp: float
    ttl: int
    n_velas: int
    hash: str = field(default="")
    hits: int = 0
    last_accessed: float = field(default_factory=time.time)
    
    def is_expired(self, now: float) -> bool:
        return (now - self.timestamp) > self.ttl
    
    def touch(self):
        self.last_accessed = time.time()
        self.hits += 1


class DataCache:
    """Caché de datos con persistencia en disco."""
    
    DEFAULT_TTLS = {
        1: 60, 5: 120, 15: 180, 30: 240,
        60: 300, 240: 600,
        1440: 3600, 10080: 7200, 43200: 14400,
    }
    
    def __init__(self, max_size=500, ttls=None, persist_dir=None, persist_interval=60):
        self.max_size = max_size
        self.persist_dir = Path(persist_dir) if persist_dir else Path("data/cache")
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.persist_interval = persist_interval
        self._last_persist = 0
        
        # Combinar TTLs por defecto con personalizados
        self.ttls = self.DEFAULT_TTLS.copy()
        if ttls:
            self.ttls.update(ttls)
        
        self._cache: Dict[Tuple[str, int, int], CacheEntry] = {}
        self._lock = threading.RLock()
        self._stats = {'hits': 0, 'misses': 0, 'expired': 0, 'evicted': 0}
        
        # Cargar caché persistente
        self._cargar_cache_persistente()
        
        logger.info(f"📦 DataCache con persistencia inicializada: {len(self._cache)} entradas")
    
    def _get_cache_path(self) -> Path:
        return self.persist_dir / "data_cache.pkl"
    
    def _cargar_cache_persistente(self):
        """Carga caché desde disco."""
        cache_path = self._get_cache_path()
        if not cache_path.exists():
            return
        
        try:
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            
            if isinstance(data, dict):
                self._cache = data
                # Verificar entradas expiradas
                now = time.time()
                expired = []
                for key, entry in self._cache.items():
                    if entry.is_expired(now):
                        expired.append(key)
                for key in expired:
                    del self._cache[key]
                
                logger.info(f"📦 Caché cargada desde disco: {len(self._cache)} entradas válidas")
            else:
                logger.warning("⚠️ Formato de caché inválido")
        except Exception as e:
            logger.warning(f"⚠️ Error cargando caché: {e}")
    
    def _guardar_cache_persistente(self):
        """Guarda caché en disco."""
        now = time.time()
        if now - self._last_persist < self.persist_interval:
            return
        
        try:
            cache_path = self._get_cache_path()
            temp_path = cache_path.with_suffix('.tmp')
            
            # Limpiar entradas expiradas antes de guardar
            self._cleanup_expired()
            
            with open(temp_path, 'wb') as f:
                pickle.dump(self._cache, f)
            temp_path.replace(cache_path)
            self._last_persist = now
        except Exception as e:
            logger.warning(f"⚠️ Error guardando caché: {e}")
    
    def _cleanup_expired(self):
        """Limpia entradas expiradas."""
        now = time.time()
        expired = [k for k, v in self._cache.items() if v.is_expired(now)]
        for key in expired:
            del self._cache[key]
            self._stats['expired'] += 1
    
    def get(self, simbolo, timeframe, n_velas, fetch_func=None, force=False):
        """Obtiene datos de caché o los descarga."""
        key = (simbolo, timeframe, n_velas)
        now = time.time()
        
        with self._lock:
            if not force and key in self._cache:
                entry = self._cache[key]
                if not entry.is_expired(now):
                    entry.touch()
                    self._stats['hits'] += 1
                    return entry.data.copy()
                else:
                    self._stats['expired'] += 1
                    del self._cache[key]
            
            self._stats['misses'] += 1
        
        # Descargar
        if fetch_func:
            try:
                df = fetch_func(simbolo, n_velas, timeframe)
                if df is not None and not df.empty:
                    ttl = self.ttls.get(timeframe, 300)
                    entry = CacheEntry(
                        data=df.copy(),
                        timestamp=now,
                        ttl=ttl,
                        n_velas=n_velas,
                        hash=self._calcular_hash(df)
                    )
                    with self._lock:
                        self._cache[key] = entry
                        self._guardar_cache_persistente()
                    return df.copy()
            except Exception as e:
                logger.error(f"Error descargando {simbolo}: {e}")
        
        return None
    
    def get_multi(self, simbolo, timeframes, n_velas=None, fetch_func=None):
        """Obtiene múltiples timeframes."""
        resultados = {}
        for tf in timeframes:
            n_v = n_velas or 250
            df = self.get(simbolo, tf, n_v, fetch_func)
            if df is not None:
                resultados[tf] = df
        return resultados
    
    def _calcular_hash(self, df: pd.DataFrame) -> str:
        """Calcula hash del DataFrame."""
        try:
            close_values = df['Close'].iloc[-10:].values
            return hashlib.md5(close_values.tobytes()).hexdigest()[:16]
        except Exception:
            return str(time.time())
    
    def _set(self, key, df, now):
        """Almacena entrada en caché (uso interno)."""
        _, timeframe, _ = key
        ttl = self.ttls.get(timeframe, 300)
        entry = CacheEntry(
            data=df.copy(),
            timestamp=now,
            ttl=ttl,
            n_velas=key[2],
            hash=self._calcular_hash(df)
        )
        with self._lock:
            self._cache[key] = entry
            self._guardar_cache_persistente()
    
    def get_stats(self) -> Dict:
        """Obtiene estadísticas de caché."""
        with self._lock:
            stats = self._stats.copy()
            stats['current_size'] = len(self._cache)
            stats['max_size'] = self.max_size
            total = stats['hits'] + stats['misses']
            stats['hit_rate'] = (stats['hits'] / total * 100) if total > 0 else 0
            return stats
    
    def clear(self):
        """Limpia toda la caché."""
        with self._lock:
            self._cache.clear()
            self._guardar_cache_persistente()
        logger.info("🧹 Caché limpiada")
    
    def invalidate(self, simbolo=None):
        """Invalida caché de un símbolo o todos."""
        with self._lock:
            if simbolo:
                keys = [k for k in self._cache.keys() if k[0] == simbolo]
                for key in keys:
                    del self._cache[key]
            else:
                self._cache.clear()
            self._guardar_cache_persistente()


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_data_cache_with_config(config: Any) -> DataCache:
    """
    Crea una instancia de DataCache con configuración desde Config.
    
    Args:
        config: Objeto de configuración (Config)
    
    Returns:
        DataCache configurada
    """
    # Extraer TTLs desde config si existen
    ttls = {}
    if hasattr(config, 'DATA_CACHE_TTLS'):
        ttls = config.DATA_CACHE_TTLS
    
    # Extraer max_size
    max_size = getattr(config, 'DATA_CACHE_MAX_SIZE', 500)
    
    # Extraer directorio de persistencia
    persist_dir = getattr(config, 'DATA_CACHE_PERSIST_DIR', 'data/cache')
    
    # Extraer intervalo de persistencia
    persist_interval = getattr(config, 'DATA_CACHE_PERSIST_INTERVAL', 60)
    
    return DataCache(
        max_size=max_size,
        ttls=ttls,
        persist_dir=persist_dir,
        persist_interval=persist_interval
    )