#!/usr/bin/env python3
"""
trading/stops.py (V9.22 - CORREGIDO DEFINITIVO)
Gestor de Stop Loss y Take Profit con R:R dinámico.

V9.22 - CORRECCIONES:
- ✅ Cálculo correcto de valor de pip para pares JPY
- ✅ Validación de SL/TP considerando spread real
- ✅ SL mínimo dinámico por tipo de activo
- ✅ TP mínimo garantizado (1.2x SL + spread)
- ✅ Validación de SL invertido con ajuste automático
"""

import logging
from typing import Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Stops')


@dataclass
class StopResultado:
    """Resultado del cálculo de SL/TP."""
    sl: float
    tp: float
    tp2: float = 0.0
    rr: float = 0.0
    sl_dist_pips: float = 0.0
    tp_dist_pips: float = 0.0
    valido: bool = True
    razon: str = "OK"
    ajustes_aplicados: Dict[str, Any] = field(default_factory=dict)


class GestorStops:
    """
    Gestor de Stop Loss y Take Profit con R:R dinámico.
    V9.22 - CORREGIDO DEFINITIVO.
    """

    # ============================================================
    # CONFIGURACIÓN BASE
    # ============================================================

    # R:R por modo (mínimo, objetivo, máximo)
    RR_POR_MODO = {
        'RETEST': {'min': 1.2, 'target': 1.5, 'max': 3.0},
        'BREAKOUT': {'min': 1.5, 'target': 2.0, 'max': 4.0},
        'PULLBACK': {'min': 1.2, 'target': 1.8, 'max': 3.0},
        'NIVEL_FUERTE': {'min': 1.0, 'target': 1.3, 'max': 2.5},
        'PATRON': {'min': 1.2, 'target': 1.5, 'max': 3.0},
        'RUPTURA_FALSA': {'min': 0.8, 'target': 1.2, 'max': 2.0},
        'VELA_BORDE': {'min': 0.8, 'target': 1.2, 'max': 2.0},
        'RETEST_FALLBACK': {'min': 0.8, 'target': 1.3, 'max': 2.0},
        'SNIPER_ELITE': {'min': 1.5, 'target': 2.0, 'max': 4.0},
    }

    # SL mínimo por activo (pips) - CORREGIDO para cuentas pequeñas
    SL_MIN_POR_ACTIVO = {
        # Forex
        'EURUSD': 10, 'GBPUSD': 10, 'USDJPY': 15,
        'AUDUSD': 10, 'USDCAD': 10, 'USDCHF': 10,
        'EURGBP': 10, 'EURJPY': 15, 'GBPJPY': 18,
        'AUDJPY': 15, 'EURNZD': 20, 'GBPAUD': 20,
        'EURCHF': 12, 'GBPCHF': 15,

        # Metales
        'XAUUSD': 50, 'XAGUSD': 50,

        # Índices
        'US30': 30, 'NAS100': 30, 'US500': 25,

        # ✅ Cripto (V1.1: ajustados al nuevo pip_val)
        # Antes: BTC=100 pips ($100) → Ahora: 800 pips ($800) = 0.95% del precio
        'BTCUSD': 800,
        # Antes: ETH=80 pips ($80) → Ahora: 250 pips ($25) = 0.93% del precio
        'ETHUSD': 250,
        # Antes: SOL=60 pips ($60) → Ahora: 200 pips ($2) = 2% del precio
        'SOLUSD': 200,
    }

    # SL máximo por activo (pips)
    SL_MAX_POR_ACTIVO = {
        'EURUSD': 150, 'GBPUSD': 150, 'USDJPY': 150,
        'XAUUSD': 300, 'BTCUSD': 300,
        'US30': 200, 'NAS100': 250, 'US500': 150,
    }

    # Factor de ajuste por calidad de horario
    FACTOR_CALIDAD_HORARIO = {
        'EXCELENTE': 0.9,
        'BUENA': 1.0,
        'REGULAR': 1.1,
        'MALA': 1.2,
        'PESIMA': 1.3,
    }

    # ✅ Mínimos absolutos
    SL_MINIMO_ABSOLUTO_PIPS = 5
    TP_FACTOR_MINIMO = 1.2

    def __init__(self,
                 config: Optional[Any] = None,
                 modo_backtest: bool = False,
                 mt5: Optional[Any] = None):
        """
        Inicializa el gestor de stops.
        """
        self.config = config
        self.modo_backtest = modo_backtest
        self.mt5 = mt5
        self.logger = logging.getLogger('BotTrading.Stops')

        self._cargar_configuracion()

        self.logger.info(f"🛡️ GestorStops V9.22 CORREGIDO inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   SL mínimo absoluto: {self.SL_MINIMO_ABSOLUTO_PIPS} pips")
        self.logger.info(f"   TP factor mínimo: {self.TP_FACTOR_MINIMO}x")

    def _cargar_configuracion(self):
        """Carga configuración desde umbrales centralizados."""
        if Umbrales is not None:
            if hasattr(Umbrales, 'RR'):
                rr_config = Umbrales.RR
                for modo in self.RR_POR_MODO:
                    rr_key = f'rr_{modo.lower()}'
                    if rr_key in rr_config:
                        self.RR_POR_MODO[modo]['target'] = rr_config[rr_key]

            if hasattr(Umbrales, 'SL'):
                sl_config = Umbrales.SL
                for activo in self.SL_MIN_POR_ACTIVO:
                    if activo in sl_config.get('sl_min_por_activo', {}):
                        self.SL_MIN_POR_ACTIVO[activo] = sl_config['sl_min_por_activo'][activo]

        if self.config:
            if hasattr(self.config, 'SL_MIN_PIPS_POR_ACTIVO'):
                self.SL_MIN_POR_ACTIVO.update(getattr(self.config, 'SL_MIN_PIPS_POR_ACTIVO', {}))
            if hasattr(self.config, 'SL_MAX_PIPS_POR_ACTIVO'):
                self.SL_MAX_POR_ACTIVO.update(getattr(self.config, 'SL_MAX_PIPS_POR_ACTIVO', {}))

        if self.modo_backtest:
            for activo in self.SL_MIN_POR_ACTIVO:
                self.SL_MIN_POR_ACTIVO[activo] = max(5, self.SL_MIN_POR_ACTIVO[activo] - 3)
            for modo in self.RR_POR_MODO:
                self.RR_POR_MODO[modo]['min'] = max(0.5, self.RR_POR_MODO[modo]['min'] - 0.3)
                self.RR_POR_MODO[modo]['target'] = max(0.8, self.RR_POR_MODO[modo]['target'] - 0.3)

    # ============================================================
    # ✅ OBTENER PRECIO ACTUAL (NUEVO)
    # ============================================================

    def _obtener_precio_actual(self, simbolo: str) -> float:
        """Obtiene el precio actual del símbolo."""
        if self.mt5 and hasattr(self.mt5, 'obtener_precio'):
            try:
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    return float(tick.get('bid', tick.get('ask', 0)))
            except Exception:
                pass
        return 1.0

    # ============================================================
    # ✅ OBTENER VALOR DE PIP (CORREGIDO)
    # ============================================================

    def _obtener_pip_val(self, simbolo: str, precio: float = 0.0) -> float:
        """Obtiene el valor de un pip para el símbolo."""
        # ✅ 1. Usar módulo unificado (SIEMPRE PRIMERO)
        try:
            from utils.parametros_simbolo import get_pip_val
            return get_pip_val(simbolo, self.mt5)
        except (ImportError, RecursionError):
            pass

        # ✅ 2. Fallback CORRECTO
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.10
        if 'XAG' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001

    def _obtener_digits(self, simbolo: str) -> int:
        """Obtiene el número de decimales para el símbolo."""
        try:
            from utils.parametros_simbolo import get_digits
            return get_digits(simbolo, self.mt5)
        except (ImportError, RecursionError):
            pass

        simbolo_upper = simbolo.upper()
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
        return 5

    # ============================================================
    # ✅ OBTENER SPREAD ACTUAL (NUEVO)
    # ============================================================

    def _obtener_spread_pips(self, simbolo: str) -> float:
        """Obtiene el spread actual en pips."""
        if self.modo_backtest or not self.mt5:
            return 0.0

        try:
            tick = self.mt5.obtener_precio(simbolo)
            if tick:
                bid = float(tick.get('bid', 0))
                ask = float(tick.get('ask', 0))
                if bid > 0 and ask > 0:
                    pip_val = self._obtener_pip_val(simbolo)
                    return (ask - bid) / pip_val if pip_val > 0 else 0
        except Exception:
            pass
        return 0.0

    # ============================================================
    # MÉTODOS DE AJUSTE DE SL (CORREGIDO)
    # ============================================================

    def _ajustar_sl(self,
                    entry_price: float,
                    sl: float,
                    direccion: str,
                    sl_min: float,
                    sl_max: float,
                    pip_val: float,
                    digits: int,
                    spread_pips: float = 0.0) -> Tuple[float, float, str]:
        """
        Ajusta el SL según mínimos y máximos.
        V9.22 - CORREGIDO: Considera spread.
        """
        sl_dist_pips = abs(entry_price - sl) / pip_val if pip_val > 0 else 0

        # ✅ SL mínimo con spread
        sl_min_efectivo = sl_min + spread_pips

        if direccion == 'COMPRA':
            if sl >= entry_price:
                sl = entry_price - (sl_min_efectivo * pip_val)
                sl_dist_pips = sl_min_efectivo
                razon = f"SL invertido, ajustado a mínimo ({sl_min_efectivo:.1f}pips)"
            elif sl_dist_pips < sl_min_efectivo:
                sl = entry_price - (sl_min_efectivo * pip_val)
                sl_dist_pips = sl_min_efectivo
                razon = f"SL ajustado a mínimo ({sl_min_efectivo:.1f}pips)"
            else:
                razon = "OK"
        else:
            if sl <= entry_price:
                sl = entry_price + (sl_min_efectivo * pip_val)
                sl_dist_pips = sl_min_efectivo
                razon = f"SL invertido, ajustado a mínimo ({sl_min_efectivo:.1f}pips)"
            elif sl_dist_pips < sl_min_efectivo:
                sl = entry_price + (sl_min_efectivo * pip_val)
                sl_dist_pips = sl_min_efectivo
                razon = f"SL ajustado a mínimo ({sl_min_efectivo:.1f}pips)"
            else:
                razon = "OK"

        if sl_dist_pips > sl_max:
            if direccion == 'COMPRA':
                sl = entry_price - (sl_max * pip_val)
            else:
                sl = entry_price + (sl_max * pip_val)
            sl_dist_pips = sl_max
            razon = f"SL ajustado a máximo ({sl_max:.1f}pips)"

        if sl_dist_pips < self.SL_MINIMO_ABSOLUTO_PIPS:
            if direccion == 'COMPRA':
                sl = entry_price - (self.SL_MINIMO_ABSOLUTO_PIPS * pip_val)
            else:
                sl = entry_price + (self.SL_MINIMO_ABSOLUTO_PIPS * pip_val)
            sl_dist_pips = self.SL_MINIMO_ABSOLUTO_PIPS
            razon = f"SL ajustado a mínimo absoluto ({self.SL_MINIMO_ABSOLUTO_PIPS} pips)"

        sl = round(sl, digits)
        return sl, sl_dist_pips, razon

    # ============================================================
    # MÉTODOS DE AJUSTE DE TP (CORREGIDO)
    # ============================================================

    def _ajustar_tp(self,
                    entry_price: float,
                    tp: float,
                    direccion: str,
                    sl_dist: float,
                    rr_target: float,
                    rr_min: float,
                    rr_max: float,
                    pip_val: float,
                    digits: int,
                    spread_pips: float = 0.0) -> Tuple[float, float, str]:
        """
        Ajusta el TP según R:R.
        V9.22 - CORREGIDO: TP mínimo con spread.
        """
        sl_dist_pips = sl_dist / pip_val if pip_val > 0 else 0

        if tp <= 0:
            if direccion == 'COMPRA':
                tp = entry_price + (sl_dist * rr_target)
            else:
                tp = entry_price - (sl_dist * rr_target)
            rr_actual = rr_target
            razon = f"TP calculado por R:R ({rr_target:.2f})"

            tp_dist_pips = abs(tp - entry_price) / pip_val if pip_val > 0 else 0
            min_tp_pips = sl_dist_pips * self.TP_FACTOR_MINIMO + spread_pips
            if tp_dist_pips < min_tp_pips:
                if direccion == 'COMPRA':
                    tp = entry_price + (min_tp_pips * pip_val)
                else:
                    tp = entry_price - (min_tp_pips * pip_val)
                razon = f"TP ajustado a mínimo ({min_tp_pips:.1f}pips)"

            return round(tp, digits), rr_actual, razon

        tp_dist = abs(tp - entry_price)
        rr_actual = tp_dist / sl_dist if sl_dist > 0 else 0
        tp_dist_pips = abs(tp - entry_price) / pip_val if pip_val > 0 else 0
        min_tp_pips = sl_dist_pips * self.TP_FACTOR_MINIMO + spread_pips

        if tp_dist_pips < min_tp_pips:
            if direccion == 'COMPRA':
                tp = entry_price + (min_tp_pips * pip_val)
            else:
                tp = entry_price - (min_tp_pips * pip_val)
            rr_actual = min_tp_pips / sl_dist_pips if sl_dist_pips > 0 else 0
            razon = f"TP ajustado a mínimo ({min_tp_pips:.1f}pips)"
            return round(tp, digits), rr_actual, razon

        if rr_actual >= rr_min:
            razon = "OK (TP mantiene R:R válido)"
            return round(tp, digits), rr_actual, razon

        if rr_actual < rr_min:
            if direccion == 'COMPRA':
                tp = entry_price + (sl_dist * max(rr_min, self.TP_FACTOR_MINIMO))
            else:
                tp = entry_price - (sl_dist * max(rr_min, self.TP_FACTOR_MINIMO))
            rr_actual = rr_min
            razon = f"TP ajustado a R:R mínimo ({rr_min:.2f})"
            return round(tp, digits), rr_actual, razon

        return round(tp, digits), rr_actual, razon

    # ============================================================
    # VALIDACIONES FINALES (CORREGIDO)
    # ============================================================

    def _validar_final(self,
                   entry_price: float,
                   sl: float,
                   tp: float,
                   direccion: str,
                   digits: int,
                   spread_pips: float = 0.0,
                   simbolo: str = 'EURUSD') -> Tuple[bool, str]:
        """
        Validaciones finales de SL/TP.
        V10.0 - FIX CRÍTICO: usa pip_val del símbolo real, no de EURUSD hardcoded.

        Antes: pip_val = self._obtener_pip_val('EURUSD') → JPY 100x mal, XAU 1000x mal
        Ahora: pip_val = self._obtener_pip_val(simbolo)
        """
        pip_val = self._obtener_pip_val(simbolo, entry_price)
        if pip_val <= 0:
            pip_val = 0.0001

        sl_dist_pips = abs(entry_price - sl) / pip_val
        tp_dist_pips = abs(tp - entry_price) / pip_val

        if direccion == 'COMPRA':
            if sl >= entry_price:
                return False, "SL inválido: SL >= precio de entrada"
            if tp <= entry_price:
                return False, "TP inválido: TP <= precio de entrada"
            if tp <= sl:
                return False, "TP inválido: TP <= SL"
        else:
            if sl <= entry_price:
                return False, "SL inválido: SL <= precio de entrada"
            if tp >= entry_price:
                return False, "TP inválido: TP >= precio de entrada"
            if tp >= sl:
                return False, "TP inválido: TP >= SL"

        min_sl_efectivo = self.SL_MINIMO_ABSOLUTO_PIPS + spread_pips
        if sl_dist_pips < min_sl_efectivo:
            return False, f"SL demasiado cerca ({sl_dist_pips:.1f} pips < {min_sl_efectivo:.1f})"

        min_tp_pips = sl_dist_pips * self.TP_FACTOR_MINIMO + spread_pips
        if tp_dist_pips < min_tp_pips:
            return False, f"TP demasiado cerca ({tp_dist_pips:.1f} pips < {min_tp_pips:.1f})"

        return True, "OK"

    # ============================================================
    # OBTENCIÓN DE PARÁMETROS (CORREGIDO)
    # ============================================================

    def _obtener_sl_minimo(self, simbolo, modo, regimen, calidad_horario, atr_pips=0) -> float:
        """
        SL mínimo en pips.
        V10.0: si el símbolo no está en el dict, usa SL_MIN_POR_ACTIVO o SL_MIN_POR_ACTIVO_UNIVERSAL.
        """
        # Lookup en dict de clase
        sl_min = self.SL_MIN_POR_ACTIVO.get(simbolo)

        # Fallback: usar la lógica universal si existe
        if sl_min is None:
            try:
                sl_min = self._obtener_sl_minimo_universal(simbolo, modo)
            except AttributeError:
                sl_min = 10

        # Ajustes por modo
        ajustes_modo = {
            'RETEST': 1.0, 'BREAKOUT': 1.2, 'PULLBACK': 1.1,
            'NIVEL_FUERTE': 0.9, 'SNIPER_ELITE': 1.0, 'PATRON': 1.0,
            'RUPTURA_FALSA': 1.0, 'VELA_BORDE': 0.9, 'RETEST_FALLBACK': 1.1,
        }
        sl_min = sl_min * ajustes_modo.get(modo, 1.0)

        # Régimen
        ajustes_reg = {
            'TREND_ALCISTA_FUERTE': 1.2, 'TREND_BAJISTA_FUERTE': 1.2,
            'TREND_ALCISTA_DEBIL': 1.0, 'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9, 'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 1.1, 'BREAKOUT_INMINENTE': 1.0, 'INCERTO': 1.0,
        }
        sl_min = sl_min * ajustes_reg.get(regimen, 1.0)

        sl_min = max(self.SL_MINIMO_ABSOLUTO_PIPS, sl_min)
        return round(sl_min, 1)

    def _obtener_sl_maximo(self,
                           simbolo: str,
                           modo: str,
                           regimen: str) -> float:
        """Obtiene el SL máximo en pips."""
        sl_max = self.SL_MAX_POR_ACTIVO.get(simbolo, 200)

        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 0.8,
            'TREND_BAJISTA_FUERTE': 0.8,
            'RANGO_APRETADO': 0.6,
            'CHOP_VOLATIL': 0.7,
        }
        sl_max = sl_max * ajustes_regimen.get(regimen, 1.0)

        return max(20, round(sl_max, 1))

    def _obtener_rr_objetivo(self,
                             modo: str,
                             regimen: str,
                             es_reversal: bool,
                             en_nivel_clave: bool,
                             calidad_horario: str) -> float:
        """Obtiene el R:R objetivo."""
        rr = {
            'RETEST': 1.5,
            'BREAKOUT': 2.0,
            'PULLBACK': 1.8,
            'NIVEL_FUERTE': 1.3,
            'PATRON': 1.5,
            'RUPTURA_FALSA': 1.2,
            'VELA_BORDE': 1.2,
            'RETEST_FALLBACK': 1.3,
            'SNIPER_ELITE': 2.0,
        }.get(modo, 1.5)

        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.1,
            'TREND_BAJISTA_FUERTE': 1.1,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,
            'RANGO_APRETADO': 0.9,
            'CHOP_VOLATIL': 0.8,
            'BREAKOUT_INMINENTE': 1.0,
            'INCERTO': 0.9,
        }
        rr = rr * ajustes_regimen.get(regimen, 1.0)

        if es_reversal:
            rr = rr * 0.85

        if en_nivel_clave:
            rr = rr * 1.1

        rr = rr / {
            'EXCELENTE': 0.9,
            'BUENA': 1.0,
            'REGULAR': 1.1,
            'MALA': 1.2,
            'PESIMA': 1.3,
        }.get(calidad_horario, 1.0)

        return max(self.TP_FACTOR_MINIMO, min(4.0, round(rr, 2)))

    def _obtener_rr_minimo(self,
                           modo: str,
                           regimen: str,
                           es_reversal: bool) -> float:
        """Obtiene el R:R mínimo."""
        rr = {
            'RETEST': 1.2,
            'BREAKOUT': 1.5,
            'PULLBACK': 1.2,
            'NIVEL_FUERTE': 1.0,
            'PATRON': 1.2,
            'RUPTURA_FALSA': 0.8,
            'VELA_BORDE': 0.8,
            'RETEST_FALLBACK': 0.8,
            'SNIPER_ELITE': 1.5,
        }.get(modo, 1.2)

        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.0,
            'TREND_BAJISTA_FUERTE': 1.0,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.8,
        }
        rr = rr * ajustes_regimen.get(regimen, 1.0)

        if es_reversal:
            rr = rr * 0.9

        return max(self.TP_FACTOR_MINIMO, round(rr, 2))

    def _obtener_rr_maximo(self, modo: str) -> float:
        """Obtiene el R:R máximo."""
        rr = {
            'RETEST': 3.0,
            'BREAKOUT': 4.0,
            'PULLBACK': 3.0,
            'NIVEL_FUERTE': 2.5,
            'PATRON': 3.0,
            'RUPTURA_FALSA': 2.0,
            'VELA_BORDE': 2.0,
            'RETEST_FALLBACK': 2.0,
            'SNIPER_ELITE': 4.0,
        }.get(modo, 3.0)
        return max(2.0, round(rr, 2))

    # ============================================================
    # MÉTODO PRINCIPAL: validar_sl_tp (CORREGIDO)
    # ============================================================

    def validar_sl_tp(self,
                      simbolo: str,
                      entry_price: float,
                      sl: float,
                      tp: float,
                      tp2: float = 0,
                      direccion: str = 'COMPRA',
                      info_simbolo: Optional[Any] = None,
                      regimen: str = 'INCERTO',
                      modo: str = 'RETEST',
                      es_reversal: bool = False,
                      en_nivel_clave: bool = False,
                      atr: float = 0.001,
                      calidad_horario: str = 'REGULAR',
                      atr_pips: float = 0.0) -> Tuple[bool, str, float, float, float]:
        """
        Valida y calcula SL/TP optimizado.
        V9.22 - CORREGIDO: Considera spread y valor de pip real.
        """
        direccion = direccion.upper().strip()
        if direccion in ['BUY', 'LONG']:
            direccion = 'COMPRA'
        elif direccion in ['SELL', 'SHORT']:
            direccion = 'VENTA'

        if sl <= 0:
            return False, "SL inválido", sl, tp, tp2
        if entry_price <= 0:
            return False, "Precio inválido", sl, tp, tp2

        if direccion == 'COMPRA':
            if sl >= entry_price:
                return False, "SL invertido para COMPRA", sl, tp, tp2
            if tp > 0 and tp <= entry_price:
                return False, "TP inválido para COMPRA", sl, tp, tp2
        else:
            if sl <= entry_price:
                return False, "SL invertido para VENTA", sl, tp, tp2
            if tp > 0 and tp >= entry_price:
                return False, "TP inválido para VENTA", sl, tp, tp2

        pip_val = self._obtener_pip_val(simbolo, entry_price)
        if pip_val <= 0:
            pip_val = 0.0001
        digits = self._obtener_digits(simbolo)

        # ✅ Obtener spread actual
        spread_pips = self._obtener_spread_pips(simbolo)
        if self.modo_backtest:
            spread_pips = 0.0

        sl_min = self._obtener_sl_minimo(simbolo, modo, regimen, calidad_horario, atr_pips)
        sl_max = self._obtener_sl_maximo(simbolo, modo, regimen)

        rr_target = self._obtener_rr_objetivo(modo, regimen, es_reversal, en_nivel_clave, calidad_horario)
        rr_min = self._obtener_rr_minimo(modo, regimen, es_reversal)
        rr_max = self._obtener_rr_maximo(modo)

        # ✅ Ajustar SL con spread
        sl_ajustado, sl_dist_pips, razon_sl = self._ajustar_sl(
            entry_price, sl, direccion, sl_min, sl_max, pip_val, digits, spread_pips
        )

        if direccion == 'COMPRA':
            if sl_ajustado >= entry_price:
                return False, "SL ajustado invertido para COMPRA", sl_ajustado, tp, tp2
        else:
            if sl_ajustado <= entry_price:
                return False, "SL ajustado invertido para VENTA", sl_ajustado, tp, tp2

        sl_dist = abs(entry_price - sl_ajustado)

        # ✅ Calcular TP con spread
        if tp <= 0:
            if direccion == 'COMPRA':
                tp_calculado = entry_price + (sl_dist * rr_target)
            else:
                tp_calculado = entry_price - (sl_dist * rr_target)
            tp_ajustado = round(tp_calculado, digits)
            rr_actual = rr_target
            razon_tp = f"TP calculado por R:R ({rr_target:.2f})"

            tp_dist_pips = abs(tp_ajustado - entry_price) / pip_val if pip_val > 0 else 0
            min_tp_pips = sl_dist_pips * self.TP_FACTOR_MINIMO + spread_pips
            if tp_dist_pips < min_tp_pips:
                if direccion == 'COMPRA':
                    tp_ajustado = entry_price + (min_tp_pips * pip_val)
                else:
                    tp_ajustado = entry_price - (min_tp_pips * pip_val)
                razon_tp = f"TP ajustado a mínimo ({min_tp_pips:.1f}pips)"
                rr_actual = min_tp_pips / sl_dist_pips if sl_dist_pips > 0 else rr_target
        else:
            tp_ajustado, rr_actual, razon_tp = self._ajustar_tp(
                entry_price, tp, direccion, sl_dist, rr_target, rr_min, rr_max, pip_val, digits, spread_pips
            )

        if direccion == 'COMPRA':
            if tp_ajustado <= entry_price:
                return False, "TP ajustado invertido para COMPRA", sl_ajustado, tp_ajustado, tp2
        else:
            if tp_ajustado >= entry_price:
                return False, "TP ajustado invertido para VENTA", sl_ajustado, tp_ajustado, tp2

        valido, razon_final = self._validar_final(
            entry_price, sl_ajustado, tp_ajustado, direccion, digits,
            spread_pips, simbolo=simbolo
        )
        if not valido:
            return False, razon_final, sl_ajustado, tp_ajustado, tp2

        return True, "OK", sl_ajustado, tp_ajustado, tp2

    def _obtener_sl_minimo_universal(self, simbolo: str, modo: str = 'RETEST') -> float:
        """Obtiene SL mínimo en pips para CUALQUIER símbolo."""
        simbolo_upper = simbolo.upper()

        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            base_min = 150
        elif 'XAU' in simbolo_upper:
            base_min = 150
        elif 'XAG' in simbolo_upper:
            base_min = 200
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            base_min = 100
        elif 'JPY' in simbolo_upper:
            base_min = 25
        elif simbolo_upper in ['EURGBP', 'EURCHF', 'GBPCHF']:
            base_min = 20
        else:
            base_min = 20

        return max(self.SL_MINIMO_ABSOLUTO_PIPS, base_min)

    def _obtener_sl_maximo_universal(self, simbolo: str, modo: str = 'RETEST') -> float:
        """Obtiene SL máximo en pips para CUALQUIER símbolo."""
        simbolo_upper = simbolo.upper()

        if 'BTC' in simbolo_upper:
            base_max = 300
        elif 'ETH' in simbolo_upper:
            base_max = 150
        elif 'SOL' in simbolo_upper:
            base_max = 30
        elif 'XAU' in simbolo_upper:
            base_max = 150
        elif 'XAG' in simbolo_upper:
            base_max = 100
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            base_max = 300
        elif 'JPY' in simbolo_upper:
            base_max = 100
        elif simbolo_upper in ['EURGBP', 'EURCHF', 'GBPCHF']:
            base_max = 80
        else:
            base_max = 60

        return max(20, base_max)

    def _log_decision(self,
                      simbolo: str,
                      entry: float,
                      sl: float,
                      tp: float,
                      sl_pips: float,
                      rr: float,
                      modo: str,
                      regimen: str,
                      calidad: str):
        """Log de la decisión de SL/TP."""
        digits = self._obtener_digits(simbolo)
        logger.info(
            f"📊 SL/TP {simbolo} | "
            f"Entry: {entry:.{digits}f} | "
            f"SL: {sl:.{digits}f} ({sl_pips:.1f}pips) | "
            f"TP: {tp:.{digits}f} | "
            f"R:R: {rr:.2f} | "
            f"Modo: {modo} | "
            f"Régimen: {regimen} | "
            f"Horario: {calidad}"
        )


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_gestor_stops(config: Optional[Any] = None,
                        modo_backtest: bool = False,
                        mt5: Optional[Any] = None) -> GestorStops:
    """Crea una instancia de GestorStops."""
    return GestorStops(
        config=config,
        modo_backtest=modo_backtest,
        mt5=mt5
    )