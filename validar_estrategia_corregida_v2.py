#!/usr/bin/env python3
"""
validar_estrategia_corregida_v2.py (V5.1 - PnL GARANTIZADO)
Validación con cálculo de PnL que SIEMPRE funciona.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging
import json
import sys
import os
import time
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s'
)
logger = logging.getLogger('ValidarEstrategiaCorregidaV2')

sys.path.insert(0, str(Path(__file__).parent))


class SimuladorCorregidoV2:
    """Simulador con PnL garantizado."""
    
    def __init__(self, capital_inicial: float = 1000.0,
                 riesgo_pct: float = 0.01,
                 modo_backtest: bool = True):
        
        self.capital_inicial = capital_inicial
        self.riesgo_pct = riesgo_pct
        self.modo_backtest = modo_backtest
        
        self.logger = logging.getLogger('ValidarCorregidaV2.Simulador')
        
        self.operaciones = []
        self.rechazos = []
        self.modos_utilizados = {}
        self.modulos_disponibles = False
        
        self._inicializar_modulos()
    
    def _inicializar_modulos(self):
        """Inicializa módulos del bot."""
        try:
            from analysis.capas import AnalisisPorCapas
            from analysis.regimen import MarketRegimeFilter
            from trading.modos import ModoSelector
            from trading.timer import EntryTimer
            from trading.stops import GestorStops
            from trading.sniper.sniper_checklist import SniperChecklist
            
            self.analisis_capas = AnalisisPorCapas(modo_backtest=True)
            self.regimen_filter = MarketRegimeFilter(modo_backtest=True)
            self.modo_selector = ModoSelector(modo_backtest=True)
            self.entry_timer = EntryTimer(modo_backtest=True)
            self.gestor_stops = GestorStops(modo_backtest=True)
            self.sniper = SniperChecklist(
                pipeline=None,
                analisis_capas=self.analisis_capas,
                modo_selector=self.modo_selector,
                entry_timer=self.entry_timer,
                gestor_stops=self.gestor_stops,
                modo_backtest=True
            )
            
            self.modulos_disponibles = True
            self.logger.info("✅ Módulos del bot inicializados")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error inicializando módulos: {e}")
            self.modulos_disponibles = False
    
    # ============================================================
    # ✅ CORRECCIÓN CRÍTICA: VALOR DE PIP GARANTIZADO
    # ============================================================
    
    def _obtener_valor_pip_usd(self, simbolo: str, lotes: float) -> float:
        """
        Obtiene el valor de 1 pip en USD para la posición.
        ✅ SIEMPRE retorna un valor > 0
        """
        simbolo_upper = simbolo.upper()
        
        # ✅ MAPA DE VALORES POR TIPO DE ACTIVO (valor por 1 lote)
        VALORES_PIP = {
            'FOREX': 10.0,      # EURUSD, GBPUSD, etc.
            'FOREX_JPY': 8.5,   # USDJPY, EURJPY, etc.
            'XAU': 0.10,        # Oro: $0.10 por pip por 0.01 lotes
            'XAG': 5.0,         # Plata
            'INDICES': 1.0,     # US30, NAS100, US500
            'CRIPTO': 1.0,      # BTCUSD, ETHUSD, SOLUSD
        }
        
        # Determinar tipo
        if 'JPY' in simbolo_upper:
            valor_base = VALORES_PIP['FOREX_JPY']
        elif 'XAU' in simbolo_upper:
            valor_base = VALORES_PIP['XAU']
        elif 'XAG' in simbolo_upper:
            valor_base = VALORES_PIP['XAG']
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            valor_base = VALORES_PIP['INDICES']
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            valor_base = VALORES_PIP['CRIPTO']
        else:
            valor_base = VALORES_PIP['FOREX']
        
        # ✅ VALOR PARA LA POSICIÓN
        valor = lotes * valor_base
        
        # ✅ GARANTIZAR QUE NUNCA SEA 0
        if valor <= 0:
            self.logger.warning(f"⚠️ Valor pip calculado como 0 para {simbolo}, usando fallback")
            valor = lotes * 10.0
        
        return valor
    
    def _obtener_pip_val(self, simbolo: str) -> float:
        """Obtiene pip_val para el símbolo."""
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.10
        if 'XAG' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001
    
    # ============================================================
    # ✅ CÁLCULO DE LOTES REALISTA
    # ============================================================
    
    def _calcular_lotes_realistas(self, simbolo: str, capital: float,
                                   entry: float, sl: float,
                                   riesgo_pct: float = 0.01) -> Tuple[float, float]:
        """Calcula lotes basado en riesgo real."""
        if capital <= 0 or entry <= 0 or sl <= 0:
            return 0.0, 0.0
        
        sl_dist = abs(entry - sl)
        pip_val = self._obtener_pip_val(simbolo)
        
        if sl_dist <= 0 or pip_val <= 0:
            return 0.01, 0.01  # ✅ Fallback a lote mínimo
        
        sl_pips = sl_dist / pip_val
        
        # ✅ Obtener valor de 1 pip para 1 lote
        valor_pip_1_lote = self._obtener_valor_pip_usd(simbolo, 1.0)
        
        # ✅ Calcular lotes
        riesgo_dinero = capital * riesgo_pct
        lotes = riesgo_dinero / (sl_pips * valor_pip_1_lote) if sl_pips > 0 and valor_pip_1_lote > 0 else 0.01
        
        # ✅ Limitar
        lote_min = 0.01
        lote_max = self._obtener_lote_maximo(simbolo, capital)
        
        lotes = max(lote_min, min(lote_max, lotes))
        lotes = round(lotes / 0.01) * 0.01
        
        # ✅ Calcular riesgo real
        riesgo_real = (lotes * sl_pips * valor_pip_1_lote) / capital * 100
        
        return lotes, riesgo_real
    
    def _obtener_lote_maximo(self, simbolo: str, capital: float) -> float:
        """Obtiene el lote máximo permitido."""
        simbolo_upper = simbolo.upper()
        
        if 'XAU' in simbolo_upper:
            return 0.10
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 0.10
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 0.05
        else:
            return 0.50
    
    # ============================================================
    # ✅ SIMULACIÓN DE OPERACIÓN CON PnL CORRECTO
    # ============================================================
    
    def _simular_operacion_realista(self, df: pd.DataFrame, index: int,
                                     precio_entrada: float, sl: float, tp: float,
                                     direccion: str, lotes: float, simbolo: str) -> Dict:
        """
        Simula operación con cálculo REAL de PnL.
        ✅ CORREGIDO: Usa valor real del pip.
        """
        # Validar SL/TP
        if direccion == 'COMPRA':
            if sl >= precio_entrada or tp <= precio_entrada:
                return {'pnl': 0.0, 'resultado': 'INVALIDO', 'bars_held': 0}
        else:
            if sl <= precio_entrada or tp >= precio_entrada:
                return {'pnl': 0.0, 'resultado': 'INVALIDO', 'bars_held': 0}
        
        max_bars = 100
        pip_val = self._obtener_pip_val(simbolo)
        
        # ✅ OBTENER VALOR DEL PIP (SIEMPRE > 0)
        valor_pip_usd = self._obtener_valor_pip_usd(simbolo, lotes)
        
        # ✅ LOG DE DEPURACIÓN (solo primeros 5)
        if len(self.operaciones) < 5:
            self.logger.info(f"🔍 {simbolo}: pip_val={pip_val}, valor_pip_usd={valor_pip_usd:.4f}, lotes={lotes:.3f}")
        
        for j in range(index + 1, min(len(df), index + max_bars + 1)):
            try:
                high = df['High'].iloc[j]
                low = df['Low'].iloc[j]
            except Exception:
                continue
            
            if direccion == 'COMPRA':
                if low <= sl:
                    pips_movidos = (sl - precio_entrada) / pip_val if pip_val > 0 else 0
                    pnl = pips_movidos * valor_pip_usd
                    return {'pnl': pnl, 'resultado': 'SL', 'bars_held': j - index}
                if high >= tp:
                    pips_movidos = (tp - precio_entrada) / pip_val if pip_val > 0 else 0
                    pnl = pips_movidos * valor_pip_usd
                    return {'pnl': pnl, 'resultado': 'TP', 'bars_held': j - index}
            else:
                if high >= sl:
                    pips_movidos = (precio_entrada - sl) / pip_val if pip_val > 0 else 0
                    pnl = pips_movidos * valor_pip_usd
                    return {'pnl': pnl, 'resultado': 'SL', 'bars_held': j - index}
                if low <= tp:
                    pips_movidos = (precio_entrada - tp) / pip_val if pip_val > 0 else 0
                    pnl = pips_movidos * valor_pip_usd
                    return {'pnl': pnl, 'resultado': 'TP', 'bars_held': j - index}
        
        # Timeout
        precio_final = df['Close'].iloc[min(len(df) - 1, index + max_bars)]
        if direccion == 'COMPRA':
            pips_movidos = (precio_final - precio_entrada) / pip_val if pip_val > 0 else 0
        else:
            pips_movidos = (precio_entrada - precio_final) / pip_val if pip_val > 0 else 0
        
        pnl = pips_movidos * valor_pip_usd
        
        return {'pnl': pnl, 'resultado': 'TIMEOUT', 'bars_held': max_bars}
    
    # ============================================================
    # MÉTODOS DE DIRECCIÓN Y SIMULACIÓN
    # ============================================================
    
    def _determinar_direccion(self, medio, pesado, regimen) -> str:
        """Determina dirección."""
        if medio is None:
            return 'NEUTRAL'
        
        bullish = 0
        bearish = 0
        
        if medio.rsi > 55:
            bullish += 1
        elif medio.rsi < 45:
            bearish += 1
        
        if medio.macd_histogram > 0:
            bullish += 1
        elif medio.macd_histogram < 0:
            bearish += 1
        
        if medio.adx > 25:
            if medio.sma20 > medio.sma50:
                bullish += 2
            else:
                bearish += 2
        
        if pesado:
            if pesado.divergencia_rsi == 'BULLISH':
                bullish += 2
            elif pesado.divergencia_rsi == 'BEARISH':
                bearish += 2
        
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            bullish += 2
        elif regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            bearish += 2
        
        if bullish > bearish + 1:
            return 'COMPRA'
        elif bearish > bullish + 1:
            return 'VENTA'
        return 'NEUTRAL'
    
    def _calcular_sl_fallback(self, precio: float, medio, direccion: str) -> float:
        """Calcula SL fallback."""
        if medio is None:
            atr = 0.001
        else:
            atr = medio.atr if hasattr(medio, 'atr') else 0.001
        
        if direccion == 'COMPRA':
            return precio - (atr * 1.5)
        else:
            return precio + (atr * 1.5)
    
    def _calcular_tp_fallback(self, precio: float, medio, direccion: str) -> float:
        """Calcula TP fallback."""
        if medio is None:
            atr = 0.001
        else:
            atr = medio.atr if hasattr(medio, 'atr') else 0.001
        
        if direccion == 'COMPRA':
            return precio + (atr * 2.5)
        else:
            return precio - (atr * 2.5)
    
    # ============================================================
    # SIMULACIÓN PRINCIPAL
    # ============================================================
    
    def simular(self, dataframes: Dict[int, pd.DataFrame], 
                simbolo: str) -> Dict:
        """Simula la estrategia completa."""
        
        if 60 not in dataframes:
            return self._resultado_vacio(simbolo, 'Sin datos H1')
        
        df_h1 = dataframes[60]
        df_m5 = dataframes.get(5)
        df_h4 = dataframes.get(240)
        df_d1 = dataframes.get(1440)
        
        if len(df_h1) < 100:
            return self._resultado_vacio(simbolo, f'Datos insuficientes')
        
        self.logger.info(f"📊 Simulando {simbolo} con {len(df_h1)} velas H1")
        
        if df_m5 is None:
            self.logger.warning("⚠️ SIN M5 - Usando fallback H1")
        
        capital = self.capital_inicial
        operaciones = []
        rechazos = []
        modos_utilizados = {}
        
        max_velas = min(len(df_h1) - 10, 3000)
        
        self.logger.info(f"📊 Analizando {max_velas - 100} velas")
        
        if not self.modulos_disponibles:
            return self._simular_simplificado(df_h1, simbolo)
        
        for i in range(100, max_velas):
            try:
                df_h1_slice = df_h1.iloc[:i+1].copy()
                precio_actual = df_h1_slice['Close'].iloc[-1]
                fecha_actual = df_h1_slice.index[-1]
                
                # Obtener H4 y D1
                df_h4_slice = None
                if df_h4 is not None:
                    idx_h4 = df_h4.index.get_indexer([fecha_actual], method='ffill')[0]
                    if idx_h4 >= 0:
                        df_h4_slice = df_h4.iloc[:idx_h4+1].copy()
                
                df_d1_slice = None
                if df_d1 is not None:
                    idx_d1 = df_d1.index.get_indexer([fecha_actual], method='ffill')[0]
                    if idx_d1 >= 0:
                        df_d1_slice = df_d1.iloc[:idx_d1+1].copy()
                
                # 1. Análisis Rápido
                try:
                    rapido = self.analisis_capas.analisis_rapido(df_h1_slice, simbolo, precio_actual)
                except Exception:
                    continue
                
                if not rapido.pasa_filtro:
                    rechazos.append({'fecha': fecha_actual, 'razon': 'Rápido falló', 'etapa': 'RAPIDO'})
                    continue
                
                # 2. Niveles
                try:
                    from analysis.niveles import NivelTracker
                    tracker = NivelTracker(modo_backtest=True)
                    niveles = tracker.detectar_y_actualizar_niveles(
                        simbolo=simbolo,
                        df=df_h1_slice,
                        precio_actual=precio_actual
                    )
                except Exception:
                    niveles = {'soportes': [], 'resistencias': []}
                
                # 3. Análisis Medio
                try:
                    medio = self.analisis_capas.analisis_medio(df_h1_slice, simbolo, rapido, niveles)
                except Exception:
                    continue
                
                if medio is None or not medio.pasa_filtro:
                    rechazos.append({'fecha': fecha_actual, 'razon': 'Medio falló', 'etapa': 'MEDIO'})
                    continue
                
                # 4. Análisis Pesado
                try:
                    pesado = self.analisis_capas.analisis_pesado(
                        df_h1_slice, simbolo, df_h4_slice, df_d1_slice, niveles, medio
                    )
                except Exception:
                    continue
                
                # 5. Score H1
                try:
                    from analysis.scoring import ScoreEngine
                    score_engine = ScoreEngine(modo_backtest=True)
                    score_h1 = score_engine.calcular_score_h1(
                        score_estructura=pesado.score_estructura,
                        score_momentum=pesado.score_momentum,
                        score_confluencia=pesado.score_confluencia,
                        score_institucional=pesado.score_institucional,
                        simbolo=simbolo
                    ).score
                except Exception:
                    score_h1 = 50
                
                # 6. Régimen
                try:
                    regimen_data = self.regimen_filter.clasificar(simbolo, df_h4_slice, df_h1_slice)
                    regimen = regimen_data.regimen.value
                except Exception:
                    regimen = 'INCERTO'
                
                # 7. Dirección
                direccion = self._determinar_direccion(medio, pesado, regimen)
                
                if direccion == 'NEUTRAL':
                    rechazos.append({'fecha': fecha_actual, 'razon': 'NEUTRAL', 'etapa': 'DIRECCION'})
                    continue
                
                # 8. Seleccionar Modo
                try:
                    modo_obj, razon_modo, _ = self.modo_selector.seleccionar_modo(
                        simbolo=simbolo,
                        regimen=regimen,
                        direccion=direccion,
                        score_h1=score_h1,
                        nivel_usado=medio.soporte_cercano if direccion == 'COMPRA' else medio.resistencia_cercana,
                        en_nivel_clave=medio.en_nivel_clave,
                        volumen_relativo=rapido.volumen_relativo,
                        patron_calidad=pesado.calidad_patron if pesado else 0
                    )
                except Exception:
                    modo_obj = None
                
                if modo_obj is None:
                    rechazos.append({'fecha': fecha_actual, 'razon': 'Sin modo', 'etapa': 'MODO'})
                    continue
                
                modo = modo_obj.value
                
                # 9. Preparar contexto H1
                contexto_h1 = {
                    'score': score_h1,
                    'regimen': regimen,
                    'direccion': direccion,
                    'en_nivel_clave': medio.en_nivel_clave,
                    'soporte_cercano': medio.soporte_cercano,
                    'resistencia_cercana': medio.resistencia_cercana,
                    'soporte_hits': medio.soporte_hits,
                    'resistencia_hits': medio.resistencia_hits,
                    'adx': medio.adx,
                    'rsi': medio.rsi,
                    'patron_principal': pesado.patron_principal if pesado else None,
                    'niveles': niveles,
                }
                
                # 10. Sniper
                resultado_sniper = None
                df_m5_slice = None
                
                if df_m5 is not None:
                    idx_m5 = df_m5.index.get_indexer([fecha_actual], method='ffill')[0]
                    if idx_m5 >= 0:
                        df_m5_slice = df_m5.iloc[:idx_m5+1].copy()
                
                if df_m5_slice is not None and len(df_m5_slice) > 20:
                    try:
                        resultado_sniper = self.sniper.evaluar_sniper_optimizado(
                            simbolo=simbolo,
                            df_m5=df_m5_slice,
                            precio_actual=precio_actual,
                            direccion=direccion,
                            estado_pipeline=None,
                            analisis_rapido=rapido,
                            analisis_medio=medio,
                            ejecutar_pesado=False,
                            contexto_h1=contexto_h1,
                            calidad_horario='REGULAR'
                        )
                    except Exception:
                        resultado_sniper = None
                
                # 11. Fallback
                if resultado_sniper is None:
                    sl = self._calcular_sl_fallback(precio_actual, medio, direccion)
                    tp = self._calcular_tp_fallback(precio_actual, medio, direccion)
                    resultado_sniper = {'sl': sl, 'tp': tp, 'modo': modo, 'score': score_h1}
                
                # 12. Ejecutar operación
                sl = resultado_sniper.get('sl', 0)
                tp = resultado_sniper.get('tp', 0)
                
                if sl > 0 and tp > 0:
                    # ✅ Calcular lotes
                    lotes, riesgo_real = self._calcular_lotes_realistas(
                        simbolo=simbolo,
                        capital=capital,
                        entry=precio_actual,
                        sl=sl,
                        riesgo_pct=self.riesgo_pct
                    )
                    
                    if lotes > 0:
                        # ✅ Simular operación
                        resultado_op = self._simular_operacion_realista(
                            df=df_h1_slice,
                            index=i,
                            precio_entrada=precio_actual,
                            sl=sl,
                            tp=tp,
                            direccion=direccion,
                            lotes=lotes,
                            simbolo=simbolo
                        )
                        
                        op = {
                            'fecha': fecha_actual,
                            'direccion': direccion,
                            'modo': modo,
                            'regimen': regimen,
                            'score': score_h1,
                            'precio_entrada': precio_actual,
                            'sl': sl,
                            'tp': tp,
                            'lotes': lotes,
                            'sl_pips': abs(precio_actual - sl) / self._obtener_pip_val(simbolo) if self._obtener_pip_val(simbolo) > 0 else 0,
                            'tp_pips': abs(tp - precio_actual) / self._obtener_pip_val(simbolo) if self._obtener_pip_val(simbolo) > 0 else 0,
                            'rr': abs(tp - precio_actual) / abs(precio_actual - sl) if abs(precio_actual - sl) > 0 else 0,
                            'pnl': resultado_op['pnl'],
                            'resultado': resultado_op['resultado'],
                            'bars_held': resultado_op['bars_held'],
                        }
                        
                        operaciones.append(op)
                        capital += op['pnl']
                        modos_utilizados[modo] = modos_utilizados.get(modo, 0) + 1
                        
                        # ✅ Log con PnL real
                        self.logger.info(f"🎯 OP #{len(operaciones)}: {direccion} {modo} | Lotes: {lotes:.3f} | PnL: ${op['pnl']:.2f} | {resultado_op['resultado']}")
                
            except Exception as e:
                self.logger.debug(f"Error: {e}")
                continue
        
        self.logger.info(f"📊 Simulación completada: {len(operaciones)} ops, {len(rechazos)} rechazos")
        
        self.operaciones = operaciones
        self.rechazos = rechazos
        self.modos_utilizados = modos_utilizados
        
        return self._calcular_metricas(simbolo)
    
    def _simular_simplificado(self, df_h1: pd.DataFrame, simbolo: str) -> Dict:
        """Versión simplificada."""
        close = df_h1['Close']
        capital = self.capital_inicial
        operaciones = []
        
        for i in range(50, len(df_h1) - 10):
            try:
                ema9 = close.ewm(span=9, adjust=False).mean().iloc[i]
                ema21 = close.ewm(span=21, adjust=False).mean().iloc[i]
                precio = close.iloc[i]
                
                if ema9 > ema21 * 1.001:
                    direccion = 'COMPRA'
                elif ema9 < ema21 * 0.999:
                    direccion = 'VENTA'
                else:
                    continue
                
                atr = self._calcular_atr_simple(df_h1.iloc[:i+1])
                sl = precio - (atr * 1.5) if direccion == 'COMPRA' else precio + (atr * 1.5)
                tp = precio + (atr * 2.5) if direccion == 'COMPRA' else precio - (atr * 2.5)
                
                lotes, _ = self._calcular_lotes_realistas(
                    simbolo=simbolo,
                    capital=capital,
                    entry=precio,
                    sl=sl,
                    riesgo_pct=self.riesgo_pct
                )
                
                if lotes > 0:
                    resultado = self._simular_operacion_realista(
                        df_h1, i, precio, sl, tp, direccion, lotes, simbolo
                    )
                    
                    op = {
                        'fecha': df_h1.index[i],
                        'direccion': direccion,
                        'modo': 'SIMPLIFICADO',
                        'regimen': 'UNKNOWN',
                        'score': 50,
                        'precio_entrada': precio,
                        'sl': sl,
                        'tp': tp,
                        'lotes': lotes,
                        'sl_pips': abs(precio - sl) / self._obtener_pip_val(simbolo) if self._obtener_pip_val(simbolo) > 0 else 0,
                        'tp_pips': abs(tp - precio) / self._obtener_pip_val(simbolo) if self._obtener_pip_val(simbolo) > 0 else 0,
                        'rr': abs(tp - precio) / abs(precio - sl) if abs(precio - sl) > 0 else 0,
                        'pnl': resultado['pnl'],
                        'resultado': resultado['resultado'],
                        'bars_held': resultado['bars_held'],
                    }
                    
                    operaciones.append(op)
                    capital += op['pnl']
                    
            except Exception:
                continue
        
        self.operaciones = operaciones
        return self._calcular_metricas(simbolo)
    
    def _calcular_atr_simple(self, df: pd.DataFrame, periodo: int = 14) -> float:
        """Calcula ATR simple."""
        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        
        return tr.rolling(periodo).mean().iloc[-1]
    
    def _resultado_vacio(self, simbolo: str, razon: str) -> Dict:
        """Retorna resultado vacío."""
        return {
            'simbolo': simbolo,
            'valido': False,
            'razon': razon,
            'n_operaciones': 0,
            'capital_final': self.capital_inicial,
            'pnl_total': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'modos_utilizados': {},
            'rechazos': 0,
            'tasa_disparo': 0,
            'capital_curve': [self.capital_inicial],
            'operaciones': []
        }
    
    def _calcular_metricas(self, simbolo: str) -> Dict:
        """Calcula métricas completas."""
        ops = self.operaciones
        
        if not ops:
            return self._resultado_vacio(simbolo, 'No se generaron operaciones')
        
        df_ops = pd.DataFrame(ops)
        
        ganadoras = df_ops[df_ops['pnl'] > 0]
        perdedoras = df_ops[df_ops['pnl'] < 0]
        
        win_rate = len(ganadoras) / len(ops) * 100 if ops else 0
        pnl_total = df_ops['pnl'].sum()
        avg_win = ganadoras['pnl'].mean() if len(ganadoras) > 0 else 0
        avg_loss = perdedoras['pnl'].mean() if len(perdedoras) > 0 else 0
        
        profit_factor = abs(ganadoras['pnl'].sum() / perdedoras['pnl'].sum()) if len(perdedoras) > 0 and perdedoras['pnl'].sum() != 0 else 0
        
        capital_curve = [self.capital_inicial]
        for op in ops:
            capital_curve.append(capital_curve[-1] + op['pnl'])
        
        peak = capital_curve[0]
        max_drawdown = 0
        for value in capital_curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100 if peak > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        returns = df_ops['pnl'] / self.capital_inicial
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        
        modos_stats = {}
        for modo in df_ops['modo'].unique():
            df_modo = df_ops[df_ops['modo'] == modo]
            ganadoras_modo = df_modo[df_modo['pnl'] > 0]
            modos_stats[modo] = {
                'total': len(df_modo),
                'winrate': len(ganadoras_modo) / len(df_modo) * 100 if len(df_modo) > 0 else 0,
                'pnl_total': df_modo['pnl'].sum(),
                'avg_pnl': df_modo['pnl'].mean(),
                'avg_rr': df_modo['rr'].mean() if 'rr' in df_modo.columns else 0,
                'avg_sl_pips': df_modo['sl_pips'].mean() if 'sl_pips' in df_modo.columns else 0,
                'avg_tp_pips': df_modo['tp_pips'].mean() if 'tp_pips' in df_modo.columns else 0,
            }
        
        return {
            'simbolo': simbolo,
            'valido': pnl_total > 0 and win_rate > 40,
            'n_operaciones': len(ops),
            'capital_final': capital_curve[-1],
            'pnl_total': pnl_total,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'modos_utilizados': modos_stats,
            'rechazos': len(self.rechazos),
            'tasa_disparo': len(ops) / (len(ops) + len(self.rechazos)) * 100 if (len(ops) + len(self.rechazos)) > 0 else 0,
            'capital_curve': capital_curve,
            'operaciones': ops,
        }


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def validar_estrategia_corregida_v2(simbolo: str = 'EURUSD',
                                    n_velas: int = 500,
                                    capital: float = 1000.0,
                                    riesgo: float = 0.01,
                                    mt5: Any = None,
                                    almacen: Any = None) -> Dict:
    """Función principal con PnL garantizado."""
    
    logger.info("=" * 70)
    logger.info(f"🚀 VALIDACIÓN CORREGIDA V2 PARA {simbolo}")
    logger.info(f"   Capital: ${capital:,.2f} | Riesgo: {riesgo*100:.1f}%")
    logger.info("=" * 70)
    
    # Obtener datos
    logger.info("📥 1. Obteniendo datos históricos...")
    
    # Intentar obtener datos
    dataframes = {}
    
    # Intentar desde MT5
    if mt5:
        try:
            df_h1 = mt5.obtener_datos(simbolo, n_velas=n_velas, timeframe=60)
            if df_h1 is not None and len(df_h1) > 50:
                dataframes[60] = df_h1
                logger.info(f"✅ H1: {len(df_h1)} velas desde MT5")
        except Exception as e:
            logger.warning(f"⚠️ Error obteniendo H1: {e}")
    
    # Intentar desde SQLite
    if 60 not in dataframes and almacen:
        try:
            df_h1 = almacen.obtener_datos_historicos(simbolo, 60)
            if df_h1 is not None and len(df_h1) > 50:
                dataframes[60] = df_h1
                logger.info(f"✅ H1: {len(df_h1)} velas desde SQLite")
        except Exception as e:
            logger.warning(f"⚠️ Error desde SQLite: {e}")
    
    if 60 not in dataframes:
        logger.error("❌ No se pudieron obtener datos H1")
        return {'valido': False, 'razon': 'Sin datos H1'}
    
    # Intentar obtener M5
    if mt5:
        try:
            df_m5 = mt5.obtener_datos(simbolo, n_velas=n_velas*12, timeframe=5)
            if df_m5 is not None and len(df_m5) > 50:
                dataframes[5] = df_m5
                logger.info(f"✅ M5: {len(df_m5)} velas desde MT5")
        except Exception:
            pass
    
    # Simular
    logger.info("📊 2. Validando estrategia...")
    simulador = SimuladorCorregidoV2(capital_inicial=capital, riesgo_pct=riesgo)
    resultado = simulador.simular(dataframes, simbolo)
    
    # Mostrar resultados
    logger.info("=" * 70)
    logger.info("📋 RESULTADOS DE VALIDACIÓN CORREGIDA V2")
    logger.info("=" * 70)
    logger.info(f"   Símbolo: {simbolo}")
    logger.info(f"   Operaciones: {resultado.get('n_operaciones', 0)}")
    logger.info(f"   Capital final: ${resultado.get('capital_final', 0):,.2f}")
    logger.info(f"   PnL total: ${resultado.get('pnl_total', 0):,.2f}")
    logger.info(f"   Win Rate: {resultado.get('win_rate', 0):.1f}%")
    logger.info(f"   Profit Factor: {resultado.get('profit_factor', 0):.2f}")
    logger.info(f"   Max Drawdown: {resultado.get('max_drawdown', 0):.1f}%")
    logger.info(f"   VALIDO: {'✅' if resultado.get('valido', False) else '❌'}")
    
    if resultado.get('modos_utilizados'):
        logger.info("")
        logger.info("📊 MODOS UTILIZADOS:")
        for modo, stats in resultado['modos_utilizados'].items():
            logger.info(f"   {modo}: {stats['total']} ops, WinRate: {stats['winrate']:.1f}%, PnL: ${stats['pnl_total']:.2f}")
    
    return resultado


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Validación corregida V2')
    parser.add_argument('--simbolo', '-s', default='EURUSD', help='Símbolo')
    parser.add_argument('--velas', '-n', type=int, default=500, help='Velas H1')
    parser.add_argument('--capital', '-c', type=float, default=1000.0, help='Capital')
    parser.add_argument('--riesgo', '-r', type=float, default=0.01, help='Riesgo')
    
    args = parser.parse_args()
    
    mt5 = None
    almacen = None
    
    try:
        from mt5.conector_mt5 import ConectorPepperstone
        from config.settings import Config
        
        config = Config()
        mt5 = ConectorPepperstone(
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
            demo=config.MT5_DEMO
        )
        mt5.conectar()
        logger.info("✅ Conectado a MT5")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo conectar a MT5: {e}")
    
    try:
        from data.almacenamiento_sqlite import AlmacenamientoSQLite
        from pathlib import Path
        almacen = AlmacenamientoSQLite(base_dir=Path("data"))
    except Exception as e:
        logger.warning(f"⚠️ No se pudo cargar almacenamiento: {e}")
    
    validar_estrategia_corregida_v2(args.simbolo, args.velas, args.capital, args.riesgo, mt5, almacen)