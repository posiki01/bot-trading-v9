#!/usr/bin/env python3
"""
validar_estrategia_completa.py (V3.2 - CORREGIDO DEFINITIVO)
Validación completa de la estrategia del bot.

CORRECCIONES V3.2:
- ✅ Orden correcto de inicialización (logger antes de _inicializar_modulos)
- ✅ Manejo de errores más robusto
- ✅ Fallback a modo simplificado cuando no hay módulos
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging
import json
import warnings
import sys
import os

warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s'
)
logger = logging.getLogger('ValidarEstrategiaCompleta')

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))


# ============================================================
# CLASE 1: OBTENEDOR DE DATOS
# ============================================================

class ObtenedorDatosCompleto:
    """Obtiene datos de M5, M15, H1, H4, D1 para validación."""
    
    def __init__(self, mt5: Any = None, almacen: Any = None):
        self.mt5 = mt5
        self.almacen = almacen
        self.logger = logging.getLogger('ValidarEstrategia.Datos')
    
    def obtener_timeframe(self, simbolo: str, timeframe: int, 
                         n_velas: int = 5000) -> Optional[pd.DataFrame]:
        """Obtiene datos de un timeframe específico."""
        if self.mt5:
            try:
                df = self.mt5.obtener_datos(simbolo, n_velas=n_velas, timeframe=timeframe)
                if df is not None and len(df) > 0:
                    return df
            except Exception as e:
                self.logger.debug(f"MT5 error para {simbolo} TF{timeframe}: {e}")
        
        if self.almacen:
            try:
                df = self.almacen.obtener_datos_historicos(simbolo, timeframe)
                if df is not None and len(df) > 0:
                    return df
            except Exception:
                pass
        
        return None
    
    def obtener_todos_timeframes(self, simbolo: str, 
                                  n_velas: int = 5000) -> Dict[int, pd.DataFrame]:
        """Obtiene M5, M15, H1, H4, D1."""
        timeframes = [5, 15, 60, 240, 1440]
        
        n_por_tf = {
            5: min(n_velas * 12, 60000),
            15: min(n_velas * 4, 20000),
            60: n_velas,
            240: max(100, n_velas // 4),
            1440: max(50, n_velas // 24),
        }
        
        resultados = {}
        
        for tf in timeframes:
            self.logger.info(f"📥 {simbolo}: Obteniendo TF{tf} ({n_por_tf[tf]} velas)...")
            
            try:
                df = self.obtener_timeframe(simbolo, tf, n_por_tf[tf])
                
                if df is not None and len(df) > 20:
                    required = ['Open', 'High', 'Low', 'Close', 'Volume']
                    if all(col in df.columns for col in required):
                        resultados[tf] = df
                        self.logger.info(f"   ✅ TF{tf}: {len(df)} velas")
                    else:
                        self.logger.warning(f"   ⚠️ TF{tf}: Columnas faltantes")
                else:
                    self.logger.warning(f"   ⚠️ TF{tf}: Datos insuficientes")
                    
            except Exception as e:
                self.logger.warning(f"   ❌ TF{tf}: Error - {e}")
        
        if 60 in resultados:
            self.logger.info(f"✅ Datos obtenidos: {', '.join([f'TF{tf}: {len(df)}' for tf, df in resultados.items()])}")
        else:
            self.logger.error(f"❌ No se obtuvieron datos H1 para {simbolo}")
        
        return resultados


# ============================================================
# CLASE 2: SIMULADOR BOT COMPLETO (CORREGIDO)
# ============================================================

class SimuladorBotCompleto:
    """
    Simula el bot completo en datos históricos.
    """
    
    def __init__(self, capital_inicial: float = 1000.0,
                 riesgo_pct: float = 0.01,
                 modo_backtest: bool = True):
        
        self.capital_inicial = capital_inicial
        self.riesgo_pct = riesgo_pct
        self.modo_backtest = modo_backtest
        
        # ✅ 1. PRIMERO: Crear el logger (ANTES de _inicializar_modulos)
        self.logger = logging.getLogger('ValidarEstrategia.Simulador')
        
        # ✅ 2. SEGUNDO: Inicializar estadísticas
        self.operaciones = []
        self.rechazos = []
        self.modos_utilizados = {}
        
        # ✅ 3. TERCERO: Inicializar módulos
        self._inicializar_modulos()
    
    def _inicializar_modulos(self):
        """Inicializa los módulos del bot en modo simulación."""
        self.modulos_disponibles = False
        
        try:
            # 1. Análisis por capas
            from analysis.capas import AnalisisPorCapas
            self.analisis_capas = AnalisisPorCapas(modo_backtest=True)
            
            # 2. Régimen de mercado
            from analysis.regimen import MarketRegimeFilter
            self.regimen_filter = MarketRegimeFilter(modo_backtest=True)
            
            # 3. Selector de modos
            from trading.modos import ModoSelector
            self.modo_selector = ModoSelector(modo_backtest=True)
            
            # 4. Entry Timer
            from trading.timer import EntryTimer
            self.entry_timer = EntryTimer(modo_backtest=True)
            
            # 5. Gestor de stops
            from trading.stops import GestorStops
            self.gestor_stops = GestorStops(modo_backtest=True)
            
            # 6. Sniper Checklist
            from trading.sniper.sniper_checklist import SniperChecklist
            self.sniper = SniperChecklist(
                pipeline=None,
                analisis_capas=self.analisis_capas,
                modo_selector=self.modo_selector,
                entry_timer=self.entry_timer,
                gestor_stops=self.gestor_stops,
                modo_backtest=True
            )
            
            self.modulos_disponibles = True
            self.logger.info("✅ Módulos del bot inicializados correctamente")
            
        except ImportError as e:
            self.logger.warning(f"⚠️ Error importando módulos: {e}")
            self.logger.info("   Usando modo simplificado (sin módulos del bot)")
            self.analisis_capas = None
            self.regimen_filter = None
            self.modo_selector = None
            self.entry_timer = None
            self.gestor_stops = None
            self.sniper = None
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error inicializando módulos: {e}")
            self.logger.info("   Usando modo simplificado (sin módulos del bot)")
            self.analisis_capas = None
            self.regimen_filter = None
            self.modo_selector = None
            self.entry_timer = None
            self.gestor_stops = None
            self.sniper = None
    
    def simular(self, dataframes: Dict[int, pd.DataFrame], 
                simbolo: str) -> Dict:
        """
        Simula el bot completo en los datos históricos.
        """
        # Verificar que tenemos H1
        if 60 not in dataframes:
            self.logger.error(f"❌ No hay datos H1 para {simbolo}")
            return {'valido': False, 'razon': 'Sin datos H1'}
        
        df_h1 = dataframes[60]
        df_m5 = dataframes.get(5)
        df_h4 = dataframes.get(240)
        df_d1 = dataframes.get(1440)
        
        if len(df_h1) < 100:
            return {'valido': False, 'razon': f'Datos insuficientes ({len(df_h1)} velas)'}
        
        self.logger.info(f"📊 Simulando {simbolo} con {len(df_h1)} velas H1")
        
        capital = self.capital_inicial
        operaciones = []
        rechazos = []
        modos_utilizados = {}
        
        max_velas = min(len(df_h1) - 10, 5000)
        
        self.logger.info(f"   Analizando desde vela 100 hasta {max_velas} ({max_velas - 100} iteraciones)")
        
        # ============================================================
        # SI NO HAY MÓDULOS, USAR MODO SIMPLIFICADO
        # ============================================================
        if not self.modulos_disponibles:
            self.logger.info("📊 Usando modo SIMPLIFICADO (solo EMAs)")
            return self._simular_simplificado(df_h1, simbolo)
        
        # ============================================================
        # MODO COMPLETO CON MÓDULOS DEL BOT
        # ============================================================
        
        for i in range(100, max_velas):
            try:
                df_h1_slice = df_h1.iloc[:i+1].copy()
                precio_actual = df_h1_slice['Close'].iloc[-1]
                fecha_actual = df_h1_slice.index[-1]
                
                # Obtener H4 y D1 sincronizados
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
                
                # Análisis Rápido
                try:
                    rapido = self.analisis_capas.analisis_rapido(df_h1_slice, simbolo, precio_actual)
                except Exception:
                    continue
                
                if not rapido.pasa_filtro:
                    rechazos.append({'fecha': fecha_actual, 'razon': 'Rápido falló', 'etapa': 'RAPIDO'})
                    continue
                
                # Detectar Niveles
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
                
                # Análisis Medio
                try:
                    medio = self.analisis_capas.analisis_medio(df_h1_slice, simbolo, rapido, niveles)
                except Exception:
                    continue
                
                if not medio.pasa_filtro:
                    rechazos.append({'fecha': fecha_actual, 'razon': 'Medio falló', 'etapa': 'MEDIO'})
                    continue
                
                # Análisis Pesado
                try:
                    pesado = self.analisis_capas.analisis_pesado(
                        df_h1_slice, simbolo, df_h4_slice, df_d1_slice, niveles, medio
                    )
                except Exception:
                    continue
                
                # Score H1
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
                
                # Régimen
                try:
                    regimen_data = self.regimen_filter.clasificar(simbolo, df_h4_slice, df_h1_slice)
                    regimen = regimen_data.regimen.value
                except Exception:
                    regimen = 'INCERTO'
                
                # Dirección
                direccion = self._determinar_direccion(medio, pesado, regimen)
                
                if direccion == 'NEUTRAL':
                    rechazos.append({'fecha': fecha_actual, 'razon': 'Dirección NEUTRAL', 'etapa': 'DIRECCION'})
                    continue
                
                # Seleccionar Modo
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
                
                # Obtener datos M5 para Sniper
                df_m5_slice = None
                if df_m5 is not None:
                    idx_m5 = df_m5.index.get_indexer([fecha_actual], method='ffill')[0]
                    if idx_m5 >= 0:
                        df_m5_slice = df_m5.iloc[:idx_m5+1].copy()
                
                # Contexto H1
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
                    'wyckoff_fase': pesado.wyckoff_fase if pesado else None,
                    'divergencia_rsi': pesado.divergencia_rsi if pesado else None,
                    'divergencia_macd': pesado.divergencia_macd if pesado else None,
                    'niveles': niveles,
                    'ob_cercano': pesado.ob_cercano if pesado else False,
                }
                
                # Evaluar Sniper
                resultado_sniper = None
                if df_m5_slice is not None and len(df_m5_slice) > 20 and self.sniper is not None:
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
                
                # Ejecutar operación si sniper dispara
                if resultado_sniper is not None:
                    sl = resultado_sniper.get('sl', 0)
                    tp = resultado_sniper.get('tp', 0)
                    modo = resultado_sniper.get('modo', modo)
                    score = resultado_sniper.get('score', score_h1)
                    
                    if sl > 0 and tp > 0:
                        pip_val = self._obtener_pip_val(simbolo)
                        sl_dist = abs(precio_actual - sl)
                        
                        if sl_dist > 0:
                            lotes = (capital * self.riesgo_pct) / (sl_dist / pip_val * 100000)
                            lotes = max(0.01, min(0.10, round(lotes, 2)))
                        else:
                            lotes = 0.01
                        
                        resultado_op = self._simular_operacion(
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
                            'score': score,
                            'precio_entrada': precio_actual,
                            'sl': sl,
                            'tp': tp,
                            'lotes': lotes,
                            'pnl': resultado_op['pnl'],
                            'resultado': resultado_op['resultado'],
                            'bars_held': resultado_op['bars_held'],
                        }
                        
                        operaciones.append(op)
                        capital += op['pnl']
                        modos_utilizados[modo] = modos_utilizados.get(modo, 0) + 1
                    
            except Exception as e:
                continue
        
        self.logger.info(f"📊 Simulación completada: {len(operaciones)} ops, {len(rechazos)} rechazos")
        
        self.operaciones = operaciones
        self.rechazos = rechazos
        self.modos_utilizados = modos_utilizados
        
        return self._calcular_metricas(simbolo)
    
    def _simular_simplificado(self, df_h1: pd.DataFrame, simbolo: str) -> Dict:
        """Versión simplificada usando solo EMAs."""
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
                
                pip_val = self._obtener_pip_val(simbolo)
                sl_dist = abs(precio - sl)
                lotes = (capital * self.riesgo_pct) / (sl_dist / pip_val * 100000)
                lotes = max(0.01, min(0.10, round(lotes, 2)))
                
                resultado = self._simular_operacion(
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
    
    def _determinar_direccion(self, medio, pesado, regimen) -> str:
        """Determina dirección basada en análisis."""
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
    
    def _simular_operacion(self, df: pd.DataFrame, index: int,
                           precio_entrada: float, sl: float, tp: float,
                           direccion: str, lotes: float, simbolo: str) -> Dict:
        """Simula el resultado de una operación."""
        
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
    
    def _calcular_metricas(self, simbolo: str) -> Dict:
        """Calcula métricas completas de la simulación."""
        
        ops = self.operaciones
        
        if not ops:
            return {
                'simbolo': simbolo,
                'valido': False,
                'razon': 'No se generaron operaciones',
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
                'rechazos': len(self.rechazos),
                'operaciones': []
            }
        
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

def validar_estrategia_completa(simbolo: str = 'EURUSD',
                               n_velas: int = 3000,
                               mt5: Any = None,
                               almacen: Any = None) -> Dict:
    """Función principal de validación."""
    
    logger.info("=" * 70)
    logger.info(f"🚀 VALIDACIÓN COMPLETA DE ESTRATEGIA PARA {simbolo}")
    logger.info("=" * 70)
    
    # 1. Obtener datos
    logger.info("📥 1. Obteniendo datos históricos...")
    obtenedor = ObtenedorDatosCompleto(mt5=mt5, almacen=almacen)
    dataframes = obtenedor.obtener_todos_timeframes(simbolo, n_velas)
    
    if 60 not in dataframes:
        logger.error("❌ No se pudieron obtener datos H1")
        return {'valido': False, 'razon': 'Sin datos H1'}
    
    # 2. Validar estrategia
    logger.info("📊 2. Validando estrategia completa...")
    simulador = SimuladorBotCompleto(capital_inicial=1000.0, riesgo_pct=0.01)
    
    resultado = simulador.simular(dataframes, simbolo)
    
    # 3. Mostrar resultados
    logger.info("=" * 70)
    logger.info("📋 RESULTADOS DE VALIDACIÓN")
    logger.info("=" * 70)
    logger.info(f"   Símbolo: {simbolo}")
    logger.info(f"   Operaciones: {resultado.get('n_operaciones', 0)}")
    logger.info(f"   Capital final: ${resultado.get('capital_final', 0):.2f}")
    logger.info(f"   PnL total: ${resultado.get('pnl_total', 0):.2f}")
    logger.info(f"   Win Rate: {resultado.get('win_rate', 0):.1f}%")
    logger.info(f"   Profit Factor: {resultado.get('profit_factor', 0):.2f}")
    logger.info(f"   Sharpe Ratio: {resultado.get('sharpe_ratio', 0):.2f}")
    logger.info(f"   Max Drawdown: {resultado.get('max_drawdown', 0):.1f}%")
    logger.info(f"   Tasa de disparo: {resultado.get('tasa_disparo', 0):.1f}%")
    logger.info(f"   VALIDO: {'✅' if resultado.get('valido', False) else '❌'}")
    
    # 4. Estadísticas por modo
    if resultado.get('modos_utilizados'):
        logger.info("")
        logger.info("📊 MODOS UTILIZADOS:")
        for modo, stats in resultado['modos_utilizados'].items():
            logger.info(f"   {modo}: {stats['total']} ops, WinRate: {stats['winrate']:.1f}%, PnL: ${stats['pnl_total']:.2f}")
    
    # 5. Guardar reporte
    ruta_reporte = Path("data") / f"validacion_{simbolo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    ruta_reporte.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        reporte_serializable = resultado.copy()
        
        if 'operaciones' in reporte_serializable:
            for op in reporte_serializable['operaciones']:
                if 'fecha' in op and hasattr(op['fecha'], 'isoformat'):
                    op['fecha'] = op['fecha'].isoformat()
        
        if 'capital_curve' in reporte_serializable:
            reporte_serializable['capital_curve'] = [
                float(v) for v in reporte_serializable['capital_curve']
            ]
        
        with open(ruta_reporte, 'w', encoding='utf-8') as f:
            json.dump(reporte_serializable, f, indent=2, default=str)
        
        logger.info(f"💾 Reporte guardado en: {ruta_reporte}")
        
    except Exception as e:
        logger.warning(f"⚠️ Error guardando reporte: {e}")
    
    return resultado


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Validación completa de estrategia')
    parser.add_argument('--simbolo', '-s', default='EURUSD', help='Símbolo a validar')
    parser.add_argument('--velas', '-n', type=int, default=3000, help='Número de velas H1')
    parser.add_argument('--all', '-a', action='store_true', help='Validar todos los símbolos')
    parser.add_argument('--capital', '-c', type=float, default=1000.0, help='Capital inicial')
    parser.add_argument('--riesgo', '-r', type=float, default=0.01, help='Riesgo por operación')
    
    args = parser.parse_args()
    
    # Intentar cargar módulos del bot
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
        logger.info("   Usando datos de SQLite o archivos locales")
    
    try:
        from data.almacenamiento_sqlite import AlmacenamientoSQLite
        from pathlib import Path
        almacen = AlmacenamientoSQLite(base_dir=Path("data"))
    except Exception as e:
        logger.warning(f"⚠️ No se pudo cargar almacenamiento: {e}")
    
    if args.all:
        simbolos = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD', 'US30']
        resultados = {}
        
        for simbolo in simbolos:
            try:
                logger.info("")
                logger.info("=" * 70)
                resultado = validar_estrategia_completa(simbolo, args.velas, mt5, almacen)
                resultados[simbolo] = resultado
            except Exception as e:
                logger.error(f"❌ Error validando {simbolo}: {e}")
                import traceback
                traceback.print_exc()
                resultados[simbolo] = {'valido': False, 'razon': str(e)}
        
        # Guardar resumen
        ruta_resumen = Path("data") / f"validacion_general_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        ruta_resumen.parent.mkdir(parents=True, exist_ok=True)
        
        resumen = {}
        for simbolo, resultado in resultados.items():
            resumen[simbolo] = {
                'valido': resultado.get('valido', False),
                'pnl': resultado.get('pnl_total', 0),
                'win_rate': resultado.get('win_rate', 0),
                'n_operaciones': resultado.get('n_operaciones', 0),
            }
        
        with open(ruta_resumen, 'w', encoding='utf-8') as f:
            json.dump(resumen, f, indent=2)
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("📊 RESUMEN GENERAL DE VALIDACIÓN")
        logger.info("=" * 70)
        
        for simbolo, stats in resumen.items():
            if stats.get('valido', False):
                logger.info(f"   ✅ {simbolo}: PnL: ${stats['pnl']:.2f}, WinRate: {stats['win_rate']:.1f}%, Ops: {stats['n_operaciones']}")
            else:
                logger.info(f"   ❌ {simbolo}: No válido")
        
        logger.info(f"💾 Resumen guardado en: {ruta_resumen}")
        
    else:
        validar_estrategia_completa(args.simbolo, args.velas, mt5, almacen)