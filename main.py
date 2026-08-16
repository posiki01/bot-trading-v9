#!/usr/bin/env python3
"""
main.py (V9.0)
Punto de entrada único del Bot de Trading.
"""

import sys
import os
from pathlib import Path

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from core.orquestador import Orquestador


def main():
    """Punto de entrada principal."""
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║  🤖 BOT DE TRADING V9.0 - PLATAFORMA INTEGRADA DE ELITE     ║
    ║  ──────────────────────────────────────────────────────────  ║
    ║  Estructura modular | Código limpio | Alto rendimiento      ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    
    bot = Orquestador()
    
    try:
        bot.iniciar()
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo bot...")
        bot.detener()
    except Exception as e:
        print(f"❌ Error crítico: {e}")
        bot.detener()
        raise


if __name__ == "__main__":
    main()