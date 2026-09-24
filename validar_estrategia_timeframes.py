#!/usr/bin/env python3
"""
validar_estrategia_timeframes.py (V1.0)
Valida la estrategia en H4 y D1 (timeframes mayores suelen tener mejores correlaciones).
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
logger = logging.getLogger('ValidarTimeframes')


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

def calcular_indicadores(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """Calcula indicadores base."""
    close = df['Close']
    
    indicadores = {
        'EMA9': close.ewm(span=9, adjust=False).mean(),
        'EMA21': close.ewm(span=21, adjust=False).mean(),
        'EMA50': close.ewm(span=50, adjust=False).mean(),
        'ATR': calcular_atr(df),
        'BB_upper': calcular_bb_upper(close),
        'BB_lower': calcular_bb_lower(close),
    }
    
    return indicadores


def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    """Calcula ATR."""
    high, low, close = df['High'], df['Low'], df['Close']
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(periodo).mean()


def calcular_bb_upper(close: pd.Series, periodo: int = 20, desv: int = 2) -> pd.Series:
    """Calcula banda superior de Bollinger."""
    sma = close.rolling(periodo).mean()
    std = close.rolling(periodo).std()
    return sma + (std * desv)


def calcular_bb_lower(close: pd.Series, periodo: int = 20, desv: int = 2) -> pd.Series:
    """Calcula banda inferior de Bollinger."""
    sma = close.rolling(periodo).mean()
    std = close.rolling(periodo).std()
    return sma - (std * desv)


# ============================================================
# SIMULAR ESTRATEGIA
# ============================================================

def simular_estrategia(df: pd.DataFrame, indicadores: Dict[str, pd.Series],
                       sl_mult: float = 1.5, tp_mult: float = 2.5) -> Dict:
    """Simula estrategia de tendencia con SL/TP basados en ATR."""
    close = df['Close']
    operaciones = []
    capital = 1000.0
    
    for i in range(50, len(df) - 10):
        precio = close.iloc[i]
        ema9 = indicadores['EMA9'].iloc[i]
        ema21 = indicadores['EMA21'].iloc[i]
        ema50 = indicadores['EMA50'].iloc[i]
        atr = indicadores['ATR'].iloc[i]
        
        # Señal de COMPRA: Tendencia alcista
        if ema9 > ema21 > ema50:
            sl = precio - (atr * sl_mult)
            tp = precio + (atr * tp_mult)
            
            # Calcular lotes
            sl_dist = abs(precio - sl)
            lotes = (capital * 0.01) / (sl_dist * 100000)
            lotes = max(0.01, min(0.10, round(lotes, 2)))
            
            # Simular resultado
            resultado = simular_operacion(df, i, precio, sl, tp)
            operaciones.append({
                'fecha': df.index[i],
                'direccion': 'COMPRA',
                'precio_entrada': precio,
                'sl': sl,
                'tp': tp,
                'pnl': resultado['pnl'] * lotes,
                'resultado': resultado['resultado'],
            })
            capital += operaciones[-1]['pnl']
        
        # Señal de VENTA: Tendencia bajista
        elif ema9 < ema21 < ema50:
            sl = precio + (atr * sl_mult)
            tp = precio - (atr * tp_mult)
            
            # Calcular lotes
            sl_dist = abs(precio - sl)
            lotes = (capital * 0.01) / (sl_dist * 100000)
            lotes = max(0.01, min(0.10, round(lotes, 2)))
            
            # Simular resultado
            resultado = simular_operacion(df, i, precio, sl, tp, 'VENTA')
            operaciones.append({
                'fecha': df.index[i],
                'direccion': 'VENTA',
                'precio_entrada': precio,
                'sl': sl,
                'tp': tp,
                'pnl': resultado['pnl'] * lotes,
                'resultado': resultado['resultado'],
            })
            capital += operaciones[-1]['pnl']
    
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


def simular_operacion(df: pd.DataFrame, index: int, precio_entrada: float, sl: float, tp: float,
                      direccion: str = 'COMPRA') -> Dict:
    """Simula una operación."""
    for j in range(index, min(len(df), index + 100)):
        precio = df['Close'].iloc[j]
        
        if direccion == 'COMPRA':
            if precio <= sl:
                return {'pnl': (sl - precio_entrada), 'resultado': 'SL'}
            if precio >= tp:
                return {'pnl': (tp - precio_entrada), 'resultado': 'TP'}
        else:
            if precio >= sl:
                return {'pnl': (precio_entrada - sl), 'resultado': 'SL'}
            if precio <= tp:
                return {'pnl': (precio_entrada - tp), 'resultado': 'TP'}
    
    precio_final = df['Close'].iloc[min(len(df) - 1, index + 100)]
    if direccion == 'COMPRA':
        return {'pnl': (precio_final - precio_entrada), 'resultado': 'TIMEOUT'}
    else:
        return {'pnl': (precio_entrada - precio_final), 'resultado': 'TIMEOUT'}


# ============================================================
# ANÁLISIS DE PODER PREDICTIVO
# ============================================================

def analizar_correlaciones(df: pd.DataFrame, indicadores: Dict[str, pd.Series]) -> Dict[str, float]:
    """Analiza correlación de indicadores con retorno futuro."""
    retorno_futuro = df['Close'].shift(-10) / df['Close'] - 1
    
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
    
    parser = argparse.ArgumentParser(description='Validar estrategia en H4 y D1')
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
        # Probar en H4 y D1
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
                    
                    indicadores = calcular_indicadores(df)
                    
                    # Correlaciones
                    corr = analizar_correlaciones(df, indicadores)
                    
                    # Simular
                    resultado = simular_estrategia(df, indicadores)
                    
                    logger.info(f"📈 {simbolo} {nombre_tf}: PnL=${resultado['pnl_total']:.2f} | WinRate={resultado['win_rate']:.1f}% | Ops={resultado['n_operaciones']}")
                    
                    resultados[f"{simbolo}_{nombre_tf}"] = {
                        'pnl': resultado['pnl_total'],
                        'win_rate': resultado['win_rate'],
                        'n_operaciones': resultado['n_operaciones'],
                        'profit_factor': resultado['profit_factor'],
                        'correlaciones': corr,
                    }
                except Exception as e:
                    logger.error(f"❌ Error con {simbolo}: {e}")
        
        # Guardar resultados
        ruta = Path("data") / f"validacion_timeframes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, indent=2, default=str)
        logger.info(f"💾 Resultados guardados en: {ruta}")
        
        # Resumen
        logger.info(f"\n{'='*60}")
        logger.info("📋 RESUMEN GENERAL")
        logger.info(f"{'='*60}")
        for clave, datos in sorted(resultados.items(), key=lambda x: x[1]['pnl'], reverse=True):
            estado = '✅' if datos['pnl'] > 0 else '❌'
            logger.info(f"{estado} {clave}: PnL=${datos['pnl']:.2f} | WR={datos['win_rate']:.1f}%")
    
    else:
        # Probar un solo símbolo y timeframe
        df = obtener_datos(mt5, args.simbolo, args.tf, args.velas)
        if df is None:
            logger.error("❌ No se obtuvieron datos")
            return
        
        indicadores = calcular_indicadores(df)
        
        # Correlaciones
        logger.info("\n📊 Correlaciones:")
        corr = analizar_correlaciones(df, indicadores)
        for nombre, valor in corr.items():
            logger.info(f"   {nombre}: {valor:.4f}")
        
        # Simular
        logger.info("\n📈 Simulando estrategia...")
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