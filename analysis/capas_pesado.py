#!/usr/bin/env python3
"""
analysis/capas_pesado.py (V9.2 - CORREGIDO)
Capa 3: Análisis pesado - Patrones, Order Blocks, Wyckoff, Divergencias.

CORRECCIONES V9.2:
- RSI: validación robusta con logs (unificado con capas_rapido)
- MACD: validación de NaN
- Divergencias: validación de que RSI y MACD no sean NaN
- Logs de depuración para divergencias
"""

import time
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple

from analysis.capas import AnalisisPesado

logger = logging.getLogger('BotTrading.CapasPesado')


class AnalisisPesadoEngine:
    """
    Motor de análisis pesado (Capa 3).
    V9.2 - CORREGIDO: RSI y MACD robustos.
    """
    
    def __init__(self,
                 analisis_tecnico: Any,
                 umbrales: Dict[str, float],
                 config: Optional[Any] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el motor de análisis pesado.
        """
        self.analisis_tecnico = analisis_tecnico
        self.umbrales = umbrales
        self.config = config
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.CapasPesado')
    
    def ejecutar(self, df: pd.DataFrame, simbolo: str,
                 df_h4: Optional[pd.DataFrame] = None,
                 df_d1: Optional[pd.DataFrame] = None,
                 niveles_historicos: Optional[Dict] = None,
                 medio: Optional[Any] = None) -> AnalisisPesado:
        """Ejecuta el análisis pesado."""
        start_time = time.time()
        
        try:
            if df is None or len(df) < 100:
                return AnalisisPesado(
                    valido=False, simbolo=simbolo,
                    patrones_encontrados=[], patron_principal='N/A',
                    calidad_patron=0,
                    bull_ob=None, bear_ob=None, ob_cercano=False,
                    wyckoff_fase='NEUTRAL', wyckoff_confianza=0,
                    divergencia_rsi=None, divergencia_macd=None,
                    score_estructura=0, score_momentum=0,
                    score_confluencia=0, score_institucional=0
                )
            
            # 1. DETECCIÓN DE PATRONES
            patrones_encontrados, patron_principal, calidad_patron = \
                self._detectar_patrones_mejorado(df)
            
            # 2. ORDER BLOCKS
            bull_ob, bear_ob, ob_cercano = self._detectar_order_blocks_corregido(df, df_h4)
            
            # 3. WYCKOFF
            wyckoff_fase, wyckoff_confianza = self._detectar_wyckoff_mejorado(df)
            
            # 4. DIVERGENCIAS (CORREGIDO V9.2)
            divergencia_rsi, divergencia_macd = self._detectar_divergencias_corregido(df, simbolo)
            
            # 5. SCORES
            score_estructura = self._calcular_score_estructura_mejorado(
                patrones_encontrados, ob_cercano, wyckoff_confianza, medio
            )
            
            score_momentum = self._calcular_score_momentum_mejorado(medio)
            
            score_confluencia = self._calcular_score_confluencia_mejorado(
                medio, divergencia_rsi, patrones_encontrados, ob_cercano
            )
            
            score_institucional = self._calcular_score_institucional_mejorado(
                wyckoff_fase, ob_cercano, bull_ob, bear_ob
            )
            
            resultado = AnalisisPesado(
                valido=True,
                simbolo=simbolo,
                patrones_encontrados=patrones_encontrados,
                patron_principal=patron_principal,
                calidad_patron=calidad_patron,
                bull_ob=bull_ob,
                bear_ob=bear_ob,
                ob_cercano=ob_cercano,
                wyckoff_fase=wyckoff_fase,
                wyckoff_confianza=wyckoff_confianza,
                divergencia_rsi=divergencia_rsi,
                divergencia_macd=divergencia_macd,
                score_estructura=score_estructura,
                score_momentum=score_momentum,
                score_confluencia=score_confluencia,
                score_institucional=score_institucional
            )
            
            if self.modo_depuracion and patrones_encontrados:
                self.logger.debug(f"📊 {simbolo}: Patrones: {patrones_encontrados}")
            
            return resultado
            
        except Exception as e:
            self.logger.error(f"❌ Error en análisis pesado {simbolo}: {e}", exc_info=True)
            return AnalisisPesado(
                valido=False, simbolo=simbolo,
                patrones_encontrados=[], patron_principal='N/A',
                calidad_patron=0,
                bull_ob=None, bear_ob=None, ob_cercano=False,
                wyckoff_fase='NEUTRAL', wyckoff_confianza=0,
                divergencia_rsi=None, divergencia_macd=None,
                score_estructura=0, score_momentum=0,
                score_confluencia=0, score_institucional=0
            )
    
    # ============================================================
    # 4. DIVERGENCIAS CORREGIDO (V9.2)
    # ============================================================
    
    def _detectar_divergencias_corregido(self, df: pd.DataFrame, simbolo: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Detecta divergencias RSI y MACD de forma robusta.
        V9.2 - CORREGIDO: Validación de RSI y MACD antes de detectar divergencias.
        """
        divergencia_rsi = None
        divergencia_macd = None

        try:
            if df is None or len(df) < 20:
                self.logger.debug(f"⚠️ {simbolo}: Datos insuficientes para divergencias ({len(df) if df else 0} < 20)")
                return None, None

            close = df['Close']
            high = df['High']
            low = df['Low']

            # 1. RSI (con validación robusta)
            rsi = self._calcular_rsi_serie_corregido(close, simbolo)
            if rsi is None or rsi.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: RSI todo NaN, no se pueden detectar divergencias")
                return None, None

            # 2. MACD (con validación robusta)
            macd_result = self._calcular_macd_corregido(close, simbolo)
            macd_line = macd_result.get('macd')
            signal_line = macd_result.get('signal')
            macd_hist = macd_result.get('histogram')
            
            if macd_line is None or macd_line.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: MACD todo NaN, no se pueden detectar divergencias")
                return None, None

            # 3. Detectar divergencias RSI (menos estricto)
            if len(rsi) >= 15:
                # Encontrar máximos locales (ventana de 3 velas)
                for i in range(5, len(close) - 5):
                    # Verificar si es un máximo local en precio
                    if close.iloc[i] == close.iloc[i-3:i+4].max():
                        # Verificar si es un máximo local en RSI
                        if rsi.iloc[i] == rsi.iloc[i-3:i+4].max():
                            # Buscar otro máximo anterior
                            for j in range(i - 10, i - 3):
                                if j < 5:
                                    continue
                                if close.iloc[j] == close.iloc[j-3:j+4].max():
                                    if rsi.iloc[j] == rsi.iloc[j-3:j+4].max():
                                        # Divergencia bajista: precio más alto, RSI más bajo
                                        if close.iloc[i] > close.iloc[j] and rsi.iloc[i] < rsi.iloc[j]:
                                            divergencia_rsi = 'BEARISH'
                                            self.logger.debug(f"📊 {simbolo}: Divergencia RSI BEARISH detectada")
                                            break
                            if divergencia_rsi:
                                break

                # Encontrar mínimos locales (ventana de 3 velas)
                if not divergencia_rsi:
                    for i in range(5, len(close) - 5):
                        if close.iloc[i] == close.iloc[i-3:i+4].min():
                            if rsi.iloc[i] == rsi.iloc[i-3:i+4].min():
                                for j in range(i - 10, i - 3):
                                    if j < 5:
                                        continue
                                    if close.iloc[j] == close.iloc[j-3:j+4].min():
                                        if rsi.iloc[j] == rsi.iloc[j-3:j+4].min():
                                            # Divergencia alcista: precio más bajo, RSI más alto
                                            if close.iloc[i] < close.iloc[j] and rsi.iloc[i] > rsi.iloc[j]:
                                                divergencia_rsi = 'BULLISH'
                                                self.logger.debug(f"📊 {simbolo}: Divergencia RSI BULLISH detectada")
                                                break
                                if divergencia_rsi:
                                    break

            # 4. Detectar divergencias MACD (menos estricto)
            if macd_hist is not None and len(macd_hist) >= 15:
                # Máximos locales
                for i in range(5, len(close) - 5):
                    if close.iloc[i] == close.iloc[i-3:i+4].max():
                        if macd_hist.iloc[i] == macd_hist.iloc[i-3:i+4].max():
                            for j in range(i - 10, i - 3):
                                if j < 5:
                                    continue
                                if close.iloc[j] == close.iloc[j-3:j+4].max():
                                    if macd_hist.iloc[j] == macd_hist.iloc[j-3:j+4].max():
                                        if close.iloc[i] > close.iloc[j] and macd_hist.iloc[i] < macd_hist.iloc[j]:
                                            divergencia_macd = 'BEARISH'
                                            self.logger.debug(f"📊 {simbolo}: Divergencia MACD BEARISH detectada")
                                            break
                            if divergencia_macd:
                                break

                # Mínimos locales
                if not divergencia_macd:
                    for i in range(5, len(close) - 5):
                        if close.iloc[i] == close.iloc[i-3:i+4].min():
                            if macd_hist.iloc[i] == macd_hist.iloc[i-3:i+4].min():
                                for j in range(i - 10, i - 3):
                                    if j < 5:
                                        continue
                                    if close.iloc[j] == close.iloc[j-3:j+4].min():
                                        if macd_hist.iloc[j] == macd_hist.iloc[j-3:j+4].min():
                                            if close.iloc[i] < close.iloc[j] and macd_hist.iloc[i] > macd_hist.iloc[j]:
                                                divergencia_macd = 'BULLISH'
                                                self.logger.debug(f"📊 {simbolo}: Divergencia MACD BULLISH detectada")
                                                break
                                if divergencia_macd:
                                    break

            return divergencia_rsi, divergencia_macd

        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error detectando divergencias: {e}", exc_info=True)
            return None, None
    
    # ============================================================
    # CÁLCULO DE RSI SERIE CORREGIDO (V9.2)
    # ============================================================
    
    def _calcular_rsi_serie_corregido(self, precios: pd.Series, simbolo: str, periodo: int = 14) -> Optional[pd.Series]:
        """
        Calcula RSI como serie con validación robusta.
        V9.2 - CORREGIDO: Validación de NaN, logs.
        """
        if precios is None or len(precios) < periodo:
            self.logger.warning(f"⚠️ {simbolo}: Insuficientes datos para RSI serie ({len(precios)} < {periodo})")
            return None
        
        try:
            delta = precios.diff()
            
            if delta.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: Delta todo NaN en RSI serie")
                return None
            
            ganancia = (delta.where(delta > 0, 0.0)).rolling(window=periodo).mean()
            perdida = (-delta.where(delta < 0, 0.0)).rolling(window=periodo).mean()
            
            if ganancia.isna().all() or perdida.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: Ganancia o pérdida todo NaN en RSI serie")
                return None
            
            rs = ganancia / perdida
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
            if rsi.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: RSI serie resultó todo NaN")
                return None
            
            return rsi.fillna(50.0)
            
        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error en RSI serie: {e}", exc_info=True)
            return None
    
    # ============================================================
    # CÁLCULO DE MACD CORREGIDO (V9.2)
    # ============================================================
    
    def _calcular_macd_corregido(self, precios: pd.Series, simbolo: str, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """
        Calcula MACD como diccionario con validación robusta.
        V9.2 - CORREGIDO: Validación de NaN.
        """
        if precios is None or len(precios) < slow:
            self.logger.warning(f"⚠️ {simbolo}: Insuficientes datos para MACD ({len(precios)} < {slow})")
            return {'macd': None, 'signal': None, 'histogram': None}
        
        try:
            ema_fast = precios.ewm(span=fast, adjust=False).mean()
            ema_slow = precios.ewm(span=slow, adjust=False).mean()
            
            if ema_fast.isna().all() or ema_slow.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: EMAs todo NaN en MACD")
                return {'macd': None, 'signal': None, 'histogram': None}
            
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            histogram = macd_line - signal_line
            
            if macd_line.isna().all() or signal_line.isna().all() or histogram.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: Componentes de MACD todo NaN")
                return {'macd': None, 'signal': None, 'histogram': None}
            
            return {
                'macd': macd_line,
                'signal': signal_line,
                'histogram': histogram
            }
            
        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error en MACD: {e}", exc_info=True)
            return {'macd': None, 'signal': None, 'histogram': None}
    
    # ============================================================
    # OTROS MÉTODOS (SIN CAMBIOS)
    # ============================================================
    
    def _detectar_patrones_mejorado(self, df: pd.DataFrame) -> Tuple[List[str], str, float]:
        """Detecta patrones chartistas de forma robusta."""
        # (código existente, sin cambios)
        patrones = []
        
        if df is None or len(df) < 5:
            return [], 'N/A', 0
        
        try:
            if len(df) < 3:
                return [], 'N/A', 0
            
            vela_actual = df.iloc[-1]
            vela_anterior = df.iloc[-2] if len(df) > 1 else vela_actual
            vela_anterior2 = df.iloc[-3] if len(df) > 2 else vela_actual
            
            rango = vela_actual['High'] - vela_actual['Low']
            cuerpo = abs(vela_actual['Close'] - vela_actual['Open'])
            
            if rango <= 0:
                return [], 'N/A', 0
            
            sombra_sup = vela_actual['High'] - max(vela_actual['Open'], vela_actual['Close'])
            sombra_inf = min(vela_actual['Open'], vela_actual['Close']) - vela_actual['Low']
            
            # PIN BAR
            if sombra_inf / rango > 0.6 and cuerpo / rango < 0.3:
                calidad = 70 + min(30, (sombra_inf / rango) * 100)
                patrones.append({
                    'nombre': 'PIN_BAR_ALCISTA',
                    'calidad': min(100, calidad),
                    'direccion': 'COMPRA',
                    'precio': vela_actual['Close']
                })
            
            if sombra_sup / rango > 0.6 and cuerpo / rango < 0.3:
                calidad = 70 + min(30, (sombra_sup / rango) * 100)
                patrones.append({
                    'nombre': 'PIN_BAR_BAJISTA',
                    'calidad': min(100, calidad),
                    'direccion': 'VENTA',
                    'precio': vela_actual['Close']
                })
            
            # ENGULFING
            if (vela_actual['Close'] > vela_anterior['Open'] and 
                vela_actual['Open'] < vela_anterior['Close'] and
                vela_anterior['Close'] < vela_anterior['Open']):
                
                rango_anterior = vela_anterior['High'] - vela_anterior['Low']
                if rango_anterior > 0:
                    ratio = rango / rango_anterior
                    calidad = 70 + min(30, ratio * 20)
                else:
                    calidad = 75
                
                patrones.append({
                    'nombre': 'ENGULFING_ALCISTA',
                    'calidad': min(100, calidad),
                    'direccion': 'COMPRA',
                    'precio': vela_actual['Close']
                })
            
            if (vela_actual['Close'] < vela_anterior['Open'] and 
                vela_actual['Open'] > vela_anterior['Close'] and
                vela_anterior['Close'] > vela_anterior['Open']):
                
                rango_anterior = vela_anterior['High'] - vela_anterior['Low']
                if rango_anterior > 0:
                    ratio = rango / rango_anterior
                    calidad = 70 + min(30, ratio * 20)
                else:
                    calidad = 75
                
                patrones.append({
                    'nombre': 'ENGULFING_BAJISTA',
                    'calidad': min(100, calidad),
                    'direccion': 'VENTA',
                    'precio': vela_actual['Close']
                })
            
            # DOJI
            if cuerpo / rango < 0.1 and rango > 0:
                patrones.append({
                    'nombre': 'DOJI',
                    'calidad': 60,
                    'direccion': 'NEUTRAL',
                    'precio': vela_actual['Close']
                })
            
            # HAMMER
            if (sombra_inf / rango > 0.6 and 
                cuerpo / rango < 0.3 and 
                cuerpo > 0 and
                vela_actual['Close'] > vela_anterior['Close']):
                
                patrones.append({
                    'nombre': 'HAMMER',
                    'calidad': 65,
                    'direccion': 'COMPRA',
                    'precio': vela_actual['Close']
                })
            
            # SHOOTING STAR
            if (sombra_sup / rango > 0.6 and 
                cuerpo / rango < 0.3 and 
                cuerpo > 0 and
                vela_actual['Close'] < vela_anterior['Close']):
                
                patrones.append({
                    'nombre': 'SHOOTING_STAR',
                    'calidad': 65,
                    'direccion': 'VENTA',
                    'precio': vela_actual['Close']
                })
            
            # MORNING STAR / EVENING STAR
            if len(df) >= 3:
                if (vela_anterior2['Close'] < vela_anterior2['Open'] and 
                    abs(vela_anterior['Close'] - vela_anterior['Open']) / (vela_anterior['High'] - vela_anterior['Low'] + 0.001) < 0.2 and 
                    vela_actual['Close'] > vela_actual['Open']):
                    
                    patrones.append({
                        'nombre': 'MORNING_STAR',
                        'calidad': 80,
                        'direccion': 'COMPRA',
                        'precio': vela_actual['Close']
                    })
                
                if (vela_anterior2['Close'] > vela_anterior2['Open'] and 
                    abs(vela_anterior['Close'] - vela_anterior['Open']) / (vela_anterior['High'] - vela_anterior['Low'] + 0.001) < 0.2 and 
                    vela_actual['Close'] < vela_actual['Open']):
                    
                    patrones.append({
                        'nombre': 'EVENING_STAR',
                        'calidad': 80,
                        'direccion': 'VENTA',
                        'precio': vela_actual['Close']
                    })
            
        except Exception as e:
            self.logger.debug(f"Error detectando patrones: {e}")
        
        patron_principal = 'N/A'
        calidad_patron = 0
        
        for p in patrones:
            nombre = p.get('nombre', '')
            calidad = p.get('calidad', 0)
            if calidad > calidad_patron:
                calidad_patron = calidad
                patron_principal = nombre
        
        nombres = [p.get('nombre', '') for p in patrones if p.get('nombre')]
        
        return nombres, patron_principal, calidad_patron
    
    def _detectar_order_blocks_corregido(self, df: pd.DataFrame, 
                                         df_h4: Optional[pd.DataFrame]) -> Tuple[Optional[Dict], Optional[Dict], bool]:
        """Detecta Order Blocks de forma robusta."""
        # (código existente, sin cambios)
        bull_ob = None
        bear_ob = None
        ob_cercano = False
        
        try:
            df_usar = df_h4 if df_h4 is not None and len(df_h4) >= 50 else df
            
            if df_usar is None or len(df_usar) < 20:
                return None, None, False
            
            high = df_usar['High']
            low = df_usar['Low']
            close = df_usar['Close']
            precio_actual = close.iloc[-1]
            
            # BULLISH ORDER BLOCK
            for i in range(len(df_usar) - 30, len(df_usar) - 5):
                vela = df_usar.iloc[i]
                vela_siguiente = df_usar.iloc[i + 1] if i + 1 < len(df_usar) else vela
                
                rango = vela['High'] - vela['Low']
                cuerpo = abs(vela['Close'] - vela['Open'])
                
                if rango > 0 and cuerpo / rango > 0.5 and vela['Close'] < vela['Open']:
                    if vela_siguiente['Close'] > vela_siguiente['Open']:
                        bull_ob = {
                            'top': float(vela['High']),
                            'bottom': float(min(vela['Open'], vela['Close'])),
                            'tipo': 'BULLISH',
                            'fecha': vela.name,
                            'fuerza': min(100, (cuerpo / rango) * 100)
                        }
                        break
            
            # BEARISH ORDER BLOCK
            for i in range(len(df_usar) - 30, len(df_usar) - 5):
                vela = df_usar.iloc[i]
                vela_siguiente = df_usar.iloc[i + 1] if i + 1 < len(df_usar) else vela
                
                rango = vela['High'] - vela['Low']
                cuerpo = abs(vela['Close'] - vela['Open'])
                
                if rango > 0 and cuerpo / rango > 0.5 and vela['Close'] > vela['Open']:
                    if vela_siguiente['Close'] < vela_siguiente['Open']:
                        bear_ob = {
                            'top': float(max(vela['Open'], vela['Close'])),
                            'bottom': float(vela['Low']),
                            'tipo': 'BEARISH',
                            'fecha': vela.name,
                            'fuerza': min(100, (cuerpo / rango) * 100)
                        }
                        break
            
            # VERIFICAR OB CERCANO
            if bull_ob is not None:
                dist = abs(bull_ob['top'] - precio_actual) / precio_actual * 100
                if dist < 1.0:
                    ob_cercano = True
                    bull_ob['distancia_pct'] = dist
            
            if bear_ob is not None and not ob_cercano:
                dist = abs(bear_ob['bottom'] - precio_actual) / precio_actual * 100
                if dist < 1.0:
                    ob_cercano = True
                    bear_ob['distancia_pct'] = dist
            
            # FALLBACK
            if bull_ob is None and bear_ob is None:
                min_reciente = low.iloc[-20:].min()
                max_reciente = high.iloc[-20:].max()
                
                if min_reciente > precio_actual * 0.99:
                    bull_ob = {
                        'top': float(min_reciente * 1.002),
                        'bottom': float(min_reciente * 0.998),
                        'tipo': 'BULLISH',
                        'fuerza': 50
                    }
                
                if max_reciente < precio_actual * 1.01:
                    bear_ob = {
                        'top': float(max_reciente * 1.002),
                        'bottom': float(max_reciente * 0.998),
                        'tipo': 'BEARISH',
                        'fuerza': 50
                    }
            
            return bull_ob, bear_ob, ob_cercano
            
        except Exception as e:
            self.logger.debug(f"Error detectando Order Blocks: {e}")
            return None, None, False
    
    def _detectar_wyckoff_mejorado(self, df: pd.DataFrame) -> Tuple[str, float]:
        """Detecta fases de Wyckoff de forma robusta."""
        # (código existente, sin cambios)
        try:
            if df is None or len(df) < 50:
                return 'NEUTRAL', 0
            
            close = df['Close']
            high = df['High']
            low = df['Low']
            
            sma20 = close.rolling(20).mean()
            sma50 = close.rolling(50).mean()
            sma200 = close.rolling(200).mean() if len(close) >= 200 else None
            
            sma20_actual = sma20.iloc[-1] if not pd.isna(sma20.iloc[-1]) else close.iloc[-1]
            sma50_actual = sma50.iloc[-1] if not pd.isna(sma50.iloc[-1]) else close.iloc[-1]
            precio_actual = close.iloc[-1]
            
            # ACUMULACION
            if (sma20_actual > sma50_actual and 
                precio_actual > sma20_actual and
                (sma200 is None or sma50_actual > sma200.iloc[-1])):
                
                rango_20 = high.iloc[-20:].max() - low.iloc[-20:].min()
                rango_pct = rango_20 / precio_actual * 100
                
                if rango_pct < 3.0:
                    return 'ACUMULACION', 75
                else:
                    return 'TENDENCIA_ALCISTA', 60
            
            # DISTRIBUCION
            if (sma20_actual < sma50_actual and 
                precio_actual < sma20_actual and
                (sma200 is None or sma50_actual < sma200.iloc[-1])):
                
                rango_20 = high.iloc[-20:].max() - low.iloc[-20:].min()
                rango_pct = rango_20 / precio_actual * 100
                
                if rango_pct < 3.0:
                    return 'DISTRIBUCION', 75
                else:
                    return 'TENDENCIA_BAJISTA', 60
            
            # SPRING
            if (sma20_actual > sma50_actual and 
                precio_actual < sma20_actual and
                precio_actual > sma50_actual):
                
                soporte_reciente = low.iloc[-10:].min()
                if close.iloc[-1] > close.iloc[-2] and close.iloc[-2] < soporte_reciente * 1.001:
                    return 'SPRING', 70
            
            # UPTHRUST
            if (sma20_actual < sma50_actual and 
                precio_actual > sma20_actual and
                precio_actual < sma50_actual):
                
                resistencia_reciente = high.iloc[-10:].max()
                if close.iloc[-1] < close.iloc[-2] and close.iloc[-2] > resistencia_reciente * 0.999:
                    return 'UPTHRUST', 70
            
            return 'NEUTRAL', 30
            
        except Exception as e:
            self.logger.debug(f"Error detectando Wyckoff: {e}")
            return 'NEUTRAL', 0
    
    def _calcular_score_estructura_mejorado(self, 
                                           patrones: List[str],
                                           ob_cercano: bool,
                                           wyckoff_confianza: float,
                                           medio: Optional[Any]) -> float:
        # (código existente, sin cambios)
        score = 5.0
        
        if patrones:
            score += min(15, len(patrones) * 4)
        
        for p in patrones:
            if p in ['ENGULFING_ALCISTA', 'ENGULFING_BAJISTA']:
                score += 8
            elif p in ['MORNING_STAR', 'EVENING_STAR']:
                score += 10
            elif p in ['PIN_BAR_ALCISTA', 'PIN_BAR_BAJISTA']:
                score += 6
        
        if ob_cercano:
            score += 12
        
        if wyckoff_confianza > 60:
            score += 10
        elif wyckoff_confianza > 40:
            score += 5
        
        if medio and medio.en_nivel_clave:
            score += 10
        
        if medio:
            if medio.soporte_hits >= 3:
                score += 5
            if medio.resistencia_hits >= 3:
                score += 5
        
        return min(35.0, score)
    
    def _calcular_score_momentum_mejorado(self, medio: Optional[Any]) -> float:
        # (código existente, sin cambios)
        score = 5.0
        
        if not medio:
            return score
        
        if medio.rsi > 65 or medio.rsi < 35:
            score += 10
        elif medio.rsi > 60 or medio.rsi < 40:
            score += 7
        elif medio.rsi > 55 or medio.rsi < 45:
            score += 4
        
        if abs(medio.macd_histogram) > 0.0005:
            score += 10
        elif abs(medio.macd_histogram) > 0.0002:
            score += 7
        elif abs(medio.macd_histogram) > 0.0001:
            score += 4
        
        if medio.adx > 35:
            score += 10
        elif medio.adx > 25:
            score += 7
        elif medio.adx > 15:
            score += 4
        
        if medio.bb_width_pct > 20:
            score += 5
        elif medio.bb_width_pct > 10:
            score += 3
        
        return min(35.0, score)
    
    def _calcular_score_confluencia_mejorado(self,
                                            medio: Optional[Any],
                                            divergencia_rsi: Optional[str],
                                            patrones: List[str],
                                            ob_cercano: bool) -> float:
        # (código existente, sin cambios)
        score = 5.0
        confluencias = 0
        
        if medio and medio.en_nivel_clave:
            score += 10
            confluencias += 1
        
        if divergencia_rsi:
            score += 10
            confluencias += 1
        
        if patrones:
            score += 8
            confluencias += 1
        
        if ob_cercano:
            score += 7
            confluencias += 1
        
        if confluencias >= 3:
            score += 5
        
        return min(35.0, score)
    
    def _calcular_score_institucional_mejorado(self,
                                              wyckoff_fase: str,
                                              ob_cercano: bool,
                                              bull_ob: Optional[Dict],
                                              bear_ob: Optional[Dict]) -> float:
        # (código existente, sin cambios)
        score = 5.0
        
        if wyckoff_fase in ['ACUMULACION', 'DISTRIBUCION']:
            score += 15
        elif wyckoff_fase in ['SPRING', 'UPTHRUST']:
            score += 10
        elif wyckoff_fase in ['TENDENCIA_ALCISTA', 'TENDENCIA_BAJISTA']:
            score += 8
        
        if ob_cercano:
            score += 12
        elif bull_ob or bear_ob:
            score += 6
        
        if bull_ob and bull_ob.get('fuerza', 0) > 60:
            score += 5
        if bear_ob and bear_ob.get('fuerza', 0) > 60:
            score += 5
        
        return min(35.0, score)