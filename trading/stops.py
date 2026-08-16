#!/usr/bin/env python3
"""
trading/stops.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Gestor de Stop Loss y Take Profit con R:R dinámico.

RESPONSABILIDADES:
- Validar SL/TP según tipo de activo y régimen
- Calcular SL/TP óptimos por modo
- Aplicar ajustes por calidad de horario
- Gestionar R:R dinámico

MEJORAS V9.0:
- Integración con umbrales centralizados
- SL/TP dinámico por calidad de horario
- Validación de R:R más robusta
- Logs detallados de decisiones
- Soporte para backtest
- Métodos de compatibilidad
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
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # CONFIGURACIÓN BASE
    # ============================================================
    
    # R:R por modo (mínimo, objetivo, máximo)
    RR_POR_MODO = {
        'RETEST': {'min': 1.2, 'target': 1.8, 'max': 3.0},
        'BREAKOUT': {'min': 1.5, 'target': 2.2, 'max': 4.0},
        'PULLBACK': {'min': 1.2, 'target': 1.8, 'max': 3.0},
        'NIVEL_FUERTE': {'min': 1.0, 'target': 1.5, 'max': 2.5},
        'PATRON': {'min': 1.2, 'target': 1.8, 'max': 3.0},
        'RUPTURA_FALSA': {'min': 0.8, 'target': 1.2, 'max': 2.0},
        'VELA_BORDE': {'min': 0.8, 'target': 1.2, 'max': 2.0},
        'RETEST_FALLBACK': {'min': 0.8, 'target': 1.3, 'max': 2.0},
        'SNIPER_ELITE': {'min': 1.5, 'target': 2.5, 'max': 4.0},
    }
    
    # SL mínimo por activo (pips)
    SL_MIN_POR_ACTIVO = {
        'EURUSD': 10, 'GBPUSD': 12, 'USDJPY': 10,
        'AUDUSD': 10, 'USDCAD': 10, 'USDCHF': 10,
        'EURGBP': 10, 'EURJPY': 15, 'GBPJPY': 18,
        'AUDJPY': 15, 'EURNZD': 18, 'GBPAUD': 18,
        'EURCHF': 12, 'GBPCHF': 15,
        'XAUUSD': 60, 'XAGUSD': 80,
        'US30': 35, 'NAS100': 40, 'US500': 30,
        'BTCUSD': 80, 'ETHUSD': 60, 'SOLUSD': 40,
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
        
        self.logger.info(f"🛡️ GestorStops V9.0 inicializado")
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
    # MÉTODO PRINCIPAL
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
                      calidad_horario: str = 'REGULAR') -> Tuple[bool, str, float, float, float]:
        """
        Valida y calcula SL/TP optimizado.
        
        Args:
            simbolo: Símbolo
            entry_price: Precio de entrada
            sl: Stop Loss propuesto
            tp: Take Profit propuesto
            tp2: Take Profit 2 (opcional)
            direccion: 'COMPRA' o 'VENTA'
            info_simbolo: Información del símbolo (opcional)
            regimen: Régimen de mercado
            modo: Modo de entrada
            es_reversal: Si es reversal
            en_nivel_clave: Si está en nivel clave
            atr: ATR actual
            calidad_horario: Calidad del horario
        
        Returns:
            (valido, razon, sl_final, tp_final, tp2_final)
        """
        # 1. Validaciones básicas
        if sl <= 0 or tp <= 0:
            return False, "SL o TP inválido", sl, tp, tp2
        
        if entry_price <= 0:
            return False, "Precio inválido", sl, tp, tp2
        
        # 2. Obtener parámetros del símbolo
        pip_val = self._obtener_pip_val(simbolo, entry_price)
        if pip_val <= 0:
            pip_val = 0.0001
        
        digits = self._obtener_digits(simbolo)
        
        # 3. Obtener SL mínimo y máximo
        sl_min = self._obtener_sl_minimo(simbolo, modo, regimen, calidad_horario)
        sl_max = self._obtener_sl_maximo(simbolo, modo, regimen)
        
        # 4. Calcular R:R objetivo
        rr_target = self._obtener_rr_objetivo(modo, regimen, es_reversal, en_nivel_clave, calidad_horario)
        rr_min = self._obtener_rr_minimo(modo, regimen, es_reversal)
        rr_max = self._obtener_rr_maximo(modo)
        
        # 5. Validar y ajustar SL
        sl_ajustado, sl_dist_pips, razon_sl = self._ajustar_sl(
            entry_price, sl, direccion, sl_min, sl_max, pip_val, digits
        )
        
        if not razon_sl.startswith("OK"):
            return False, razon_sl, sl_ajustado, tp, tp2
        
        # 6. Calcular SL distance
        sl_dist = abs(entry_price - sl_ajustado)
        
        # 7. Calcular TP
        tp_ajustado, rr_actual, razon_tp = self._ajustar_tp(
            entry_price, tp, direccion, sl_dist, rr_target, rr_min, rr_max, pip_val, digits
        )
        
        if not razon_tp.startswith("OK"):
            return False, razon_tp, sl_ajustado, tp_ajustado, tp2
        
        # 8. Calcular TP2 (si se proporcionó)
        tp2_ajustado = self._ajustar_tp2(entry_price, tp2, tp_ajustado, direccion, sl_dist, digits)
        
        # 9. Validaciones finales
        valido, razon_final = self._validar_final(
            entry_price, sl_ajustado, tp_ajustado, direccion, digits
        )
        
        if not valido:
            return False, razon_final, sl_ajustado, tp_ajustado, tp2_ajustado
        
        # 10. Log de la decisión
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
        """
        Ajusta el SL según mínimos y máximos.
        
        Returns:
            (sl_ajustado, sl_dist_pips, razon)
        """
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
        
        Returns:
            (tp_ajustado, rr_actual, razon)
        """
        # Calcular R:R actual
        tp_dist = abs(tp - entry_price)
        rr_actual = tp_dist / sl_dist if sl_dist > 0 else 0
        
        # Verificar si TP es válido
        if rr_actual < rr_min:
            # Ajustar TP al mínimo R:R
            if direccion == 'COMPRA':
                tp = entry_price + (sl_dist * rr_min)
            else:
                tp = entry_price - (sl_dist * rr_min)
            rr_actual = rr_min
            razon = f"TP ajustado a R:R mínimo ({rr_min:.2f})"
        elif rr_actual > rr_max:
            # Ajustar TP al máximo R:R
            if direccion == 'COMPRA':
                tp = entry_price + (sl_dist * rr_max)
            else:
                tp = entry_price - (sl_dist * rr_max)
            rr_actual = rr_max
            razon = f"TP ajustado a R:R máximo ({rr_max:.2f})"
        elif rr_actual < rr_target:
            # Intentar acercar al objetivo
            if direccion == 'COMPRA':
                tp = entry_price + (sl_dist * rr_target)
            else:
                tp = entry_price - (sl_dist * rr_target)
            rr_actual = rr_target
            razon = f"TP ajustado a R:R objetivo ({rr_target:.2f})"
        else:
            razon = "OK"
        
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
        """
        Ajusta el TP2.
        
        Returns:
            tp2_ajustado
        """
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
        """
        Validaciones finales de SL/TP.
        
        Returns:
            (valido, razon)
        """
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
        
        # Validar distancia mínima entre SL y TP (5 pips)
        pip_val = 0.0001
        if abs(tp - sl) < (5 * pip_val):
            return False, "Distancia SL-TP insuficiente"
        
        return True, "OK"
    
    # ============================================================
    # OBTENCIÓN DE PARÁMETROS
    # ============================================================
    
    def _obtener_sl_minimo(self,
                           simbolo: str,
                           modo: str,
                           regimen: str,
                           calidad_horario: str) -> float:
        """
        Obtiene el SL mínimo en pips.
        
        Args:
            simbolo: Símbolo
            modo: Modo de entrada
            regimen: Régimen de mercado
            calidad_horario: Calidad del horario
        
        Returns:
            SL mínimo en pips
        """
        # 1. SL base por activo
        sl_min = self.SL_MIN_POR_ACTIVO.get(simbolo, 10)
        
        # 2. Ajuste por modo
        ajustes_modo = {
            'RETEST': 1.0,
            'BREAKOUT': 1.2,
            'PULLBACK': 1.1,
            'NIVEL_FUERTE': 0.9,
            'PATRON': 1.0,
            'RUPTURA_FALSA': 1.0,
            'VELA_BORDE': 0.9,
            'RETEST_FALLBACK': 1.1,
            'SNIPER_ELITE': 1.0,
        }
        sl_min = sl_min * ajustes_modo.get(modo, 1.0)
        
        # 3. Ajuste por régimen
        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.2,
            'TREND_BAJISTA_FUERTE': 1.2,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 1.1,
            'BREAKOUT_INMINENTE': 1.0,
            'INCERTO': 1.0,
        }
        sl_min = sl_min * ajustes_regimen.get(regimen, 1.0)
        
        # 4. Ajuste por calidad de horario
        sl_min = sl_min * self.FACTOR_CALIDAD_HORARIO.get(calidad_horario, 1.0)
        
        # 5. Backtest
        if self.modo_backtest:
            sl_min = max(5, sl_min - 3)
        
        return max(5, round(sl_min, 1))
    
    def _obtener_sl_maximo(self,
                           simbolo: str,
                           modo: str,
                           regimen: str) -> float:
        """
        Obtiene el SL máximo en pips.
        
        Args:
            simbolo: Símbolo
            modo: Modo de entrada
            regimen: Régimen de mercado
        
        Returns:
            SL máximo en pips
        """
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
        """
        Obtiene el R:R objetivo.
        
        Args:
            modo: Modo de entrada
            regimen: Régimen de mercado
            es_reversal: Si es reversal
            en_nivel_clave: Si está en nivel clave
            calidad_horario: Calidad del horario
        
        Returns:
            R:R objetivo
        """
        # 1. R:R base por modo
        rr = self.RR_POR_MODO.get(modo, self.RR_POR_MODO['RETEST'])['target']
        
        # 2. Ajuste por régimen
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
        rr = rr * ajustes_regimen.get(regimen, 1.0)
        
        # 3. Ajuste por reversal
        if es_reversal:
            rr = rr * 0.85
        
        # 4. Ajuste por nivel clave
        if en_nivel_clave:
            rr = rr * 1.1
        
        # 5. Ajuste por calidad de horario
        rr = rr / self.FACTOR_CALIDAD_HORARIO.get(calidad_horario, 1.0)
        
        # 6. Backtest
        if self.modo_backtest:
            rr = max(1.0, rr - 0.3)
        
        # Limitar
        rr = max(0.8, min(4.0, rr))
        
        return round(rr, 2)
    
    def _obtener_rr_minimo(self,
                           modo: str,
                           regimen: str,
                           es_reversal: bool) -> float:
        """
        Obtiene el R:R mínimo.
        
        Args:
            modo: Modo de entrada
            regimen: Régimen de mercado
            es_reversal: Si es reversal
        
        Returns:
            R:R mínimo
        """
        rr = self.RR_POR_MODO.get(modo, self.RR_POR_MODO['RETEST'])['min']
        
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
        
        if self.modo_backtest:
            rr = max(0.5, rr - 0.2)
        
        return max(0.5, round(rr, 2))
    
    def _obtener_rr_maximo(self, modo: str) -> float:
        """
        Obtiene el R:R máximo.
        
        Args:
            modo: Modo de entrada
        
        Returns:
            R:R máximo
        """
        rr = self.RR_POR_MODO.get(modo, self.RR_POR_MODO['RETEST'])['max']
        
        if self.modo_backtest:
            rr = min(5.0, rr + 0.5)
        
        return max(2.0, round(rr, 2))
    
    # ============================================================
    # UTILIDADES
    # ============================================================
    
    def _obtener_pip_val(self, simbolo: str, precio: float) -> float:
        """
        Obtiene el valor de un pip para el símbolo.
        
        Args:
            simbolo: Símbolo
            precio: Precio de referencia
        
        Returns:
            Valor del pip
        """
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 0.10
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001
    
    def _obtener_digits(self, simbolo: str) -> int:
        """
        Obtiene el número de dígitos del símbolo.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Número de dígitos
        """
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 3
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 2
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 2
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 2
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
        """
        Log de la decisión de SL/TP.
        
        Args:
            simbolo: Símbolo
            entry: Precio de entrada
            sl: Stop Loss
            tp: Take Profit
            sl_pips: SL en pips
            rr: R:R
            modo: Modo de entrada
            regimen: Régimen de mercado
            calidad: Calidad del horario
        """
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
        """
        Versión legacy de validar_sl_tp.
        DEPRECADO - Usar validar_sl_tp() en su lugar.
        """
        return self.validar_sl_tp(
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
    """
    Crea una instancia de GestorStops.
    
    Args:
        config: Configuración
        modo_backtest: Modo backtest
    
    Returns:
        GestorStops
    """
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
        tp=1.10300,
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
        tp=2020.00,
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
        tp=40200.00,
        direccion='COMPRA',
        modo='BREAKOUT',
        regimen='BREAKOUT_INMINENTE',
        calidad_horario='BUENA'
    )
    print(f"\nTest 3 - US30 BREAKOUT: {valido} - {razon}")
    print(f"  SL: {sl:.2f}, TP: {tp:.2f}, TP2: {tp2:.2f}")
    
    print("\n✅ Prueba completada")