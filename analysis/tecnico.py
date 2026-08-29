# core/analisis_tecnico.py - ARCHIVO COMPLETO

#!/usr/bin/env python3
"""
analysis/tecnico.py (V9.0 - REFACTORIZADO)
Análisis técnico para el Bot de Trading.
CAPA DE COMPATIBILIDAD - Usa regimen_indicadores para cálculos avanzados.
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple

# Importar indicadores avanzados
from analysis.regimen_indicadores import RegimenIndicadores

logger = logging.getLogger('BotTrading.Tecnico')


class AnalisisTecnico:
    """
    Clase para análisis técnico de mercado.
    V9.0 - REFACTORIZADO como capa de compatibilidad.
    
    Proporciona indicadores básicos y detección de patrones.
    Los cálculos avanzados delegan en RegimenIndicadores.
    """

    def __init__(self):
        self.logger = logging.getLogger('BotTrading.Tecnico')
        self.indicadores = RegimenIndicadores()

    # ============================================================
    # INDICADORES BÁSICOS (MANTENIDOS)
    # ============================================================

    def calcular_rsi(self, precios: pd.Series, periodo: int = 14) -> pd.Series:
        """
        Calcula el RSI (Relative Strength Index).
        
        Args:
            precios: Serie de precios de cierre
            periodo: Período para el cálculo (default 14)
        
        Returns:
            Serie con los valores de RSI
        """
        if precios is None or len(precios) < periodo:
            return pd.Series([50.0] * len(precios) if len(precios) > 0 else pd.Series([50.0]))
        
        delta = precios.diff()
        ganancia = (delta.where(delta > 0, 0.0)).rolling(window=periodo).mean()
        perdida = (-delta.where(delta < 0, 0.0)).rolling(window=periodo).mean()
        
        rs = ganancia / perdida
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return rsi.fillna(50.0)

    def calcular_macd(self, precios: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """
        Calcula el MACD (Moving Average Convergence Divergence).
        
        Args:
            precios: Serie de precios de cierre
            fast: Período rápido (default 12)
            slow: Período lento (default 26)
            signal: Período de señal (default 9)
        
        Returns:
            Diccionario con 'macd' y 'signal'
        """
        if precios is None or len(precios) < slow:
            return {'macd': pd.Series([0.0] * len(precios)), 'signal': pd.Series([0.0] * len(precios))}
        
        ema_fast = precios.ewm(span=fast, adjust=False).mean()
        ema_slow = precios.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        
        return {'macd': macd_line, 'signal': signal_line}

    def calcular_bollinger(self, precios: pd.Series, periodo: int = 20, desviaciones: int = 2) -> Dict:
        """
        Calcula las Bandas de Bollinger.
        
        Args:
            precios: Serie de precios de cierre
            periodo: Período (default 20)
            desviaciones: Número de desviaciones (default 2)
        
        Returns:
            Diccionario con 'upper', 'middle', 'lower'
        """
        if precios is None or len(precios) < periodo:
            return {'upper': pd.Series([0.0] * len(precios)), 
                    'middle': pd.Series([0.0] * len(precios)), 
                    'lower': pd.Series([0.0] * len(precios))}
        
        sma = precios.rolling(window=periodo).mean()
        std = precios.rolling(window=periodo).std()
        
        upper = sma + (std * desviaciones)
        lower = sma - (std * desviaciones)
        
        return {'upper': upper, 'middle': sma, 'lower': lower}

    def calcular_ema(self, precios: pd.Series, periodo: int = 9) -> pd.Series:
        """Calcula la EMA (Exponential Moving Average)."""
        if precios is None or len(precios) < periodo:
            return pd.Series([0.0] * len(precios) if len(precios) > 0 else pd.Series([0.0]))
        return precios.ewm(span=periodo, adjust=False).mean()

    def calcular_sma(self, precios: pd.Series, periodo: int = 20) -> pd.Series:
        """Calcula la SMA (Simple Moving Average)."""
        if precios is None or len(precios) < periodo:
            return pd.Series([0.0] * len(precios) if len(precios) > 0 else pd.Series([0.0]))
        return precios.rolling(window=periodo).mean()

    # ============================================================
    # INDICADORES AVANZADOS (DELEGAN EN REGIMEN_INDICADORES)
    # ============================================================

    def calcular_adx(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula el ADX (Average Directional Index).
        DELEGA EN RegimenIndicadores.
        """
        return self.indicadores.calcular_adx(df, periodo)

    def calcular_atr(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula el ATR (Average True Range).
        DELEGA EN RegimenIndicadores.
        """
        return self.indicadores.calcular_atr_pct(df, periodo)

    def calcular_bb_width(self, df: pd.DataFrame, periodo: int = 20) -> float:
        """Calcula el ancho de Bollinger Bands."""
        return self.indicadores.calcular_bb_width(df, periodo)

    def calcular_er_kaufman(self, df: pd.DataFrame, periodo: int = 20) -> float:
        """Calcula Efficiency Ratio de Kaufman."""
        return self.indicadores.calcular_er_kaufman(df, periodo)

    def calcular_estructura_swings(self, df: pd.DataFrame) -> str:
        """Analiza estructura de swings."""
        return self.indicadores.calcular_estructura_swings(df)

    def calcular_ichimoku(self, df: pd.DataFrame) -> Dict:
        """Calcula indicadores Ichimoku."""
        return self.indicadores.calcular_ichimoku(df)

    def calcular_chop_index(self, df: pd.DataFrame) -> float:
        """Calcula Choppiness Index."""
        return self.indicadores.calcular_chop_index(df)

    def calcular_vix_proxy(self, df: pd.DataFrame) -> float:
        """Calcula proxy del VIX."""
        return self.indicadores.calcular_vix_proxy(df)

    def calcular_donchian(self, df: pd.DataFrame) -> Dict:
        """Calcula Donchian Channels."""
        return self.indicadores.calcular_donchian(df)

    def calcular_elder_ray(self, df: pd.DataFrame) -> Dict:
        """Calcula Elder Ray Index."""
        return self.indicadores.calcular_elder_ray(df)

    def calcular_sar(self, df: pd.DataFrame) -> float:
        """Calcula Parabolic SAR."""
        return self.indicadores.calcular_sar(df)

    # ============================================================
    # DETECCIÓN DE PATRONES (MANTENIDOS)
    # ============================================================

    def detectar_patrones(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detecta patrones chartistas en el DataFrame.
        
        Returns:
            Lista de patrones encontrados
        """
        patrones = []
        
        if df is None or len(df) < 5:
            return patrones
        
        try:
            vela = df.iloc[-1]
            rango = vela['High'] - vela['Low']
            
            if rango > 0:
                sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
                sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
                cuerpo = abs(vela['Close'] - vela['Open'])
                
                # Pin Bar Alcista
                if sombra_inf / rango > 0.6 and cuerpo / rango < 0.3:
                    patrones.append({
                        'nombre': 'PIN_BAR_ALCISTA',
                        'calidad': 70 + min(30, (sombra_inf / rango) * 100),
                        'direccion': 'COMPRA'
                    })
                
                # Pin Bar Bajista
                if sombra_sup / rango > 0.6 and cuerpo / rango < 0.3:
                    patrones.append({
                        'nombre': 'PIN_BAR_BAJISTA',
                        'calidad': 70 + min(30, (sombra_sup / rango) * 100),
                        'direccion': 'VENTA'
                    })
            
            # Engulfing
            if len(df) > 1:
                vela_actual = df.iloc[-1]
                vela_anterior = df.iloc[-2]
                
                if (vela_actual['Close'] > vela_anterior['Open'] and 
                    vela_actual['Open'] < vela_anterior['Close'] and
                    vela_anterior['Close'] < vela_anterior['Open']):
                    patrones.append({
                        'nombre': 'ENGULFING_ALCISTA',
                        'calidad': 75,
                        'direccion': 'COMPRA'
                    })
                
                if (vela_actual['Close'] < vela_anterior['Open'] and 
                    vela_actual['Open'] > vela_anterior['Close'] and
                    vela_anterior['Close'] > vela_anterior['Open']):
                    patrones.append({
                        'nombre': 'ENGULFING_BAJISTA',
                        'calidad': 75,
                        'direccion': 'VENTA'
                    })
            
            # Doji
            if cuerpo / rango < 0.1 and rango > 0:
                patrones.append({
                    'nombre': 'DOJI',
                    'calidad': 60,
                    'direccion': 'NEUTRAL'
                })
            
        except Exception as e:
            self.logger.debug(f"Error detectando patrones: {e}")
        
        return patrones

    def detectar_divergencia(self, df: pd.DataFrame, rsi: pd.Series, 
                            lookback: int = 10) -> Optional[Dict[str, Any]]:
        """
        Detecta divergencia entre precio y RSI.
        """
        if df is None or len(df) < lookback or rsi is None or len(rsi) < lookback:
            return None
        
        try:
            precio_reciente = df['Close'].iloc[-lookback:]
            rsi_recente = rsi.iloc[-lookback:]
            
            max_precio = precio_reciente.max()
            min_precio = precio_reciente.min()
            max_rsi = rsi_recente.max()
            min_rsi = rsi_recente.min()
            
            idx_max_precio = precio_reciente.idxmax()
            idx_min_precio = precio_reciente.idxmin()
            idx_max_rsi = rsi_recente.idxmax()
            idx_min_rsi = rsi_recente.idxmin()
            
            # Divergencia Bajista
            if idx_max_precio > idx_max_rsi and max_precio > precio_reciente.iloc[-5]:
                return {
                    'tipo': 'BEARISH',
                    'confianza': 70,
                    'descripcion': 'Divergencia bajista (precio > RSI)'
                }
            
            # Divergencia Alcista
            if idx_min_precio > idx_min_rsi and min_precio < precio_reciente.iloc[-5]:
                return {
                    'tipo': 'BULLISH',
                    'confianza': 70,
                    'descripcion': 'Divergencia alcista (precio < RSI)'
                }
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error detectando divergencia: {e}")
            return None

    def identificar_tendencia(self, df: pd.DataFrame) -> Tuple[str, float]:
        """
        Identifica la tendencia actual.
        
        Returns:
            (tendencia, fuerza) donde tendencia es 'ALCISTA', 'BAJISTA' o 'LATERAL'
        """
        if df is None or len(df) < 50:
            return 'LATERAL', 0.0
        
        try:
            close = df['Close']
            sma20 = close.rolling(20).mean().iloc[-1]
            sma50 = close.rolling(50).mean().iloc[-1]
            sma200 = close.rolling(200).mean().iloc[-1] if len(df) >= 200 else sma50
            
            pendiente = (sma20 - close.rolling(20).mean().iloc[-5]) / close.rolling(20).mean().iloc[-5] * 100
            
            if sma20 > sma50 and sma50 > sma200 and pendiente > 0.1:
                return 'ALCISTA', min(100, 50 + pendiente * 10)
            elif sma20 < sma50 and sma50 < sma200 and pendiente < -0.1:
                return 'BAJISTA', min(100, 50 + abs(pendiente) * 10)
            else:
                return 'LATERAL', 30.0
                
        except Exception as e:
            self.logger.debug(f"Error identificando tendencia: {e}")
            return 'LATERAL', 0.0

    def identificar_order_blocks(self, df: pd.DataFrame) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        Identifica Order Blocks (bullish y bearish).
        """
        if df is None or len(df) < 20:
            return None, None
        
        try:
            high = df['High']
            low = df['Low']
            
            high_ultimo = high.iloc[-20:].max()
            low_ultimo = low.iloc[-20:].min()
            precio_actual = df['Close'].iloc[-1]
            
            bullish_ob = None
            if low_ultimo > precio_actual * 0.99:
                bullish_ob = {
                    'top': low_ultimo * 1.002,
                    'bottom': low_ultimo * 0.998,
                    'tipo': 'BULLISH'
                }
            
            bearish_ob = None
            if high_ultimo < precio_actual * 1.01:
                bearish_ob = {
                    'top': high_ultimo * 1.002,
                    'bottom': high_ultimo * 0.998,
                    'tipo': 'BEARISH'
                }
            
            return bullish_ob, bearish_ob
            
        except Exception as e:
            self.logger.debug(f"Error identificando order blocks: {e}")
            return None, None

    def detectar_wyckoff(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Detecta fases de Wyckoff.
        """
        if df is None or len(df) < 30:
            return {'fase': 'NEUTRAL', 'confianza': 0}
        
        try:
            close = df['Close']
            sma20 = close.rolling(20).mean()
            sma50 = close.rolling(50).mean()
            
            sma20_actual = sma20.iloc[-1]
            sma50_actual = sma50.iloc[-1]
            precio_actual = close.iloc[-1]
            
            if sma20_actual > sma50_actual and precio_actual > sma20_actual:
                return {'fase': 'ACUMULACION', 'confianza': 60}
            elif sma20_actual < sma50_actual and precio_actual < sma20_actual:
                return {'fase': 'DISTRIBUCION', 'confianza': 60}
            elif precio_actual > sma50_actual and precio_actual < sma20_actual:
                return {'fase': 'SPRING', 'confianza': 50}
            elif precio_actual < sma50_actual and precio_actual > sma20_actual:
                return {'fase': 'UPTHRUST', 'confianza': 50}
            else:
                return {'fase': 'NEUTRAL', 'confianza': 30}
                
        except Exception as e:
            self.logger.debug(f"Error detectando Wyckoff: {e}")
            return {'fase': 'NEUTRAL', 'confianza': 0}