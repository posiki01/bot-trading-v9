#!/usr/bin/env python3
"""
utils/cache.py (V10.0 - REFACTORIZADO)
Sistema unificado de caché para datos de mercado y análisis.

CORRECCIONES V10.0:
- ✅ get() definido UNA sola vez (antes había dos definiciones → la segunda ganaba)
- ✅ Sin logger.info en hot path (antes logueaba CADA llamada)
- ✅ Persistencia excluye DataFrames (solo config/estado)
- ✅ Hilo de limpieza con flag para detenerse
- ✅ Interfaz pública preservada (DataCache, AnalysisCache, get_datos, get_analisis)
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
# DATACLASS
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
    V10.0 - REFACTORIZADO.
    """

    # TTL por defecto (segundos)
    TTL_POR_DEFECTO = {
        # Timeframes (minutos)
        1: 60, 5: 120, 15: 180, 30: 240,
        60: 300, 240: 600,
        1440: 3600, 10080: 7200, 43200: 14400,

        # Fases y tipos de análisis
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

    # Claves que NO se persisten en disco (contienen DataFrames grandes)
    _CLAVES_NO_PERSISTIBLES_PATRONES = ('historico_', 'datos_market_')

    def __init__(
        self,
        max_size: int = 500,
        default_ttl: int = 300,
        ttls: Optional[Dict[Union[int, str], int]] = None,
        persist_dir: Optional[Path] = None,
        persist_interval: int = 60,
        modo_backtest: bool = False,
        almacen: Optional[Any] = None,
    ):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.persist_dir = Path(persist_dir) if persist_dir else Path("data/cache")
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.persist_interval = persist_interval
        self.modo_backtest = modo_backtest
        self.almacen = almacen

        self.ttls = self.TTL_POR_DEFECTO.copy()
        if ttls:
            self.ttls.update(ttls)

        self.logger = logging.getLogger('BotTrading.Cache')

        # Cache en memoria
        self._cache: Dict[Tuple, CacheEntry] = {}
        self._lock = threading.RLock()
        self._last_persist = 0.0

        # Índices
        self._indice_simbolo: Dict[str, List[Tuple]] = {}
        self._indice_fase: Dict[str, List[Tuple]] = {}

        # Stats
        self._stats = {
            'hits': 0,
            'misses': 0,
            'expired': 0,
            'evicted': 0,
            'total_entries': 0,
            'persist_count': 0,
            'load_count': 0,
        }

        # Control del hilo limpiador
        self._running = True
        self._cleaner_thread: Optional[threading.Thread] = None

        # Cargar caché persistente
        self._cargar_cache_persistente()

        # Iniciar limpieza automática
        self._iniciar_limpieza_automatica()

        self.logger.info("📦 CacheUnificado V10.0 inicializado")
        self.logger.info(f"   Max size: {max_size} | Default TTL: {default_ttl}s")
        self.logger.info(f"   Persist dir: {self.persist_dir}")

    # ============================================================
    # API PRINCIPAL: get / set (UNA SOLA DEFINICIÓN CADA UNO)
    # ============================================================

    def get(self, key: Union[Tuple, str], ttl: Optional[int] = None) -> Optional[Any]:
        """Obtiene un valor del caché. Sin logs en hot path."""
        if isinstance(key, str):
            key = (key,)

        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats['misses'] += 1
                return None

            if entry.is_expired(now):
                self._stats['expired'] += 1
                del self._cache[key]
                self._remover_indices(key)
                return None

            entry.touch()
            self._stats['hits'] += 1
            return entry.data

    def set(self, key: Union[Tuple, str], data: Any, ttl: Optional[int] = None):
        """Guarda un valor en el caché. Sin logs en hot path."""
        if data is None:
            return

        if isinstance(key, str):
            key = (key,)

        now = time.time()
        if ttl is None:
            ttl = self._obtener_ttl(key)

        # Calcular hash solo para DataFrames (para invalidación por contenido)
        hash_val = self._calcular_hash(data) if isinstance(data, pd.DataFrame) else ""

        with self._lock:
            entry = CacheEntry(
                data=data,
                timestamp=now,
                ttl=ttl,
                hash=hash_val,
                hits=0,
                last_accessed=now,
            )
            self._cache[key] = entry
            self._agregar_indices(key)
            self._stats['total_entries'] += 1

            # Cleanup si excede
            self._cleanup_if_needed()

            # Persistir solo datos de mercado a SQLite
            if len(key) == 3 and isinstance(key[1], int):
                self._guardar_en_sqlite(key[0], key[1], data)

            # Persistencia a disco (con throttling)
            self._guardar_cache_persistente()

    def get_or_compute(
        self,
        key: Union[Tuple, str],
        compute_func: Callable,
        ttl: Optional[int] = None,
        force: bool = False,
    ) -> Optional[Any]:
        """Get o compute con fallback."""
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
    # DATOS DE MERCADO
    # ============================================================

    def get_datos(self, simbolo, timeframe, n_velas, fetch_func):
        """
        Obtiene datos de mercado con caché y validación de frescura.
        Prioriza: memoria → SQLite → fetch_func → fallback antiguo.
        """
        cache_key = (simbolo, timeframe, n_velas)

        # 1. Memoria
        entry = self._cache.get(cache_key)
        if entry and not entry.is_expired(time.time()):
            df = entry.data
            if df is not None and len(df) > 0:
                # Validar frescura
                try:
                    ultima_fecha = df.index[-1]
                    if ultima_fecha.tzinfo is None:
                        ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
                    antiguedad = (datetime.now(timezone.utc) - ultima_fecha).total_seconds() / 60
                    if antiguedad < 1.0:
                        entry.touch()
                        return df
                except Exception:
                    pass

        # 2. SQLite
        if self.almacen:
            try:
                df_sqlite = self.almacen.obtener_datos_historicos(simbolo, timeframe)
                if df_sqlite is not None and not df_sqlite.empty:
                    try:
                        ultima_fecha = df_sqlite.index[-1]
                        if ultima_fecha.tzinfo is None:
                            ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
                        antiguedad = (datetime.now(timezone.utc) - ultima_fecha).total_seconds() / 60
                        if antiguedad < 2.0:
                            self.set(cache_key, df_sqlite)
                            return df_sqlite
                    except Exception:
                        pass
            except Exception:
                pass

        # 3. Fetch
        if fetch_func:
            try:
                data = fetch_func(simbolo, n_velas, timeframe)
                if data is not None and not data.empty:
                    self.set(cache_key, data)
                    return data
            except Exception as e:
                self.logger.debug(f"⚠️ fetch_func falló para {simbolo} TF{timeframe}: {e}")

        # 4. Fallback: memoria antigua
        if entry and entry.data is not None:
            return entry.data

        if self.almacen:
            try:
                return self.almacen.obtener_datos_historicos(simbolo, timeframe)
            except Exception:
                pass

        return None

    def get_datos_multi(
        self,
        simbolo: str,
        timeframes: List[int],
        n_velas: Optional[int] = None,
        fetch_func: Optional[Callable] = None,
    ) -> Dict[int, Optional[pd.DataFrame]]:
        resultados: Dict[int, Optional[pd.DataFrame]] = {}
        n_v = n_velas or 250
        for tf in timeframes:
            resultados[tf] = self.get_datos(simbolo, tf, n_v, fetch_func)
        return resultados

    def _guardar_en_sqlite(self, simbolo: str, timeframe: int, df: pd.DataFrame):
        """Guarda datos históricos en SQLite (best-effort)."""
        if self.almacen is None:
            return
        try:
            self.almacen.guardar_datos_historicos(simbolo, timeframe, df)
        except Exception as e:
            logger.debug(f"⚠️ Error guardando {simbolo} TF{timeframe}: {e}")

    # ============================================================
    # ANÁLISIS
    # ============================================================

    def get_analisis(
        self,
        simbolo: str,
        fase: str,
        df: pd.DataFrame,
        ttl: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        if df is None or df.empty:
            return None
        df_hash = self._calcular_hash(df)
        return self.get((simbolo, fase, df_hash), ttl)

    def set_analisis(
        self,
        simbolo: str,
        fase: str,
        df: pd.DataFrame,
        resultado: Dict[str, Any],
        ttl: Optional[int] = None,
    ):
        if df is None or df.empty or resultado is None:
            return
        df_hash = self._calcular_hash(df)
        self.set((simbolo, fase, df_hash), dict(resultado), ttl)

    def get_analisis_or_compute(
        self,
        simbolo: str,
        fase: str,
        df: pd.DataFrame,
        compute_func: Callable,
        ttl: Optional[int] = None,
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
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
            logger.debug("🧹 Toda la caché invalidada")
            return

        if isinstance(key, str):
            key = (key,)

        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._remover_indices(key)

    def invalidate_por_simbolo(self, simbolo: str):
        with self._lock:
            keys = self._indice_simbolo.get(simbolo, []).copy()
            for key in keys:
                self._cache.pop(key, None)
                self._remover_indices(key)

    def invalidate_por_fase(self, fase: str):
        with self._lock:
            keys = self._indice_fase.get(fase, []).copy()
            for key in keys:
                self._cache.pop(key, None)
                self._remover_indices(key)

    def clear(self):
        self.invalidate()

    # ============================================================
    # HELPERS INTERNOS
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
                if n == 0:
                    return ""
                if 'Close' in data.columns:
                    close_values = data['Close'].iloc[-n:].values
                    volume_values = (
                        data['Volume'].iloc[-n:].values if 'Volume' in data.columns else []
                    )
                    combined = close_values.tobytes() + (
                        volume_values.tobytes() if len(volume_values) > 0 else b''
                    )
                    return hashlib.md5(combined).hexdigest()[:16]
            elif isinstance(data, dict):
                return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]
            elif isinstance(data, str):
                return hashlib.md5(data.encode()).hexdigest()[:16]
        except Exception:
            pass
        return str(int(time.time()))

    def _agregar_indices(self, key: Tuple):
        if len(key) >= 1 and isinstance(key[0], str):
            simbolo = key[0]
            self._indice_simbolo.setdefault(simbolo, [])
            if key not in self._indice_simbolo[simbolo]:
                self._indice_simbolo[simbolo].append(key)

        if len(key) >= 2 and isinstance(key[1], str):
            fase = key[1]
            self._indice_fase.setdefault(fase, [])
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
        """Limpia expirados y aplica LRU si excede tamaño."""
        with self._lock:
            now = time.time()
            expired = [k for k, e in self._cache.items() if e.is_expired(now)]
            for k in expired:
                del self._cache[k]
                self._remover_indices(k)
                self._stats['expired'] += 1

            if len(self._cache) > self.max_size:
                sorted_entries = sorted(
                    self._cache.items(),
                    key=lambda x: x[1].last_accessed,
                )
                to_remove = len(self._cache) - self.max_size
                for k, _ in sorted_entries[:to_remove]:
                    del self._cache[k]
                    self._remover_indices(k)
                    self._stats['evicted'] += 1

    # ============================================================
    # PERSISTENCIA
    # ============================================================

    def _es_persistible(self, key: Tuple) -> bool:
        """Determina si una entrada debe persistirse."""
        # No persistir DataFrames de mercado (son grandes y se regeneran)
        if isinstance(key, tuple) and len(key) >= 2 and isinstance(key[1], int):
            return False
        return True

    def _cargar_cache_persistente(self):
        cache_path = self.persist_dir / "cache_unificado.pkl"
        if not cache_path.exists():
            return
        try:
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            if not isinstance(data, dict):
                return

            now = time.time()
            valid = {}
            for key, entry in data.items():
                if not isinstance(entry, CacheEntry):
                    continue
                if not entry.is_expired(now):
                    valid[key] = entry

            self._cache = valid
            self._stats['load_count'] += 1

            for key in self._cache:
                self._agregar_indices(key)

            logger.info(f"📦 Caché cargada desde disco: {len(self._cache)} entradas")
        except Exception as e:
            logger.warning(f"⚠️ Error cargando caché: {e}")

    def _guardar_cache_persistente(self):
        """Persiste SOLO entradas persistibles."""
        now = time.time()
        if now - self._last_persist < self.persist_interval:
            return

        try:
            with self._lock:
                # Filtrar solo persistibles
                persistible = {
                    k: v for k, v in self._cache.items()
                    if self._es_persistible(k)
                }

            cache_path = self.persist_dir / "cache_unificado.pkl"
            temp_path = cache_path.with_suffix('.tmp')
            with open(temp_path, 'wb') as f:
                pickle.dump(persistible, f)
            temp_path.replace(cache_path)

            self._last_persist = now
            self._stats['persist_count'] += 1
        except Exception as e:
            logger.debug(f"⚠️ Error guardando caché: {e}")

    # ============================================================
    # LIMPIEZA AUTOMÁTICA
    # ============================================================

    def _iniciar_limpieza_automatica(self):
        """Hilo daemon que limpia expirados cada 5 min."""
        def loop():
            while self._running:
                try:
                    # Sleep en pequeños pasos para poder detenerse
                    for _ in range(300):
                        if not self._running:
                            return
                        time.sleep(1)
                    with self._lock:
                        now = time.time()
                        expired = [k for k, e in self._cache.items() if e.is_expired(now)]
                        for k in expired:
                            del self._cache[k]
                            self._remover_indices(k)
                            self._stats['expired'] += 1
                except Exception:
                    pass

        self._cleaner_thread = threading.Thread(
            target=loop, daemon=True, name="CacheCleaner"
        )
        self._cleaner_thread.start()

    def stop(self):
        """Detiene el hilo de limpieza (para shutdown limpio)."""
        self._running = False
        if self._cleaner_thread and self._cleaner_thread.is_alive():
            self._cleaner_thread.join(timeout=2.0)
        self._guardar_cache_persistente()
        logger.debug("🛑 CacheUnificado detenido")

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

def create_cache_unificado(
    config: Optional[Any] = None,
    persist_dir: Optional[Path] = None,
    modo_backtest: bool = False,
    almacen: Optional[Any] = None,
) -> CacheUnificado:
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
        modo_backtest=modo_backtest,
        almacen=almacen,
    )


# ============================================================
# ALIAS DE COMPATIBILIDAD
# ============================================================

DataCache = CacheUnificado
AnalysisCache = CacheUnificado


def create_data_cache_with_config(config, **kwargs):
    return create_cache_unificado(config, **kwargs)


def create_analysis_cache_with_config(config, **kwargs):
    return create_cache_unificado(config, **kwargs)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import numpy as np

    print("🧪 Probando CacheUnificado V10.0...")

    cache = CacheUnificado(max_size=10, modo_backtest=True)

    # Test get/set básico
    df = pd.DataFrame({
        'Close': np.random.randn(100) + 100,
        'Volume': np.random.randint(100, 1000, 100),
    })
    cache.set(('EURUSD', 60, 100), df)
    r = cache.get(('EURUSD', 60, 100))
    assert r is not None, "❌ Falló get de datos"
    print("✅ get/set de datos")

    # Test análisis
    cache.set_analisis('EURUSD', 'fase1', df, {'score': 75})
    r = cache.get_analisis('EURUSD', 'fase1', df)
    assert r is not None and r.get('score') == 75, "❌ Falló análisis"
    print("✅ get/set análisis")

    # Stats
    print(f"📊 Stats: {cache.get_stats()['hits']} hits")

    cache.stop()
    print("\n✅ Prueba completada")