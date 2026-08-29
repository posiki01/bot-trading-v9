#!/usr/bin/env python3
"""
analysis/capas_medio.py (V9.16 - CORREGIDO)
Capa 2: Análisis medio con detección de niveles.

CORRECCIONES V9.16:
- HITS_MINIMOS: 2 (antes 3)
- DISTANCIA_MAXIMA_PCT: 3.0 (antes 1.0)
- Usar obtener_niveles() en lugar de obtener_niveles_validos()
- Fallback con lookback ampliado
- Detección de niveles más flexible para cripto y metales
"""

import time
import numpy as np
import logging
import pandas as pd
from typing import Dict, Any, Optional, Tuple

from analysis.capas import AnalisisMedio
from analysis.niveles import NivelTracker

logger = logging.getLogger('BotTrading.CapasMedio')


class AnalisisMedioEngine:
    """
    Motor de análisis medio (Capa 2).
    V9.16 - CORREGIDO: Detección de niveles más flexible.
    """

    def __init__(self,
                 umbrales: Dict[str, float],
                 config: Optional[Any] = None,
                 nivel_tracker: Optional[NivelTracker] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el motor de análisis medio.
        """
        self.umbrales = umbrales
        self.config = config
        self.nivel_tracker = nivel_tracker
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.CapasMedio')

    # ============================================================
    # EJECUTAR ANÁLISIS
    # ============================================================

    def ejecutar(self, df: pd.DataFrame, simbolo: str,
                 rapido: Optional[Any] = None,
                 niveles_historicos: Optional[Dict] = None,
                 score_h1: float = 0) -> AnalisisMedio:
        """
        Ejecuta el análisis medio.
        V9.16 - CORREGIDO: Detección de niveles mejorada.
        """
        start_time = time.time()
        self.logger.info(f"⚙️ {simbolo}: Iniciando análisis medio...")

        try:
            # ============================================================
            # 0. VALIDAR DATOS BÁSICOS
            # ============================================================
            if df is None:
                self.logger.error(f"❌ {simbolo}: DataFrame es None")
                return AnalisisMedio(
                    valido=False, simbolo=simbolo,
                    rsi=50, macd_line=0, macd_signal=0, macd_histogram=0,
                    bb_upper=0, bb_lower=0, bb_middle=0, bb_width_pct=0,
                    adx=0, atr=0, sma20=0, sma50=0, sma200=None,
                    soporte_cercano=None, resistencia_cercana=None,
                    distancia_soporte_pct=0, distancia_resistencia_pct=0,
                    soporte_hits=0, resistencia_hits=0,
                    pasa_filtro=False, razon_rechazo="DataFrame es None"
                )

            if len(df) < 50:
                self.logger.warning(f"⚠️ {simbolo}: DataFrame insuficiente ({len(df)} velas < 50)")
                return AnalisisMedio(
                    valido=False, simbolo=simbolo,
                    rsi=50, macd_line=0, macd_signal=0, macd_histogram=0,
                    bb_upper=0, bb_lower=0, bb_middle=0, bb_width_pct=0,
                    adx=0, atr=0, sma20=0, sma50=0, sma200=None,
                    soporte_cercano=None, resistencia_cercana=None,
                    distancia_soporte_pct=0, distancia_resistencia_pct=0,
                    soporte_hits=0, resistencia_hits=0,
                    pasa_filtro=False, razon_rechazo=f"Datos insuficientes ({len(df)} velas)"
                )

            # Validar columnas requeridas
            required_cols = ['High', 'Low', 'Close']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                self.logger.error(f"❌ {simbolo}: Columnas faltantes: {missing_cols}")
                return AnalisisMedio(
                    valido=False, simbolo=simbolo,
                    rsi=50, macd_line=0, macd_signal=0, macd_histogram=0,
                    bb_upper=0, bb_lower=0, bb_middle=0, bb_width_pct=0,
                    adx=0, atr=0, sma20=0, sma50=0, sma200=None,
                    soporte_cercano=None, resistencia_cercana=None,
                    distancia_soporte_pct=0, distancia_resistencia_pct=0,
                    soporte_hits=0, resistencia_hits=0,
                    pasa_filtro=False, razon_rechazo=f"Columnas faltantes: {missing_cols}"
                )

            # Log de datos
            self.logger.debug(f"📊 {simbolo}: Datos - {len(df)} velas, última: {df.index[-1]}")
            self.logger.debug(f"📊 {simbolo}: Precio actual: {df['Close'].iloc[-1]:.5f}")

            precio_actual = df['Close'].iloc[-1]

            # ============================================================
            # 1. INDICADORES TÉCNICOS
            # ============================================================
            self.logger.debug(f"📊 {simbolo}: Calculando RSI...")
            rsi = self._calcular_rsi_corregido(df['Close'], simbolo)
            self.logger.debug(f"📊 {simbolo}: RSI = {rsi:.2f}")

            self.logger.debug(f"📊 {simbolo}: Calculando MACD...")
            macd = self._calcular_macd_corregido(df['Close'], simbolo)
            self.logger.debug(f"📊 {simbolo}: MACD = {macd['macd']:.4f}, Signal = {macd['signal']:.4f}")

            self.logger.debug(f"📊 {simbolo}: Calculando Bollinger...")
            bb = self._calcular_bollinger_corregido(df['Close'], simbolo)
            self.logger.debug(f"📊 {simbolo}: BB Width = {bb['width']:.2f}%")

            self.logger.debug(f"📊 {simbolo}: Calculando ADX...")
            adx = self._calcular_adx_corregido(df, simbolo)
            self.logger.debug(f"📊 {simbolo}: ADX = {adx:.2f}")

            self.logger.debug(f"📊 {simbolo}: Calculando ATR...")
            atr = self._calcular_atr(df)
            self.logger.debug(f"📊 {simbolo}: ATR = {atr:.5f}")

            # SMAs
            sma20 = df['Close'].rolling(20).mean().iloc[-1]
            sma50 = df['Close'].rolling(50).mean().iloc[-1]
            sma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else None

            self.logger.debug(f"📊 {simbolo}: SMA20 = {sma20:.5f}, SMA50 = {sma50:.5f}")

            # ============================================================
            # 2. DETECCIÓN DE NIVELES (V9.16 - CORREGIDO)
            # ============================================================
            self.logger.debug(f"📊 {simbolo}: Detectando niveles...")
            soporte_cercano, resistencia_cercana, soporte_hits, resistencia_hits = \
                self._detectar_niveles_v9_16(df, simbolo, precio_actual, niveles_historicos)

            distancia_soporte_pct = (precio_actual - soporte_cercano) / precio_actual * 100 if soporte_cercano else 100
            distancia_resistencia_pct = (resistencia_cercana - precio_actual) / precio_actual * 100 if resistencia_cercana else 100

            self.logger.debug(f"📊 {simbolo}: Soporte = {soporte_cercano}, Resistencia = {resistencia_cercana}")
            self.logger.debug(f"📊 {simbolo}: Dist soporte = {distancia_soporte_pct:.2f}%, Dist resistencia = {distancia_resistencia_pct:.2f}%")

            # ============================================================
            # 3. EVALUACIÓN
            # ============================================================

            # 🔥 UMBRALES PARA BACKTEST
            adx_umbral = self.umbrales.get('adx_fuerte', 20)
            if self.modo_backtest:
                adx_umbral = 10

            adx_fuerte = adx >= adx_umbral
            en_nivel_clave = (soporte_cercano is not None and distancia_soporte_pct < self.umbrales.get('distancia_nivel_max', 3.0)) or \
                            (resistencia_cercana is not None and distancia_resistencia_pct < self.umbrales.get('distancia_nivel_max', 3.0))

            if self.modo_backtest:
                en_nivel_clave = (soporte_cercano is not None and distancia_soporte_pct < 5.0) or \
                                (resistencia_cercana is not None and distancia_resistencia_pct < 5.0)

            tendencia_alineada = False
            if rapido and rapido.valido:
                if rapido.tendencia_corta == 'ALCISTA' and rsi > 50:
                    tendencia_alineada = True
                elif rapido.tendencia_corta == 'BAJISTA' and rsi < 50:
                    tendencia_alineada = True

            # Pasa filtro?
            pasa_filtro = adx_fuerte or en_nivel_clave or tendencia_alineada or (rsi >= 65 or rsi <= 35)

            if not pasa_filtro:
                razon_rechazo = self._generar_razon_rechazo(
                    simbolo=simbolo,
                    adx=adx,
                    adx_umbral=adx_umbral,
                    en_nivel_clave=en_nivel_clave,
                    tendencia_alineada=tendencia_alineada,
                    rsi=rsi,
                    soporte_cercano=soporte_cercano,
                    resistencia_cercana=resistencia_cercana,
                    distancia_soporte_pct=distancia_soporte_pct,
                    distancia_resistencia_pct=distancia_resistencia_pct
                )
            else:
                razon_rechazo = ""

            # ============================================================
            # 4. CREAR RESULTADO
            # ============================================================
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

            elapsed = (time.time() - start_time) * 1000
            self.logger.info(f"✅ {simbolo}: Análisis medio completado ({elapsed:.1f}ms)")
            self.logger.info(f"   ADX: {adx:.2f} | RSI: {rsi:.2f} | Pasa filtro: {pasa_filtro}")
            if soporte_cercano:
                self.logger.info(f"   Soporte: {soporte_cercano:.5f} ({distancia_soporte_pct:.2f}%, hits: {soporte_hits})")
            if resistencia_cercana:
                self.logger.info(f"   Resistencia: {resistencia_cercana:.5f} ({distancia_resistencia_pct:.2f}%, hits: {resistencia_hits})")

            return resultado

        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error en análisis medio: {e}", exc_info=True)
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
    # DETECCIÓN DE NIVELES V9.16 (CORREGIDO)
    # ============================================================

    def _detectar_niveles_v9_16(self, df: pd.DataFrame, simbolo: str,
                                precio_actual: float,
                                niveles_historicos: Optional[Dict]) -> Tuple[Optional[float], Optional[float], int, int]:
        """
        Detecta soporte y resistencia cercanos con validación de calidad.
        V9.16 - CORREGIDO: Menos estricto, funciona con cripto y metales.
        """
        soporte = None
        resistencia = None
        soporte_hits = 0
        resistencia_hits = 0

        # ✅ CORREGIDO: Mínimo 2 hits (antes 3)
        HITS_MINIMOS = 2

        # ✅ CORREGIDO: Distancia máxima 3% (antes 1%)
        DISTANCIA_MAXIMA_PCT = 3.0

        self.logger.debug(f"📊 {simbolo}: Detectando niveles con hits_min={HITS_MINIMOS}, dist_max={DISTANCIA_MAXIMA_PCT}%")

        # 1. Intentar usar NivelTracker (fuente principal)
        if self.nivel_tracker is not None:
            try:
                # ✅ CORREGIDO: Usar obtener_niveles() en lugar de obtener_niveles_validos()
                niveles = self.nivel_tracker.obtener_niveles(simbolo)

                self.logger.debug(f"📊 {simbolo}: Niveles del tracker: {len(niveles.get('soportes', []))} soportes, {len(niveles.get('resistencias', []))} resistencias")

                for s in niveles.get('soportes', []):
                    precio_s = s.get('precio', 0)
                    hits = s.get('hits', 0)

                    if precio_s > 0 and precio_s < precio_actual:
                        dist = (precio_actual - precio_s) / precio_actual * 100

                        # ✅ CORREGIDO: Menos estricto
                        if hits >= HITS_MINIMOS and dist < DISTANCIA_MAXIMA_PCT:
                            if soporte is None or hits > soporte_hits:
                                soporte = precio_s
                                soporte_hits = hits
                                self.logger.debug(f"📊 {simbolo}: Soporte del tracker: {precio_s:.5f} (hits: {hits}, dist: {dist:.2f}%)")

                for r in niveles.get('resistencias', []):
                    precio_r = r.get('precio', 0)
                    hits = r.get('hits', 0)

                    if precio_r > 0 and precio_r > precio_actual:
                        dist = (precio_r - precio_actual) / precio_actual * 100

                        if hits >= HITS_MINIMOS and dist < DISTANCIA_MAXIMA_PCT:
                            if resistencia is None or hits > resistencia_hits:
                                resistencia = precio_r
                                resistencia_hits = hits
                                self.logger.debug(f"📊 {simbolo}: Resistencia del tracker: {precio_r:.5f} (hits: {hits}, dist: {dist:.2f}%)")
            except Exception as e:
                self.logger.debug(f"Error obteniendo niveles del tracker: {e}")

        # 2. Fallback: detectar niveles locales (CORREGIDO PARA H1)
        if soporte is None or resistencia is None:
            try:
                window = 10  # ✅ AUMENTADO: Ventana más amplia para H1
                lookback = 100  # ✅ AUMENTADO: Buscar más velas en H1
                low = df['Low']
                high = df['High']

                # Buscar soportes (mínimos locales)
                for i in range(len(df) - lookback, len(df) - 2):
                    if low.iloc[i] == low.iloc[max(0, i-window):min(len(df), i+window)].min():
                        precio_s = low.iloc[i]
                        if precio_s < precio_actual:
                            dist = (precio_actual - precio_s) / precio_actual * 100
                            if dist < DISTANCIA_MAXIMA_PCT:
                                if soporte is None or dist < (precio_actual - soporte) / precio_actual * 100:
                                    soporte = precio_s
                                    soporte_hits = self._contar_hits_soporte(df, precio_s, precio_actual)

                # Buscar resistencias (máximos locales)
                for i in range(len(df) - lookback, len(df) - 2):
                    if high.iloc[i] == high.iloc[max(0, i-window):min(len(df), i+window)].max():
                        precio_r = high.iloc[i]
                        if precio_r > precio_actual:
                            dist = (precio_r - precio_actual) / precio_actual * 100
                            if dist < DISTANCIA_MAXIMA_PCT:
                                if resistencia is None or dist < (resistencia - precio_actual) / precio_actual * 100:
                                    resistencia = precio_r
                                    resistencia_hits = self._contar_hits_resistencia(df, precio_r, precio_actual)
            except Exception as e:
                self.logger.debug(f"Error en detección local de niveles: {e}")

        # 3. Último recurso: usar mínimos/máximos de ventana (CORREGIDO)
        if soporte is None:
            try:
                # ✅ CORREGIDO: Buscar en más velas
                min_reciente = df['Low'].iloc[-100:].min()
                dist = (precio_actual - min_reciente) / precio_actual * 100
                if dist < DISTANCIA_MAXIMA_PCT:
                    soporte = min_reciente
                    soporte_hits = 1
                    self.logger.debug(f"📊 {simbolo}: Soporte último recurso: {soporte:.5f} (dist: {dist:.2f}%)")
            except Exception:
                pass

        if resistencia is None:
            try:
                max_reciente = df['High'].iloc[-50:].max()
                dist = (max_reciente - precio_actual) / precio_actual * 100
                if dist < DISTANCIA_MAXIMA_PCT:
                    resistencia = max_reciente
                    resistencia_hits = 1
                    self.logger.debug(f"📊 {simbolo}: Resistencia último recurso: {resistencia:.5f} (dist: {dist:.2f}%)")
            except Exception:
                pass

        self.logger.info(f"📊 {simbolo}: NIVELES DETECTADOS - Soporte: {soporte}, Resistencia: {resistencia}")

        return soporte, resistencia, soporte_hits, resistencia_hits

    # ============================================================
    # CÁLCULO DE RSI CORREGIDO (V9.2)
    # ============================================================

    def _calcular_rsi_corregido(self, precios: pd.Series, simbolo: str, periodo: int = 14) -> float:
        """
        Calcula RSI con validación robusta (unificado con capas_rapido).
        """
        if precios is None:
            self.logger.warning(f"⚠️ {simbolo}: Serie de precios None, usando fallback 50.0")
            return 50.0

        if len(precios) < periodo:
            self.logger.warning(f"⚠️ {simbolo}: Insuficientes datos para RSI ({len(precios)} < {periodo}), usando fallback 50.0")
            return 50.0

        if precios.isna().all():
            self.logger.warning(f"⚠️ {simbolo}: Todos los precios son NaN, usando fallback 50.0")
            return 50.0

        if precios.nunique() == 1:
            self.logger.warning(f"⚠️ {simbolo}: Todos los precios iguales ({precios.iloc[0]:.5f}), usando fallback 50.0")
            return 50.0

        try:
            delta = precios.diff()

            if delta.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: Delta todo NaN, usando fallback 50.0")
                return 50.0

            ganancia = (delta.where(delta > 0, 0.0)).rolling(window=periodo).mean()
            perdida = (-delta.where(delta < 0, 0.0)).rolling(window=periodo).mean()

            if ganancia.isna().all() or perdida.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: Ganancia o pérdida todo NaN, usando fallback 50.0")
                return 50.0

            if perdida.iloc[-1] == 0:
                self.logger.debug(f"📊 {simbolo}: No hay pérdida en el último período, RSI = 100")
                return 100.0

            rs = ganancia / perdida
            rsi = 100.0 - (100.0 / (1.0 + rs))

            valor_final = rsi.iloc[-1]

            if pd.isna(valor_final):
                self.logger.warning(f"⚠️ {simbolo}: RSI resultó NaN, usando fallback 50.0")
                return 50.0

            if valor_final < 0 or valor_final > 100:
                self.logger.warning(f"⚠️ {simbolo}: RSI fuera de rango ({valor_final:.2f}), usando fallback 50.0")
                return 50.0

            self.logger.debug(f"📊 {simbolo}: RSI calculado correctamente: {valor_final:.2f}")
            return float(valor_final)

        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error en cálculo de RSI: {e}", exc_info=True)
            return 50.0

    # ============================================================
    # CÁLCULO DE ADX CORREGIDO (V9.2)
    # ============================================================

    def _calcular_adx_corregido(self, df: pd.DataFrame, simbolo: str, periodo: int = 14) -> float:
        """
        Calcula ADX con validación robusta para evitar saturación.
        """
        if df is None or len(df) < periodo:
            self.logger.warning(f"⚠️ {simbolo}: Insuficientes datos para ADX ({len(df)} < {periodo})")
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
            atr = tr.rolling(window=periodo).mean()

            # ✅ CORRECCIÓN V9.2: ATR seguro (evita división por cero)
            atr_seguro = atr.replace(0, np.nan)

            if atr_seguro.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: ATR todo NaN, ADX = 0")
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

            if plus_di.isna().all() or minus_di.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: plus_di o minus_di todo NaN, ADX = 0")
                return 0.0

            di_suma = plus_di + minus_di

            if di_suma.isna().all() or (di_suma == 0).all():
                self.logger.warning(f"⚠️ {simbolo}: di_suma todo 0 o NaN, ADX = 0")
                return 0.0

            di_suma_segura = di_suma.replace(0, np.nan)

            dx = 100 * (plus_di - minus_di).abs() / di_suma_segura
            adx = dx.rolling(periodo).mean().iloc[-1]

            if pd.isna(adx):
                self.logger.warning(f"⚠️ {simbolo}: ADX resultó NaN")
                return 0.0

            if adx < 0 or adx > 100:
                self.logger.warning(f"⚠️ {simbolo}: ADX fuera de rango ({adx:.2f}), forzando a 0")
                return 0.0

            return float(adx) if pd.notna(adx) else 0.0

        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error en cálculo de ADX: {e}", exc_info=True)
            return 0.0

    # ============================================================
    # CÁLCULO DE MACD CORREGIDO (V9.2)
    # ============================================================

    def _calcular_macd_corregido(self, precios: pd.Series, simbolo: str, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """
        Calcula MACD con validación de NaN.
        """
        if precios is None or len(precios) < slow:
            self.logger.warning(f"⚠️ {simbolo}: Insuficientes datos para MACD ({len(precios)} < {slow})")
            return {'macd': 0, 'signal': 0, 'histogram': 0}

        try:
            ema_fast = precios.ewm(span=fast, adjust=False).mean()
            ema_slow = precios.ewm(span=slow, adjust=False).mean()

            if ema_fast.isna().all() or ema_slow.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: EMAs todo NaN, MACD = 0")
                return {'macd': 0, 'signal': 0, 'histogram': 0}

            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            histogram = macd_line - signal_line

            macd_val = float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else 0
            signal_val = float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else 0
            hist_val = float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else 0

            return {
                'macd': macd_val,
                'signal': signal_val,
                'histogram': hist_val
            }

        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error en cálculo de MACD: {e}", exc_info=True)
            return {'macd': 0, 'signal': 0, 'histogram': 0}

    # ============================================================
    # CÁLCULO DE BOLLINGER CORREGIDO (V9.2)
    # ============================================================

    def _calcular_bollinger_corregido(self, precios: pd.Series, simbolo: str, periodo: int = 20, desviaciones: int = 2) -> Dict:
        """
        Calcula Bandas de Bollinger con validación de NaN.
        """
        if precios is None or len(precios) < periodo:
            self.logger.warning(f"⚠️ {simbolo}: Insuficientes datos para Bollinger ({len(precios)} < {periodo})")
            return {'upper': 0, 'middle': 0, 'lower': 0, 'width': 0}

        try:
            sma = precios.rolling(window=periodo).mean()
            std = precios.rolling(window=periodo).std()

            if sma.isna().all() or std.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: SMA o STD todo NaN, Bollinger = 0")
                return {'upper': 0, 'middle': 0, 'lower': 0, 'width': 0}

            upper = sma + (std * desviaciones)
            lower = sma - (std * desviaciones)
            middle = sma

            width = (upper.iloc[-1] - lower.iloc[-1]) / middle.iloc[-1] * 100 if middle.iloc[-1] > 0 else 0

            upper_val = float(upper.iloc[-1]) if not pd.isna(upper.iloc[-1]) else 0
            middle_val = float(middle.iloc[-1]) if not pd.isna(middle.iloc[-1]) else 0
            lower_val = float(lower.iloc[-1]) if not pd.isna(lower.iloc[-1]) else 0
            width_val = float(width) if not pd.isna(width) else 0

            return {
                'upper': upper_val,
                'middle': middle_val,
                'lower': lower_val,
                'width': width_val
            }

        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error en cálculo de Bollinger: {e}", exc_info=True)
            return {'upper': 0, 'middle': 0, 'lower': 0, 'width': 0}

    # ============================================================
    # CÁLCULO DE ATR
    # ============================================================

    def _calcular_atr(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """Calcula ATR en unidades de precio."""
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
    # GENERAR RAZÓN DE RECHAZO
    # ============================================================

    def _generar_razon_rechazo(self, simbolo: str, adx: float, adx_umbral: float,
                              en_nivel_clave: bool, tendencia_alineada: bool,
                              rsi: float, soporte_cercano: Optional[float],
                              resistencia_cercana: Optional[float],
                              distancia_soporte_pct: float,
                              distancia_resistencia_pct: float) -> str:
        """
        Genera una razón de rechazo estructurada y detallada.
        """
        detalles = []

        if not en_nivel_clave:
            detalles.append(f"no nivel clave")

        if not tendencia_alineada:
            detalles.append(f"tendencia no alineada (rsi={rsi:.0f})")

        if adx < adx_umbral:
            detalles.append(f"adx={adx:.0f} < {adx_umbral}")

        if not (rsi >= 65 or rsi <= 35):
            detalles.append(f"rsi={rsi:.0f} (no extremo)")

        razon = f"Condiciones insuficientes: {' | '.join(detalles)}"

        self.logger.info(f"📊 DIAGNÓSTICO {simbolo}: {razon}")
        self.logger.info(f"   🔧 SUGERENCIA: Ajustar adx_fuerte ({adx_umbral}) o distancia_nivel_max (3.0%)")

        return razon
    
    def _contar_hits_soporte(self, df: pd.DataFrame, precio: float, precio_actual: float) -> int:
        """Cuenta hits de soporte en el DataFrame."""
        hits = 0
        lookback = 100
        for i in range(max(0, len(df) - lookback), len(df) - 1):
            if df['Low'].iloc[i] <= precio * 1.001 and df['Low'].iloc[i] >= precio * 0.999:
                if df['Close'].iloc[i] > precio:
                    hits += 1
        return max(1, hits)

    def _contar_hits_resistencia(self, df: pd.DataFrame, precio: float, precio_actual: float) -> int:
        """Cuenta hits de resistencia en el DataFrame."""
        hits = 0
        lookback = 100
        for i in range(max(0, len(df) - lookback), len(df) - 1):
            if df['High'].iloc[i] >= precio * 0.999 and df['High'].iloc[i] <= precio * 1.001:
                if df['Close'].iloc[i] < precio:
                    hits += 1
        return max(1, hits)