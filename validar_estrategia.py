#!/usr/bin/env python3
"""
validar_estrategia.py (V2.0 - ACTUALIZADO)
Script de validación de estrategia simplificada.

IMPORTANTE: Este script NO ejecuta operaciones. Solo analiza datos históricos
para verificar si la estrategia tiene ventaja estadística y lógica económica.

V2.0 - CAMBIOS:
- ✅ Usa la estrategia SIMPLIFICADA (solo indicadores que aportan)
- ✅ Lógica específica por símbolo
- ✅ Elimina RSI, ADX, MACD donde no aportan
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
import os

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s'
)
logger = logging.getLogger('ValidarEstrategia')


# ============================================================
# CLASE 1: OBTENER DATOS HISTÓRICOS
# ============================================================

class ObtenedorDatos:
    """Obtiene datos históricos desde MT5 o SQLite."""
    
    def __init__(self, mt5: Any = None, almacen: Any = None):
        self.mt5 = mt5
        self.almacen = almacen
        self.logger = logging.getLogger('ValidarEstrategia.Datos')
    
    def obtener_h1(self, simbolo: str, n_velas: int = 5000) -> Optional[pd.DataFrame]:
        """
        Obtiene datos H1 históricos.
        Prioridad: MT5 → SQLite → None
        """
        if self.mt5:
            try:
                df = self.mt5.obtener_datos(simbolo, n_velas=n_velas, timeframe=60)
                if df is not None and len(df) > 0:
                    logger.info(f"✅ {simbolo}: {len(df)} velas H1 desde MT5")
                    return df
            except Exception as e:
                logger.warning(f"⚠️ {simbolo}: Error obteniendo de MT5: {e}")
        
        if self.almacen:
            try:
                df = self.almacen.obtener_datos_historicos(simbolo, 60)
                if df is not None and len(df) > 0:
                    logger.info(f"✅ {simbolo}: {len(df)} velas H1 desde SQLite")
                    return df
            except Exception as e:
                logger.warning(f"⚠️ {simbolo}: Error obteniendo de SQLite: {e}")
        
        logger.warning(f"⚠️ {simbolo}: No se obtuvieron datos")
        return None
    
    def obtener_para_validacion(self, simbolo: str, n_velas: int = 5000) -> Optional[pd.DataFrame]:
        """Obtiene datos completos con OHLCV."""
        df = self.obtener_h1(simbolo, n_velas)
        
        if df is None:
            return None
        
        # Validar columnas
        columnas_requeridas = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in columnas_requeridas:
            if col not in df.columns:
                logger.error(f"❌ {simbolo}: Falta columna '{col}'")
                return None
        
        # Convertir índice a datetime (si no lo es)
        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                df.index = pd.to_datetime(df.index)
            except Exception as e:
                logger.error(f"❌ {simbolo}: Error convirtiendo índice: {e}")
                return None
        
        # Asegurar zona horaria
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        
        logger.info(f"✅ {simbolo}: Datos preparados ({len(df)} velas, {df.index[0]} - {df.index[-1]})")
        return df


# ============================================================
# CLASE 2: CALCULAR INDICADORES SIMPLIFICADOS
# ============================================================

class CalculadorIndicadoresSimplificados:
    """Calcula SOLO los indicadores que aportan poder predictivo."""
    
    def __init__(self):
        self.logger = logging.getLogger('ValidarEstrategia.Indicadores')
    
    def calcular_para_simbolo(self, df: pd.DataFrame, simbolo: str) -> Dict[str, pd.Series]:
        """
        Calcula indicadores simplificados según el símbolo.
        V2.0 - SOLO indicadores con poder predictivo.
        """
        close = df['Close']
        high = df['High']
        low = df['Low']
        
        # Indicadores base (siempre necesarios)
        indicadores = {
            'EMA9': close.ewm(span=9, adjust=False).mean(),
            'EMA21': close.ewm(span=21, adjust=False).mean(),
            'EMA50': close.ewm(span=50, adjust=False).mean(),
            'ATR': self._calcular_atr(df),
        }
        
        simbolo_upper = simbolo.upper()
        
        # Indicadores específicos por tipo de activo
        if simbolo_upper in ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'EURGBP', 'EURJPY', 'GBPJPY']:
            # Forex: Bollinger + Ichimoku
            bb = self._calcular_bollinger(close)
            indicadores['BB_lower'] = bb['lower']
            indicadores['BB_upper'] = bb['upper']
            indicadores['Ichimoku_tenkan'] = self._calcular_ichimoku_tenkan(df)
            
        elif simbolo_upper == 'XAUUSD':
            # Oro: ADX
            indicadores['ADX'] = self._calcular_adx(df)
            
        elif simbolo_upper in ['BTCUSD', 'ETHUSD', 'SOLUSD']:
            # Cripto: MACD
            macd = self._calcular_macd(close)
            indicadores['MACD_line'] = macd['macd']
            indicadores['MACD_signal'] = macd['signal']
            indicadores['MACD_hist'] = macd['histogram']
            
        elif simbolo_upper in ['US30', 'NAS100', 'US500', 'SP500']:
            # Índices: VIX_proxy + Bollinger
            indicadores['VIX_proxy'] = (indicadores['ATR'] / close) * 100
            bb = self._calcular_bollinger(close)
            indicadores['BB_lower'] = bb['lower']
            indicadores['BB_upper'] = bb['upper']
        
        return indicadores
    
    def _calcular_atr(self, df: pd.DataFrame, periodo: int = 14) -> pd.Series:
        """Calcula ATR."""
        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        
        return tr.rolling(periodo).mean()
    
    def _calcular_bollinger(self, close: pd.Series, periodo: int = 20, desv: int = 2) -> Dict[str, pd.Series]:
        """Calcula Bollinger Bands."""
        sma = close.rolling(periodo).mean()
        std = close.rolling(periodo).std()
        
        upper = sma + (std * desv)
        lower = sma - (std * desv)
        
        return {'upper': upper, 'lower': lower}
    
    def _calcular_ichimoku_tenkan(self, df: pd.DataFrame) -> pd.Series:
        """Calcula Ichimoku Tenkan-sen."""
        high = df['High']
        low = df['Low']
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
        return tenkan
    
    def _calcular_adx(self, df: pd.DataFrame, periodo: int = 14) -> pd.Series:
        """Calcula ADX."""
        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(periodo).mean()
        atr_seguro = atr.replace(0, np.nan)
        
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
        
        di_suma = plus_di + minus_di
        di_suma_segura = di_suma.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / di_suma_segura
        
        return dx.rolling(periodo).mean()
    
    def _calcular_macd(self, close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
        """Calcula MACD."""
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        
        return {'macd': macd, 'signal': signal_line, 'histogram': histogram}


# ============================================================
# CLASE 3: SIMULACIÓN DE ESTRATEGIA SIMPLIFICADA
# ============================================================

class SimuladorEstrategiaSimplificada:
    """Simula la estrategia simplificada del bot."""
    
    def __init__(self, capital_inicial: float = 1000.0, 
                 riesgo_pct: float = 0.01,
                 pip_val: float = 0.0001):
        self.capital_inicial = capital_inicial
        self.riesgo_pct = riesgo_pct
        self.pip_val = pip_val
        self.logger = logging.getLogger('ValidarEstrategia.Simulador')
    
    def simular(self, df: pd.DataFrame, simbolo: str,
                indicadores: Dict[str, pd.Series]) -> Dict:
        """
        Simula la estrategia simplificada.
        V2.0 - Lógica específica por símbolo.
        """
        close = df['Close']
        operaciones = []
        capital = self.capital_inicial
        
        # Recorrer datos
        for i in range(50, len(df) - 10):
            precio = close.iloc[i]
            
            # Obtener señal específica por símbolo
            señal = self._generar_senal(simbolo, indicadores, i, precio)
            
            if señal == 'COMPRA':
                # SL/TP basados en ATR
                atr = indicadores['ATR'].iloc[i]
                sl = precio - (atr * 1.5)
                tp = precio + (atr * 2.5)
                
                # Calcular lotes
                sl_dist = abs(precio - sl)
                lotes = (capital * self.riesgo_pct) / (sl_dist * 100000)
                lotes = max(0.01, min(0.10, round(lotes, 2)))
                
                # Simular resultado
                resultado = self._simular_operacion(df, i, precio, sl, tp)
                
                operaciones.append({
                    'fecha': df.index[i],
                    'direccion': 'COMPRA',
                    'precio_entrada': precio,
                    'sl': sl,
                    'tp': tp,
                    'lotes': lotes,
                    'pnl': resultado['pnl'] * lotes,
                    'resultado': resultado['resultado'],
                })
                
                capital += operaciones[-1]['pnl']
            
            elif señal == 'VENTA':
                # SL/TP basados en ATR
                atr = indicadores['ATR'].iloc[i]
                sl = precio + (atr * 1.5)
                tp = precio - (atr * 2.5)
                
                # Calcular lotes
                sl_dist = abs(precio - sl)
                lotes = (capital * self.riesgo_pct) / (sl_dist * 100000)
                lotes = max(0.01, min(0.10, round(lotes, 2)))
                
                # Simular resultado
                resultado = self._simular_operacion(df, i, precio, sl, tp, 'VENTA')
                
                operaciones.append({
                    'fecha': df.index[i],
                    'direccion': 'VENTA',
                    'precio_entrada': precio,
                    'sl': sl,
                    'tp': tp,
                    'lotes': lotes,
                    'pnl': resultado['pnl'] * lotes,
                    'resultado': resultado['resultado'],
                })
                
                capital += operaciones[-1]['pnl']
        
        # Calcular métricas
        if operaciones:
            ganadoras = [op for op in operaciones if op['pnl'] > 0]
            perdedoras = [op for op in operaciones if op['pnl'] < 0]
            
            win_rate = len(ganadoras) / len(operaciones) * 100 if operaciones else 0
            pnl_total = sum(op['pnl'] for op in operaciones)
            ganancia_promedio = np.mean([op['pnl'] for op in ganadoras]) if ganadoras else 0
            perdida_promedio = np.mean([op['pnl'] for op in perdedoras]) if perdedoras else 0
            profit_factor = abs(sum(op['pnl'] for op in ganadoras) / sum(op['pnl'] for op in perdedoras)) if perdedoras else 0
        else:
            win_rate = 0
            pnl_total = 0
            ganancia_promedio = 0
            perdida_promedio = 0
            profit_factor = 0
        
        return {
            'capital_final': capital,
            'pnl_total': pnl_total,
            'win_rate': win_rate,
            'n_operaciones': len(operaciones),
            'ganancia_promedio': ganancia_promedio,
            'perdida_promedio': perdida_promedio,
            'profit_factor': profit_factor,
            'operaciones': operaciones,
        }
    
    def _generar_senal(self, simbolo: str, indicadores: Dict[str, pd.Series],
                       index: int, precio: float) -> str:
        """
        Genera señal específica por símbolo.
        V2.0 - Lógica simplificada.
        """
        simbolo_upper = simbolo.upper()
        
        # FOREX: EMA + Bollinger
        if simbolo_upper in ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'EURGBP', 'EURJPY', 'GBPJPY']:
            ema9 = indicadores['EMA9'].iloc[index]
            ema21 = indicadores['EMA21'].iloc[index]
            bb_lower = indicadores['BB_lower'].iloc[index]
            bb_upper = indicadores['BB_upper'].iloc[index]
            
            dist_lower = abs(precio - bb_lower) / bb_lower * 100
            dist_upper = abs(precio - bb_upper) / bb_upper * 100
            
            if ema9 > ema21 and dist_lower < 0.3:
                return 'COMPRA'
            elif ema9 < ema21 and dist_upper < 0.3:
                return 'VENTA'
            return 'NEUTRAL'
        
        # ORO: ADX + EMA
        elif simbolo_upper == 'XAUUSD':
            adx = indicadores['ADX'].iloc[index]
            ema50 = indicadores['EMA50'].iloc[index]
            
            if adx > 25 and abs(precio - ema50) / ema50 * 100 < 0.5:
                if precio > ema50:
                    return 'COMPRA'
                else:
                    return 'VENTA'
            return 'NEUTRAL'
        
        # CRIPTO: MACD + EMA
        elif simbolo_upper in ['BTCUSD', 'ETHUSD', 'SOLUSD']:
            macd_line = indicadores['MACD_line'].iloc[index]
            macd_signal = indicadores['MACD_signal'].iloc[index]
            ema21 = indicadores['EMA21'].iloc[index]
            
            diff_macd = abs(macd_line - macd_signal)
            
            if macd_line > macd_signal and diff_macd > 0.0005 and precio > ema21:
                return 'COMPRA'
            elif macd_line < macd_signal and diff_macd > 0.0005 and precio < ema21:
                return 'VENTA'
            return 'NEUTRAL'
        
        # ÍNDICES: VIX + Bollinger
        elif simbolo_upper in ['US30', 'NAS100', 'US500', 'SP500']:
            vix_proxy = indicadores['VIX_proxy'].iloc[index]
            bb_lower = indicadores['BB_lower'].iloc[index]
            bb_upper = indicadores['BB_upper'].iloc[index]
            
            dist_lower = abs(precio - bb_lower) / bb_lower * 100
            dist_upper = abs(precio - bb_upper) / bb_upper * 100
            
            if vix_proxy < 20 and dist_lower < 0.3:
                return 'COMPRA'
            elif vix_proxy > 30 and dist_upper < 0.3:
                return 'VENTA'
            return 'NEUTRAL'
        
        return 'NEUTRAL'
    
    def _simular_operacion(self, df: pd.DataFrame, index: int, 
                           precio_entrada: float, sl: float, tp: float,
                           direccion: str = 'COMPRA') -> Dict:
        """Simula el resultado de una operación."""
        for j in range(index, min(len(df), index + 100)):
            precio = df['Close'].iloc[j]
            
            if direccion == 'COMPRA':
                if precio <= sl:
                    return {'pnl': (sl - precio_entrada) / self.pip_val, 'resultado': 'SL'}
                if precio >= tp:
                    return {'pnl': (tp - precio_entrada) / self.pip_val, 'resultado': 'TP'}
            else:
                if precio >= sl:
                    return {'pnl': (precio_entrada - sl) / self.pip_val, 'resultado': 'SL'}
                if precio <= tp:
                    return {'pnl': (precio_entrada - tp) / self.pip_val, 'resultado': 'TP'}
        
        # Si no se tocó SL ni TP, cerrar al final
        precio_final = df['Close'].iloc[min(len(df) - 1, index + 100)]
        if direccion == 'COMPRA':
            return {'pnl': (precio_final - precio_entrada) / self.pip_val, 'resultado': 'TIMEOUT'}
        else:
            return {'pnl': (precio_entrada - precio_final) / self.pip_val, 'resultado': 'TIMEOUT'}


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def ejecutar_validacion(simbolo: str = 'EURUSD', 
                        n_velas: int = 5000,
                        mt5: Any = None,
                        almacen: Any = None) -> Dict:
    """
    Ejecuta la validación completa de la estrategia simplificada.
    """
    logger.info("=" * 60)
    logger.info(f"🚀 INICIANDO VALIDACIÓN DE ESTRATEGIA SIMPLIFICADA PARA {simbolo}")
    logger.info("=" * 60)
    
    # 1. Obtener datos
    logger.info(f"📥 1. Obteniendo datos de {simbolo}...")
    obtenedor = ObtenedorDatos(mt5=mt5, almacen=almacen)
    df = obtenedor.obtener_para_validacion(simbolo, n_velas)
    
    if df is None:
        logger.error("❌ No se pudieron obtener datos")
        return {'valido': False, 'razon': 'No hay datos'}
    
    # 2. Calcular indicadores simplificados
    logger.info("📊 2. Calculando indicadores simplificados...")
    calculador = CalculadorIndicadoresSimplificados()
    indicadores = calculador.calcular_para_simbolo(df, simbolo)
    
    # 3. Simular estrategia simplificada
    logger.info("📈 3. Simulando estrategia simplificada...")
    simulador = SimuladorEstrategiaSimplificada(capital_inicial=1000.0)
    resultado = simulador.simular(df, simbolo, indicadores)
    
    logger.info(f"   Capital final: ${resultado['capital_final']:.2f}")
    logger.info(f"   PnL total: ${resultado['pnl_total']:.2f}")
    logger.info(f"   Win Rate: {resultado['win_rate']:.1f}%")
    logger.info(f"   Operaciones: {resultado['n_operaciones']}")
    logger.info(f"   Profit Factor: {resultado['profit_factor']:.2f}")
    
    # 4. Conclusión
    valido = resultado['pnl_total'] > 0 and resultado['win_rate'] > 50
    logger.info("=" * 60)
    logger.info("📋 RESUMEN DE VALIDACIÓN")
    logger.info("=" * 60)
    logger.info(f"   PnL Total: ${resultado['pnl_total']:.2f}")
    logger.info(f"   Win Rate: {resultado['win_rate']:.1f}%")
    logger.info(f"   VÁLIDO: {'✅' if valido else '❌'}")
    
    return {
        'simbolo': simbolo,
        'n_velas': len(df),
        'pnl_total': resultado['pnl_total'],
        'win_rate': resultado['win_rate'],
        'n_operaciones': resultado['n_operaciones'],
        'profit_factor': resultado['profit_factor'],
        'valido': valido,
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Validación de estrategia simplificada')
    parser.add_argument('--simbolo', '-s', default='EURUSD', help='Símbolo a validar')
    parser.add_argument('--velas', '-n', type=int, default=5000, help='Número de velas H1')
    parser.add_argument('--all', '-a', action='store_true', help='Validar todos los símbolos')
    
    args = parser.parse_args()
    
    # Intentar cargar MT5 y almacen
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
    
    if args.all:
        simbolos = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD', 'US30']
        resultados = {}
        
        for simbolo in simbolos:
            try:
                resultado = ejecutar_validacion(simbolo, args.velas, mt5, almacen)
                resultados[simbolo] = resultado
            except Exception as e:
                logger.error(f"❌ Error validando {simbolo}: {e}")
                resultados[simbolo] = {'valido': False, 'razon': str(e)}
        
        # Guardar resumen general
        ruta_resumen = Path("data") / f"validacion_general_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        ruta_resumen.parent.mkdir(parents=True, exist_ok=True)
        
        with open(ruta_resumen, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, indent=2, default=str)
        
        logger.info(f"💾 Resumen general guardado en: {ruta_resumen}")
    else:
        ejecutar_validacion(args.simbolo, args.velas, mt5, almacen)