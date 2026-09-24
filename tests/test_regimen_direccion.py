#!/usr/bin/env python3
"""Verifica coherencia régimen ↔ dirección_favor."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_direccion_favor():
    from analysis.regimen import MarketRegimeFilter, RegimenMercado

    filtro = MarketRegimeFilter(modo_backtest=True)

    # Casos de test: (regimen, estructura_h1, direccion_esperada)
    casos = [
        # Régimen alcista → ALCISTA (independiente de estructura)
        ('TREND_ALCISTA_FUERTE', 'ALCISTA', 'ALCISTA'),
        ('TREND_ALCISTA_FUERTE', 'BAJISTA', 'ALCISTA'),  # régimen gana
        ('TREND_ALCISTA_DEBIL', 'BAJISTA', 'ALCISTA'),

        # Régimen bajista → BAJISTA (independiente de estructura)
        ('TREND_BAJISTA_FUERTE', 'ALCISTA', 'BAJISTA'),  # ← EL BUG
        ('TREND_BAJISTA_FUERTE', 'BAJISTA', 'BAJISTA'),
        ('TREND_BAJISTA_DEBIL', 'ALCISTA', 'BAJISTA'),

        # Breakout → según estructura
        ('BREAKOUT_INMINENTE', 'ALCISTA', 'ALCISTA'),
        ('BREAKOUT_INMINENTE', 'BAJISTA', 'BAJISTA'),
        ('BREAKOUT_INMINENTE', 'RANGO', 'NONE'),

        # Rango/CHOP/INCERTO → según estructura
        ('RANGO_AMPLIO', 'ALCISTA', 'ALCISTA'),
        ('RANGO_APRETADO', 'BAJISTA', 'BAJISTA'),
        ('RANGO_AMPLIO', 'RANGO', 'NONE'),
        ('CHOP_VOLATIL', 'ALCISTA', 'ALCISTA'),
        ('INCERTO', 'RANGO', 'NONE'),

        # Sin régimen → fallback a estructura
        (None, 'ALCISTA', 'ALCISTA'),
        (None, 'BAJISTA', 'BAJISTA'),
        (None, 'RANGO', 'NONE'),
    ]

    print("=" * 70)
    print("🔍 TEST COHERENCIA régimen ↔ dirección_favor")
    print("=" * 70)
    print(f"\n{'Régimen':<25} {'Estructura':<12} {'Esperado':<10} {'Obtenido':<10} {'OK':>4}")
    print("-" * 70)

    errores = 0
    for regimen, estructura, esperado in casos:
        indicadores = {'estructura': estructura}
        obtenido = filtro._determinar_direccion_favor(indicadores, regimen)

        ok = obtenido == esperado
        if not ok:
            errores += 1

        marca = "✅" if ok else "❌"
        regimen_str = regimen if regimen else "(None)"
        print(f"{regimen_str:<25} {estructura:<12} {esperado:<10} {obtenido:<10} {marca:>4}")

    print("=" * 70)

    if errores:
        print(f"\n❌ {errores} caso(s) fallaron")
        return 1
    else:
        print(f"\n✅ Todos los casos pasan ({len(casos)} verificados)")
        return 0


if __name__ == "__main__":
    sys.exit(test_direccion_favor())