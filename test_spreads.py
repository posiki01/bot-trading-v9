#!/usr/bin/env python3
"""
test_spreads_diagnostico.py
Prueba DIRECTA de spreads contra MetaTrader5/Pepperstone.
No usa conector_mt5.py ni ninguna función del bot.
Compara ask-bid, info.spread, info.spread_float y ticks recientes.
"""

import math
import time
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5
import pandas as pd

from config.settings import _get_env, _get_env_int

MT5_LOGIN = _get_env_int("MT5_LOGIN", 0)
MT5_PASSWORD = _get_env("MT5_PASSWORD", "")
MT5_SERVER = _get_env("MT5_SERVER", "Pepperstone-Demo")

SIMBOLOS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "EURJPY", "GBPJPY", "AUDJPY", "EURGBP",
    "US30", "NAS100", "US500", "XAUUSD",
    "BTCUSD", "ETHUSD", "SOLUSD"
]

MUESTRAS_EN_VIVO = 10
INTERVALO_MUESTRAS = 0.30
MINUTOS_HISTORICO = 5
MAX_TICKS_HISTORICO = 5000


def now_local():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return math.nan


def tick_timestamp(tick):
    try:
        if getattr(tick, "time_msc", 0):
            return datetime.fromtimestamp(
                tick.time_msc / 1000.0, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if getattr(tick, "time", 0):
            return datetime.fromtimestamp(
                tick.time, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return "N/A"


def get_pip_size(info):
    point = float(info.point or 0.0)
    if point <= 0:
        return 0.0
    if info.digits in (3, 5):
        return point * 10.0
    return point


def calculate_spread(info, bid, ask):
    bid = float(bid)
    ask = float(ask)
    spread_price = ask - bid
    point = float(info.point or 0.0)
    spread_points = spread_price / point if point > 0 else math.nan
    pip_size = get_pip_size(info)
    spread_pips = spread_price / pip_size if pip_size > 0 else math.nan
    return {
        "spread_price": spread_price,
        "spread_points": spread_points,
        "spread_pips": spread_pips,
        "pip_size": pip_size,
    }


def classify_symbol(info):
    name = info.name.upper()
    if any(x in name for x in ("BTC", "ETH", "SOL")):
        return "CRYPTO"
    if any(x in name for x in ("XAU", "XAG")):
        return "METAL"
    if any(x in name for x in ("US30", "NAS100", "US500", "SP500")):
        return "INDEX"
    clean = "".join(c for c in name if c.isalpha())
    if len(clean) == 6:
        return "FOREX"
    return "OTHER"


def conectar_mt5():
    print("=" * 100)
    print(f"🔍 TEST DIRECTO DE SPREADS - {now_local()}")
    print("=" * 100)
    print("\n📡 Inicializando MetaTrader 5...")

    if not mt5.initialize(
        login=MT5_LOGIN,
        password=MT5_PASSWORD,
        server=MT5_SERVER,
        timeout=10000,
    ):
        print(f"❌ mt5.initialize() falló: {mt5.last_error()}")
        return False

    terminal = mt5.terminal_info()
    account = mt5.account_info()
    print("✅ MT5 conectado")
    print(f"   Servidor solicitado : {MT5_SERVER}")

    if account:
        print(f"   Login               : {account.login}")
        print(f"   Servidor real       : {account.server}")
        print(f"   Moneda              : {account.currency}")
        print(f"   Balance             : {account.balance:.2f}")
        print(f"   Equity              : {account.equity:.2f}")
    if terminal:
        print(f"   Terminal conectado  : {terminal.connected}")
        print(f"   Terminal build      : {terminal.build}")
    return True


def preparar_simbolo(simbolo):
    info = mt5.symbol_info(simbolo)
    if info is None:
        print(f"❌ {simbolo}: symbol_info() = None")
        print(f"   mt5.last_error() = {mt5.last_error()}")
        return None

    if not info.visible or not getattr(info, "select", True):
        if not mt5.symbol_select(simbolo, True):
            print(f"❌ {simbolo}: symbol_select(..., True) falló")
            print(f"   mt5.last_error() = {mt5.last_error()}")
            return None
        info = mt5.symbol_info(simbolo)

    return info


def imprimir_info_simbolo(info):
    print(f"   name              : {info.name}")
    print(f"   description       : {info.description}")
    print(f"   path              : {info.path}")
    print(f"   visible           : {info.visible}")
    print(f"   select             : {getattr(info, 'select', 'N/A')}")
    print(f"   trade_mode        : {getattr(info, 'trade_mode', 'N/A')}")
    print(f"   digits            : {info.digits}")
    print(f"   point             : {info.point}")
    print(f"   tick_size         : {getattr(info, 'trade_tick_size', 'N/A')}")
    print(f"   info.spread       : {getattr(info, 'spread', 'N/A')}")
    print(f"   info.spread_float : {getattr(info, 'spread_float', 'N/A')}")
    print(f"   tipo activo       : {classify_symbol(info)}")


def test_muestras_en_vivo(simbolo, info):
    print("\n   📡 MUESTREO EN VIVO")
    print(
        "   "
        f"{'#':>2} {'BID':>12} {'ASK':>12} {'SPR.PRICE':>12} "
        f"{'POINTS':>9} {'PIPS':>9} {'ESTADO':>10} {'tick UTC':>23}"
    )

    ceros = 0
    invalidos = 0

    for i in range(1, MUESTRAS_EN_VIVO + 1):
        tick = mt5.symbol_info_tick(simbolo)
        if tick is None:
            invalidos += 1
            print(f"   {i:>2} ❌ symbol_info_tick() = None")
            time.sleep(INTERVALO_MUESTRAS)
            continue

        bid = safe_float(tick.bid)
        ask = safe_float(tick.ask)
        if not math.isfinite(bid) or not math.isfinite(ask):
            invalidos += 1
            print(f"   {i:>2} ❌ Bid/Ask no numérico")
            time.sleep(INTERVALO_MUESTRAS)
            continue

        calc = calculate_spread(info, bid, ask)
        spread = calc["spread_price"]
        if spread < 0:
            estado = "ASK<BID"
            invalidos += 1
        elif spread == 0:
            estado = "ZERO"
            ceros += 1
        else:
            estado = "OK"

        print(
            "   "
            f"{i:>2} {bid:>12.{info.digits}f} {ask:>12.{info.digits}f} "
            f"{spread:>12.{info.digits}f} {calc['spread_points']:>9.1f} "
            f"{calc['spread_pips']:>9.2f} {estado:>10} "
            f"{tick_timestamp(tick):>23}"
        )
        time.sleep(INTERVALO_MUESTRAS)

    return ceros, invalidos


def test_historico_ticks(simbolo, info):
    print(f"\n   🕐 HISTÓRICO DE TICKS: últimos {MINUTOS_HISTORICO} minutos")
    utc_desde = datetime.now(timezone.utc) - timedelta(minutes=MINUTOS_HISTORICO)

    ticks = mt5.copy_ticks_from(
        simbolo,
        utc_desde,
        MAX_TICKS_HISTORICO,
        mt5.COPY_TICKS_INFO,
    )

    if ticks is None:
        print(f"   ❌ copy_ticks_from() = None")
        print(f"      mt5.last_error() = {mt5.last_error()}")
        return None
    if len(ticks) == 0:
        print("   ⚠️ No se recibieron ticks históricos.")
        return None

    ceros = positivos = negativos = invalidos = 0
    spreads = []

    for row in ticks:
        bid = safe_float(row["bid"])
        ask = safe_float(row["ask"])
        if not math.isfinite(bid) or not math.isfinite(ask):
            invalidos += 1
            continue
        spread = ask - bid
        if spread < 0:
            negativos += 1
        elif spread == 0:
            ceros += 1
        else:
            positivos += 1
            spreads.append(spread)

    validos = ceros + positivos + negativos
    print(f"   Ticks recibidos     : {len(ticks)}")
    print(f"   Ticks válidos       : {validos}")
    print(f"   Spread = 0          : {ceros}")
    print(f"   Spread > 0          : {positivos}")
    print(f"   Spread < 0          : {negativos}")
    print(f"   Bid/Ask inválidos   : {invalidos}")

    if validos:
        print(f"   % spread = 0        : {ceros / validos * 100:.2f}%")
        print(f"   % spread > 0        : {positivos / validos * 100:.2f}%")

    if spreads:
        point = float(info.point or 0)
        avg = sum(spreads) / len(spreads)
        print(
            f"   Spread positivo     : "
            f"min={min(spreads):.{info.digits}f} "
            f"avg={avg:.{info.digits}f} "
            f"max={max(spreads):.{info.digits}f}"
        )
        if point > 0:
            print(
                f"   En puntos           : "
                f"min={min(spreads)/point:.1f} "
                f"avg={avg/point:.1f} "
                f"max={max(spreads)/point:.1f}"
            )

    return {
        "ticks": len(ticks),
        "validos": validos,
        "ceros": ceros,
        "positivos": positivos,
        "negativos": negativos,
        "invalidos": invalidos,
    }


def analizar_simbolo(simbolo):
    print("\n" + "=" * 100)
    print(f"🔍 {simbolo}")
    print("=" * 100)

    info = preparar_simbolo(simbolo)
    if info is None:
        return {
            "Simbolo": simbolo,
            "Estado": "SIN_INFO",
            "Bid": math.nan,
            "Ask": math.nan,
            "SpreadPips": math.nan,
            "SpreadPoints": math.nan,
            "MT5Spread": math.nan,
            "MT5SpreadFloat": math.nan,
            "CerosVivo": math.nan,
            "CerosHistoricos": math.nan,
            "PositivosHistoricos": math.nan,
        }

    imprimir_info_simbolo(info)

    tick = mt5.symbol_info_tick(simbolo)
    if tick is None:
        print(f"\n   ❌ {simbolo}: no hay tick actual")
        print(f"      mt5.last_error() = {mt5.last_error()}")
        return {"Simbolo": simbolo, "Estado": "SIN_TICK"}

    bid = safe_float(tick.bid)
    ask = safe_float(tick.ask)
    calc = calculate_spread(info, bid, ask)

    print("\n   📌 TICK ACTUAL DIRECTO")
    print(f"   Bid                  : {bid:.{info.digits}f}")
    print(f"   Ask                  : {ask:.{info.digits}f}")
    print(f"   Spread precio        : {calc['spread_price']:.{info.digits}f}")
    print(f"   Spread puntos        : {calc['spread_points']:.2f}")
    print(f"   Spread pips          : {calc['spread_pips']:.2f}")
    print(f"   info.spread          : {getattr(info, 'spread', 'N/A')}")
    print(f"   info.spread_float    : {getattr(info, 'spread_float', 'N/A')}")
    print(f"   Tick UTC             : {tick_timestamp(tick)}")

    ceros_vivo, invalidos_vivo = test_muestras_en_vivo(simbolo, info)
    hist = test_historico_ticks(simbolo, info)

    if hist is None:
        estado = "SIN_HISTORICO"
    elif hist["positivos"] > 0 and hist["ceros"] == 0:
        estado = "SPREAD_POSITIVO"
    elif hist["positivos"] > 0 and hist["ceros"] > 0:
        estado = "MIXTO"
    elif hist["positivos"] == 0 and hist["ceros"] > 0:
        estado = "ZERO_PERSISTENTE"
    else:
        estado = "SIN_SPREAD_VALIDO"

    print(f"\n   🧪 DIAGNÓSTICO: {estado}")
    if estado == "ZERO_PERSISTENTE":
        print("   ⚠️ MT5 entrega Bid == Ask de forma persistente.")
        print("   → El cálculo ask-bid del bot NO parece ser la causa.")
    elif estado == "MIXTO":
        print("   ⚠️ El feed alterna entre spread 0 y spread positivo.")
        print("   → El bot debe esperar ticks válidos antes de rechazar.")
    elif estado == "SPREAD_POSITIVO":
        print("   ✅ MT5 entrega spread positivo en el histórico.")
        print("   → Si tu bot ve 0, compara el flujo del conector.")

    return {
        "Simbolo": simbolo,
        "Estado": estado,
        "Bid": bid,
        "Ask": ask,
        "SpreadPips": calc["spread_pips"],
        "SpreadPoints": calc["spread_points"],
        "MT5Spread": safe_float(getattr(info, "spread", math.nan)),
        "MT5SpreadFloat": getattr(info, "spread_float", math.nan),
        "CerosVivo": ceros_vivo,
        "InvalidosVivo": invalidos_vivo,
        "TicksHistoricos": hist["ticks"] if hist else math.nan,
        "CerosHistoricos": hist["ceros"] if hist else math.nan,
        "PositivosHistoricos": hist["positivos"] if hist else math.nan,
    }


def resumen_final(resultados):
    if not resultados:
        return
    df = pd.DataFrame(resultados)
    print("\n" + "=" * 100)
    print("📊 RESUMEN FINAL")
    print("=" * 100)
    columnas = [
        "Simbolo", "Estado", "Bid", "Ask", "SpreadPips", "SpreadPoints",
        "MT5Spread", "MT5SpreadFloat", "CerosVivo", "CerosHistoricos",
        "PositivosHistoricos"
    ]
    columnas = [c for c in columnas if c in df.columns]
    print(df[columnas].to_string(index=False))

    print("\n" + "=" * 100)
    print("🧠 INTERPRETACIÓN")
    print("=" * 100)
    for estado, mensaje in [
        ("ZERO_PERSISTENTE", "⚠️ ZERO_PERSISTENTE"),
        ("MIXTO", "⚠️ MIXTO (0 y >0)"),
        ("SPREAD_POSITIVO", "✅ SPREAD_POSITIVO"),
    ]:
        subset = df[df["Estado"] == estado]
        if len(subset):
            print(f"{mensaje}: {list(subset['Simbolo'])}")

    print("\nRegla de diagnóstico:")
    print("1. Script DIRECTO >0 y bot 0  => problema en bot/conector.")
    print("2. Script DIRECTO 0 persistente => NO es la fórmula del bot.")
    print("3. Script DIRECTO alterna 0/>0 => comportamiento temporal del feed/tick.")
    print("=" * 100)


def main():
    if not conectar_mt5():
        return

    resultados = []
    try:
        for simbolo in SIMBOLOS:
            try:
                resultados.append(analizar_simbolo(simbolo))
            except Exception as exc:
                print(
                    f"\n❌ EXCEPCIÓN procesando {simbolo}: "
                    f"{type(exc).__name__}: {exc}"
                )
        resumen_final(resultados)
    finally:
        mt5.shutdown()
        print("\n🔒 MT5 desconectado.")


if __name__ == "__main__":
    main()