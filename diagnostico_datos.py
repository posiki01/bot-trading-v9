# tests/diagnostico_datos.py
import MetaTrader5 as mt5
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

mt5.initialize()

for simbolo in ['ETHUSD', 'BTCUSD', 'EURUSD', 'XAUUSD']:
    tick = mt5.symbol_info_tick(simbolo)
    info = mt5.symbol_info(simbolo)
    
    if not tick or not info:
        print(f"❌ {simbolo}: no disponible")
        continue
    
    spread_precio = tick.ask - tick.bid
    spread_points = spread_precio / info.point if info.point > 0 else 0
    spread_broker = info.spread  # ← VALOR OFICIAL DEL BROKER
    
    print(f"\n{simbolo}:")
    print(f"  Bid/Ask: {tick.bid} / {tick.ask}")
    print(f"  Spread precio: {spread_precio}")
    print(f"  Spread calculado: {spread_points:.0f} points")
    print(f"  Spread del broker: {spread_broker} points  ← FUENTE OFICIAL")
    print(f"  Digits: {info.digits}, Point: {info.point}")
    print(f"  ¿Coinciden? {'✅' if abs(spread_points - spread_broker) < 2 else '❌ DIFERENCIA'}")

mt5.shutdown()