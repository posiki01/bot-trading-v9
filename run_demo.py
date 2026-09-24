#!/usr/bin/env python3
"""
run_demo.py
Arranque en modo PRODUCCIÓN sobre cuenta DEMO.
- Usa MT5 real (no backtest)
- Ejecuta órdenes reales sobre la cuenta demo
- Registra todo en SQLite con es_demo=1

USO:
    python run_demo.py
"""

import os
import sys
from pathlib import Path

# Forzar variables de entorno ANTES de importar Config
os.environ['ENTORNO'] = 'produccion'
os.environ['MT5_DEMO'] = 'true'

# Verificar .env cargado
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

# Verificar credenciales
MT5_LOGIN = os.getenv('MT5_LOGIN')
if not MT5_LOGIN:
    print("❌ MT5_LOGIN no configurado en .env")
    sys.exit(1)

if os.getenv('MT5_DEMO', 'true').lower() not in ('true', '1', 'yes'):
    print("⚠️  ATENCIÓN: MT5_DEMO no está en 'true'.")
    respuesta = input("¿Seguro que quieres operar en cuenta REAL? (escribe SI): ")
    if respuesta != 'SI':
        print("Cancelado")
        sys.exit(0)

print("=" * 70)
print("🎯 BOT DE TRADING - MODO PRODUCCIÓN EN CUENTA DEMO")
print("=" * 70)
print(f"   Entorno: produccion")
print(f"   MT5_DEMO: {os.getenv('MT5_DEMO')}")
print(f"   Login: {MT5_LOGIN}")
print(f"   Servidor: {os.getenv('MT5_SERVER', 'N/A')}")
print("=" * 70)

# Importar y arrancar
from core.orquestador import Orquestador

bot = Orquestador(modo_backtest=False, modo_depuracion=False)

try:
    bot.iniciar()
except KeyboardInterrupt:
    print("\n🛑 Deteniendo bot...")
    bot.detener()
except Exception as e:
    print(f"❌ Error crítico: {e}")
    import traceback
    traceback.print_exc()
    try:
        bot.detener()
    except Exception:
        pass
    raise