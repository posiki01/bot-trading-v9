#!/usr/bin/env python3
"""
analysis/capas_rapido.py (V9.0)
Capa 1: Análisis rápido - Filtro inicial de oportunidades.
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
    V9.0 - INDEPENDIENTE.
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
        
        Args:
            df: DataFrame con datos
            simbolo: Símbolo
            precio_actual: Precio actual (opcional)
        
        Returns:
            AnalisisRapido
        """
        start_time = time.time()
        
        try:
            if df is None or len(df) < 20:
                return AnalisisRapido(
                    valido=False, simbolo=simbolo,
                    precio_actual=0, precio_anterior=0,
                    cambio_vela_pct=0, volumen_relativo=0,
                    rsi=50, ema9=0, ema21=0,
                    tendencia_corta='LATERAL', atr=0,
                    pasa_filtro=False, razon_rechazo="Datos insuficientes"
                )
            
            # Precios
            precio_anterior = df['Close'].iloc[-2] if len(df) > 1 else df['Close'].iloc[-1]
            precio_cierre_actual = df['Close'].iloc[-1]
            
            if precio_actual and precio_actual > 0:
                precio_actual_usar = precio_actual
            else:
                precio_actual_usar = precio_cierre_actual
            
            # Cambio de vela
            cambio_vela_pct = (precio_cierre_actual - precio_anterior) / precio_anterior * 100 if precio_anterior > 0 else 0
            
            # Volumen
            volumen_actual = df['Volume'].iloc[-1] if 'Volume' in df.columns else 0
            volumen_promedio = df['Volume'].rolling(20).mean().iloc[-1] if 'Volume' in df.columns and len(df) >= 20 else 1
            volumen_relativo = volumen_actual / volumen_promedio if volumen_promedio > 0 else 1
            
            # RSI
            rsi = self._calcular_rsi(df['Close'])
            
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
        """
        Evalúa si el símbolo pasa el filtro rápido.
        
        Returns:
            (pasa_filtro, razon_rechazo)
        """
        # Detectar horario
        from datetime import datetime, timezone
        ahora = datetime.now(timezone.utc)
        hora_utc = ahora.hour + ahora.minute / 60.0
        
        es_asiatico = 0 <= hora_utc <= 7
        es_overlap = 12 <= hora_utc <= 16
        
        # Umbrales dinámicos
        if es_asiatico:
            umbral_movimiento = 0.006
            vol_min = 0.03
            rsi_extremo_superior = 85
            rsi_extremo_inferior = 15
        elif es_overlap:
            umbral_movimiento = 0.035
            vol_min = 0.05
            rsi_extremo_superior = 75
            rsi_extremo_inferior = 25
        else:
            umbral_movimiento = 0.020
            vol_min = 0.10
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
        
        # Evaluar condiciones
        hay_movimiento = abs(cambio_vela_pct) >= umbral_movimiento
        volumen_suficiente = volumen_relativo >= vol_min
        rsi_interesante = rsi >= rsi_extremo_superior or rsi <= rsi_extremo_inferior
        tendencia_definida = tendencia != 'LATERAL'
        atr_movimiento = abs(cambio_vela_pct) >= (atr / precio * 100 * 0.5) if atr > 0 and precio > 0 else False
        
        # Contar condiciones cumplidas
        condiciones_cumplidas = sum([
            hay_movimiento,
            volumen_suficiente,
            rsi_interesante,
            tendencia_definida,
            atr_movimiento
        ])
        
        # Umbral de condiciones según horario
        if es_asiatico or es_baja_volatilidad:
            umbral_condiciones = 1
        else:
            umbral_condiciones = 2
        
        if condiciones_cumplidas >= umbral_condiciones:
            return True, "OK"
        else:
            razon = (f"Sin condiciones: mov ({cambio_vela_pct:.2f}%), "
                    f"vol ({volumen_relativo:.2f}x), RSI ({rsi:.0f}), "
                    f"tendencia {tendencia} | Condiciones: {condiciones_cumplidas}/{umbral_condiciones}")
            return False, razon