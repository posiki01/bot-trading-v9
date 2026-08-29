#!/usr/bin/env python3
"""
mt5/conector_mt5.py (V9.5 - CORREGIDO DEFINITIVO)
Conector para MetaTrader 5 con soporte para Pepperstone y modo Headless.
V9.5: Usa self.mt5 en lugar de mt5 global para permitir inyección de mocks.
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
import MetaTrader5 as mt5_global  # ✅ Import directo
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
    def obtener_posiciones(self, simbolo=None, force=False):
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

    def obtener_posiciones(self, simbolo=None, force=False):
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
    V9.5 - CORREGIDO DEFINITIVO: Usa self.mt5 en lugar de mt5 global.
    """
    
    def __init__(self, login, password, server, magic_number=None, demo=True, almacen=None, mt5_modulo=None):
        self.login = login
        self.password = password
        self.server = server
        self.magic = magic_number if magic_number is not None else Config.MAGIC_NUMBER
        self.demo = demo
        self.almacen = almacen
        self.conectado = False
        
        # ✅ CORRECCIÓN: Usar self.mt5 (inyectable) o importar
        if mt5_modulo is not None:
            self.mt5 = mt5_modulo
        else:
            import MetaTrader5 as mt5
            self.mt5 = mt5
        
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
        
        self.logger.info(f"🔌 ConectorPepperstone V9.5 CORREGIDO DEFINITIVO inicializado")
        self.logger.info(f"   Magic: {self.magic}")
        self.logger.info(f"   Demo: {self.demo}")
        self.logger.info(f"   Rate Limit: {Config.MT5_RATE_LIMIT_PER_SEC}/s")

    # ============================================================
    # MÉTODOS DE CONEXIÓN (✅ USANDO self.mt5)
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
                info = self.mt5.symbol_info(simbolo)  # ✅ self.mt5
            except Exception as e:
                self.logger.warning(f"⚠️ Error obteniendo info de {simbolo}: {e}")
                return False
            
            if info is None:
                self.logger.warning(f"⚠️ Símbolo {simbolo} no existe en MT5")
                return False
            
            for intento in range(3):
                try:
                    if self.mt5.symbol_select(simbolo, True):  # ✅ self.mt5
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
        info = self.mt5.symbol_info(simbolo)  # ✅ self.mt5
        if info:
            self._cache_simbolos[simbolo] = info
        return info

    @retry_mt5(max_retries=5, base_delay=1.0, max_delay=16.0)
    def conectar(self) -> bool:
        self.logger.info(f"Conectando a {self.server}...")
        if not self.mt5.initialize(login=self.login, password=self.password,  # ✅ self.mt5
                             server=self.server, timeout=10000):
            error = self.mt5.last_error()  # ✅ self.mt5
            self.logger.error(f"❌ Error MT5: {error}")
            return False
        
        self.conectado = True
        account = self.mt5.account_info()  # ✅ self.mt5
        if account:
            self.logger.info(f"✅ Conectado - Balance: ${account.balance:.2f}, "
                           f"Equity: ${account.equity:.2f}")
            return True
        return False

    def verificar_conexion(self) -> bool:
        term = self.mt5.terminal_info()  # ✅ self.mt5
        if term is not None and term.connected:
            self.conectado = True
            return True
        
        self.logger.warning("⚠️ Conexión con MT5 perdida. Intentando reconectar...")
        self.conectado = False
        
        try:
            self.mt5.shutdown()  # ✅ self.mt5
        except Exception:
            pass
        
        self._symbol_selected.clear()
        self._cache_simbolos.clear()
        self._tick_cache.clear()
        return self.conectar()

    # ============================================================
    # OBTENCIÓN DE DATOS (✅ USANDO self.mt5)
    # ============================================================

    def validar_frescura(self, df, timeframe):
        """Valida si los datos están frescos."""
        if df is None or len(df) == 0:
            return False
        
        ultima_fecha = df.index[-1]
        if ultima_fecha.tzinfo is None:
            ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
        
        antiguedad = (datetime.now(timezone.utc) - ultima_fecha).total_seconds() / 60
        
        max_antiguedad = timeframe * 2
        
        return antiguedad < max_antiguedad

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def obtener_datos(self, simbolo, n_velas=100, timeframe=None):
        self._throttle()
        
        if not self.conectado:
            return None
        
        if not self._seleccionar_simbolo(simbolo):
            return None
        
        tf = timeframe or Config.TIMEFRAME
        cache_key = (simbolo, tf)
        
        ultima_fecha = None
        df_sqlite = None
        
        if self.almacen:
            df_sqlite = self.almacen.obtener_datos_historicos(simbolo, tf)
            if df_sqlite is not None and not df_sqlite.empty:
                ultima_fecha = df_sqlite.index[-1]
                antiguedad = (datetime.now(timezone.utc) - ultima_fecha).total_seconds() / 60
                self.logger.info(f"📊 {simbolo} TF{tf}: Última vela en SQLite: {ultima_fecha} ({antiguedad:.1f} min) - {len(df_sqlite)} velas")
        
        if ultima_fecha is not None:
            df_nuevo = self._descargar_incremental(simbolo, tf, ultima_fecha, n_velas)
            
            if df_nuevo is not None and len(df_nuevo) > 0:
                if df_sqlite is not None and len(df_sqlite) > 0:
                    if df_sqlite.index.tz is None:
                        df_sqlite.index = df_sqlite.index.tz_localize('UTC')
                    if df_nuevo.index.tz is None:
                        df_nuevo.index = df_nuevo.index.tz_localize('UTC')
                    
                    df_combinado = pd.concat([df_sqlite, df_nuevo])
                    df_combinado = df_combinado[~df_combinado.index.duplicated(keep='last')]
                    df_combinado = df_combinado.sort_index()
                    
                    MAX_VELAS = 50000
                    if len(df_combinado) > MAX_VELAS:
                        df_combinado = df_combinado.iloc[-MAX_VELAS:]
                    
                    self._cache_simbolos_data[cache_key] = df_combinado
                    return df_combinado
                else:
                    self._cache_simbolos_data[cache_key] = df_nuevo
                    return df_nuevo
            else:
                if df_sqlite is not None and len(df_sqlite) > 0:
                    self.logger.warning(f"⚠️ {simbolo} TF{tf}: No hay datos nuevos desde {ultima_fecha}")
                    self._cache_simbolos_data[cache_key] = df_sqlite
                    return df_sqlite
                return None
        
        self.logger.info(f"📥 {simbolo} TF{tf}: Primera descarga...")
        return self._descargar_completo(simbolo, tf, n_velas)

    def obtener_margen(self, simbolo: str, volumen: float, precio: float) -> float:
        if not self.conectado:
            return 0.0
        
        try:
            margen = self.mt5.order_calc_margin(  # ✅ self.mt5
                action=self.mt5.TRADE_ACTION_DEAL,
                symbol=simbolo,
                volume=volumen,
                price=precio
            )
            
            if margen and margen > 0:
                self.logger.info(f"📊 {simbolo}: Margen REAL: ${margen:.2f}")
                return float(margen)
            
            info = self.mt5.symbol_info(simbolo)  # ✅ self.mt5
            if info and hasattr(info, 'margin_initial'):
                margin_initial = float(info.margin_initial or 0)
                if margin_initial > 0:
                    margen_ajustado = margin_initial * volumen * (precio / info.trade_tick_size)
                    return float(margen_ajustado)
            
            self.logger.warning(f"⚠️ {simbolo}: No se pudo obtener margen de MT5")
            return 0.0
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo margen de {simbolo}: {e}")
            return 0.0

    def calcular_margen(self, simbolo: str, lotes: float, precio: float) -> float:
        if not self.conectado:
            return 0.0
        
        try:
            margen = self.mt5.order_calc_margin(  # ✅ self.mt5
                action=self.mt5.TRADE_ACTION_DEAL,
                symbol=simbolo,
                volume=lotes,
                price=precio
            )
            
            return float(margen) if margen else 0.0
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error calculando margen: {e}")
            return 0.0

    def _descargar_completo(self, simbolo: str, tf: int, n_velas: int) -> Optional[pd.DataFrame]:
        try:
            rates = self.mt5.copy_rates_from_pos(simbolo, tf, 0, n_velas)  # ✅ self.mt5
            
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
        
        try:
            fecha_desde = datetime.now(timezone.utc) - timedelta(days=90)
            fecha_hasta = datetime.now(timezone.utc)
            rates = self.mt5.copy_rates_range(simbolo, tf, fecha_desde, fecha_hasta)  # ✅ self.mt5
            
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
        
        try:
            rates_m5 = self.mt5.copy_rates_from_pos(simbolo, 5, 0, 30000)  # ✅ self.mt5
            
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

    def _descargar_incremental(self, simbolo, tf, ultima_fecha, n_velas):
        if ultima_fecha.tzinfo is None:
            ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
        else:
            ultima_fecha = ultima_fecha.astimezone(timezone.utc)
        
        fecha_desde = ultima_fecha + timedelta(minutes=1)
        fecha_hasta = datetime.now(timezone.utc)
        
        self.logger.info(f"📥 {simbolo} TF{tf}: Descargando desde {fecha_desde} hasta {fecha_hasta}")
        
        try:
            rates = self.mt5.copy_rates_range(simbolo, tf, fecha_desde, fecha_hasta)  # ✅ self.mt5
            
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                df.set_index('time', inplace=True)
                df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
                
                self.logger.info(f"✅ {simbolo} TF{tf}: {len(df)} velas nuevas descargadas")
                
                if self.almacen:
                    self.almacen.guardar_datos_historicos(simbolo, tf, df)
                
                return df
            else:
                self.logger.info(f"ℹ️ {simbolo} TF{tf}: No hay datos nuevos desde {fecha_desde}")
                return None
        except Exception as e:
            self.logger.warning(f"⚠️ {simbolo} TF{tf}: Error en copy_rates_range: {e}")
            
            try:
                rates = self.mt5.copy_rates_from_pos(simbolo, tf, 0, n_velas)  # ✅ self.mt5
                
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
        import time
        import MetaTrader5 as mt5  # ❌ ESTE DEBE SER self.mt5
        # ✅ CORRECCIÓN: Usar self.mt5
        metodos = [
            ('copy_rates_from_pos', lambda: self.mt5.copy_rates_from_pos(simbolo, timeframe, 0, n_velas)),
            ('copy_rates_range', lambda: self.mt5.copy_rates_range(
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
                        
                        df = pd.DataFrame(rates)
                        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                        df.set_index('time', inplace=True)
                        df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
                        
                        return df
                        
                except Exception as e:
                    self.logger.debug(f"⚠️ {simbolo} TF{timeframe}: {nombre_metodo} intento {intento+1} falló: {e}")
                    time.sleep(0.5)
        
        return None

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def obtener_datos_desde_fecha(self, simbolo: str, fecha_desde: datetime, n_velas: int = 250, timeframe: int = None) -> Optional[pd.DataFrame]:
        self._throttle()
        
        if not self.conectado:
            self.logger.warning(f"⚠️ {simbolo}: No conectado a MT5")
            return None
        
        if not self._seleccionar_simbolo(simbolo):
            self.logger.warning(f"⚠️ {simbolo}: No se pudo seleccionar en Market Watch")
            return None

        tf = timeframe or Config.TIMEFRAME
        
        if fecha_desde.tzinfo is None:
            fecha_desde = fecha_desde.replace(tzinfo=timezone.utc)
        else:
            fecha_desde = fecha_desde.astimezone(timezone.utc)
        
        fecha_hasta = datetime.now(timezone.utc)
        
        self.logger.info(f"📥 {simbolo}: Descargando desde {fecha_desde.strftime('%Y-%m-%d %H:%M')} hasta ahora (TF{tf})")
        
        try:
            rates = self.mt5.copy_rates_range(simbolo, tf, fecha_desde, fecha_hasta)  # ✅ self.mt5
            
            if rates is None or len(rates) == 0:
                self.logger.warning(f"⚠️ {simbolo}: No hay nuevos datos desde {fecha_desde.strftime('%Y-%m-%d %H:%M')}")
                return None
            
            self.logger.info(f"✅ {simbolo}: {len(rates)} velas descargadas desde {fecha_desde.strftime('%Y-%m-%d %H:%M')}")
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df.set_index('time', inplace=True)
            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
            
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
            getattr(self.mt5, "SYMBOL_CALC_MODE_FOREX", None),  # ✅ self.mt5
            getattr(self.mt5, "SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE", None),  # ✅ self.mt5
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

    def _es_horario_cerrado(self, simbolo: str, fecha=None):
        """Verifica si el mercado está cerrado para un símbolo."""
        try:
            simbolo_upper = simbolo.upper()
            if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                return False
            
            if fecha is None:
                ahora = datetime.now().astimezone(timezone.utc)
            else:
                ahora = fecha.astimezone(timezone.utc)
            
            hora_col = ahora.astimezone(timezone(timedelta(hours=-5)))
            weekday_col = hora_col.weekday()
            
            if weekday_col == 5:
                return True
            
            if weekday_col == 6:
                hora_col_float = hora_col.hour + hora_col.minute / 60.0
                
                if self._es_forex(simbolo_upper):
                    return hora_col_float < 17.0
                
                if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                    return hora_col_float < 18.0
                
                return True
            
            if weekday_col == 4:
                hora_col_float = hora_col.hour + hora_col.minute / 60.0
                
                if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                    return hora_col_float >= 16.0
                
                if self._es_forex(simbolo_upper):
                    return hora_col_float >= 17.0
            
            return False
        except Exception as e:
            self.logger.debug(f"⚠️ Error verificando horario: {e}")
            return False

    def _es_forex(self, simbolo: str) -> bool:
        pares_forex = [
            'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF',
            'EURGBP', 'EURJPY', 'GBPJPY', 'AUDJPY', 'EURNZD', 'GBPAUD',
            'EURCHF', 'GBPCHF', 'AUDCAD', 'AUDCHF', 'AUDNZD', 'CADJPY',
            'CHFJPY', 'EURAUD', 'EURCAD', 'GBPAUD', 'GBPCAD', 'GBPCHF',
            'NZDJPY', 'NZDUSD', 'USDSGD', 'USDHKD', 'USDMXN', 'USDZAR'
        ]
        return simbolo in pares_forex

    def _es_indice(self, simbolo: str) -> bool:
        indices = ['US30', 'NAS100', 'US500', 'SP500', 'GER40', 'UK100', 'DAX', 'SPX']
        return any(x in simbolo for x in indices)

    def _es_metal(self, simbolo: str) -> bool:
        metales = ['XAU', 'XAG', 'XPT', 'XPD']
        return any(x in simbolo for x in metales)

    def obtener_precio(self, simbolo):
        self.logger.info(f"📥 {simbolo}: Iniciando obtener_precio()")

        if not self.verificar_conexion():
            self.logger.error(f"❌ {simbolo}: MT5 no conectado")
            return None

        max_wait = 3.0
        poll_interval = 0.15
        deadline = time.monotonic() + max_wait
        intento = 0

        while time.monotonic() < deadline:
            intento += 1

            try:
                if not self._seleccionar_simbolo(simbolo):
                    self.logger.debug(f"⚠️ {simbolo}: _seleccionar_simbolo falló (intento {intento})")
                    time.sleep(poll_interval)
                    continue

                info = self.mt5.symbol_info(simbolo)  # ✅ self.mt5
                if info is None:
                    self.logger.debug(f"⚠️ {simbolo}: symbol_info=None (intento {intento})")
                    time.sleep(poll_interval)
                    continue

                point = float(getattr(info, "point", 0.0) or 0.0)
                if point <= 0:
                    self.logger.warning(f"⚠️ {simbolo}: point inválido {point}")
                    time.sleep(poll_interval)
                    continue

                tick = self.mt5.symbol_info_tick(simbolo)  # ✅ self.mt5
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
                    simbolo_upper = simbolo.upper()
                    if simbolo_upper in ['USDCAD', 'AUDCAD', 'NZDCAD', 'NZDJPY', 'AUDNZD']:
                        self.logger.debug(f"⏳ {simbolo}: BID==ASK pero símbolo exótico, usando punto mínimo")
                        spread_price = point
                        spread_points = 1.0
                        spread_pips = spread_price / point if point > 0 else 0
                        
                        self.logger.info(f"✅ {simbolo}: Tick obtenido (spread=0, usando fallback)")
                        self.logger.info(f"   BID={bid:.{info.digits}f} | ASK={ask:.{info.digits}f} | spread={spread_price:.{info.digits}f} | {spread_points:.1f} points | {spread_pips:.2f} pips")

                        return {
                            "bid": bid,
                            "ask": ask,
                            "spread": spread_price,
                            "spread_price": spread_price,
                            "spread_points": spread_points,
                            "spread_pips": spread_pips,
                            "point": point,
                            "pip_size": self._pip_size_simbolo(simbolo, info),
                            "tick_size": float(getattr(info, "trade_tick_size", 0.0) or 0.0),
                            "digits": int(info.digits),
                            "timestamp": time.time(),
                            "tick_time": getattr(tick, "time", None),
                            "tick_time_msc": getattr(tick, "time_msc", None),
                            "fuente": "symbol_info_tick (spread=0 fallback)",
                        }
                    
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

    def _obtener_filling_mode(self, simbolo: str) -> int:
        info = self._get_symbol_info(simbolo)
        if not info:
            return self.mt5.ORDER_FILLING_IOC  # ✅ self.mt5
        
        filling = info.filling_mode
        try:
            if filling == self.mt5.SYMBOL_FILLING_MODE_FOK:  # ✅ self.mt5
                return self.mt5.ORDER_FILLING_FOK  # ✅ self.mt5
            elif filling == self.mt5.SYMBOL_FILLING_MODE_IOC:  # ✅ self.mt5
                return self.mt5.ORDER_FILLING_IOC  # ✅ self.mt5
            elif filling == self.mt5.SYMBOL_FILLING_MODE_RETURN:  # ✅ self.mt5
                return self.mt5.ORDER_FILLING_RETURN  # ✅ self.mt5
        except AttributeError:
            pass
        return self.mt5.ORDER_FILLING_IOC  # ✅ self.mt5

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def enviar_orden(self, simbolo: str, tipo: str, volumen: float, sl: float, tp: float, comentario: str = "", **kwargs):
        tipo_normalizado = tipo.upper().strip()
        
        if tipo_normalizado in ['COMPRA', 'BUY', 'LONG']:
            order_type = self.mt5.ORDER_TYPE_BUY  # ✅ self.mt5
            direccion = 'COMPRA'
        elif tipo_normalizado in ['VENTA', 'SELL', 'SHORT']:
            order_type = self.mt5.ORDER_TYPE_SELL  # ✅ self.mt5
            direccion = 'VENTA'
        else:
            return {'retcode': -1, 'comentario': f"Dirección inválida: {tipo}"}
        
        info = self.mt5.symbol_info(simbolo)  # ✅ self.mt5
        if info is None:
            return {'retcode': -1, 'comentario': f"Símbolo inválido: {simbolo}"}
        
        tick = self.mt5.symbol_info_tick(simbolo)  # ✅ self.mt5
        if tick is None:
            return {'retcode': -1, 'comentario': f"No se pudo obtener tick para {simbolo}"}
        
        if direccion == 'COMPRA':
            if sl >= tick.ask:
                return {'retcode': -1, 'comentario': f"SL inválido para COMPRA: SL={sl} >= ask={tick.ask}"}
            if tp <= tick.ask:
                return {'retcode': -1, 'comentario': f"TP inválido para COMPRA: TP={tp} <= ask={tick.ask}"}
        else:
            if sl <= tick.bid:
                return {'retcode': -1, 'comentario': f"SL inválido para VENTA: SL={sl} <= bid={tick.bid}"}
            if tp >= tick.bid:
                return {'retcode': -1, 'comentario': f"TP inválido para VENTA: TP={tp} >= bid={tick.bid}"}
        
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,  # ✅ self.mt5
            "symbol": simbolo,
            "volume": float(volumen),
            "type": order_type,
            "price": tick.ask if direccion == 'COMPRA' else tick.bid,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": kwargs.get('magic_number', getattr(self, 'magic_number', 0)),
            "comment": comentario,
            "type_time": self.mt5.ORDER_TIME_GTC,  # ✅ self.mt5
            "type_filling": self.mt5.ORDER_FILLING_IOC,  # ✅ self.mt5
        }
        
        result = self.mt5.order_send(request)  # ✅ self.mt5
        
        if result is None:
            return {'retcode': -1, 'comentario': "Error desconocido en MT5"}
        
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:  # ✅ self.mt5
            return {
                'retcode': result.retcode,
                'comentario': f"Error {result.retcode}: {result.comment}",
                'ticket': None
            }
        
        return {
            'retcode': result.retcode,
            'ticket': result.order,
            'precio': result.price,
            'sl': request['sl'],
            'tp': request['tp'],
            'comentario': result.comment
        }

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def cerrar_posicion(self, ticket):
        if not self.conectado:
            return False
        if not ticket:
            self.logger.error("❌ Ticket inválido para cerrar")
            return False
        
        pos = self.mt5.positions_get(ticket=ticket)  # ✅ self.mt5
        if not pos:
            self.logger.warning(f"Posición {ticket} no encontrada")
            return False
        
        pos = pos[0]
        for intento in range(3):
            tick = self.mt5.symbol_info_tick(pos.symbol)  # ✅ self.mt5
            if not tick:
                continue
            
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,  # ✅ self.mt5
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": self.mt5.ORDER_TYPE_SELL if pos.type == 0 else self.mt5.ORDER_TYPE_BUY,  # ✅ self.mt5
                "position": ticket,
                "price": tick.bid if pos.type == 0 else tick.ask,
                "deviation": self._obtener_deviation(pos.symbol),
                "magic": self.magic,
                "comment": "Cierre Bot",
                "type_time": self.mt5.ORDER_TIME_GTC,  # ✅ self.mt5
                "type_filling": self._obtener_filling_mode(pos.symbol),
            }
            result = self.mt5.order_send(request)  # ✅ self.mt5
            if result and result.retcode == self.mt5.TRADE_RETCODE_DONE:  # ✅ self.mt5
                self.logger.info(f"✅ Posición {ticket} cerrada correctamente")
                return True
            if result and result.retcode in [self.mt5.TRADE_RETCODE_REQUOTE, self.mt5.TRADE_RETCODE_PRICE_OFF]:  # ✅ self.mt5
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
        
        pos = self.mt5.positions_get(ticket=ticket)  # ✅ self.mt5
        if not pos:
            return False
        
        pos = pos[0]
        volumen_a_cerrar = max(0.01, round(volumen_a_cerrar, 2))
        
        if volumen_a_cerrar >= pos.volume:
            return self.cerrar_posicion(ticket)
        
        for intento in range(3):
            tick = self.mt5.symbol_info_tick(pos.symbol)  # ✅ self.mt5
            if not tick:
                continue
            
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,  # ✅ self.mt5
                "symbol": pos.symbol,
                "volume": volumen_a_cerrar,
                "type": self.mt5.ORDER_TYPE_SELL if pos.type == 0 else self.mt5.ORDER_TYPE_BUY,  # ✅ self.mt5
                "position": ticket,
                "price": tick.bid if pos.type == 0 else tick.ask,
                "deviation": self._obtener_deviation(pos.symbol),
                "magic": self.magic,
                "comment": "Cierre Parcial",
                "type_time": self.mt5.ORDER_TIME_GTC,  # ✅ self.mt5
                "type_filling": self._obtener_filling_mode(pos.symbol),
            }
            result = self.mt5.order_send(request)  # ✅ self.mt5
            if result and result.retcode == self.mt5.TRADE_RETCODE_DONE:  # ✅ self.mt5
                self.logger.info(f"✅ Cierre parcial {volumen_a_cerrar} de {ticket} exitoso")
                return True
            if result and result.retcode in [self.mt5.TRADE_RETCODE_REQUOTE, self.mt5.TRADE_RETCODE_PRICE_OFF]:  # ✅ self.mt5
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
        
        pos = self.mt5.positions_get(ticket=ticket)  # ✅ self.mt5
        if not pos:
            return False
        
        pos = pos[0]
        info = self._get_symbol_info(pos.symbol)
        digits = info.digits if info else 5

        for intento in range(3):
            request = {
                "action": self.mt5.TRADE_ACTION_SLTP,  # ✅ self.mt5
                "position": ticket,
                "sl": round(nuevo_sl, digits),
                "tp": pos.tp
            }
            result = self.mt5.order_send(request)  # ✅ self.mt5
            if result and result.retcode == self.mt5.TRADE_RETCODE_DONE:  # ✅ self.mt5
                self.logger.info(f"✅ SL modificado para {ticket} a {nuevo_sl:.{digits}f}")
                return True
            if result and result.retcode in [self.mt5.TRADE_RETCODE_REQUOTE, self.mt5.TRADE_RETCODE_PRICE_OFF]:  # ✅ self.mt5
                time.sleep(0.1)
                continue
            break
        
        self.logger.error(f"❌ Fallo al modificar SL para {ticket}")
        return False

    @retry_mt5(max_retries=20, base_delay=0.1, max_delay=5.0)
    def obtener_detalle_cierre(self, ticket):
        if not self.conectado or not ticket:
            return None
        
        deals = self.mt5.history_deals_get(position=ticket)  # ✅ self.mt5
        if deals is None or len(deals) == 0:
            return None

        ganancia, comision, swap, precio_salida, time_salida = 0.0, 0.0, 0.0, 0.0, None
        for d in deals:
            ganancia += d.profit
            comision += d.commission
            swap += d.swap
            if d.entry in [self.mt5.DEAL_ENTRY_OUT, self.mt5.DEAL_ENTRY_INOUT, self.mt5.DEAL_ENTRY_OUT_BY]:  # ✅ self.mt5
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
        
        account = self.mt5.account_info()  # ✅ self.mt5
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
            return self.mt5.screen_shot(simbolo, tf, str(ruta_archivo))  # ✅ self.mt5
        except Exception as e:
            self.logger.error(f"Error al tomar captura de {simbolo}: {e}")
            return False

    def obtener_posiciones(self, simbolo=None, force=False):
        if not self.conectado:
            return []

        ahora = time.time()
        if not force and (ahora - self._last_pos_sync) < 1.0:
            if simbolo is None:
                return self._cache_posiciones
            else:
                return [p for p in self._cache_posiciones if p['simbolo'] == simbolo]

        try:
            positions = self.mt5.positions_get()  # ✅ self.mt5
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
                    'ganancia': p.profit,  # ✅ P&L en USD de MT5
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
        self.mt5.shutdown()  # ✅ self.mt5
        self.conectado = False
        self._symbol_selected.clear()
        self._cache_simbolos.clear()
        self._tick_cache.clear()
        self.logger.info("🔒 Desconectado de MT5")

    def obtener_historial_operaciones(self, 
                                   fecha_desde=None,
                                   fecha_hasta=None,
                                   simbolo=None):
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
            deals = self.mt5.history_deals_get(desde_ts, hasta_ts, symbol=simbolo)  # ✅ self.mt5
            
            if deals is not None and len(deals) > 0:
                self.logger.info(f"📊 MT5: {len(deals)} deals obtenidos")
                
                for deal in deals:
                    try:
                        ticket = deal.order if hasattr(deal, 'order') else deal.deal
                        deal_id = deal.deal if hasattr(deal, 'deal') else deal.order
                        
                        if deal.type in [self.mt5.DEAL_TYPE_BUY, self.mt5.DEAL_TYPE_BUY_STOP, self.mt5.DEAL_TYPE_BUY_LIMIT]:  # ✅ self.mt5
                            direccion = 'COMPRA'
                        elif deal.type in [self.mt5.DEAL_TYPE_SELL, self.mt5.DEAL_TYPE_SELL_STOP, self.mt5.DEAL_TYPE_SELL_LIMIT]:  # ✅ self.mt5
                            direccion = 'VENTA'
                        else:
                            direccion = 'DESCONOCIDO'
                        
                        if deal.entry in [self.mt5.DEAL_ENTRY_IN, self.mt5.DEAL_ENTRY_INOUT]:  # ✅ self.mt5
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
                            'ganancia': deal.profit,  # ✅ P&L de MT5
                            'comision': deal.commission,
                            'swap': deal.swap,
                            'timestamp': datetime.fromtimestamp(deal.time, tz=timezone.utc).isoformat(),
                            'magic': deal.magic,
                            'estado': estado,
                            'tipo': 'DEAL',
                            'entry_type': 'IN' if deal.entry in [self.mt5.DEAL_ENTRY_IN, self.mt5.DEAL_ENTRY_INOUT] else 'OUT',  # ✅ self.mt5
                        }
                        operaciones.append(op)
                        
                    except Exception as e:
                        self.logger.debug(f"Error procesando deal: {e}")
                        continue
            else:
                self.logger.debug("📭 No se obtuvieron deals de MT5")
            
            try:
                positions = self.mt5.positions_get(symbol=simbolo)  # ✅ self.mt5
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
                orders = self.mt5.orders_get(symbol=simbolo)  # ✅ self.mt5
                if orders is not None and len(orders) > 0:
                    self.logger.info(f"📊 MT5: {len(orders)} órdenes pendientes obtenidas")
                    for order in orders:
                        if order.magic == self.magic or self.magic == 0:
                            op = {
                                'ticket': order.ticket,
                                'simbolo': order.symbol,
                                'direccion': 'COMPRA' if order.type in [self.mt5.ORDER_TYPE_BUY, self.mt5.ORDER_TYPE_BUY_LIMIT, self.mt5.ORDER_TYPE_BUY_STOP] else 'VENTA',  # ✅ self.mt5
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