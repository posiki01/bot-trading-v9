from trading.sniper.sniper_checklist import SniperChecklist

checklist = SniperChecklist(
    pipeline=None, analisis_capas=None, modo_selector=None,
    entry_timer=None, gestor_stops=None, config=None, almacen=None,
    mt5=None, noticias=None, patron_tracker=None, ml_optimizer=None,
    analysis_cache=None, modo_depuracion=True, modo_backtest=True
)

# Verificar para EURUSD y BTCUSD en todos los modos
simbolos = ['EURUSD', 'BTCUSD']
modos = ['RETEST', 'BREAKOUT', 'PULLBACK', 'SNIPER_ELITE', 'NIVEL_FUERTE']

for s in simbolos:
    print(f'📊 {s}:')
    for modo in modos:
        sl_min = checklist._obtener_sl_minimo_universal(s, modo)
        sl_max = checklist._obtener_sl_maximo_universal(s, modo)
        print(f'  {modo}: SL min={sl_min} pips, SL max={sl_max} pips')
    print()
