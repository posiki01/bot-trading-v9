#!/usr/bin/env python3
"""
analysis/ml/ml_surrogate.py (V9.0)
Surrogate Trading - Aprende de todas las velas históricas.
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional

logger = logging.getLogger('BotTrading.ML.Surrogate')


class SurrogateTrader:
    """
    Genera simulaciones de trading para entrenamiento del modelo.
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self,
                 score_engine: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el Surrogate Trader.
        
        Args:
            score_engine: ScoreEngine
            modo_backtest: Modo backtest
        """
        self.score_engine = score_engine
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.ML.Surrogate')
    
    def generar_simulaciones(self,
                             mt5_connector: Any,
                             simbolos: List[str],
                             velas_back: int = 300) -> List[Dict[str, Any]]:
        """
        Genera simulaciones de trading.
        
        Args:
            mt5_connector: Conector MT5
            simbolos: Lista de símbolos
            velas_back: Número de velas a analizar
        
        Returns:
            Lista de simulaciones
        """
        todas_las_simulaciones = []
        max_total = 2000
        max_por_simbolo = 300
        
        for simbolo in simbolos:
            try:
                df = mt5_connector.obtener_datos(simbolo, n_velas=velas_back)
                if df is None or len(df) < 100:
                    self.logger.warning(f"⚠️ {simbolo}: Sin datos suficientes")
                    continue
                
                simulaciones = self._simular_simbolo(df, simbolo, max_por_simbolo)
                todas_las_simulaciones.extend(simulaciones)
                
                if len(todas_las_simulaciones) >= max_total:
                    break
                    
            except Exception as e:
                self.logger.warning(f"⚠️ Error en {simbolo}: {e}")
                continue
        
        return todas_las_simulaciones
    
    def _simular_simbolo(self, df: Any, simbolo: str,
                         max_samples: int) -> List[Dict]:
        """Simula operaciones para un símbolo."""
        simulaciones = []
        
        try:
            start_idx = 100
            end_idx = len(df) - 20
            available = max(0, end_idx - start_idx)
            
            if available <= 0:
                return []
            
            n_samples = min(max_samples, available)
            indices = np.linspace(start_idx, end_idx - 1, n_samples, dtype=int)
            
            for i in indices:
                slice_df = df.iloc[:i]
                if slice_df.empty:
                    continue
                
                # Análisis simplificado
                analisis = self._analizar_slice(slice_df, simbolo)
                
                if not analisis or analisis.get('direccion') == 'NEUTRAL':
                    continue
                
                score = analisis.get('senal', 0)
                if score < 40:
                    continue
                
                # Simular resultado
                resultado = self._simular_resultado(
                    slice_df=slice_df,
                    df_completo=df,
                    idx=i,
                    analisis=analisis
                )
                
                if resultado != 0:
                    simulaciones.append({
                        'pts_estructura': analisis.get('pts_estructura', 50),
                        'pts_momentum': analisis.get('pts_momentum', 50),
                        'pts_confluencia': analisis.get('pts_confluencia', 50),
                        'pts_institucional': analisis.get('pts_institucional', 50),
                        'modificador_noticias': 0,
                        'sent_cot': 0,
                        'direccion': analisis.get('direccion', 'COMPRA'),
                        'ganancia_neta': resultado * 0.1,
                    })
                    
        except Exception as e:
            self.logger.debug(f"Error simulando {simbolo}: {e}")
        
        return simulaciones
    
    def _analizar_slice(self, df: Any, simbolo: str) -> Optional[Dict]:
        """Analiza un slice de datos."""
        try:
            close = df['Close']
            high = df['High']
            low = df['Low']
            
            # RSI
            delta = close.diff()
            ganancia = (delta.where(delta > 0, 0.0)).rolling(14).mean()
            perdida = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
            rs = ganancia / perdida
            rsi = 100.0 - (100.0 / (1.0 + rs))
            rsi_actual = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
            
            # EMA
            ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
            ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
            
            # ATR
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            
            # Dirección
            if rsi_actual > 60 and ema9 > ema21:
                direccion = 'COMPRA'
                senal = rsi_actual * 0.5 + 30
            elif rsi_actual < 40 and ema9 < ema21:
                direccion = 'VENTA'
                senal = (100 - rsi_actual) * 0.5 + 30
            else:
                return None
            
            # Puntuación
            pts_estructura = 30 + (abs(rsi_actual - 50) / 50) * 30
            pts_momentum = 30 + (atr / close.iloc[-1] * 100) * 50
            pts_confluencia = 20 + (1 if ema9 > ema21 else 0) * 20
            pts_institucional = 20
            
            return {
                'direccion': direccion,
                'senal': min(100, senal),
                'pts_estructura': min(30, pts_estructura),
                'pts_momentum': min(35, pts_momentum),
                'pts_confluencia': min(35, pts_confluencia),
                'pts_institucional': min(35, pts_institucional),
                'atr': atr,
            }
            
        except Exception as e:
            self.logger.debug(f"Error analizando slice: {e}")
            return None
    
    def _simular_resultado(self, slice_df: Any, df_completo: Any,
                           idx: int, analisis: Dict) -> float:
        """Simula el resultado de una operación."""
        try:
            close = slice_df['Close']
            precio_actual = close.iloc[-1]
            atr = analisis.get('atr', 0.001)
            direccion = analisis.get('direccion', 'COMPRA')
            score = analisis.get('senal', 50)
            
            # SL/TP basado en score
            if score > 85:
                sl_dist = atr * 0.8
                tp_dist = atr * 3.0
            elif score > 70:
                sl_dist = atr * 1.0
                tp_dist = atr * 2.5
            else:
                sl_dist = atr * 1.2
                tp_dist = atr * 2.0
            
            if direccion == 'COMPRA':
                sl = precio_actual - sl_dist
                tp = precio_actual + tp_dist
            else:
                sl = precio_actual + sl_dist
                tp = precio_actual - tp_dist
            
            # Verificar resultado en las siguientes 15 velas
            futuro = df_completo.iloc[idx+1:idx+16]
            if futuro.empty:
                return 0
            
            if direccion == 'COMPRA':
                if futuro['Low'].min() <= sl:
                    return -1
                elif futuro['High'].max() >= tp:
                    return 1
            else:
                if futuro['High'].max() >= sl:
                    return -1
                elif futuro['Low'].min() <= tp:
                    return 1
            
            return 0
            
        except Exception:
            return 0