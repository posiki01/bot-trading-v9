# test_direccion.py
"""
Diagnóstico de determinar_direccion con datos reales.
"""
from data.almacenamiento_sqlite import AlmacenamientoSQLite
from analysis.direccion import determinar_direccion
from pathlib import Path

alm = AlmacenamientoSQLite(base_dir=Path('data'), modo_backup=False)

simbolos = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD', 'US30']

for simbolo in simbolos:
    df_h1 = alm.obtener_datos_historicos(simbolo, 60)
    df_h4 = alm.obtener_datos_historicos(simbolo, 240)

    if df_h1 is None or df_h4 is None:
        print(f"\n{simbolo}: sin datos")
        continue

    print(f"\n{'=' * 60}")
    print(f"{simbolo}")
    print('=' * 60)
    print(f"  DF H1: {len(df_h1)} velas, última: {df_h1.index[-1]}")
    print(f"  DF H4: {len(df_h4)} velas, última: {df_h4.index[-1]}")

    # Probar con régimen simulado
    for regimen in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE', 'RANGO_AMPLIO']:
        r = determinar_direccion(
            df_h4=df_h4,
            df_h1=df_h1,
            df_m15=None,
            regimen=regimen,
            en_nivel_clave=False,
            soporte_cercano=None,
            resistencia_cercana=None,
            precio_actual=float(df_h1['Close'].iloc[-1]),
            modo_backtest=False,
        )
        print(f"\n  Régimen: {regimen}")
        print(f"    → Dirección: {r.direccion}")
        print(f"    → Estructura H4: {r.estructura_h4}")
        print(f"    → Estructura H1: {r.estructura_h1}")
        print(f"    → Alineación: {r.alineacion}")
        print(f"    → Votos: {r.votos}")
        print(f"    → Score total: {sum(r.votos.values()):.1f}")

alm.cerrar()