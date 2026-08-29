#!/usr/bin/env python3
"""
reset_perdidas.py - Restablece pérdidas consecutivas
"""
import sys
from pathlib import Path

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from core.orquestador import Orquestador

def main():
    """Restablece pérdidas consecutivas."""
    print("🔄 Restableciendo pérdidas consecutivas...")
    
    bot = Orquestador(modo_backtest=False)
    
    # Restablecer
    bot.gestion_riesgo.reset_perdidas_consecutivas()
    
    # Verificar
    stats = bot.gestion_riesgo.estadisticas()
    print(f"✅ Pérdidas consecutivas: {stats['perdidas_consecutivas']}")
    print(f"✅ Circuit breaker: {stats['circuit_breaker']['activo']}")
    
    bot.detener()

if __name__ == "__main__":
    main()