#!/usr/bin/env python3
"""
trading/ejecucion.py (V9.73 - CORREGIDO DEFINITIVO)
Ejecución de órdenes de trading con validación completa.

V9.73 - CORRECCIONES DEFINITIVAS:
- ✅ _obtener_pip_val con 3 fuentes (MT5 + Nombre + Default)
- ✅ _obtener_digits con 3 fuentes (MT5 + Nombre + Default)
- ✅ _obtener_apalancamiento_real (MT5 + Fallback por activo)
- ✅ _obtener_spread_max (MT5 + Fallback por activo)
- ✅ _obtener_paso_lote (MT5 + Fallback estándar)
- ✅ Validación de SL/TP considerando SPREAD real
- ✅ Validación de SL/TP ANTES de continuar
- ✅ SL mínimo de 5 pips + spread
- ✅ TP mínimo de 1.2x SL + spread
- ✅ _estimar_margen con apalancamiento real
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal

# Importar módulos internos
from trading.stops import GestorStops, create_gestor_stops

logger = logging.getLogger('BotTrading.Ejecucion')


class EjecutorOperaciones:
    """
    Ejecuta órdenes de trading con validación robusta.
    V9.73 - CORREGIDO DEFINITIVO.
    """
    
    def __init__(self,
                 orquestador: Any,
                 mt5: Any,
                 gestion_riesgo: Any,
                 gestor_stops: Any,
                 notificaciones: Any,
                 modo_backtest: bool = False,
                 almacen: Optional[Any] = None):
        """
        Inicializa el ejecutor de operaciones.
        """
        self.orquestador = orquestador
        self.mt5 = mt5
        self.gestion_riesgo = gestion_riesgo
        self.gestor_stops = gestor_stops
        self.notificaciones = notificaciones
        self.almacen = almacen
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Ejecutor')
        
        # Lock para operaciones pendientes
        self._lock_operaciones = threading.Lock()
        self._operaciones_pendientes: Dict[str, str] = {}
        
        # Contador de reintentos por símbolo
        self._reintentos_por_simbolo: Dict[str, int] = {}
        self._max_reintentos = 3
        
        # ✅ Mínimos absolutos para validación
        self.SL_MINIMO_ABSOLUTO_PIPS = 5
        self.TP_FACTOR_MINIMO = 1.2
        
        self.logger.info(f"📈 EjecutorOperaciones V9.73 CORREGIDO DEFINITIVO inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   SL mínimo: {self.SL_MINIMO_ABSOLUTO_PIPS} pips")
        self.logger.info(f"   TP mínimo: {self.TP_FACTOR_MINIMO}x SL")
    
    # ============================================================
    # ✅ _obtener_pip_val con 3 fuentes
    # ============================================================
    
    def _obtener_pip_val(self, simbolo: str) -> float:
        """
        Obtiene el valor de un pip para el símbolo.
        Fuente 1: MT5 (preciso pero a veces incorrecto)
        Fuente 2: Nombre del símbolo (fallback inteligente)
        Fuente 3: Default Forex (0.0001)
        """
        simbolo_upper = simbolo.upper()
        
        # ✅ FUENTE 1: MT5
        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, '_pip_size_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'point') and info.point > 0:
                    point = float(info.point)
                    
                    # Convertir point a pip_val basado en el tipo de activo
                    if 'JPY' in simbolo_upper:
                        pip_val = 0.01
                    elif 'XAU' in simbolo_upper:
                        pip_val = 0.10
                    elif 'XAG' in simbolo_upper:
                        pip_val = 0.01
                    elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
                        pip_val = 1.0
                    elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                        pip_val = 1.0
                    else:
                        pip_val = point * 10 if point < 0.001 else point
                    
                    # ✅ VERIFICACIÓN: Si es XAUUSD y devuelve 0.0001, forzar 0.10
                    if 'XAU' in simbolo_upper and pip_val == 0.0001:
                        return 0.10
                    
                    # ✅ VERIFICACIÓN: Si es BTCUSD y devuelve 0.0001, forzar 1.0
                    if 'BTC' in simbolo_upper and pip_val == 0.0001:
                        return 1.0
                    
                    return pip_val
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error obteniendo pip_val de MT5: {e}")
        
        # ✅ FUENTE 2: Nombre del símbolo
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.10  # ✅ CORREGIDO: 0.10 para oro
        if 'XAG' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        
        # ✅ FUENTE 3: Default Forex
        return 0.0001
    
    # ============================================================
    # ✅ _obtener_digits con 3 fuentes
    # ============================================================
    
    def _obtener_digits(self, simbolo: str) -> int:
        """
        Obtiene el número de decimales para el símbolo.
        Fuente 1: MT5 (preciso pero a veces incorrecto)
        Fuente 2: Nombre del símbolo (fallback inteligente)
        Fuente 3: Default Forex (5 dígitos)
        """
        simbolo_upper = simbolo.upper()
        
        # ✅ FUENTE 1: MT5
        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'digits'):
                    digits = int(info.digits)
                    
                    # ✅ VERIFICACIÓN: Si es XAUUSD y digits=5, forzar 2
                    if 'XAU' in simbolo_upper and digits == 5:
                        return 2
                    
                    # ✅ VERIFICACIÓN: Si es USDJPY y digits=5, forzar 3
                    if 'JPY' in simbolo_upper and digits == 5:
                        return 3
                    
                    return digits
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error obteniendo digits de MT5: {e}")
        
        # ✅ FUENTE 2: Nombre del símbolo
        if 'JPY' in simbolo_upper:
            return 3
        if 'XAU' in simbolo_upper:
            return 2
        if 'XAG' in simbolo_upper:
            return 3
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1
        if 'BTC' in simbolo_upper:
            return 2
        if 'ETH' in simbolo_upper:
            return 2
        if 'SOL' in simbolo_upper:
            return 2
        
        # ✅ FUENTE 3: Default Forex (5 dígitos)
        return 5
    
    # ============================================================
    # ✅ _calcular_valor_pip
    # ============================================================
    
    def _calcular_valor_pip(self, simbolo: str) -> float:
        """Calcula el valor de 1 pip en USD para 1 lote estándar."""
        simbolo_upper = simbolo.upper()
        
        tamano_contrato = self._obtener_tamano_contrato(simbolo)
        pip_val = self._obtener_pip_val(simbolo)
        
        # Para pares JPY, el valor del pip se divide por el precio
        if 'JPY' in simbolo_upper:
            return tamano_contrato * pip_val / 100  # Aproximación
        
        return tamano_contrato * pip_val
    
    # ============================================================
    # ✅ _obtener_tamano_contrato
    # ============================================================
    
    def _obtener_tamano_contrato(self, simbolo: str) -> float:
        """Obtiene el tamaño del contrato para cada símbolo."""
        simbolo_upper = simbolo.upper()
        
        # ✅ FUENTE 1: MT5
        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'trade_contract_size') and info.trade_contract_size > 0:
                    return float(info.trade_contract_size)
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error obteniendo tamaño de contrato: {e}")
        
        # ✅ FUENTE 2: Nombre del símbolo
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        if 'XAU' in simbolo_upper:
            return 100.0
        if 'XAG' in simbolo_upper:
            return 5000.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        return 100000.0
    
    # ============================================================
    # ✅ _obtener_apalancamiento_real (NUEVO)
    # ============================================================
    
    def _obtener_apalancamiento_real(self, simbolo: str) -> float:
        """
        Obtiene el apalancamiento real del broker para el símbolo.
        Fuente 1: MT5 (preciso)
        Fuente 2: Fallback por tipo de activo
        """
        # ✅ FUENTE 1: MT5
        if not self.modo_backtest and self.mt5:
            try:
                cuenta = self.mt5.info_cuenta()
                if cuenta:
                    apalancamiento = float(cuenta.get('apalancamiento', 0) or 0)
                    if apalancamiento > 0:
                        return apalancamiento
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error obteniendo apalancamiento: {e}")
        
        # ✅ FUENTE 2: Fallback por tipo de activo
        simbolo_upper = simbolo.upper()
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 200  # Metales
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 20  # Índices
        elif 'BTC' in simbolo_upper:
            return 2  # BTC
        elif any(c in simbolo_upper for c in ['ETH', 'SOL']):
            return 5  # ETH/SOL
        else:
            return 500  # Forex
    
    # ============================================================
    # ✅ _obtener_spread_max (NUEVO)
    # ============================================================
    
    def _obtener_spread_max(self, simbolo: str) -> float:
        """
        Obtiene el spread máximo permitido para el símbolo.
        Fuente 1: MT5 (si el broker proporciona max_spread)
        Fuente 2: Fallback por tipo de activo
        """
        simbolo_upper = simbolo.upper()
        
        # ✅ FUENTE 1: MT5
        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'spread_max'):
                    spread_max = float(info.spread_max)
                    if spread_max > 0:
                        return spread_max / 10  # Convertir a pips
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error obteniendo spread máximo: {e}")
        
        # ✅ FUENTE 2: Fallback por tipo de activo
        spread_max = {
            'EURUSD': 2, 'GBPUSD': 2, 'USDJPY': 2,
            'AUDUSD': 2, 'USDCAD': 2, 'USDCHF': 2,
            'EURJPY': 3, 'GBPJPY': 3, 'AUDJPY': 3,
            'XAUUSD': 30, 'XAGUSD': 30,
            'US30': 5, 'NAS100': 5, 'US500': 5,
            'BTCUSD': 50, 'ETHUSD': 50, 'SOLUSD': 50,
        }
        
        return spread_max.get(simbolo_upper, 3)
    
    # ============================================================
    # ✅ _obtener_paso_lote (NUEVO)
    # ============================================================
    
    def _obtener_paso_lote(self, simbolo: str) -> float:
        """
        Obtiene el paso de lote del broker.
        Fuente 1: MT5 (preciso)
        Fuente 2: Fallback estándar (0.01)
        """
        # ✅ FUENTE 1: MT5
        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None:
                    if hasattr(info, 'volume_step') and info.volume_step > 0:
                        return float(info.volume_step)
                    if hasattr(info, 'trade_volume_step') and info.trade_volume_step > 0:
                        return float(info.trade_volume_step)
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error obteniendo paso de lote: {e}")
        
        # ✅ FUENTE 2: Fallback estándar
        return 0.01
    
    # ============================================================
    # ✅ _estimar_margen con apalancamiento real
    # ============================================================
    
    def _estimar_margen(self, simbolo: str, lotes: float, precio: float) -> float:
        """Estima el margen requerido para una operación."""
        simbolo_upper = simbolo.upper()
        
        # ✅ Obtener apalancamiento real
        apalancamiento = self._obtener_apalancamiento_real(simbolo)
        
        contract_size = self._obtener_tamano_contrato(simbolo)
        
        valor_operacion = lotes * contract_size * precio
        
        if simbolo_upper.endswith('JPY'):
            valor_operacion_usd = valor_operacion / precio
        else:
            valor_operacion_usd = valor_operacion
        
        margen = valor_operacion_usd / apalancamiento
        
        return margen
    
    # ============================================================
    # ✅ _validar_sl_tp_antes_enviar con SPREAD
    # ============================================================
    
    def _validar_sl_tp_antes_enviar(self,
                                    simbolo: str,
                                    entry_price: float,
                                    sl: float,
                                    tp: float,
                                    direccion: str,
                                    bid: float = 0,
                                    ask: float = 0) -> Tuple[bool, str]:
        """
        Validación EXTRA de SL/TP antes de enviar al broker.
        V9.73 - Considera SPREAD real del broker.
        
        Returns:
            (valido, razon)
        """
        if entry_price <= 0 or sl <= 0 or tp <= 0:
            return False, f"Precios inválidos (entry={entry_price}, sl={sl}, tp={tp})"
        
        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            pip_val = 0.0001
        
        # ✅ 1. Validar SL según dirección
        if direccion == 'COMPRA':
            if sl >= entry_price:
                return False, f"SL INVERTIDO para COMPRA (SL={sl:.5f} >= Entry={entry_price:.5f})"
            if tp <= entry_price:
                return False, f"TP INVERTIDO para COMPRA (TP={tp:.5f} <= Entry={entry_price:.5f})"
            if tp <= sl:
                return False, f"TP <= SL para COMPRA (TP={tp:.5f} <= SL={sl:.5f})"
        else:
            if sl <= entry_price:
                return False, f"SL INVERTIDO para VENTA (SL={sl:.5f} <= Entry={entry_price:.5f})"
            if tp >= entry_price:
                return False, f"TP INVERTIDO para VENTA (TP={tp:.5f} >= Entry={entry_price:.5f})"
            if tp >= sl:
                return False, f"TP >= SL para VENTA (TP={tp:.5f} >= SL={sl:.5f})"
        
        # ✅ 2. Calcular spread en pips
        spread_pips = 0
        if bid > 0 and ask > 0:
            spread_pips = (ask - bid) / pip_val if pip_val > 0 else 0
        
        # ✅ 3. Validar SL mínimo (5 pips + spread)
        sl_dist = abs(entry_price - sl)
        sl_dist_pips = sl_dist / pip_val if pip_val > 0 else 0
        min_sl_pips = self.SL_MINIMO_ABSOLUTO_PIPS + spread_pips
        
        if sl_dist_pips < min_sl_pips:
            return False, f"SL demasiado cerca considerando spread ({spread_pips:.1f} pips)"
        
        # ✅ 4. Validar TP mínimo (1.2x SL + spread)
        tp_dist = abs(tp - entry_price)
        tp_dist_pips = tp_dist / pip_val if pip_val > 0 else 0
        min_tp_pips = sl_dist_pips * self.TP_FACTOR_MINIMO + spread_pips
        
        if tp_dist_pips < min_tp_pips:
            return False, f"TP demasiado cerca considerando spread ({spread_pips:.1f} pips)"
        
        # ✅ 5. Validar contra el tick actual
        if bid > 0 and ask > 0:
            if direccion == 'COMPRA':
                if sl >= ask:
                    return False, f"SL INVERTIDO para COMPRA vs ASK (SL={sl:.5f} >= ASK={ask:.5f})"
                if tp <= ask:
                    return False, f"TP INVERTIDO para COMPRA vs ASK (TP={tp:.5f} <= ASK={ask:.5f})"
            else:
                if sl <= bid:
                    return False, f"SL INVERTIDO para VENTA vs BID (SL={sl:.5f} <= BID={bid:.5f})"
                if tp >= bid:
                    return False, f"TP INVERTIDO para VENTA vs BID (TP={tp:.5f} >= BID={bid:.5f})"
        
        return True, "OK"
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def ejecutar(self, señal: Dict[str, Any]) -> bool:
        """
        Ejecuta una operación con validación completa.
        V9.73 - CORREGIDO DEFINITIVO.
        """
        from config.umbrales import Umbrales
        from datetime import datetime, timezone
        from decimal import Decimal
        
        # ============================================================
        # 1. EXTRAER DATOS DE LA SEÑAL
        # ============================================================
        simbolo = señal.get('simbolo')
        direccion = señal.get('direccion')
        entry_price = señal.get('entry_price', 0)
        sl = señal.get('sl', 0)
        tp = señal.get('tp', 0)
        tp2 = señal.get('tp2', 0)
        score = señal.get('score', 0)
        modo = señal.get('modo', 'RETEST')
        regimen = señal.get('regimen', 'INCERTO')
        calidad_horario = señal.get('calidad_horario', 'REGULAR')
        volumen_relativo = señal.get('volumen_relativo', 1.0)
        
        self.logger.info(f"🚀 Ejecutando {simbolo} {direccion}...")
        self.logger.info(f"   Entry: {entry_price:.5f}, SL: {sl:.5f}, TP: {tp:.5f}")
        self.logger.info(f"   Modo: {modo}, Score: {score:.1f}")
        
        # ============================================================
        # 2. VALIDACIONES PREVIAS
        # ============================================================
        if not simbolo or not direccion:
            self.logger.error("❌ Señal incompleta")
            return False
        
        # Normalizar dirección
        direccion = direccion.upper().strip()
        if direccion in ['BUY', 'LONG']:
            direccion = 'COMPRA'
        elif direccion in ['SELL', 'SHORT']:
            direccion = 'VENTA'
        
        if direccion not in ['COMPRA', 'VENTA']:
            self.logger.error(f"❌ Dirección inválida: {direccion}")
            return False
        
        if entry_price <= 0 or sl <= 0 or tp <= 0:
            self.logger.error(f"❌ Precios inválidos: entry={entry_price}, sl={sl}, tp={tp}")
            return False
        
        # ✅ CORRECCIÓN: Validar SL/TP ANTES de continuar
        if direccion == 'COMPRA':
            if sl >= entry_price:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO para COMPRA (SL={sl:.5f} >= Entry={entry_price:.5f})")
                return False
            if tp <= entry_price:
                self.logger.error(f"❌ {simbolo}: TP INVERTIDO para COMPRA (TP={tp:.5f} <= Entry={entry_price:.5f})")
                return False
            if tp <= sl:
                self.logger.error(f"❌ {simbolo}: TP <= SL para COMPRA (TP={tp:.5f} <= SL={sl:.5f})")
                return False
        else:
            if sl <= entry_price:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO para VENTA (SL={sl:.5f} <= Entry={entry_price:.5f})")
                return False
            if tp >= entry_price:
                self.logger.error(f"❌ {simbolo}: TP INVERTIDO para VENTA (TP={tp:.5f} >= Entry={entry_price:.5f})")
                return False
            if tp >= sl:
                self.logger.error(f"❌ {simbolo}: TP >= SL para VENTA (TP={tp:.5f} >= SL={sl:.5f})")
                return False
        
        # ✅ CORRECCIÓN: Validar SL mínimo (5 pips)
        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            pip_val = 0.0001
        
        sl_dist = abs(entry_price - sl)
        sl_dist_pips = sl_dist / pip_val if pip_val > 0 else 0
        
        if sl_dist_pips < self.SL_MINIMO_ABSOLUTO_PIPS:
            self.logger.error(f"❌ {simbolo}: SL demasiado cerca ({sl_dist_pips:.1f} pips < {self.SL_MINIMO_ABSOLUTO_PIPS})")
            return False
        
        # ✅ CORRECCIÓN: Validar TP mínimo (1.2x SL)
        tp_dist = abs(tp - entry_price)
        tp_dist_pips = tp_dist / pip_val if pip_val > 0 else 0
        min_tp_pips = sl_dist_pips * self.TP_FACTOR_MINIMO
        
        if tp_dist_pips < min_tp_pips:
            self.logger.error(f"❌ {simbolo}: TP demasiado cerca ({tp_dist_pips:.1f} pips < {min_tp_pips:.1f})")
            return False
        
        # ============================================================
        # 3. PREVENCIÓN DE DUPLICADOS
        # ============================================================
        with self._lock_operaciones:
            if simbolo in self._operaciones_pendientes:
                self.logger.error(f"⛔ {simbolo}: Operación YA EN PROCESO")
                return False
            self._operaciones_pendientes[simbolo] = datetime.now(timezone.utc).isoformat()
        
        try:
            # 3.2 Verificar en MT5 (si no es backtest)
            if not self.modo_backtest:
                valido, razon = self._verificar_posiciones_existentes(simbolo, direccion)
                if not valido:
                    self.logger.error(f"⛔ {razon}")
                    return False
            
            # 4. OBTENER CAPITAL REAL
            capital = self._obtener_capital_real()
            if isinstance(capital, Decimal):
                capital = float(capital)
            
            if capital <= 0:
                self.logger.error(f"❌ Capital insuficiente: ${capital:.2f}")
                return False
            
            # 5. VALIDAR CAPITAL MÍNIMO POR ACTIVO
            valido_capital, razon_capital = self._validar_capital_minimo(simbolo, capital)
            if not valido_capital:
                self.logger.error(f"❌ {razon_capital}")
                return False
            
            self.logger.info(f"✅ {simbolo}: Capital suficiente (${capital:.2f})")
            
            simbolo_upper = simbolo.upper()
            
            # ============================================================
            # 6. OBTENER PARÁMETROS DEL SÍMBOLO
            # ============================================================
            digits = self._obtener_digits(simbolo)
            
            # ============================================================
            # 7. CALCULAR SL EN PIPS
            # ============================================================
            sl_pips = sl_dist_pips
            
            if sl_pips <= 0:
                self.logger.error(f"❌ SL inválido: {sl_pips:.1f} pips")
                return False
            
            # ============================================================
            # 8. CALCULAR LOTES DINÁMICOS
            # ============================================================
            lotes_max_por_activo = getattr(Umbrales, 'LOTES_MAX_POR_ACTIVO', {})
            lotes_min_por_activo = getattr(Umbrales, 'LOTES_MIN_POR_ACTIVO', {})
            riesgo_max_por_operacion = getattr(Umbrales, 'RIESGO_MAX_POR_OPERACION', {})
            
            lote_max = lotes_max_por_activo.get(simbolo_upper, 0.10)
            lote_min = lotes_min_por_activo.get(simbolo_upper, 0.01)
            riesgo_pct = riesgo_max_por_operacion.get(simbolo_upper, 0.01)
            
            riesgo_pct = float(riesgo_pct)
            
            # Calcular valor del pip real
            valor_pip_por_lote = self._calcular_valor_pip(simbolo)
            
            # Verificar spread actual
            spread_actual = 0
            if not self.modo_backtest:
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    spread_actual = float(tick.get('spread_pips', 0))
            
            # ✅ Obtener spread máximo
            spread_max = self._obtener_spread_max(simbolo)
            
            # Factor de spread
            if spread_actual > spread_max:
                factor_spread = 0.5
                self.logger.warning(f"⚠️ {simbolo}: Spread alto ({spread_actual:.1f} pips)")
            elif spread_actual > spread_max * 0.7:
                factor_spread = 0.7
            else:
                factor_spread = 1.0
            
            # Calcular lotes por riesgo
            riesgo_dinero = capital * riesgo_pct
            lotes_por_riesgo = riesgo_dinero / (sl_pips * valor_pip_por_lote) if sl_pips > 0 and valor_pip_por_lote > 0 else 0
            
            # Aplicar factores
            lotes = lotes_por_riesgo * factor_spread
            
            # ✅ Redondear al paso del broker
            paso_lote = self._obtener_paso_lote(simbolo)
            lotes = round(lotes / paso_lote) * paso_lote
            
            if lotes < lote_min:
                lotes = lote_min
            if lotes > lote_max:
                lotes = lote_max
            
            self.logger.info(f"📊 {simbolo}: Lotes calculados: {lotes:.3f}")
            
            if lotes <= 0:
                self.logger.error(f"❌ {simbolo}: Lotes inválidos ({lotes:.3f})")
                return False
            
            # ============================================================
            # 9. VALIDAR LOTE MÍNIMO DEL BROKER
            # ============================================================
            lote_minimo_broker = self._obtener_lote_minimo_broker(simbolo)
            if lotes < lote_minimo_broker:
                lotes = lote_minimo_broker
                self.logger.info(f"📊 {simbolo}: Lotes ajustados a mínimo broker ({lotes:.3f})")
            
            # ============================================================
            # 10. VERIFICAR MARGEN REAL
            # ============================================================
            valido_margen, razon_margen = self._verificar_margen_real(simbolo, lotes, entry_price)
            if not valido_margen:
                self.logger.error(f"❌ {razon_margen}")
                return False
            
            # ============================================================
            # 11. VALIDAR SL/TP CON EL GESTOR DE STOPS
            # ============================================================
            valido, razon, sl_validado, tp_validado, tp2_validado = self.gestor_stops.validar_sl_tp(
                simbolo=simbolo,
                entry_price=entry_price,
                sl=sl,
                tp=tp,
                tp2=tp2,
                direccion=direccion,
                regimen=regimen,
                modo=modo,
                es_reversal=señal.get('es_reversal', False),
                en_nivel_clave=señal.get('en_nivel_clave', False),
                calidad_horario=calidad_horario,
                atr_pips=señal.get('atr_pips', 0)
            )
            
            if not valido:
                self.logger.error(f"❌ SL/TP inválido: {razon}")
                return False
            
            self.logger.info(f"✅ SL/TP validado: {simbolo} {direccion}")
            self.logger.info(f"   SL: {sl_validado:.{digits}f}, TP: {tp_validado:.{digits}f}")
            
            # ============================================================
            # 12. VALIDAR SL/TP SEGÚN MODO
            # ============================================================
            valido_modo_sl_tp, razon_modo_sl_tp = self._validar_sl_tp_por_modo(
                simbolo=simbolo,
                modo=modo,
                sl=sl_validado,
                tp=tp_validado,
                entry_price=entry_price,
                direccion=direccion,
                regimen=regimen
            )
            
            if not valido_modo_sl_tp:
                self.logger.error(f"❌ {razon_modo_sl_tp}")
                return False
            
            # ============================================================
            # 13. VALIDAR R:R >= 1.5
            # ============================================================
            rr = abs(tp_validado - entry_price) / abs(sl_validado - entry_price) if abs(sl_validado - entry_price) > 0 else 0
            
            if rr < 1.5 - 0.001:
                self.logger.error(f"❌ {simbolo}: R:R insuficiente ({rr:.2f} < 1.5)")
                return False
            
            self.logger.info(f"✅ {simbolo}: R:R válido ({rr:.2f} >= 1.5)")
            
            # ============================================================
            # 14. OBTENER TICK ACTUAL
            # ============================================================
            tick = self.mt5.obtener_precio(simbolo) if not self.modo_backtest else None
            bid = 0
            ask = 0
            
            if not self.modo_backtest:
                if not tick:
                    self.logger.error(f"❌ No se pudo obtener precio para {simbolo}")
                    return False
                
                bid = tick.get('bid', 0)
                ask = tick.get('ask', 0)
                
                if direccion == 'COMPRA':
                    if sl_validado >= ask:
                        self.logger.error(f"❌ {simbolo}: SL INVERTIDO para COMPRA")
                        return False
                    if tp_validado <= ask:
                        self.logger.error(f"❌ {simbolo}: TP inválido para COMPRA")
                        return False
                else:
                    if sl_validado <= bid:
                        self.logger.error(f"❌ {simbolo}: SL INVERTIDO para VENTA")
                        return False
                    if tp_validado >= bid:
                        self.logger.error(f"❌ {simbolo}: TP inválido para VENTA")
                        return False
                
                # Determinar precio de ejecución
                if direccion == 'COMPRA':
                    precio_ejecucion = ask
                else:
                    precio_ejecucion = bid
            else:
                precio_ejecucion = entry_price
            
            # ============================================================
            # 15. ✅ VALIDACIÓN EXTRA ANTES DE ENVIAR (CON SPREAD)
            # ============================================================
            valido_extra, razon_extra = self._validar_sl_tp_antes_enviar(
                simbolo=simbolo,
                entry_price=entry_price,
                sl=sl_validado,
                tp=tp_validado,
                direccion=direccion,
                bid=bid,
                ask=ask
            )
            
            if not valido_extra:
                self.logger.error(f"❌ {simbolo}: {razon_extra}")
                return False
            
            self.logger.info(f"✅ {simbolo}: SL/TP validado correctamente antes de enviar")
            
            # ============================================================
            # 16. ENVIAR ORDEN
            # ============================================================
            comentario = f"Bot_{modo}_{score:.0f}"
            
            magic_number = getattr(self.mt5, 'magic_number', None)
            if magic_number is None:
                magic_number = getattr(self.orquestador.config, 'MAGIC_NUMBER', 0)
            
            try:
                resultado = self.mt5.enviar_orden(
                    simbolo=simbolo,
                    tipo=direccion,
                    volumen=lotes,
                    sl=sl_validado,
                    tp=tp_validado,
                    comentario=comentario,
                    magic_number=magic_number
                )
            except TypeError:
                self.logger.warning(f"⚠️ {simbolo}: Conector no acepta magic_number")
                resultado = self.mt5.enviar_orden(
                    simbolo=simbolo,
                    tipo=direccion,
                    volumen=lotes,
                    sl=sl_validado,
                    tp=tp_validado,
                    comentario=comentario
                )
            
            if not resultado or resultado.get('ticket') is None:
                self.logger.error(f"❌ Falló ejecución de {simbolo}: {resultado.get('comentario', 'Error')}")
                return False
            
            # Usar SL/TP reales del broker
            sl_real = resultado.get('sl', sl_validado)
            tp_real = resultado.get('tp', tp_validado)
            precio_ejecutado = resultado.get('precio', precio_ejecucion)
            
            # ============================================================
            # 17. REGISTRAR OPERACIÓN
            # ============================================================
            ticket = resultado.get('ticket')
            
            operacion = {
                'ticket': ticket,
                'simbolo': simbolo,
                'direccion': direccion,
                'entrada': precio_ejecutado,
                'lotes': lotes,
                'sl': sl_real,
                'tp': tp_real,
                'tp2': tp2_validado,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'estado': 'ABIERTA',
                'modo': modo,
                'score': score,
                'regimen': regimen,
                'es_sniper': True,
            }
            
            if self.almacen:
                try:
                    self.almacen.guardar_operacion(operacion)
                except Exception as e:
                    self.logger.warning(f"⚠️ Error guardando operación: {e}")
            
            if hasattr(self, 'orquestador') and self.orquestador:
                self.orquestador.estado.posiciones_abiertas[ticket] = operacion
            
            self.notificaciones.notificar_operacion({
                'simbolo': simbolo,
                'direccion': direccion,
                'entrada': precio_ejecutado,
                'sl': sl_real,
                'tp': tp_real,
                'lotes': lotes,
                'score': score,
                'modo': modo,
                'ticket': ticket,
                'es_sniper': True,
            })
            
            self.logger.info(f"✅ ORDEN EJECUTADA: {simbolo} {direccion} {lotes:.3f} @ {precio_ejecutado:.{digits}f}")
            self.logger.info(f"   SL: {sl_real:.{digits}f}, TP: {tp_real:.{digits}f}")
            
            return True
            
        finally:
            with self._lock_operaciones:
                if simbolo in self._operaciones_pendientes:
                    del self._operaciones_pendientes[simbolo]
    
    # ============================================================
    # MÉTODOS AUXILIARES
    # ============================================================
    
    def _verificar_posiciones_existentes(self, simbolo: str, direccion: str) -> Tuple[bool, str]:
        """Verifica si ya existe una posición del mismo símbolo."""
        try:
            posiciones = self.mt5.obtener_posiciones()
            if not posiciones:
                return True, "Sin posiciones"
            
            for pos in posiciones:
                if pos.get('simbolo') == simbolo:
                    tipo = pos.get('tipo')
                    if tipo in ['BUY', 0, 'COMPRA']:
                        direccion_existente = 'COMPRA'
                    elif tipo in ['SELL', 1, 'VENTA']:
                        direccion_existente = 'VENTA'
                    else:
                        direccion_existente = pos.get('direccion', 'DESCONOCIDO')
                    
                    if direccion_existente == direccion:
                        return False, f"⛔ {simbolo}: YA EXISTE posición {direccion}"
            
            return True, "Sin conflictos"
        except Exception as e:
            self.logger.warning(f"⚠️ Error verificando posiciones: {e}")
            return True, "No se pudo verificar"
    
    def _obtener_capital_real(self) -> float:
        """Obtiene capital REAL desde MT5."""
        if self.modo_backtest:
            return float(self.gestion_riesgo.capital_actual)
        
        try:
            cuenta = self.mt5.info_cuenta()
            if cuenta and cuenta.get('balance', 0) > 0:
                return float(cuenta['balance'])
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo capital: {e}")
        
        return float(self.gestion_riesgo.capital_actual)
    
    def _validar_capital_minimo(self, simbolo: str, capital: float) -> Tuple[bool, str]:
        """Valida si el capital es suficiente para operar el símbolo."""
        try:
            # Obtener precio
            precio = 0
            if not self.modo_backtest:
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    precio = float(tick.get('ask', tick.get('bid', 0)))
            
            if precio <= 0:
                return True, "OK"
            
            # Calcular margen para 0.01 lotes
            margen_requerido = self._estimar_margen(simbolo, 0.01, precio)
            
            # Capital mínimo = 2x margen
            capital_minimo = margen_requerido * 2
            
            self.logger.info(f"📊 {simbolo}: Capital mínimo requerido: ${capital_minimo:.2f}")
            
            if capital < capital_minimo:
                return False, f"Capital insuficiente para {simbolo} (${capital:.2f} < ${capital_minimo:.2f})"
            
            return True, "OK"
        except:
            return True, "OK"
    
    def _verificar_margen_real(self, simbolo: str, lotes: float, precio: float) -> Tuple[bool, str]:
        """Verifica si hay margen REAL disponible."""
        if self.modo_backtest:
            return True, "Backtest"
        
        try:
            margen_requerido = self._estimar_margen(simbolo, lotes, precio)
            
            cuenta = self.mt5.info_cuenta()
            if not cuenta:
                return False, "No se pudo obtener cuenta"
            
            margen_libre = float(cuenta.get('margen_libre', 0) or 0)
            if margen_libre <= 0:
                margen_libre = float(cuenta.get('margin_free', 0) or 0)
            if margen_libre <= 0:
                margen_libre = float(cuenta.get('equity', 0) or 0)
            
            margen_con_seguridad = margen_requerido * 1.20
            
            if margen_con_seguridad > margen_libre:
                return False, f"Margen insuficiente (req: ${margen_requerido:.2f}, libre: ${margen_libre:.2f})"
            
            return True, "OK"
        except Exception as e:
            self.logger.warning(f"⚠️ Error verificando margen: {e}")
            return True, "OK"
    
    def _validar_sl_tp_por_modo(self, simbolo: str, modo: str, sl: float, tp: float, 
                               entry_price: float, direccion: str, regimen: str) -> Tuple[bool, str]:
        """Validación específica de SL/TP según el modo de entrada."""
        # ✅ CORREGIDO: Obtener pip_val correctamente
        pip_val = self._obtener_pip_val(simbolo)
        sl_dist = abs(entry_price - sl)
        sl_pips = sl_dist / pip_val if pip_val > 0 else 0
        tp_dist = abs(tp - entry_price)
        tp_pips = tp_dist / pip_val if pip_val > 0 else 0
        
        rr_min_modo = {
            'RETEST': 1.2,
            'BREAKOUT': 1.5,
            'PULLBACK': 1.2,
            'NIVEL_FUERTE': 1.0,
            'SNIPER_ELITE': 1.5,
            'PATRON': 1.2,
            'RUPTURA_FALSA': 0.8,
            'VELA_BORDE': 0.8,
            'RETEST_FALLBACK': 0.8,
        }.get(modo, 1.0)
        
        rr = tp_pips / sl_pips if sl_pips > 0 else 0
        
        if rr < rr_min_modo - 0.01:  # ✅ Añadir tolerancia
            return False, f"R:R insuficiente para {modo} ({rr:.2f} < {rr_min_modo})"
        
        sl_min_activo = {
            'XAUUSD': 50, 'XAGUSD': 50,
            'US30': 30, 'NAS100': 30, 'US500': 25,
            'BTCUSD': 100, 'ETHUSD': 80, 'SOLUSD': 60,
            'EURUSD': 10, 'GBPUSD': 10, 'USDJPY': 10,
            'AUDUSD': 10, 'USDCAD': 10, 'USDCHF': 10,
            'EURGBP': 10, 'EURJPY': 15, 'GBPJPY': 18,
        }.get(simbolo, 10)
        
        if sl_pips < sl_min_activo - 0.01:  # ✅ Añadir tolerancia
            return False, f"SL demasiado cerca para {simbolo} ({sl_pips:.0f} < {sl_min_activo} pips)"
        
        return True, "SL/TP válido para modo"

    def _obtener_lote_minimo_broker(self, simbolo: str) -> float:
        """Obtiene el lote mínimo del broker para el símbolo."""
        simbolo_upper = simbolo.upper()
        
        # ✅ FUENTE 1: MT5
        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None:
                    if hasattr(info, 'volume_min') and info.volume_min > 0:
                        return float(info.volume_min)
                    if hasattr(info, 'trade_volume_min') and info.trade_volume_min > 0:
                        return float(info.trade_volume_min)
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error obteniendo lote mínimo: {e}")
        
        # ✅ FUENTE 2: Fallback por nombre del símbolo
        LOTES_MINIMOS_BROKER = {
            'US500': 0.10, 'US30': 0.10, 'NAS100': 0.10, 'SP500': 0.10,
            'XAUUSD': 0.01, 'XAGUSD': 0.01,
            'BTCUSD': 0.01, 'ETHUSD': 0.01, 'SOLUSD': 0.01,
            'EURUSD': 0.01, 'GBPUSD': 0.01, 'USDJPY': 0.01,
            'AUDUSD': 0.01, 'USDCAD': 0.01, 'USDCHF': 0.01,
            'EURGBP': 0.01, 'EURJPY': 0.01, 'GBPJPY': 0.01,
            'AUDJPY': 0.01, 'NZDUSD': 0.01, 'EURNZD': 0.01,
            'GBPAUD': 0.01, 'GBPCHF': 0.01, 'EURCHF': 0.01,
            'AUDCAD': 0.01, 'AUDCHF': 0.01, 'CADJPY': 0.01,
            'CHFJPY': 0.01, 'EURAUD': 0.01, 'EURCAD': 0.01,
            'GBPCAD': 0.01, 'NZDJPY': 0.01,
        }
        
        return LOTES_MINIMOS_BROKER.get(simbolo_upper, 0.01)


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_ejecutor_operaciones(orquestador: Any,
                                mt5: Any,
                                gestion_riesgo: Any,
                                gestor_stops: Optional[GestorStops] = None,
                                notificaciones: Optional[Any] = None,
                                modo_backtest: bool = False,
                                almacen: Optional[Any] = None) -> EjecutorOperaciones:
    """
    Crea una instancia de EjecutorOperaciones.
    
    Args:
        orquestador: Orquestador principal
        mt5: Conector MT5
        gestion_riesgo: Gestión de riesgo
        gestor_stops: Gestor de stops (opcional)
        notificaciones: Sistema de notificaciones
        modo_backtest: Modo backtest
        almacen: Almacenamiento SQLite
    
    Returns:
        EjecutorOperaciones
    """
    return EjecutorOperaciones(
        orquestador=orquestador,
        mt5=mt5,
        gestion_riesgo=gestion_riesgo,
        gestor_stops=gestor_stops,
        notificaciones=notificaciones,
        modo_backtest=modo_backtest,
        almacen=almacen
    )


# ============================================================
# TEST RÁPIDO
# ============================================================

if __name__ == "__main__":
    # Prueba de importación
    print("✅ EjecutorOperaciones V9.73 importado correctamente")
    print(f"   Función create_ejecutor_operaciones: {'✅' if create_ejecutor_operaciones else '❌'}")