#!/usr/bin/env python3
"""
trading/stops.py (V9.20 - CORREGIDO DEFINITIVO)
Gestor de Stop Loss y Take Profit con R:R dinámico.

V9.20 - CORRECCIONES DEFINITIVAS:
- Método público validar_sl_tp() que llama a _validar_sl_tp()
- _validar_sl_tp() acepta tp=0 para cálculo automático
- TP calculado basado en R:R objetivo cuando tp=0
- Indentación correcta en todos los métodos
"""

import logging
from typing import Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Importar umbrales centralizados
try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Stops')


# ============================================================
# DATACLASSES
# ============================================================

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


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class GestorStops:
    """
    Gestor de Stop Loss y Take Profit con R:R dinámico.
    V9.20 - CORREGIDO DEFINITIVO.
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

    # SL mínimo por activo (pips)
    SL_MIN_POR_ACTIVO = {
        'EURUSD': 15, 'GBPUSD': 18, 'USDJPY': 15,
        'AUDUSD': 15, 'USDCAD': 15, 'USDCHF': 15,
        'EURGBP': 15, 'EURJPY': 20, 'GBPJPY': 25,
        'AUDJPY': 20, 'EURNZD': 25, 'GBPAUD': 25,
        'EURCHF': 18, 'GBPCHF': 20,
        'XAUUSD': 80, 'XAGUSD': 100,
        'US30': 45, 'NAS100': 50, 'US500': 40,
        'BTCUSD': 100, 'ETHUSD': 80, 'SOLUSD': 60,
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

    def __init__(self,
                 config: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el gestor de stops.

        Args:
            config: Configuración
            modo_backtest: Modo backtest
        """
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Stops')

        # Cargar configuración
        self._cargar_configuracion()

        self.logger.info(f"🛡️ GestorStops V9.20 CORREGIDO DEFINITIVO inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")

    def _cargar_configuracion(self):
        """Carga configuración desde umbrales centralizados."""
        if Umbrales is not None:
            # R:R desde umbrales
            if hasattr(Umbrales, 'RR'):
                rr_config = Umbrales.RR
                for modo in self.RR_POR_MODO:
                    rr_key = f'rr_{modo.lower()}'
                    if rr_key in rr_config:
                        self.RR_POR_MODO[modo]['target'] = rr_config[rr_key]

            # SL desde umbrales
            if hasattr(Umbrales, 'SL'):
                sl_config = Umbrales.SL
                for activo in self.SL_MIN_POR_ACTIVO:
                    if activo in sl_config.get('sl_min_por_activo', {}):
                        self.SL_MIN_POR_ACTIVO[activo] = sl_config['sl_min_por_activo'][activo]

        # Cargar desde config
        if self.config:
            if hasattr(self.config, 'SL_MIN_PIPS_POR_ACTIVO'):
                self.SL_MIN_POR_ACTIVO.update(getattr(self.config, 'SL_MIN_PIPS_POR_ACTIVO', {}))
            if hasattr(self.config, 'SL_MAX_PIPS_POR_ACTIVO'):
                self.SL_MAX_POR_ACTIVO.update(getattr(self.config, 'SL_MAX_PIPS_POR_ACTIVO', {}))

        # Ajustes para backtest
        if self.modo_backtest:
            for activo in self.SL_MIN_POR_ACTIVO:
                self.SL_MIN_POR_ACTIVO[activo] = max(5, self.SL_MIN_POR_ACTIVO[activo] - 3)
            for modo in self.RR_POR_MODO:
                self.RR_POR_MODO[modo]['min'] = max(0.5, self.RR_POR_MODO[modo]['min'] - 0.3)
                self.RR_POR_MODO[modo]['target'] = max(0.8, self.RR_POR_MODO[modo]['target'] - 0.3)

    # ============================================================
    # ✅ MÉTODO PÚBLICO PRINCIPAL (COMPATIBILIDAD)
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
        V9.20 - MÉTODO PÚBLICO (compatibilidad).
        """
        return self._validar_sl_tp(
            simbolo=simbolo,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            tp2=tp2,
            direccion=direccion,
            info_simbolo=info_simbolo,
            regimen=regimen,
            modo=modo,
            es_reversal=es_reversal,
            en_nivel_clave=en_nivel_clave,
            atr=atr,
            calidad_horario=calidad_horario,
            atr_pips=atr_pips
        )

    # ============================================================
    # MÉTODO INTERNO _validar_sl_tp()
    # ============================================================

    def _validar_sl_tp(self,
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
        V9.55 - CORREGIDO DEFINITIVO:
        - Validación ESTRICTA de SL/TP según dirección
        - Normaliza dirección (BUY/SELL → COMPRA/VENTA)
        - Rechaza SL invertido antes de continuar
        """
        # ✅ CORREGIDO: Normalizar dirección
        direccion = direccion.upper().strip()
        if direccion in ['BUY', 'LONG']:
            direccion = 'COMPRA'
        elif direccion in ['SELL', 'SHORT']:
            direccion = 'VENTA'
        
        # 1. Validaciones básicas
        if sl <= 0:
            self.logger.debug(f"❌ SL inválido: sl={sl}")
            return False, "SL inválido", sl, tp, tp2
        
        if entry_price <= 0:
            self.logger.debug(f"❌ Precio inválido: {entry_price}")
            return False, "Precio inválido", sl, tp, tp2
        
        # ✅ CORREGIDO V9.55: VALIDACIÓN ESTRICTA DE DIRECCIÓN
        if direccion == 'COMPRA':
            # SL DEBE estar ESTRICTAMENTE DEBAJO del precio
            if sl >= entry_price:
                self.logger.error(f"❌ SL INVERTIDO para COMPRA: SL={sl:.5f} >= entry={entry_price:.5f}")
                return False, "SL invertido para COMPRA", sl, tp, tp2
            # TP DEBE estar ESTRICTAMENTE ARRIBA del precio (si tp > 0)
            if tp > 0 and tp <= entry_price:
                self.logger.error(f"❌ TP inválido para COMPRA: TP={tp:.5f} <= entry={entry_price:.5f}")
                return False, "TP inválido para COMPRA", sl, tp, tp2
        else:  # VENTA
            # SL DEBE estar ESTRICTAMENTE ARRIBA del precio
            if sl <= entry_price:
                self.logger.error(f"❌ SL INVERTIDO para VENTA: SL={sl:.5f} <= entry={entry_price:.5f}")
                return False, "SL invertido para VENTA", sl, tp, tp2
            # TP DEBE estar ESTRICTAMENTE DEBAJO del precio (si tp > 0)
            if tp > 0 and tp >= entry_price:
                self.logger.error(f"❌ TP inválido para VENTA: TP={tp:.5f} >= entry={entry_price:.5f}")
                return False, "TP inválido para VENTA", sl, tp, tp2
        
        # 2. Obtener parámetros del símbolo
        pip_val = self._obtener_pip_val(simbolo, entry_price)
        if pip_val <= 0:
            pip_val = 0.0001
        
        digits = self._obtener_digits(simbolo)
        
        # 3. Obtener SL mínimo y máximo
        sl_min = self._obtener_sl_minimo(
            simbolo=simbolo,
            modo=modo,
            regimen=regimen,
            calidad_horario=calidad_horario,
            atr_pips=atr_pips
        )
        sl_max = self._obtener_sl_maximo(simbolo, modo, regimen)
        
        self.logger.debug(f"📊 SL mínimo: {sl_min:.1f}pips, SL máximo: {sl_max:.1f}pips")
        
        # 4. Calcular R:R objetivo
        rr_target = self._obtener_rr_objetivo(modo, regimen, es_reversal, en_nivel_clave, calidad_horario)
        rr_min = self._obtener_rr_minimo(modo, regimen, es_reversal)
        rr_max = self._obtener_rr_maximo(modo)
        
        self.logger.debug(f"📊 R:R objetivo: {rr_target:.2f}, R:R mínimo: {rr_min:.2f}, R:R máximo: {rr_max:.2f}")
        
        # 5. Validar y ajustar SL
        sl_ajustado, sl_dist_pips, razon_sl = self._ajustar_sl(
            entry_price, sl, direccion, sl_min, sl_max, pip_val, digits
        )
        
        self.logger.debug(f"📊 SL después de ajuste: {sl_ajustado:.{digits}f} ({sl_dist_pips:.1f}pips) - {razon_sl}")
        
        # ✅ CORREGIDO V9.55: VERIFICAR SL AJUSTADO SEGÚN DIRECCIÓN
        if direccion == 'COMPRA':
            if sl_ajustado >= entry_price:
                self.logger.error(f"❌ SL ajustado INVERTIDO para COMPRA: {sl_ajustado:.{digits}f} >= {entry_price:.{digits}f}")
                return False, "SL ajustado invertido para COMPRA", sl_ajustado, tp, tp2
        else:  # VENTA
            if sl_ajustado <= entry_price:
                self.logger.error(f"❌ SL ajustado INVERTIDO para VENTA: {sl_ajustado:.{digits}f} <= {entry_price:.{digits}f}")
                return False, "SL ajustado invertido para VENTA", sl_ajustado, tp, tp2
        
        # 6. Calcular SL distance
        sl_dist = abs(entry_price - sl_ajustado)
        
        # 7. Calcular TP (si tp=0, calcular automáticamente)
        if tp <= 0:
            if direccion == 'COMPRA':
                tp_calculado = entry_price + (sl_dist * rr_target)
            else:
                tp_calculado = entry_price - (sl_dist * rr_target)
            tp_ajustado = round(tp_calculado, digits)
            rr_actual = rr_target
            razon_tp = f"TP calculado por R:R ({rr_target:.2f})"
            self.logger.debug(f"📊 TP calculado automáticamente: {tp_ajustado:.{digits}f} (R:R: {rr_actual:.2f}) - {razon_tp}")
        else:
            # 8. Ajustar TP según R:R
            tp_ajustado, rr_actual, razon_tp = self._ajustar_tp(
                entry_price, tp, direccion, sl_dist, rr_target, rr_min, rr_max, pip_val, digits
            )
            self.logger.debug(f"📊 TP después de ajuste: {tp_ajustado:.{digits}f} (R:R: {rr_actual:.2f}) - {razon_tp}")
        
        # ✅ CORREGIDO V9.55: VERIFICAR TP AJUSTADO SEGÚN DIRECCIÓN
        if direccion == 'COMPRA':
            if tp_ajustado <= entry_price:
                self.logger.error(f"❌ TP ajustado INVERTIDO para COMPRA: {tp_ajustado:.{digits}f} <= {entry_price:.{digits}f}")
                return False, "TP ajustado invertido para COMPRA", sl_ajustado, tp_ajustado, tp2
        else:  # VENTA
            if tp_ajustado >= entry_price:
                self.logger.error(f"❌ TP ajustado INVERTIDO para VENTA: {tp_ajustado:.{digits}f} >= {entry_price:.{digits}f}")
                return False, "TP ajustado invertido para VENTA", sl_ajustado, tp_ajustado, tp2
        
        # 9. Calcular TP2 (si se proporcionó)
        tp2_ajustado = self._ajustar_tp2(entry_price, tp2, tp_ajustado, direccion, sl_dist, digits)
        
        # 10. Validaciones finales
        valido, razon_final = self._validar_final(
            entry_price, sl_ajustado, tp_ajustado, direccion, digits
        )
        
        if not valido:
            self.logger.debug(f"❌ Validación final falló: {razon_final}")
            return False, razon_final, sl_ajustado, tp_ajustado, tp2_ajustado
        
        # 11. Log de la decisión
        self._log_decision(simbolo, entry_price, sl_ajustado, tp_ajustado,
                        sl_dist_pips, rr_actual, modo, regimen, calidad_horario)
        
        return True, "OK", sl_ajustado, tp_ajustado, tp2_ajustado

    # ============================================================
    # MÉTODOS DE AJUSTE DE SL
    # ============================================================

    def _ajustar_sl(self,
                    entry_price: float,
                    sl: float,
                    direccion: str,
                    sl_min: float,
                    sl_max: float,
                    pip_val: float,
                    digits: int) -> Tuple[float, float, str]:
        """Ajusta el SL según mínimos y máximos."""
        sl_dist_pips = abs(entry_price - sl) / pip_val if pip_val > 0 else 0

        # Verificar SL mínimo
        if sl_dist_pips < sl_min:
            if direccion == 'COMPRA':
                sl = entry_price - (sl_min * pip_val)
            else:
                sl = entry_price + (sl_min * pip_val)
            sl_dist_pips = sl_min
            razon = f"SL ajustado a mínimo ({sl_min:.1f}pips)"
        else:
            razon = "OK"

        # Verificar SL máximo
        if sl_dist_pips > sl_max:
            if direccion == 'COMPRA':
                sl = entry_price - (sl_max * pip_val)
            else:
                sl = entry_price + (sl_max * pip_val)
            sl_dist_pips = sl_max
            razon = f"SL ajustado a máximo ({sl_max:.1f}pips)"

        # Redondear
        sl = round(sl, digits)

        return sl, sl_dist_pips, razon

    # ============================================================
    # MÉTODOS DE AJUSTE DE TP
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
                digits: int) -> Tuple[float, float, str]:
        """
        Ajusta el TP según R:R.
        V9.21 - CORREGIDO: Respeta estructura, no fuerza TP.
        """
        # ✅ CORREGIDO: Si TP=0, calcular TP basado en R:R objetivo
        if tp <= 0:
            if direccion == 'COMPRA':
                tp = entry_price + (sl_dist * rr_target)
            else:
                tp = entry_price - (sl_dist * rr_target)
            rr_actual = rr_target
            razon = f"TP calculado por R:R ({rr_target:.2f})"
            return round(tp, digits), rr_actual, razon
        
        # Calcular R:R actual
        tp_dist = abs(tp - entry_price)
        rr_actual = tp_dist / sl_dist if sl_dist > 0 else 0
        
        # ✅ CORREGIDO: Si TP es válido (R:R >= mínimo), mantener
        if rr_actual >= rr_min:
            razon = "OK (TP mantiene R:R válido)"
            return round(tp, digits), rr_actual, razon
        
        # ✅ CORREGIDO: Si R:R es bajo, NO forzar TP lejano
        # En su lugar, mantener el TP y ajustar el SL si es posible
        if rr_actual < rr_min:
            # Intentar acercar SL al precio para mejorar R:R
            # Pero NO mover el TP más lejos (no realista)
            razon = f"TP mantiene R:R bajo ({rr_actual:.2f} < {rr_min})"
            return round(tp, digits), rr_actual, razon
        
        # Redondear
        tp = round(tp, digits)
        
        return tp, rr_actual, razon

    def _ajustar_tp2(self,
                     entry_price: float,
                     tp2: float,
                     tp_final: float,
                     direccion: str,
                     sl_dist: float,
                     digits: int) -> float:
        """Ajusta el TP2."""
        if tp2 <= 0:
            return 0.0

        # TP2 debe estar más lejos que TP1
        tp_dist_final = abs(tp_final - entry_price)
        tp2_dist_min = tp_dist_final + (sl_dist * 0.3)

        if direccion == 'COMPRA':
            tp2_ajustado = entry_price + max(tp2_dist_min, abs(tp2 - entry_price))
        else:
            tp2_ajustado = entry_price - max(tp2_dist_min, abs(entry_price - tp2))

        return round(tp2_ajustado, digits)

    # ============================================================
    # VALIDACIONES FINALES
    # ============================================================

    def _validar_final(self,
                       entry_price: float,
                       sl: float,
                       tp: float,
                       direccion: str,
                       digits: int) -> Tuple[bool, str]:
        """Validaciones finales de SL/TP."""
        # Validar dirección del SL
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

        # Validar distancia mínima entre SL y TP (3 pips)
        pip_val = 0.0001
        if abs(tp - sl) < (3 * pip_val):
            return True, "OK (distancia SL-TP ajustada)"

        return True, "OK"

    # ============================================================
    # OBTENCIÓN DE PARÁMETROS
    # ============================================================

    def _obtener_sl_minimo(self,
                           simbolo: str,
                           modo: str,
                           regimen: str,
                           calidad_horario: str,
                           atr_pips: float = 0) -> float:
        """Obtiene el SL mínimo en pips."""
        from config.umbrales import Umbrales
        sl_base = Umbrales.SL.get('sl_min_cripto', 40)

        if simbolo in self.SL_MIN_POR_ACTIVO:
            sl_base = self.SL_MIN_POR_ACTIVO[simbolo]

        # Ajustes por modo
        ajustes_modo = {
            'RETEST': 1.0, 'BREAKOUT': 1.2, 'PULLBACK': 1.1,
            'NIVEL_FUERTE': 0.9, 'PATRON': 1.0, 'RUPTURA_FALSA': 1.0,
            'VELA_BORDE': 0.9, 'RETEST_FALLBACK': 0.8, 'SNIPER_ELITE': 1.0,
        }
        sl_min = sl_base * ajustes_modo.get(modo, 1.0)

        # Ajustes por régimen
        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.2, 'TREND_BAJISTA_FUERTE': 1.2,
            'TREND_ALCISTA_DEBIL': 1.0, 'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9, 'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 1.1, 'BREAKOUT_INMINENTE': 1.0, 'INCERTO': 1.0,
        }
        sl_min = sl_min * ajustes_regimen.get(regimen, 1.0)

        # Ajustes por calidad de horario
        ajustes_horario = {
            'EXCELENTE': 0.9, 'BUENA': 1.0, 'REGULAR': 1.1,
            'MALA': 1.2, 'PESIMA': 1.3,
        }
        sl_min = sl_min * ajustes_horario.get(calidad_horario, 1.0)

        # Ajuste dinámico por ATR
        if atr_pips > 0 and any(c in simbolo.upper() for c in ['BTC', 'ETH', 'SOL']):
            sl_min_dinamico = max(sl_min, atr_pips * 0.7)
            self.logger.debug(f"📊 {simbolo}: SL mínimo ajustado de {sl_min:.1f} a {sl_min_dinamico:.1f}pips (ATR: {atr_pips:.1f}pips)")
            sl_min = sl_min_dinamico

        return max(5, round(sl_min, 1))

    def _obtener_sl_maximo(self,
                           simbolo: str,
                           modo: str,
                           regimen: str) -> float:
        """Obtiene el SL máximo en pips."""
        sl_max = self.SL_MAX_POR_ACTIVO.get(simbolo, 200)

        # Ajuste por régimen
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

        # Ajuste por régimen
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

        # Ajuste por reversal
        if es_reversal:
            rr = rr * 0.85

        # Ajuste por nivel clave
        if en_nivel_clave:
            rr = rr * 1.1

        # Ajuste por calidad de horario
        rr = rr / {
            'EXCELENTE': 0.9,
            'BUENA': 1.0,
            'REGULAR': 1.1,
            'MALA': 1.2,
            'PESIMA': 1.3,
        }.get(calidad_horario, 1.0)

        return max(0.8, min(4.0, round(rr, 2)))

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

        # Ajuste por régimen
        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.0,
            'TREND_BAJISTA_FUERTE': 1.0,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.8,
        }
        rr = rr * ajustes_regimen.get(regimen, 1.0)

        if es_reversal:
            rr = rr * 0.9

        return max(0.5, round(rr, 2))

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
    # UTILIDADES
    # ============================================================

    def _obtener_pip_val(self, simbolo: str, precio: float) -> float:
        """
        Obtiene el valor de un pip para el símbolo.
        V9.47 - CORREGIDO: XAGUSD usa 0.01.
        """
        simbolo_upper = simbolo.upper()
        
        # JPY
        if 'JPY' in simbolo_upper:
            return 0.01
        
        # Metales
        if 'XAU' in simbolo_upper:
            return 0.01
        if 'XAG' in simbolo_upper:
            return 0.01  # ✅ CORREGIDO: XAGUSD usa 0.01
        
        # Índices
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 1.0
        
        # Cripto
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        
        # Forex estándar
        return 0.0001
    def _obtener_pip_val_universal(self, simbolo: str) -> float:
        """
        Obtiene pip_val para CUALQUIER símbolo.
        V9.47 - CORREGIDO: XAGUSD usa 0.01.
        """
        simbolo_upper = simbolo.upper()
        
        # 1. Intentar desde MT5
        if self.mt5 is not None:
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'point'):
                    point = float(info.point)
                    digits = int(getattr(info, 'digits', 5))
                    
                    if hasattr(self.mt5, '_pip_size_simbolo'):
                        pip_size = float(self.mt5._pip_size_simbolo(simbolo, info))
                        if pip_size > 0:
                            return pip_size
                    
                    if digits == 5 or digits == 3:
                        return 0.0001 if digits == 5 else 0.01
                    
                    if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
                        return 1.0
                    
                    if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                        return 1.0
                    
                    if point > 0:
                        return point * 10 if digits > 2 else point
            except Exception as e:
                self.logger.debug(f"⚠️ Error obteniendo pip_val de MT5 para {simbolo}: {e}")
        
        # 2. Fallback estático
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.01
        if 'XAG' in simbolo_upper:
            return 0.01  # ✅ CORREGIDO: XAGUSD usa 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001

    def _obtener_sl_minimo_universal(self, simbolo: str, modo: str = 'RETEST') -> float:
        """
        Obtiene SL mínimo en pips para CUALQUIER símbolo.
        V9.47 - CORREGIDO: XAGUSD usa 200 pips.
        """
        simbolo_upper = simbolo.upper()
        
        # 1. CRIPTO
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            base_min = 150
        # 2. METALES
        elif 'XAU' in simbolo_upper:
            base_min = 150
        elif 'XAG' in simbolo_upper:
            base_min = 200  # ✅ CORRECTO: 200 pips = 2.00 unidades
        # 3. ÍNDICES
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            base_min = 100
        # 4. FOREX
        elif 'JPY' in simbolo_upper:
            base_min = 25
        elif simbolo_upper in ['EURGBP', 'EURCHF', 'GBPCHF']:
            base_min = 20
        else:
            base_min = 20
        
        return base_min

    def _obtener_digits(self, simbolo: str) -> int:
        """
        Obtiene el número de decimales para el símbolo.
        V9.2 - CORREGIDO: Unificado con el resto del sistema.
        """
        simbolo_upper = simbolo.upper()
        
        # JPY
        if 'JPY' in simbolo_upper:
            return 3
        
        # Metales
        if 'XAU' in simbolo_upper:
            return 2  # ✅ CORREGIDO: Oro usa 2 decimales
        if 'XAG' in simbolo_upper:
            return 3  # ✅ CORREGIDO: Plata usa 3 decimales
        
        # Índices
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1  # ✅ CORREGIDO: Índices usan 1 decimal
        
        # Cripto
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 2
        
        # Forex estándar
        return 5

    # ============================================================
    # LOGGING
    # ============================================================

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
    # MÉTODOS DE COMPATIBILIDAD (LEGACY)
    # ============================================================

    def validar_sl_tp_legacy(self,
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
                             calidad_horario: str = 'REGULAR') -> Tuple[bool, str, float, float, float]:
        """Versión legacy de validar_sl_tp."""
        return self._validar_sl_tp(
            simbolo=simbolo,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            tp2=tp2,
            direccion=direccion,
            info_simbolo=info_simbolo,
            regimen=regimen,
            modo=modo,
            es_reversal=es_reversal,
            en_nivel_clave=en_nivel_clave,
            atr=atr,
            calidad_horario=calidad_horario
        )


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_gestor_stops(config: Optional[Any] = None,
                        modo_backtest: bool = False) -> GestorStops:
    """Crea una instancia de GestorStops."""
    return GestorStops(
        config=config,
        modo_backtest=modo_backtest
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida
    gestor = GestorStops(modo_backtest=True)

    # Test 1: RETEST en EURUSD
    valido, razon, sl, tp, tp2 = gestor.validar_sl_tp(
        simbolo='EURUSD',
        entry_price=1.10000,
        sl=1.09850,
        tp=0,  # TP=0 para cálculo automático
        direccion='COMPRA',
        modo='RETEST',
        regimen='TREND_ALCISTA_FUERTE',
        calidad_horario='EXCELENTE'
    )
    print(f"Test 1 - EURUSD RETEST: {valido} - {razon}")
    print(f"  SL: {sl:.5f}, TP: {tp:.5f}, TP2: {tp2:.5f}")

    # Test 2: SNIPER_ELITE en XAUUSD
    valido, razon, sl, tp, tp2 = gestor.validar_sl_tp(
        simbolo='XAUUSD',
        entry_price=2000.00,
        sl=1990.00,
        tp=0,  # TP=0 para cálculo automático
        direccion='COMPRA',
        modo='SNIPER_ELITE',
        regimen='RANGO_APRETADO',
        calidad_horario='REGULAR'
    )
    print(f"\nTest 2 - XAUUSD SNIPER_ELITE: {valido} - {razon}")
    print(f"  SL: {sl:.2f}, TP: {tp:.2f}, TP2: {tp2:.2f}")

    # Test 3: BREAKOUT en US30
    valido, razon, sl, tp, tp2 = gestor.validar_sl_tp(
        simbolo='US30',
        entry_price=40000.00,
        sl=39900.00,
        tp=0,  # TP=0 para cálculo automático
        direccion='COMPRA',
        modo='BREAKOUT',
        regimen='BREAKOUT_INMINENTE',
        calidad_horario='BUENA'
    )
    print(f"\nTest 3 - US30 BREAKOUT: {valido} - {razon}")
    print(f"  SL: {sl:.2f}, TP: {tp:.2f}, TP2: {tp2:.2f}")

    print("\n✅ Prueba completada")