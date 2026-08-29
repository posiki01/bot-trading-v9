#!/usr/bin/env python3
"""
validar_horario.py
Prueba la lógica de horario de mercado.
"""

import sys
from pathlib import Path

# Añadir el directorio raíz del proyecto al path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from utils.tiempo import HorarioMercado
from datetime import datetime, timezone

def main():
    print("🧪 Validando horario de mercado...\n")
    
    # Crear instancia del horario
    horario = HorarioMercado(zona_usuario='COLOMBIA')
    
    # 1. Simular la hora de tu log (2026-08-17 00:03:46 COT)
    simulada_utc = datetime(2026, 8, 17, 5, 3, 46, tzinfo=timezone.utc)
    simulada_col = simulada_utc.astimezone(horario.ZONAS['COLOMBIA'])
    
    print(f"📅 Hora simulada (UTC): {simulada_utc}")
    print(f"📅 Hora Colombia: {simulada_col}")
    print(f"📊 Mercado abierto: {horario.mercado_abierto(simulada_utc)}")
    print(f"📊 Estado: {horario.estado_mercado(simulada_utc).value}")
    print()
    
    # 2. Probar varios horarios clave
    casos = [
        (2026, 8, 16, 21, 0, 0),   # Domingo 21:00 UTC → cerrado
        (2026, 8, 16, 22, 0, 0),   # Domingo 22:00 UTC → abierto (apertura)
        (2026, 8, 17, 5, 3, 46),   # Lunes 05:03 UTC → abierto (tu caso)
        (2026, 8, 21, 21, 0, 0),   # Viernes 21:00 UTC → abierto
        (2026, 8, 21, 22, 0, 0),   # Viernes 22:00 UTC → cerrado (cierre)
        (2026, 8, 22, 10, 0, 0),   # Sábado 10:00 UTC → cerrado
    ]
    
    print("📊 Casos de prueba:")
    for year, month, day, hour, minute, second in casos:
        dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        col = dt.astimezone(horario.ZONAS['COLOMBIA'])
        abierto = horario.mercado_abierto(dt)
        print(f"  {dt.strftime('%Y-%m-%d %H:%M UTC')} → Colombia {col.strftime('%H:%M')} → {'✅ ABIERTO' if abierto else '❌ CERRADO'}")

if __name__ == "__main__":
    main()