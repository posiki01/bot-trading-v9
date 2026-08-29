#!/usr/bin/env python3
"""
mt5/conector_mt5.py (V9.4 - CORREGIDO DEFINITIVO)
Conector para MetaTrader 5 con soporte para Pepperstone y modo Headless.

CORRECCIONES V9.4:
- Conversión de time a datetime con zona horaria UTC (tz-aware)
- Normalización de índices de DataFrame a UTC antes de combinar
- Manejo robusto de fechas en copy_rates_range
- VALIDACIÓN DE MERCADO CERRADO antes de descargar datos
"""

import time
import logging
from collections import deque
from threading import Lock
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
import concurrent.futures
import functools
import MetaTrader5 as mt5
import pandas as pd

from config.settings import Config


# ============================================================
# DECORADOR DE RETRY INTERNO
# ============================================================

def retry_mt5(max_retries=3, base_delay=0.5, max_delay=16.0, exceptions=(Exception,)):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _last_exc = None
            delay = base_delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    _last_exc = e
                    if attempt == max_retries:
                        logging.getLogger('BotTrading.MT5').error(
                            f"❌ {func.__name__} falló después de {max_retries} reintentos: {e}"
                        )
                        raise
                    logging.getLogger('BotTrading.MT5').warning(
                        f"⏳ {func.__name__} falló (intento {attempt+1}/{max_retries}), "
                        f"reintentando en {delay:.2f}s..."
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, max_delay)
            raise _last_exc
        return wrapper
    return decorator


# ============================================================
# CLASE BASE
# ============================================================

class ConectorBase(ABC):
    """Clase base para conectores de trading."""
    
    @abstractmethod
    def conectar(self) -> bool:
        pass

    @abstractmethod
    def verificar_conexion(self) -> bool:
        pass

    @abstractmethod
    def enviar_orden(self, simbolo, tipo, volumen, sl=0, tp=0, comentario=""):
        pass

    @abstractmethod
    def obtener_datos(self, simbolo, n_velas=100, timeframe=None):
        pass

    @abstractmethod
    def obtener_precio(self, simbolo):
        pass

    @abstractmethod
    def obtener_posiciones(self, simbolo: Optional[str] = None, force: bool = False):
        pass

    @abstractmethod
    def cerrar_posicion(self, ticket):
        pass

    @abstractmethod
    def cerrar_parcial(self, ticket, volumen_a_cerrar):
        pass

    @abstractmethod
    def modificar_sl(self, ticket, nuevo_sl):
        pass

    @abstractmethod
    def tomar_captura(self, simbolo, ruta_archivo, timeframe=None):
        pass

    @abstractmethod
    def obtener_detalle_cierre(self, ticket):
        pass

    @abstractmethod
    def info_cuenta(self):
        pass

    @abstractmethod
    def desconectar(self):
        pass


# ============================================================
# CONECTOR HEADLESS (LINUX/REST)
# ============================================================

class ConectorHeadless(ConectorBase):
    """Conector para Linux/REST API (cTrader o MetaApi) - Stub para compatibilidad."""
    
    def __init__(self, token, url_base):
        self.token = token
        self.url = url_base
        self.conectado = False
        self.logger = logging.getLogger('BotTrading.REST')

    def conectar(self):
        if self.token:
            self.logger.info("Conexión REST API establecida (Modo Linux)")
            self.conectado = True
            return True
        return False

    def verificar_conexion(self) -> bool:
        return self.conectado

    def obtener_datos(self, simbolo, n_velas=100, timeframe=None):
        if not self.conectado:
            self.logger.error(f"❌ obtener_datos abortado: Conector REST no conectado para {simbolo}.")
            return None
        return None

    def obtener_precio(self, simbolo):
        return {'bid': 0, 'ask': 0, 'spread': 0}

    def enviar_orden(self, simbolo, tipo, volumen, sl=0, tp=0, comentario=""):
        self.logger.info(f"Enviando orden vía REST: {simbolo} {tipo}")
        return {"ticket": 999, "precio": 0}

    def obtener_posiciones(self, simbolo: Optional[str] = None, force: bool = False):
        return []

    def cerrar_posicion(self, ticket):
        return True

    def cerrar_parcial(self, ticket, volumen_a_cerrar):
        return True

    def modificar_sl(self, ticket, nuevo_sl):
        return True

    def info_cuenta(self):
        return {"balance": 0, "equity": 0}

    def obtener_detalle_cierre(self, ticket):
        return None

    def tomar_captura(self, simbolo, ruta_archivo, timeframe=None):
        return False

    def desconectar(self):
        self.conectado = False
        self.logger.info("Sesión API cerrada")


# ============================================================
# CONECTOR PEPPERSTONE (MT5)
# ============================================================

class ConectorPepperstone(ConectorBase):
    """
    Conector para MetaTrader 5 (Windows) con Pepperstone.
    V9.4 - CORREGIDO DEFINITIVO: Normalización de zonas horarias en DataFrames.
    V9.10 - AGREGADO: Validación de mercado cerrado antes de descargar.
    """
    
    def __init__(self, login, password, server, magic_number=None, demo=True, almacen=None):
        self.login = login
        self.password = password
        self.server = server
        self.magic = magic_number if magic_number is not None else Config.MAGIC_NUMBER
        self.demo = demo
        self.almacen = almacen
        self.conectado = False
        
        # Cachés
        self._cache_simbolos = {}
        self._cache_posiciones = []
        self._last_pos_sync = 0
        self._tick_cache = {}
        self._tick_cache_ttl = 0.2
        self._symbol_selected = set()

        self._cache_simbolos_data = {}
        
        # Locks
        self._symbol_lock = Lock()
        self._request_lock = Lock()
        self._last_request_times = deque(maxlen=Config.MT5_RATE_LIMIT_PER_SEC)
        
        self.logger = logging.getLogger('BotTrading.MT5')

        self._deviation_por_clase = {
            'AUD': 20, 'XAU': 50, 'XAG': 50,
            'US30': 80, 'NAS100': 80, 'US500': 50,
            'GER40': 50, 'UK100': 50,
            'BTC': 200, 'ETH': 150, 'SOL': 150,
        }
        self._deviation_default = 10
        
        self.SL_MIN_PIPS = 14.5
        self.SL_MAX_PIPS = 200
        self.MIN_RR = 1.2
        
        # ✅ AÑADIR DICCIONARIO DE SL MÍNIMO POR SÍMBOLO (NUEVO)
        self.SL_MIN_PIPS_POR_SIMBOLO = {
            'EURUSD': 15, 'GBPUSD': 15, 'USDJPY': 15, 'AUDUSD': 15,
            'USDCAD': 15, 'USDCHF': 15, 'EURGBP': 15, 'EURJPY': 15,
            'GBPJPY': 18, 'AUDJPY': 15, 'EURNZD': 18, 'GBPAUD': 18,
            'EURCHF': 12, 'GBPCHF': 15,
            'XAUUSD': 60, 'XAGUSD': 80,
            'US30': 40, 'NAS100': 45, 'US500': 35,
            'BTCUSD': 80, 'ETHUSD': 60, 'SOLUSD': 40,
        }
        
        self.logger.info(f"🔌 ConectorPepperstone V9.4 CORREGIDO DEFINITIVO inicializado")
        self.logger.info(f"   Magic: {self.magic}")
        self.logger.info(f"   Demo: {self.demo}")
        self.logger.info(f"   Rate Limit: {Config.MT5_RATE_LIMIT_PER_SEC}/s")

    # ============================================================
    # MÉTODOS DE CONEXIÓN
    # ============================================================
    
    def _obtener_deviation(self, simbolo: str) -> int:
        simbolo_upper = simbolo.upper()
        for prefijo, deviation in self._deviation_por_clase.items():
            if simbolo_upper.startswith(prefijo):
                return deviation
        return self._deviation_default

    def _throttle(self):
        while True:
            with self._request_lock:
                now = time.time()
                if (len(self._last_request_times) < Config.MT5_RATE_LIMIT_PER_SEC or 
                    (now - self._last_request_times[0]) >= 1.0):
                    self._last_request_times.append(now)
                    break
            time.sleep(0.02)

    def _seleccionar_simbolo(self, simbolo):
        with self._symbol_lock:
            if simbolo in self._symbol_selected:
                return True
            
            try:
                info = mt5.symbol_info(simbolo)
            except Exception as e:
                self.logger.warning(f"⚠️ Error obteniendo info de {simbolo}: {e}")
                return False
            
            if info is None:
                self.logger.warning(f"⚠️ Símbolo {simbolo} no existe en MT5")
                return False
            
            for intento in range(3):
                try:
                    if mt5.symbol_select(simbolo, True):
                        self._symbol_selected.add(simbolo)
                        self._cache_simbolos[simbolo] = info
                        return True
                    else:
                        if intento < 2:
                            self.logger.debug(f"⚠️ Reintentando seleccionar {simbolo} (intento {intento+1}/3)")
                            time.sleep(0.1 * (intento + 1))
                except Exception as e:
                    if intento < 2:
                        self.logger.debug(f"⚠️ Error seleccionando {simbolo}: {e}, reintentando...")
                        time.sleep(0.1 * (intento + 1))
            
            self.logger.warning(f"⚠️ No se pudo seleccionar {simbolo} en Market Watch después de 3 intentos")
            return False

    def _get_symbol_info(self, simbolo):
        if simbolo in self._cache_simbolos:
            return self._cache_simbolos[simbolo]
        info = mt5.symbol_info(simbolo)
        if info:
            self._cache_simbolos[simbolo] = info
        return info

    @retry_mt5(max_retries=5, base_delay=1.0, max_delay=16.0)
    def conectar(self) -> bool:
        self.logger.info(f"Conectando a {self.server}...")
        if not mt5.initialize(login=self.login, password=self.password, 
                             server=self.server, timeout=10000):
            error = mt5.last_error()
            self.logger.error(f"❌ Error MT5: {error}")
            return False
        
        self.conectado = True
        account = mt5.account_info()
        if account:
            self.logger.info(f"✅ Conectado - Balance: ${account.balance:.2f}, "
                           f"Equity: ${account.equity:.2f}")
            return True
        return False

    def verificar_conexion(self) -> bool:
        term = mt5.terminal_info()
        if term is not None and term.connected:
            self.conectado = True
            return True
        
        self.logger.warning("⚠️ Conexión con MT5 perdida. Intentando reconectar...")
        self.conectado = False
        
        try:
            mt5.shutdown()
        except Exception:
            pass
        
        self._symbol_selected.clear()
        self._cache_simbolos.clear()
        self._tick_cache.clear()
        return self.conectar()

    # ============================================================
    # OBTENCIÓN DE DATOS (CORREGIDO V9.4 + V9.10)
    # ============================================================

    def _validar_frescura(self, df: pd.DataFrame, timeframe: int) -> bool:
        """
        Valida si los datos están frescos (última vela cercana).
        
        Args:
            df: DataFrame con datos OHLCV
            timeframe: Timeframe en minutos (60=H1, 5=M5, etc.)
        
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
            
            # Calcular tiempo máximo permitido (2x el timeframe)
            tiempo_maximo = timedelta(minutes=timeframe * 2)
            
            # Obtener hora actual
            ahora = datetime.now(timezone.utc)
            
            # Calcular diferencia
            diferencia = ahora - ultima_fecha
            
            # Si la diferencia es mayor al máximo permitido, los datos están desactualizados
            if diferencia > tiempo_maximo:
                self.logger.warning(f"⚠️ Datos desactualizados (última: {ultima_fecha}, diff: {diferencia}, max: {tiempo_maximo})")
                return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error validando frescura: {e}")
            return False

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def obtener_datos(self, simbolo, n_velas=100, timeframe=None):
        """
        Obtiene datos de mercado con actualización incremental.
        V9.7 - CORREGIDO DEFINITIVO: NO limita el histórico al combinar.
        """
        self._throttle()
        
        if not self.conectado:
            self.logger.warning(f"⚠️ {simbolo}: No conectado a MT5")
            return None
        
        if not self._seleccionar_simbolo(simbolo):
            self.logger.warning(f"⚠️ {simbolo}: No se pudo seleccionar en Market Watch")
            return None
        
        tf = timeframe or Config.TIMEFRAME
        cache_key = (simbolo, tf)
        
        # ============================================================
        # 1. OBTENER ÚLTIMA FECHA DESDE SQLITE
        # ============================================================
        ultima_fecha = None
        df_sqlite = None
        
        if self.almacen:
            try:
                df_sqlite = self.almacen.obtener_datos_historicos(simbolo, tf)
                if df_sqlite is not None and not df_sqlite.empty:
                    ultima_fecha = df_sqlite.index[-1]
                    self.logger.info(f"📊 {simbolo} TF{tf}: Última vela en SQLite: {ultima_fecha} ({len(df_sqlite)} velas)")
            except Exception as e:
                self.logger.debug(f"⚠️ Error leyendo SQLite: {e}")
        
        # ============================================================
        # 2. SI HAY ÚLTIMA FECHA → DESCARGAR INCREMENTAL (SIEMPRE)
        # ============================================================
        if ultima_fecha is not None:
            self.logger.info(f"📥 {simbolo} TF{tf}: Actualizando desde {ultima_fecha}...")
            
            # ✅ CORRECCIÓN: Intentar descargar INCLUSO con mercado cerrado
            df_nuevo = self._descargar_incremental(simbolo, tf, ultima_fecha, n_velas)
            
            if df_nuevo is not None and len(df_nuevo) > 0:
                # ✅ COMBINAR CON DATOS EXISTENTES
                if df_sqlite is not None and len(df_sqlite) > 0:
                    # Asegurar que ambos tengan índice tz-aware
                    if df_sqlite.index.tz is None:
                        df_sqlite.index = df_sqlite.index.tz_localize('UTC')
                    if df_nuevo.index.tz is None:
                        df_nuevo.index = df_nuevo.index.tz_localize('UTC')
                    
                    # ✅ CORRECCIÓN: NO LIMITAR A n_velas
                    df_combinado = pd.concat([df_sqlite, df_nuevo])
                    df_combinado = df_combinado[~df_combinado.index.duplicated(keep='last')]
                    df_combinado = df_combinado.sort_index()
                    
                    # ✅ LIMITAR SOLO SI ES DEMASIADO GRANDE (ej: > 50000)
                    MAX_VELAS = 50000  # Límite de seguridad
                    if len(df_combinado) > MAX_VELAS:
                        df_combinado = df_combinado.iloc[-MAX_VELAS:]
                    
                    self._cache_simbolos_data[cache_key] = df_combinado
                    return df_combinado
                else:
                    self._cache_simbolos_data[cache_key] = df_nuevo
                    return df_nuevo
            else:
                # No hay datos nuevos, devolver existentes
                if df_sqlite is not None and len(df_sqlite) > 0:
                    self.logger.warning(f"⚠️ {simbolo} TF{tf}: No hay datos nuevos desde {ultima_fecha}")
                    self._cache_simbolos_data[cache_key] = df_sqlite
                    return df_sqlite
                return None
        
        # ============================================================
        # 3. PRIMERA DESCARGA (NO HAY DATOS EN SQLITE)
        # ============================================================
        self.logger.info(f"📥 {simbolo} TF{tf}: Primera descarga...")
        return self._descargar_completo(simbolo, tf, n_velas)

    def _descargar_completo(self, simbolo: str, tf: int, n_velas: int) -> Optional[pd.DataFrame]:
        """
        Descarga datos completos (primera vez).
        V9.8 - CORREGIDO: Descarga 90 días desde M5 si el broker no tiene.
        """
        # 1. Intentar desde broker con copy_rates_from_pos
        try:
            rates = mt5.copy_rates_from_pos(simbolo, tf, 0, n_velas)
            
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                df.set_index('time', inplace=True)
                df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
                
                if self.almacen:
                    self.almacen.guardar_datos_historicos(simbolo, tf, df)
                
                return df
        except Exception as e:
            self.logger.debug(f"⚠️ {simbolo} TF{tf}: Error en copy_rates_from_pos: {e}")
        
        # 2. Intentar desde broker con copy_rates_range (90 días)
        try:
            fecha_desde = datetime.now(timezone.utc) - timedelta(days=90)
            fecha_hasta = datetime.now(timezone.utc)
            rates = mt5.copy_rates_range(simbolo, tf, fecha_desde, fecha_hasta)
            
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                df.set_index('time', inplace=True)
                df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
                
                if self.almacen:
                    self.almacen.guardar_datos_historicos(simbolo, tf, df)
                
                return df
        except Exception as e:
            self.logger.debug(f"⚠️ {simbolo} TF{tf}: Error en copy_rates_range: {e}")
        
        # 3. Construir desde M5 (30000 velas = 104 días)
        try:
            rates_m5 = mt5.copy_rates_from_pos(simbolo, 5, 0, 30000)
            
            if rates_m5 is not None and len(rates_m5) > 0:
                df_m5 = pd.DataFrame(rates_m5)
                df_m5['time'] = pd.to_datetime(df_m5['time'], unit='s', utc=True)
                df_m5.set_index('time', inplace=True)
                df_m5.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
                
                from utils.construir_timeframes import construir_desde_m5
                timeframes_construidos = construir_desde_m5(df_m5, [tf])
                df = timeframes_construidos.get(tf)
                
                if df is not None and len(df) > 0:
                    if self.almacen:
                        self.almacen.guardar_datos_historicos(simbolo, tf, df)
                    
                    return df
        except Exception as e:
            self.logger.debug(f"⚠️ {simbolo} TF{tf}: Error construyendo desde M5: {e}")
        
        return None
    
    def _descargar_incremental(self, simbolo: str, tf: int, ultima_fecha: datetime, n_velas: int) -> Optional[pd.DataFrame]:
        """
        Descarga datos incrementales desde la última fecha guardada.
        V9.7 - NUEVO: Funciona incluso con mercado cerrado.
        """
        # Normalizar fecha a UTC
        if ultima_fecha.tzinfo is None:
            ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
        else:
            ultima_fecha = ultima_fecha.astimezone(timezone.utc)
        
        # Añadir 1 minuto para evitar la última vela duplicada
        fecha_desde = ultima_fecha + timedelta(minutes=1)
        fecha_hasta = datetime.now(timezone.utc)
        
        self.logger.info(f"📥 {simbolo} TF{tf}: Descargando desde {fecha_desde} hasta {fecha_hasta}")
        
        # Intentar con copy_rates_range (el broker siempre tiene datos)
        try:
            rates = mt5.copy_rates_range(simbolo, tf, fecha_desde, fecha_hasta)
            
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                df.set_index('time', inplace=True)
                df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
                
                self.logger.info(f"✅ {simbolo} TF{tf}: {len(df)} velas nuevas descargadas")
                
                # Guardar en SQLite
                if self.almacen:
                    self.almacen.guardar_datos_historicos(simbolo, tf, df)
                
                return df
            else:
                self.logger.info(f"ℹ️ {simbolo} TF{tf}: No hay datos nuevos desde {fecha_desde}")
                return None
                
        except Exception as e:
            self.logger.warning(f"⚠️ {simbolo} TF{tf}: Error en copy_rates_range: {e}")
            
            # Fallback: intentar con copy_rates_from_pos
            try:
                rates = mt5.copy_rates_from_pos(simbolo, tf, 0, n_velas)
                
                if rates is not None and len(rates) > 0:
                    df = pd.DataFrame(rates)
                    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                    df.set_index('time', inplace=True)
                    df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
                    
                    self.logger.info(f"✅ {simbolo} TF{tf}: {len(df)} velas descargadas (fallback)")
                    
                    if self.almacen:
                        self.almacen.guardar_datos_historicos(simbolo, tf, df)
                    
                    return df
            except Exception as e2:
                self.logger.warning(f"⚠️ {simbolo} TF{tf}: Error en fallback: {e2}")
        
        return None


    def _descargar_con_reintentos(self, simbolo: str, timeframe: int, n_velas: int = 100) -> Optional[pd.DataFrame]:
        """
        Descarga datos con múltiples métodos y reintentos.
        """
        import time
        import MetaTrader5 as mt5
        
        # Métodos de descarga en orden de preferencia
        metodos = [
            ('copy_rates_from_pos', lambda: mt5.copy_rates_from_pos(simbolo, timeframe, 0, n_velas)),
            ('copy_rates_range', lambda: mt5.copy_rates_range(
                simbolo, timeframe, 
                datetime.now(timezone.utc) - timedelta(days=90), 
                datetime.now(timezone.utc)
            )),
        ]
        
        for nombre_metodo, funcion in metodos:
            for intento in range(3):
                try:
                    rates = funcion()
                    
                    if rates is not None and len(rates) > 0:
                        self.logger.debug(f"✅ {simbolo} TF{timeframe}: Datos obtenidos con {nombre_metodo} (intento {intento+1})")
                        
                        # Convertir a DataFrame
                        df = pd.DataFrame(rates)
                        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                        df.set_index('time', inplace=True)
                        df.rename(columns={
                            'open': 'Open', 'high': 'High', 'low': 'Low',
                            'close': 'Close', 'tick_volume': 'Volume'
                        }, inplace=True)
                        
                        return df
                        
                except Exception as e:
                    self.logger.debug(f"⚠️ {simbolo} TF{timeframe}: {nombre_metodo} intento {intento+1} falló: {e}")
                    time.sleep(0.5)
        
        return None

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def obtener_datos_desde_fecha(self, simbolo: str, fecha_desde: datetime, 
                                n_velas: int = 250, timeframe: int = None) -> Optional[pd.DataFrame]:
        self._throttle()
        
        if not self.conectado:
            self.logger.warning(f"⚠️ {simbolo}: No conectado a MT5")
            return None
        
        if not self._seleccionar_simbolo(simbolo):
            self.logger.warning(f"⚠️ {simbolo}: No se pudo seleccionar en Market Watch")
            return None

        tf = timeframe or Config.TIMEFRAME
        
        # ✅ CORRECCIÓN V9.4: Normalizar fecha_desde a timezone.utc
        if fecha_desde.tzinfo is None:
            fecha_desde = fecha_desde.replace(tzinfo=timezone.utc)
        else:
            fecha_desde = fecha_desde.astimezone(timezone.utc)
        
        fecha_hasta = datetime.now(timezone.utc)
        
        self.logger.info(f"📥 {simbolo}: Descargando desde {fecha_desde.strftime('%Y-%m-%d %H:%M')} hasta ahora (TF{tf})")
        
        try:
            rates = mt5.copy_rates_range(simbolo, tf, fecha_desde, fecha_hasta)
            
            if rates is None or len(rates) == 0:
                self.logger.warning(f"⚠️ {simbolo}: No hay nuevos datos desde {fecha_desde.strftime('%Y-%m-%d %H:%M')}")
                return None
            
            self.logger.info(f"✅ {simbolo}: {len(rates)} velas descargadas desde {fecha_desde.strftime('%Y-%m-%d %H:%M')}")
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df.set_index('time', inplace=True)
            df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low',
                'close': 'Close', 'tick_volume': 'Volume'
            }, inplace=True)
            
            if n_velas > 0 and len(df) > n_velas:
                df = df.iloc[-n_velas:]
            
            if hasattr(self, 'almacen') and self.almacen is not None:
                try:
                    self.almacen.guardar_datos_historicos(simbolo, tf, df)
                    self.logger.debug(f"💾 {simbolo} TF{tf}: {len(df)} velas guardadas en SQLite")
                except Exception as e:
                    self.logger.warning(f"⚠️ Error guardando en SQLite: {e}")
            
            return df
            
        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error descargando datos desde {fecha_desde}: {e}")
            return None

    def _pip_size_simbolo(self, simbolo: str, info: Any) -> float:
        point = float(getattr(info, "point", 0.0) or 0.0)
        if point <= 0:
            return 0.0
        
        nombre = str(getattr(info, "name", simbolo)).upper()
        calc_mode = getattr(info, "trade_calc_mode", None)
        
        forex_modes = {
            getattr(mt5, "SYMBOL_CALC_MODE_FOREX", None),
            getattr(mt5, "SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE", None),
        }
        forex_modes.discard(None)
        
        if calc_mode in forex_modes:
            return point * 10.0 if int(getattr(info, "digits", 0)) in (3, 5) else point
        
        if any(x in nombre for x in ("XAU", "XAG")):
            return 0.10
        
        if any(x in nombre for x in ("US30", "NAS100", "US500", "SP500")):
            return 1.0
        
        if any(x in nombre for x in ("BTC", "ETH", "SOL")):
            return 1.0
        
        return point

    # ============================================================
    # ✅ MÉTODO _es_horario_cerrado (CORREGIDO DEFINITIVO)
    # ============================================================

    def _es_horario_cerrado(self, simbolo: str) -> bool:
        """
        Verifica si el mercado está cerrado para un símbolo.
        V9.10 - CORREGIDO DEFINITIVO: Solo cripto opera el sábado.
        
        Args:
            simbolo: Símbolo a verificar
    
        Returns:
            True si el mercado está cerrado (no descargar datos)
        """
        try:
            # Verificar si es cripto (siempre abierto)
            simbolo_upper = simbolo.upper()
            if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                return False
            
            # Obtener hora actual en Colombia
            ahora = datetime.now(timezone.utc)
            hora_col = ahora.astimezone(timezone(timedelta(hours=-5)))
            weekday_col = hora_col.weekday()
            
            # SÁBADO: Todo cerrado excepto cripto
            if weekday_col == 5:
                return True
            
            # DOMINGO: Forex/Índices/Metales cerrados hasta cierta hora
            if weekday_col == 6:
                hora_col_float = hora_col.hour + hora_col.minute / 60.0
                
                # Forex abre 17:00 COT
                if self._es_forex(simbolo_upper):
                    return hora_col_float < 17.0
                
                # Índices y Metales abren 18:00 COT
                if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                    return hora_col_float < 18.0
                
                return True  # No es forex ni índice ni metal
            
            # VIERNES: Cierres anticipados
            if weekday_col == 4:
                hora_col_float = hora_col.hour + hora_col.minute / 60.0
                
                # Índices y Metales cierran 16:00 COT
                if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                    return hora_col_float >= 16.0
                
                # Forex cierra 17:00 COT
                if self._es_forex(simbolo_upper):
                    return hora_col_float >= 17.0
            
            # LUNES A JUEVES: Mercado abierto (considerado normal)
            return False
            
        except Exception as e:
            self.logger.debug(f"⚠️ Error verificando horario: {e}")
            return False

    def _es_forex(self, simbolo: str) -> bool:
        """Verifica si es un par de divisas."""
        pares_forex = [
            'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF',
            'EURGBP', 'EURJPY', 'GBPJPY', 'AUDJPY', 'EURNZD', 'GBPAUD',
            'EURCHF', 'GBPCHF', 'AUDCAD', 'AUDCHF', 'AUDNZD', 'CADJPY',
            'CHFJPY', 'EURAUD', 'EURCAD', 'GBPAUD', 'GBPCAD', 'GBPCHF',
            'NZDJPY', 'NZDUSD', 'USDSGD', 'USDHKD', 'USDMXN', 'USDZAR'
        ]
        return simbolo in pares_forex

    def _es_indice(self, simbolo: str) -> bool:
        """Verifica si es un índice."""
        indices = ['US30', 'NAS100', 'US500', 'SP500', 'GER40', 'UK100', 'DAX', 'SPX']
        return any(x in simbolo for x in indices)

    def _es_metal(self, simbolo: str) -> bool:
        """Verifica si es un metal precioso."""
        metales = ['XAU', 'XAG', 'XPT', 'XPD']
        return any(x in simbolo for x in metales)

    # ============================================================
    # OBTENCIÓN DE PRECIO
    # ============================================================

    def obtener_precio(self, simbolo):
        self.logger.info(f"📥 {simbolo}: Iniciando obtener_precio()")

        if not self.verificar_conexion():
            self.logger.error(f"❌ {simbolo}: MT5 no conectado")
            return None

        max_wait = 1.0
        poll_interval = 0.10
        deadline = time.monotonic() + max_wait
        intento = 0

        while time.monotonic() < deadline:
            intento += 1

            try:
                if not self._seleccionar_simbolo(simbolo):
                    self.logger.debug(f"⚠️ {simbolo}: _seleccionar_simbolo falló (intento {intento})")
                    time.sleep(poll_interval)
                    continue

                info = mt5.symbol_info(simbolo)
                if info is None:
                    self.logger.debug(f"⚠️ {simbolo}: symbol_info=None (intento {intento})")
                    time.sleep(poll_interval)
                    continue

                point = float(getattr(info, "point", 0.0) or 0.0)
                if point <= 0:
                    self.logger.warning(f"⚠️ {simbolo}: point inválido {point}")
                    time.sleep(poll_interval)
                    continue

                tick = mt5.symbol_info_tick(simbolo)
                if tick is None:
                    self.logger.debug(f"⚠️ {simbolo}: tick=None (intento {intento})")
                    time.sleep(poll_interval)
                    continue

                bid = float(tick.bid)
                ask = float(tick.ask)

                if bid <= 0 or ask <= 0:
                    self.logger.debug(f"⚠️ {simbolo}: BID/ASK inválido bid={bid}, ask={ask}")
                    time.sleep(poll_interval)
                    continue

                if ask < bid:
                    self.logger.warning(f"⚠️ {simbolo}: ASK < BID bid={bid}, ask={ask}")
                    time.sleep(poll_interval)
                    continue

                spread_price = ask - bid

                if spread_price <= 0:
                    self.logger.debug(f"⏳ {simbolo}: BID==ASK ({bid:.{info.digits}f}), esperando spread > 0 (intento {intento})")
                    time.sleep(poll_interval)
                    continue

                pip_size = self._pip_size_simbolo(simbolo, info)
                if pip_size <= 0:
                    self.logger.warning(f"⚠️ {simbolo}: pip_size inválido {pip_size}")
                    time.sleep(poll_interval)
                    continue

                spread_points = spread_price / point
                spread_pips = spread_price / pip_size
                timestamp = time.time()

                self.logger.info(f"✅ {simbolo}: Tick obtenido en intento {intento}")
                self.logger.info(f"   BID={bid:.{info.digits}f} | ASK={ask:.{info.digits}f} | spread={spread_price:.{info.digits}f} | {spread_points:.1f} points | {spread_pips:.2f} pips")

                return {
                    "bid": bid,
                    "ask": ask,
                    "spread": spread_price,
                    "spread_price": spread_price,
                    "spread_points": spread_points,
                    "spread_pips": spread_pips,
                    "point": point,
                    "pip_size": pip_size,
                    "tick_size": float(getattr(info, "trade_tick_size", 0.0) or 0.0),
                    "digits": int(info.digits),
                    "timestamp": timestamp,
                    "tick_time": getattr(tick, "time", None),
                    "tick_time_msc": getattr(tick, "time_msc", None),
                    "fuente": "symbol_info_tick",
                }

            except Exception as e:
                self.logger.warning(f"⚠️ {simbolo}: error obteniendo precio: {e}")
                time.sleep(poll_interval)

        self.logger.warning(f"⚠️ {simbolo}: no se obtuvo tick con spread positivo en {max_wait:.1f}s ({intento} intentos)")
        return None

    # ============================================================
    # ENVÍO DE ÓRDENES
    # ============================================================

    def _obtener_filling_mode(self, simbolo: str) -> int:
        info = self._get_symbol_info(simbolo)
        if not info:
            return mt5.ORDER_FILLING_IOC
        
        filling = info.filling_mode
        try:
            if filling == mt5.SYMBOL_FILLING_MODE_FOK:
                return mt5.ORDER_FILLING_FOK
            elif filling == mt5.SYMBOL_FILLING_MODE_IOC:
                return mt5.ORDER_FILLING_IOC
            elif filling == mt5.SYMBOL_FILLING_MODE_RETURN:
                return mt5.ORDER_FILLING_RETURN
        except AttributeError:
            pass
        return mt5.ORDER_FILLING_IOC

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def enviar_orden(self, simbolo: str, tipo: str, volumen: float, sl: float, tp: float, comentario: str = "", **kwargs):
        """
        Envía una orden al broker.
        V9.67 - CORREGIDO: Retorna SL/TP del request (no de result).
        """
        # ✅ CORREGIDO: Normalizar dirección
        tipo_normalizado = tipo.upper().strip()
        
        if tipo_normalizado in ['COMPRA', 'BUY', 'LONG']:
            order_type = mt5.ORDER_TYPE_BUY
            direccion = 'COMPRA'
        elif tipo_normalizado in ['VENTA', 'SELL', 'SHORT']:
            order_type = mt5.ORDER_TYPE_SELL
            direccion = 'VENTA'
        else:
            return {'retcode': -1, 'comentario': f"Dirección inválida: {tipo}"}
        
        # Obtener información del símbolo
        info = mt5.symbol_info(simbolo)
        if info is None:
            return {'retcode': -1, 'comentario': f"Símbolo inválido: {simbolo}"}
        
        # Obtener tick actual
        tick = mt5.symbol_info_tick(simbolo)
        if tick is None:
            return {'retcode': -1, 'comentario': f"No se pudo obtener tick para {simbolo}"}
        
        # ✅ CORREGIDO: Validar SL/TP según dirección REAL
        if direccion == 'COMPRA':
            if sl >= tick.ask:
                return {'retcode': -1, 'comentario': f"SL inválido para COMPRA: SL={sl} >= ask={tick.ask}"}
            if tp <= tick.ask:
                return {'retcode': -1, 'comentario': f"TP inválido para COMPRA: TP={tp} <= ask={tick.ask}"}
        else:  # VENTA
            if sl <= tick.bid:
                return {'retcode': -1, 'comentario': f"SL inválido para VENTA: SL={sl} <= bid={tick.bid}"}
            if tp >= tick.bid:
                return {'retcode': -1, 'comentario': f"TP inválido para VENTA: TP={tp} >= bid={tick.bid}"}
        
        # Preparar request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": simbolo,
            "volume": float(volumen),
            "type": order_type,
            "price": tick.ask if direccion == 'COMPRA' else tick.bid,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": kwargs.get('magic_number', getattr(self, 'magic_number', 0)),
            "comment": comentario,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        # Enviar orden
        result = mt5.order_send(request)
        
        if result is None:
            return {'retcode': -1, 'comentario': "Error desconocido en MT5"}
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                'retcode': result.retcode,
                'comentario': f"Error {result.retcode}: {result.comment}",
                'ticket': None
            }
        
        # ✅ CORREGIDO V9.67: Usar SL/TP del request (NO de result.sl)
        return {
            'retcode': result.retcode,
            'ticket': result.order,
            'precio': result.price,
            'sl': request['sl'],  # ✅ El SL que enviamos
            'tp': request['tp'],  # ✅ El TP que enviamos
            'comentario': result.comment
        }
        
    # ============================================================
    # GESTIÓN DE POSICIONES
    # ============================================================

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def cerrar_posicion(self, ticket):
        if not self.conectado:
            return False
        if not ticket:
            self.logger.error("❌ Ticket inválido para cerrar")
            return False
        
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            self.logger.warning(f"Posición {ticket} no encontrada")
            return False
        
        pos = pos[0]
        for intento in range(3):
            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                continue
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                "position": ticket,
                "price": tick.bid if pos.type == 0 else tick.ask,
                "deviation": self._obtener_deviation(pos.symbol),
                "magic": self.magic,
                "comment": "Cierre Bot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._obtener_filling_mode(pos.symbol),
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(f"✅ Posición {ticket} cerrada correctamente")
                return True
            if result and result.retcode in [mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_OFF]:
                time.sleep(0.1)
                continue
            break
        
        self.logger.error(f"❌ Fallo al cerrar posición {ticket} después de 3 intentos")
        return False

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def cerrar_parcial(self, ticket, volumen_a_cerrar):
        if not self.conectado:
            return False
        if not ticket:
            self.logger.error("❌ Ticket inválido para cerrar parcial")
            return False
        
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        
        pos = pos[0]
        volumen_a_cerrar = max(0.01, round(volumen_a_cerrar, 2))
        
        if volumen_a_cerrar >= pos.volume:
            return self.cerrar_posicion(ticket)
        
        for intento in range(3):
            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                continue
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": volumen_a_cerrar,
                "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                "position": ticket,
                "price": tick.bid if pos.type == 0 else tick.ask,
                "deviation": self._obtener_deviation(pos.symbol),
                "magic": self.magic,
                "comment": "Cierre Parcial",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._obtener_filling_mode(pos.symbol),
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(f"✅ Cierre parcial {volumen_a_cerrar} de {ticket} exitoso")
                return True
            if result and result.retcode in [mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_OFF]:
                time.sleep(0.1)
                continue
            break
        
        return False

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def modificar_sl(self, ticket, nuevo_sl):
        if not self.conectado:
            return False
        if not ticket:
            self.logger.error("❌ Ticket inválido para modificar SL")
            return False
        
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        
        pos = pos[0]
        info = self._get_symbol_info(pos.symbol)
        digits = info.digits if info else 5

        for intento in range(3):
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl": round(nuevo_sl, digits),
                "tp": pos.tp
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(f"✅ SL modificado para {ticket} a {nuevo_sl:.{digits}f}")
                return True
            if result and result.retcode in [mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_OFF]:
                time.sleep(0.1)
                continue
            break
        
        self.logger.error(f"❌ Fallo al modificar SL para {ticket}")
        return False

    # ============================================================
    # OBTENCIÓN DE INFORMACIÓN
    # ============================================================

    @retry_mt5(max_retries=20, base_delay=0.1, max_delay=5.0)
    def obtener_detalle_cierre(self, ticket):
        if not self.conectado or not ticket:
            return None
        
        deals = mt5.history_deals_get(position=ticket)
        if deals is None or len(deals) == 0:
            return None

        ganancia, comision, swap, precio_salida, time_salida = 0.0, 0.0, 0.0, 0.0, None
        for d in deals:
            ganancia += d.profit
            comision += d.commission
            swap += d.swap
            if d.entry in [mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT, mt5.DEAL_ENTRY_OUT_BY]:
                precio_salida = d.price
                time_salida = datetime.fromtimestamp(d.time).isoformat()
        
        return {
            'ganancia': ganancia,
            'comision': comision,
            'swap': swap,
            'precio_salida': precio_salida,
            'timestamp_salida': time_salida or datetime.now(timezone.utc).isoformat()
        }

    def info_cuenta(self):
        if not self.conectado:
            return None
        
        account = mt5.account_info()
        if account:
            return {
                'login': account.login,
                'balance': account.balance,
                'equity': account.equity,
                'margen_libre': account.margin_free,
                'margen': account.margin,
                'nivel_margen': account.margin_level,
                'apalancamiento': account.leverage,
                'moneda': account.currency
            }
        return None

    def tomar_captura(self, simbolo, ruta_archivo, timeframe=None):
        if not self.conectado:
            return False
        
        tf = timeframe or Config.TIMEFRAME
        if not self._seleccionar_simbolo(simbolo):
            return False
        
        try:
            return mt5.screen_shot(simbolo, tf, str(ruta_archivo))
        except Exception as e:
            self.logger.error(f"Error al tomar captura de {simbolo}: {e}")
            return False

    def obtener_posiciones(self, simbolo: Optional[str] = None, force: bool = False) -> List[Dict[str, Any]]:
        if not self.conectado:
            return []

        ahora = time.time()
        if not force and (ahora - self._last_pos_sync) < 1.0:
            if simbolo is None:
                return self._cache_posiciones
            else:
                return [p for p in self._cache_posiciones if p['simbolo'] == simbolo]

        try:
            positions = mt5.positions_get()
        except Exception as e:
            self.logger.error(f"Error al obtener posiciones: {e}")
            return []

        if not positions:
            self._cache_posiciones = []
            self._last_pos_sync = ahora
            return []

        pos_list = []
        for p in positions:
            if p.magic == self.magic or self.magic == 0:
                pos_list.append({
                    'ticket': p.ticket,
                    'simbolo': p.symbol,
                    'tipo': 'BUY' if p.type == 0 else 'SELL',
                    'volumen': p.volume,
                    'precio_apertura': p.price_open,
                    'precio_actual': p.price_current,
                    'sl': p.sl,
                    'tp': p.tp,
                    'ganancia': p.profit,
                    'swap': p.swap,
                    'magic': p.magic,
                    'time': p.time,
                })

        self._cache_posiciones = pos_list
        self._last_pos_sync = ahora

        if simbolo is None:
            return self._cache_posiciones
        else:
            return [p for p in self._cache_posiciones if p['simbolo'] == simbolo]

    def obtener_info_simbolo(self, simbolo):
        return self._get_symbol_info(simbolo)

    def desconectar(self):
        mt5.shutdown()
        self.conectado = False
        self._symbol_selected.clear()
        self._cache_simbolos.clear()
        self._tick_cache.clear()
        self.logger.info("🔒 Desconectado de MT5")

    def obtener_historial_operaciones(self, 
                                   fecha_desde: Optional[datetime] = None,
                                   fecha_hasta: Optional[datetime] = None,
                                   simbolo: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.conectado:
            self.logger.error("❌ No conectado a MT5")
            return []
        
        if fecha_desde is None:
            fecha_desde = datetime.now(timezone.utc) - timedelta(days=30)
        
        if fecha_hasta is None:
            fecha_hasta = datetime.now(timezone.utc)
        
        desde_ts = int(fecha_desde.timestamp())
        hasta_ts = int(fecha_hasta.timestamp())
        
        operaciones = []
        
        try:
            deals = mt5.history_deals_get(desde_ts, hasta_ts, symbol=simbolo)
            
            if deals is not None and len(deals) > 0:
                self.logger.info(f"📊 MT5: {len(deals)} deals obtenidos")
                
                for deal in deals:
                    try:
                        ticket = deal.order if hasattr(deal, 'order') else deal.deal
                        deal_id = deal.deal if hasattr(deal, 'deal') else deal.order
                        
                        if deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_BUY_STOP, mt5.DEAL_TYPE_BUY_LIMIT]:
                            direccion = 'COMPRA'
                        elif deal.type in [mt5.DEAL_TYPE_SELL, mt5.DEAL_TYPE_SELL_STOP, mt5.DEAL_TYPE_SELL_LIMIT]:
                            direccion = 'VENTA'
                        else:
                            direccion = 'DESCONOCIDO'
                        
                        if deal.entry in [mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_INOUT]:
                            estado = 'ABIERTA'
                        else:
                            estado = 'CERRADA'
                        
                        op = {
                            'ticket': ticket,
                            'deal_id': deal_id,
                            'simbolo': deal.symbol,
                            'direccion': direccion,
                            'entrada': deal.price,
                            'volumen': deal.volume,
                            'ganancia': deal.profit,
                            'comision': deal.commission,
                            'swap': deal.swap,
                            'timestamp': datetime.fromtimestamp(deal.time, tz=timezone.utc).isoformat(),
                            'magic': deal.magic,
                            'estado': estado,
                            'tipo': 'DEAL',
                            'entry_type': 'IN' if deal.entry in [mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_INOUT] else 'OUT',
                        }
                        operaciones.append(op)
                        
                    except Exception as e:
                        self.logger.debug(f"Error procesando deal: {e}")
                        continue
            else:
                self.logger.debug("📭 No se obtuvieron deals de MT5")
            
            try:
                positions = mt5.positions_get(symbol=simbolo)
                if positions is not None and len(positions) > 0:
                    self.logger.info(f"📊 MT5: {len(positions)} posiciones abiertas obtenidas")
                    for pos in positions:
                        if pos.magic == self.magic or self.magic == 0:
                            op = {
                                'ticket': pos.ticket,
                                'simbolo': pos.symbol,
                                'direccion': 'COMPRA' if pos.type == 0 else 'VENTA',
                                'entrada': pos.price_open,
                                'precio_actual': pos.price_current,
                                'volumen': pos.volume,
                                'sl': pos.sl,
                                'tp': pos.tp,
                                'ganancia': pos.profit,
                                'swap': pos.swap,
                                'timestamp': datetime.fromtimestamp(pos.time, tz=timezone.utc).isoformat(),
                                'magic': pos.magic,
                                'tipo': 'POSITION',
                                'estado': 'ABIERTA',
                            }
                            operaciones.append(op)
            except Exception as e:
                self.logger.debug(f"Error obteniendo posiciones: {e}")
            
            try:
                orders = mt5.orders_get(symbol=simbolo)
                if orders is not None and len(orders) > 0:
                    self.logger.info(f"📊 MT5: {len(orders)} órdenes pendientes obtenidas")
                    for order in orders:
                        if order.magic == self.magic or self.magic == 0:
                            op = {
                                'ticket': order.ticket,
                                'simbolo': order.symbol,
                                'direccion': 'COMPRA' if order.type in [mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP] else 'VENTA',
                                'entrada': order.price_open,
                                'volumen': order.volume_initial,
                                'sl': order.sl,
                                'tp': order.tp,
                                'timestamp': datetime.fromtimestamp(order.time_setup, tz=timezone.utc).isoformat(),
                                'magic': order.magic,
                                'tipo': 'ORDER',
                                'estado': 'PENDIENTE',
                            }
                            operaciones.append(op)
            except Exception as e:
                self.logger.debug(f"Error obteniendo órdenes: {e}")
            
            if operaciones:
                tipos = {}
                for op in operaciones:
                    tipo = op.get('tipo', 'DESCONOCIDO')
                    tipos[tipo] = tipos.get(tipo, 0) + 1
                
                estados = {}
                for op in operaciones:
                    estado = op.get('estado', 'DESCONOCIDO')
                    estados[estado] = estados.get(estado, 0) + 1
                
                self.logger.info(
                    f"📊 Historial MT5: {len(operaciones)} operaciones "
                    f"(Tipos: {tipos}, Estados: {estados})"
                )
            else:
                self.logger.info("📭 No hay operaciones en el broker")
            
            return operaciones
            
        except Exception as e:
            self.logger.error(f"❌ Error obteniendo historial de MT5: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return []
    
    # ============================================================
    # UTILIDADES INTERNAS
    # ============================================================
    
    def _obtener_lote_minimo_por_activo(self, simbolo: str) -> float:
        simbolo_upper = simbolo.upper()
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 0.1
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 0.01
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 0.01
        else:
            return 0.01

    def _obtener_lote_maximo_por_activo(self, simbolo: str) -> float:
        simbolo_upper = simbolo.upper()
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 10.0
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 1.0
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        else:
            return 10.0