# testing/diagnostico_mt5.py

#!/usr/bin/env python3
"""
testing/diagnostico_mt5.py (V1.0)
Diagnostica qué timeframes están disponibles en MT5.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from colorama import Fore, Style, init

sys.path.insert(0, str(Path(__file__).parent.parent))
init(autoreset=True)

CYAN = Fore.CYAN
GREEN = Fore.GREEN
YELLOW = Fore.YELLOW
RED = Fore.RED
WHITE = Fore.WHITE
RESET = Style.RESET_ALL

import MetaTrader5 as mt5
from config.settings import Config


def diagnosticar_timeframes():
    """Diagnostica qué timeframes están disponibles."""
    
    print(f"\n{CYAN}{'='*80}{RESET}")
    print(f"{CYAN}🔍 DIAGNÓSTICO DE TIMEFRAMES DISPONIBLES{RESET}")
    print(f"{CYAN}{'='*80}{RESET}")
    
    # Conectar a MT5
    if not mt5.initialize(
        login=Config.MT5_LOGIN,
        password=Config.MT5_PASSWORD,
        server=Config.MT5_SERVER,
        timeout=10000
    ):
        print(f"{RED}❌ No se pudo conectar a MT5{RESET}")
        return
    
    print(f"{GREEN}✅ Conectado a MT5{RESET}")
    
    # Probar timeframes
    timeframes = [1, 5, 15, 30, 60, 240, 1440, 10080, 43200]
    nombres = {
        1: "M1", 5: "M5", 15: "M15", 30: "M30",
        60: "H1", 240: "H4", 1440: "D1", 10080: "W1", 43200: "MN1"
    }
    
    # Probar con varios símbolos
    simbolos = ['EURUSD', 'GBPUSD', 'XAUUSD', 'BTCUSD', 'US30']
    
    for simbolo in simbolos:
        print(f"\n{CYAN}📊 {simbolo}:{RESET}")
        
        # Seleccionar símbolo
        if not mt5.symbol_select(simbolo, True):
            print(f"  {RED}❌ No se pudo seleccionar{RESET}")
            continue
        
        for tf in timeframes:
            try:
                # Obtener info del timeframe
                rates = mt5.copy_rates_from_pos(simbolo, tf, 0, 10)
                
                if rates is not None and len(rates) > 0:
                    # Obtener primera y última fecha
                    primera = datetime.fromtimestamp(rates[0]['time'], tz=timezone.utc)
                    ultima = datetime.fromtimestamp(rates[-1]['time'], tz=timezone.utc)
                    nombre_tf = nombres.get(tf, f"TF{tf}")
                    
                    print(f"  {GREEN}✅ {nombre_tf}: {len(rates)} velas disponibles")
                    print(f"     {WHITE}Primera: {primera.strftime('%Y-%m-%d %H:%M')}{RESET}")
                    print(f"     {WHITE}Última: {ultima.strftime('%Y-%m-%d %H:%M')}{RESET}")
                else:
                    nombre_tf = nombres.get(tf, f"TF{tf}")
                    print(f"  {YELLOW}⚠️ {nombre_tf}: Sin datos{RESET}")
                    
            except Exception as e:
                nombre_tf = nombres.get(tf, f"TF{tf}")
                print(f"  {RED}❌ {nombre_tf}: Error: {e}{RESET}")
    
    # Desconectar
    mt5.shutdown()
    print(f"\n{GREEN}✅ Diagnóstico completado{RESET}")


if __name__ == "__main__":
    diagnosticar_timeframes()