#!/usr/bin/env python3
"""
trading/decision_cierre.py (V9.2 - CORREGIDO COMPLETAMENTE)
Decide si cerrar una operación con ganancia anticipada.

V9.2 - CORRECCIONES:
- ✅ Acepta dirección 'BUY'/'SELL' además de 'COMPRA'/'VENTA'
- ✅ Verificación de datos de análisis antes de usar
- ✅ Lógica más robusta para decisión de cierre
- ✅ Logs más detallados y claros
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger('BotTrading.DecisionCierre')


class DecisorCierre:
    """
    Decide si cerrar una operación con ganancia anticipada.
    V9.2 - CORREGIDO COMPLETAMENTE.
    """
    
    def __init__(self, analisis_capas: Any = None):
        """Inicializa el decisor de cierre."""
        self.analisis_capas = analisis_capas
        self.logger = logging.getLogger('BotTrading.DecisionCierre')
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def decidir_si_cerrar(self,
                          simbolo: str,
                          direccion: str,
                          ganancia_pips: float,
                          precio_actual: float,
                          entry_price: float,
                          sl: float,
                          tp: float,
                          analisis_rapido: Optional[Any] = None,
                          analisis_medio: Optional[Any] = None,
                          modo: str = 'RETEST',
                          regimen: str = 'INCERTO') -> Optional[str]:
        """
        Decide si conviene cerrar la operación con ganancia anticipada.
        V9.2 - CORREGIDO: Acepta 'BUY'/'SELL' y 'COMPRA'/'VENTA'.
        
        Args:
            simbolo: Símbolo
            direccion: Dirección ('COMPRA'/'VENTA' o 'BUY'/'SELL')
            ganancia_pips: Ganancia actual en pips
            precio_actual: Precio actual
            entry_price: Precio de entrada
            sl: Stop Loss
            tp: Take Profit
            analisis_rapido: Análisis rápido (M5)
            analisis_medio: Análisis medio (H1)
            modo: Modo de entrada
            regimen: Régimen de mercado
        
        Returns:
            Razón del cierre o None si no cerrar
        """
        # ============================================================
        # 1. NORMALIZAR DIRECCIÓN (CORREGIDO)
        # ============================================================
        direccion = self._normalizar_direccion(direccion)
        
        if direccion not in ['COMPRA', 'VENTA']:
            self.logger.warning(f"⚠️ {simbolo}: Dirección inválida ({direccion})")
            return None
        
        # ============================================================
        # 2. SI LA GANANCIA ES MUY ALTA, CERRAR
        # ============================================================
        if ganancia_pips >= 60:
            self.logger.info(f"🎯 {simbolo}: Cierre por ganancia alta ({ganancia_pips:.1f} pips)")
            return f"GANANCIA_ALTA_{ganancia_pips:.1f}_PIPS"
        
        # ============================================================
        # 3. SI NO HAY ANÁLISIS, NO CERRAR POR DECISIÓN
        # ============================================================
        if analisis_medio is None:
            self.logger.debug(f"ℹ️ {simbolo}: Sin análisis medio, no cerrar por decisión")
            return None
        
        # ============================================================
        # 4. SI HAY RESISTENCIA CERCA Y ESTÁ TOCANDO, CERRAR
        # ============================================================
        if direccion == 'COMPRA' and hasattr(analisis_medio, 'resistencia_cercana'):
            resistencia = analisis_medio.resistencia_cercana
            if resistencia and resistencia > 0:
                dist_resistencia = abs(resistencia - precio_actual) / precio_actual * 100
                if dist_resistencia < 0.2 and ganancia_pips > 15:
                    self.logger.info(f"🎯 {simbolo}: Cierre por resistencia cercana ({dist_resistencia:.2f}%)")
                    return f"RESISTENCIA_CERCA_{dist_resistencia:.2f}%"
        
        if direccion == 'VENTA' and hasattr(analisis_medio, 'soporte_cercano'):
            soporte = analisis_medio.soporte_cercano
            if soporte and soporte > 0:
                dist_soporte = abs(soporte - precio_actual) / precio_actual * 100
                if dist_soporte < 0.2 and ganancia_pips > 15:
                    self.logger.info(f"🎯 {simbolo}: Cierre por soporte cercano ({dist_soporte:.2f}%)")
                    return f"SOPORTE_CERCA_{dist_soporte:.2f}%"
        
        # ============================================================
        # 5. SI RSI ESTÁ SOBRECOMPRADO Y ES COMPRA, CERRAR
        # ============================================================
        if analisis_rapido is not None and hasattr(analisis_rapido, 'rsi'):
            rsi = analisis_rapido.rsi
            
            if direccion == 'COMPRA' and rsi > 75:
                if ganancia_pips > 10:
                    self.logger.info(f"🎯 {simbolo}: Cierre por RSI sobrecompra ({rsi:.0f})")
                    return f"RSI_SOBRECOMPRA_{rsi:.0f}"
            
            if direccion == 'VENTA' and rsi < 25:
                if ganancia_pips > 10:
                    self.logger.info(f"🎯 {simbolo}: Cierre por RSI sobreventa ({rsi:.0f})")
                    return f"RSI_SOBREVENTA_{rsi:.0f}"
        
        # ============================================================
        # 6. SI MACD ESTÁ CONTRARIANDO LA DIRECCIÓN
        # ============================================================
        if hasattr(analisis_medio, 'macd_histogram'):
            macd_hist = analisis_medio.macd_histogram
            
            if direccion == 'COMPRA' and macd_hist < 0:
                if ganancia_pips > 20:
                    self.logger.info(f"🎯 {simbolo}: Cierre por MACD bajista ({macd_hist:.4f})")
                    return f"MACD_BAJISTA_{macd_hist:.4f}"
            
            if direccion == 'VENTA' and macd_hist > 0:
                if ganancia_pips > 20:
                    self.logger.info(f"🎯 {simbolo}: Cierre por MACD alcista ({macd_hist:.4f})")
                    return f"MACD_ALCISTA_{macd_hist:.4f}"
        
        # ============================================================
        # 7. SI ADX ESTÁ BAJANDO (PÉRDIDA DE MOMENTO)
        # ============================================================
        if hasattr(analisis_medio, 'adx'):
            adx = analisis_medio.adx
            
            if adx < 15 and ganancia_pips > 15:
                self.logger.info(f"🎯 {simbolo}: Cierre por ADX bajo ({adx:.0f})")
                return f"ADX_BAJO_{adx:.0f}"
        
        # ============================================================
        # 8. SI R:R YA ES BUENO Y EL PRECIO ESTÁ EN UN NIVEL CLAVE
        # ============================================================
        if sl and tp and ganancia_pips > 0:
            sl_dist = abs(entry_price - sl)
            if sl_dist > 0:
                rr_actual = abs(precio_actual - entry_price) / sl_dist
                
                if rr_actual >= 2.0 and hasattr(analisis_medio, 'en_nivel_clave'):
                    if analisis_medio.en_nivel_clave:
                        self.logger.info(f"🎯 {simbolo}: Cierre por R:R alto en nivel clave ({rr_actual:.1f})")
                        return f"RR_ALTO_YA_EN_NIVEL_{rr_actual:.1f}"
        
        return None
    
    # ============================================================
    # ✅ CORRECCIÓN V9.2: Normalizar dirección
    # ============================================================
    
    def _normalizar_direccion(self, direccion: str) -> str:
        """
        Normaliza la dirección a formato interno.
        V9.2 - CORREGIDO: Acepta BUY/SELL y COMPRA/VENTA.
        
        Args:
            direccion: Dirección (BUY, SELL, COMPRA, VENTA)
        
        Returns:
            Dirección normalizada ('COMPRA' o 'VENTA')
        """
        if direccion is None:
            return 'NEUTRAL'
        
        direccion = direccion.upper().strip()
        
        if direccion in ['BUY', 'LONG', 'COMPRA', 'B']:
            return 'COMPRA'
        if direccion in ['SELL', 'SHORT', 'VENTA', 'S']:
            return 'VENTA'
        
        return 'NEUTRAL'


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_decisor_cierre(analisis_capas: Any = None) -> DecisorCierre:
    """
    Crea una instancia de DecisorCierre.
    
    Args:
        analisis_capas: Análisis por capas (opcional)
    
    Returns:
        DecisorCierre
    """
    return DecisorCierre(
        analisis_capas=analisis_capas
    )