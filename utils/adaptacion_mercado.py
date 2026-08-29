#!/usr/bin/env python3
"""
utils/adaptacion_mercado.py (V1.0 - DEFINITIVO)
Sistema dinámico de adaptación al mercado.
En lugar de ajustes fijos por mes, detecta condiciones actuales y ajusta umbrales.
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger('BotTrading.AdaptacionMercado')


class AdaptadorMercado:
    """
    Detecta condiciones actuales del mercado y ajusta umbrales dinámicamente.
    V1.0 - DEFINITIVO.
    """
    
    def __init__(self):
        self.logger = logging.getLogger('BotTrading.AdaptacionMercado')
        self._cache = {}
        self._cache_ttl = 300  # 5 minutos
    
    def obtener_ajustes(self, simbolo: str, df_m5: pd.DataFrame, df_h1: pd.DataFrame = None) -> Dict[str, float]:
        """
        Calcula ajustes dinámicos basados en condiciones actuales del mercado.
        
        Returns:
            Diccionario con multiplicadores para umbrales
        """
        ajustes = {
            'tolerancia_nivel': 1.0,
            'volumen_minimo': 1.0,
            'score_minimo': 1.0,
            'rr_minimo': 1.0,
            'sl_min_pips': 1.0,
            'distancia_nivel_max': 1.0,
        }
        
        if df_m5 is None or len(df_m5) < 50:
            return ajustes
        
        # ============================================================
        # 1. VOLATILIDAD (ATR)
        # ============================================================
        atr_actual = self._calcular_atr(df_m5)
        atr_promedio = self._calcular_atr_promedio_histórico(df_m5)
        
        if atr_promedio > 0:
            ratio_atr = atr_actual / atr_promedio
            
            if ratio_atr > 2.0:
                # Volatilidad MUY ALTA → SL más amplio, menos operaciones
                ajustes['sl_min_pips'] = 1.25
                ajustes['score_minimo'] = 1.15
                ajustes['rr_minimo'] = 1.10
                ajustes['volumen_minimo'] = 0.90
                self.logger.info(f"📊 {simbolo}: Volatilidad ALTA (ratio={ratio_atr:.2f})")
            elif ratio_atr > 1.5:
                # Volatilidad ALTA
                ajustes['sl_min_pips'] = 1.15
                ajustes['score_minimo'] = 1.08
                ajustes['rr_minimo'] = 1.05
            elif ratio_atr < 0.5:
                # Volatilidad MUY BAJA → Breakout inminente
                ajustes['sl_min_pips'] = 0.90
                ajustes['score_minimo'] = 0.90
                ajustes['rr_minimo'] = 0.90
                ajustes['tolerancia_nivel'] = 1.15
                self.logger.info(f"📊 {simbolo}: Volatilidad BAJA (ratio={ratio_atr:.2f})")
            elif ratio_atr < 0.7:
                # Volatilidad BAJA
                ajustes['sl_min_pips'] = 0.95
                ajustes['score_minimo'] = 0.95
        
        # ============================================================
        # 2. LIQUIDEZ (Volumen)
        # ============================================================
        volumen_reciente = df_m5['Volume'].iloc[-20:].mean()
        volumen_promedio = df_m5['Volume'].rolling(100).mean().iloc[-1]
        
        if volumen_promedio > 0:
            ratio_volumen = volumen_reciente / volumen_promedio
            
            if ratio_volumen < 0.5:
                # Liquidez BAJA → exigir más volumen
                ajustes['volumen_minimo'] = 1.20
                ajustes['score_minimo'] = 1.05
                self.logger.info(f"📊 {simbolo}: Liquidez BAJA (ratio={ratio_volumen:.2f})")
            elif ratio_volumen > 2.0:
                # Liquidez ALTA → menos exigente
                ajustes['volumen_minimo'] = 0.80
                ajustes['score_minimo'] = 0.90
                self.logger.info(f"📊 {simbolo}: Liquidez ALTA (ratio={ratio_volumen:.2f})")
        
        # ============================================================
        # 3. TENDENCIA (ADX)
        # ============================================================
        if df_h1 is not None and len(df_h1) >= 30:
            adx = self._calcular_adx(df_h1)
            
            if adx < 15:
                # Sin tendencia → menos operaciones en rangos
                ajustes['score_minimo'] *= 1.10
                ajustes['tolerancia_nivel'] *= 0.90
                self.logger.info(f"📊 {simbolo}: Sin tendencia (ADX={adx:.1f})")
            elif adx > 40:
                # Tendencia FUERTE → más operaciones
                ajustes['score_minimo'] *= 0.90
                ajustes['rr_minimo'] *= 1.10
                self.logger.info(f"📊 {simbolo}: Tendencia FUERTE (ADX={adx:.1f})")
        
        # ============================================================
        # 4. RANGO DEL MERCADO (Últimos 30 días)
        # ============================================================
        if df_h1 is not None and len(df_h1) >= 50:
            rango_30d = (df_h1['High'].iloc[-30:].max() - df_h1['Low'].iloc[-30:].min()) / df_h1['Close'].iloc[-1] * 100
            
            if rango_30d < 2.0:
                # Rango ESTRECHO → Breakout inminente
                ajustes['tolerancia_nivel'] *= 1.15
                ajustes['distancia_nivel_max'] *= 1.15
                self.logger.info(f"📊 {simbolo}: Rango ESTRECHO ({rango_30d:.2f}%)")
            elif rango_30d > 8.0:
                # Rango AMPLIO → más cuidado
                ajustes['score_minimo'] *= 1.08
                self.logger.info(f"📊 {simbolo}: Rango AMPLIO ({rango_30d:.2f}%)")
        
        return ajustes
    
    def _calcular_atr(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """Calcula ATR actual."""
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            
            return float(tr.rolling(periodo).mean().iloc[-1])
        except Exception:
            return 0.001
    
    def _calcular_atr_promedio_histórico(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """Calcula ATR promedio de los últimos 100 períodos."""
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            
            atr_serie = tr.rolling(periodo).mean()
            return float(atr_serie.mean())
        except Exception:
            return 0.001
    
    def _calcular_adx(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """Calcula ADX."""
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(periodo).mean()
            atr_seguro = atr.replace(0, np.nan)
            
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
            
            plus_di = 100 * plus_dm.rolling(periodo).mean() / atr_seguro
            minus_di = 100 * minus_dm.rolling(periodo).mean() / atr_seguro
            di_suma = plus_di + minus_di
            di_suma_segura = di_suma.replace(0, np.nan)
            
            dx = 100 * (plus_di - minus_di).abs() / di_suma_segura
            adx = dx.rolling(periodo).mean().iloc[-1]
            
            return float(adx) if not pd.isna(adx) else 0.0
        except Exception:
            return 0.0