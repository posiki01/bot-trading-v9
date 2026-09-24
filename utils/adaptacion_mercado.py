#!/usr/bin/env python3
"""
utils/adaptacion_mercado.py (V2.0 - CORREGIDO)
Sistema dinámico de adaptación al mercado.

CAMBIOS V2.0:
- ✅ Fix NaN en _calcular_atr_promedio_historico (dropna)
- ✅ Fix NaN en _calcular_adx (atr_seguro)
- ✅ Ajustes con límites sanos (evita 3x sobreajuste)
- ✅ Guarda razones de ajuste para debugging
- ✅ Cache con TTL por símbolo (antes no cacheaba)
- ✅ Detecta mercado lateral para relajar exigencia (no endurecerla)
"""

import logging
import time
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta

logger = logging.getLogger('BotTrading.AdaptacionMercado')


class AdaptadorMercado:
    """
    Detecta condiciones actuales del mercado y ajusta umbrales dinámicamente.
    V2.0 - CORREGIDO.
    """

    # Límites sanos para evitar sobreajuste
    FACTOR_MIN = 0.75
    FACTOR_MAX = 1.30

    # TTL de caché (segundos)
    CACHE_TTL = 300

    def __init__(self):
        self.logger = logging.getLogger('BotTrading.AdaptacionMercado')
        self._cache: Dict[str, Tuple[Dict[str, float], float]] = {}

    # ============================================================
    # API PÚBLICA
    # ============================================================

    def obtener_ajustes(
        self,
        simbolo: str,
        df_m5: pd.DataFrame,
        df_h1: pd.DataFrame = None,
        usar_cache: bool = True,
    ) -> Dict[str, float]:
        """
        Calcula ajustes dinámicos basados en condiciones actuales.

        Returns:
            Diccionario con multiplicadores para umbrales (todos acotados).
        """
        ajustes_base = {
            'tolerancia_nivel': 1.0,
            'volumen_minimo': 1.0,
            'score_minimo': 1.0,
            'rr_minimo': 1.0,
            'sl_min_pips': 1.0,
            'distancia_nivel_max': 1.0,
        }

        # Cache
        if usar_cache and simbolo in self._cache:
            cached_ajustes, ts = self._cache[simbolo]
            if time.time() - ts < self.CACHE_TTL:
                return cached_ajustes.copy()

        if df_m5 is None or len(df_m5) < 50:
            return ajustes_base

        ajustes = dict(ajustes_base)
        razones = []

        # ============================================================
        # 1. VOLATILIDAD (ATR)
        # ============================================================
        try:
            atr_actual = self._calcular_atr(df_m5)
            atr_promedio = self._calcular_atr_promedio_historico(df_m5)

            if atr_promedio > 0 and np.isfinite(atr_promedio):
                ratio_atr = atr_actual / atr_promedio

                if ratio_atr > 2.0:
                    ajustes['sl_min_pips'] = 1.20
                    ajustes['score_minimo'] = 1.10
                    ajustes['rr_minimo'] = 1.05
                    ajustes['volumen_minimo'] = 0.95
                    razones.append(f"Volatilidad ALTA (ratio={ratio_atr:.2f})")
                elif ratio_atr > 1.5:
                    ajustes['sl_min_pips'] = 1.10
                    ajustes['score_minimo'] = 1.05
                    razones.append(f"Volatilidad media-alta (ratio={ratio_atr:.2f})")
                elif ratio_atr < 0.5:
                    ajustes['sl_min_pips'] = 0.90
                    ajustes['score_minimo'] = 0.90
                    ajustes['rr_minimo'] = 0.90
                    ajustes['tolerancia_nivel'] = 1.10
                    razones.append(f"Volatilidad BAJA (ratio={ratio_atr:.2f})")
                elif ratio_atr < 0.7:
                    ajustes['sl_min_pips'] = 0.95
                    ajustes['score_minimo'] = 0.95
                    razones.append(f"Volatilidad media-baja (ratio={ratio_atr:.2f})")
        except Exception as e:
            self.logger.debug(f"⚠️ Error calculando ATR: {e}")

        # ============================================================
        # 2. LIQUIDEZ (Volumen)
        # ============================================================
        try:
            volumen_reciente = df_m5['Volume'].iloc[-20:].mean()
            volumen_promedio = df_m5['Volume'].rolling(100).mean().iloc[-1]

            if volumen_promedio > 0 and np.isfinite(volumen_promedio):
                ratio_volumen = volumen_reciente / volumen_promedio

                if ratio_volumen < 0.5:
                    ajustes['volumen_minimo'] = 1.15
                    ajustes['score_minimo'] *= 1.03
                    razones.append(f"Liquidez BAJA (ratio={ratio_volumen:.2f})")
                elif ratio_volumen > 2.0:
                    ajustes['volumen_minimo'] = 0.85
                    ajustes['score_minimo'] *= 0.95
                    razones.append(f"Liquidez ALTA (ratio={ratio_volumen:.2f})")
        except Exception as e:
            self.logger.debug(f"⚠️ Error calculando volumen: {e}")

        # ============================================================
        # 3. TENDENCIA (ADX en H1)
        # ============================================================
        if df_h1 is not None and len(df_h1) >= 30:
            try:
                adx = self._calcular_adx(df_h1)

                if np.isfinite(adx):
                    if adx < 15:
                        # Sin tendencia → mercado lateral
                        # ⚠️ En lugar de endurecer, RELAJAR un poco (permite operar rangos)
                        ajustes['score_minimo'] *= 0.95
                        ajustes['tolerancia_nivel'] *= 1.10
                        razones.append(f"Sin tendencia (ADX={adx:.1f}) → relajado")
                    elif adx > 40:
                        # Tendencia FUERTE → menos exigente con score, más con RR
                        ajustes['score_minimo'] *= 0.90
                        ajustes['rr_minimo'] *= 1.10
                        razones.append(f"Tendencia FUERTE (ADX={adx:.1f})")
            except Exception as e:
                self.logger.debug(f"⚠️ Error calculando ADX: {e}")

        # ============================================================
        # 4. RANGO DEL MERCADO
        # ============================================================
        if df_h1 is not None and len(df_h1) >= 50:
            try:
                close_actual = float(df_h1['Close'].iloc[-1])
                if close_actual > 0:
                    rango_30d = (df_h1['High'].iloc[-30:].max() -
                                 df_h1['Low'].iloc[-30:].min()) / close_actual * 100

                    if rango_30d < 2.0:
                        # Rango estrecho → breakout inminente
                        ajustes['tolerancia_nivel'] *= 1.10
                        ajustes['distancia_nivel_max'] *= 1.10
                        razones.append(f"Rango ESTRECHO ({rango_30d:.2f}%)")
                    elif rango_30d > 8.0:
                        # Rango amplio → más cuidado
                        ajustes['score_minimo'] *= 1.05
                        razones.append(f"Rango AMPLIO ({rango_30d:.2f}%)")
            except Exception as e:
                self.logger.debug(f"⚠️ Error calculando rango: {e}")

        # ============================================================
        # 5. ACOTAR FACTORES
        # ============================================================
        ajustes = self._acotar_ajustes(ajustes)

        # ============================================================
        # 6. CACHE
        # ============================================================
        if usar_cache:
            self._cache[simbolo] = (ajustes, time.time())

        # ============================================================
        # 7. LOG
        # ============================================================
        if razones:
            self.logger.info(f"📊 {simbolo}: {' | '.join(razones)}")
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"   Ajustes: {ajustes}")

        return ajustes

    def limpiar_cache(self, simbolo: Optional[str] = None):
        """Limpia la caché."""
        if simbolo:
            self._cache.pop(simbolo, None)
        else:
            self._cache.clear()

    # ============================================================
    # HELPERS
    # ============================================================

    def _acotar_ajustes(self, ajustes: Dict[str, float]) -> Dict[str, float]:
        """Acota todos los factores a [FACTOR_MIN, FACTOR_MAX]."""
        return {
            k: max(self.FACTOR_MIN, min(self.FACTOR_MAX, v))
            for k, v in ajustes.items()
        }

    def _calcular_atr(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """Calcula ATR actual (último valor)."""
        if df is None or len(df) < periodo + 1:
            return 0.0

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
            atr_valor = atr_serie.iloc[-1]

            if pd.isna(atr_valor) or not np.isfinite(atr_valor):
                return 0.0

            return float(atr_valor)
        except Exception:
            return 0.0

    def _calcular_atr_promedio_historico(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula ATR promedio de la historia.
        ✅ FIX V2.0: dropna() antes de mean()
        """
        if df is None or len(df) < periodo + 1:
            return 0.0

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

            # ✅ FIX: eliminar NaN antes de mean()
            atr_limpio = atr_serie.dropna()

            if len(atr_limpio) == 0:
                return 0.0

            promedio = atr_limpio.mean()

            if pd.isna(promedio) or not np.isfinite(promedio):
                return 0.0

            return float(promedio)
        except Exception:
            return 0.0

    def _calcular_adx(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """
        Calcula ADX.
        ✅ FIX V2.0: atr_seguro + di_suma_segura para evitar NaN/inf.
        """
        if df is None or len(df) < periodo * 2:
            return 0.0

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
            atr = tr.rolling(periodo).mean()

            # ✅ FIX: reemplazar 0 por NaN
            atr_seguro = atr.replace(0, np.nan)

            if atr_seguro.isna().all():
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

            plus_di = 100 * plus_dm.rolling(periodo).mean() / atr_seguro
            minus_di = 100 * minus_dm.rolling(periodo).mean() / atr_seguro

            di_suma = plus_di + minus_di
            di_suma_segura = di_suma.replace(0, np.nan)

            dx = 100 * (plus_di - minus_di).abs() / di_suma_segura
            adx_serie = dx.rolling(periodo).mean()

            adx_valor = adx_serie.iloc[-1]

            if pd.isna(adx_valor) or not np.isfinite(adx_valor):
                return 0.0

            return float(adx_valor)
        except Exception:
            return 0.0


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Añadir raíz al path
    if str(Path(__file__).parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent.parent))

    print("🧪 Probando AdaptadorMercado V2.0...")

    # Crear datos sintéticos
    np.random.seed(42)
    n = 500
    fechas = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq='5min', tz='UTC')

    # Simular volatilidad variable
    close = 1.1 + np.random.randn(n).cumsum() * 0.0005
    df_m5 = pd.DataFrame({
        'Open': close + np.random.randn(n) * 0.0001,
        'High': close + np.abs(np.random.randn(n)) * 0.0003,
        'Low': close - np.abs(np.random.randn(n)) * 0.0003,
        'Close': close,
        'Volume': np.random.randint(100, 1000, n),
    }, index=fechas)

    # H1 (construido desde M5)
    df_h1 = df_m5.resample('1h').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min',
        'Close': 'last', 'Volume': 'sum'
    }).dropna()

    adaptador = AdaptadorMercado()

    # Test 1: ATR sin NaN
    atr_promedio = adaptador._calcular_atr_promedio_historico(df_m5)
    print(f"1. ATR promedio: {atr_promedio:.6f}")
    assert np.isfinite(atr_promedio), "❌ ATR promedio es NaN/inf"
    print("   ✅ No NaN")

    # Test 2: ADX sin NaN
    adx = adaptador._calcular_adx(df_h1)
    print(f"2. ADX: {adx:.2f}")
    assert np.isfinite(adx), "❌ ADX es NaN/inf"
    print("   ✅ No NaN")

    # Test 3: Ajustes acotados
    ajustes = adaptador.obtener_ajustes('EURUSD', df_m5, df_h1)
    print(f"3. Ajustes: {ajustes}")
    for k, v in ajustes.items():
        assert adaptador.FACTOR_MIN <= v <= adaptador.FACTOR_MAX, f"❌ {k}={v} fuera de rango"
    print("   ✅ Todos acotados")

    # Test 4: Cache funciona
    ajustes2 = adaptador.obtener_ajustes('EURUSD', df_m5, df_h1)
    assert ajustes == ajustes2, "❌ Cache no funciona"
    print("4. ✅ Cache funciona")

    # Test 5: Cache se limpia
    adaptador.limpiar_cache('EURUSD')
    assert 'EURUSD' not in adaptador._cache
    print("5. ✅ Cache limpiada")

    print("\n✅ Todas las pruebas pasan")