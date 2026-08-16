#!/usr/bin/env python3
"""
analysis/capas_medio.py (V9.0)
Capa 2: Análisis medio con detección de niveles.
"""

import time
import numpy as np
import logging
import pandas as pd
from typing import Dict, Any, Optional

from analysis.capas import AnalisisMedio
from analysis.niveles import NivelTracker

logger = logging.getLogger('BotTrading.CapasMedio')


class AnalisisMedioEngine:
    """
    Motor de análisis medio (Capa 2).
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self,
                 umbrales: Dict[str, float],
                 config: Optional[Any] = None,
                 nivel_tracker: Optional[NivelTracker] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el motor de análisis medio.
        
        Args:
            umbrales: Diccionario con umbrales
            config: Configuración
            nivel_tracker: Tracker de niveles
            modo_backtest: Modo backtest
            modo_depuracion: Modo depuración
        """
        self.umbrales = umbrales
        self.config = config
        self.nivel_tracker = nivel_tracker
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.CapasMedio')
    
    def ejecutar(self, df: pd.DataFrame, simbolo: str,
                 rapido: Optional[Any] = None,
                 niveles_historicos: Optional[Dict] = None,
                 score_h1: float = 0) -> AnalisisMedio:
        """
        Ejecuta el análisis medio.
        
        Args:
            df: DataFrame con datos
            simbolo: Símbolo
            rapido: Resultado del análisis rápido
            niveles_historicos: Niveles históricos
            score_h1: Score H1
        
        Returns:
            AnalisisMedio
        """
        start_time = time.time()
        
        try:
            if df is None or len(df) < 50:
                return AnalisisMedio(
                    valido=False, simbolo=simbolo,
                    rsi=50, macd_line=0, macd_signal=0, macd_histogram=0,
                    bb_upper=0, bb_lower=0, bb_middle=0, bb_width_pct=0,
                    adx=0, atr=0, sma20=0, sma50=0, sma200=None,
                    soporte_cercano=None, resistencia_cercana=None,
                    distancia_soporte_pct=0, distancia_resistencia_pct=0,
                    soporte_hits=0, resistencia_hits=0,
                    pasa_filtro=False, razon_rechazo="Datos insuficientes"
                )
            
            precio_actual = df['Close'].iloc[-1]
            
            # ============================================================
            # 1. INDICADORES TÉCNICOS
            # ============================================================
            
            rsi = self._calcular_rsi(df['Close'])
            macd = self._calcular_macd(df['Close'])
            bb = self._calcular_bollinger(df['Close'])
            adx = self._calcular_adx(df)
            atr = self._calcular_atr(df)
            
            sma20 = df['Close'].rolling(20).mean().iloc[-1]
            sma50 = df['Close'].rolling(50).mean().iloc[-1]
            sma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else None
            
            # ============================================================
            # 2. DETECCIÓN DE NIVELES
            # ============================================================
            
            soporte_cercano, resistencia_cercana, soporte_hits, resistencia_hits = \
                self._detectar_niveles(df, simbolo, precio_actual, niveles_historicos)
            
            distancia_soporte_pct = (precio_actual - soporte_cercano) / precio_actual * 100 if soporte_cercano else 100
            distancia_resistencia_pct = (resistencia_cercana - precio_actual) / precio_actual * 100 if resistencia_cercana else 100
            
            # ============================================================
            # 3. EVALUACIÓN
            # ============================================================
            
            adx_fuerte = adx >= self.umbrales.get('adx_fuerte', 20)
            en_nivel_clave = (soporte_cercano is not None and distancia_soporte_pct < self.umbrales.get('distancia_nivel_max', 3.0)) or \
                            (resistencia_cercana is not None and distancia_resistencia_pct < self.umbrales.get('distancia_nivel_max', 3.0))
            
            tendencia_alineada = False
            if rapido and rapido.valido:
                if rapido.tendencia_corta == 'ALCISTA' and rsi > 50:
                    tendencia_alineada = True
                elif rapido.tendencia_corta == 'BAJISTA' and rsi < 50:
                    tendencia_alineada = True
            
            # Pasa filtro?
            pasa_filtro = adx_fuerte or en_nivel_clave or tendencia_alineada or (rsi >= 65 or rsi <= 35)
            
            if not pasa_filtro:
                razon_rechazo = f"ADX bajo ({adx:.0f}), no en nivel clave"
            else:
                razon_rechazo = ""
            
            resultado = AnalisisMedio(
                valido=True,
                simbolo=simbolo,
                rsi=rsi,
                macd_line=macd['macd'],
                macd_signal=macd['signal'],
                macd_histogram=macd['histogram'],
                bb_upper=bb['upper'],
                bb_lower=bb['lower'],
                bb_middle=bb['middle'],
                bb_width_pct=bb['width'],
                adx=adx,
                atr=atr,
                sma20=sma20,
                sma50=sma50,
                sma200=sma200,
                soporte_cercano=soporte_cercano,
                resistencia_cercana=resistencia_cercana,
                distancia_soporte_pct=distancia_soporte_pct,
                distancia_resistencia_pct=distancia_resistencia_pct,
                soporte_hits=soporte_hits,
                resistencia_hits=resistencia_hits,
                adx_fuerte=adx_fuerte,
                en_nivel_clave=en_nivel_clave,
                tendencia_alineada=tendencia_alineada,
                pasa_filtro=pasa_filtro,
                razon_rechazo=razon_rechazo
            )
            
            if score_h1 > 0:
                resultado._datos_extra['score_h1'] = score_h1
            
            return resultado
            
        except Exception as e:
            self.logger.error(f"❌ Error en análisis medio {simbolo}: {e}")
            return AnalisisMedio(
                valido=False, simbolo=simbolo,
                rsi=50, macd_line=0, macd_signal=0, macd_histogram=0,
                bb_upper=0, bb_lower=0, bb_middle=0, bb_width_pct=0,
                adx=0, atr=0, sma20=0, sma50=0, sma200=None,
                soporte_cercano=None, resistencia_cercana=None,
                distancia_soporte_pct=0, distancia_resistencia_pct=0,
                soporte_hits=0, resistencia_hits=0,
                pasa_filtro=False, razon_rechazo=f"Error: {e}"
            )
    
    # ============================================================
    # MÉTODOS DE CÁLCULO
    # ============================================================
    
    def _calcular_rsi(self, precios: pd.Series, periodo: int = 14) -> float:
        """Calcula RSI."""
        if precios is None or len(precios) < periodo:
            return 50.0
        try:
            delta = precios.diff()
            ganancia = (delta.where(delta > 0, 0.0)).rolling(window=periodo).mean()
            perdida = (-delta.where(delta < 0, 0.0)).rolling(window=periodo).mean()
            rs = ganancia / perdida if perdida > 0 else 100
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
        except Exception:
            return 50.0
    
    def _calcular_macd(self, precios: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """Calcula MACD."""
        if precios is None or len(precios) < slow:
            return {'macd': 0, 'signal': 0, 'histogram': 0}
        try:
            ema_fast = precios.ewm(span=fast, adjust=False).mean()
            ema_slow = precios.ewm(span=slow, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            return {
                'macd': float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else 0,
                'signal': float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else 0,
                'histogram': float(macd_line.iloc[-1] - signal_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else 0
            }
        except Exception:
            return {'macd': 0, 'signal': 0, 'histogram': 0}
    
    def _calcular_bollinger(self, precios: pd.Series, periodo: int = 20, desviaciones: int = 2) -> Dict:
        """Calcula Bandas de Bollinger."""
        if precios is None or len(precios) < periodo:
            return {'upper': 0, 'middle': 0, 'lower': 0, 'width': 0}
        try:
            sma = precios.rolling(window=periodo).mean()
            std = precios.rolling(window=periodo).std()
            upper = sma + (std * desviaciones)
            lower = sma - (std * desviaciones)
            middle = sma
            width = (upper.iloc[-1] - lower.iloc[-1]) / middle.iloc[-1] * 100 if middle.iloc[-1] > 0 else 0
            return {
                'upper': float(upper.iloc[-1]) if not pd.isna(upper.iloc[-1]) else 0,
                'middle': float(middle.iloc[-1]) if not pd.isna(middle.iloc[-1]) else 0,
                'lower': float(lower.iloc[-1]) if not pd.isna(lower.iloc[-1]) else 0,
                'width': float(width) if not pd.isna(width) else 0
            }
        except Exception:
            return {'upper': 0, 'middle': 0, 'lower': 0, 'width': 0}
    
    def _calcular_adx(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """Calcula ADX."""
        if df is None or len(df) < periodo:
            return 0.0
        try:
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
            
            plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
            minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
            
            plus_di = 100.0 * plus_dm.rolling(window=periodo).mean() / atr
            minus_di = 100.0 * minus_dm.rolling(window=periodo).mean() / atr
            
            dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
            adx = dx.rolling(window=periodo).mean()
            
            return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0
        except Exception:
            return 0.0
    
    def _calcular_atr(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """Calcula ATR."""
        if df is None or len(df) < periodo:
            return 0.001
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            tr1 = high - low
            tr2 = (high - close.shift()).abs()
            tr3 = (low - close.shift()).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=periodo).mean()
            return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.001
        except Exception:
            return 0.001
    
    # ============================================================
    # DETECCIÓN DE NIVELES
    # ============================================================
    
    def _detectar_niveles(self, df: pd.DataFrame, simbolo: str,
                          precio_actual: float,
                          niveles_historicos: Optional[Dict]) -> tuple:
        """
        Detecta soporte y resistencia cercanos.
        
        Returns:
            (soporte, resistencia, soporte_hits, resistencia_hits)
        """
        soporte = None
        resistencia = None
        soporte_hits = 0
        resistencia_hits = 0
        
        distancia_minima_pct = 0.15
        if self.modo_backtest:
            distancia_minima_pct = 0.05
        
        # 1. Intentar usar NivelTracker
        if self.nivel_tracker is not None:
            try:
                niveles = self.nivel_tracker.obtener_niveles_validos(simbolo, timeframe='H1')
                
                # Buscar soporte más cercano
                for s in niveles.get('soportes', []):
                    precio_s = s.get('precio', 0)
                    if precio_s > 0 and precio_s < precio_actual:
                        dist = (precio_actual - precio_s) / precio_actual * 100
                        hits = s.get('hits', 1)
                        if dist > distancia_minima_pct and dist < 100:
                            if soporte is None or dist < (precio_actual - soporte) / precio_actual * 100:
                                soporte = precio_s
                                soporte_hits = hits
                
                # Buscar resistencia más cercana
                for r in niveles.get('resistencias', []):
                    precio_r = r.get('precio', 0)
                    if precio_r > 0 and precio_r > precio_actual:
                        dist = (precio_r - precio_actual) / precio_actual * 100
                        hits = r.get('hits', 1)
                        if dist > distancia_minima_pct and dist < 100:
                            if resistencia is None or dist < (resistencia - precio_actual) / precio_actual * 100:
                                resistencia = precio_r
                                resistencia_hits = hits
            except Exception as e:
                self.logger.debug(f"Error obteniendo niveles del tracker: {e}")
        
        # 2. Fallback: detectar niveles locales
        if soporte is None or resistencia is None:
            try:
                window = 10
                low = df['Low']
                high = df['High']
                
                # Buscar mínimos locales recientes (soportes)
                for i in range(len(df) - 20, len(df) - 5):
                    if low.iloc[i] == low.iloc[i-window:i+window].min():
                        precio_s = low.iloc[i]
                        if precio_s < precio_actual:
                            dist = (precio_actual - precio_s) / precio_actual * 100
                            if dist > distancia_minima_pct and dist < 5.0:
                                if soporte is None or dist < (precio_actual - soporte) / precio_actual * 100:
                                    soporte = precio_s
                                    soporte_hits = 1
                
                # Buscar máximos locales recientes (resistencias)
                for i in range(len(df) - 20, len(df) - 5):
                    if high.iloc[i] == high.iloc[i-window:i+window].max():
                        precio_r = high.iloc[i]
                        if precio_r > precio_actual:
                            dist = (precio_r - precio_actual) / precio_actual * 100
                            if dist > distancia_minima_pct and dist < 5.0:
                                if resistencia is None or dist < (resistencia - precio_actual) / precio_actual * 100:
                                    resistencia = precio_r
                                    resistencia_hits = 1
            except Exception as e:
                self.logger.debug(f"Error en detección local de niveles: {e}")
        
        # 3. Último recurso: usar mínimos/máximos de ventana
        if soporte is None:
            try:
                min_reciente = df['Low'].iloc[-50:].min()
                dist = (precio_actual - min_reciente) / precio_actual * 100
                if 0.1 < dist < 5.0:
                    soporte = min_reciente
                    soporte_hits = 1
            except Exception:
                pass
        
        if resistencia is None:
            try:
                max_reciente = df['High'].iloc[-50:].max()
                dist = (max_reciente - precio_actual) / precio_actual * 100
                if 0.1 < dist < 5.0:
                    resistencia = max_reciente
                    resistencia_hits = 1
            except Exception:
                pass
        
        # Log de niveles encontrados
        if self.modo_depuracion and (soporte is not None or resistencia is not None):
            soporte_str = f"{soporte:.5f}" if soporte is not None else "None"
            resistencia_str = f"{resistencia:.5f}" if resistencia is not None else "None"
            self.logger.debug(f"📊 {simbolo}: NIVELES - Soporte: {soporte_str} (hits:{soporte_hits}) | Resistencia: {resistencia_str} (hits:{resistencia_hits})")
        
        return soporte, resistencia, soporte_hits, resistencia_hits