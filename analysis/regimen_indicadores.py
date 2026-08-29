#!/usr/bin/env python3
"""
analysis/regimen_indicadores.py (V9.2 - CORREGIDO)
Cálculo de indicadores técnicos para clasificación de régimen.
RESPONSABILIDAD: Solo calcular indicadores, no clasificar.

CORRECCIONES V9.2:
- ADX: atr_seguro para evitar división por cero
- ADX: validación de di_suma != 0
- Chop Index: validación de rango_total > 0
- Elder Ray: validación de denominador != 0
- Ichimoku: validación de NaN
- Todos los indicadores: logs de depuración
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger('BotTrading.RegimenIndicadores')


class RegimenIndicadores:
    """
    Calcula indicadores técnicos para clasificación de régimen.
    V9.2 - CORREGIDO: ADX robusto, validaciones mejoradas.
    """
    
    @staticmethod
    def calcular_adx(df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula ADX (Average Directional Index).
        V9.2 - CORREGIDO: atr_seguro, validación de división por cero.
        
        Args:
            df: DataFrame con High, Low, Close
            periodo: Período (default 14)
        
        Returns:
            Valor ADX
        """
        if df is None or len(df) < periodo + 1:
            logger.warning(f"ADX: Datos insuficientes ({len(df) if df else 0} < {periodo+1})")
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
            
            # ✅ CORRECCIÓN V9.2: ATR seguro (evita división por cero)
            atr_seguro = atr.replace(0, np.nan)
            
            # Validar que ATR no sea todo NaN
            if atr_seguro.isna().all():
                logger.warning("ADX: ATR todo NaN")
                return 0.0
            
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
            
            # ✅ CORRECCIÓN V9.2: Usar ATR seguro
            atr_seguro = atr.replace(0, np.nan)
            plus_di = 100 * plus_dm.rolling(periodo).mean() / atr_seguro
            minus_di = 100 * minus_dm.rolling(periodo).mean() / atr_seguro
            
            # Validar que plus_di y minus_di no sean todo NaN
            if plus_di.isna().all() or minus_di.isna().all():
                logger.warning("ADX: plus_di o minus_di todo NaN")
                return 0.0
            
            di_suma = plus_di + minus_di
            
            # ✅ CORRECCIÓN V9.2: Validar división por cero
            if di_suma.isna().all() or (di_suma == 0).all():
                logger.warning("ADX: di_suma todo 0 o NaN")
                return 0.0
            
            # ✅ CORRECCIÓN V9.2: Reemplazar 0 por NaN para evitar división por cero
            di_suma_segura = di_suma.replace(0, np.nan)
            
            dx = 100 * (plus_di - minus_di).abs() / di_suma_segura
            adx = dx.rolling(periodo).mean().iloc[-1]
            
            # Validar que ADX no sea NaN
            if pd.isna(adx):
                logger.warning("ADX resultó NaN")
                return 0.0
            
            # Validar que ADX esté en rango
            if adx < 0 or adx > 100:
                logger.warning(f"ADX fuera de rango ({adx:.2f})")
                return 0.0
            
            logger.debug(f"ADX calculado: {adx:.2f}")
            return float(adx) if pd.notna(adx) else 0.0
            
        except Exception as e:
            logger.error(f"Error calculando ADX: {e}", exc_info=True)
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
            logger.warning(f"ER Kaufman: Datos insuficientes ({len(df) if df else 0} < {periodo})")
            return 0.0
        
        try:
            close = df['Close']
            cambio_neto = abs(close.iloc[-1] - close.iloc[-periodo])
            suma_mov = abs(close.diff()).iloc[-periodo:].sum()
            
            er = cambio_neto / suma_mov if suma_mov > 0 else 0.0
            if pd.isna(er):
                logger.warning("ER Kaufman resultó NaN")
                return 0.0
            
            logger.debug(f"ER Kaufman: {er:.4f}")
            return float(er) if not pd.isna(er) else 0.0
            
        except Exception as e:
            logger.error(f"Error calculando ER: {e}")
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
            logger.warning(f"BB Width: Datos insuficientes ({len(df) if df else 0} < {periodo})")
            return 50.0
        
        try:
            close = df['Close']
            sma = close.rolling(periodo).mean()
            std = close.rolling(periodo).std()
            
            if sma.isna().all() or std.isna().all():
                logger.warning("BB Width: SMA o STD todo NaN")
                return 50.0
            
            upper = sma + (std * 2)
            lower = sma - (std * 2)
            
            width = ((upper - lower) / sma * 100).iloc[-1]
            if pd.isna(width):
                logger.warning("BB Width resultó NaN")
                return 50.0
            
            logger.debug(f"BB Width: {width:.2f}%")
            return float(width) if not pd.isna(width) else 50.0
            
        except Exception as e:
            logger.error(f"Error calculando BB width: {e}")
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
            logger.warning(f"ATR pct: Datos insuficientes ({len(df) if df else 0} < {periodo})")
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
            
            if pd.isna(atr) or precio <= 0:
                logger.warning("ATR pct: ATR NaN o precio <= 0")
                return 0.5
            
            atr_pct = (atr / precio * 100)
            if pd.isna(atr_pct):
                logger.warning("ATR pct resultó NaN")
                return 0.5
            
            logger.debug(f"ATR pct: {atr_pct:.2f}%")
            return float(atr_pct) if not pd.isna(atr_pct) else 0.5
            
        except Exception as e:
            logger.error(f"Error calculando ATR pct: {e}")
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
            logger.warning(f"Estructura: Datos insuficientes ({len(df) if df else 0} < 30)")
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
                logger.debug("Estructura: Insuficientes pivotes")
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
            logger.error(f"Error calculando estructura: {e}")
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
            logger.warning(f"Ichimoku: Datos insuficientes ({len(df) if df else 0} < 52)")
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
            
            # ✅ CORRECCIÓN V9.2: Validar que senkou_a y senkou_b no sean NaN
            tenkan_actual = tenkan.iloc[-1] if not pd.isna(tenkan.iloc[-1]) else 0
            kijun_actual = kijun.iloc[-1] if not pd.isna(kijun.iloc[-1]) else 0
            senkou_a_actual = senkou_a.iloc[-1] if not pd.isna(senkou_a.iloc[-1]) else 0
            senkou_b_actual = senkou_b.iloc[-1] if not pd.isna(senkou_b.iloc[-1]) else 0
            precio_actual = close.iloc[-1]
            
            # Ancho de la nube
            if precio_actual > 0:
                senkou_ancho = abs(senkou_a_actual - senkou_b_actual) / precio_actual
            else:
                senkou_ancho = 0
            
            if pd.isna(senkou_ancho):
                logger.warning("Ichimoku: senkou_ancho resultó NaN")
                senkou_ancho = 0
            
            # Tendencia Ichimoku
            if tenkan_actual > kijun_actual and precio_actual > senkou_a_actual:
                tendencia = 'ALCISTA'
            elif tenkan_actual < kijun_actual and precio_actual < senkou_a_actual:
                tendencia = 'BAJISTA'
            else:
                tendencia = 'NEUTRAL'
            
            logger.debug(f"Ichimoku: Tendencia = {tendencia}, Senkou ancho = {senkou_ancho:.4f}")
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
            logger.error(f"Error calculando Ichimoku: {e}")
            return {
                'tenkan': 0, 'kijun': 0, 'senkou_a': 0, 'senkou_b': 0,
                'senkou_ancho': 0, 'tendencia': 'NEUTRAL'
            }
    
    @staticmethod
    def calcular_chop_index(df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula Choppiness Index.
        V9.3 - CORREGIDO: Validación de Series.
        """
        if df is None or len(df) < periodo:
            return 50.0
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            # True Range
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            
            # ATR sum
            atr = tr.rolling(periodo).sum()
            
            # Rango total (último valor)
            max_high = high.rolling(periodo).max()
            min_low = low.rolling(periodo).min()
            rango_total = max_high - min_low
            
            # ✅ CORREGIDO: Obtener último valor
            rango_final = rango_total.iloc[-1] if not rango_total.isna().iloc[-1] else 0
            atr_final = atr.iloc[-1] if not atr.isna().iloc[-1] else 0
            
            if rango_final <= 0:
                return 50.0
            
            chop = 100 * np.log10(atr_final / rango_final) / np.log10(periodo)
            
            if pd.isna(chop):
                return 50.0
            
            return float(chop)
            
        except Exception as e:
            logger.error(f"Error calculando Chop Index: {e}")
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
            logger.warning(f"VIX proxy: Datos insuficientes ({len(df) if df else 0} < 20)")
            return 0.0
        
        try:
            close = df['Close']
            returns = close.pct_change().dropna()
            
            if len(returns) < 20:
                return 0.0
            
            vol = returns.std() * np.sqrt(252)
            vix_proxy = vol * 100
            
            if pd.isna(vix_proxy):
                logger.warning("VIX proxy resultó NaN")
                return 0.0
            
            logger.debug(f"VIX proxy: {vix_proxy:.2f}")
            return float(vix_proxy) if not pd.isna(vix_proxy) else 0.0
            
        except Exception as e:
            logger.error(f"Error calculando VIX proxy: {e}")
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
            logger.warning(f"Donchian: Datos insuficientes ({len(df) if df else 0} < {periodo})")
            return {'alto': 0, 'bajo': 0, 'medio': 0, 'ancho': 0, 'posicion': 0.5}
        
        try:
            high = df['High'].iloc[-periodo:].max()
            low = df['Low'].iloc[-periodo:].min()
            close = df['Close'].iloc[-1]
            medio = (high + low) / 2
            ancho = (high - low) / close if close > 0 else 0
            posicion = (close - low) / (high - low) if (high - low) > 0 else 0.5
            
            if pd.isna(ancho) or pd.isna(posicion):
                logger.warning("Donchian: NaN en ancho o posición")
                return {'alto': 0, 'bajo': 0, 'medio': 0, 'ancho': 0, 'posicion': 0.5}
            
            logger.debug(f"Donchian: Posición = {posicion:.2f}, Ancho = {ancho:.4f}")
            return {
                'alto': float(high),
                'bajo': float(low),
                'medio': float(medio),
                'ancho': float(ancho),
                'posicion': float(posicion),
            }
            
        except Exception as e:
            logger.error(f"Error calculando Donchian: {e}")
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
            logger.warning(f"Elder Ray: Datos insuficientes ({len(df) if df else 0} < {periodo})")
            return {'bull_power': 0, 'bear_power': 0, 'fuerza': 'NEUTRAL'}
        
        try:
            close = df['Close']
            high = df['High']
            low = df['Low']
            
            ema = close.ewm(span=periodo, adjust=False).mean()
            ema_actual = ema.iloc[-1]
            
            bull_power = high.iloc[-1] - ema_actual
            bear_power = low.iloc[-1] - ema_actual
            
            if pd.isna(bull_power) or pd.isna(bear_power):
                logger.warning("Elder Ray: NaN en bull_power o bear_power")
                return {'bull_power': 0, 'bear_power': 0, 'fuerza': 'NEUTRAL'}
            
            if bull_power > 0 and bear_power > 0:
                fuerza = 'BULLISH'
            elif bull_power < 0 and bear_power < 0:
                fuerza = 'BEARISH'
            else:
                fuerza = 'NEUTRAL'
            
            # ✅ CORRECCIÓN V9.2: Validar denominador != 0
            bull_ratio = 0.5
            if (bull_power - bear_power) != 0:
                bull_ratio = bull_power / (bull_power - bear_power)
            
            if pd.isna(bull_ratio):
                logger.warning("Elder Ray: bull_ratio resultó NaN")
                bull_ratio = 0.5
            
            logger.debug(f"Elder Ray: Fuerza = {fuerza}, Bull ratio = {bull_ratio:.2f}")
            return {
                'bull_power': float(bull_power),
                'bear_power': float(bear_power),
                'fuerza': fuerza,
                'bull_ratio': float(bull_ratio),
            }
            
        except Exception as e:
            logger.error(f"Error calculando Elder Ray: {e}")
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
            logger.warning(f"SAR: Datos insuficientes ({len(df) if df else 0} < 5)")
            return 0.0
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            if close.iloc[-1] > close.iloc[-5]:
                min_anterior = low.iloc[-5:].min()
                sar = min_anterior - (min_anterior * paso)
            else:
                max_anterior = high.iloc[-5:].max()
                sar = max_anterior + (max_anterior * paso)
            
            if pd.isna(sar):
                logger.warning("SAR resultó NaN")
                return 0.0
            
            logger.debug(f"SAR: {sar:.5f}")
            return float(sar) if not pd.isna(sar) else 0.0
            
        except Exception as e:
            logger.error(f"Error calculando SAR: {e}")
            return 0.0

    @staticmethod
    def calcular_todos_indicadores_con_fallback(df_h4: pd.DataFrame, df_h1: pd.DataFrame) -> Dict[str, Any]:
        """
        Calcula indicadores con fallback por EMAs si no hay suficientes datos.
        V9.2 - CORREGIDO: Usa indicadores corregidos.
        """
        # Intentar cálculo normal
        resultado = RegimenIndicadores.calcular_todos_indicadores(df_h4, df_h1)
        
        # Si el resultado está vacío o no tiene indicadores clave, usar fallback
        if not resultado or resultado.get('adx_h1', 0) == 0:
            logger.debug("⚠️ Usando fallback por EMAs para clasificación")
            
            if df_h1 is not None and len(df_h1) >= 50:
                close = df_h1['Close']
                ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
                ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
                
                if ema20 > ema50 * 1.01:
                    estructura = 'ALCISTA'
                    adx_estimado = 25
                elif ema20 < ema50 * 0.99:
                    estructura = 'BAJISTA'
                    adx_estimado = 25
                else:
                    estructura = 'RANGO'
                    adx_estimado = 15
                
                resultado = {
                    'adx_h4': adx_estimado,
                    'adx_h1': adx_estimado,
                    'er_kaufman': 0.3,
                    'bb_width': 1.5,
                    'atr_pct': 0.5,
                    'estructura': estructura,
                    'ichimoku': {'tendencia': 'ALCISTA' if estructura == 'ALCISTA' else 'BAJISTA' if estructura == 'BAJISTA' else 'NEUTRAL'},
                    'chop_index': 45 if estructura != 'RANGO' else 65,
                    'vix_proxy': 15,
                    'donchian': {'posicion': 0.6 if estructura == 'ALCISTA' else 0.4 if estructura == 'BAJISTA' else 0.5},
                    'elder_ray': {'fuerza': 'BULLISH' if estructura == 'ALCISTA' else 'BEARISH' if estructura == 'BAJISTA' else 'NEUTRAL'},
                    'sar': 0,
                }
        
        return resultado
    
    @staticmethod
    def calcular_todos_indicadores(df_h4: pd.DataFrame, df_h1: pd.DataFrame) -> Dict[str, Any]:
        """
        Calcula todos los indicadores necesarios para la clasificación.
        V9.2 - CORREGIDO: Usa métodos corregidos.
        
        Args:
            df_h4: DataFrame H4
            df_h1: DataFrame H1
        
        Returns:
            Diccionario con todos los indicadores
        """
        if df_h1 is None or len(df_h1) < 50:
            logger.warning(f"df_h1 vacío o insuficiente: {len(df_h1) if df_h1 is not None else 'None'}")
            return {}
        
        # Verificar columnas
        required = ['High', 'Low', 'Close']
        if not all(col in df_h1.columns for col in required):
            logger.warning(f"df_h1 columnas: {df_h1.columns.tolist()}")
            return {}
        
        try:
            # Indicadores H4 (si está disponible)
            adx_h4 = RegimenIndicadores.calcular_adx(df_h4) if df_h4 is not None and len(df_h4) >= 14 else 0.0
            
            # Indicadores H1 (usando métodos corregidos)
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