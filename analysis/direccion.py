#!/usr/bin/env python3
"""
analysis/direccion.py (V1.1 - CORREGIDO)
Determinación de dirección basada en estructura de mercado multi-TF.

CORRECCIONES V1.1:
- ✅ Umbral bajado a ±45 (antes ±60, imposible de alcanzar)
- ✅ Bonus de confirmación H1 + régimen (refuerza cuando coinciden)
- ✅ Fallback a régimen cuando H1 es RANGO
- ✅ Estructura H4 menos crítica (el sistema puede operar sin H4 alineado)

FILOSOFÍA:
- Dirección basada en ESTRUCTURA (HH/HL, LH/LL)
- Si H1 tiene estructura clara → votar fuerte
- Si H1 no tiene estructura pero el régimen es fuerte → votar
- Si no hay convicción → NEUTRAL (no operar)

PESOS (total 100):
- H4 estructura:  40 pts
- H1 estructura:  30 pts
- Alineación H4↔H1: ±20 pts
- Régimen:        ±15 pts
- Nivel clave:    ±15 pts
- Bonus confirmación H1+régimen: ±20 pts
- Fallback régimen (H1 RANGO):   ±30 pts
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

import pandas as pd

from analysis.estructura import (
    clasificar_estructura,
    EstructuraResultado,
)

logger = logging.getLogger('BotTrading.Direccion')


# ============================================================
# DATACLASS
# ============================================================

@dataclass
class DireccionResultado:
    """Resultado de la determinación de dirección."""
    direccion: str
    confianza: float
    votos: Dict[str, float] = field(default_factory=dict)
    estructura_h4: Optional[str] = None
    estructura_h1: Optional[str] = None
    estructura_m15: Optional[str] = None
    alineacion: bool = False
    razon: str = ""
    detalles: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# CONFIGURACIÓN
# ============================================================

PESO_H4 = 40
PESO_H1 = 30
PESO_ALINEACION = 20
PENALIZACION_DIVERGENCIA = -30
PESO_REGIMEN = 15
PESO_NIVEL_CLAVE = 15

# ✅ NUEVO: bonus y fallback
BONUS_CONFIRMACION = 20
PESO_FALLBACK_REGIMEN = 30

# ✅ Umbrales bajados (antes 60, imposible de alcanzar)
UMBRAL_COMPRA = 45
UMBRAL_VENTA = -45

REGIMENES_ALCISTAS = {'TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL'}
REGIMENES_BAJISTAS = {'TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL'}
REGIMENES_INVALIDOS = {'CHOP_VOLATIL'}


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def determinar_direccion(
    df_h4: Optional[pd.DataFrame] = None,
    df_h1: Optional[pd.DataFrame] = None,
    df_m15: Optional[pd.DataFrame] = None,
    regimen: str = 'INCERTO',
    en_nivel_clave: bool = False,
    soporte_cercano: Optional[float] = None,
    resistencia_cercana: Optional[float] = None,
    precio_actual: Optional[float] = None,
    modo_backtest: bool = False,
) -> DireccionResultado:
    """
    Determina la dirección basada en estructura de mercado.
    V1.1 - CORREGIDO.
    """
    resultado = DireccionResultado(direccion='NEUTRAL', confianza=0.0)
    votos: Dict[str, float] = {}

    # ============================================================
    # 1. ESTRUCTURA H4
    # ============================================================
    est_h4 = None
    if df_h4 is not None and len(df_h4) >= 50:
        est_h4 = clasificar_estructura(df_h4, ventana=5)
        resultado.estructura_h4 = est_h4.tipo

        if est_h4.tipo == 'ALCISTA':
            factor = est_h4.fuerza / 100.0
            votos['estructura_h4'] = PESO_H4 * factor
        elif est_h4.tipo == 'BAJISTA':
            factor = est_h4.fuerza / 100.0
            votos['estructura_h4'] = -PESO_H4 * factor
        else:
            votos['estructura_h4'] = 0.0

    # ============================================================
    # 2. ESTRUCTURA H1
    # ============================================================
    est_h1 = None
    if df_h1 is not None and len(df_h1) >= 50:
        est_h1 = clasificar_estructura(df_h1, ventana=5)
        resultado.estructura_h1 = est_h1.tipo

        if est_h1.tipo == 'ALCISTA':
            factor = est_h1.fuerza / 100.0
            votos['estructura_h1'] = PESO_H1 * factor
        elif est_h1.tipo == 'BAJISTA':
            factor = est_h1.fuerza / 100.0
            votos['estructura_h1'] = -PESO_H1 * factor
        else:
            votos['estructura_h1'] = 0.0

    # ============================================================
    # 3. ALINEACIÓN H4 ↔ H1
    # ============================================================
    if est_h4 and est_h1:
        if est_h4.tipo == est_h1.tipo and est_h4.tipo in ('ALCISTA', 'BAJISTA'):
            resultado.alineacion = True
            signo = 1 if est_h4.tipo == 'ALCISTA' else -1
            votos['alineacion'] = PESO_ALINEACION * signo
        elif est_h4.tipo in ('ALCISTA', 'BAJISTA') and est_h1.tipo in ('ALCISTA', 'BAJISTA'):
            # Divergencia explícita
            votos['alineacion'] = PENALIZACION_DIVERGENCIA

    # ============================================================
    # 4. ESTRUCTURA M15 (confirmación ligera)
    # ============================================================
    if df_m15 is not None and len(df_m15) >= 30:
        est_m15 = clasificar_estructura(df_m15, ventana=4)
        resultado.estructura_m15 = est_m15.tipo

        if est_h1 and est_h1.tipo in ('ALCISTA', 'BAJISTA'):
            if est_m15.tipo == est_h1.tipo:
                votos['estructura_m15'] = 5.0 if est_m15.tipo == 'ALCISTA' else -5.0
            elif est_m15.tipo in ('ALCISTA', 'BAJISTA'):
                votos['estructura_m15'] = -3.0 if est_h1.tipo == 'ALCISTA' else 3.0

    # ============================================================
    # 5. RÉGIMEN
    # ============================================================
    if regimen in REGIMENES_ALCISTAS:
        votos['regimen'] = PESO_REGIMEN
    elif regimen in REGIMENES_BAJISTAS:
        votos['regimen'] = -PESO_REGIMEN
    else:
        votos['regimen'] = 0.0

    # ============================================================
    # 6. NIVEL CLAVE
    # ============================================================
    if en_nivel_clave and precio_actual:
        if soporte_cercano and soporte_cercano > 0 and soporte_cercano < precio_actual:
            votos['nivel_clave'] = PESO_NIVEL_CLAVE
        elif resistencia_cercana and resistencia_cercana > precio_actual:
            votos['nivel_clave'] = -PESO_NIVEL_CLAVE
        else:
            votos['nivel_clave'] = 0.0
    else:
        votos['nivel_clave'] = 0.0

    # ============================================================
    # 7. BONUS DE CONFIRMACIÓN (H1 + régimen)
    # ============================================================
    if est_h1 and est_h1.tipo in ('ALCISTA', 'BAJISTA'):
        if est_h1.tipo == 'ALCISTA' and regimen in REGIMENES_ALCISTAS:
            votos['bonus_confirmacion'] = BONUS_CONFIRMACION
        elif est_h1.tipo == 'BAJISTA' and regimen in REGIMENES_BAJISTAS:
            votos['bonus_confirmacion'] = -BONUS_CONFIRMACION
        else:
            votos['bonus_confirmacion'] = 0.0

    # ============================================================
    # 8. FALLBACK RÉGIMEN (si H1 no tiene estructura)
    # ============================================================
    if est_h1 and est_h1.tipo == 'RANGO':
        if regimen in REGIMENES_ALCISTAS:
            votos['regimen_fallback'] = PESO_FALLBACK_REGIMEN
        elif regimen in REGIMENES_BAJISTAS:
            votos['regimen_fallback'] = -PESO_FALLBACK_REGIMEN
        else:
            votos['regimen_fallback'] = 0.0

    # ============================================================
    # 9. AGREGAR
    # ============================================================
    score_total = sum(votos.values())

    # Ajuste para backtest
    umbral_c = UMBRAL_COMPRA
    umbral_v = UMBRAL_VENTA
    if modo_backtest:
        umbral_c = UMBRAL_COMPRA * 0.7
        umbral_v = UMBRAL_VENTA * 0.7

    resultado.votos = votos
    resultado.detalles['score_total'] = score_total
    resultado.detalles['umbral'] = umbral_c

    # ============================================================
    # 10. DECISIÓN
    # ============================================================
    if score_total >= umbral_c:
        resultado.direccion = 'COMPRA'
        resultado.confianza = min(100, score_total)
        resultado.razon = (
            f"Estructura: H4={est_h4.tipo if est_h4 else '?'} "
            f"H1={est_h1.tipo if est_h1 else '?'} "
            f"(score {score_total:.0f})"
        )
    elif score_total <= umbral_v:
        resultado.direccion = 'VENTA'
        resultado.confianza = min(100, abs(score_total))
        resultado.razon = (
            f"Estructura: H4={est_h4.tipo if est_h4 else '?'} "
            f"H1={est_h1.tipo if est_h1 else '?'} "
            f"(score {score_total:.0f})"
        )
    else:
        resultado.direccion = 'NEUTRAL'
        resultado.confianza = 0.0
        resultado.razon = f"Sin convicción (score {score_total:.0f}, umbral ±{umbral_c:.0f})"

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            f"🧭 Dirección: {resultado.direccion} "
            f"(score {score_total:.0f}, alineación={resultado.alineacion})"
        )

    return resultado


# ============================================================
# API DE COMPATIBILIDAD
# ============================================================

def determinar_direccion_simple(
    df_h4: Optional[pd.DataFrame] = None,
    df_h1: Optional[pd.DataFrame] = None,
    df_m15: Optional[pd.DataFrame] = None,
    regimen: str = 'INCERTO',
    **kwargs,
) -> str:
    """Versión simplificada que retorna solo el string."""
    resultado = determinar_direccion(
        df_h4=df_h4,
        df_h1=df_h1,
        df_m15=df_m15,
        regimen=regimen,
        **kwargs,
    )
    return resultado.direccion


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando determinación de dirección V1.1...")

    import numpy as np

    def crear_df(tendencia: str, n: int = 200) -> pd.DataFrame:
        if tendencia == 'ALCISTA':
            base = np.linspace(100, 120, n)
        elif tendencia == 'BAJISTA':
            base = np.linspace(120, 100, n)
        else:
            base = 100 + np.sin(np.linspace(0, 10, n)) * 2

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

    # Test 1: Alcista alineado
    print("\n" + "=" * 60)
    print("TEST 1: H4 + H1 alcista alineados + régimen alcista")
    print("=" * 60)
    r = determinar_direccion(
        df_h4=crear_df('ALCISTA'),
        df_h1=crear_df('ALCISTA'),
        df_m15=crear_df('ALCISTA'),
        regimen='TREND_ALCISTA_FUERTE',
        en_nivel_clave=True,
        soporte_cercano=118,
        precio_actual=119,
    )
    print(f"Dirección: {r.direccion}")
    print(f"Confianza: {r.confianza:.1f}")
    print(f"Alineación: {r.alineacion}")
    print(f"Votos: {r.votos}")

    # Test 2: H1 claro + régimen (H4 RANGO)
    print("\n" + "=" * 60)
    print("TEST 2: H1 bajista + régimen bajista (H4 RANGO)")
    print("=" * 60)
    r = determinar_direccion(
        df_h4=crear_df('RANGO'),
        df_h1=crear_df('BAJISTA'),
        regimen='TREND_BAJISTA_FUERTE',
    )
    print(f"Dirección: {r.direccion}")
    print(f"Votos: {r.votos}")

    # Test 3: Solo régimen (H1 y H4 RANGO)
    print("\n" + "=" * 60)
    print("TEST 3: Solo régimen bajista (H1 y H4 RANGO)")
    print("=" * 60)
    r = determinar_direccion(
        df_h4=crear_df('RANGO'),
        df_h1=crear_df('RANGO'),
        regimen='TREND_BAJISTA_FUERTE',
    )
    print(f"Dirección: {r.direccion}")
    print(f"Votos: {r.votos}")

    # Test 4: Todo RANGO
    print("\n" + "=" * 60)
    print("TEST 4: Todo RANGO")
    print("=" * 60)
    r = determinar_direccion(
        df_h4=crear_df('RANGO'),
        df_h1=crear_df('RANGO'),
        regimen='RANGO_AMPLIO',
    )
    print(f"Dirección: {r.direccion}")
    print(f"Votos: {r.votos}")

    print("\n✅ Prueba completada")