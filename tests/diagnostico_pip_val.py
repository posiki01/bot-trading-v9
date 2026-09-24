#!/usr/bin/env python3
"""Verifica que pip_val sea correcto en todo el sistema."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_pip_val():
    from utils.parametros_simbolo import get_pip_val as get_pip_param
    from utils.helpers import get_pip_val as get_pip_helpers

    print("=" * 70)
    print("🔍 VERIFICACIÓN DE pip_val EN EL SISTEMA")
    print("=" * 70)

    # Valores esperados
    esperados = {
        'EURUSD': 0.0001,
        'USDJPY': 0.01,
        'GBPJPY': 0.01,
        'XAUUSD': 0.10,
        'XAGUSD': 0.01,
        'US30': 1.0,
        'NAS100': 1.0,
        'BTCUSD': 1.0,
        'ETHUSD': 0.10,
        'SOLUSD': 0.01,
    }

    print(f"\n{'Símbolo':<10} {'Esperado':>12} {'parametros':>14} {'helpers':>12} {'OK':>5}")
    print("-" * 60)

    errores = []
    for simbolo, esperado in esperados.items():
        v_param = get_pip_param(simbolo)
        v_helpers = get_pip_helpers(simbolo)

        ok_param = abs(v_param - esperado) < 1e-9
        ok_helpers = abs(v_helpers - esperado) < 1e-9

        estado = "✅" if (ok_param and ok_helpers) else "❌"
        if not (ok_param and ok_helpers):
            errores.append(simbolo)

        print(f"{simbolo:<10} {esperado:>12.5f} {v_param:>14.5f} {v_helpers:>12.5f} {estado:>5}")

    print("=" * 70)

    # Verificar consistencia con el broker (spread)
    print("\n🔍 VERIFICACIÓN CON BROKER (spread real)")
    print("-" * 60)

    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            for simbolo in ['EURUSD', 'XAUUSD', 'BTCUSD', 'ETHUSD']:
                tick = mt5.symbol_info_tick(simbolo)
                info = mt5.symbol_info(simbolo)

                if not tick or not info:
                    continue

                spread_price = tick.ask - tick.bid
                pip = get_pip_param(simbolo)
                spread_pips = spread_price / pip if pip > 0 else 0

                print(
                    f"  {simbolo:<8} "
                    f"spread_precio={spread_price:>10.5f} | "
                    f"pip={pip:>8.5f} | "
                    f"spread_pips={spread_pips:>8.2f}"
                )
            mt5.shutdown()
    except ImportError:
        print("  ⚠️ MetaTrader5 no disponible")
    except Exception as e:
        print(f"  ⚠️ Error: {e}")

    print()
    if errores:
        print(f"❌ Fallaron {len(errores)} símbolos: {errores}")
        return 1
    else:
        print("✅ Todas las verificaciones pasan")
        return 0


if __name__ == "__main__":
    sys.exit(test_pip_val())