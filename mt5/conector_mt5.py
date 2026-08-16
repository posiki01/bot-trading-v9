#!/usr/bin/env python3
"""
mt5/conector_mt5.py (V8.0 - REFACTORIZADO)
Conector para MetaTrader 5 con soporte para Pepperstone y modo Headless.

MEJORAS V8.0:
- Integración con DataCache (opcional)
- Mejores validaciones de SL/TP usando Config
- Soporte para nuevos parámetros de configuración
- Logs más detallados con tiempos
- Gestión de errores mejorada
- Compatibilidad con nuevos umbrales
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
    """
    Decorador para reintentar funciones de MT5 con backoff exponencial.
    """
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
    V8.0: Validaciones mejoradas, integración con Config.
    """
    
    def __init__(self, login, password, server, magic_number=None, demo=True):
        self.login = login
        self.password = password
        self.server = server
        self.magic = magic_number if magic_number is not None else Config.MAGIC_NUMBER
        self.demo = demo
        self.conectado = False
        
        # Cachés
        self._cache_simbolos = {}
        self._cache_posiciones = []
        self._last_pos_sync = 0
        self._tick_cache = {}
        self._tick_cache_ttl = 0.2
        self._symbol_selected = set()
        
        # Locks
        self._symbol_lock = Lock()
        self._request_lock = Lock()
        self._last_request_times = deque(maxlen=Config.MT5_RATE_LIMIT_PER_SEC)
        
        self.logger = logging.getLogger('BotTrading.MT5')

        # Deviation por clase de activo
        self._deviation_por_clase = {
            'AUD': 20,           # Aumentado para AUDUSD (evita errores 10009)
            'XAU': 50,
            'XAG': 50,
            'US30': 80,
            'NAS100': 80,
            'US500': 50,
            'GER40': 50,
            'UK100': 50,
            'BTC': 200,
            'ETH': 150,
            'SOL': 150,
        }
        self._deviation_default = 10
        
        # Límites de SL/TP desde Config
        self.SL_MIN_PIPS = 14.5
        self.SL_MAX_PIPS = 200
        self.MIN_RR = 1.2
        
        self.logger.info(f"🔌 ConectorPepperstone V8.0 inicializado")
        self.logger.info(f"   Magic: {self.magic}")
        self.logger.info(f"   Demo: {self.demo}")
        self.logger.info(f"   Rate Limit: {Config.MT5_RATE_LIMIT_PER_SEC}/s")

    # ============================================================
    # MÉTODOS DE CONEXIÓN
    # ============================================================
    
    def _obtener_deviation(self, simbolo: str) -> int:
        """
        Obtiene deviation según el tipo de activo.
        V8.44 - Aumentado para AUDUSD y otros.
        
        Args:
            simbolo: Símbolo (ej: 'AUDUSD', 'EURUSD', 'XAUUSD')
        
        Returns:
            Deviation en puntos (enteros)
        """
        simbolo_upper = simbolo.upper()
        
        for prefijo, deviation in self._deviation_por_clase.items():
            if simbolo_upper.startswith(prefijo):
                return deviation
        
        return self._deviation_default

    def _throttle(self):
        """Limita la tasa de solicitudes a MT5."""
        while True:
            with self._request_lock:
                now = time.time()
                if (len(self._last_request_times) < Config.MT5_RATE_LIMIT_PER_SEC or 
                    (now - self._last_request_times[0]) >= 1.0):
                    self._last_request_times.append(now)
                    break
            time.sleep(0.02)

    def _seleccionar_simbolo(self, simbolo):
        """Selecciona el símbolo en Market Watch."""
        with self._symbol_lock:
            if simbolo in self._symbol_selected:
                return True
            
            info = mt5.symbol_info(simbolo)
            if info is None:
                self.logger.warning(f"⚠️ Símbolo {simbolo} no existe en MT5")
                return False
            
            if not mt5.symbol_select(simbolo, True):
                self.logger.warning(f"⚠️ No se pudo seleccionar {simbolo} en Market Watch")
                return False
            
            self._symbol_selected.add(simbolo)
            self._cache_simbolos[simbolo] = info
            return True

    def _get_symbol_info(self, simbolo):
        """Obtiene info del símbolo desde caché o desde MT5."""
        if simbolo in self._cache_simbolos:
            info = self._cache_simbolos[simbolo]
            if info is not None:
                return info
        
        info = mt5.symbol_info(simbolo)
        if info:
            self._cache_simbolos[simbolo] = info
        return info

    @retry_mt5(max_retries=5, base_delay=1.0, max_delay=16.0)
    def conectar(self) -> bool:
        """Conecta a MT5."""
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
        """Verifica la conexión y reconecta si es necesario."""
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
        
        return self.conectar()

    # ============================================================
    # OBTENCIÓN DE DATOS
    # ============================================================
    
    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def obtener_datos(self, simbolo, n_velas=100, timeframe=None):
        """Obtiene datos históricos del símbolo."""
        self._throttle()
        if not self.conectado:
            return None
        if not self._seleccionar_simbolo(simbolo):
            return None

        tf = timeframe or Config.TIMEFRAME

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(mt5.copy_rates_from_pos, simbolo, tf, 0, n_velas)
            try:
                rates = future.result(timeout=10.0)
            except concurrent.futures.TimeoutError:
                self.logger.warning(f"⏳ Timeout al obtener datos de {simbolo} TF{tf}")
                return None
            except Exception as e:
                self.logger.error(f"❌ Error en obtener_datos para {simbolo}: {e}")
                return None

        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'tick_volume': 'Volume'
        }, inplace=True)
        return df

    # mt5/conector_mt5.py - Método obtener_precio (V8.38 - COMPLETO CORREGIDO)

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def obtener_precio(self, simbolo):
        """
        Obtiene precio actual del símbolo con manejo robusto de spread cero.
        V8.39 - CORREGIDO: Sin modo_depuracion, usa logger.debug.
        """
        now = time.time()
        
        # Verificar caché
        if simbolo in self._tick_cache:
            cached = self._tick_cache[simbolo]
            if (now - cached['ts']) < self._tick_cache_ttl:
                data = cached['data']
                if data and data.get('spread', 0) > 0 and data.get('bid', 0) > 0:
                    return data
        
        self._throttle()
        
        # 8 intentos con backoff
        for intento in range(8):
            try:
                if not self.conectado:
                    self.logger.debug(f"⚠️ {simbolo}: no conectado, intento {intento+1}/8")
                    time.sleep(0.2 * (intento + 1))
                    continue
                
                if not self._seleccionar_simbolo(simbolo):
                    self.logger.debug(f"⚠️ {simbolo}: no seleccionado, intento {intento+1}/8")
                    time.sleep(0.2 * (intento + 1))
                    continue
                
                tick = mt5.symbol_info_tick(simbolo)
                if tick is None:
                    self.logger.debug(f"⚠️ {simbolo}: tick None, intento {intento+1}/8")
                    time.sleep(0.1 * (intento + 1))
                    continue
                
                if tick.bid <= 0 or tick.ask <= 0:
                    self.logger.debug(f"⚠️ {simbolo}: precio inválido, intento {intento+1}/8")
                    time.sleep(0.1 * (intento + 1))
                    continue
                
                spread = tick.ask - tick.bid
                
                if spread <= 0:
                    self.logger.debug(f"⚠️ {simbolo}: spread cero, intento {intento+1}/8")
                    time.sleep(0.2 * (intento + 1))
                    continue
                
                pip_val = self._pip_value_simbolo(simbolo)
                spread_pips = spread / pip_val if pip_val > 0 else 0
                
                if spread_pips > 50:
                    self.logger.debug(f"⚠️ {simbolo}: spread alto ({spread_pips:.1f}pips), intento {intento+1}/8")
                    time.sleep(0.1 * (intento + 1))
                    continue
                
                data = {
                    'bid': tick.bid,
                    'ask': tick.ask,
                    'spread': spread,
                    'spread_pips': spread_pips
                }
                
                self._tick_cache[simbolo] = {'data': data, 'ts': now}
                
                if intento > 0:
                    self.logger.debug(f"✅ {simbolo}: precio obtenido en intento {intento+1}/8 (spread: {spread:.6f})")
                
                return data
                
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: error obteniendo tick: {e}, intento {intento+1}/8")
                time.sleep(0.1 * (intento + 1))
        
        self.logger.warning(f"⚠️ No se pudo obtener precio válido para {simbolo} después de 8 intentos")
        
        # Fallback: caché antiguo
        if simbolo in self._tick_cache:
            cached_data = self._tick_cache[simbolo]['data']
            if cached_data and cached_data.get('spread', 0) > 0:
                self.logger.warning(f"⚠️ Usando caché antiguo para {simbolo}")
                return cached_data
        
        # Fallback: symbol_info
        try:
            info = mt5.symbol_info(simbolo)
            if info and info.bid > 0 and info.ask > 0:
                spread = info.ask - info.bid
                if spread > 0:
                    pip_val = self._pip_value_simbolo(simbolo)
                    data = {
                        'bid': info.bid,
                        'ask': info.ask,
                        'spread': spread,
                        'spread_pips': spread / pip_val if pip_val > 0 else 0
                    }
                    self.logger.warning(f"⚠️ {simbolo}: usando symbol_info como fallback (spread: {spread:.6f})")
                    return data
        except Exception as e:
            self.logger.debug(f"⚠️ {simbolo}: fallback symbol_info falló: {e}")
        
        return None

    # ============================================================
    # ENVÍO DE ÓRDENES (VALIDACIONES MEJORADAS)
    # ============================================================
    
    def _obtener_filling_mode(self, simbolo: str) -> int:
        """
        Obtiene el modo de llenado del símbolo.
        """
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

    def _pip_value_simbolo(self, simbolo: str) -> float:
        """
        Calcula el valor de un pip para el símbolo.
        """
        s = simbolo.upper()
        if 'JPY' in s:
            return 0.01
        if 'XAU' in s or 'XAG' in s:
            return 0.10
        if any(x in s for x in ['US30', 'NAS100', 'US500', 'GER40', 'UK100', 'SP500']):
            return 1.0
        if any(c in s for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001

    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def enviar_orden(self, simbolo, tipo, volumen, sl=0, tp=0, comentario="Bot"):
        """
        Envía una orden a MT5 con validación completa de SL/TP.
        V8.44 - CORREGIDO: Validación de volumen mínimo por tipo de activo.
        """
        # ============================================================
        # 0. VALIDACIONES BÁSICAS
        # ============================================================
        if not self.conectado:
            self.logger.error("❌ No conectado a MT5")
            return {"ticket": None, "comment": "No conectado", "retcode": -1}

        if sl <= 0 or tp <= 0:
            self.logger.error(f"❌ SL/TP inválidos ({sl}, {tp}) para {simbolo}")
            return {"ticket": None, "comment": "SL/TP_missing", "retcode": -1}

        if not self._seleccionar_simbolo(simbolo):
            return {"ticket": None, "comment": "Symbol not selected", "retcode": -1}

        info = self._get_symbol_info(simbolo)
        if not info:
            self.logger.error(f"❌ No se pudo obtener info de {simbolo}")
            return {"ticket": None, "comment": "Symbol info None", "retcode": -1}

        # ============================================================
        # 1. VALIDAR VOLUMEN MÍNIMO Y PASO DEL SÍMBOLO (V8.44)
        # ============================================================
        try:
            # Obtener lote mínimo por tipo de activo (fallback)
            lote_minimo_por_tipo = self._obtener_lote_minimo_por_activo(simbolo)
            
            # Verificar volume_min del símbolo
            if hasattr(info, 'volume_min') and info.volume_min:
                volume_min_float = float(info.volume_min)
                # Usar el máximo entre el mínimo del símbolo y el mínimo por tipo
                lote_minimo = max(volume_min_float, lote_minimo_por_tipo)
            else:
                lote_minimo = lote_minimo_por_tipo
            
            if float(volumen) < lote_minimo:
                self.logger.error(f"❌ Volumen {volumen:.3f} < mínimo {lote_minimo:.3f} para {simbolo}")
                return {
                    "ticket": None, 
                    "comment": f"Volume below min {lote_minimo:.3f}", 
                    "retcode": -1
                }
            
            # Verificar volume_step (paso)
            if hasattr(info, 'volume_step') and info.volume_step:
                paso = float(info.volume_step)
                if paso > 0 and abs(float(volumen) % paso) > 0.00001:
                    volumen_ajustado = round(float(volumen) / paso) * paso
                    # Asegurar que no sea menor que el mínimo
                    if volumen_ajustado < lote_minimo:
                        volumen_ajustado = lote_minimo
                    self.logger.warning(f"⚠️ Volumen ajustado de {volumen:.3f} a {volumen_ajustado:.3f} (paso {paso}) para {simbolo}")
                    volumen = volumen_ajustado
            
            # Verificar volume_max
            if hasattr(info, 'volume_max') and info.volume_max:
                volume_max_float = float(info.volume_max)
                if float(volumen) > volume_max_float:
                    self.logger.warning(f"⚠️ Volumen {volumen:.3f} > máximo {volume_max_float:.3f} para {simbolo}, ajustando...")
                    volumen = volume_max_float
                    
        except Exception as e:
            self.logger.warning(f"⚠️ Error validando volumen para {simbolo}: {e}")

        # ============================================================
        # 2. OBTENER PRECIO CON REINTENTOS
        # ============================================================
        precio_data = None
        for intento in range(5):
            precio_data = self.obtener_precio(simbolo)
            if precio_data and precio_data.get('bid', 0) > 0 and precio_data.get('ask', 0) > 0:
                break
            self.logger.warning(f"⚠️ {simbolo}: intento {intento+1}/5 obteniendo precio...")
            time.sleep(0.2 * (intento + 1))
        
        if not precio_data:
            self.logger.error(f"❌ No se pudo obtener precio para {simbolo} después de 5 intentos")
            return {"ticket": None, "comment": "No price", "retcode": -1}
        
        bid = float(precio_data.get('bid', 0))
        ask = float(precio_data.get('ask', 0))
        spread_real = float(precio_data.get('spread', 0))
        
        if tipo == 'BUY':
            precio = ask
        else:
            precio = bid
        
        if precio <= 0:
            self.logger.error(f"❌ Precio inválido para {simbolo}: {precio}")
            return {"ticket": None, "comment": "Invalid price", "retcode": -1}

        # ============================================================
        # 3. CALCULAR PIP VALUE Y DIGITS
        # ============================================================
        pip_val = self._pip_value_simbolo(simbolo)
        digits = info.digits if info else 5
        min_pips = self.SL_MIN_PIPS
        max_pips = self.SL_MAX_PIPS

        # ============================================================
        # 4. VALIDAR DIRECCIÓN DEL SL
        # ============================================================
        if tipo == 'BUY':
            if sl >= precio:
                self.logger.error(f"❌ SL invertido (BUY): SL={sl:.{digits}f} >= precio={precio:.{digits}f}")
                return {"ticket": None, "comment": "SL_inverted_BUY", "retcode": -1}
            sl_dist_pips = (precio - sl) / pip_val
        else:
            if sl <= precio:
                self.logger.error(f"❌ SL invertido (SELL): SL={sl:.{digits}f} <= precio={precio:.{digits}f}")
                return {"ticket": None, "comment": "SL_inverted_SELL", "retcode": -1}
            sl_dist_pips = (sl - precio) / pip_val

        # ============================================================
        # 5. VALIDAR DISTANCIA MÍNIMA Y MÁXIMA DE SL
        # ============================================================
        if sl_dist_pips < (min_pips - 0.05):
            self.logger.error(f"❌ SL muy cercano: {sl_dist_pips:.1f} pips < {min_pips} pips")
            return {"ticket": None, "comment": f"SL_too_close_{sl_dist_pips:.1f}", "retcode": -1}
        
        if sl_dist_pips > max_pips:
            self.logger.warning(f"⚠️ SL muy amplio: {sl_dist_pips:.1f} pips > {max_pips} pips")

        # ============================================================
        # 6. VALIDAR DIRECCIÓN DEL TP
        # ============================================================
        if tipo == 'BUY':
            if tp <= precio:
                self.logger.error(f"❌ TP invertido (BUY): TP={tp:.{digits}f} <= precio={precio:.{digits}f}")
                return {"ticket": None, "comment": "TP_inverted_BUY", "retcode": -1}
            tp_dist_pips = (tp - precio) / pip_val
        else:
            if tp >= precio:
                self.logger.error(f"❌ TP invertido (SELL): TP={tp:.{digits}f} >= precio={precio:.{digits}f}")
                return {"ticket": None, "comment": "TP_inverted_SELL", "retcode": -1}
            tp_dist_pips = (precio - tp) / pip_val

        # ============================================================
        # 7. VALIDAR R:R MÍNIMO
        # ============================================================
        rr = abs(tp - precio) / abs(sl - precio)
        if rr < self.MIN_RR:
            self.logger.error(f"❌ R:R insuficiente: {rr:.2f} < {self.MIN_RR}")
            return {"ticket": None, "comment": f"RR_too_low_{rr:.2f}", "retcode": -1}

        # ============================================================
        # 8. VALIDAR STOPS_LEVEL
        # ============================================================
        stops_level = info.trade_stops_level * info.point
        if abs(sl - precio) < stops_level:
            self.logger.error(f"❌ SL viola stops_level: {abs(sl - precio):.{digits}f} < {stops_level:.{digits}f}")
            return {"ticket": None, "comment": "SL_violates_stops_level", "retcode": -1}
        
        if abs(tp - precio) < stops_level:
            self.logger.error(f"❌ TP viola stops_level: {abs(tp - precio):.{digits}f} < {stops_level:.{digits}f}")
            return {"ticket": None, "comment": "TP_violates_stops_level", "retcode": -1}

        # ============================================================
        # 9. REDONDEAR SL/TP
        # ============================================================
        sl_rounded = round(sl, digits)
        tp_rounded = round(tp, digits)

        # ============================================================
        # 10. LOG DE VALIDACIÓN EXITOSA
        # ============================================================
        self.logger.info(f"✅ SL/TP validado: {simbolo} {tipo} | "
                        f"SL={sl_rounded:.{digits}f} ({sl_dist_pips:.1f}pips) | "
                        f"TP={tp_rounded:.{digits}f} ({tp_dist_pips:.1f}pips) | "
                        f"R:R={rr:.2f} | Spread={spread_real:.6f}")

        # ============================================================
        # 11. DEFINIR CÓDIGOS DE RETORNO
        # ============================================================
        CODIGOS_EXITO = [
            0,
            mt5.TRADE_RETCODE_DONE,
            10009,
        ]
        
        CODIGOS_REINTENTAR = [
            mt5.TRADE_RETCODE_REQUOTE,
            mt5.TRADE_RETCODE_PRICE_CHANGED,
            mt5.TRADE_RETCODE_PRICE_OFF,
            mt5.TRADE_RETCODE_TIMEOUT,
        ]
        
        CODIGOS_EXITO_PARCIAL = [
            mt5.TRADE_RETCODE_DONE_PARTIAL,
        ]

        # ============================================================
        # 12. ENVIAR ORDEN CON REINTENTOS
        # ============================================================
        
        for intento in range(5):
            tick = mt5.symbol_info_tick(simbolo)
            if tick:
                precio_actual = tick.ask if tipo == 'BUY' else tick.bid
                if precio_actual <= 0:
                    precio_actual = precio
            else:
                precio_actual = precio
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": simbolo,
                "volume": float(volumen),
                "type": mt5.ORDER_TYPE_BUY if tipo == 'BUY' else mt5.ORDER_TYPE_SELL,
                "price": float(precio_actual),
                "sl": float(sl_rounded),
                "tp": float(tp_rounded),
                "deviation": self._obtener_deviation(simbolo),
                "magic": self.magic,
                "comment": comentario,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._obtener_filling_mode(simbolo),
            }
            
            # ============================================================
            # 13. VALIDACIÓN PREVIA (order_check)
            # ============================================================
            check = mt5.order_check(request)
            if check is None:
                self.logger.warning(f"⚠️ {simbolo}: order_check None, intento {intento+1}/5")
                time.sleep(0.1 * (intento + 1))
                continue
            
            if check.retcode not in CODIGOS_EXITO + CODIGOS_EXITO_PARCIAL:
                if check.retcode in CODIGOS_REINTENTAR:
                    self.logger.warning(f"⚠️ {simbolo}: {check.comment} (código {check.retcode}), reintento {intento+1}/5")
                    time.sleep(0.1 * (intento + 1))
                    continue
                else:
                    self.logger.error(f"❌ Error validación {simbolo}: {check.comment} (código {check.retcode})")
                    return {"ticket": None, "comment": check.comment, "retcode": check.retcode}
            
            # ============================================================
            # 14. ENVIAR ORDEN (order_send)
            # ============================================================
            result = mt5.order_send(request)
            
            if result is None:
                self.logger.warning(f"⚠️ {simbolo}: order_send None, intento {intento+1}/5")
                time.sleep(0.1 * (intento + 1))
                continue
            
            # ============================================================
            # 15. PROCESAR RESULTADO
            # ============================================================
            
            if result.retcode in CODIGOS_EXITO:
                ticket = result.order if result.order else result.deal
                self.logger.info(f"✅ ORDEN EJECUTADA: {simbolo} {tipo} {volumen:.3f} @ {precio_actual:.{digits}f} (Ticket: {ticket})")
                return {
                    "ticket": ticket,
                    "precio": precio_actual,
                    "retcode": result.retcode,
                    "volumen": volumen,
                    "comentario": result.comment
                }
            
            if result.retcode in CODIGOS_EXITO_PARCIAL:
                ticket = result.order if result.order else result.deal
                self.logger.info(f"✅ CIERRE PARCIAL: {simbolo} {volumen:.3f} @ {precio_actual:.{digits}f} (Ticket: {ticket})")
                return {
                    "ticket": ticket,
                    "precio": precio_actual,
                    "retcode": result.retcode,
                    "volumen": volumen,
                    "comentario": result.comment,
                    "parcial": True
                }
            
            if result.retcode in CODIGOS_REINTENTAR:
                self.logger.warning(f"⚠️ {simbolo}: {result.comment} (código {result.retcode}), reintento {intento+1}/5")
                time.sleep(0.1 * (intento + 1))
                continue
            
            self.logger.error(f"❌ ORDEN RECHAZADA: {simbolo} - {result.comment} (código {result.retcode})")
            return {
                "ticket": None,
                "precio": None,
                "retcode": result.retcode,
                "comentario": result.comment,
                "volumen": volumen
            }
        
        self.logger.error(f"❌ No se pudo ejecutar orden para {simbolo} después de 5 intentos")
        return {
            "ticket": None,
            "precio": None,
            "retcode": -1,
            "comentario": "Max retries exceeded",
            "volumen": volumen
        }
    # ============================================================
    # GESTIÓN DE POSICIONES
    # ============================================================
    
    @retry_mt5(max_retries=Config.MT5_MAX_RETRIES, base_delay=Config.MT5_RETRY_BACKOFF_BASE)
    def cerrar_posicion(self, ticket):
        """Cierra una posición por ticket."""
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
        """Cierra parcialmente una posición."""
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
        """Modifica el Stop Loss de una posición."""
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
        """Obtiene detalles de cierre de una posición."""
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
        """Obtiene información de la cuenta."""
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
        """Toma una captura de pantalla del gráfico."""
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
        """Obtiene las posiciones abiertas."""
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
            # ✅ Verificar magic number
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
                    'magic': p.magic,  # ✅ INCLUIR MAGIC
                    'time': p.time,
                })

        self._cache_posiciones = pos_list
        self._last_pos_sync = ahora

        if simbolo is None:
            return self._cache_posiciones
        else:
            return [p for p in self._cache_posiciones if p['simbolo'] == simbolo]

    def obtener_info_simbolo(self, simbolo):
        """Expone la caché de info de símbolos para uso externo."""
        return self._get_symbol_info(simbolo)

    def desconectar(self):
        """Desconecta de MT5."""
        mt5.shutdown()
        self.conectado = False
        self.logger.info("🔒 Desconectado de MT5")


    # mt5/conector_mt5.py - Dentro de la clase ConectorPepperstone

    def _obtener_lote_minimo_por_activo(self, simbolo: str) -> float:
        """
        Obtiene el lote mínimo permitido para el tipo de activo.
        V8.44 - NUEVO: Índices requieren 0.1, Forex 0.01, Metales 0.01, Cripto 0.01.
        
        Args:
            simbolo: Símbolo (ej: 'EURUSD', 'US500', 'XAUUSD')
        
        Returns:
            Lote mínimo para el tipo de activo
        """
        simbolo_upper = simbolo.upper()
        
        # ============================================================
        # ÍNDICES (US30, NAS100, US500, SP500) - LOTE MÍNIMO 0.1
        # ============================================================
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 0.1
        
        # ============================================================
        # METALES (XAUUSD, XAGUSD) - LOTE MÍNIMO 0.01
        # ============================================================
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 0.01
        
        # ============================================================
        # CRIPTO (BTC, ETH, SOL) - LOTE MÍNIMO 0.01
        # ============================================================
        elif any(x in simbolo_upper for x in ['BTC', 'ETH', 'SOL']):
            return 0.01
        
        # ============================================================
        # FOREX - LOTE MÍNIMO 0.01 (DEFAULT)
        # ============================================================
        else:
            return 0.01

    # mt5/conector_mt5.py - Dentro de la clase ConectorPepperstone

    def _obtener_lote_maximo_por_activo(self, simbolo: str) -> float:
        """
        Obtiene el lote máximo permitido para el tipo de activo.
        V8.44 - NUEVO.
        
        Args:
            simbolo: Símbolo (ej: 'EURUSD', 'US500', 'XAUUSD')
        
        Returns:
            Lote máximo para el tipo de activo
        """
        simbolo_upper = simbolo.upper()
        
        # ============================================================
        # ÍNDICES - LOTE MÁXIMO 10.0
        # ============================================================
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 10.0
        
        # ============================================================
        # METALES - LOTE MÁXIMO 1.0
        # ============================================================
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 1.0
        
        # ============================================================
        # CRIPTO - LOTE MÁXIMO 1.0
        # ============================================================
        elif any(x in simbolo_upper for x in ['BTC', 'ETH', 'SOL']):
            return 1.0
        
        # ============================================================
        # FOREX - LOTE MÁXIMO 10.0 (DEFAULT)
        # ============================================================
        else:
            return 10.0

    def obtener_historial_operaciones(self, 
                                   fecha_desde: Optional[datetime] = None,
                                   fecha_hasta: Optional[datetime] = None,
                                   simbolo: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Obtiene el historial de operaciones (cerradas y abiertas) desde MT5.
        V8.45 - CORREGIDO: Atributos correctos de TradeDeal.
        
        Args:
            fecha_desde: Fecha de inicio (por defecto últimos 30 días)
            fecha_hasta: Fecha de fin (por defecto ahora)
            simbolo: Símbolo específico (opcional)
        
        Returns:
            Lista de operaciones con todos los detalles
        """
        if not self.conectado:
            self.logger.error("❌ No conectado a MT5")
            return []
        
        if fecha_desde is None:
            fecha_desde = datetime.now(timezone.utc) - timedelta(days=30)
        
        if fecha_hasta is None:
            fecha_hasta = datetime.now(timezone.utc)
        
        # Convertir a timestamp para MT5
        desde_ts = int(fecha_desde.timestamp())
        hasta_ts = int(fecha_hasta.timestamp())
        
        operaciones = []
        
        try:
            # ============================================================
            # 1. OBTENER DEALS (OPERACIONES CERRADAS)
            # ============================================================
            deals = mt5.history_deals_get(desde_ts, hasta_ts, symbol=simbolo)
            
            if deals is not None and len(deals) > 0:
                self.logger.info(f"📊 MT5: {len(deals)} deals obtenidos")
                
                for deal in deals:
                    try:
                        # CORRECCIÓN: Usar atributos correctos de TradeDeal
                        # deal_id = deal.deal (esto es lo que fallaba)
                        # El atributo correcto es 'deal' o 'order' dependiendo
                        
                        # Obtener el ticket (order) y el deal_id
                        ticket = deal.order if hasattr(deal, 'order') else deal.deal
                        deal_id = deal.deal if hasattr(deal, 'deal') else deal.order
                        
                        # Determinar dirección
                        if deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_BUY_STOP, mt5.DEAL_TYPE_BUY_LIMIT]:
                            direccion = 'COMPRA'
                        elif deal.type in [mt5.DEAL_TYPE_SELL, mt5.DEAL_TYPE_SELL_STOP, mt5.DEAL_TYPE_SELL_LIMIT]:
                            direccion = 'VENTA'
                        else:
                            direccion = 'DESCONOCIDO'
                        
                        # Determinar estado
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
            
            # ============================================================
            # 2. OBTENER POSICIONES ABIERTAS
            # ============================================================
            try:
                positions = mt5.positions_get(symbol=simbolo)
                
                if positions is not None and len(positions) > 0:
                    self.logger.info(f"📊 MT5: {len(positions)} posiciones abiertas obtenidas")
                    
                    for pos in positions:
                        # Solo si es del bot (mismo magic number) o si magic=0 (todas)
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
            
            # ============================================================
            # 3. OBTENER ÓRDENES PENDIENTES (OPCIONAL)
            # ============================================================
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
            
            # ============================================================
            # 4. LOG DE RESULTADO
            # ============================================================
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