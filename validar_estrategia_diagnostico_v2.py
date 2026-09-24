#!/usr/bin/env python3
"""
validar_estrategia_diagnostico_v2.py (V4.1 - CORREGIDO M5)
Versión que maneja correctamente la ausencia de M5.

CAMBIOS:
- ✅ Prioriza descarga de M5
- ✅ Si no hay M5, usa H1 para sniper (sin validación de momento)
- ✅ Logs más detallados de obtención de datos
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

# Configurar logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-7s | %(message)s'
)
logger = logging.getLogger('ValidarEstrategiaDiagnosticoV2')

sys.path.insert(0, str(Path(__file__).parent))


class ObtenedorDatosDiagnosticoV2:
    """Obtiene datos con prioridad en M5."""
    
    def __init__(self, mt5: Any = None, almacen: Any = None):
        self.mt5 = mt5
        self.almacen = almacen
        self.logger = logging.getLogger('DiagnosticoV2.Datos')
    
    def obtener_timeframe(self, simbolo: str, timeframe: int, 
                         n_velas: int = 500, reintentos: int = 3) -> Optional[pd.DataFrame]:
        """Obtiene datos con reintentos."""
        self.logger.info(f"📥 Obteniendo {simbolo} TF{timeframe} ({n_velas} velas)...")
        
        for intento in range(reintentos):
            # 1. Intentar MT5
            if self.mt5:
                try:
                    df = self.mt5.obtener_datos(simbolo, n_velas=n_velas, timeframe=timeframe)
                    if df is not None and len(df) > 20:
                        self.logger.info(f"   ✅ TF{timeframe}: {len(df)} velas desde MT5 (intento {intento+1})")
                        return df
                except Exception as e:
                    self.logger.debug(f"   ⚠️ MT5 intento {intento+1} falló: {e}")
                    time.sleep(0.5)
            
            # 2. Intentar SQLite
            if self.almacen:
                try:
                    df = self.almacen.obtener_datos_historicos(simbolo, timeframe)
                    if df is not None and len(df) > 20:
                        self.logger.info(f"   ✅ TF{timeframe}: {len(df)} velas desde SQLite")
                        return df
                except Exception:
                    pass
        
        self.logger.warning(f"   ❌ No se obtuvieron datos para TF{timeframe} después de {reintentos} intentos")
        
        # 3. Si es M5 y no hay, intentar construir desde ticks (solo si es backtest)
        if timeframe == 5 and self.mt5:
            self.logger.info(f"   🔧 Intentando construir M5 desde velas más pequeñas...")
            try:
                # Intentar M1
                df_m1 = self.mt5.obtener_datos(simbolo, n_velas=n_velas*5, timeframe=1)
                if df_m1 is not None and len(df_m1) > 50:
                    # Construir M5 desde M1
                    df_m5 = df_m1.resample('5min').agg({
                        'Open': 'first',
                        'High': 'max',
                        'Low': 'min',
                        'Close': 'last',
                        'Volume': 'sum'
                    }).dropna()
                    if len(df_m5) > 10:
                        self.logger.info(f"   ✅ TF5: {len(df_m5)} velas construidas desde M1")
                        return df_m5
            except Exception as e:
                self.logger.debug(f"   ⚠️ Error construyendo M5: {e}")
        
        return None
    
    def obtener_todos_timeframes(self, simbolo: str, n_velas: int = 500) -> Dict[int, pd.DataFrame]:
        """Obtiene todos los timeframes prioritarios."""
        timeframes = [5, 60, 240, 1440]
        
        # Ajustar número de velas
        n_por_tf = {
            5: min(n_velas * 12, 10000),   # M5: máximo 10,000
            60: n_velas,                    # H1
            240: max(50, n_velas // 4),    # H4: mínimo 50
            1440: max(30, n_velas // 24),  # D1: mínimo 30
        }
        
        resultados = {}
        
        # PRIORIDAD 1: OBTENER M5 (CRÍTICO PARA SNIPER)
        self.logger.info("=" * 50)
        self.logger.info("📥 PRIORIDAD 1: OBTENIENDO M5 (CRÍTICO)")
        self.logger.info("=" * 50)
        
        df_m5 = self.obtener_timeframe(simbolo, 5, n_por_tf[5], reintentos=5)
        if df_m5 is not None:
            resultados[5] = df_m5
            self.logger.info(f"✅ M5 OBTENIDO: {len(df_m5)} velas")
        else:
            self.logger.warning("⚠️ NO se pudo obtener M5 - El sniper usará H1 como fallback")
        
        # PRIORIDAD 2: OBTENER H1
        self.logger.info("=" * 50)
        self.logger.info("📥 PRIORIDAD 2: OBTENIENDO H1")
        self.logger.info("=" * 50)
        
        df_h1 = self.obtener_timeframe(simbolo, 60, n_por_tf[60], reintentos=3)
        if df_h1 is not None:
            resultados[60] = df_h1
            self.logger.info(f"✅ H1 OBTENIDO: {len(df_h1)} velas")
        else:
            self.logger.error("❌ NO se pudo obtener H1 - Abortando")
            return resultados
        
        # PRIORIDAD 3: OBTENER H4 y D1 (opcionales)
        self.logger.info("=" * 50)
        self.logger.info("📥 PRIORIDAD 3: OBTENIENDO H4 y D1 (opcionales)")
        self.logger.info("=" * 50)
        
        df_h4 = self.obtener_timeframe(simbolo, 240, n_por_tf[240], reintentos=2)
        if df_h4 is not None:
            resultados[240] = df_h4
            self.logger.info(f"✅ H4 OBTENIDO: {len(df_h4)} velas")
        
        df_d1 = self.obtener_timeframe(simbolo, 1440, n_por_tf[1440], reintentos=2)
        if df_d1 is not None:
            resultados[1440] = df_d1
            self.logger.info(f"✅ D1 OBTENIDO: {len(df_d1)} velas")
        
        self.logger.info("=" * 50)
        self.logger.info(f"📊 RESUMEN DE DATOS OBTENIDOS:")
        for tf, df in resultados.items():
            self.logger.info(f"   TF{tf}: {len(df)} velas")
        self.logger.info("=" * 50)
        
        return resultados


class SimuladorDiagnosticoV2:
    """Simulador que maneja ausencia de M5."""
    
    def __init__(self, capital_inicial: float = 1000.0, riesgo_pct: float = 0.01):
        self.capital_inicial = capital_inicial
        self.riesgo_pct = riesgo_pct
        self.logger = logging.getLogger('DiagnosticoV2.Simulador')
        
        self.contadores = {
            'velas_procesadas': 0,
            'filtro_rapido_pasa': 0,
            'filtro_medio_pasa': 0,
            'direccion_determinada': 0,
            'direccion_neutral': 0,
            'modo_seleccionado': 0,
            'sniper_con_m5': 0,
            'sniper_sin_m5_fallback': 0,
            'operaciones_ejecutadas': 0,
        }
        
        self.rechazos_detallados = {}
    
    def simular(self, dataframes: Dict[int, pd.DataFrame], simbolo: str) -> Dict:
        """Simula con manejo de ausencia de M5."""
        
        self.logger.info("=" * 70)
        self.logger.info(f"🔍 INICIANDO DIAGNÓSTICO V2 PARA {simbolo}")
        self.logger.info("=" * 70)
        
        if 60 not in dataframes:
            self.logger.error("❌ No hay datos H1")
            return {'valido': False, 'razon': 'Sin datos H1'}
        
        df_h1 = dataframes[60]
        df_m5 = dataframes.get(5)
        df_h4 = dataframes.get(240)
        df_d1 = dataframes.get(1440)
        
        self.logger.info(f"📊 Datos disponibles:")
        self.logger.info(f"   H1: {len(df_h1)} velas")
        self.logger.info(f"   M5: {len(df_m5) if df_m5 is not None else '❌ NO DISPONIBLE'}")
        self.logger.info(f"   H4: {len(df_h4) if df_h4 is not None else '❌ NO DISPONIBLE'}")
        self.logger.info(f"   D1: {len(df_d1) if df_d1 is not None else '❌ NO DISPONIBLE'}")
        
        if df_m5 is None:
            self.logger.warning("⚠️ NO HAY M5 - Usando H1 como fallback para sniper")
        
        # Cargar módulos
        modulos = self._cargar_modulos()
        
        if not modulos['disponible']:
            self.logger.warning("⚠️ Módulos NO disponibles, usando modo simplificado")
            return self._simular_simplificado(df_h1, simbolo)
        
        self.logger.info("✅ Módulos del bot cargados")
        
        capital = self.capital_inicial
        operaciones = []
        
        max_velas = min(len(df_h1) - 10, 500)
        
        self.logger.info(f"📊 Analizando {max_velas - 100} velas (100 a {max_velas})")
        
        for i in range(100, max_velas):
            self.contadores['velas_procesadas'] += 1
            
            try:
                df_h1_slice = df_h1.iloc[:i+1].copy()
                precio_actual = df_h1_slice['Close'].iloc[-1]
                fecha_actual = df_h1_slice.index[-1]
                
                # ============================================================
                # PASO 1: ANÁLISIS RÁPIDO
                # ============================================================
                
                try:
                    rapido = modulos['analisis_capas'].analisis_rapido(df_h1_slice, simbolo, precio_actual)
                except Exception:
                    continue
                
                if not rapido.pasa_filtro:
                    continue
                
                self.contadores['filtro_rapido_pasa'] += 1
                
                # ============================================================
                # PASO 2: NIVELES
                # ============================================================
                
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
                
                # ============================================================
                # PASO 3: ANÁLISIS MEDIO
                # ============================================================
                
                try:
                    medio = modulos['analisis_capas'].analisis_medio(df_h1_slice, simbolo, rapido, niveles)
                except Exception:
                    continue
                
                if medio is None or not medio.pasa_filtro:
                    continue
                
                self.contadores['filtro_medio_pasa'] += 1
                
                # ============================================================
                # PASO 4: ANÁLISIS PESADO
                # ============================================================
                
                try:
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
                    
                    pesado = modulos['analisis_capas'].analisis_pesado(
                        df_h1_slice, simbolo, df_h4_slice, df_d1_slice, niveles, medio
                    )
                except Exception:
                    continue
                
                # ============================================================
                # PASO 5: SCORE H1
                # ============================================================
                
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
                
                # ============================================================
                # PASO 6: RÉGIMEN
                # ============================================================
                
                try:
                    regimen_data = modulos['regimen_filter'].clasificar(simbolo, df_h4_slice, df_h1_slice)
                    regimen = regimen_data.regimen.value
                except Exception:
                    regimen = 'INCERTO'
                
                # ============================================================
                # PASO 7: DIRECCIÓN
                # ============================================================
                
                direccion = self._determinar_direccion(medio, pesado, regimen)
                
                if direccion == 'NEUTRAL':
                    self.contadores['direccion_neutral'] += 1
                    continue
                
                self.contadores['direccion_determinada'] += 1
                
                # ============================================================
                # PASO 8: SELECCIONAR MODO
                # ============================================================
                
                try:
                    modo_obj, razon_modo, _ = modulos['modo_selector'].seleccionar_modo(
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
                    continue
                
                self.contadores['modo_seleccionado'] += 1
                modo = modo_obj.value
                
                # ============================================================
                # PASO 9: SNIPER (CON FALLBACK SI NO HAY M5)
                # ============================================================
                
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
                    'niveles': niveles,
                }
                
                resultado_sniper = None
                
                # CASO 1: TENEMOS M5
                if df_m5 is not None:
                    idx_m5 = df_m5.index.get_indexer([fecha_actual], method='ffill')[0]
                    if idx_m5 >= 0:
                        df_m5_slice = df_m5.iloc[:idx_m5+1].copy()
                        
                        if len(df_m5_slice) > 20:
                            try:
                                resultado_sniper = modulos['sniper'].evaluar_sniper_optimizado(
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
                                self.contadores['sniper_con_m5'] += 1
                            except Exception as e:
                                self.logger.debug(f"Error en sniper con M5: {e}")
                
                # CASO 2: FALLBACK - USAR H1 (SIN VALIDACIÓN DE MOMENTO)
                if resultado_sniper is None:
                    self.logger.debug(f"⚠️ Sniper falló, usando fallback H1 para {simbolo} en {fecha_actual}")
                    self.contadores['sniper_sin_m5_fallback'] += 1
                    
                    # Crear señal manual desde análisis H1
                    resultado_sniper = {
                        'sl': self._calcular_sl_fallback(precio_actual, medio, direccion),
                        'tp': self._calcular_tp_fallback(precio_actual, medio, direccion),
                        'modo': modo,
                        'score': score_h1,
                    }
                
                # ============================================================
                # PASO 10: EJECUTAR
                # ============================================================
                
                if resultado_sniper is not None:
                    sl = resultado_sniper.get('sl', 0)
                    tp = resultado_sniper.get('tp', 0)
                    
                    if sl > 0 and tp > 0:
                        pip_val = self._obtener_pip_val(simbolo)
                        sl_dist = abs(precio_actual - sl)
                        
                        if sl_dist > 0:
                            lotes = (capital * self.riesgo_pct) / (sl_dist / pip_val * 100000)
                            lotes = max(0.01, min(0.10, round(lotes, 2)))
                        else:
                            lotes = 0.01
                        
                        resultado_op = self._simular_operacion(
                            df_h1, i, precio_actual, sl, tp, direccion, lotes, simbolo
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
                            'pnl': resultado_op['pnl'],
                            'resultado': resultado_op['resultado'],
                            'bars_held': resultado_op['bars_held'],
                            'sniper_con_m5': df_m5 is not None,
                        }
                        
                        operaciones.append(op)
                        capital += op['pnl']
                        self.contadores['operaciones_ejecutadas'] += 1
                        
                        self.logger.info(f"🎯 OP #{len(operaciones)}: {direccion} {modo} | PnL: ${op['pnl']:.2f} | {resultado_op['resultado']}")
                
            except Exception as e:
                self.logger.debug(f"Error: {e}")
                continue
        
        # ============================================================
        # MOSTRAR RESULTADOS
        # ============================================================
        
        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("📊 ESTADÍSTICAS DE DIAGNÓSTICO V2")
        self.logger.info("=" * 70)
        self.logger.info(f"   Velas procesadas: {self.contadores['velas_procesadas']}")
        self.logger.info(f"   Filtro Rápido → Pasa: {self.contadores['filtro_rapido_pasa']}")
        self.logger.info(f"   Filtro Medio → Pasa: {self.contadores['filtro_medio_pasa']}")
        self.logger.info(f"   Dirección → Determinada: {self.contadores['direccion_determinada']} | Neutral: {self.contadores['direccion_neutral']}")
        self.logger.info(f"   Modo → Seleccionado: {self.contadores['modo_seleccionado']}")
        self.logger.info(f"   Sniper con M5: {self.contadores['sniper_con_m5']}")
        self.logger.info(f"   Sniper fallback (sin M5): {self.contadores['sniper_sin_m5_fallback']}")
        self.logger.info(f"   Operaciones ejecutadas: {self.contadores['operaciones_ejecutadas']}")
        
        self.logger.info("")
        self.logger.info("📈 RESULTADOS DE LA SIMULACIÓN:")
        self.logger.info(f"   Operaciones: {len(operaciones)}")
        self.logger.info(f"   Capital final: ${capital:.2f}")
        
        return {
            'simbolo': simbolo,
            'n_operaciones': len(operaciones),
            'capital_final': capital,
            'contadores': self.contadores,
            'operaciones': operaciones,
        }
    
    def _cargar_modulos(self) -> Dict:
        """Carga módulos del bot."""
        resultado = {'disponible': False}
        
        try:
            from analysis.capas import AnalisisPorCapas
            from analysis.regimen import MarketRegimeFilter
            from trading.modos import ModoSelector
            from trading.timer import EntryTimer
            from trading.stops import GestorStops
            from trading.sniper.sniper_checklist import SniperChecklist
            
            resultado = {
                'disponible': True,
                'analisis_capas': AnalisisPorCapas(modo_backtest=True),
                'regimen_filter': MarketRegimeFilter(modo_backtest=True),
                'modo_selector': ModoSelector(modo_backtest=True),
                'entry_timer': EntryTimer(modo_backtest=True),
                'gestor_stops': GestorStops(modo_backtest=True),
                'sniper': SniperChecklist(
                    pipeline=None,
                    analisis_capas=resultado.get('analisis_capas'),
                    modo_selector=resultado.get('modo_selector'),
                    entry_timer=resultado.get('entry_timer'),
                    gestor_stops=resultado.get('gestor_stops'),
                    modo_backtest=True
                ) if 'analisis_capas' in resultado else None
            }
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando módulos: {e}")
        
        return resultado
    
    def _determinar_direccion(self, medio, pesado, regimen) -> str:
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
        """Calcula SL fallback cuando no hay M5."""
        if medio is None:
            atr = 0.001
        else:
            atr = medio.atr if hasattr(medio, 'atr') else 0.001
        
        if direccion == 'COMPRA':
            return precio - (atr * 1.5)
        else:
            return precio + (atr * 1.5)
    
    def _calcular_tp_fallback(self, precio: float, medio, direccion: str) -> float:
        """Calcula TP fallback cuando no hay M5."""
        if medio is None:
            atr = 0.001
        else:
            atr = medio.atr if hasattr(medio, 'atr') else 0.001
        
        if direccion == 'COMPRA':
            return precio + (atr * 2.5)
        else:
            return precio - (atr * 2.5)
    
    def _simular_operacion(self, df: pd.DataFrame, index: int,
                           precio_entrada: float, sl: float, tp: float,
                           direccion: str, lotes: float, simbolo: str) -> Dict:
        """Simula resultado."""
        
        if direccion == 'COMPRA':
            if sl >= precio_entrada or tp <= precio_entrada:
                return {'pnl': 0, 'resultado': 'INVALIDO', 'bars_held': 0}
        else:
            if sl <= precio_entrada or tp >= precio_entrada:
                return {'pnl': 0, 'resultado': 'INVALIDO', 'bars_held': 0}
        
        max_bars = 100
        pip_val = self._obtener_pip_val(simbolo)
        
        for j in range(index + 1, min(len(df), index + max_bars + 1)):
            try:
                high = df['High'].iloc[j]
                low = df['Low'].iloc[j]
            except Exception:
                continue
            
            if direccion == 'COMPRA':
                if low <= sl:
                    pnl = (sl - precio_entrada) / pip_val * lotes * 100000
                    return {'pnl': pnl, 'resultado': 'SL', 'bars_held': j - index}
                if high >= tp:
                    pnl = (tp - precio_entrada) / pip_val * lotes * 100000
                    return {'pnl': pnl, 'resultado': 'TP', 'bars_held': j - index}
            else:
                if high >= sl:
                    pnl = (precio_entrada - sl) / pip_val * lotes * 100000
                    return {'pnl': pnl, 'resultado': 'SL', 'bars_held': j - index}
                if low <= tp:
                    pnl = (precio_entrada - tp) / pip_val * lotes * 100000
                    return {'pnl': pnl, 'resultado': 'TP', 'bars_held': j - index}
        
        precio_final = df['Close'].iloc[min(len(df) - 1, index + max_bars)]
        
        if direccion == 'COMPRA':
            pnl = (precio_final - precio_entrada) / pip_val * lotes * 100000
        else:
            pnl = (precio_entrada - precio_final) / pip_val * lotes * 100000
        
        return {'pnl': pnl, 'resultado': 'TIMEOUT', 'bars_held': max_bars}
    
    def _obtener_pip_val(self, simbolo: str) -> float:
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


def validar_con_diagnostico_v2(simbolo: str = 'EURUSD',
                               n_velas: int = 500,
                               mt5: Any = None,
                               almacen: Any = None) -> Dict:
    """Función principal con diagnóstico V2."""
    
    logger.info("=" * 70)
    logger.info(f"🔍 DIAGNÓSTICO V2 PARA {simbolo}")
    logger.info("=" * 70)
    
    # 1. Obtener datos
    logger.info("📥 1. Obteniendo datos históricos...")
    obtenedor = ObtenedorDatosDiagnosticoV2(mt5=mt5, almacen=almacen)
    dataframes = obtenedor.obtener_todos_timeframes(simbolo, n_velas)
    
    if 60 not in dataframes:
        logger.error("❌ No se pudieron obtener datos H1")
        return {'valido': False, 'razon': 'Sin datos H1'}
    
    # 2. Ejecutar simulación
    logger.info("📊 2. Ejecutando simulación con diagnóstico V2...")
    simulador = SimuladorDiagnosticoV2(capital_inicial=1000.0, riesgo_pct=0.01)
    resultado = simulador.simular(dataframes, simbolo)
    
    # 3. Guardar
    ruta = Path("data") / f"diagnostico_v2_{simbolo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(resultado, f, indent=2, default=str)
        logger.info(f"💾 Diagnóstico guardado en: {ruta}")
    except Exception:
        pass
    
    return resultado


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Diagnóstico V2')
    parser.add_argument('--simbolo', '-s', default='EURUSD', help='Símbolo')
    parser.add_argument('--velas', '-n', type=int, default=500, help='Velas H1')
    
    args = parser.parse_args()
    
    # Cargar módulos
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
    except Exception:
        pass
    
    validar_con_diagnostico_v2(args.simbolo, args.velas, mt5, almacen)