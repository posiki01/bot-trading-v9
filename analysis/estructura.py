#!/usr/bin/env python3
"""
analysis/estructura.py (V1.2 - CORREGIDO)
Detección de estructura de mercado: HH/HL (alcista), LH/LL (bajista), RANGO.

CORRECCIONES V1.2:
- ✅ Clasificación por DOMINANCIA (no umbral binario 60% en cada componente)
- ✅ Umbral de dominancia más realista (58% del total)
- ✅ Detección de ZigZag con threshold ATR (filtra ruido)
- ✅ BOS/CHoCH mejorados
- ✅ Fuerza amplificada para dar más peso
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

logger = logging.getLogger('BotTrading.Estructura')


# ============================================================
# CONFIGURACIÓN
# ============================================================

ZIGZAG_ATR_MULT = 0.5
ZIGZAG_FALLBACK_PCT = 0.005
ATR_PERIODO = 14

# ✅ NUEVO: Umbral de dominancia para clasificación
UMBRAL_DOMINANCIA = 58.0


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class Pivot:
    """Un punto de swing (high o low)."""
    indice: int
    timestamp: Any
    precio: float
    tipo: str  # 'HIGH' | 'LOW'


@dataclass
class EstructuraResultado:
    """Resultado del análisis de estructura."""
    tipo: str  # 'ALCISTA' | 'BAJISTA' | 'RANGO' | 'DESCONOCIDO'
    fuerza: float
    pivots_high: List[Pivot] = field(default_factory=list)
    pivots_low: List[Pivot] = field(default_factory=list)
    hh: int = 0
    hl: int = 0
    lh: int = 0
    ll: int = 0
    bos: bool = False
    choch: bool = False
    razon: str = ""


# ============================================================
# CÁLCULO DE ATR
# ============================================================

def _calcular_atr(df: pd.DataFrame, periodo: int = ATR_PERIODO) -> float:
    """ATR del dataframe."""
    if df is None or len(df) < periodo + 1:
        return 0.0
    try:
        high = df['High']
        low = df['Low']
        close = df['Close']
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(periodo).mean().iloc[-1]
        return float(atr) if not pd.isna(atr) else 0.0
    except Exception:
        return 0.0


# ============================================================
# DETECTOR ZIGZAG
# ============================================================

def detectar_pivots_zigzag(
    df: pd.DataFrame,
    umbral_atr_mult: float = ZIGZAG_ATR_MULT,
    mirar_atras: int = 200,
) -> Tuple[List[Pivot], List[Pivot]]:
    """Detecta pivots significativos con ZigZag + threshold ATR."""
    if df is None or len(df) < 20:
        return [], []

    df_slice = df.iloc[-mirar_atras:] if len(df) > mirar_atras else df
    if len(df_slice) < 20:
        return [], []

    atr = _calcular_atr(df_slice)
    precio_ref = float(df_slice['Close'].iloc[-1])
    if atr <= 0:
        atr = precio_ref * ZIGZAG_FALLBACK_PCT
    umbral = atr * umbral_atr_mult

    high = df_slice['High'].values
    low = df_slice['Low'].values
    n = len(high)
    offset = len(df) - n

    pivots_high: List[Pivot] = []
    pivots_low: List[Pivot] = []

    ultimo_alto = high[0]
    ultimo_bajo = low[0]
    idx_alto = 0
    idx_bajo = 0
    direccion = None

    for i in range(1, n):
        # Búsqueda de HIGH
        if direccion != 'DOWN':
            if high[i] > ultimo_alto:
                ultimo_alto = high[i]
                idx_alto = i
            elif (ultimo_alto - low[i]) >= umbral:
                pivots_high.append(Pivot(
                    indice=offset + idx_alto,
                    timestamp=df_slice.index[idx_alto],
                    precio=float(ultimo_alto),
                    tipo='HIGH',
                ))
                direccion = 'DOWN'
                ultimo_bajo = low[i]
                idx_bajo = i

        # Búsqueda de LOW
        if direccion != 'UP':
            if low[i] < ultimo_bajo:
                ultimo_bajo = low[i]
                idx_bajo = i
            elif (high[i] - ultimo_bajo) >= umbral:
                pivots_low.append(Pivot(
                    indice=offset + idx_bajo,
                    timestamp=df_slice.index[idx_bajo],
                    precio=float(ultimo_bajo),
                    tipo='LOW',
                ))
                direccion = 'UP'
                ultimo_alto = high[i]
                idx_alto = i

    pivots_high.sort(key=lambda p: p.indice)
    pivots_low.sort(key=lambda p: p.indice)

    return pivots_high, pivots_low


# ============================================================
# DETECTOR CLÁSICO (FALLBACK)
# ============================================================

def detectar_pivots(
    df: pd.DataFrame,
    ventana: int = 5,
    mirar_atras: int = 100,
) -> Tuple[List[Pivot], List[Pivot]]:
    """Detector clásico de pivots (fallback)."""
    if df is None or len(df) < (ventana * 2 + 1):
        return [], []

    df_slice = df.iloc[-mirar_atras:] if len(df) > mirar_atras else df
    high = df_slice['High'].values
    low = df_slice['Low'].values
    n = len(df_slice)

    pivots_high: List[Pivot] = []
    pivots_low: List[Pivot] = []

    for i in range(ventana, n - ventana):
        izq_high = high[i - ventana:i]
        der_high = high[i + 1:i + ventana + 1]
        if len(izq_high) > 0 and len(der_high) > 0:
            if high[i] > izq_high.max() and high[i] > der_high.max():
                idx_abs = len(df) - n + i
                pivots_high.append(Pivot(
                    indice=idx_abs,
                    timestamp=df_slice.index[i],
                    precio=float(high[i]),
                    tipo='HIGH',
                ))

        izq_low = low[i - ventana:i]
        der_low = low[i + 1:i + ventana + 1]
        if len(izq_low) > 0 and len(der_low) > 0:
            if low[i] < izq_low.min() and low[i] < der_low.min():
                idx_abs = len(df) - n + i
                pivots_low.append(Pivot(
                    indice=idx_abs,
                    timestamp=df_slice.index[i],
                    precio=float(low[i]),
                    tipo='LOW',
                ))

    return pivots_high, pivots_low


# ============================================================
# CLASIFICACIÓN DE ESTRUCTURA (V1.2)
# ============================================================

def clasificar_estructura(
    df: pd.DataFrame,
    ventana: int = 5,
    min_pivots: int = 2,
    usar_zigzag: bool = True,
) -> EstructuraResultado:
    """
    Clasifica la estructura de mercado.
    V1.2 - Clasificación por DOMINANCIA (no umbral binario).
    """
    resultado = EstructuraResultado(tipo='DESCONOCIDO', fuerza=0.0)

    if df is None or len(df) < 20:
        resultado.razon = "Datos insuficientes"
        return resultado

    # Detectar pivots
    if usar_zigzag:
        pivots_high, pivots_low = detectar_pivots_zigzag(df)
        if len(pivots_high) < min_pivots and len(pivots_low) < min_pivots:
            pivots_high, pivots_low = detectar_pivots(df, ventana=ventana)
    else:
        pivots_high, pivots_low = detectar_pivots(df, ventana=ventana)

    resultado.pivots_high = pivots_high
    resultado.pivots_low = pivots_low

    if len(pivots_high) < min_pivots and len(pivots_low) < min_pivots:
        resultado.razon = "Pivots insuficientes"
        return resultado

    # ------------------------------------------------------------
    # Contar HH / LH / HL / LL
    # ------------------------------------------------------------
    hh = hl = lh = ll = 0

    for i in range(1, len(pivots_high)):
        if pivots_high[i].precio > pivots_high[i - 1].precio:
            hh += 1
        else:
            lh += 1

    for i in range(1, len(pivots_low)):
        if pivots_low[i].precio > pivots_low[i - 1].precio:
            hl += 1
        else:
            ll += 1

    resultado.hh = hh
    resultado.hl = hl
    resultado.lh = lh
    resultado.ll = ll

    # ------------------------------------------------------------
    # ✅ V1.2: Clasificación por DOMINANCIA
    # ------------------------------------------------------------
    score_alcista = hh + hl       # HH + HL → alcista
    score_bajista = lh + ll       # LH + LL → bajista
    total_pivots = score_alcista + score_bajista

    if total_pivots == 0:
        resultado.tipo = 'RANGO'
        resultado.fuerza = 0.0
        resultado.razon = "Sin movimientos de pivots"
        return resultado

    pct_alcista = score_alcista / total_pivots * 100
    pct_bajista = score_bajista / total_pivots * 100

    # ✅ Umbral relajado: 58% dominancia
    if pct_alcista >= UMBRAL_DOMINANCIA:
        resultado.tipo = 'ALCISTA'
        resultado.fuerza = min(100.0, pct_alcista * 1.3)  # Amplificar
        resultado.razon = f"HH {hh} + HL {hl} = {pct_alcista:.0f}% alcista"
    elif pct_bajista >= UMBRAL_DOMINANCIA:
        resultado.tipo = 'BAJISTA'
        resultado.fuerza = min(100.0, pct_bajista * 1.3)
        resultado.razon = f"LH {lh} + LL {ll} = {pct_bajista:.0f}% bajista"
    else:
        resultado.tipo = 'RANGO'
        resultado.fuerza = max(0.0, 100 - max(pct_alcista, pct_bajista))
        resultado.razon = f"Mixto: HH {hh} LH {lh} HL {hl} LL {ll}"

    # ------------------------------------------------------------
    # BOS / CHoCH
    # ------------------------------------------------------------
    bos, choch = _detectar_bos_choch(df, pivots_high, pivots_low, resultado.tipo)
    resultado.bos = bos
    resultado.choch = choch

    return resultado


def _detectar_bos_choch(
    df: pd.DataFrame,
    pivots_high: List[Pivot],
    pivots_low: List[Pivot],
    tipo_actual: str,
) -> Tuple[bool, bool]:
    """Detecta BOS y CHoCH."""
    if df is None or len(df) < 5:
        return False, False

    high_actual = float(df['High'].iloc[-1])
    low_actual = float(df['Low'].iloc[-1])

    bos = False
    choch = False

    ultimo_high = pivots_high[-1].precio if pivots_high else None
    ultimo_low = pivots_low[-1].precio if pivots_low else None

    if tipo_actual == 'ALCISTA':
        if ultimo_high and high_actual > ultimo_high:
            bos = True
        if ultimo_low and low_actual < ultimo_low:
            choch = True
    elif tipo_actual == 'BAJISTA':
        if ultimo_low and low_actual < ultimo_low:
            bos = True
        if ultimo_high and high_actual > ultimo_high:
            choch = True

    return bos, choch


# ============================================================
# API DE ALTO NIVEL
# ============================================================

def obtener_estructura(df: pd.DataFrame, ventana: int = 5) -> EstructuraResultado:
    """Alias corto."""
    return clasificar_estructura(df, ventana=ventana)


def obtener_nivel_invalidacion(
    df: pd.DataFrame,
    direccion: str,
    ventana: int = 5,
) -> Optional[float]:
    """
    Nivel clave donde se invalida la estructura.
    COMPRA → último swing low
    VENTA  → último swing high
    """
    pivots_high, pivots_low = detectar_pivots_zigzag(df)

    if direccion == 'COMPRA' and pivots_low:
        return pivots_low[-1].precio
    if direccion == 'VENTA' and pivots_high:
        return pivots_high[-1].precio
    return None


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando análisis de estructura V1.2...")

    np.random.seed(42)

    def crear_df(tendencia: str, n: int = 300) -> pd.DataFrame:
        if tendencia == 'ALCISTA':
            base = np.linspace(100, 130, n)
        elif tendencia == 'BAJISTA':
            base = np.linspace(130, 100, n)
        else:
            base = 115 + np.sin(np.linspace(0, 15, n)) * 3

        ruido = np.random.randn(n) * 0.3
        close = base + ruido
        high = close + np.abs(np.random.randn(n) * 0.2)
        low = close - np.abs(np.random.randn(n) * 0.2)

        fechas = pd.date_range('2024-01-01', periods=n, freq='1h')
        return pd.DataFrame({
            'Open': close + np.random.randn(n) * 0.1,
            'High': high,
            'Low': low,
            'Close': close,
            'Volume': np.random.randint(1000, 10000, n),
        }, index=fechas)

    for tendencia in ['ALCISTA', 'BAJISTA', 'RANGO']:
        print(f"\n{'=' * 60}")
        print(f"TEST: {tendencia}")
        print('=' * 60)
        df = crear_df(tendencia)
        r = clasificar_estructura(df)
        print(f"Detectado: {r.tipo}")
        print(f"Fuerza: {r.fuerza:.1f}")
        print(f"HH:{r.hh} HL:{r.hl} LH:{r.lh} LL:{r.ll}")
        print(f"BOS: {r.bos} | CHoCH: {r.choch}")
        print(f"Razón: {r.razon}")

        esperado = tendencia
        ok = "✅" if r.tipo == esperado else "❌"
        print(f"{ok} Esperado: {esperado} | Obtenido: {r.tipo}")

    print("\n✅ Prueba completada")