#!/usr/bin/env python3
"""
analysis/regimen_indicadores.py (V9.0)
Cálculo de indicadores técnicos para clasificación de régimen.
RESPONSABILIDAD: Solo calcular indicadores, no clasificar.
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger('BotTrading.RegimenIndicadores')


class RegimenIndicadores:
    """
    Calcula indicadores técnicos para clasificación de régimen.
    V9.0 - INDEPENDIENTE.
    """
    
    @staticmethod
    def calcular_adx(df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula ADX (Average Directional Index).
        
        Args:
            df: DataFrame con High, Low, Close
            periodo: Período (default 14)
        
        Returns:
            Valor ADX
        """
        if df is None or len(df) < periodo + 1:
            return 0.0
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            # True Range
            tr1 = high - low
            tr2 = (high - close.shift()).abs()
            tr3 = (low - close.shift()).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(periodo).mean()
            
            # Directional Movement
            up_move = high.diff()
            down_move = -low.diff()
            
            plus_dm = pd.Series(
                np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
                index=df.index
            )
            minus_dm = pd.Series(
                np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
                index=df.index
            )
            
            atr_seguro = atr.replace(0, np.nan)
            plus_di = 100 * plus_dm.rolling(periodo).mean() / atr_seguro
            minus_di = 100 * minus_dm.rolling(periodo).mean() / atr_seguro
            
            di_suma = (plus_di + minus_di).replace(0, np.nan)
            dx = 100 * (plus_di - minus_di).abs() / di_suma
            adx = dx.rolling(periodo).mean().iloc[-1]
            
            return float(adx) if pd.notna(adx) else 0.0
            
        except Exception as e:
            logger.debug(f"Error calculando ADX: {e}")
            return 0.0
    
    @staticmethod
    def calcular_er_kaufman(df: pd.DataFrame, periodo: int = 20) -> float:
        """
        Calcula Efficiency Ratio de Kaufman.
        
        Args:
            df: DataFrame con Close
            periodo: Período (default 20)
        
        Returns:
            Efficiency Ratio (0-1)
        """
        if df is None or len(df) < periodo:
            return 0.0
        
        try:
            close = df['Close']
            cambio_neto = abs(close.iloc[-1] - close.iloc[-periodo])
            suma_mov = abs(close.diff()).iloc[-periodo:].sum()
            
            er = cambio_neto / suma_mov if suma_mov > 0 else 0.0
            return float(er) if not pd.isna(er) else 0.0
            
        except Exception as e:
            logger.debug(f"Error calculando ER: {e}")
            return 0.0
    
    @staticmethod
    def calcular_bb_width(df: pd.DataFrame, periodo: int = 20) -> float:
        """
        Calcula ancho de Bollinger Bands como porcentaje.
        
        Args:
            df: DataFrame con Close
            periodo: Período (default 20)
        
        Returns:
            Ancho de BB en porcentaje
        """
        if df is None or len(df) < periodo:
            return 50.0
        
        try:
            close = df['Close']
            sma = close.rolling(periodo).mean()
            std = close.rolling(periodo).std()
            
            upper = sma + (std * 2)
            lower = sma - (std * 2)
            
            width = ((upper - lower) / sma * 100).iloc[-1]
            return float(width) if not pd.isna(width) else 50.0
            
        except Exception as e:
            logger.debug(f"Error calculando BB width: {e}")
            return 50.0
    
    @staticmethod
    def calcular_atr_pct(df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula ATR como porcentaje del precio.
        
        Args:
            df: DataFrame con High, Low, Close
            periodo: Período (default 14)
        
        Returns:
            ATR como porcentaje
        """
        if df is None or len(df) < periodo:
            return 0.5
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            tr = pd.concat([
                high - low,
                abs(high - close.shift()),
                abs(low - close.shift())
            ], axis=1).max(axis=1)
            
            atr = tr.rolling(periodo).mean().iloc[-1]
            precio = close.iloc[-1]
            
            atr_pct = (atr / precio * 100) if precio > 0 else 0
            return float(atr_pct) if not pd.isna(atr_pct) else 0.5
            
        except Exception as e:
            logger.debug(f"Error calculando ATR pct: {e}")
            return 0.5
    
    @staticmethod
    def calcular_estructura_swings(df: pd.DataFrame) -> str:
        """
        Analiza estructura de swings (máximos/mínimos).
        
        Args:
            df: DataFrame con High, Low
        
        Returns:
            'ALCISTA', 'BAJISTA', 'RANGO', o 'DESCONOCIDO'
        """
        if df is None or len(df) < 30:
            return 'DESCONOCIDO'
        
        try:
            high = df['High']
            low = df['Low']
            
            pivots_high = []
            pivots_low = []
            
            for i in range(5, len(df) - 5):
                if high.iloc[i] == high.iloc[i-5:i+6].max():
                    pivots_high.append((i, high.iloc[i]))
                if low.iloc[i] == low.iloc[i-5:i+6].min():
                    pivots_low.append((i, low.iloc[i]))
            
            if len(pivots_high) < 2 or len(pivots_low) < 2:
                return 'DESCONOCIDO'
            
            highs_increasing = pivots_high[-1][1] > pivots_high[0][1]
            lows_increasing = pivots_low[-1][1] > pivots_low[0][1]
            
            if highs_increasing and lows_increasing:
                return 'ALCISTA'
            elif not highs_increasing and not lows_increasing:
                return 'BAJISTA'
            else:
                return 'RANGO'
                
        except Exception as e:
            logger.debug(f"Error calculando estructura: {e}")
            return 'DESCONOCIDO'
    
    @staticmethod
    def calcular_ichimoku(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calcula indicadores Ichimoku.
        
        Args:
            df: DataFrame con High, Low, Close
        
        Returns:
            Diccionario con indicadores Ichimoku
        """
        if df is None or len(df) < 52:
            return {
                'tenkan': 0, 'kijun': 0, 'senkou_a': 0, 'senkou_b': 0,
                'senkou_ancho': 0, 'tendencia': 'NEUTRAL'
            }
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            # Tenkan-sen (Conversión)
            tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
            
            # Kijun-sen (Base)
            kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
            
            # Senkou Span A (desplazado 26)
            senkou_a = ((tenkan + kijun) / 2).shift(26)
            
            # Senkou Span B (desplazado 26)
            senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
            
            # Valores actuales
            tenkan_actual = tenkan.iloc[-1] if not pd.isna(tenkan.iloc[-1]) else 0
            kijun_actual = kijun.iloc[-1] if not pd.isna(kijun.iloc[-1]) else 0
            senkou_a_actual = senkou_a.iloc[-1] if not pd.isna(senkou_a.iloc[-1]) else 0
            senkou_b_actual = senkou_b.iloc[-1] if not pd.isna(senkou_b.iloc[-1]) else 0
            precio_actual = close.iloc[-1]
            
            # Ancho de la nube
            senkou_ancho = abs(senkou_a_actual - senkou_b_actual) / precio_actual if precio_actual > 0 else 0
            
            # Tendencia Ichimoku
            if tenkan_actual > kijun_actual and precio_actual > senkou_a_actual:
                tendencia = 'ALCISTA'
            elif tenkan_actual < kijun_actual and precio_actual < senkou_a_actual:
                tendencia = 'BAJISTA'
            else:
                tendencia = 'NEUTRAL'
            
            return {
                'tenkan': tenkan_actual,
                'kijun': kijun_actual,
                'senkou_a': senkou_a_actual,
                'senkou_b': senkou_b_actual,
                'senkou_ancho': senkou_ancho,
                'tendencia': tendencia,
                'precio_actual': precio_actual,
                'precio_vs_tenkan': precio_actual - tenkan_actual,
                'precio_vs_kijun': precio_actual - kijun_actual,
            }
            
        except Exception as e:
            logger.debug(f"Error calculando Ichimoku: {e}")
            return {
                'tenkan': 0, 'kijun': 0, 'senkou_a': 0, 'senkou_b': 0,
                'senkou_ancho': 0, 'tendencia': 'NEUTRAL'
            }
    
    @staticmethod
    def calcular_chop_index(df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula Choppiness Index.
        
        Args:
            df: DataFrame con High, Low, Close
            periodo: Período (default 14)
        
        Returns:
            Chop Index (0-100)
        """
        if df is None or len(df) < periodo:
            return 50.0
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            
            atr = tr.rolling(periodo).sum()
            max_high = high.rolling(periodo).max()
            min_low = low.rolling(periodo).min()
            rango_total = max_high - min_low
            
            chop = 100 * np.log10(atr / rango_total) / np.log10(periodo) if rango_total > 0 else 50
            return float(chop) if not pd.isna(chop) else 50.0
            
        except Exception as e:
            logger.debug(f"Error calculando Chop Index: {e}")
            return 50.0
    
    @staticmethod
    def calcular_vix_proxy(df: pd.DataFrame) -> float:
        """
        Calcula proxy del VIX (volatilidad implícita).
        
        Args:
            df: DataFrame con Close
        
        Returns:
            VIX proxy (0-100)
        """
        if df is None or len(df) < 20:
            return 0.0
        
        try:
            close = df['Close']
            returns = close.pct_change().dropna()
            
            if len(returns) < 20:
                return 0.0
            
            vol = returns.std() * np.sqrt(252)
            vix_proxy = vol * 100
            
            return float(vix_proxy) if not pd.isna(vix_proxy) else 0.0
            
        except Exception as e:
            logger.debug(f"Error calculando VIX proxy: {e}")
            return 0.0
    
    @staticmethod
    def calcular_donchian(df: pd.DataFrame, periodo: int = 20) -> Dict[str, float]:
        """
        Calcula Donchian Channels.
        
        Args:
            df: DataFrame con High, Low, Close
            periodo: Período (default 20)
        
        Returns:
            Diccionario con canales de Donchian
        """
        if df is None or len(df) < periodo:
            return {'alto': 0, 'bajo': 0, 'medio': 0, 'ancho': 0, 'posicion': 0.5}
        
        try:
            high = df['High'].iloc[-periodo:].max()
            low = df['Low'].iloc[-periodo:].min()
            close = df['Close'].iloc[-1]
            medio = (high + low) / 2
            ancho = (high - low) / close if close > 0 else 0
            posicion = (close - low) / (high - low) if (high - low) > 0 else 0.5
            
            return {
                'alto': float(high),
                'bajo': float(low),
                'medio': float(medio),
                'ancho': float(ancho),
                'posicion': float(posicion),
            }
            
        except Exception as e:
            logger.debug(f"Error calculando Donchian: {e}")
            return {'alto': 0, 'bajo': 0, 'medio': 0, 'ancho': 0, 'posicion': 0.5}
    
    @staticmethod
    def calcular_elder_ray(df: pd.DataFrame, periodo: int = 13) -> Dict[str, Any]:
        """
        Calcula Elder Ray Index.
        
        Args:
            df: DataFrame con High, Low, Close
            periodo: Período (default 13)
        
        Returns:
            Diccionario con Bull Power, Bear Power, Fuerza
        """
        if df is None or len(df) < periodo:
            return {'bull_power': 0, 'bear_power': 0, 'fuerza': 'NEUTRAL'}
        
        try:
            close = df['Close']
            high = df['High']
            low = df['Low']
            
            ema = close.ewm(span=periodo, adjust=False).mean()
            ema_actual = ema.iloc[-1]
            
            bull_power = high.iloc[-1] - ema_actual
            bear_power = low.iloc[-1] - ema_actual
            
            if bull_power > 0 and bear_power > 0:
                fuerza = 'BULLISH'
            elif bull_power < 0 and bear_power < 0:
                fuerza = 'BEARISH'
            else:
                fuerza = 'NEUTRAL'
            
            return {
                'bull_power': float(bull_power),
                'bear_power': float(bear_power),
                'fuerza': fuerza,
                'bull_ratio': bull_power / (bull_power - bear_power) if (bull_power - bear_power) != 0 else 0.5,
            }
            
        except Exception as e:
            logger.debug(f"Error calculando Elder Ray: {e}")
            return {'bull_power': 0, 'bear_power': 0, 'fuerza': 'NEUTRAL'}
    
    @staticmethod
    def calcular_sar(df: pd.DataFrame, paso: float = 0.02, maximo: float = 0.2) -> float:
        """
        Calcula Parabolic SAR.
        
        Args:
            df: DataFrame con High, Low, Close
            paso: Factor de aceleración (default 0.02)
            maximo: Factor máximo (default 0.2)
        
        Returns:
            Valor SAR
        """
        if df is None or len(df) < 5:
            return 0.0
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            # SAR simplificado
            if close.iloc[-1] > close.iloc[-5]:
                # Tendencia alcista
                min_anterior = low.iloc[-5:].min()
                sar = min_anterior - (min_anterior * paso)
            else:
                # Tendencia bajista
                max_anterior = high.iloc[-5:].max()
                sar = max_anterior + (max_anterior * paso)
            
            return float(sar) if not pd.isna(sar) else 0.0
            
        except Exception as e:
            logger.debug(f"Error calculando SAR: {e}")
            return 0.0
    
    @staticmethod
    def calcular_todos_indicadores(df_h4: pd.DataFrame, df_h1: pd.DataFrame) -> Dict[str, Any]:
        """
        Calcula todos los indicadores necesarios para la clasificación.
        
        Args:
            df_h4: DataFrame H4
            df_h1: DataFrame H1
        
        Returns:
            Diccionario con todos los indicadores
        """
        if df_h1 is None or len(df_h1) < 50:
            logger.warning(f"⚠️ df_h1 vacío o insuficiente: {len(df_h1) if df_h1 is not None else 'None'}")
            return {}
        # Verificar columnas
        required = ['High', 'Low', 'Close']
        if not all(col in df_h1.columns for col in required):
            logger.warning(f"⚠️ df_h1 columnas: {df_h1.columns.tolist()}")
            return {}
            
        # Verificar que tengan las columnas necesarias
        for df in [df_h4, df_h1]:
            if df is not None and len(df) > 0:
                required = ['High', 'Low', 'Close']
                if not all(col in df.columns for col in required):
                    logger.warning(f"DataFrame sin columnas requeridas: {df.columns.tolist()}")
                    return {}
        
        try:
            # Indicadores H4 (si está disponible)
            adx_h4 = RegimenIndicadores.calcular_adx(df_h4) if df_h4 is not None and len(df_h4) >= 14 else 0.0
            
            # Indicadores H1
            adx_h1 = RegimenIndicadores.calcular_adx(df_h1) if len(df_h1) >= 14 else 0.0
            er_kaufman = RegimenIndicadores.calcular_er_kaufman(df_h1) if len(df_h1) >= 20 else 0.0
            bb_width = RegimenIndicadores.calcular_bb_width(df_h1) if len(df_h1) >= 20 else 50.0
            atr_pct = RegimenIndicadores.calcular_atr_pct(df_h1) if len(df_h1) >= 14 else 0.5
            estructura = RegimenIndicadores.calcular_estructura_swings(df_h1) if len(df_h1) >= 30 else 'DESCONOCIDO'
            ichimoku = RegimenIndicadores.calcular_ichimoku(df_h1) if len(df_h1) >= 52 else {}
            chop_index = RegimenIndicadores.calcular_chop_index(df_h1) if len(df_h1) >= 14 else 50.0
            vix_proxy = RegimenIndicadores.calcular_vix_proxy(df_h1) if len(df_h1) >= 20 else 0.0
            donchian = RegimenIndicadores.calcular_donchian(df_h1) if len(df_h1) >= 20 else {}
            elder_ray = RegimenIndicadores.calcular_elder_ray(df_h1) if len(df_h1) >= 13 else {}
            sar = RegimenIndicadores.calcular_sar(df_h1) if len(df_h1) >= 5 else 0.0
            
            return {
                'adx_h4': adx_h4,
                'adx_h1': adx_h1,
                'er_kaufman': er_kaufman,
                'bb_width': bb_width,
                'atr_pct': atr_pct,
                'estructura': estructura,
                'ichimoku': ichimoku,
                'chop_index': chop_index,
                'vix_proxy': vix_proxy,
                'donchian': donchian,
                'elder_ray': elder_ray,
                'sar': sar,
            }
            
        except Exception as e:
            logger.error(f"Error calculando indicadores: {e}")
            return {}