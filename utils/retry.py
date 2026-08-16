#!/usr/bin/env python3
"""
utils/retry.py (V9.0 - REFACTORIZADO)
Decoradores y utilidades para reintentar operaciones con backoff exponencial.

RESPONSABILIDADES:
- Reintentar operaciones que fallan temporalmente
- Backoff exponencial con jitter
- Logging de intentos fallidos
- Métricas de reintentos

MEJORAS V9.0:
- Métricas de reintentos (contadores)
- Excepciones específicas por plataforma
- Backoff personalizable por tipo
- Integración con umbrales centralizados
- Decorador unificado `@retry`
- Soporte para condiciones de retry personalizadas
"""

import sqlite3
import time
import random
import functools
import asyncio
import threading
from typing import Callable, Type, Tuple, Optional, Any, Union, Dict, List
from collections import defaultdict

# ============================================================
# LOGGING V9.0
# ============================================================

try:
    from utils.logger_persistente import LoggerPersistente
    _logger = LoggerPersistente()
    logger = _logger.get_logger()
except ImportError:
    import logging
    logger = logging.getLogger('BotTrading.Retry')

try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None


# ============================================================
# CONFIGURACIÓN
# ============================================================

# Configuración por defecto
CONFIG_POR_DEFECTO = {
    'max_retries': 3,
    'base_delay': 0.2,
    'max_delay': 5.0,
    'jitter': True,
    'log_attempts': True,
}

# Configuración por tipo de operación
CONFIG_POR_TIPO = {
    'mt5': {
        'max_retries': 5,
        'base_delay': 0.5,
        'max_delay': 10.0,
        'jitter': True,
        'log_attempts': True,
    },
    'http': {
        'max_retries': 3,
        'base_delay': 1.0,
        'max_delay': 10.0,
        'jitter': True,
        'log_attempts': True,
    },
    'db': {
        'max_retries': 3,
        'base_delay': 0.1,
        'max_delay': 2.0,
        'jitter': True,
        'log_attempts': True,
    },
    'cache': {
        'max_retries': 2,
        'base_delay': 0.05,
        'max_delay': 0.5,
        'jitter': False,
        'log_attempts': False,
    },
    'analisis': {
        'max_retries': 2,
        'base_delay': 0.1,
        'max_delay': 1.0,
        'jitter': True,
        'log_attempts': True,
    },
}

# Excepciones específicas por plataforma
EXCEPCIONES_MT5 = (ConnectionError, TimeoutError, OSError, RuntimeError)
EXCEPCIONES_HTTP = (ConnectionError, TimeoutError, OSError)
EXCEPCIONES_DB = (sqlite3.OperationalError, sqlite3.IntegrityError) if 'sqlite3' in dir() else (Exception,)


# ============================================================
# MÉTRICAS DE REINTENTOS
# ============================================================

class RetryMetrics:
    """
    Métricas de reintentos para monitoreo.
    Thread-safe.
    """
    
    def __init__(self):
        self._metrics = defaultdict(lambda: {
            'total_attempts': 0,
            'successful_attempts': 0,
            'failed_attempts': 0,
            'retries': 0,
            'total_time_ms': 0.0,
        })
        self._lock = threading.RLock()
    
    def record_attempt(self, operation: str, success: bool, retries: int, time_ms: float):
        """
        Registra un intento de operación.
        
        Args:
            operation: Nombre de la operación
            success: Si fue exitosa
            retries: Número de reintentos realizados
            time_ms: Tiempo total en milisegundos
        """
        with self._lock:
            data = self._metrics[operation]
            data['total_attempts'] += 1
            data['total_time_ms'] += time_ms
            
            if success:
                data['successful_attempts'] += 1
            else:
                data['failed_attempts'] += 1
            
            data['retries'] += retries
    
    def get_stats(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """
        Obtiene estadísticas de reintentos.
        
        Args:
            operation: Nombre de la operación (None = todas)
        
        Returns:
            Estadísticas
        """
        with self._lock:
            if operation:
                return self._metrics.get(operation, {}).copy()
            
            return {
                op: data.copy()
                for op, data in self._metrics.items()
            }
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Obtiene un resumen de todas las métricas.
        
        Returns:
            Resumen
        """
        with self._lock:
            total_attempts = sum(d['total_attempts'] for d in self._metrics.values())
            total_success = sum(d['successful_attempts'] for d in self._metrics.values())
            total_retries = sum(d['retries'] for d in self._metrics.values())
            total_time = sum(d['total_time_ms'] for d in self._metrics.values())
            
            return {
                'total_attempts': total_attempts,
                'total_success': total_success,
                'total_failed': total_attempts - total_success,
                'total_retries': total_retries,
                'total_time_ms': total_time,
                'success_rate': (total_success / total_attempts * 100) if total_attempts > 0 else 0,
                'avg_retries_per_attempt': (total_retries / total_attempts) if total_attempts > 0 else 0,
            }
    
    def reset(self):
        """Reinicia todas las métricas."""
        with self._lock:
            self._metrics.clear()


# Instancia global de métricas
_metrics = RetryMetrics()


# ============================================================
# FUNCIONES DE UTILIDAD
# ============================================================

def _calcular_delay(attempt: int, base_delay: float, max_delay: float, jitter: bool) -> float:
    """
    Calcula el delay para un reintento con backoff exponencial.
    
    Args:
        attempt: Número de intento (1-based)
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        jitter: Si se debe agregar jitter
    
    Returns:
        Delay en segundos
    """
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    if jitter:
        # Jitter aleatorio entre 0 y 10% del delay
        jitter_amount = random.uniform(0, delay * 0.1)
        delay += jitter_amount
    return delay


def _debe_reintentar(exc: Exception, exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]]) -> bool:
    """
    Determina si se debe reintentar basado en la excepción.
    
    Args:
        exc: Excepción capturada
        exceptions: Excepciones a reintentar
    
    Returns:
        True si se debe reintentar
    """
    if isinstance(exceptions, tuple):
        return isinstance(exc, exceptions)
    return isinstance(exc, exceptions)


# ============================================================
# DECORADORES
# ============================================================

def retry_mt5(
    max_retries: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,),
    log_attempts: bool = True,
    jitter: bool = True,
    operation_name: Optional[str] = None,
):
    """
    Decorador para reintentar operaciones MT5.
    
    Args:
        max_retries: Número máximo de reintentos
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        exceptions: Excepciones a reintentar
        log_attempts: Logear intentos fallidos
        jitter: Agregar jitter aleatorio
        operation_name: Nombre de la operación (para métricas)
    """
    return retry(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exceptions=exceptions,
        log_attempts=log_attempts,
        jitter=jitter,
        operation_name=operation_name or 'mt5'
    )


def retry_http(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,),
    log_attempts: bool = True,
    jitter: bool = True,
    operation_name: Optional[str] = None,
):
    """
    Decorador para reintentar operaciones HTTP.
    
    Args:
        max_retries: Número máximo de reintentos
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        exceptions: Excepciones a reintentar
        log_attempts: Logear intentos fallidos
        jitter: Agregar jitter aleatorio
        operation_name: Nombre de la operación (para métricas)
    """
    return retry(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exceptions=exceptions,
        log_attempts=log_attempts,
        jitter=jitter,
        operation_name=operation_name or 'http'
    )


def retry_async(
    max_retries: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,),
    log_attempts: bool = True,
    jitter: bool = True,
    operation_name: Optional[str] = None,
):
    """
    Decorador para reintentar operaciones asíncronas.
    
    Args:
        max_retries: Número máximo de reintentos
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        exceptions: Excepciones a reintentar
        log_attempts: Logear intentos fallidos
        jitter: Agregar jitter aleatorio
        operation_name: Nombre de la operación (para métricas)
    """
    return retry(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exceptions=exceptions,
        log_attempts=log_attempts,
        jitter=jitter,
        operation_name=operation_name or 'async',
        _async=True
    )


def retry(
    max_retries: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,),
    log_attempts: bool = True,
    jitter: bool = True,
    operation_name: Optional[str] = None,
    _async: bool = False,
):
    """
    Decorador genérico para reintentar operaciones.
    
    Args:
        max_retries: Número máximo de reintentos
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        exceptions: Excepciones a reintentar
        log_attempts: Logear intentos fallidos
        jitter: Agregar jitter aleatorio
        operation_name: Nombre de la operación (para métricas)
        _async: Si la función es asíncrona
    
    Returns:
        Decorador
    """
    def decorator(func: Callable) -> Callable:
        nombre_operacion = operation_name or func.__name__
        
        if _async or asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def wrapper_async(*args, **kwargs):
                last_exception = None
                start_time = time.perf_counter()
                retries_used = 0
                
                for attempt in range(1, max_retries + 2):  # +1 para el intento inicial
                    try:
                        result = await func(*args, **kwargs)
                        
                        # Registrar éxito
                        elapsed_ms = (time.perf_counter() - start_time) * 1000
                        _metrics.record_attempt(nombre_operacion, True, retries_used, elapsed_ms)
                        
                        return result
                        
                    except exceptions as e:
                        last_exception = e
                        retries_used = attempt - 1
                        
                        if attempt == max_retries + 1:
                            # Último intento fallido
                            elapsed_ms = (time.perf_counter() - start_time) * 1000
                            _metrics.record_attempt(nombre_operacion, False, retries_used, elapsed_ms)
                            logger.error(f"Fallo definitivo en {func.__name__} tras {max_retries} reintentos: {e}")
                            raise
                        
                        delay = _calcular_delay(attempt, base_delay, max_delay, jitter)
                        
                        if log_attempts:
                            logger.warning(
                                f"Reintento {attempt}/{max_retries} para {func.__name__} "
                                f"en {delay:.2f}s: {e}"
                            )
                        
                        await asyncio.sleep(delay)
                
                raise last_exception
            
            return wrapper_async
        
        else:
            @functools.wraps(func)
            def wrapper_sync(*args, **kwargs):
                last_exception = None
                start_time = time.perf_counter()
                retries_used = 0
                
                for attempt in range(1, max_retries + 2):  # +1 para el intento inicial
                    try:
                        result = func(*args, **kwargs)
                        
                        # Registrar éxito
                        elapsed_ms = (time.perf_counter() - start_time) * 1000
                        _metrics.record_attempt(nombre_operacion, True, retries_used, elapsed_ms)
                        
                        return result
                        
                    except exceptions as e:
                        last_exception = e
                        retries_used = attempt - 1
                        
                        if attempt == max_retries + 1:
                            # Último intento fallido
                            elapsed_ms = (time.perf_counter() - start_time) * 1000
                            _metrics.record_attempt(nombre_operacion, False, retries_used, elapsed_ms)
                            logger.error(f"Fallo definitivo en {func.__name__} tras {max_retries} reintentos: {e}")
                            raise
                        
                        delay = _calcular_delay(attempt, base_delay, max_delay, jitter)
                        
                        if log_attempts:
                            logger.warning(
                                f"Reintento {attempt}/{max_retries} para {func.__name__} "
                                f"en {delay:.2f}s: {e}"
                            )
                        
                        time.sleep(delay)
                
                raise last_exception
            
            return wrapper_sync
    
    return decorator


# ============================================================
# FUNCIONES DE LLAMADA CON REINTENTOS
# ============================================================

def retry_call(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,),
    retry_if_result_none: bool = False,
    retry_if: Optional[Callable[[Any], bool]] = None,
    log_attempts: bool = True,
    jitter: bool = True,
    operation_name: Optional[str] = None,
    **kwargs
) -> Any:
    """
    Llama a una función con reintentos.
    
    Args:
        func: Función a llamar
        *args: Argumentos posicionales
        max_retries: Número máximo de reintentos
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        exceptions: Excepciones a reintentar
        retry_if_result_none: Reintentar si el resultado es None
        retry_if: Función que determina si se debe reintentar basado en el resultado
        log_attempts: Logear intentos fallidos
        jitter: Agregar jitter aleatorio
        operation_name: Nombre de la operación (para métricas)
        **kwargs: Argumentos de palabra clave
    
    Returns:
        Resultado de la función
    """
    nombre_operacion = operation_name or func.__name__
    last_exception = None
    start_time = time.perf_counter()
    retries_used = 0
    
    for attempt in range(1, max_retries + 2):
        try:
            result = func(*args, **kwargs)
            
            # Verificar si se debe reintentar por resultado
            if retry_if_result_none and result is None:
                raise ValueError("Resultado None, reintentando")
            
            if retry_if is not None and retry_if(result):
                raise ValueError(f"Resultado no cumple condición: {result}")
            
            # Éxito
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _metrics.record_attempt(nombre_operacion, True, retries_used, elapsed_ms)
            return result
            
        except exceptions as e:
            last_exception = e
            retries_used = attempt - 1
            
            if attempt == max_retries + 1:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                _metrics.record_attempt(nombre_operacion, False, retries_used, elapsed_ms)
                logger.error(f"Fallo definitivo en {func.__name__} tras {max_retries} reintentos: {e}")
                raise
            
            delay = _calcular_delay(attempt, base_delay, max_delay, jitter)
            
            if log_attempts:
                logger.warning(
                    f"Reintento {attempt}/{max_retries} para {func.__name__} "
                    f"en {delay:.2f}s: {e}"
                )
            
            time.sleep(delay)
    
    raise last_exception


async def retry_call_async(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,),
    retry_if_result_none: bool = False,
    retry_if: Optional[Callable[[Any], bool]] = None,
    log_attempts: bool = True,
    jitter: bool = True,
    operation_name: Optional[str] = None,
    **kwargs
) -> Any:
    """
    Llama a una función asíncrona con reintentos.
    
    Args:
        func: Función asíncrona a llamar
        *args: Argumentos posicionales
        max_retries: Número máximo de reintentos
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        exceptions: Excepciones a reintentar
        retry_if_result_none: Reintentar si el resultado es None
        retry_if: Función que determina si se debe reintentar basado en el resultado
        log_attempts: Logear intentos fallidos
        jitter: Agregar jitter aleatorio
        operation_name: Nombre de la operación (para métricas)
        **kwargs: Argumentos de palabra clave
    
    Returns:
        Resultado de la función
    """
    nombre_operacion = operation_name or func.__name__
    last_exception = None
    start_time = time.perf_counter()
    retries_used = 0
    
    for attempt in range(1, max_retries + 2):
        try:
            result = await func(*args, **kwargs)
            
            if retry_if_result_none and result is None:
                raise ValueError("Resultado None, reintentando")
            
            if retry_if is not None and retry_if(result):
                raise ValueError(f"Resultado no cumple condición: {result}")
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _metrics.record_attempt(nombre_operacion, True, retries_used, elapsed_ms)
            return result
            
        except exceptions as e:
            last_exception = e
            retries_used = attempt - 1
            
            if attempt == max_retries + 1:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                _metrics.record_attempt(nombre_operacion, False, retries_used, elapsed_ms)
                logger.error(f"Fallo definitivo en {func.__name__} tras {max_retries} reintentos: {e}")
                raise
            
            delay = _calcular_delay(attempt, base_delay, max_delay, jitter)
            
            if log_attempts:
                logger.warning(
                    f"Reintento asíncrono {attempt}/{max_retries} para {func.__name__} "
                    f"en {delay:.2f}s: {e}"
                )
            
            await asyncio.sleep(delay)
    
    raise last_exception


# ============================================================
# FUNCIONES DE MÉTRICAS
# ============================================================

def get_retry_metrics(operation: Optional[str] = None) -> Dict[str, Any]:
    """
    Obtiene métricas de reintentos.
    
    Args:
        operation: Nombre de la operación (None = todas)
    
    Returns:
        Métricas
    """
    return _metrics.get_stats(operation)


def get_retry_summary() -> Dict[str, Any]:
    """
    Obtiene un resumen de todas las métricas de reintentos.
    
    Returns:
        Resumen
    """
    return _metrics.get_summary()


def reset_retry_metrics():
    """Reinicia todas las métricas de reintentos."""
    _metrics.reset()
    logger.info("🧹 Métricas de reintentos reiniciadas")


# ============================================================
# ALIAS DE COMPATIBILIDAD
# ============================================================

reintento_http = retry_http


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando módulo de reintentos...")
    
    # Ejemplo de función que falla
    intentos = 0
    
    @retry(max_retries=3, base_delay=0.1, log_attempts=True)
    def funcion_fallona():
        global intentos
        intentos += 1
        print(f"Intento {intentos}")
        if intentos < 3:
            raise ConnectionError("Error de conexión simulado")
        return "Éxito!"
    
    try:
        resultado = funcion_fallona()
        print(f"Resultado: {resultado}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Mostrar métricas
    print("\n📊 Métricas de reintentos:")
    import json
    print(json.dumps(get_retry_summary(), indent=2, default=str))
    
    # Probar retry_call
    print("\n🧪 Probando retry_call...")
    
    def funcion_simple():
        return "OK"
    
    resultado = retry_call(funcion_simple, max_retries=2)
    print(f"Resultado: {resultado}")
    
    # Probar condición de retry
    print("\n🧪 Probando retry_if...")
    
    def verificar_resultado(r):
        return r is None
    
    def funcion_que_falla():
        return None
    
    try:
        resultado = retry_call(
            funcion_que_falla,
            max_retries=2,
            retry_if=verificar_resultado,
            log_attempts=True
        )
        print(f"Resultado: {resultado}")
    except Exception as e:
        print(f"Error esperado: {e}")
    
    print("\n✅ Prueba completada")