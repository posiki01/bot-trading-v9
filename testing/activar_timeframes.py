# testing/activar_timeframes.py

#!/usr/bin/env python3
"""
testing/activar_timeframes.py (V1.0)
Abre charts en MT5 para activar la descarga de timeframes mayores.
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime, timezone
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


def activar_timeframes():
    """Activa timeframes abriendo charts en MT5."""
    
    print(f"\n{CYAN}{'='*80}{RESET}")
    print(f"{CYAN}🔄 ACTIVANDO TIMEFRAMES EN MT5{RESET}")
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
    
    # Timeframes a activar
    timeframes = [60, 240, 1440]  # H1, H4, D1
    nombres = {60: "H1", 240: "H4", 1440: "D1"}
    
    # Símbolos principales
    simbolos = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'US30', 'BTCUSD']
    
    for simbolo in simbolos:
        print(f"\n{CYAN}📊 {simbolo}:{RESET}")
        
        # Seleccionar símbolo
        if not mt5.symbol_select(simbolo, True):
            print(f"  {RED}❌ No se pudo seleccionar{RESET}")
            continue
        
        for tf in timeframes:
            try:
                # ✅ ABRIR CHART CON EL TIMEFRAME
                # Esto fuerza a MT5 a descargar datos históricos
                chart_id = mt5.chart_new(
                    symbol=simbolo,
                    timeframe=tf,
                    position=0,
                    price=0,
                    visible=False  # No mostrar el chart
                )
                
                if chart_id != 0:
                    # Esperar a que MT5 cargue los datos
                    time.sleep(2)
                    
                    # Verificar si ahora hay datos
                    rates = mt5.copy_rates_from_pos(simbolo, tf, 0, 10)
                    
                    if rates is not None and len(rates) > 0:
                        print(f"  {GREEN}✅ {nombres[tf]}: Chart abierto, {len(rates)} velas disponibles")
                    else:
                        print(f"  {YELLOW}⚠️ {nombres[tf]}: Chart abierto pero sin datos aún")
                    
                    # Cerrar chart
                    mt5.chart_close(chart_id)
                else:
                    print(f"  {YELLOW}⚠️ {nombres[tf]}: No se pudo abrir chart")
                    
            except Exception as e:
                print(f"  {RED}❌ {nombres[tf]}: Error: {e}")
        
        # Esperar entre símbolos
        time.sleep(1)
    
    # Desconectar
    mt5.shutdown()
    print(f"\n{GREEN}✅ Timeframes activados{RESET}")


if __name__ == "__main__":
    activar_timeframes()