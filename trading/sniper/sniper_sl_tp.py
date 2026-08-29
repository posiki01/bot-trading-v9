#!/usr/bin/env python3
"""
trading/sniper/sniper_sl_tp.py (V9.17 - CORREGIDO)
Cálculo de SL/TP para el sniper.
V9.17 - CORREGIDO: TP se calcula por R:R, no por nivel cercano.
"""

import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger('BotTrading.SniperSLTP')


class CalculadorSLTP:
    """
    Calculador de SL/TP para el sniper.
    V9.17 - CORREGIDO: TP basado en R:R.
    """

    # SL mínimo por activo (pips)
    SL_MIN_POR_ACTIVO = {
        'EURUSD': 10, 'GBPUSD': 12, 'USDJPY': 10,
        'AUDUSD': 10, 'USDCAD': 10, 'USDCHF': 10,
        'EURGBP': 10, 'EURJPY': 15, 'GBPJPY': 18,
        'AUDJPY': 15, 'XAUUSD': 60, 'XAGUSD': 80,
        'US30': 35, 'NAS100': 40, 'US500': 30,
        'BTCUSD': 80, 'ETHUSD': 60, 'SOLUSD': 40,
    }

    def __init__(self, config: Optional[Any] = None, modo_backtest: bool = False):
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.SniperSLTP')

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    def calcular(self,
             simbolo: str,
             entry_price: float,
             direccion: str,
             modo: str,
             analisis_medio: Any,
             df_m5: Any,
             contexto_h1: Dict,
             calidad_horario: str = 'REGULAR') -> Optional[Dict[str, float]]:
        """
        Calcula SL y TP óptimos.
        V9.23 - CORREGIDO: TP basado en R:R, no en resistencia directa.
        """
        if not entry_price or entry_price <= 0:
            return None

        # Obtener parámetros
        pip_val = self._obtener_pip_val(simbolo, entry_price)
        if pip_val <= 0:
            pip_val = 0.0001

        digits = self._obtener_digits(simbolo)
        atr = analisis_medio.atr if analisis_medio else 0.001

        # Obtener SL mínimo por activo
        sl_min_activo = self.SL_MIN_POR_ACTIVO.get(simbolo, 15)
        sl_min = self._ajustar_sl_minimo(sl_min_activo, modo, calidad_horario)

        # ============================================================
        # 1. CALCULAR SL (basado en estructura)
        # ============================================================

        sl = self._calcular_sl_por_modo(
            simbolo=simbolo,
            entry_price=entry_price,
            direccion=direccion,
            modo=modo,
            analisis_medio=analisis_medio,
            df_m5=df_m5,
            atr=atr,
            pip_val=pip_val,
            sl_min=sl_min
        )

        if not sl:
            return None

        # Validar SL
        sl, sl_dist_pips = self._validar_sl(
            sl=sl,
            entry_price=entry_price,
            direccion=direccion,
            sl_min=sl_min,
            pip_val=pip_val,
            digits=digits
        )

        if not sl:
            return None

        # ============================================================
        # 2. CALCULAR TP BASADO EN R:R (CORREGIDO V9.23)
        # ============================================================

        # Obtener R:R objetivo
        rr_target = self._obtener_rr_objetivo(modo, contexto_h1, calidad_horario)

        # Calcular distancia del SL
        sl_dist = abs(entry_price - sl)

        # ✅ CORRECCIÓN: TP = entry + (SL_dist × rr_target)
        tp = self._calcular_tp_por_rr(
            entry_price=entry_price,
            direccion=direccion,
            sl_dist=sl_dist,
            rr_target=rr_target,
            digits=digits
        )

        # ✅ CORRECCIÓN: NO usar resistencia como TP directo
        # Solo ajustar si el TP por R:R está más allá de la estructura
        if direccion == 'COMPRA':
            resistencia_cercana = contexto_h1.get('resistencia_cercana')
            if resistencia_cercana and resistencia_cercana > entry_price:
                # Si la resistencia está ANTES del TP por R:R, usar resistencia
                if tp > resistencia_cercana:
                    self.logger.info(f"📊 {simbolo}: TP ajustado a resistencia ({resistencia_cercana:.{digits}f})")
                    tp = resistencia_cercana
        elif direccion == 'VENTA':
            soporte_cercano = contexto_h1.get('soporte_cercano')
            if soporte_cercano and soporte_cercano < entry_price:
                # Si el soporte está ANTES del TP por R:R, usar soporte
                if tp < soporte_cercano:
                    self.logger.info(f"📊 {simbolo}: TP ajustado a soporte ({soporte_cercano:.{digits}f})")
                    tp = soporte_cercano

        # Calcular TP2
        tp2 = self._calcular_tp2(
            entry_price=entry_price,
            tp=tp,
            direccion=direccion,
            sl_dist=sl_dist,
            digits=digits
        )

        # R:R final
        sl_dist = abs(entry_price - sl)
        tp_dist = abs(tp - entry_price)
        rr = tp_dist / sl_dist if sl_dist > 0 else 0

        self.logger.info(f"📊 {simbolo}: SL={sl:.{digits}f} | TP={tp:.{digits}f} | R:R={rr:.2f}")

        return {
            'sl': sl,
            'tp': tp,
            'tp2': tp2,
            'rr': rr,
            'sl_dist_pips': sl_dist_pips,
            'tp_dist_pips': tp_dist / pip_val if pip_val > 0 else 0,
            'atr': atr,
            'atr_medio': atr * 0.7,
        }

    # ============================================================
    # ✅ NUEVO: CALCULAR TP POR R:R (CORREGIDO)
    # ============================================================

    def _calcular_tp_por_rr(self,
                            entry_price: float,
                            direccion: str,
                            sl_dist: float,
                            rr_target: float,
                            digits: int) -> float:
        """
        Calcula TP basado en R:R objetivo.
        V9.17 - CORREGIDO: TP = entry + (SL_dist × rr_target)
        """
        # ✅ CORREGIDO: No usar resistencia cercana como TP
        # TP se calcula por la fórmula R:R
        if direccion == 'COMPRA':
            tp = entry_price + (sl_dist * rr_target)
        else:
            tp = entry_price - (sl_dist * rr_target)

        # Redondear al formato del símbolo
        tp = round(tp, digits)

        self.logger.debug(f"📊 TP calculado por R:R: {tp:.{digits}f} (SL_dist: {sl_dist:.{digits}f}, R:R: {rr_target:.2f})")

        return tp

    # ============================================================
    # CALCULAR SL POR MODO (EXISTENTE - SIN CAMBIOS)
    # ============================================================

    def _calcular_sl_por_modo(self, **kwargs) -> Optional[float]:
        """Calcula SL según el modo."""
        modo = kwargs.get('modo')
        entry_price = kwargs.get('entry_price')
        direccion = kwargs.get('direccion')
        analisis_medio = kwargs.get('analisis_medio')
        df_m5 = kwargs.get('df_m5')
        atr = kwargs.get('atr', 0.001)
        pip_val = kwargs.get('pip_val', 0.0001)

        if modo == 'RETEST':
            if direccion == 'COMPRA' and analisis_medio and analisis_medio.soporte_cercano:
                return analisis_medio.soporte_cercano - (pip_val * 3)
            elif direccion == 'VENTA' and analisis_medio and analisis_medio.resistencia_cercana:
                return analisis_medio.resistencia_cercana + (pip_val * 3)
            return entry_price - (atr * 1.2) if direccion == 'COMPRA' else entry_price + (atr * 1.2)

        elif modo == 'BREAKOUT':
            if direccion == 'COMPRA' and df_m5 is not None and len(df_m5) >= 10:
                min_anterior = df_m5['Low'].iloc[-10:-1].min()
                return min_anterior - (atr * 0.3)
            elif direccion == 'VENTA' and df_m5 is not None and len(df_m5) >= 10:
                max_anterior = df_m5['High'].iloc[-10:-1].max()
                return max_anterior + (atr * 0.3)
            return entry_price - (atr * 1.5) if direccion == 'COMPRA' else entry_price + (atr * 1.5)

        elif modo == 'PULLBACK':
            if direccion == 'COMPRA' and df_m5 is not None and len(df_m5) >= 5:
                min_pullback = df_m5['Low'].iloc[-5:].min()
                return min_pullback - (atr * 0.5)
            elif direccion == 'VENTA' and df_m5 is not None and len(df_m5) >= 5:
                max_pullback = df_m5['High'].iloc[-5:].max()
                return max_pullback + (atr * 0.5)
            return entry_price - (atr * 1.3) if direccion == 'COMPRA' else entry_price + (atr * 1.3)

        elif modo == 'NIVEL_FUERTE':
            if direccion == 'COMPRA' and analisis_medio and analisis_medio.soporte_cercano:
                return analisis_medio.soporte_cercano - (pip_val * 2)
            elif direccion == 'VENTA' and analisis_medio and analisis_medio.resistencia_cercana:
                return analisis_medio.resistencia_cercana + (pip_val * 2)
            return entry_price - (atr * 1.1) if direccion == 'COMPRA' else entry_price + (atr * 1.1)

        elif modo == 'SNIPER_ELITE':
            if direccion == 'COMPRA' and analisis_medio and analisis_medio.soporte_cercano:
                return analisis_medio.soporte_cercano - (pip_val * 3)
            elif direccion == 'VENTA' and analisis_medio and analisis_medio.resistencia_cercana:
                return analisis_medio.resistencia_cercana + (pip_val * 3)
            return entry_price - (atr * 1.0) if direccion == 'COMPRA' else entry_price + (atr * 1.0)

        else:  # Fallback
            return entry_price - (atr * 1.2) if direccion == 'COMPRA' else entry_price + (atr * 1.2)

    # ============================================================
    # VALIDAR SL (EXISTENTE - SIN CAMBIOS)
    # ============================================================

    def _validar_sl(self, sl: float, entry_price: float, direccion: str,
                    sl_min: float, pip_val: float, digits: int) -> Tuple[Optional[float], float]:
        """Valida y ajusta SL."""
        sl_dist_pips = abs(entry_price - sl) / pip_val

        if sl_dist_pips < sl_min:
            if direccion == 'COMPRA':
                sl = entry_price - (sl_min * pip_val)
            else:
                sl = entry_price + (sl_min * pip_val)
            sl_dist_pips = sl_min

        # Verificar dirección
        if direccion == 'COMPRA' and sl >= entry_price:
            return None, 0
        if direccion == 'VENTA' and sl <= entry_price:
            return None, 0

        return round(sl, digits), sl_dist_pips

    # ============================================================
    # CALCULAR TP2 (EXISTENTE - SIN CAMBIOS)
    # ============================================================

    def _calcular_tp2(self, entry_price: float, tp: float, direccion: str,
                      sl_dist: float, digits: int) -> float:
        """Calcula TP2."""
        tp_dist = abs(tp - entry_price)
        tp2_dist = tp_dist + (sl_dist * 0.5)

        if direccion == 'COMPRA':
            tp2 = entry_price + tp2_dist
        else:
            tp2 = entry_price - tp2_dist

        return round(tp2, digits)

    # ============================================================
    # AJUSTAR SL MÍNIMO (EXISTENTE - SIN CAMBIOS)
    # ============================================================

    def _ajustar_sl_minimo(self, sl_min: float, modo: str, calidad_horario: str) -> float:
        """Ajusta SL mínimo según modo y horario."""
        ajustes_modo = {
            'RETEST': 1.0,
            'BREAKOUT': 1.2,
            'PULLBACK': 1.1,
            'NIVEL_FUERTE': 0.9,
            'SNIPER_ELITE': 1.0,
            'PATRON': 1.0,
            'RUPTURA_FALSA': 1.0,
            'VELA_BORDE': 0.9,
            'RETEST_FALLBACK': 1.1,
        }
        sl_min = sl_min * ajustes_modo.get(modo, 1.0)

        # Ajuste por horario
        ajustes_horario = {
            'EXCELENTE': 0.9,
            'BUENA': 1.0,
            'REGULAR': 1.1,
            'MALA': 1.2,
            'PESIMA': 1.3,
        }
        sl_min = sl_min * ajustes_horario.get(calidad_horario, 1.0)

        if self.modo_backtest:
            sl_min = max(5, sl_min - 3)

        return max(5, round(sl_min, 1))

    # ============================================================
    # OBTENER R:R OBJETIVO (EXISTENTE - SIN CAMBIOS)
    # ============================================================

    def _obtener_rr_objetivo(self, modo: str, contexto_h1: Dict, calidad_horario: str) -> float:
        """Obtiene R:R objetivo."""
        rr_base = {
            'RETEST': 1.5,
            'BREAKOUT': 1.8,
            'PULLBACK': 1.6,
            'NIVEL_FUERTE': 1.4,
            'SNIPER_ELITE': 2.0,
            'PATRON': 1.5,
            'RUPTURA_FALSA': 1.2,
            'VELA_BORDE': 1.3,
            'RETEST_FALLBACK': 1.3,
        }.get(modo, 1.5)

        # Ajuste por régimen
        regimen = contexto_h1.get('regimen', 'INCERTO')
        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.1,
            'TREND_BAJISTA_FUERTE': 1.1,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.8,
            'BREAKOUT_INMINENTE': 1.0,
            'INCERTO': 0.9,
        }
        rr = rr_base * ajustes_regimen.get(regimen, 1.0)

        # Ajuste por horario
        ajustes_horario = {
            'EXCELENTE': 0.85,
            'BUENA': 0.95,
            'REGULAR': 1.0,
            'MALA': 1.1,
            'PESIMA': 1.2,
        }
        rr = rr * ajustes_horario.get(calidad_horario, 1.0)

        if self.modo_backtest:
            rr = max(1.0, rr - 0.3)

        return max(1.0, min(3.0, rr))

    # ============================================================
    # OBTENER PIP VAL (EXISTENTE - SIN CAMBIOS)
    # ============================================================

    def _obtener_pip_val(self, simbolo: str, precio: float) -> float:
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.01
        if 'XAG' in simbolo_upper:
            return 0.1
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001

    # ============================================================
    # OBTENER DIGITS (EXISTENTE - SIN CAMBIOS)
    # ============================================================

    def _obtener_digits(self, simbolo: str) -> int:
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 3
        if 'XAU' in simbolo_upper:
            return 2
        if 'XAG' in simbolo_upper:
            return 3
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 2
        return 5


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_calculador_sl_tp(config: Optional[Any] = None,
                            modo_backtest: bool = False) -> CalculadorSLTP:
    """Crea una instancia de CalculadorSLTP."""
    return CalculadorSLTP(
        config=config,
        modo_backtest=modo_backtest
    )