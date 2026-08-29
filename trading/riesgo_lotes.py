#!/usr/bin/env python3
"""
trading/riesgo_lotes.py (V9.35 - CORREGIDO)
Cálculo de lotes con límites por activo y capital disponible.
"""

import logging
from typing import Dict, Any, Optional, Tuple
import math

from config.umbrales import Umbrales

logger = logging.getLogger('BotTrading.RiesgoLotes')


class CalculadorLotes:
    """
    Calculador de lotes con límites por activo y verificación de margen.
    V9.35 - CORREGIDO: Límites estrictos por activo.
    """
    
    def __init__(self, config: Optional[Any] = None, modo_backtest: bool = False):
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.RiesgoLotes')
        
        # Cargar límites
        self._cargar_limites()
    
    def _cargar_limites(self):
        """Carga límites desde Umbrales."""
        self.lotes_max = getattr(Umbrales, 'LOTES_MAX_POR_ACTIVO', {})
        self.lotes_min = getattr(Umbrales, 'LOTES_MIN_POR_ACTIVO', {})
        self.riesgo_max = getattr(Umbrales, 'RIESGO_MAX_POR_OPERACION', {})
        
        # Defaults
        self.lotes_max_default = 0.10
        self.lotes_min_default = 0.01
        self.riesgo_max_default = 0.01
    
    def calcular(self,
                 simbolo: str,
                 entry_price: float,
                 stop_loss: float,
                 capital: float,
                 pip_size: float,
                 tick_value: float,
                 tick_size: float,
                 point: float,
                 probabilidad: float = 50.0,
                 riesgo_personalizado: Optional[float] = None) -> Tuple[float, float, str]:
        """
        Calcula lotes óptimos con límites por activo.
        
        Args:
            simbolo: Símbolo
            entry_price: Precio de entrada
            stop_loss: Precio de stop loss
            capital: Capital disponible
            pip_size: Tamaño del pip
            tick_value: Valor del tick
            tick_size: Tamaño del tick
            point: Tamaño del punto
            probabilidad: Probabilidad de éxito (0-100)
            riesgo_personalizado: Riesgo personalizado (opcional)
        
        Returns:
            (lotes, riesgo_porcentaje, mensaje)
        """
        simbolo_upper = simbolo.upper()
        
        # ============================================================
        # 1. VERIFICAR CAPITAL SUFICIENTE
        # ============================================================
        if capital <= 0:
            self.logger.error(f"❌ {simbolo}: Capital insuficiente (${capital:.2f})")
            return 0.0, 0.0, "Capital insuficiente"
        
        if entry_price <= 0 or stop_loss <= 0:
            self.logger.error(f"❌ {simbolo}: Precios inválidos (entry={entry_price}, sl={stop_loss})")
            return 0.0, 0.0, "Precios inválidos"
        
        # ============================================================
        # 2. CALCULAR DISTANCIA DEL SL
        # ============================================================
        sl_dist = abs(entry_price - stop_loss)
        
        if sl_dist <= 0:
            self.logger.error(f"❌ {simbolo}: SL en precio de entrada")
            return 0.0, 0.0, "SL en entrada"
        
        # Calcular SL en pips
        if pip_size > 0:
            sl_pips = sl_dist / pip_size
        else:
            sl_pips = 0
        
        if sl_pips <= 0:
            self.logger.warning(f"⚠️ {simbolo}: SL inválido ({sl_pips:.1f} pips)")
            # Fallback: usar punto
            if point > 0:
                sl_pips = sl_dist / point
            else:
                sl_pips = 10
        
        # ============================================================
        # 3. OBTENER RIESGO MÁXIMO PERMITIDO
        # ============================================================
        if riesgo_personalizado is not None:
            riesgo_pct = min(riesgo_personalizado, 0.02)  # Máximo 2%
        else:
            riesgo_pct = self.riesgo_max.get(simbolo_upper, self.riesgo_max_default)
            
            # Ajuste por probabilidad
            if probabilidad > 70:
                riesgo_pct = riesgo_pct * 1.1
            elif probabilidad < 40:
                riesgo_pct = riesgo_pct * 0.7
            
            # Ajuste por backtest
            if self.modo_backtest:
                riesgo_pct = min(riesgo_pct * 1.2, 0.02)
        
        # Limitar riesgo máximo
        riesgo_pct = min(riesgo_pct, 0.02)  # Máximo 2%
        riesgo_pct = max(riesgo_pct, 0.001)  # Mínimo 0.1%
        
        # ============================================================
        # 4. CALCULAR LOTES POR RIESGO
        # ============================================================
        riesgo_dinero = capital * riesgo_pct
        valor_pip = self._calcular_valor_pip(simbolo, entry_price, tick_value, tick_size, point)
        
        if valor_pip <= 0:
            self.logger.warning(f"⚠️ {simbolo}: Valor pip inválido, usando fallback")
            valor_pip = 1.0
        
        lotes_por_riesgo = riesgo_dinero / (sl_pips * valor_pip)
        
        # ============================================================
        # 5. APLICAR LÍMITES POR ACTIVO
        # ============================================================
        lote_min = self.lotes_min.get(simbolo_upper, self.lotes_min_default)
        lote_max = self.lotes_max.get(simbolo_upper, self.lotes_max_default)
        
        # ✅ CORRECCIÓN CRÍTICA: Límite especial para XAUUSD
        if simbolo_upper == 'XAUUSD':
            lote_max = min(lote_max, 0.05)  # Máximo 0.05 para oro con capital bajo
            
            # Si capital < $1000, reducir aún más
            if capital < 1000:
                lote_max = min(lote_max, 0.02)
        
        # ✅ Límite especial para BTCUSD
        if 'BTC' in simbolo_upper:
            lote_max = min(lote_max, 0.01)
        
        # ✅ Límite especial para ETHUSD
        if 'ETH' in simbolo_upper:
            lote_max = min(lote_max, 0.02)
        
        # Ajustar lotes
        lotes = max(lote_min, min(lote_max, lotes_por_riesgo))
        
        # ✅ Si la cuenta es pequeña, reducir lotes automáticamente
        if capital < 2000:
            factor_reduccion = capital / 2000
            lotes = max(lote_min, lotes * factor_reduccion)
        
        # Redondear al paso del broker
        lotes = self._redondear_lotes(lotes, simbolo)
        
        # ============================================================
        # 6. VERIFICAR MARGEN DISPONIBLE (si está disponible)
        # ============================================================
        margen_requerido = self._estimar_margen(simbolo, lotes, entry_price)
        margen_disponible = capital * 0.8  # Estimación conservadora
        
        if margen_requerido > margen_disponible:
            self.logger.warning(f"⚠️ {simbolo}: Margen insuficiente (req: ${margen_requerido:.2f}, disp: ${margen_disponible:.2f})")
            # Reducir lotes hasta que el margen sea suficiente
            while margen_requerido > margen_disponible and lotes > lote_min:
                lotes = max(lote_min, lotes * 0.8)
                margen_requerido = self._estimar_margen(simbolo, lotes, entry_price)
            
            self.logger.info(f"📊 {simbolo}: Lotes reducidos a {lotes:.3f} por margen")
        
        # ============================================================
        # 7. LOG DE RESULTADO
        # ============================================================
        riesgo_final = (lotes * sl_pips * valor_pip) / capital
        
        self.logger.info(f"📊 {simbolo}: Lotes calculados:")
        self.logger.info(f"   Capital: ${capital:.2f}")
        self.logger.info(f"   Riesgo: {riesgo_pct*100:.2f}% (${riesgo_dinero:.2f})")
        self.logger.info(f"   SL: {sl_pips:.1f} pips")
        self.logger.info(f"   Valor pip: ${valor_pip:.2f}")
        self.logger.info(f"   Lotes: {lotes:.3f} (min: {lote_min}, max: {lote_max})")
        self.logger.info(f"   Riesgo real: {riesgo_final*100:.2f}%")
        
        return lotes, riesgo_final * 100, f"Lotes: {lotes:.3f}"
    
    def _calcular_valor_pip(self,
                            simbolo: str,
                            precio: float,
                            tick_value: float,
                            tick_size: float,
                            point: float) -> float:
        """Calcula el valor de 1 pip en la moneda de la cuenta."""
        try:
            simbolo_upper = simbolo.upper()
            
            # 1. Usar tick_value del broker si está disponible
            if tick_value > 0 and tick_size > 0:
                pip_size = self._obtener_pip_size(simbolo, point)
                if pip_size > 0:
                    return tick_value / tick_size * pip_size
            
            # 2. Fallback: estimación por tipo de activo
            if 'JPY' in simbolo_upper:
                return 1.0 / 100
            elif 'XAU' in simbolo_upper:
                return 0.10  # $0.10 por pip para 0.01 lotes
            elif 'XAG' in simbolo_upper:
                return 1.0
            elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
                return 1.0
            elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                return 1.0
            else:
                return 1.0  # Forex estándar: $1 por pip para 0.01 lotes
                
        except Exception as e:
            self.logger.warning(f"⚠️ Error calculando valor pip para {simbolo}: {e}")
            return 1.0
    
    def _obtener_pip_size(self, simbolo: str, point: float) -> float:
        """Obtiene el tamaño del pip en unidades de precio."""
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 0.01
        elif 'XAU' in simbolo_upper:
            return 0.01
        elif 'XAG' in simbolo_upper:
            return 0.1
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        else:
            return 0.0001
    
    def _redondear_lotes(self, lotes: float, simbolo: str) -> float:
        """Redondea lotes al paso del broker."""
        # Paso estándar
        paso = 0.01
        
        # Pasos especiales
        simbolo_upper = simbolo.upper()
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            paso = 0.01
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            paso = 0.01
        elif 'XAU' in simbolo_upper:
            paso = 0.01
        else:
            paso = 0.01
        
        # Redondear al paso
        lotes_redondeado = round(lotes / paso) * paso
        
        # Asegurar mínimo 0.01
        if lotes_redondeado < 0.01:
            lotes_redondeado = 0.01
        
        return lotes_redondeado
    
    def _estimar_margen(self, simbolo: str, lotes: float, precio: float) -> float:
        """Estima el margen requerido para una operación."""
        simbolo_upper = simbolo.upper()
        
        # Apalancamiento típico
        apalancamiento = 30  # 30:1 para Forex
        
        if 'XAU' in simbolo_upper:
            apalancamiento = 20
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            apalancamiento = 20
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            apalancamiento = 10
        
        # Tamaño del contrato
        contract_size = 100000  # 1 lote = 100,000 unidades
        
        if 'XAU' in simbolo_upper:
            contract_size = 100  # 1 lote = 100 onzas
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            contract_size = 1  # 1 lote = 1 contrato
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            contract_size = 1  # 1 lote = 1 unidad
        
        # Margen estimado
        valor_operacion = lotes * contract_size * precio
        margen = valor_operacion / apalancamiento
        
        return margen
    
    def calcular_lotes_segun_capital(self,
                                     simbolo: str,
                                     capital: float) -> Dict[str, Any]:
        """Calcula lotes según capital disponible."""
        simbolo_upper = simbolo.upper()
        
        # Obtener límites
        lote_max = self.lotes_max.get(simbolo_upper, self.lotes_max_default)
        lote_min = self.lotes_min.get(simbolo_upper, self.lotes_min_default)
        
        # ✅ CORRECCIÓN: Límites según capital
        if capital < 1000:
            factor_capital = 0.3
        elif capital < 5000:
            factor_capital = 0.6
        elif capital < 10000:
            factor_capital = 0.8
        else:
            factor_capital = 1.0
        
        lote_max_ajustado = lote_max * factor_capital
        
        # Límites especiales para activos de alto margen
        if 'XAU' in simbolo_upper:
            lote_max_ajustado = min(lote_max_ajustado, 0.05)
        elif any(x in simbolo_upper for x in ['BTC', 'ETH', 'SOL']):
            lote_max_ajustado = min(lote_max_ajustado, 0.02)
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            lote_max_ajustado = min(lote_max_ajustado, 0.05)
        
        return {
            'lote_minimo': lote_min,
            'lote_maximo': lote_max_ajustado,
            'lote_recomendado': round((lote_min + lote_max_ajustado) / 2, 2),
            'factor_capital': factor_capital,
            'capital': capital,
        }


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_calculador_lotes(config: Optional[Any] = None,
                            modo_backtest: bool = False) -> CalculadorLotes:
    """Crea una instancia de CalculadorLotes."""
    return CalculadorLotes(
        config=config,
        modo_backtest=modo_backtest
    )