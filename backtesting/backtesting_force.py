#!/usr/bin/env python3
"""
backtesting/backtesting_force.py - VERSIÓN QUE FUERZA OPERACIONES
Para diagnosticar por qué no se ejecutan operaciones.
"""

import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import logging
import MetaTrader5 as mt5
from pathlib import Path
from typing import Dict, Any, List, Optional

from config.settings import Config

logger = logging.getLogger('BotTrading.BacktestingForce')


class BacktesterForce:
    """
    Backtesting que FUERZA operaciones para diagnóstico.
    """
    
    def __init__(
        self,
        config: Config,
        simbolos: List[str],
        capital_inicial: float = 300.0,
        modo_depuracion: bool = True,
        max_ops_dia: int = 10,
        risk_per_trade: float = 0.01,
    ):
        self.config = config
        self.simbolos = simbolos
        self.capital_inicial = capital_inicial
        self.capital_actual = capital_inicial
        self.modo_depuracion = modo_depuracion
        self.max_ops_dia = max_ops_dia
        self.risk_per_trade = risk_per_trade
        
        self.logger = logging.getLogger('BotTrading.BacktestingForce')
        
        # Estados
        self.posiciones_abiertas = []
        self.trades = []
        self.equity_curve = [capital_inicial]
        self.timestamps = []
        self.ops_hoy = 0
        self.dia_actual = None
        self.dataframes = {}
        self.fechas_comunes = []
        
        # Estadísticas
        self.analisis_realizados = 0
        self.senales_generadas = 0
        self.operaciones_ejecutadas = 0
        
        self.logger.info(f"📊 BacktesterForce V1.0 inicializado")
        self.logger.info(f"   Símbolos: {len(simbolos)}")
        self.logger.info(f"   Capital: ${capital_inicial:.2f}")
        self.logger.info(f"   Max ops/día: {max_ops_dia}")

    # ================================================================
    # DESCARGA DE DATOS
    # ================================================================

    def _descargar_datos(self, simbolo: str, inicio: datetime, fin: datetime) -> Optional[Dict[str, pd.DataFrame]]:
        """Descarga datos de MT5."""
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
        }
        
        for name, tf in tfs.items():
            try:
                rates = mt5.copy_rates_range(simbolo, tf, inicio, fin)
            except Exception as e:
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
            return None
        
        return dfs

    # ================================================================
    # ANÁLISIS SIMPLIFICADO QUE SIEMPRE GENERA SEÑALES
    # ================================================================

    def _analizar_simbolo_force(self, simbolo: str, df_h1: pd.DataFrame) -> Dict:
        """Análisis que SIEMPRE genera señales para pruebas."""
        try:
            close = df_h1['Close']
            high = df_h1['High']
            low = df_h1['Low']
            
            # Calcular RSI
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
            
            # 🔥 FORZAR SEÑALES - SIEMPRE GENERA UNA SEÑAL
            precio_actual = close.iloc[-1]
            precio_anterior = close.iloc[-2] if len(close) > 1 else precio_actual
            
            # Determinar dirección basada en precio
            if precio_actual > precio_anterior:
                direccion = 'COMPRA'
                score = 65 + (rsi_actual / 100) * 20
            elif precio_actual < precio_anterior:
                direccion = 'VENTA'
                score = 65 + ((100 - rsi_actual) / 100) * 20
            else:
                # Si es lateral, usar RSI
                if rsi_actual > 55:
                    direccion = 'COMPRA'
                    score = 60
                elif rsi_actual < 45:
                    direccion = 'VENTA'
                    score = 60
                else:
                    direccion = 'COMPRA'  # Default
                    score = 55
            
            score = min(100, max(40, score))
            
            # Detectar niveles simples
            ventana = 20
            soporte = low.iloc[-ventana:].min()
            resistencia = high.iloc[-ventana:].max()
            
            soporte_cercano = soporte if (precio_actual - soporte) / precio_actual < 0.02 else None
            resistencia_cercana = resistencia if (resistencia - precio_actual) / precio_actual < 0.02 else None
            
            return {
                'direccion': direccion,
                'score': score,
                'rsi': rsi_actual,
                'macd': macd_hist,
                'atr': atr,
                'soporte': soporte_cercano,
                'resistencia': resistencia_cercana,
                'precio_actual': precio_actual,
                'ema9': ema9,
                'ema21': ema21,
            }
            
        except Exception as e:
            self.logger.debug(f"Error analizando {simbolo}: {e}")
            return {
                'direccion': 'COMPRA',
                'score': 50,
                'rsi': 50,
                'macd': 0,
                'atr': 0.001,
                'soporte': None,
                'resistencia': None,
                'precio_actual': 1.0,
            }

    # ================================================================
    # EJECUCIÓN DE OPERACIONES
    # ================================================================

    def _ejecutar_operacion(self, simbolo: str, direccion: str, precio: float, 
                           score: float, fecha: datetime, atr: float = 0.001):
        """Ejecuta una operación."""
        if self.ops_hoy >= self.max_ops_dia:
            self.logger.info(f"   ⏸️ Límite diario alcanzado: {self.ops_hoy}/{self.max_ops_dia}")
            return
        
        if len(self.posiciones_abiertas) >= 3:  # Máximo 3 posiciones
            self.logger.info(f"   ⏸️ Máximo de posiciones alcanzado: {len(self.posiciones_abiertas)}")
            return
        
        # ============================================================
        # CALCULAR SL Y TP
        # ============================================================
        
        pip_val = self._obtener_pip_val(simbolo)
        sl_dist_pips = 20  # SL fijo de 20 pips para pruebas
        
        if direccion == 'COMPRA':
            sl = precio - (sl_dist_pips * pip_val)
            tp = precio + (sl_dist_pips * 2.0 * pip_val)  # R:R 2.0
        else:
            sl = precio + (sl_dist_pips * pip_val)
            tp = precio - (sl_dist_pips * 2.0 * pip_val)
        
        # ============================================================
        # CALCULAR LOTES
        # ============================================================
        
        riesgo_max_usd = self.capital_actual * self.risk_per_trade
        pip_value_per_lot = self._obtener_pip_value_por_lote(simbolo)
        pip_value_por_0_01 = pip_value_per_lot * 0.01
        
        if sl_dist_pips > 0 and pip_value_por_0_01 > 0:
            lotes = riesgo_max_usd / (sl_dist_pips * pip_value_por_0_01)
        else:
            lotes = 0.01
        
        factor_confianza = min(1.5, max(0.5, score / 50.0))
        lotes = lotes * factor_confianza
        lotes = max(0.001, min(0.02, lotes))  # Lote máximo 0.02
        lotes = round(lotes, 3)
        
        # ============================================================
        # CREAR OPERACIÓN
        # ============================================================
        
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
            'modo': 'FORZADO',
            'regimen': 'TEST',
            'sl_original': sl,
            'pnl_acumulado': 0.0,
        }
        
        self.posiciones_abiertas.append(op)
        self.ops_hoy += 1
        self.operaciones_ejecutadas += 1
        
        self.logger.info(
            f"📈 ENTRADA {simbolo} {direccion} @ {precio:.5f} | "
            f"SL: {sl:.5f} ({sl_dist_pips:.1f}pips) | "
            f"TP: {tp:.5f} | Lotes: {lotes:.3f} | "
            f"Score: {score:.0f} | Ops hoy: {self.ops_hoy}/{self.max_ops_dia}"
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
            
            # Trailing stop simple (para pruebas)
            if ganancia_pips > 25:
                if pos['direccion'] == 'COMPRA':
                    nuevo_sl = precio_actual - (15 * pip_val)
                    if nuevo_sl > pos['sl']:
                        pos['sl'] = nuevo_sl
                        self.logger.debug(f"   🔄 {simbolo}: SL movido a {nuevo_sl:.5f}")
                else:
                    nuevo_sl = precio_actual + (15 * pip_val)
                    if nuevo_sl < pos['sl']:
                        pos['sl'] = nuevo_sl
                        self.logger.debug(f"   🔄 {simbolo}: SL movido a {nuevo_sl:.5f}")

    def _cerrar_posicion(self, pos, fecha, precio_salida, motivo):
        """Cierra una posición."""
        if pos['estado'] != 'ABIERTA':
            return
        
        simbolo = pos['simbolo']
        pip_val = self._obtener_pip_val(simbolo)
        pip_value_per_lot = self._obtener_pip_value_por_lote(simbolo)
        
        if pos['direccion'] == 'COMPRA':
            pips = (precio_salida - pos['entrada']) / pip_val if pip_val > 0 else 0
        else:
            pips = (pos['entrada'] - precio_salida) / pip_val if pip_val > 0 else 0
        
        pnl = pips * pip_value_per_lot * pos['lotes']
        
        self.capital_actual += pnl
        pos['pnl'] = pnl
        pos['estado'] = 'CERRADA'
        pos['precio_salida'] = precio_salida
        pos['motivo_cierre'] = motivo
        
        self.trades.append(pos.copy())
        self.posiciones_abiertas.remove(pos)
        
        self.logger.info(
            f"📊 CIERRE {simbolo} {pos['direccion']} | "
            f"PnL: ${pnl:.2f} | Motivo: {motivo} | Equity: ${self.capital_actual:.2f}"
        )

    # ================================================================
    # UTILIDADES
    # ================================================================

    def _obtener_pip_val(self, simbolo: str) -> float:
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 0.10
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        return 0.0001

    def _obtener_pip_value_por_lote(self, simbolo: str) -> float:
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 10.0
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 10.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        return 10.0

    # ================================================================
    # MÉTODO PRINCIPAL
    # ================================================================

    def run(self, fecha_inicio: datetime, fecha_fin: datetime) -> Dict[str, Any]:
        """Ejecuta el backtest forzando operaciones."""
        start_time = time.time()

        self.logger.info(f"🚀 INICIANDO BACKTEST FORZADO")
        self.logger.info(f"📅 Rango: {fecha_inicio} → {fecha_fin}")

        # ============================================================
        # DESCARGAR DATOS
        # ============================================================
        
        self.logger.info("📥 DESCARGANDO DATOS...")
        
        for simbolo in self.simbolos:
            dfs = self._descargar_datos(simbolo, fecha_inicio, fecha_fin)
            if dfs is None:
                self.logger.error(f"❌ {simbolo}: DESCARGA FALLIDA")
                continue
            
            self.dataframes[simbolo] = dfs

        if not self.dataframes:
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

        ultima_hora_h1_procesada = None
        total_velas = len(fechas_m5_comunes)

        self.logger.info(f"🚀 Iniciando simulación: {total_velas} velas M5")
        self.logger.info(f"   📊 Cada H1 generará una señal FORZADA")

        for idx, fecha_m5 in enumerate(fechas_m5_comunes):
            if idx % 500 == 0 and idx > 0:
                elapsed = time.time() - start_time
                self.logger.info(f"⏳ Progreso: {idx/total_velas*100:.1f}% | "
                           f"Ops: {len(self.trades)} | Equity: ${self.capital_actual:.2f}")

            if fecha_m5.tzinfo is None:
                fecha_m5 = fecha_m5.replace(tzinfo=timezone.utc)

            # Reset diario
            if self.dia_actual != fecha_m5.date():
                self.dia_actual = fecha_m5.date()
                self.ops_hoy = 0
                self.logger.info(f"📅 Nuevo día: {self.dia_actual}")

            # Procesar nueva vela H1
            fecha_h1_actual = fecha_m5.floor('h')
            idx_h1 = pos_h1.get(fecha_h1_actual)
            
            if idx_h1 is None or idx_h1 < 20:
                continue

            hay_h1_nueva = (ultima_hora_h1_procesada is None or fecha_h1_actual > ultima_hora_h1_procesada) and fecha_h1_actual in set_fechas_h1

            if hay_h1_nueva:
                ultima_hora_h1_procesada = fecha_h1_actual
                self.analisis_realizados += 1
                
                if self.analisis_realizados % 10 == 0:
                    self.logger.info(f"📊 Analizando H1 #{self.analisis_realizados}: {fecha_h1_actual}")
                
                for simbolo, dfs in self.dataframes.items():
                    df_h1_hasta = dfs.get('H1', pd.DataFrame()).loc[:fecha_h1_actual]
                    
                    if len(df_h1_hasta) < 20:
                        continue
                    
                    # 🔥 FORZAR ANÁLISIS - SIEMPRE GENERA SEÑAL
                    analisis = self._analizar_simbolo_force(simbolo, df_h1_hasta)
                    self.senales_generadas += 1
                    
                    self.logger.info(
                        f"   📊 {simbolo}: {analisis['direccion']} | "
                        f"Score: {analisis['score']:.0f} | "
                        f"RSI: {analisis['rsi']:.0f} | "
                        f"Precio: {analisis['precio_actual']:.5f}"
                    )
                    
                    # ============================================================
                    # 🔥 SIEMPRE EJECUTAR OPERACIÓN (FORZADO)
                    # ============================================================
                    
                    # Verificar límites
                    if self.ops_hoy >= self.max_ops_dia:
                        self.logger.info(f"   ⏸️ Límite diario alcanzado para {simbolo}")
                        continue
                    
                    if len(self.posiciones_abiertas) >= 3:
                        continue
                    
                    # Ejecutar operación
                    self._ejecutar_operacion(
                        simbolo=simbolo,
                        direccion=analisis['direccion'],
                        precio=analisis['precio_actual'],
                        score=analisis['score'],
                        fecha=fecha_m5,
                        atr=analisis['atr']
                    )

            # ============================================================
            # ACTUALIZAR OPERACIONES
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
        self.logger.info(f"   Análisis realizados: {self.analisis_realizados}")
        self.logger.info(f"   Señales generadas: {self.senales_generadas}")
        self.logger.info(f"   Operaciones ejecutadas: {self.operaciones_ejecutadas}")
        self.logger.info(f"   Operaciones totales: {len(self.trades)}")
        self.logger.info(f"   Capital final: ${self.capital_actual:.2f}")

        return self._calcular_metricas()

    # ================================================================
    # MÉTRICAS
    # ================================================================

    def _calcular_metricas(self):
        if not self.trades:
            return {
                'mensaje': 'Sin operaciones',
                'total_operaciones': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'net_profit': 0,
                'total_return': 0,
                'max_drawdown': 0,
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
        
        peak = self.capital_inicial
        max_dd = 0.0
        for val in self.equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd = max(0.0, (peak - val) / peak * 100)
                if dd > max_dd:
                    max_dd = dd

        return {
            'total_operaciones': total,
            'ganadoras': len(ganadoras),
            'perdedoras': total - len(ganadoras),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'net_profit': gross_profit - gross_loss,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'capital_final': self.capital_actual,
            'trades': self.trades,
            'equity_curve': self.equity_curve,
        }

    def guardar_reporte(self, ruta: Path):
        import json
        metricas = self._calcular_metricas()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(metricas, f, indent=2, default=str)


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_backtester_force(config, simbolos, **kwargs):
    return BacktesterForce(config=config, simbolos=simbolos, **kwargs)