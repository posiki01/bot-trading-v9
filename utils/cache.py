#!/usr/bin/env python3
"""
utils/cache.py (V9.0 - UNIFICADO COMPLETAMENTE)
Sistema unificado de caché para datos de mercado y análisis.
"""

import time
import threading
import logging
import pickle
import hashlib
import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
import pandas as pd

logger = logging.getLogger('BotTrading.Cache')


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class CacheEntry:
    """Entrada de caché con metadata."""
    data: Any
    timestamp: float
    ttl: int
    hash: str = ""
    hits: int = 0
    last_accessed: float = field(default_factory=time.time)
    
    def is_expired(self, now: float) -> bool:
        return (now - self.timestamp) > self.ttl
    
    def touch(self):
        self.last_accessed = time.time()
        self.hits += 1


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class CacheUnificado:
    """
    Sistema unificado de caché para datos de mercado y análisis.
    V9.0 - UNIFICADO COMPLETAMENTE.
    """
    
    # TTL por defecto (segundos)
    TTL_POR_DEFECTO = {
        1: 60, 5: 120, 15: 180, 30: 240,
        60: 300, 240: 600,
        1440: 3600, 10080: 7200, 43200: 14400,
        'fase1': 300,
        'fase2': 180,
        'fase3': 120,
        'sniper': 60,
        'tecnico': 300,
        'niveles': 600,
        'patrones': 600,
        'regimen': 900,
        'score': 300,
        'cot': 3600,
    }
    
    def __init__(self,
                 max_size: int = 500,
                 default_ttl: int = 300,
                 ttls: Optional[Dict[Union[int, str], int]] = None,
                 persist_dir: Optional[Path] = None,
                 persist_interval: int = 60,
                 modo_backtest: bool = False):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.persist_dir = Path(persist_dir) if persist_dir else Path("data/cache")
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.persist_interval = persist_interval
        self.modo_backtest = modo_backtest
        
        self.ttls = self.TTL_POR_DEFECTO.copy()
        if ttls:
            self.ttls.update(ttls)
        
        self._cache: Dict[Tuple, CacheEntry] = {}
        self._lock = threading.RLock()
        self._last_persist = 0
        
        self._indice_simbolo: Dict[str, List[Tuple]] = {}
        self._indice_fase: Dict[str, List[Tuple]] = {}
        
        self._stats = {
            'hits': 0,
            'misses': 0,
            'expired': 0,
            'evicted': 0,
            'total_entries': 0,
            'persist_count': 0,
            'load_count': 0,
        }
        
        self._cargar_cache_persistente()
        self._iniciar_limpieza_automatica()
        
        logger.info(f"📦 CacheUnificado V9.0 inicializado")
        logger.info(f"   Max size: {max_size}")
        logger.info(f"   Default TTL: {default_ttl}s")
        logger.info(f"   Persist dir: {self.persist_dir}")
    
    # ============================================================
    # MÉTODOS PRINCIPALES
    # ============================================================
    
    def get(self, key: Union[Tuple, str], ttl: Optional[int] = None) -> Optional[Any]:
        if isinstance(key, str):
            key = (key,)
        
        now = time.time()
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                ttl_efectivo = ttl or entry.ttl
                if not entry.is_expired(now):
                    entry.touch()
                    self._stats['hits'] += 1
                    return entry.data
                else:
                    self._stats['expired'] += 1
                    del self._cache[key]
                    self._remover_indices(key)
                    return None
            
            self._stats['misses'] += 1
            return None
    
    def set(self, key: Union[Tuple, str], data: Any, ttl: Optional[int] = None):
        if data is None:
            return
        
        if isinstance(key, str):
            key = (key,)
        
        now = time.time()
        if ttl is None:
            ttl = self._obtener_ttl(key)
        
        hash_val = self._calcular_hash(data) if isinstance(data, pd.DataFrame) else ""
        
        with self._lock:
            entry = CacheEntry(
                data=data,
                timestamp=now,
                ttl=ttl,
                hash=hash_val,
                hits=0,
                last_accessed=now
            )
            
            self._cache[key] = entry
            self._agregar_indices(key)
            self._stats['total_entries'] += 1
            self._cleanup_if_needed()
            self._guardar_cache_persistente()
    
    def get_or_compute(self, key: Union[Tuple, str],
                       compute_func: Callable,
                       ttl: Optional[int] = None,
                       force: bool = False) -> Optional[Any]:
        if not force:
            resultado = self.get(key, ttl)
            if resultado is not None:
                return resultado
        
        try:
            resultado = compute_func()
            if resultado is not None:
                self.set(key, resultado, ttl)
            return resultado
        except Exception as e:
            logger.error(f"❌ Error calculando para caché {key}: {e}")
            return None
    
    # ============================================================
    # MÉTODOS DE DATOS (DataCache)
    # ============================================================
    
    def get_datos(self, simbolo: str, timeframe: int, n_velas: int,
                  fetch_func: Optional[Callable] = None,
                  force: bool = False) -> Optional[pd.DataFrame]:
        key = (simbolo, timeframe, n_velas)
        if not force:
            resultado = self.get(key)
            if resultado is not None:
                return resultado.copy() if isinstance(resultado, pd.DataFrame) else resultado
        
        if fetch_func:
            try:
                df = fetch_func(simbolo, n_velas, timeframe)
                if df is not None and not df.empty:
                    self.set(key, df.copy())
                    return df.copy()
            except Exception as e:
                logger.error(f"❌ Error descargando {simbolo}: {e}")
        
        return None
    
    def get_datos_multi(self, simbolo: str, timeframes: List[int],
                        n_velas: Optional[int] = None,
                        fetch_func: Optional[Callable] = None) -> Dict[int, Optional[pd.DataFrame]]:
        resultados = {}
        n_v = n_velas or 250
        for tf in timeframes:
            df = self.get_datos(simbolo, tf, n_v, fetch_func)
            if df is not None:
                resultados[tf] = df
        return resultados
    
    # ============================================================
    # MÉTODOS DE ANÁLISIS (AnalysisCache)
    # ============================================================
    
    def get_analisis(self, simbolo: str, fase: str, df: pd.DataFrame,
                     ttl: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if df is None or df.empty:
            return None
        df_hash = self._calcular_hash(df)
        key = (simbolo, fase, df_hash)
        return self.get(key, ttl)
    
    def set_analisis(self, simbolo: str, fase: str, df: pd.DataFrame,
                     resultado: Dict[str, Any], ttl: Optional[int] = None):
        if df is None or df.empty or resultado is None:
            return
        df_hash = self._calcular_hash(df)
        key = (simbolo, fase, df_hash)
        self.set(key, resultado.copy() if resultado else {}, ttl)
    
    def get_analisis_or_compute(self, simbolo: str, fase: str, df: pd.DataFrame,
                                compute_func: Callable, ttl: Optional[int] = None,
                                force: bool = False) -> Optional[Dict[str, Any]]:
        if not force:
            resultado = self.get_analisis(simbolo, fase, df, ttl)
            if resultado is not None:
                return resultado
        
        try:
            resultado = compute_func()
            if resultado:
                self.set_analisis(simbolo, fase, df, resultado, ttl)
            return resultado
        except Exception as e:
            logger.error(f"❌ Error calculando análisis {simbolo} [{fase}]: {e}")
            return None
    
    # ============================================================
    # INVALIDACIÓN
    # ============================================================
    
    def invalidate(self, key: Optional[Union[Tuple, str]] = None):
        if key is None:
            with self._lock:
                self._cache.clear()
                self._indice_simbolo.clear()
                self._indice_fase.clear()
            logger.info("🧹 Toda la caché invalidada")
            return
        
        if isinstance(key, str):
            key = (key,)
        
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._remover_indices(key)
    
    def invalidate_por_simbolo(self, simbolo: str):
        if simbolo in self._indice_simbolo:
            keys_to_remove = self._indice_simbolo[simbolo].copy()
            for key in keys_to_remove:
                if key in self._cache:
                    del self._cache[key]
                self._remover_indices(key)
    
    def invalidate_por_fase(self, fase: str):
        if fase in self._indice_fase:
            keys_to_remove = self._indice_fase[fase].copy()
            for key in keys_to_remove:
                if key in self._cache:
                    del self._cache[key]
                self._remover_indices(key)
    
    def clear(self):
        self.invalidate()
    
    # ============================================================
    # MÉTODOS INTERNOS
    # ============================================================
    
    def _obtener_ttl(self, key: Tuple) -> int:
        if len(key) >= 2 and isinstance(key[1], int):
            return self.ttls.get(key[1], self.default_ttl)
        if len(key) >= 2 and isinstance(key[1], str):
            return self.ttls.get(key[1], self.default_ttl)
        return self.default_ttl
    
    def _calcular_hash(self, data: Any) -> str:
        if data is None:
            return ""
        try:
            if isinstance(data, pd.DataFrame):
                n = min(10, len(data))
                if 'Close' in data.columns:
                    close_values = data['Close'].iloc[-n:].values
                    volume_values = data['Volume'].iloc[-n:].values if 'Volume' in data.columns else []
                    combined = close_values.tobytes() + (volume_values.tobytes() if len(volume_values) > 0 else b'')
                    return hashlib.md5(combined).hexdigest()[:16]
            elif isinstance(data, dict):
                return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
            elif isinstance(data, str):
                return hashlib.md5(data.encode()).hexdigest()[:16]
        except Exception as e:
            logger.debug(f"Error calculando hash: {e}")
        return str(time.time())
    
    def _agregar_indices(self, key: Tuple):
        if len(key) >= 1 and isinstance(key[0], str):
            simbolo = key[0]
            if simbolo not in self._indice_simbolo:
                self._indice_simbolo[simbolo] = []
            if key not in self._indice_simbolo[simbolo]:
                self._indice_simbolo[simbolo].append(key)
        if len(key) >= 2 and isinstance(key[1], str):
            fase = key[1]
            if fase not in self._indice_fase:
                self._indice_fase[fase] = []
            if key not in self._indice_fase[fase]:
                self._indice_fase[fase].append(key)
    
    def _remover_indices(self, key: Tuple):
        if len(key) >= 1 and isinstance(key[0], str):
            simbolo = key[0]
            if simbolo in self._indice_simbolo and key in self._indice_simbolo[simbolo]:
                self._indice_simbolo[simbolo].remove(key)
                if not self._indice_simbolo[simbolo]:
                    del self._indice_simbolo[simbolo]
        if len(key) >= 2 and isinstance(key[1], str):
            fase = key[1]
            if fase in self._indice_fase and key in self._indice_fase[fase]:
                self._indice_fase[fase].remove(key)
                if not self._indice_fase[fase]:
                    del self._indice_fase[fase]
    
    def _cleanup_if_needed(self):
        with self._lock:
            now = time.time()
            expired_keys = []
            for key, entry in self._cache.items():
                if entry.is_expired(now):
                    expired_keys.append(key)
            for key in expired_keys:
                del self._cache[key]
                self._remover_indices(key)
                self._stats['expired'] += 1
            
            if len(self._cache) > self.max_size:
                sorted_entries = sorted(self._cache.items(), key=lambda x: x[1].last_accessed)
                to_remove = len(self._cache) - self.max_size
                for key, _ in sorted_entries[:to_remove]:
                    del self._cache[key]
                    self._remover_indices(key)
                    self._stats['evicted'] += 1
    
    # ============================================================
    # PERSISTENCIA
    # ============================================================
    
    def _cargar_cache_persistente(self):
        cache_path = self.persist_dir / "cache_unificado.pkl"
        if not cache_path.exists():
            return
        try:
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            if isinstance(data, dict):
                now = time.time()
                valid_entries = {}
                for key, entry in data.items():
                    if not entry.is_expired(now):
                        valid_entries[key] = entry
                self._cache = valid_entries
                self._stats['load_count'] += 1
                for key in self._cache:
                    self._agregar_indices(key)
                logger.info(f"📦 Caché cargada desde disco: {len(self._cache)} entradas")
        except Exception as e:
            logger.warning(f"⚠️ Error cargando caché: {e}")
    
    def _guardar_cache_persistente(self):
        now = time.time()
        if now - self._last_persist < self.persist_interval:
            return
        try:
            cache_path = self.persist_dir / "cache_unificado.pkl"
            temp_path = cache_path.with_suffix('.tmp')
            with open(temp_path, 'wb') as f:
                pickle.dump(self._cache, f)
            temp_path.replace(cache_path)
            self._last_persist = now
            self._stats['persist_count'] += 1
        except Exception as e:
            logger.warning(f"⚠️ Error guardando caché: {e}")
    
    def _iniciar_limpieza_automatica(self):
        def limpiar():
            import time as _time
            while True:
                _time.sleep(300)
                try:
                    with self._lock:
                        now = _time.time()
                        expired_keys = []
                        for key, entry in self._cache.items():
                            if entry.is_expired(now):
                                expired_keys.append(key)
                        for key in expired_keys:
                            del self._cache[key]
                            self._remover_indices(key)
                            self._stats['expired'] += 1
                except Exception:
                    pass
        threading.Thread(target=limpiar, daemon=True, name="CacheCleaner").start()
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            stats = self._stats.copy()
            total = stats['hits'] + stats['misses']
            stats['hit_rate'] = (stats['hits'] / total * 100) if total > 0 else 0
            stats['current_size'] = len(self._cache)
            stats['max_size'] = self.max_size
            
            by_type = {'datos': 0, 'analisis': 0, 'otros': 0}
            for key in self._cache.keys():
                if len(key) >= 2:
                    if isinstance(key[1], int):
                        by_type['datos'] += 1
                    elif isinstance(key[1], str):
                        by_type['analisis'] += 1
                    else:
                        by_type['otros'] += 1
                else:
                    by_type['otros'] += 1
            stats['by_type'] = by_type
            return stats


# ============================================================
# FUNCIONES DE UTILIDAD
# ============================================================

def create_cache_unificado(config: Optional[Any] = None,
                           persist_dir: Optional[Path] = None,
                           modo_backtest: bool = False) -> CacheUnificado:
    max_size = getattr(config, 'CACHE_MAX_SIZE', 500) if config else 500
    default_ttl = getattr(config, 'CACHE_DEFAULT_TTL', 300) if config else 300
    ttls = getattr(config, 'CACHE_TTLS', None) if config else None
    persist_interval = getattr(config, 'CACHE_PERSIST_INTERVAL', 60) if config else 60
    
    return CacheUnificado(
        max_size=max_size,
        default_ttl=default_ttl,
        ttls=ttls,
        persist_dir=persist_dir,
        persist_interval=persist_interval,
        modo_backtest=modo_backtest
    )


# ============================================================
# ALIAS DE COMPATIBILIDAD (PARA BACKTEST Y MIGRACIÓN)
# ============================================================

# Alias para compatibilidad con código antiguo
DataCache = CacheUnificado
AnalysisCache = CacheUnificado

# Función de compatibilidad
def create_data_cache_with_config(config, **kwargs):
    """Alias de compatibilidad para DataCache."""
    return create_cache_unificado(config, **kwargs)

def create_analysis_cache_with_config(config, **kwargs):
    """Alias de compatibilidad para AnalysisCache."""
    return create_cache_unificado(config, **kwargs)


# ============================================================
# DECORADOR PARA CACHÉ
# ============================================================

def cached(fase: str, ttl: Optional[int] = None):
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            simbolo = kwargs.get('simbolo') or args[0]
            df = kwargs.get('df') or args[1] if len(args) > 1 else None
            if not simbolo or df is None:
                return func(self, *args, **kwargs)
            if hasattr(self, '_cache') and self._cache:
                resultado = self._cache.get_analisis(simbolo, fase, df, ttl)
                if resultado is not None:
                    return resultado
            resultado = func(self, *args, **kwargs)
            if hasattr(self, '_cache') and self._cache and resultado:
                self._cache.set_analisis(simbolo, fase, df, resultado, ttl)
            return resultado
        return wrapper
    return decorator


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import pandas as pd
    import numpy as np
    
    print("🧪 Probando CacheUnificado...")
    
    cache = CacheUnificado(max_size=10, modo_backtest=True)
    
    df = pd.DataFrame({
        'Close': np.random.randn(100) + 100,
        'Volume': np.random.randint(100, 1000, 100)
    })
    
    cache.set(('EURUSD', 60, 100), df)
    resultado = cache.get(('EURUSD', 60, 100))
    print(f"Datos: {'✅' if resultado is not None else '❌'}")
    
    cache.set_analisis('EURUSD', 'fase1', df, {'score': 75, 'direccion': 'COMPRA'})
    resultado = cache.get_analisis('EURUSD', 'fase1', df)
    print(f"Análisis: {'✅' if resultado is not None else '❌'}")
    
    print("\n✅ Prueba completada")