# core/analisis_tecnico.py - ARCHIVO COMPLETO

#!/usr/bin/env python3
"""
core/tecnico.py
Análisis técnico para el Bot de Trading.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
import logging

logger = logging.getLogger('BotTrading.AnalisisTecnico')


class AnalisisTecnico:
    """
    Clase para análisis técnico de mercado.
    Proporciona indicadores y detección de patrones.
    """

    def __init__(self):
        self.logger = logging.getLogger('BotTrading.AnalisisTecnico')

    # ============================================================
    # INDICADORES TÉCNICOS
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

    def calcular_adx(self, df: pd.DataFrame, periodo: int = 14) -> pd.Series:
        """
        Calcula el ADX (Average Directional Index).
        
        Args:
            df: DataFrame con columnas 'High', 'Low', 'Close'
            periodo: Período (default 14)
        
        Returns:
            Serie con los valores de ADX
        """
        if df is None or len(df) < periodo:
            return pd.Series([0.0] * len(df) if len(df) > 0 else pd.Series([0.0]))
        
        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=periodo).mean()
        
        up_move = high.diff()
        down_move = -low.diff()
        
        plus_dm = pd.Series(0.0, index=df.index)
        minus_dm = pd.Series(0.0, index=df.index)
        
        for i in range(1, len(df)):
            if up_move.iloc[i] > down_move.iloc[i] and up_move.iloc[i] > 0:
                plus_dm.iloc[i] = float(up_move.iloc[i])
            else:
                plus_dm.iloc[i] = 0.0
            
            if down_move.iloc[i] > up_move.iloc[i] and down_move.iloc[i] > 0:
                minus_dm.iloc[i] = float(down_move.iloc[i])
            else:
                minus_dm.iloc[i] = 0.0
        
        plus_di = 100.0 * plus_dm.rolling(window=periodo).mean() / atr
        minus_di = 100.0 * minus_dm.rolling(window=periodo).mean() / atr
        
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.rolling(window=periodo).mean()
        
        return adx.fillna(0.0)

    def calcular_atr(self, df: pd.DataFrame, periodo: int = 14) -> pd.Series:
        """
        Calcula el ATR (Average True Range).
        
        Args:
            df: DataFrame con columnas 'High', 'Low', 'Close'
            periodo: Período (default 14)
        
        Returns:
            Serie con los valores de ATR
        """
        if df is None or len(df) < periodo:
            return pd.Series([0.001] * len(df) if len(df) > 0 else pd.Series([0.001]))
        
        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=periodo).mean()
        
        return atr.fillna(0.001)

    def calcular_ema(self, precios: pd.Series, periodo: int = 9) -> pd.Series:
        """
        Calcula la EMA (Exponential Moving Average).
        
        Args:
            precios: Serie de precios
            periodo: Período (default 9)
        
        Returns:
            Serie con los valores de EMA
        """
        if precios is None or len(precios) < periodo:
            return pd.Series([0.0] * len(precios) if len(precios) > 0 else pd.Series([0.0]))
        
        return precios.ewm(span=periodo, adjust=False).mean()

    def calcular_sma(self, precios: pd.Series, periodo: int = 20) -> pd.Series:
        """
        Calcula la SMA (Simple Moving Average).
        
        Args:
            precios: Serie de precios
            periodo: Período (default 20)
        
        Returns:
            Serie con los valores de SMA
        """
        if precios is None or len(precios) < periodo:
            return pd.Series([0.0] * len(precios) if len(precios) > 0 else pd.Series([0.0]))
        
        return precios.rolling(window=periodo).mean()

    # ============================================================
    # DETECCIÓN DE PATRONES
    # ============================================================

    def detectar_patrones(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detecta patrones chartistas en el DataFrame.
        
        Args:
            df: DataFrame con columnas 'Open', 'High', 'Low', 'Close'
        
        Returns:
            Lista de patrones encontrados
        """
        patrones = []
        
        if df is None or len(df) < 5:
            return patrones
        
        try:
            # Pin Bar
            vela = df.iloc[-1]
            rango = vela['High'] - vela['Low']
            
            if rango > 0:
                sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
                sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
                cuerpo = abs(vela['Close'] - vela['Open'])
                
                # Pin Bar Alcista (sombra inferior larga)
                if sombra_inf / rango > 0.6 and cuerpo / rango < 0.3:
                    patrones.append({
                        'nombre': 'PIN_BAR_ALCISTA',
                        'calidad': 70 + min(30, (sombra_inf / rango) * 100),
                        'direccion': 'COMPRA'
                    })
                
                # Pin Bar Bajista (sombra superior larga)
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
                
                # Engulfing Alcista
                if (vela_actual['Close'] > vela_anterior['Open'] and 
                    vela_actual['Open'] < vela_anterior['Close'] and
                    vela_anterior['Close'] < vela_anterior['Open']):
                    patrones.append({
                        'nombre': 'ENGULFING_ALCISTA',
                        'calidad': 75,
                        'direccion': 'COMPRA'
                    })
                
                # Engulfing Bajista
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
        
        Args:
            df: DataFrame con columnas 'High', 'Low', 'Close'
            rsi: Serie de RSI
            lookback: Período de búsqueda (default 10)
        
        Returns:
            Diccionario con la divergencia o None
        """
        if df is None or len(df) < lookback or rsi is None or len(rsi) < lookback:
            return None
        
        try:
            # Precios recientes
            precio_reciente = df['Close'].iloc[-lookback:]
            rsi_reciente = rsi.iloc[-lookback:]
            
            # Máximos y mínimos
            max_precio = precio_reciente.max()
            min_precio = precio_reciente.min()
            max_rsi = rsi_reciente.max()
            min_rsi = rsi_reciente.min()
            
            # Posiciones de máximos y mínimos
            idx_max_precio = precio_reciente.idxmax()
            idx_min_precio = precio_reciente.idxmin()
            idx_max_rsi = rsi_reciente.idxmax()
            idx_min_rsi = rsi_reciente.idxmin()
            
            # Divergencia Bajista (precio sube, RSI baja)
            if idx_max_precio > idx_max_rsi and max_precio > precio_reciente.iloc[-5]:
                return {
                    'tipo': 'BEARISH',
                    'confianza': 70,
                    'descripcion': 'Divergencia bajista (precio > RSI)'
                }
            
            # Divergencia Alcista (precio baja, RSI sube)
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
        
        Args:
            df: DataFrame con columna 'Close'
        
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
            
            # Pendiente de SMA20
            pendiente = (sma20 - close.rolling(20).mean().iloc[-5]) / close.rolling(20).mean().iloc[-5] * 100
            
            # Determinar tendencia
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
        
        Args:
            df: DataFrame con columnas 'High', 'Low', 'Close'
        
        Returns:
            (bullish_ob, bearish_ob)
        """
        if df is None or len(df) < 20:
            return None, None
        
        try:
            # Simplificado: buscar máximos y mínimos recientes
            high = df['High']
            low = df['Low']
            
            # Últimos 20 periodos
            high_ultimo = high.iloc[-20:].max()
            low_ultimo = low.iloc[-20:].min()
            precio_actual = df['Close'].iloc[-1]
            
            # Order Block Alcista (soporte)
            bullish_ob = None
            if low_ultimo > precio_actual * 0.99:
                bullish_ob = {
                    'top': low_ultimo * 1.002,
                    'bottom': low_ultimo * 0.998,
                    'tipo': 'BULLISH'
                }
            
            # Order Block Bajista (resistencia)
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
        
        Args:
            df: DataFrame con columnas 'Close'
        
        Returns:
            Diccionario con la fase de Wyckoff
        """
        if df is None or len(df) < 30:
            return {'fase': 'NEUTRAL', 'confianza': 0}
        
        try:
            close = df['Close']
            sma20 = close.rolling(20).mean()
            sma50 = close.rolling(50).mean()
            
            # Últimos valores
            sma20_actual = sma20.iloc[-1]
            sma50_actual = sma50.iloc[-1]
            precio_actual = close.iloc[-1]
            
            # Detectar fases simples
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