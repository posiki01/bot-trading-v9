#!/usr/bin/env python3
"""
backtesting/backtesting_engine_v2.py (V9.0 - SIMPLIFICADO Y FUNCIONAL)
Backtesting Engine con simulación REALISTA.
"""

import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import logging
import MetaTrader5 as mt5
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import json

from config.settings import Config

logger = logging.getLogger('BotTrading.Backtesting')


class AlmacenMock:
    """Mock de almacenamiento para backtesting."""
    
    def __init__(self):
        self.niveles = {}
        self.operaciones = []
        self.configuracion = {}
        self.watchlist = {}
        self.directorio_base = Path("data")

    def obtener_configuracion(self):
        return self.configuracion

    def guardar_configuracion(self, config):
        if isinstance(config, dict):
            self.configuracion.update(config)

    def obtener_niveles(self, simbolo):
        return self.niveles.get(simbolo, {'soportes': [], 'resistencias': []})

    def guardar_niveles(self, simbolo, soportes, resistencias):
        self.niveles[simbolo] = {'soportes': soportes, 'resistencias': resistencias}

    def guardar_watchlist(self, watchlist):
        self.watchlist = watchlist if watchlist else {}

    def obtener_watchlist(self):
        return self.watchlist

    def guardar_operacion(self, op):
        self.operaciones.append(op)

    def obtener_operaciones(self, filtros=None):
        return self.operaciones

    def guardar_metrica_diaria(self, fecha, metricas):
        pass

    def cerrar(self):
        pass


class BacktesterV2:
    """
    Backtesting Engine simplificado y funcional.
    V9.0 - VERSIÓN FUNCIONAL.
    """

    def __init__(
        self,
        config: Config,
        simbolos: List[str],
        modo_forzado: Optional[str] = None,
        capital_inicial: float = 300.0,
        comision_por_lote: float = 1.0,
        slippage_pips: float = 0.5,
        use_risk_manager: bool = True,
        max_simultaneas: Optional[int] = None,
        max_ops_dia: Optional[int] = None,
        risk_per_trade: Optional[float] = None,
        max_daily_drawdown: Optional[float] = None,
        umbral_fase_1: int = 20,
        use_ml: bool = False,
        modo_depuracion: bool = True,
        max_lote_absoluto: float = 0.005,
        dias_warmup: int = 21,
        zona_horaria: str = 'COLOMBIA',
        fidelidad_real: bool = True,
        usar_precarga: bool = False,
    ):
        self.config = config
        self.simbolos = simbolos
        self.modo_forzado = modo_forzado
        self.dias_warmup = dias_warmup
        self.capital_inicial = capital_inicial
        self.capital_actual = capital_inicial
        self.comision_por_lote = comision_por_lote
        self.slippage_pips = slippage_pips
        self.use_risk_manager = use_risk_manager
        self.umbral_fase_1 = umbral_fase_1
        self.modo_depuracion = modo_depuracion
        self.max_lote_absoluto = max_lote_absoluto
        self.zona_horaria = zona_horaria
        self.fidelidad_real = fidelidad_real
        self.modo_evaluacion = 'REAL' if fidelidad_real else 'DIAGNOSTICO'
        self.almacen_simulado = AlmacenMock()

        # ============================================================
        # PARÁMETROS DE RIESGO
        # ============================================================

        self.max_simultaneas = max_simultaneas or 3
        self.max_ops_dia = max_ops_dia or 8
        self.risk_per_trade = risk_per_trade or 0.01
        self.max_daily_drawdown = max_daily_drawdown or 0.06

        # ============================================================
        # ESTADOS INTERNOS
        # ============================================================

        self.posiciones_abiertas = []
        self.trades = []
        self.equity_curve = [capital_inicial]
        self.timestamps = []
        self.ops_hoy = 0
        self.dia_actual = None
        self.equity_inicio_dia = capital_inicial
        self.simbolos_info = {}
        self.dataframes = {}
        self.fechas_comunes = []
        self._h4_precargados = {}
        self._d1_precargados = {}
        self.cooldowns_simbolos: Dict[str, datetime] = {}
        self.watchlist: Dict[str, datetime] = {}
        self.max_edad_horas = 2
        self._contexto_h1: Dict[str, Dict] = {}

        self.logger = logger
        self.logger.info(f"📊 BacktesterV2 V9.0 inicializado")
        self.logger.info(f"   Símbolos: {len(simbolos)}")
        self.logger.info(f"   Capital: ${capital_inicial:.2f}")
        self.logger.info(f"   Riesgo por operación: {risk_per_trade:.1%}")
        self.logger.info(f"   Umbral F1: {umbral_fase_1}")
        self.logger.info(f"   Warmup: {dias_warmup} días")

    # ================================================================
    # MÉTODOS DE DESCARGA DE DATOS
    # ================================================================

    def _descargar_datos_con_logs(self, simbolo: str, inicio: datetime, fin: datetime) -> Optional[Dict[str, pd.DataFrame]]:
        """Descarga datos de MT5 con logs detallados."""
        self.logger.info(f"   📥 Descargando {simbolo}...")
        
        if not mt5.initialize():
            self.logger.error(f"   ❌ {simbolo}: No se pudo inicializar MT5")
            return None
        
        if not mt5.symbol_select(simbolo, True):
            self.logger.error(f"   ❌ {simbolo}: No existe en Market Watch")
            mt5.shutdown()
            return None
        
        dfs = {}
        tfs = {
            'H1': mt5.TIMEFRAME_H1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
        }
        
        for name, tf in tfs.items():
            try:
                rates = mt5.copy_rates_range(simbolo, tf, inicio, fin)
            except Exception as e:
                self.logger.error(f"      ❌ {simbolo} {name}: Error: {e}")
                continue
            
            if rates is None or len(rates) == 0:
                continue
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            df.index = df.index.tz_localize('UTC')
            df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low',
                'close': 'Close', 'tick_volume': 'Volume'
            }, inplace=True)
            
            dfs[name] = df
        
        mt5.shutdown()
        
        if len(dfs) < 2:
            self.logger.error(f"   ❌ {simbolo}: Datos insuficientes")
            return None
        
        return dfs

    def _resamplear_h4(self, df_h1: pd.DataFrame) -> pd.DataFrame:
        """Resamplea H1 a H4."""
        if df_h1 is None or df_h1.empty:
            return pd.DataFrame()
        try:
            return df_h1.resample('4h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min',
                'Close': 'last', 'Volume': 'sum'
            }).dropna()
        except Exception:
            return pd.DataFrame()

    def _resamplear_d1(self, df_h1: pd.DataFrame) -> pd.DataFrame:
        """Resamplea H1 a D1."""
        if df_h1 is None or df_h1.empty:
            return pd.DataFrame()
        try:
            return df_h1.resample('D').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min',
                'Close': 'last', 'Volume': 'sum'
            }).dropna()
        except Exception:
            return pd.DataFrame()

    # ================================================================
    # MÉTODOS DE ANÁLISIS SIMPLIFICADOS
    # ================================================================

    def _analizar_simbolo(self, simbolo: str, df_h1: pd.DataFrame) -> Dict:
        """Análisis simplificado de símbolo."""
        try:
            close = df_h1['Close']
            high = df_h1['High']
            low = df_h1['Low']
            
            # RSI
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            rsi_actual = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
            
            # EMAs
            ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
            ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
            ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1] if len(close) >= 50 else close.iloc[-1]
            
            # MACD
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = float((macd_line - signal_line).iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else 0
            
            # ATR
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else 0.001
            
            # Determinar dirección
            score = 0
            direccion = 'NEUTRAL'
            
            if rsi_actual > 60:
                score += 1
            if macd_hist > 0:
                score += 1
            if ema9 > ema21:
                score += 1
            
            if score >= 2:
                direccion = 'COMPRA'
            elif score <= -2:
                direccion = 'VENTA'
            
            # Score técnico
            score_tecnico = 50
            if rsi_actual > 60:
                score_tecnico += 15
            elif rsi_actual < 40:
                score_tecnico -= 15
            
            if macd_hist > 0:
                score_tecnico += 10
            else:
                score_tecnico -= 10
            
            if ema9 > ema21:
                score_tecnico += 10
            else:
                score_tecnico -= 10
            
            score_tecnico = max(0, min(100, score_tecnico))
            
            # Detectar niveles simples
            ventana = 20
            soporte = low.iloc[-ventana:].min()
            resistencia = high.iloc[-ventana:].max()
            precio_actual = close.iloc[-1]
            
            soporte_cercano = soporte if (precio_actual - soporte) / precio_actual < 0.02 else None
            resistencia_cercana = resistencia if (resistencia - precio_actual) / precio_actual < 0.02 else None
            
            return {
                'direccion': direccion,
                'score': score_tecnico,
                'rsi': rsi_actual,
                'macd': macd_hist,
                'atr': atr,
                'soporte': soporte_cercano,
                'resistencia': resistencia_cercana,
                'ema9': ema9,
                'ema21': ema21,
                'precio_actual': precio_actual,
            }
            
        except Exception as e:
            self.logger.debug(f"Error analizando {simbolo}: {e}")
            return {
                'direccion': 'NEUTRAL',
                'score': 0,
                'rsi': 50,
                'macd': 0,
                'atr': 0.001,
                'soporte': None,
                'resistencia': None,
            }

    # ================================================================
    # MÉTODOS DE EJECUCIÓN
    # ================================================================

    def _ejecutar_operacion(self, simbolo: str, direccion: str, precio: float, 
                           score: float, fecha: datetime, atr: float = 0.001):
        """Ejecuta una operación."""
        if self.ops_hoy >= self.max_ops_dia:
            return
        
        if len(self.posiciones_abiertas) >= self.max_simultaneas:
            return
        
        # Calcular SL y TP
        pip_val = self._obtener_pip_val(simbolo)
        
        # SL mínimo por activo
        sl_min = self._obtener_sl_minimo(simbolo)
        sl_dist_pips = max(sl_min, atr / pip_val * 1.5 if pip_val > 0 else 20)
        
        if direccion == 'COMPRA':
            sl = precio - (sl_dist_pips * pip_val)
            tp = precio + (sl_dist_pips * 2 * pip_val)
        else:
            sl = precio + (sl_dist_pips * pip_val)
            tp = precio - (sl_dist_pips * 2 * pip_val)
        
        # Calcular lotes
        riesgo_max_usd = self.capital_actual * self.risk_per_trade
        pip_value_per_lot = self._obtener_pip_value_por_lote(simbolo)
        pip_value_por_0_01 = pip_value_per_lot * 0.01
        
        if sl_dist_pips > 0 and pip_value_por_0_01 > 0:
            lotes = riesgo_max_usd / (sl_dist_pips * pip_value_por_0_01)
        else:
            lotes = 0.01
        
        factor_confianza = min(1.5, max(0.5, score / 50.0))
        lotes = lotes * factor_confianza
        lotes = max(0.001, min(self.max_lote_absoluto, lotes))
        lotes = round(lotes, 3)
        
        # Crear operación
        op = {
            'simbolo': simbolo,
            'direccion': direccion,
            'entrada': precio,
            'sl': sl,
            'tp': tp,
            'lotes': lotes,
            'fecha_entrada': fecha,
            'estado': 'ABIERTA',
            'ticket': len(self.trades) + 1,
            'score': score,
            'modo': 'RETEST',
            'regimen': 'INCERTO',
            'sl_original': sl,
            'pnl_acumulado': 0.0,
            'sl_movido_breakeven': False,
            'max_beneficio_alcanzado': 0.0,
        }
        
        self.posiciones_abiertas.append(op)
        self.ops_hoy += 1
        
        self.logger.info(
            f"📈 ENTRADA {simbolo} {direccion} @ {precio:.5f} | "
            f"SL: {sl:.5f} ({sl_dist_pips:.1f}pips) | "
            f"TP: {tp:.5f} | Lotes: {lotes:.3f} | "
            f"Score: {score:.0f} | Equity: ${self.capital_actual:.2f}"
        )

    def _actualizar_operaciones(self, fecha: datetime, df_m5: pd.DataFrame):
        """Actualiza operaciones abiertas."""
        if not self.posiciones_abiertas or df_m5 is None:
            return
        
        df_hasta = df_m5.loc[:fecha]
        if len(df_hasta) < 2:
            return
        
        for pos in self.posiciones_abiertas[:]:
            if pos['estado'] != 'ABIERTA':
                continue
            
            precio_actual = df_hasta['Close'].iloc[-1]
            simbolo = pos['simbolo']
            
            # Determinar pip value
            pip_val = self._obtener_pip_val(simbolo)
            
            # Verificar SL/TP
            if pos['direccion'] == 'COMPRA':
                if df_hasta['Low'].min() <= pos['sl']:
                    self._cerrar_posicion(pos, fecha, pos['sl'], "SL")
                    continue
                if df_hasta['High'].max() >= pos['tp']:
                    self._cerrar_posicion(pos, fecha, pos['tp'], "TP")
                    continue
                
                ganancia_pips = (precio_actual - pos['entrada']) / pip_val if pip_val > 0 else 0
            else:
                if df_hasta['High'].max() >= pos['sl']:
                    self._cerrar_posicion(pos, fecha, pos['sl'], "SL")
                    continue
                if df_hasta['Low'].min() <= pos['tp']:
                    self._cerrar_posicion(pos, fecha, pos['tp'], "TP")
                    continue
                
                ganancia_pips = (pos['entrada'] - precio_actual) / pip_val if pip_val > 0 else 0
            
            # Trailing stop simple
            if ganancia_pips > 20:
                if pos['direccion'] == 'COMPRA':
                    nuevo_sl = precio_actual - (15 * pip_val)
                    if nuevo_sl > pos['sl']:
                        pos['sl'] = nuevo_sl
                else:
                    nuevo_sl = precio_actual + (15 * pip_val)
                    if nuevo_sl < pos['sl']:
                        pos['sl'] = nuevo_sl

    def _cerrar_posicion(self, pos, fecha, precio_salida, motivo):
        """Cierra una posición."""
        if pos['estado'] != 'ABIERTA':
            return
        
        # Calcular PnL
        simbolo = pos['simbolo']
        pip_val = self._obtener_pip_val(simbolo)
        pip_value_per_lot = self._obtener_pip_value_por_lote(simbolo)
        
        if pos['direccion'] == 'COMPRA':
            pips = (precio_salida - pos['entrada']) / pip_val if pip_val > 0 else 0
        else:
            pips = (pos['entrada'] - precio_salida) / pip_val if pip_val > 0 else 0
        
        pnl = pips * pip_value_per_lot * pos['lotes']
        pnl = pnl - (self.comision_por_lote * pos['lotes'] * 2)
        
        self.capital_actual += pnl
        pos['pnl'] = pnl
        pos['pnl_acumulado'] = pnl
        pos['estado'] = 'CERRADA'
        pos['precio_salida'] = precio_salida
        pos['motivo_cierre'] = motivo
        
        self.trades.append(pos.copy())
        self.posiciones_abiertas.remove(pos)
        
        self.logger.info(
            f"📊 CIERRE {simbolo} {pos['direccion']} @ {precio_salida:.5f} | "
            f"PnL: ${pnl:.2f} | Motivo: {motivo} | Equity: ${self.capital_actual:.2f}"
        )

    # ================================================================
    # MÉTODOS DE UTILIDAD
    # ================================================================

    def _obtener_pip_val(self, simbolo: str) -> float:
        """Obtiene el valor de un pip."""
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 0.10
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001

    def _obtener_pip_value_por_lote(self, simbolo: str) -> float:
        """Obtiene el valor por pip para 1 lote."""
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 10.0
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 10.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 10.0

    def _obtener_sl_minimo(self, simbolo: str) -> float:
        """Obtiene SL mínimo en pips."""
        simbolo_upper = simbolo.upper()
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 80.0
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 60.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 35.0
        return 20.0

    # ================================================================
    # MÉTODO PRINCIPAL RUN
    # ================================================================

    def run(self, fecha_inicio: datetime, fecha_fin: datetime) -> Dict[str, Any]:
        """Ejecuta el backtest principal."""
        start_time = time.time()

        self.logger.info(f"🚀 INICIANDO BACKTEST V9.0")
        self.logger.info(f"📅 Rango: {fecha_inicio} → {fecha_fin}")

        # ============================================================
        # DESCARGA DE DATOS
        # ============================================================

        self.logger.info("📥 DESCARGANDO DATOS DESDE MT5...")
        
        for simbolo in self.simbolos:
            dfs = self._descargar_datos_con_logs(simbolo, fecha_inicio, fecha_fin)
            if dfs is None:
                self.logger.error(f"❌ {simbolo}: DESCARGA FALLIDA")
                continue
            
            self.dataframes[simbolo] = dfs
            
            # Precargar H4 y D1
            if 'H4' not in dfs or len(dfs['H4']) < 20:
                self._h4_precargados[simbolo] = self._resamplear_h4(dfs.get('H1', pd.DataFrame()))
            else:
                self._h4_precargados[simbolo] = dfs['H4']

            if 'D1' not in dfs or len(dfs['D1']) < 20:
                self._d1_precargados[simbolo] = self._resamplear_d1(dfs.get('H1', pd.DataFrame()))
            else:
                self._d1_precargados[simbolo] = dfs['D1']

        if not self.dataframes:
            self.logger.error("❌ No se descargaron datos de ningún símbolo")
            return {'error': 'No data'}

        # ============================================================
        # CALCULAR FECHAS COMUNES
        # ============================================================

        fechas_h1 = None
        fechas_m5 = None
        
        for simbolo, dfs in self.dataframes.items():
            df_h1 = dfs.get('H1', pd.DataFrame())
            df_m5 = dfs.get('M5', pd.DataFrame())
            
            if fechas_h1 is None:
                fechas_h1 = df_h1.index
                fechas_m5 = df_m5.index
            else:
                fechas_h1 = fechas_h1.intersection(df_h1.index)
                fechas_m5 = fechas_m5.intersection(df_m5.index)

        self.fechas_comunes = sorted(fechas_h1)
        fechas_m5_comunes = sorted(fechas_m5)
        set_fechas_h1 = set(self.fechas_comunes)
        pos_h1 = {f: i for i, f in enumerate(self.fechas_comunes)}

        self.logger.info(f"📊 Fechas comunes H1: {len(self.fechas_comunes)}")
        self.logger.info(f"📊 Fechas comunes M5: {len(fechas_m5_comunes)}")

        if len(self.fechas_comunes) < 20:
            return {'error': 'Fechas H1 insuficientes'}

        # ============================================================
        # BUCLE PRINCIPAL
        # ============================================================

        self.equity_curve = [self.capital_inicial]
        self.timestamps = [fechas_m5_comunes[0]] if fechas_m5_comunes else [fecha_inicio]

        self._contexto_h1 = {}
        ultima_hora_h1_procesada = None

        total_velas = len(fechas_m5_comunes)
        velas_procesadas = 0

        self.logger.info(f"🚀 Iniciando simulación: {total_velas} velas M5")

        # Variables para estadísticas
        analisis_realizados = 0
        senales_generadas = 0
        operaciones_ejecutadas = 0

        for idx, fecha_m5 in enumerate(fechas_m5_comunes):
            if idx % 1000 == 0 and idx > 0:
                elapsed = time.time() - start_time
                self.logger.info(f"⏳ Progreso: {idx/total_velas*100:.1f}% | "
                           f"Ops: {len(self.trades)} | Equity: ${self.capital_actual:.2f}")

            if fecha_m5.tzinfo is None:
                fecha_m5 = fecha_m5.replace(tzinfo=timezone.utc)

            # Reset diario
            if self.dia_actual != fecha_m5.date():
                self.dia_actual = fecha_m5.date()
                self.ops_hoy = 0
                self.equity_inicio_dia = self.capital_actual

            # Procesar nueva vela H1
            fecha_h1_actual = fecha_m5.floor('h')
            idx_h1 = pos_h1.get(fecha_h1_actual)
            
            if idx_h1 is None or idx_h1 < 20:
                continue

            hay_h1_nueva = (ultima_hora_h1_procesada is None or fecha_h1_actual > ultima_hora_h1_procesada) and fecha_h1_actual in set_fechas_h1

            if hay_h1_nueva:
                ultima_hora_h1_procesada = fecha_h1_actual
                velas_procesadas += 1
                
                if velas_procesadas % 20 == 0:
                    self.logger.info(f"📊 Procesando H1 #{velas_procesadas}: {fecha_h1_actual}")
                
                for simbolo, dfs in self.dataframes.items():
                    df_h1_hasta = dfs.get('H1', pd.DataFrame()).loc[:fecha_h1_actual]
                    
                    if len(df_h1_hasta) < 20:
                        continue
                    
                    # Análisis simplificado
                    analisis = self._analizar_simbolo(simbolo, df_h1_hasta)
                    analisis_realizados += 1
                    
                    if analisis['direccion'] == 'NEUTRAL':
                        continue
                    
                    if analisis['score'] < self.umbral_fase_1:
                        continue
                    
                    senales_generadas += 1
                    
                    # Guardar en contexto
                    self._contexto_h1[simbolo] = {
                        'direccion': analisis['direccion'],
                        'score': analisis['score'],
                        'precio': analisis['precio_actual'],
                        'atr': analisis['atr'],
                        'soporte': analisis['soporte'],
                        'resistencia': analisis['resistencia'],
                        'timestamp': fecha_h1_actual,
                        'rsi': analisis['rsi'],
                        'macd': analisis['macd'],
                    }

            # ============================================================
            # EVALUAR OPORTUNIDADES (SNIPER SIMPLIFICADO)
            # ============================================================

            if len(self.posiciones_abiertas) >= self.max_simultaneas:
                continue

            if self.ops_hoy >= self.max_ops_dia:
                continue

            for simbolo in list(self._contexto_h1.keys()):
                ctx = self._contexto_h1.get(simbolo)
                if not ctx:
                    continue

                # Verificar cooldown
                cooldown_hasta = self.cooldowns_simbolos.get(simbolo)
                if cooldown_hasta and fecha_m5 < cooldown_hasta:
                    continue

                # Verificar posición abierta
                if any(p['simbolo'] == simbolo for p in self.posiciones_abiertas):
                    continue

                direccion = ctx.get('direccion', 'NEUTRAL')
                score = ctx.get('score', 0)
                precio = ctx.get('precio', 0)
                atr = ctx.get('atr', 0.001)

                # Ejecutar operación
                self._ejecutar_operacion(
                    simbolo=simbolo,
                    direccion=direccion,
                    precio=precio,
                    score=score,
                    fecha=fecha_m5,
                    atr=atr
                )
                operaciones_ejecutadas += 1

                # Limpiar contexto después de ejecutar
                if simbolo in self._contexto_h1:
                    del self._contexto_h1[simbolo]

                # Cooldown
                self.cooldowns_simbolos[simbolo] = fecha_m5 + timedelta(hours=2)

            # ============================================================
            # ACTUALIZAR STOPS
            # ============================================================

            for simbolo, dfs in self.dataframes.items():
                df_m5 = dfs.get('M5')
                if df_m5 is not None and len(df_m5) > 0:
                    self._actualizar_operaciones(fecha_m5, df_m5)

        # ============================================================
        # FIN DEL BACKTEST
        # ============================================================

        elapsed = time.time() - start_time

        self.logger.info("")
        self.logger.info(f"📊 RESUMEN DE ANÁLISIS:")
        self.logger.info(f"   Análisis realizados: {analisis_realizados}")
        self.logger.info(f"   Señales generadas: {senales_generadas}")
        self.logger.info(f"   Operaciones ejecutadas: {operaciones_ejecutadas}")
        self.logger.info(f"   Operaciones totales: {len(self.trades)}")
        self.logger.info(f"   Capital final: ${self.capital_actual:.2f}")

        return self._calcular_metricas()

    # ================================================================
    # MÉTRICAS
    # ================================================================

    def _calcular_metricas(self):
        """Calcula métricas del backtest."""
        if not self.trades:
            return {
                'mensaje': 'Sin operaciones',
                'total_operaciones': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'net_profit': 0,
                'total_return': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'capital_final': self.capital_actual,
                'trades': [],
                'equity_curve': self.equity_curve,
            }

        df_trades = pd.DataFrame(self.trades)
        total = len(df_trades)
        ganadoras = df_trades[df_trades['pnl'] > 0]
        win_rate = len(ganadoras) / total * 100 if total > 0 else 0
        gross_profit = ganadoras['pnl'].sum() if not ganadoras.empty else 0
        gross_loss = abs(df_trades[df_trades['pnl'] < 0]['pnl'].sum()) if not df_trades[df_trades['pnl'] < 0].empty else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
        total_return = (self.capital_actual / self.capital_inicial - 1) * 100
        
        # Drawdown
        peak = self.capital_inicial
        max_dd = 0.0
        for val in self.equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd = max(0.0, (peak - val) / peak * 100)
                if dd > max_dd:
                    max_dd = dd

        # Sharpe Ratio
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

        return {
            'total_operaciones': total,
            'ganadoras': len(ganadoras),
            'perdedoras': total - len(ganadoras),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'net_profit': gross_profit - gross_loss,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'sharpe_ratio': sharpe,
            'capital_final': self.capital_actual,
            'trades': self.trades,
            'equity_curve': self.equity_curve,
        }

    def guardar_reporte(self, ruta: Path):
        """Guarda reporte en JSON."""
        metricas = self._calcular_metricas()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(metricas, f, indent=2, default=str)

    def guardar_equity_curve(self, ruta: Path):
        """Guarda equity curve en CSV."""
        import csv
        if not self.equity_curve or not self.timestamps:
            return

        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'equity'])
            for ts, eq in zip(self.timestamps, self.equity_curve):
                writer.writerow([ts.isoformat(), eq])