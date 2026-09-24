#!/usr/bin/env python3
"""
validar_estrategia_original_timeframes.py (V4.1 - CORREGIDO)
Valida la estrategia original con operación única.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging
import sys
import json
import time

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-7s | %(message)s')
logger = logging.getLogger('ValidarOriginalTF')


# ============================================================
# OBTENER DATOS
# ============================================================

def obtener_datos(mt5: Any, simbolo: str, timeframe: int, n_velas: int = 2000) -> Optional[pd.DataFrame]:
    """Obtiene datos del timeframe especificado."""
    if mt5:
        try:
            df = mt5.obtener_datos(simbolo, n_velas=n_velas, timeframe=timeframe)
            if df is not None and len(df) > 0:
                logger.info(f"✅ {simbolo} TF{timeframe}: {len(df)} velas")
                return df
        except Exception as e:
            logger.warning(f"⚠️ {simbolo} TF{timeframe}: Error: {e}")
    return None


# ============================================================
# CALCULAR INDICADORES
# ============================================================

def calcular_todos_indicadores(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """Calcula todos los indicadores."""
    close = df['Close']
    high = df['High']
    low = df['Low']
    
    indicadores = {
        'RSI': calcular_rsi(close, 14),
        'MACD_line': calcular_ema(close, 12) - calcular_ema(close, 26),
        'MACD_signal': (calcular_ema(close, 12) - calcular_ema(close, 26)).ewm(span=9, adjust=False).mean(),
        'MACD_hist': (calcular_ema(close, 12) - calcular_ema(close, 26)) - (calcular_ema(close, 12) - calcular_ema(close, 26)).ewm(span=9, adjust=False).mean(),
        'BB_upper': calcular_bb_upper(close),
        'BB_middle': close.rolling(20).mean(),
        'BB_lower': calcular_bb_lower(close),
        'BB_width': (calcular_bb_upper(close) - calcular_bb_lower(close)) / close.rolling(20).mean() * 100,
        'EMA9': close.ewm(span=9, adjust=False).mean(),
        'EMA21': close.ewm(span=21, adjust=False).mean(),
        'EMA50': close.ewm(span=50, adjust=False).mean(),
        'ADX': calcular_adx(df),
        'ATR': calcular_atr(df),
        'Ichimoku_tenkan': (high.rolling(9).max() + low.rolling(9).min()) / 2,
        'Ichimoku_kijun': (high.rolling(26).max() + low.rolling(26).min()) / 2,
        'Ichimoku_senkou_a': ((high.rolling(9).max() + low.rolling(9).min()) / 2 + (high.rolling(26).max() + low.rolling(26).min()) / 2) / 2,
        'Ichimoku_senkou_b': (high.rolling(52).max() + low.rolling(52).min()) / 2,
        'Donchian_upper': high.rolling(20).max(),
        'Donchian_lower': low.rolling(20).min(),
        'Donchian_posicion': (close - low.rolling(20).min()) / (high.rolling(20).max() - low.rolling(20).min()),
        'VIX_proxy': (calcular_atr(df) / close) * 100,
        'ER_Kaufman': calcular_er_kaufman(close),
        'Chop_Index': calcular_chop_index(df),
    }
    
    return indicadores


def calcular_rsi(precios: pd.Series, periodo: int = 14) -> pd.Series:
    delta = precios.diff()
    ganancia = (delta.where(delta > 0, 0.0)).rolling(periodo).mean()
    perdida = (-delta.where(delta < 0, 0.0)).rolling(periodo).mean()
    rs = ganancia / perdida
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def calcular_ema(precios: pd.Series, periodo: int) -> pd.Series:
    return precios.ewm(span=periodo, adjust=False).mean()


def calcular_bb_upper(close: pd.Series, periodo: int = 20, desv: int = 2) -> pd.Series:
    sma = close.rolling(periodo).mean()
    std = close.rolling(periodo).std()
    return sma + (std * desv)


def calcular_bb_lower(close: pd.Series, periodo: int = 20, desv: int = 2) -> pd.Series:
    sma = close.rolling(periodo).mean()
    std = close.rolling(periodo).std()
    return sma - (std * desv)


def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    high, low, close = df['High'], df['Low'], df['Close']
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(periodo).mean()


def calcular_adx(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    high, low, close = df['High'], df['Low'], df['Close']
    
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(periodo).mean()
    atr_seguro = atr.replace(0, np.nan)
    
    up_move = high.diff()
    down_move = -low.diff()
    
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    
    plus_di = 100 * plus_dm.rolling(periodo).mean() / atr_seguro
    minus_di = 100 * minus_dm.rolling(periodo).mean() / atr_seguro
    
    di_suma = plus_di + minus_di
    di_suma_segura = di_suma.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_suma_segura
    
    return dx.rolling(periodo).mean()


def calcular_er_kaufman(close: pd.Series, periodo: int = 10) -> pd.Series:
    cambio = (close - close.shift(periodo)).abs()
    volatilidad = close.diff().abs().rolling(periodo).sum()
    er = cambio / volatilidad.replace(0, np.nan)
    return er.fillna(0.0)


def calcular_chop_index(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    high, low, close = df['High'], df['Low'], df['Close']
    
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_sum = tr.rolling(periodo).sum()
    rango = high.rolling(periodo).max() - low.rolling(periodo).min()
    
    chop = 100 * np.log10(atr_sum / rango.replace(0, np.nan)) / np.log10(periodo)
    return chop.fillna(50.0)


# ============================================================
# SIMULAR ESTRATEGIA (V4.1 - CON OPERACIÓN ÚNICA)
# ============================================================

def simular_estrategia(df: pd.DataFrame, indicadores: Dict[str, pd.Series]) -> Dict:
    """Simula estrategia con operación única (sin superposiciones)."""
    close = df['Close']
    operaciones = []
    capital = 1000.0
    
    # Variables para operación abierta
    operacion_abierta = None
    
    # Definir condiciones_venta ANTES del bucle (✅ CORREGIDO)
    condiciones_venta = []
    
    for i in range(50, len(df) - 10):
        precio = close.iloc[i]
        
        # ✅ 1. SI HAY OPERACIÓN ABIERTA, VERIFICAR CIERRE
        if operacion_abierta:
            resultado = verificar_cierre(df, i, operacion_abierta)
            if resultado:
                operaciones.append(resultado)
                capital += resultado['pnl']
                operacion_abierta = None
                # ✅ NO continuar a la siguiente vela sin cerrar
        
        # ✅ 2. SOLO ENTRAR SI NO HAY OPERACIÓN ABIERTA
        if operacion_abierta is None:
            # Obtener valores de indicadores
            rsi = indicadores['RSI'].iloc[i]
            macd_line = indicadores['MACD_line'].iloc[i]
            macd_signal = indicadores['MACD_signal'].iloc[i]
            bb_upper = indicadores['BB_upper'].iloc[i]
            bb_lower = indicadores['BB_lower'].iloc[i]
            ema9 = indicadores['EMA9'].iloc[i]
            ema21 = indicadores['EMA21'].iloc[i]
            ema50 = indicadores['EMA50'].iloc[i]
            adx = indicadores['ADX'].iloc[i]
            atr = indicadores['ATR'].iloc[i]
            
            # ✅ Señal de COMPRA (al menos 2 de 5)
            condiciones_compra = [
                rsi < 30,
                macd_line > macd_signal,
                ema9 > ema21 > ema50,
                adx > 25,
                precio < bb_lower * 1.002,
            ]
            
            # ✅ Señal de VENTA (al menos 2 de 5)
            condiciones_venta = [
                rsi > 70,
                macd_line < macd_signal,
                ema9 < ema21 < ema50,
                adx > 25,
                precio > bb_upper * 0.998,
            ]
            
            if sum(condiciones_compra) >= 2:
                sl = precio - (atr * 2.5)
                tp = precio + (atr * 4.0)
                
                # Calcular lotes
                sl_dist = abs(precio - sl)
                lotes = (capital * 0.01) / (sl_dist * 100000)
                lotes = max(0.01, min(0.10, round(lotes, 2)))
                
                # Abrir operación
                operacion_abierta = {
                    'fecha_entrada': df.index[i],
                    'direccion': 'COMPRA',
                    'precio_entrada': precio,
                    'sl': sl,
                    'tp': tp,
                    'lotes': lotes,
                    'index_entrada': i,
                }
            
            # Señal de VENTA
            elif sum(condiciones_venta) >= 2:
                sl = precio + (atr * 2.5)
                tp = precio - (atr * 4.0)
                
                # Calcular lotes
                sl_dist = abs(precio - sl)
                lotes = (capital * 0.01) / (sl_dist * 100000)
                lotes = max(0.01, min(0.10, round(lotes, 2)))
                
                # Abrir operación
                operacion_abierta = {
                    'fecha_entrada': df.index[i],
                    'direccion': 'VENTA',
                    'precio_entrada': precio,
                    'sl': sl,
                    'tp': tp,
                    'lotes': lotes,
                    'index_entrada': i,
                }
    
    # Cerrar operación pendiente al final
    if operacion_abierta:
        precio_final = close.iloc[-1]
        direccion = operacion_abierta['direccion']
        precio_entrada = operacion_abierta['precio_entrada']
        
        if direccion == 'COMPRA':
            pnl = (precio_final - precio_entrada) * operacion_abierta['lotes']
            resultado = 'TIMEOUT'
        else:
            pnl = (precio_entrada - precio_final) * operacion_abierta['lotes']
            resultado = 'TIMEOUT'
        
        operaciones.append({
            'fecha': operacion_abierta['fecha_entrada'],
            'direccion': direccion,
            'precio_entrada': precio_entrada,
            'sl': operacion_abierta['sl'],
            'tp': operacion_abierta['tp'],
            'lotes': operacion_abierta['lotes'],
            'pnl': pnl,
            'resultado': resultado,
        })
    
    # Calcular métricas
    if operaciones:
        ganadoras = [op for op in operaciones if op['pnl'] > 0]
        perdedoras = [op for op in operaciones if op['pnl'] < 0]
        win_rate = len(ganadoras) / len(operaciones) * 100
        pnl_total = sum(op['pnl'] for op in operaciones)
        profit_factor = abs(sum(op['pnl'] for op in ganadoras) / sum(op['pnl'] for op in perdedoras)) if perdedoras else 0
    else:
        win_rate = 0
        pnl_total = 0
        profit_factor = 0
    
    return {
        'capital_final': capital,
        'pnl_total': pnl_total,
        'win_rate': win_rate,
        'n_operaciones': len(operaciones),
        'profit_factor': profit_factor,
        'operaciones': operaciones,
    }


def verificar_cierre(df: pd.DataFrame, index: int, operacion: Dict) -> Optional[Dict]:
    """Verifica si la operación se cerró en la vela actual."""
    precio = df['Close'].iloc[index]
    direccion = operacion['direccion']
    precio_entrada = operacion['precio_entrada']
    sl = operacion['sl']
    tp = operacion['tp']
    lotes = operacion['lotes']
    
    if direccion == 'COMPRA':
        if precio <= sl:
            return {
                'fecha': df.index[index],
                'direccion': direccion,
                'precio_entrada': precio_entrada,
                'sl': sl,
                'tp': tp,
                'lotes': lotes,
                'pnl': (sl - precio_entrada) * lotes,
                'resultado': 'SL',
            }
        if precio >= tp:
            return {
                'fecha': df.index[index],
                'direccion': direccion,
                'precio_entrada': precio_entrada,
                'sl': sl,
                'tp': tp,
                'lotes': lotes,
                'pnl': (tp - precio_entrada) * lotes,
                'resultado': 'TP',
            }
    else:
        if precio >= sl:
            return {
                'fecha': df.index[index],
                'direccion': direccion,
                'precio_entrada': precio_entrada,
                'sl': sl,
                'tp': tp,
                'lotes': lotes,
                'pnl': (precio_entrada - sl) * lotes,
                'resultado': 'SL',
            }
        if precio <= tp:
            return {
                'fecha': df.index[index],
                'direccion': direccion,
                'precio_entrada': precio_entrada,
                'sl': sl,
                'tp': tp,
                'lotes': lotes,
                'pnl': (precio_entrada - tp) * lotes,
                'resultado': 'TP',
            }
    
    return None


# ============================================================
# ANÁLISIS DE PODER PREDICTIVO
# ============================================================

def analizar_correlaciones(df: pd.DataFrame, indicadores: Dict[str, pd.Series], horizonte: int = 10) -> Dict[str, float]:
    retorno_futuro = df['Close'].shift(-horizonte) / df['Close'] - 1
    
    resultados = {}
    for nombre, serie in indicadores.items():
        datos = pd.concat([serie, retorno_futuro], axis=1).dropna()
        if len(datos) > 30:
            corr = datos.iloc[:, 0].corr(datos.iloc[:, 1])
            if not pd.isna(corr):
                resultados[nombre] = float(corr)
    
    return dict(sorted(resultados.items(), key=lambda x: abs(x[1]), reverse=True))


# ============================================================
# MAIN
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Validar estrategia original con operación única')
    parser.add_argument('--simbolo', '-s', default='EURUSD', help='Símbolo')
    parser.add_argument('--tf', '-t', type=int, default=240, help='Timeframe (240=H4, 1440=D1)')
    parser.add_argument('--velas', '-n', type=int, default=2000, help='Número de velas')
    parser.add_argument('--all', '-a', action='store_true', help='Probar en H4 y D1')
    
    args = parser.parse_args()
    
    # Conectar a MT5
    mt5 = None
    try:
        from mt5.conector_mt5 import ConectorPepperstone
        from config.settings import Config
        config = Config()
        mt5 = ConectorPepperstone(
            login=config.MT5_LOGIN, password=config.MT5_PASSWORD,
            server=config.MT5_SERVER, demo=config.MT5_DEMO
        )
        mt5.conectar()
        logger.info("✅ Conectado a MT5")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo conectar a MT5: {e}")
        return
    
    if args.all:
        timeframes = [240, 1440]
        simbolos = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD', 'US30']
        resultados = {}
        
        for tf in timeframes:
            nombre_tf = 'H4' if tf == 240 else 'D1'
            logger.info(f"\n{'='*60}")
            logger.info(f"📊 VALIDANDO EN {nombre_tf}")
            logger.info(f"{'='*60}")
            
            for simbolo in simbolos:
                try:
                    df = obtener_datos(mt5, simbolo, tf)
                    if df is None:
                        continue
                    
                    indicadores = calcular_todos_indicadores(df)
                    corr = analizar_correlaciones(df, indicadores)
                    resultado = simular_estrategia(df, indicadores)
                    
                    logger.info(f"📈 {simbolo} {nombre_tf}: PnL=${resultado['pnl_total']:.2f} | WinRate={resultado['win_rate']:.1f}% | Ops={resultado['n_operaciones']} | PF={resultado['profit_factor']:.2f}")
                    
                    resultados[f"{simbolo}_{nombre_tf}"] = {
                        'pnl': resultado['pnl_total'],
                        'win_rate': resultado['win_rate'],
                        'n_operaciones': resultado['n_operaciones'],
                        'profit_factor': resultado['profit_factor'],
                        'correlaciones': corr,
                    }
                except Exception as e:
                    logger.error(f"❌ Error con {simbolo}: {e}")
        
        ruta = Path("data") / f"validacion_original_timeframes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, indent=2, default=str)
        logger.info(f"💾 Resultados guardados en: {ruta}")
        
        logger.info(f"\n{'='*60}")
        logger.info("📋 RESUMEN GENERAL")
        logger.info(f"{'='*60}")
        for clave, datos in sorted(resultados.items(), key=lambda x: x[1]['pnl'], reverse=True):
            estado = '✅' if datos['pnl'] > 0 else '❌'
            logger.info(f"{estado} {clave}: PnL=${datos['pnl']:.2f} | WR={datos['win_rate']:.1f}% | PF={datos['profit_factor']:.2f}")
    
    else:
        df = obtener_datos(mt5, args.simbolo, args.tf, args.velas)
        if df is None:
            logger.error("❌ No se obtuvieron datos")
            return
        
        indicadores = calcular_todos_indicadores(df)
        
        logger.info("\n📊 Correlaciones:")
        corr = analizar_correlaciones(df, indicadores)
        for nombre, valor in corr.items():
            logger.info(f"   {nombre}: {valor:.4f}")
        
        logger.info("\n📈 Simulando estrategia con operación única...")
        resultado = simular_estrategia(df, indicadores)
        
        tf_nombre = 'H4' if args.tf == 240 else 'D1'
        logger.info(f"\n📋 RESULTADO {args.simbolo} {tf_nombre}:")
        logger.info(f"   PnL: ${resultado['pnl_total']:.2f}")
        logger.info(f"   Win Rate: {resultado['win_rate']:.1f}%")
        logger.info(f"   Operaciones: {resultado['n_operaciones']}")
        logger.info(f"   Profit Factor: {resultado['profit_factor']:.2f}")
        logger.info(f"   VÁLIDO: {'✅' if resultado['pnl_total'] > 0 and resultado['win_rate'] > 50 else '❌'}")


if __name__ == "__main__":
    main()