#!/usr/bin/env python3
"""
utils/logger_latencia.py (V9.0 - CORREGIDO)
Módulo de medición de latencia para funciones críticas del bot.
"""

import time
import logging
import os
import functools
import asyncio
import json
import threading
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List, Union
from collections import defaultdict
from datetime import datetime, timezone

# ============================================================
# IMPORTAR LOGGER PERSISTENTE
# ============================================================

try:
    from utils.logger_persistente import LoggerPersistente
    _logger_persistente = LoggerPersistente()
    logger = _logger_persistente.get_logger()
except ImportError:
    logger = logging.getLogger('BotTrading.Latencia')

try:
    from config.settings import Config
except ImportError:
    Config = None


# ============================================================
# CONFIGURACIÓN
# ============================================================

DISABLE_LATENCY_LOG = os.getenv('DISABLE_LATENCY_LOG', 'false').lower() in ('true', '1', 'yes')
LATENCY_LOG_LEVEL = os.getenv('LATENCY_LOG_LEVEL', 'INFO')
LATENCY_PERSIST_DIR = os.getenv('LATENCY_PERSIST_DIR', 'data/latency')
LATENCY_MAX_RECORDS = int(os.getenv('LATENCY_MAX_RECORDS', '10000'))

LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
}

LOG_LEVEL = LEVEL_MAP.get(LATENCY_LOG_LEVEL, logging.INFO)

UMBRALES_WARNING = {
    'MT5': 100,
    'REST': 200,
    'CACHE': 10,
    'ANALISIS': 50,
    'DB': 50,
    'SISTEMA': 100,
    'PIPELINE': 50,
    'SNIPER': 50,
    'DEFAULT': 100,
}


# ============================================================
# ESTADÍSTICAS DE LATENCIA
# ============================================================

class LatencyStats:
    """Almacena y calcula estadísticas de latencia."""
    
    def __init__(self, persist_dir: Optional[Path] = None, max_records: int = 10000):
        self._data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'count': 0,
            'total_ms': 0.0,
            'min_ms': float('inf'),
            'max_ms': 0.0,
            'sum_squared': 0.0,
            'last_ms': 0.0,
            'last_updated': None,
            'history': [],
        })
        self._lock = threading.RLock()
        self.persist_dir = Path(persist_dir) if persist_dir else Path("data/latency")
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.max_records = max_records
        self._ultima_persistencia = 0
        self._persistencia_intervalo = 60
    
    def add_measurement(self, metrica: str, latencia_ms: float, plataforma: str):
        """Añade una medición."""
        with self._lock:
            data = self._data[metrica]
            data['count'] += 1
            data['total_ms'] += latencia_ms
            data['min_ms'] = min(data['min_ms'], latencia_ms)
            data['max_ms'] = max(data['max_ms'], latencia_ms)
            data['sum_squared'] += latencia_ms ** 2
            data['last_ms'] = latencia_ms
            data['last_updated'] = datetime.now(timezone.utc).isoformat()
            
            data['history'].append({
                'timestamp': data['last_updated'],
                'ms': latencia_ms,
                'plataforma': plataforma
            })
            if len(data['history']) > 100:
                data['history'] = data['history'][-100:]
            
            self._guardar_datos()
    
    def _guardar_datos(self):
        """Guarda datos en disco."""
        ahora = time.time()
        if ahora - self._ultima_persistencia < self._persistencia_intervalo:
            return
        
        try:
            archivo = self.persist_dir / "latency_stats.json"
            with self._lock:
                data = {}
                for metrica, stats in self._data.items():
                    data[metrica] = {
                        'count': stats['count'],
                        'total_ms': stats['total_ms'],
                        'min_ms': stats['min_ms'],
                        'max_ms': stats['max_ms'],
                        'sum_squared': stats['sum_squared'],
                        'last_ms': stats['last_ms'],
                        'last_updated': stats['last_updated'],
                        'history': stats['history'][-100:],
                    }
            
            with open(archivo, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            self._ultima_persistencia = ahora
        except Exception as e:
            logger.debug(f"Error guardando estadísticas: {e}")
    
    def get_stats(self, metrica: str) -> Optional[Dict]:
        """Obtiene estadísticas para una métrica."""
        with self._lock:
            if metrica not in self._data:
                return None
            data = self._data[metrica]
            if data['count'] == 0:
                return None
            
            mean = data['total_ms'] / data['count']
            variance = (data['sum_squared'] / data['count']) - (mean ** 2)
            std_dev = variance ** 0.5 if variance > 0 else 0
            
            return {
                'count': data['count'],
                'mean_ms': mean,
                'min_ms': data['min_ms'],
                'max_ms': data['max_ms'],
                'std_dev_ms': std_dev,
                'last_ms': data['last_ms'],
                'last_updated': data['last_updated'],
                'history': data['history'][-20:],
            }
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Obtiene estadísticas de todas las métricas."""
        with self._lock:
            return {m: self.get_stats(m) for m in self._data if self.get_stats(m) is not None}
    
    def get_summary(self) -> Dict[str, Any]:
        """Obtiene un resumen."""
        stats = self.get_all_stats()
        total_measurements = sum(s['count'] for s in stats.values() if s)
        avg_latency = sum(s['mean_ms'] for s in stats.values() if s) / len(stats) if stats else 0
        
        slowest = None
        slowest_latency = 0
        for metrica, s in stats.items():
            if s and s['mean_ms'] > slowest_latency:
                slowest_latency = s['mean_ms']
                slowest = metrica
        
        return {
            'total_metrics': len(stats),
            'total_measurements': total_measurements,
            'avg_latency_ms': avg_latency,
            'slowest_metric': slowest,
            'slowest_latency_ms': slowest_latency,
        }
    
    def reset(self):
        """Reinicia estadísticas."""
        with self._lock:
            self._data.clear()
    
    def to_dict(self) -> Dict:
        """Exporta a diccionario."""
        return self.get_all_stats()


# Instancia global
_stats = LatencyStats()


# ============================================================
# DETECCIÓN DE PLATAFORMA
# ============================================================

def _get_plataforma(instancia: Any, class_name: Optional[str] = None) -> str:
    """Determina la plataforma."""
    if instancia is None:
        if class_name:
            if "ConectorPepperstone" in class_name:
                return "MT5"
            elif "ConectorHeadless" in class_name:
                return "REST"
            elif "DataCache" in class_name or "AnalysisCache" in class_name:
                return "CACHE"
            elif "AnalisisPorCapas" in class_name:
                return "ANALISIS"
            elif "HorarioMercado" in class_name:
                return "SISTEMA"
            elif "AlmacenamientoSQLite" in class_name:
                return "DB"
            elif "MLOptimizer" in class_name:
                return "ML"
        return "SISTEMA"
    
    class_name = instancia.__class__.__name__
    if "ConectorPepperstone" in class_name:
        return "MT5"
    elif "ConectorHeadless" in class_name:
        return "REST"
    elif "DataCache" in class_name or "AnalysisCache" in class_name:
        return "CACHE"
    elif "AnalisisPorCapas" in class_name or "AnalisisTecnico" in class_name:
        return "ANALISIS"
    elif "AnalisisPorFase" in class_name:
        return "ANALISIS"
    elif "PipelineOportunidades" in class_name:
        return "PIPELINE"
    elif "SniperChecklist" in class_name:
        return "SNIPER"
    elif "AlmacenamientoSQLite" in class_name:
        return "DB"
    elif "HorarioMercado" in class_name or "MarketRegimeFilter" in class_name:
        return "SISTEMA"
    elif "MLOptimizer" in class_name:
        return "ML"
    
    return "MT5"


def _obtener_umbral_warning(plataforma: str) -> float:
    """Obtiene el umbral de advertencia."""
    return UMBRALES_WARNING.get(plataforma, UMBRALES_WARNING['DEFAULT'])


# ============================================================
# DECORADOR PRINCIPAL - CORREGIDO
# ============================================================

def medir_latencia(
    metrica_nombre: str,
    plataforma: Optional[str] = None,
    nivel_log: Union[int, str] = logging.INFO,
    desactivar: bool = False,
    log_excepciones: bool = True,
    guardar_estadisticas: bool = True,
    umbral_warning_ms: Optional[float] = None,
):
    """
    Decorador para medir la latencia de funciones críticas.
    
    Args:
        metrica_nombre: Nombre de la métrica
        plataforma: Plataforma (si no se especifica, se autodetecta)
        nivel_log: Nivel de log (INFO, DEBUG, etc.)
        desactivar: Desactiva la medición
        log_excepciones: Logea excepciones
        guardar_estadisticas: Guarda estadísticas agregadas
        umbral_warning_ms: Si se supera, logea como WARNING
    """
    # Convertir nivel a int si es string
    if isinstance(nivel_log, str):
        nivel_log = LEVEL_MAP.get(nivel_log.upper(), logging.INFO)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper_sync(*args, **kwargs):
            if DISABLE_LATENCY_LOG or desactivar:
                return func(*args, **kwargs)

            t_inicio = time.perf_counter_ns()
            excepcion = None
            try:
                return func(*args, **kwargs)
            except Exception as e:
                excepcion = e
                raise
            finally:
                t_fin = time.perf_counter_ns()
                latencia_ms = (t_fin - t_inicio) / 1_000_000
                
                # Determinar plataforma
                if plataforma:
                    plat = plataforma
                else:
                    instancia = args[0] if args and hasattr(args[0], '__class__') else None
                    plat = _get_plataforma(instancia, func.__qualname__)
                
                # Guardar estadísticas
                if guardar_estadisticas:
                    _stats.add_measurement(metrica_nombre, latencia_ms, plat)
                
                # Determinar nivel de log
                nivel = nivel_log
                # Obtener umbral si no se proporcionó
                if umbral_warning_ms is None:
                    umbral = _obtener_umbral_warning(plat)
                else:
                    umbral = umbral_warning_ms
                
                if latencia_ms > umbral:
                    nivel = logging.WARNING
                
                mensaje = f"[{plat}] [{metrica_nombre}] -> {latencia_ms:.2f} ms"
                
                if excepcion is not None and log_excepciones:
                    logger.error(f"{mensaje} (EXCEPCIÓN: {type(excepcion).__name__}: {excepcion})")
                else:
                    logger.log(nivel, mensaje)
        
        @functools.wraps(func)
        async def wrapper_async(*args, **kwargs):
            if DISABLE_LATENCY_LOG or desactivar:
                return await func(*args, **kwargs)

            t_inicio = time.perf_counter_ns()
            excepcion = None
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                excepcion = e
                raise
            finally:
                t_fin = time.perf_counter_ns()
                latencia_ms = (t_fin - t_inicio) / 1_000_000
                
                if plataforma:
                    plat = plataforma
                else:
                    instancia = args[0] if args and hasattr(args[0], '__class__') else None
                    plat = _get_plataforma(instancia, func.__qualname__)
                
                if guardar_estadisticas:
                    _stats.add_measurement(metrica_nombre, latencia_ms, plat)
                
                nivel = nivel_log
                if umbral_warning_ms is None:
                    umbral = _obtener_umbral_warning(plat)
                else:
                    umbral = umbral_warning_ms
                
                if latencia_ms > umbral:
                    nivel = logging.WARNING
                
                mensaje = f"[{plat}] [{metrica_nombre}] -> {latencia_ms:.2f} ms"
                
                if excepcion is not None and log_excepciones:
                    logger.error(f"{mensaje} (EXCEPCIÓN: {type(excepcion).__name__}: {excepcion})")
                else:
                    logger.log(nivel, mensaje)

        if asyncio.iscoroutinefunction(func):
            return wrapper_async
        else:
            return wrapper_sync

    return decorator


# ============================================================
# CONTEXT MANAGER
# ============================================================

class TemporizadorContexto:
    """Context manager para medir latencia de bloques de código."""
    
    def __init__(self, metrica_nombre: str, plataforma: Optional[str] = None,
                 nivel_log: Union[int, str] = logging.INFO,
                 log_excepciones: bool = True,
                 guardar_estadisticas: bool = True,
                 umbral_warning_ms: Optional[float] = None):
        self.metrica_nombre = metrica_nombre
        self.plataforma = plataforma or "SISTEMA"
        self.nivel_log = nivel_log if isinstance(nivel_log, int) else LEVEL_MAP.get(str(nivel_log).upper(), logging.INFO)
        self.log_excepciones = log_excepciones
        self.guardar_estadisticas = guardar_estadisticas
        self.umbral_warning_ms = umbral_warning_ms or _obtener_umbral_warning(self.plataforma)
        self._start = None

    def __enter__(self):
        if not DISABLE_LATENCY_LOG:
            self._start = time.perf_counter_ns()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._start is None:
            return
        
        latencia_ms = (time.perf_counter_ns() - self._start) / 1_000_000
        
        if self.guardar_estadisticas:
            _stats.add_measurement(self.metrica_nombre, latencia_ms, self.plataforma)
        
        nivel = self.nivel_log
        if latencia_ms > self.umbral_warning_ms:
            nivel = logging.WARNING
        
        mensaje = f"[{self.plataforma}] [{self.metrica_nombre}] -> Bloque: {latencia_ms:.2f} ms"
        
        if exc_type is not None and self.log_excepciones:
            logger.error(f"{mensaje} (EXCEPCIÓN: {exc_type.__name__}: {exc_val})")
        else:
            logger.log(nivel, mensaje)


# ============================================================
# FUNCIONES DE UTILIDAD
# ============================================================

def get_latency_stats(metrica: Optional[str] = None) -> Union[Dict, Optional[Dict]]:
    """Obtiene estadísticas de latencia."""
    if metrica:
        return _stats.get_stats(metrica)
    return _stats.get_all_stats()


def get_latency_summary() -> Dict[str, Any]:
    """Obtiene un resumen."""
    return _stats.get_summary()


def reset_latency_stats():
    """Reinicia estadísticas."""
    _stats.reset()
    logger.info("🧹 Estadísticas de latencia reiniciadas")


def export_latency_stats(ruta: Optional[Path] = None) -> bool:
    """Exporta estadísticas a JSON."""
    try:
        if ruta is None:
            ruta = Path("data/latency") / f"latency_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(_stats.to_dict(), f, indent=2, default=str)
        
        logger.info(f"📊 Estadísticas exportadas a {ruta}")
        return True
    except Exception as e:
        logger.error(f"❌ Error exportando: {e}")
        return False


# ============================================================
# DECORADORES ESPECÍFICOS
# ============================================================

def medir_mt5(metrica_nombre: str, **kwargs):
    """Decorador para MT5."""
    return medir_latencia(metrica_nombre, plataforma="MT5", **kwargs)


def medir_cache(metrica_nombre: str, **kwargs):
    """Decorador para caché."""
    return medir_latencia(metrica_nombre, plataforma="CACHE", **kwargs)


def medir_analisis(metrica_nombre: str, **kwargs):
    """Decorador para análisis."""
    return medir_latencia(metrica_nombre, plataforma="ANALISIS", **kwargs)


def medir_db(metrica_nombre: str, **kwargs):
    """Decorador para base de datos."""
    return medir_latencia(metrica_nombre, plataforma="DB", **kwargs)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando logger_latencia...")
    
    @medir_latencia("test_funcion", plataforma="TEST", umbral_warning_ms=10)
    def test_funcion():
        time.sleep(0.015)
    
    test_funcion()
    
    print("📊 Estadísticas:")
    import json
    print(json.dumps(get_latency_stats(), indent=2, default=str))
    
    print("\n✅ Prueba completada")