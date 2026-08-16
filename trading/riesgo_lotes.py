#!/usr/bin/env python3
"""
trading/riesgo_lotes.py (V9.0)
Cálculo de lotes optimizado para trading.
RESPONSABILIDAD: Solo calcular lotes, no gestionar riesgo.
"""

import logging
from typing import Optional, Dict, Any
from decimal import Decimal

logger = logging.getLogger('BotTrading.RiesgoLotes')


class CalculadorLotes:
    """
    Calcula el tamaño de posición óptimo.
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self, config: Optional[Any] = None):
        """
        Inicializa el calculador de lotes.
        
        Args:
            config: Configuración
        """
        self.config = config
        self.logger = logging.getLogger('BotTrading.RiesgoLotes')
        
        # Cargar configuración
        self._cargar_configuracion()
    
    def _cargar_configuracion(self):
        """Carga configuración desde Config."""
        if self.config:
            self.max_lote_absoluto = getattr(self.config, 'MAX_LOTE_ABSOLUTO', 0.05)
            self.min_lote_absoluto = getattr(self.config, 'MIN_LOTE_ABSOLUTO', 0.01)
            self.max_risk_per_trade = getattr(self.config, 'MAX_RISK_PER_TRADE_PCT', 0.01)
        else:
            self.max_lote_absoluto = 0.05
            self.min_lote_absoluto = 0.01
            self.max_risk_per_trade = 0.01
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def calcular_lotes(self,
                       entrada: float,
                       stop_loss: float,
                       probabilidad: float,
                       simbolo: str,
                       capital: float,
                       tick_value: float = 0.01,
                       tick_size: float = 0.00001,
                       point: float = 0.00001,
                       atr: float = 0.001,
                       atr_medio: float = 0.001,
                       spread: float = 0.0,
                       margin_level: Optional[float] = None,
                       factor_volatilidad: float = 1.0,
                       factor_conviccion: float = 1.0) -> float:
        """
        Calcula el tamaño de posición óptimo.
        
        Args:
            entrada: Precio de entrada
            stop_loss: Precio de stop loss
            probabilidad: Probabilidad de éxito (0-100)
            simbolo: Símbolo
            capital: Capital disponible
            tick_value: Valor del tick
            tick_size: Tamaño del tick
            point: Punto del símbolo
            atr: ATR actual
            atr_medio: ATR medio (para ajuste)
            spread: Spread actual
            margin_level: Nivel de margen
            factor_volatilidad: Factor de volatilidad
            factor_conviccion: Factor de convicción
        
        Returns:
            Lotes calculados
        """
        # 1. Validaciones básicas
        if capital <= 0 or entrada <= 0 or stop_loss <= 0:
            return 0.0
        
        distancia = abs(entrada - stop_loss)
        if distancia == 0:
            return 0.0
        
        # 2. Calcular pip value y distancia en pips
        pip_size = self._obtener_pip_size(simbolo)
        pip_val = self._obtener_pip_value(simbolo)
        
        distancia_en_pips = distancia / pip_size if pip_size > 0 else 0
        if distancia_en_pips <= 0:
            return 0.0
        
        # 3. Calcular riesgo máximo en USD
        riesgo_max_usd = self._calcular_riesgo_maximo(
            capital=capital,
            probabilidad=probabilidad,
            factor_volatilidad=factor_volatilidad,
            factor_conviccion=factor_conviccion
        )
        
        # 4. Calcular lotes base
        pip_value_por_lote = pip_val * 0.01  # Valor de pip por 0.01 lotes
        if pip_value_por_lote <= 0:
            return 0.0
        
        lotes_teoricos = riesgo_max_usd / (distancia_en_pips * pip_value_por_lote)
        
        # 5. Aplicar ajustes
        lotes_ajustados = self._aplicar_ajustes(
            lotes=lotes_teoricos,
            simbolo=simbolo,
            atr=atr,
            atr_medio=atr_medio,
            spread=spread,
            margin_level=margin_level,
            capital=capital
        )
        
        # 6. Redondear y limitar
        lotes_finales = self._redondear_y_limitar(lotes_ajustados, simbolo)
        
        self.logger.debug(
            f"📊 Lotes calculados: {lotes_finales:.3f} "
            f"(base: {lotes_teoricos:.3f}, ajustado: {lotes_ajustados:.3f})"
        )
        
        return lotes_finales
    
    # ============================================================
    # CÁLCULO DE RIESGO MÁXIMO
    # ============================================================
    
    def _calcular_riesgo_maximo(self,
                                capital: float,
                                probabilidad: float,
                                factor_volatilidad: float = 1.0,
                                factor_conviccion: float = 1.0) -> float:
        """
        Calcula el riesgo máximo en USD.
        
        Args:
            capital: Capital disponible
            probabilidad: Probabilidad de éxito (0-100)
            factor_volatilidad: Factor de volatilidad
            factor_conviccion: Factor de convicción
        
        Returns:
            Riesgo máximo en USD
        """
        # 1. Riesgo base por capital
        riesgo_base = capital * self.max_risk_per_trade
        
        # 2. Ajuste por probabilidad (Kelly Criterion simplificado)
        if probabilidad > 80:
            factor_prob = 1.2
        elif probabilidad > 65:
            factor_prob = 1.0
        elif probabilidad > 50:
            factor_prob = 0.8
        else:
            factor_prob = 0.5
        
        # 3. Riesgo final
        riesgo_max = riesgo_base * factor_prob * factor_volatilidad * factor_conviccion
        
        # 4. Limitar
        riesgo_max = max(riesgo_max, capital * 0.001)  # Mínimo 0.1%
        riesgo_max = min(riesgo_max, capital * 0.025)  # Máximo 2.5%
        
        return riesgo_max
    
    # ============================================================
    # AJUSTES
    # ============================================================
    
    def _aplicar_ajustes(self,
                         lotes: float,
                         simbolo: str,
                         atr: float,
                         atr_medio: float,
                         spread: float,
                         margin_level: Optional[float],
                         capital: float) -> float:
        """
        Aplica ajustes al tamaño de posición.
        
        Args:
            lotes: Lotes base
            simbolo: Símbolo
            atr: ATR actual
            atr_medio: ATR medio
            spread: Spread actual
            margin_level: Nivel de margen
            capital: Capital disponible
        
        Returns:
            Lotes ajustados
        """
        lotes_ajustados = lotes
        
        # 1. Ajuste por ATR (volatilidad)
        if atr > 0 and atr_medio > 0:
            atr_ratio = atr / atr_medio
            if atr_ratio > 1.5:
                lotes_ajustados *= 0.7  # Reducir en alta volatilidad
            elif atr_ratio > 1.2:
                lotes_ajustados *= 0.85
            elif atr_ratio < 0.7:
                lotes_ajustados *= 1.15  # Aumentar en baja volatilidad
        
        # 2. Ajuste por spread
        if spread > 0:
            spread_ratio = spread / 0.0001  # Asumiendo spread base
            if spread_ratio > 2.0:
                lotes_ajustados *= 0.8
        
        # 3. Ajuste por margen
        if margin_level is not None:
            if margin_level < 300:
                lotes_ajustados *= 0.3
            elif margin_level < 500:
                lotes_ajustados *= 0.5
            elif margin_level < 1000:
                lotes_ajustados *= 0.7
        
        # 4. Ajuste por capital (más conservador con capital bajo)
        if capital < 500:
            lotes_ajustados *= 0.5
        elif capital < 1000:
            lotes_ajustados *= 0.8
        
        return max(0.01, lotes_ajustados)
    
    # ============================================================
    # REDONDEO Y LÍMITES
    # ============================================================
    
    def _redondear_y_limitar(self, lotes: float, simbolo: str) -> float:
        """
        Redondea y limita los lotes según el tipo de activo.
        
        Args:
            lotes: Lotes a redondear
            simbolo: Símbolo
        
        Returns:
            Lotes redondeados y limitados
        """
        simbolo_upper = simbolo.upper()
        
        # Determinar paso y límites según tipo de activo
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            paso = 0.1
            min_lote = 0.1
            max_lote = min(self.max_lote_absoluto, 10.0)
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            paso = 0.01
            min_lote = 0.01
            max_lote = self.max_lote_absoluto
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            paso = 0.01
            min_lote = 0.01
            max_lote = self.max_lote_absoluto
        else:
            paso = 0.01
            min_lote = 0.01
            max_lote = self.max_lote_absoluto
        
        # Redondear al múltiplo del paso
        if paso > 0:
            lotes_redondeados = round(lotes / paso) * paso
        else:
            lotes_redondeados = lotes
        
        # Aplicar límites
        lotes_redondeados = max(min_lote, min(max_lote, lotes_redondeados))
        
        return round(lotes_redondeados, 3)
    
    # ============================================================
    # UTILIDADES
    # ============================================================
    
    def _obtener_pip_size(self, simbolo: str) -> float:
        """
        Obtiene el tamaño de un pip para el símbolo.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Tamaño del pip
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
    
    def _obtener_pip_value(self, simbolo: str) -> float:
        """
        Obtiene el valor de un pip por lote estándar.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Valor del pip por lote estándar
        """
        simbolo_upper = simbolo.upper()
        
        if any(x in simbolo_upper for x in ['JPY']):
            return 10.0  # JPY pairs
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 10.0  # Metals
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0   # Indices
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0   # Crypto
        return 10.0      # Forex standard
    
    def _obtener_lote_minimo_por_activo(self, simbolo: str) -> float:
        """
        Obtiene el lote mínimo permitido para el tipo de activo.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Lote mínimo
        """
        simbolo_upper = simbolo.upper()
        
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 0.1
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 0.01
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 0.01
        return 0.01
    
    def calcular_factor_volatilidad(self, atr: float, precio: float) -> float:
        """
        Calcula el factor de volatilidad basado en ATR.
        
        Args:
            atr: ATR actual
            precio: Precio actual
        
        Returns:
            Factor de volatilidad (0.5-1.5)
        """
        if precio <= 0 or atr <= 0:
            return 1.0
        
        atr_pct = (atr / precio) * 100
        
        if atr_pct > 1.0:
            return 0.7
        elif atr_pct > 0.5:
            return 0.85
        elif atr_pct > 0.3:
            return 1.0
        else:
            return 1.2