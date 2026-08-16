#!/usr/bin/env python3
"""
analysis/fases_validacion.py (V9.0)
Validación de Fase 2 (M15) - Lógica extraída de fases.py.
"""

import logging
import pandas as pd
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger('BotTrading.FasesValidacion')


class ValidadorFase2:
    """Validador de Fase 2 (M15)."""
    
    def __init__(self, umbrales: Dict[str, float], modo_backtest: bool = False):
        self.umbrales = umbrales
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.FasesValidacion')
    
    def validar(self, simbolo: str, df_m15: pd.DataFrame, direccion_h1: str,
                regimen_h1: str, contexto_h1: Optional[Dict] = None) -> Tuple[bool, str, Dict]:
        """Valida Fase 2."""
        detalles = {}
        
        if df_m15 is None or len(df_m15) < 30:
            return False, f"Datos insuficientes", detalles
        
        rsi = self._calcular_rsi(df_m15)
        macd = self._calcular_macd(df_m15)
        adx = self._calcular_adx(df_m15)
        volumen_relativo = self._calcular_volumen_relativo(df_m15)
        
        detalles.update({'rsi': rsi, 'macd': macd, 'adx': adx, 'volumen_relativo': volumen_relativo})
        
        adx_min = self.umbrales.get('adx_minimo', 10)
        if adx < adx_min:
            return False, f"ADX bajo ({adx:.0f} < {adx_min:.0f})", detalles
        
        vol_min = self.umbrales.get('vol_minimo', 0.15)
        if volumen_relativo < vol_min:
            if adx > 30 or abs(macd) > 0.0005:
                self.logger.debug(f"⚠️ {simbolo}: volumen bajo pero permitido")
            else:
                return False, f"Volumen bajo ({volumen_relativo:.1f}x < {vol_min:.1f}x)", detalles
        
        rsi_tol = self.umbrales.get('rsi_tolerancia', 10)
        if direccion_h1 == 'COMPRA' and rsi > (80 + rsi_tol):
            return False, f"RSI sobrecompra ({rsi:.0f} > {80 + rsi_tol:.0f})", detalles
        if direccion_h1 == 'VENTA' and rsi < (20 - rsi_tol):
            return False, f"RSI sobreventa ({rsi:.0f} < {20 - rsi_tol:.0f})", detalles
        
        return True, "OK", detalles
    
    def _calcular_rsi(self, df: pd.DataFrame, periodo: int = 14) -> float:
        if df is None or len(df) < periodo:
            return 50.0
        try:
            close = df['Close']
            delta = close.diff()
            ganancia = (delta.where(delta > 0, 0.0)).rolling(window=periodo).mean()
            perdida = (-delta.where(delta < 0, 0.0)).rolling(window=periodo).mean()
            rs = ganancia / perdida if perdida > 0 else 100
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
        except Exception:
            return 50.0
    
    def _calcular_macd(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> float:
        if df is None or len(df) < slow:
            return 0.0
        try:
            close = df['Close']
            ema_fast = close.ewm(span=fast, adjust=False).mean()
            ema_slow = close.ewm(span=slow, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            return float(macd_line.iloc[-1] - signal_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else 0.0
        except Exception:
            return 0.0
    
    def _calcular_adx(self, df: pd.DataFrame, periodo: int = 14) -> float:
        if df is None or len(df) < periodo:
            return 0.0
        try:
            import numpy as np
            high = df['High']; low = df['Low']; close = df['Close']
            tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
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
    
    def _calcular_volumen_relativo(self, df: pd.DataFrame) -> float:
        if df is None or 'Volume' not in df.columns or len(df) < 20:
            return 1.0
        try:
            vol_actual = df['Volume'].iloc[-1]
            vol_promedio = df['Volume'].rolling(20).mean().iloc[-1]
            return vol_actual / vol_promedio if vol_promedio > 0 else 1.0
        except Exception:
            return 1.0