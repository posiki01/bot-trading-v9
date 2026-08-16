#!/usr/bin/env python3
"""
trading/sniper/sniper_quality.py (V9.0)
Validación de calidad extra para el sniper.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger('BotTrading.SniperQuality')


class ValidadorCalidad:
    """
    Validador de calidad extra para el sniper.
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self, config: Optional[Any] = None, modo_backtest: bool = False):
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.SniperQuality')
    
    def validar_condiciones_rapidas(self, simbolo: str, analisis_rapido: Any, direccion: str) -> Tuple[bool, str]:
        """Valida condiciones rápidas."""
        if not analisis_rapido or not analisis_rapido.pasa_filtro:
            return False, analisis_rapido.razon_rechazo if analisis_rapido else "Filtro rápido falló"
        
        # Volumen
        vol_min = 0.05 if self.modo_backtest else 0.10
        if analisis_rapido.volumen_relativo < vol_min:
            if analisis_rapido.rsi_extremo or analisis_rapido.tendencia_fuerte:
                return True, "Volumen bajo pero permitido"
            return False, f"Volumen bajo: {analisis_rapido.volumen_relativo:.2f}x"
        
        # RSI
        rsi_min = 10 if self.modo_backtest else 20
        rsi_max = 90 if self.modo_backtest else 80
        
        if direccion == 'COMPRA' and analisis_rapido.rsi > rsi_max:
            if analisis_rapido.tendencia_corta == 'ALCISTA' and analisis_rapido.rsi < 95:
                return True, "RSI sobrecompra pero permitido por tendencia"
            return False, f"RSI sobrecompra: {analisis_rapido.rsi:.0f}"
        
        if direccion == 'VENTA' and analisis_rapido.rsi < rsi_min:
            if analisis_rapido.tendencia_corta == 'BAJISTA' and analisis_rapido.rsi > 5:
                return True, "RSI sobreventa pero permitido por tendencia"
            return False, f"RSI sobreventa: {analisis_rapido.rsi:.0f}"
        
        return True, "OK"
    
    def validar_condiciones_medias(self, simbolo: str, analisis_medio: Any, direccion: str) -> Tuple[bool, str]:
        """Valida condiciones medias."""
        if not analisis_medio or not analisis_medio.pasa_filtro:
            return False, analisis_medio.razon_rechazo if analisis_medio else "Filtro medio falló"
        
        # ADX
        adx_min = 5 if self.modo_backtest else 10
        if analisis_medio.adx < adx_min:
            if analisis_medio.en_nivel_clave:
                return True, "ADX bajo pero en nivel clave"
            return False, f"ADX bajo: {analisis_medio.adx:.0f}"
        
        # MACD
        if not self.modo_backtest:
            if direccion == 'VENTA' and analisis_medio.macd_histogram > 1.0:
                if analisis_medio.en_nivel_clave:
                    return True, "MACD alto pero en nivel clave"
                return False, f"MACD alcista: {analisis_medio.macd_histogram:.2f}"
            if direccion == 'COMPRA' and analisis_medio.macd_histogram < -1.0:
                if analisis_medio.en_nivel_clave:
                    return True, "MACD bajo pero en nivel clave"
                return False, f"MACD bajista: {analisis_medio.macd_histogram:.2f}"
        
        return True, "OK"
    
    def validar_calidad_extra(self,
                              simbolo: str,
                              analisis_rapido: Any,
                              analisis_medio: Any,
                              direccion: str,
                              score_h1: float = 0,
                              fecha_vela: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Filtros adicionales para mejorar el Win Rate.
        
        Returns:
            (valido, razon)
        """
        if fecha_vela is None:
            fecha_vela = datetime.now(timezone.utc)
        
        hora_utc = fecha_vela.hour + fecha_vela.minute / 60.0
        es_asiatico = 0 <= hora_utc <= 7
        es_overlap = 12 <= hora_utc <= 16
        
        # 1. RSI
        if direccion == 'COMPRA' and analisis_rapido.rsi > 78:
            if analisis_rapido.rsi > 85 and not analisis_medio.en_nivel_clave:
                return False, f"RSI sobrecompra extrema ({analisis_rapido.rsi:.0f}) sin nivel clave"
        elif direccion == 'VENTA' and analisis_rapido.rsi < 22:
            if analisis_rapido.rsi < 15 and not analisis_medio.en_nivel_clave:
                return False, f"RSI sobreventa extrema ({analisis_rapido.rsi:.0f}) sin nivel clave"
        
        # 2. ADX
        if not analisis_medio.en_nivel_clave and analisis_medio.adx < 8:
            if not hasattr(analisis_medio, 'sma20') or not hasattr(analisis_medio, 'sma50'):
                return False, f"ADX bajo ({analisis_medio.adx:.0f}) sin nivel"
        
        # 3. Volumen
        senal_excepcional = (
            analisis_rapido.rsi > 70 or 
            analisis_rapido.rsi < 30 or 
            analisis_medio.en_nivel_clave or
            analisis_medio.adx > 35
        )
        
        if es_asiatico:
            vol_min = 0.03 if self.modo_backtest else 0.06
        elif es_overlap:
            vol_min = 0.15 if self.modo_backtest else 0.20
        else:
            vol_min = 0.10 if self.modo_backtest else 0.15
        
        if senal_excepcional:
            vol_min = vol_min * 0.5
        
        vol_min = max(0.01, vol_min)
        
        if analisis_rapido.volumen_relativo < vol_min:
            return False, f"Volumen bajo ({analisis_rapido.volumen_relativo:.2f}x < {vol_min:.2f}x)"
        
        # 4. Movimiento
        if es_asiatico:
            mov_min = 0.001
        elif es_overlap:
            mov_min = 0.010
        else:
            mov_min = 0.005
        
        if senal_excepcional:
            mov_min = mov_min * 0.4
        
        mov_min = max(0.0005, mov_min)
        
        cambio_abs = abs(analisis_rapido.cambio_vela_pct)
        if cambio_abs < mov_min:
            return False, f"Movimiento insuficiente ({cambio_abs:.3f}% < {mov_min:.3f}%)"
        
        return True, "OK"