#!/usr/bin/env python3
"""
analysis/capas_pesado.py (V9.0 - CORREGIDO DEFINITIVO)
Capa 3: Análisis pesado - Patrones, Wyckoff, divergencias.
"""

import time
import logging
import pandas as pd
from typing import Dict, Any, Optional, List

from analysis.capas import AnalisisPesado

logger = logging.getLogger('BotTrading.CapasPesado')


class AnalisisPesadoEngine:
    """Motor de análisis pesado (Capa 3)."""
    
    def __init__(self, analisis_tecnico: Any, umbrales: Dict[str, float],
                 config: Optional[Any] = None, modo_backtest: bool = False):
        self.analisis_tecnico = analisis_tecnico
        self.umbrales = umbrales
        self.config = config
        self.modo_backtest = modo_backtest
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
            
            # ============================================================
            # 1. DETECCIÓN DE PATRONES (CON MANEJO DE ERRORES)
            # ============================================================
            
            patrones_encontrados = []
            patron_principal = 'N/A'
            calidad_patron = 0
            
            try:
                # ✅ AHORA SIEMPRE RETORNA 3 VALORES
                resultado = self._detectar_patrones_seguro(df)
                if resultado is not None and len(resultado) >= 3:
                    patrones_encontrados, patron_principal, calidad_patron = resultado
                else:
                    patrones_encontrados = []
                    patron_principal = 'N/A'
                    calidad_patron = 0
            except Exception as e:
                self.logger.debug(f"Error en detección de patrones: {e}")
                patrones_encontrados = []
                patron_principal = 'N/A'
                calidad_patron = 0
            
            # ============================================================
            # 2. ORDER BLOCKS
            # ============================================================
            
            bull_ob, bear_ob, ob_cercano = self._detectar_order_blocks(df, df_h4)
            
            # ============================================================
            # 3. WYCKOFF
            # ============================================================
            
            wyckoff_fase, wyckoff_confianza = self._detectar_wyckoff(df)
            
            # ============================================================
            # 4. DIVERGENCIAS
            # ============================================================
            
            divergencia_rsi, divergencia_macd = self._detectar_divergencias(df)
            
            # ============================================================
            # 5. CALCULAR SCORES
            # ============================================================
            
            score_estructura = self._calcular_score_estructura(
                patrones_encontrados, ob_cercano, wyckoff_confianza
            )
            
            score_momentum = self._calcular_score_momentum(medio)
            
            score_confluencia = self._calcular_score_confluencia(
                medio, divergencia_rsi
            )
            
            score_institucional = self._calcular_score_institucional(
                wyckoff_fase, ob_cercano
            )
            
            return AnalisisPesado(
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
            
        except Exception as e:
            self.logger.error(f"❌ Error en análisis pesado {simbolo}: {e}")
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
    
    def _detectar_patrones(self, df: pd.DataFrame) -> tuple:
        """
        Detecta patrones chartistas - CON LOGS DETALLADOS.
        
        Returns:
            (patrones_encontrados, patron_principal, calidad_patron)
            SIEMPRE retorna 3 valores.
        """
        self.logger.debug(f"🔍 _detectar_patrones: INICIO")
        
        patrones = []
        patron_principal = 'N/A'
        calidad_patron = 0
        
        # 1. Validar datos
        self.logger.debug(f"🔍 Validando datos: df is None? {df is None}, len={len(df) if df is not None else 0}")
        
        if df is None or len(df) < 5:
            self.logger.debug(f"🔍 _detectar_patrones: SALIDA TEMPRANA - datos insuficientes")
            return [], 'N/A', 0
        
        self.logger.debug(f"🔍 _detectar_patrones: df tiene {len(df)} filas")
        
        try:
            # 2. Intentar usar analisis_tecnico
            self.logger.debug(f"🔍 Verificando analisis_tecnico: {hasattr(self, 'analisis_tecnico')}")
            
            if hasattr(self, 'analisis_tecnico') and hasattr(self.analisis_tecnico, 'detectar_patrones'):
                self.logger.debug(f"🔍 Llamando a analisis_tecnico.detectar_patrones()...")
                try:
                    resultado = self.analisis_tecnico.detectar_patrones(df)
                    self.logger.debug(f"🔍 analisis_tecnico resultado: {type(resultado)} - {resultado if resultado is not None else 'None'}")
                    
                    if resultado is not None and isinstance(resultado, list):
                        patrones = resultado
                        self.logger.debug(f"🔍 Patrones encontrados por analisis_tecnico: {len(patrones)}")
                    elif resultado is not None:
                        self.logger.debug(f"🔍 Resultado no es lista, tipo: {type(resultado)}")
                        patrones = [resultado] if isinstance(resultado, dict) else []
                    else:
                        self.logger.debug(f"🔍 analisis_tecnico retornó None")
                        patrones = []
                        
                except Exception as e:
                    self.logger.error(f"❌ Error en analisis_tecnico.detectar_patrones: {e}")
                    patrones = []
            else:
                self.logger.debug(f"🔍 analisis_tecnico no disponible o no tiene detectar_patrones")
            
            # 3. Si no hay patrones, usar detección local
            if not patrones:
                self.logger.debug(f"🔍 Usando detección local de patrones...")
                try:
                    patrones = self._detectar_patrones_local(df)
                    self.logger.debug(f"🔍 Patrones locales encontrados: {len(patrones)}")
                except Exception as e:
                    self.logger.error(f"❌ Error en _detectar_patrones_local: {e}")
                    patrones = []
            
            # 4. Procesar patrones
            self.logger.debug(f"🔍 Procesando {len(patrones)} patrones...")
            
            for i, p in enumerate(patrones):
                nombre = p.get('nombre', '')
                calidad = p.get('calidad', 0)
                self.logger.debug(f"🔍   Patrón {i+1}: {nombre} (calidad: {calidad})")
                
                if calidad > calidad_patron:
                    calidad_patron = calidad
                    patron_principal = nombre
            
            # 5. Extraer nombres
            nombres = [p.get('nombre', '') for p in patrones if p.get('nombre')]
            self.logger.debug(f"🔍 Nombres extraídos: {nombres}")
            
            # 6. RETORNAR SIEMPRE 3 VALORES
            self.logger.debug(f"🔍 _detectar_patrones: RETORNANDO -> ({len(nombres)} patrones, '{patron_principal}', {calidad_patron})")
            return nombres, patron_principal, calidad_patron
            
        except Exception as e:
            self.logger.error(f"❌ Error en _detectar_patrones: {e}")
            import traceback
            self.logger.error(f"❌ Traceback: {traceback.format_exc()}")
            # SIEMPRE RETORNAR 3 VALORES
            return [], 'N/A', 0
        
    def _detectar_patrones_local(self, df: pd.DataFrame) -> List[Dict]:
        """Detección local de patrones básicos."""
        patrones = []
        
        if df is None or len(df) < 2:
            return patrones
        
        try:
            vela = df.iloc[-1]
            vela_anterior = df.iloc[-2] if len(df) > 1 else vela
            
            rango = vela['High'] - vela['Low']
            
            if rango > 0:
                sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
                sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
                cuerpo = abs(vela['Close'] - vela['Open'])
                
                if sombra_inf / rango > 0.6 and cuerpo / rango < 0.3:
                    patrones.append({
                        'nombre': 'PIN_BAR_ALCISTA',
                        'calidad': 70 + min(30, (sombra_inf / rango) * 100),
                        'direccion': 'COMPRA'
                    })
                
                if sombra_sup / rango > 0.6 and cuerpo / rango < 0.3:
                    patrones.append({
                        'nombre': 'PIN_BAR_BAJISTA',
                        'calidad': 70 + min(30, (sombra_sup / rango) * 100),
                        'direccion': 'VENTA'
                    })
                
                if len(df) > 1:
                    if (vela['Close'] > vela_anterior['Open'] and 
                        vela['Open'] < vela_anterior['Close'] and
                        vela_anterior['Close'] < vela_anterior['Open']):
                        patrones.append({
                            'nombre': 'ENGULFING_ALCISTA',
                            'calidad': 75,
                            'direccion': 'COMPRA'
                        })
                    
                    if (vela['Close'] < vela_anterior['Open'] and 
                        vela['Open'] > vela_anterior['Close'] and
                        vela_anterior['Close'] > vela_anterior['Open']):
                        patrones.append({
                            'nombre': 'ENGULFING_BAJISTA',
                            'calidad': 75,
                            'direccion': 'VENTA'
                        })
                
                if cuerpo / rango < 0.1:
                    patrones.append({
                        'nombre': 'DOJI',
                        'calidad': 60,
                        'direccion': 'NEUTRAL'
                    })
                    
        except Exception as e:
            self.logger.debug(f"Error en _detectar_patrones_local: {e}")
        
        return patrones
    
    def _detectar_order_blocks(self, df: pd.DataFrame, df_h4: Optional[pd.DataFrame]) -> tuple:
        """Detecta Order Blocks."""
        try:
            if hasattr(self.analisis_tecnico, 'identificar_order_blocks'):
                df_usar = df_h4 if df_h4 is not None and len(df_h4) >= 50 else df
                return self.analisis_tecnico.identificar_order_blocks(df_usar)
            
            if len(df) < 20:
                return None, None, False
            
            high = df['High']
            low = df['Low']
            close = df['Close']
            precio_actual = close.iloc[-1]
            
            bull_ob = None
            min_reciente = low.iloc[-20:].min()
            if min_reciente > precio_actual * 0.99:
                bull_ob = {
                    'top': min_reciente * 1.002,
                    'bottom': min_reciente * 0.998,
                    'tipo': 'BULLISH'
                }
            
            bear_ob = None
            max_reciente = high.iloc[-20:].max()
            if max_reciente < precio_actual * 1.01:
                bear_ob = {
                    'top': max_reciente * 1.002,
                    'bottom': max_reciente * 0.998,
                    'tipo': 'BEARISH'
                }
            
            ob_cercano = (bull_ob is not None and abs(bull_ob['top'] - precio_actual) / precio_actual < 0.01) or \
                         (bear_ob is not None and abs(bear_ob['bottom'] - precio_actual) / precio_actual < 0.01)
            
            return bull_ob, bear_ob, ob_cercano
            
        except Exception as e:
            self.logger.debug(f"Error detectando Order Blocks: {e}")
            return None, None, False
    
    def _detectar_wyckoff(self, df: pd.DataFrame) -> tuple:
        """Detecta fases de Wyckoff."""
        try:
            if hasattr(self.analisis_tecnico, 'detectar_wyckoff'):
                wyckoff = self.analisis_tecnico.detectar_wyckoff(df)
                if wyckoff:
                    return wyckoff.get('fase', 'NEUTRAL'), wyckoff.get('confianza', 0)
            
            if len(df) < 30:
                return 'NEUTRAL', 0
            
            close = df['Close']
            sma20 = close.rolling(20).mean()
            sma50 = close.rolling(50).mean()
            
            sma20_actual = sma20.iloc[-1] if not pd.isna(sma20.iloc[-1]) else close.iloc[-1]
            sma50_actual = sma50.iloc[-1] if not pd.isna(sma50.iloc[-1]) else close.iloc[-1]
            precio_actual = close.iloc[-1]
            
            if sma20_actual > sma50_actual and precio_actual > sma20_actual:
                return 'ACUMULACION', 60
            elif sma20_actual < sma50_actual and precio_actual < sma20_actual:
                return 'DISTRIBUCION', 60
            elif precio_actual > sma50_actual and precio_actual < sma20_actual:
                return 'SPRING', 50
            elif precio_actual < sma50_actual and precio_actual > sma20_actual:
                return 'UPTHRUST', 50
            else:
                return 'NEUTRAL', 30
                
        except Exception as e:
            self.logger.debug(f"Error detectando Wyckoff: {e}")
            return 'NEUTRAL', 0
    
    def _detectar_divergencias(self, df: pd.DataFrame) -> tuple:
        """Detecta divergencias RSI y MACD."""
        try:
            if hasattr(self.analisis_tecnico, 'detectar_divergencia'):
                rsi = self._calcular_rsi_ultimo(df['Close'])
                divergencia = self.analisis_tecnico.detectar_divergencia(df, pd.Series([rsi] * len(df)))
                if divergencia:
                    tipo = divergencia.get('tipo')
                    if tipo == 'BULLISH':
                        return 'BULLISH', None
                    elif tipo == 'BEARISH':
                        return 'BEARISH', None
            
            if len(df) < 20:
                return None, None
            
            close = df['Close']
            rsi = self._calcular_rsi_serie(df['Close'])
            
            if len(rsi) < 10:
                return None, None
            
            precio_reciente = close.iloc[-10:]
            rsi_reciente = rsi.iloc[-10:] if len(rsi) >= 10 else rsi
            
            max_precio = precio_reciente.max()
            min_precio = precio_reciente.min()
            max_rsi = rsi_reciente.max()
            min_rsi = rsi_reciente.min()
            
            if max_precio > precio_reciente.iloc[-5] and max_rsi < rsi_reciente.iloc[-5]:
                return 'BEARISH', None
            
            if min_precio < precio_reciente.iloc[-5] and min_rsi > rsi_reciente.iloc[-5]:
                return 'BULLISH', None
            
            return None, None
            
        except Exception as e:
            self.logger.debug(f"Error detectando divergencias: {e}")
            return None, None
    
    def _calcular_rsi_serie(self, precios: pd.Series, periodo: int = 14) -> pd.Series:
        """Calcula RSI como serie."""
        if precios is None or len(precios) < periodo:
            return pd.Series([50.0] * len(precios) if len(precios) > 0 else [50.0])
        try:
            delta = precios.diff()
            ganancia = (delta.where(delta > 0, 0.0)).rolling(window=periodo).mean()
            perdida = (-delta.where(delta < 0, 0.0)).rolling(window=periodo).mean()
            rs = ganancia / perdida
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return rsi.fillna(50.0)
        except Exception:
            return pd.Series([50.0] * len(precios))
    
    def _calcular_rsi_ultimo(self, precios: pd.Series, periodo: int = 14) -> float:
        """Calcula RSI (último valor)."""
        rsi = self._calcular_rsi_serie(precios, periodo)
        return float(rsi.iloc[-1]) if len(rsi) > 0 and not pd.isna(rsi.iloc[-1]) else 50.0
    
    def _calcular_score_estructura(self, patrones: List, ob_cercano: bool, wyckoff_confianza: float) -> float:
        """Calcula score de estructura (0-30)."""
        score = 0.0
        
        if patrones:
            score += min(30, len(patrones) * 8)
        
        if ob_cercano:
            score += 20
        
        if wyckoff_confianza > 40:
            score += min(20, wyckoff_confianza / 8)
        
        return min(30.0, score)
    
    def _calcular_score_momentum(self, medio: Optional[Any]) -> float:
        """Calcula score de momentum (0-35)."""
        score = 0.0
        
        if medio:
            if medio.rsi > 55 or medio.rsi < 45:
                score += 15
            
            if medio.macd_histogram > 0:
                score += 15
            
            if medio.adx > 15:
                score += min(20, medio.adx)
        
        return min(35.0, score)
    
    def _calcular_score_confluencia(self, medio: Optional[Any], divergencia_rsi: Optional[str]) -> float:
        """Calcula score de confluencia (0-35)."""
        score = 0.0
        
        if medio and medio.en_nivel_clave:
            score += 20
        
        if divergencia_rsi:
            score += 15
        
        return min(35.0, score)
    
    def _calcular_score_institucional(self, wyckoff_fase: str, ob_cercano: bool) -> float:
        """Calcula score institucional (0-35)."""
        score = 0.0
        
        if wyckoff_fase in ['ACUMULACION', 'DISTRIBUCION']:
            score += 20
        
        if ob_cercano:
            score += 15
        
        return min(35.0, score)