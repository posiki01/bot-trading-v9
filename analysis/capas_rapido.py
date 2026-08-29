#!/usr/bin/env python3
"""
analysis/capas_rapido.py (V9.2 - CORREGIDO)
Capa 1: Análisis rápido - Filtro inicial de oportunidades.

CORRECCIONES V9.2:
- Logs de depuración para RSI
- Validación de suficiencia de datos antes de calcular
- Validación de NaN en el resultado
- Validación de DataFrame (columnas, no vacío)
- Manejo de excepciones específicas con logs claros
"""

import time
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

from analysis.capas import AnalisisRapido

logger = logging.getLogger('BotTrading.CapasRapido')


class AnalisisRapidoEngine:
    """
    Motor de análisis rápido (Capa 1).
    V9.2 - CORREGIDO: RSI con validación robusta.
    """
    
    def __init__(self,
                 umbrales: Dict[str, float],
                 config: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el motor de análisis rápido.
        
        Args:
            umbrales: Diccionario con umbrales
            config: Configuración
            modo_backtest: Modo backtest
        """
        self.umbrales = umbrales
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.CapasRapido')
    
    def ejecutar(self, df: pd.DataFrame, simbolo: str,
             precio_actual: Optional[float] = None) -> AnalisisRapido:
        """
        Ejecuta el análisis rápido.
        V9.2 - CORREGIDO: RSI robusto con logs.
        """
        start_time = time.time()
        
        try:
            if df is None or len(df) < 20:
                self.logger.warning(f"⚠️ {simbolo}: DataFrame insuficiente ({len(df) if df else 0} velas)")
                return AnalisisRapido(
                    valido=False, simbolo=simbolo,
                    precio_actual=0, precio_anterior=0,
                    cambio_vela_pct=0, volumen_relativo=0,
                    rsi=50, ema9=0, ema21=0,
                    tendencia_corta='LATERAL', atr=0,
                    pasa_filtro=False, razon_rechazo="Datos insuficientes"
                )
            
            # Validar columnas requeridas
            required_cols = ['Close']
            if not all(col in df.columns for col in required_cols):
                self.logger.warning(f"⚠️ {simbolo}: Columnas faltantes: {required_cols}")
                return AnalisisRapido(
                    valido=False, simbolo=simbolo,
                    precio_actual=0, precio_anterior=0,
                    cambio_vela_pct=0, volumen_relativo=0,
                    rsi=50, ema9=0, ema21=0,
                    tendencia_corta='LATERAL', atr=0,
                    pasa_filtro=False, razon_rechazo="Columnas faltantes"
                )
            
            # Precios
            precio_anterior = df['Close'].iloc[-2] if len(df) > 1 else df['Close'].iloc[-1]
            precio_cierre_actual = df['Close'].iloc[-1]
            
            # ✅ USAR PRECIO EN TIEMPO REAL SI ESTÁ DISPONIBLE
            if precio_actual and precio_actual > 0:
                precio_actual_usar = precio_actual
                cambio_vela_pct = (precio_actual_usar - precio_anterior) / precio_anterior * 100
                self.logger.debug(f"📊 {simbolo}: Usando precio en tiempo real: {precio_actual_usar:.5f}")
            else:
                precio_actual_usar = precio_cierre_actual
                cambio_vela_pct = (precio_cierre_actual - precio_anterior) / precio_anterior * 100
            
            # Volumen
            volumen_actual = df['Volume'].iloc[-1] if 'Volume' in df.columns else 0
            volumen_promedio = df['Volume'].rolling(20).mean().iloc[-1] if 'Volume' in df.columns and len(df) >= 20 else 1
            volumen_relativo = volumen_actual / volumen_promedio if volumen_promedio > 0 else 1
            
            # RSI (CORREGIDO V9.2)
            rsi = self._calcular_rsi_corregido(df['Close'], simbolo)
            
            # EMAs
            ema9 = df['Close'].ewm(span=9, adjust=False).mean().iloc[-1]
            ema21 = df['Close'].ewm(span=21, adjust=False).mean().iloc[-1]
            
            # Tendencia
            if ema9 > ema21 * 1.001:
                tendencia = 'ALCISTA'
            elif ema9 < ema21 * 0.999:
                tendencia = 'BAJISTA'
            else:
                tendencia = 'LATERAL'
            
            # ATR
            atr = self._calcular_atr(df)
            
            # Determinar si pasa el filtro
            pasa_filtro, razon_rechazo = self._evaluar_filtro(
                simbolo=simbolo,
                cambio_vela_pct=cambio_vela_pct,
                volumen_relativo=volumen_relativo,
                rsi=rsi,
                tendencia=tendencia,
                atr=atr,
                precio=precio_cierre_actual
            )
            
            resultado = AnalisisRapido(
                valido=True,
                simbolo=simbolo,
                precio_actual=precio_actual_usar,
                precio_anterior=precio_anterior,
                cambio_vela_pct=cambio_vela_pct,
                volumen_relativo=volumen_relativo,
                rsi=rsi,
                ema9=ema9,
                ema21=ema21,
                tendencia_corta=tendencia,
                atr=atr,
                volumen_ok=volumen_relativo >= self.umbrales.get('volumen_minimo', 0.10),
                rsi_extremo=rsi >= self.umbrales.get('rsi_extremo_superior', 80) or rsi <= self.umbrales.get('rsi_extremo_inferior', 20),
                tendencia_fuerte=tendencia != 'LATERAL',
                pasa_filtro=pasa_filtro,
                razon_rechazo=razon_rechazo
            )
            
            return resultado
            
        except Exception as e:
            self.logger.error(f"❌ Error en análisis rápido {simbolo}: {e}")
            return AnalisisRapido(
                valido=False, simbolo=simbolo,
                precio_actual=0, precio_anterior=0,
                cambio_vela_pct=0, volumen_relativo=0,
                rsi=50, ema9=0, ema21=0,
                tendencia_corta='LATERAL', atr=0,
                pasa_filtro=False, razon_rechazo=f"Error: {e}"
            )
    
    # ============================================================
    # CÁLCULO DE RSI CORREGIDO (V9.2)
    # ============================================================
    
    def _calcular_rsi_corregido(self, precios: pd.Series, simbolo: str, periodo: int = 14) -> float:
        """
        Calcula RSI con validación robusta y logs de depuración.
        V9.2 - CORREGIDO: Logs, validación de NaN, fallback controlado.
        
        Args:
            precios: Serie de precios de cierre
            simbolo: Símbolo (para logs)
            periodo: Período para el cálculo
        
        Returns:
            Valor RSI (0-100) o 50.0 si falla
        """
        # 1. Validación de datos básica
        if precios is None:
            self.logger.warning(f"⚠️ {simbolo}: Serie de precios None, usando fallback 50.0")
            return 50.0
        
        if len(precios) < periodo:
            self.logger.warning(f"⚠️ {simbolo}: Insuficientes datos para RSI ({len(precios)} < {periodo}), usando fallback 50.0")
            return 50.0
        
        # 2. Validación de que no esté vacía o con todos los valores iguales
        if precios.isna().all():
            self.logger.warning(f"⚠️ {simbolo}: Todos los precios son NaN, usando fallback 50.0")
            return 50.0
        
        if precios.nunique() == 1:
            self.logger.warning(f"⚠️ {simbolo}: Todos los precios iguales ({precios.iloc[0]:.5f}), usando fallback 50.0")
            return 50.0
        
        try:
            # 3. Cálculo estándar de RSI
            delta = precios.diff()
            
            # Validar que delta no esté todo NaN
            if delta.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: Delta todo NaN, usando fallback 50.0")
                return 50.0
            
            ganancia = (delta.where(delta > 0, 0.0)).rolling(window=periodo).mean()
            perdida = (-delta.where(delta < 0, 0.0)).rolling(window=periodo).mean()
            
            # Validar que ganancia y perdida no sean todo NaN
            if ganancia.isna().all() or perdida.isna().all():
                self.logger.warning(f"⚠️ {simbolo}: Ganancia o pérdida todo NaN, usando fallback 50.0")
                return 50.0
            
            # Validar que no hay división por cero
            if perdida.iloc[-1] == 0:
                # Si no hay pérdida, RSI = 100
                self.logger.debug(f"📊 {simbolo}: No hay pérdida en el último período, RSI = 100")
                return 100.0
            
            rs = ganancia / perdida
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
            # 4. Validar que el resultado no sea NaN
            valor_final = rsi.iloc[-1]
            
            if pd.isna(valor_final):
                self.logger.warning(f"⚠️ {simbolo}: RSI resultó NaN, usando fallback 50.0")
                return 50.0
            
            # 5. Validar que el resultado esté en rango válido (0-100)
            if valor_final < 0 or valor_final > 100:
                self.logger.warning(f"⚠️ {simbolo}: RSI fuera de rango ({valor_final:.2f}), usando fallback 50.0")
                return 50.0
            
            # 6. Log de éxito (solo en modo depuración)
            self.logger.debug(f"📊 {simbolo}: RSI calculado correctamente: {valor_final:.2f}")
            
            return float(valor_final)
            
        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error en cálculo de RSI: {e}", exc_info=True)
            return 50.0
    
    # ============================================================
    # CÁLCULO DE ATR
    # ============================================================
    
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
    # EVALUACIÓN DEL FILTRO
    # ============================================================
    
    def _evaluar_filtro(self, simbolo: str, cambio_vela_pct: float,
                        volumen_relativo: float, rsi: float,
                        tendencia: str, atr: float, precio: float) -> tuple:
        # Detectar horario
        from datetime import datetime, timezone
        ahora = datetime.now(timezone.utc)
        hora_utc = ahora.hour + ahora.minute / 60.0
        
        es_asiatico = 0 <= hora_utc <= 7
        es_overlap = 12 <= hora_utc <= 16
        
        # Umbrales dinámicos
        if es_asiatico:
            umbral_movimiento = 0.005
            vol_min = 0.08
            rsi_extremo_superior = 85
            rsi_extremo_inferior = 15
        elif es_overlap:
            umbral_movimiento = 0.015
            vol_min = 0.05
            rsi_extremo_superior = 80
            rsi_extremo_inferior = 20
        else:
            umbral_movimiento = 0.005
            vol_min = 0.08
            rsi_extremo_superior = 80
            rsi_extremo_inferior = 20
        
        # Ajustes por tipo de activo
        simbolo_upper = simbolo.upper()
        es_indice = any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500'])
        es_cripto = any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL'])
        es_baja_volatilidad = simbolo_upper in ['EURGBP', 'EURCHF', 'GBPCHF', 'USDCHF']
        
        if es_indice:
            umbral_movimiento = max(0.010, umbral_movimiento * 0.7)
        elif es_cripto:
            umbral_movimiento = max(0.015, umbral_movimiento * 0.8)
        elif es_baja_volatilidad:
            umbral_movimiento = max(0.005, umbral_movimiento * 0.5)
        
        if self.modo_backtest:
            umbral_movimiento = max(0.005, umbral_movimiento * 0.5)
            vol_min = max(0.02, vol_min * 0.3)
            rsi_extremo_superior = 90
            rsi_extremo_inferior = 10
        
        # Evaluar condiciones
        hay_movimiento = abs(cambio_vela_pct) >= umbral_movimiento
        volumen_suficiente = volumen_relativo >= vol_min
        rsi_interesante = rsi >= rsi_extremo_superior or rsi <= rsi_extremo_inferior
        tendencia_definida = tendencia != 'LATERAL'
        atr_movimiento = abs(cambio_vela_pct) >= (atr / precio * 100 * 0.5) if atr > 0 and precio > 0 else False
        
        condiciones_cumplidas = sum([
            hay_movimiento,
            volumen_suficiente,
            rsi_interesante,
            tendencia_definida,
            atr_movimiento
        ])
        
        if es_asiatico or es_baja_volatilidad:
            umbral_condiciones = 1
        else:
            umbral_condiciones = 2
        
        if self.modo_backtest:
            umbral_condiciones = 1
        
        if condiciones_cumplidas < umbral_condiciones:
            razon = self._generar_razon_rechazo(
                simbolo=simbolo,
                condiciones_cumplidas=condiciones_cumplidas,
                umbral_condiciones=umbral_condiciones,
                hay_movimiento=hay_movimiento,
                volumen_suficiente=volumen_suficiente,
                rsi_interesante=rsi_interesante,
                tendencia_definida=tendencia_definida,
                atr_movimiento=atr_movimiento,
                cambio_vela_pct=cambio_vela_pct,
                umbral_movimiento=umbral_movimiento,
                volumen_relativo=volumen_relativo,
                vol_min=vol_min,
                rsi=rsi,
                rsi_extremo_superior=rsi_extremo_superior,
                rsi_extremo_inferior=rsi_extremo_inferior,
                tendencia=tendencia,
                atr=atr,
                precio=precio
            )
            return False, razon
        
        return True, "OK"
    
    def _generar_razon_rechazo(self, simbolo: str, condiciones_cumplidas: int,
                              umbral_condiciones: int, hay_movimiento: bool,
                              volumen_suficiente: bool, rsi_interesante: bool,
                              tendencia_definida: bool, atr_movimiento: bool,
                              cambio_vela_pct: float, umbral_movimiento: float,
                              volumen_relativo: float, vol_min: float,
                              rsi: float, rsi_extremo_superior: float,
                              rsi_extremo_inferior: float, tendencia: str,
                              atr: float, precio: float) -> str:
        """
        Genera una razón de rechazo estructurada y detallada.
        """
        detalles = []
        
        if not hay_movimiento:
            detalles.append(f"mov={cambio_vela_pct:.2f}% < {umbral_movimiento*100:.1f}%")
        
        if not volumen_suficiente:
            detalles.append(f"vol={volumen_relativo:.2f}x < {vol_min:.2f}x")
        
        if not rsi_interesante:
            detalles.append(f"rsi={rsi:.0f} ({rsi_extremo_inferior}-{rsi_extremo_superior})")
        
        if not tendencia_definida:
            detalles.append(f"tendencia={tendencia}")
        
        if not atr_movimiento:
            detalles.append(f"atr_mov={cambio_vela_pct:.2f}% < {atr/precio*100*0.5:.2f}%")
        
        razon = f"Condiciones insuficientes: {condiciones_cumplidas}/{umbral_condiciones} | "
        razon += " | ".join(detalles)
        
        # ✅ LOG DE DIAGNÓSTICO
        self.logger.info(f"📊 DIAGNÓSTICO {simbolo}: {razon}")
        self.logger.info(f"   🔧 SUGERENCIA: Ajustar umbral_movimiento ({umbral_movimiento*100:.1f}%) o vol_min ({vol_min:.2f}x)")
        
        return razon