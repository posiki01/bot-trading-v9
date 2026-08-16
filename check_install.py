#!/usr/bin/env python3
"""
check_install.py - Verifica la instalación del Bot de Trading V9.0
"""

import sys
import importlib

# ============================================================
# MÓDULOS REQUERIDOS
# ============================================================

MODULOS = [
    ('MetaTrader5', 'mt5'),
    ('pandas', 'pd'),
    ('numpy', 'np'),
    ('sklearn', 'sklearn'),
    ('requests', 'requests'),
    ('feedparser', 'feedparser'),
    ('dotenv', 'dotenv'),
    ('colorama', 'colorama'),
]


def verificar_modulos():
    """Verifica que todos los módulos estén instalados."""
    print("🔍 Verificando módulos instalados...")
    print("-" * 50)
    
    ok = True
    for nombre, alias in MODULOS:
        try:
            modulo = importlib.import_module(nombre)
            version = getattr(modulo, '__version__', 'desconocida')
            print(f"  ✅ {nombre} {version}")
        except ImportError:
            print(f"  ❌ {nombre} NO INSTALADO")
            ok = False
    
    print("-" * 50)
    return ok


def verificar_python():
    """Verifica la versión de Python."""
    print("🐍 Verificando Python...")
    print(f"  Python {sys.version}")
    print("-" * 50)
    
    if sys.version_info < (3, 9):
        print("  ⚠️ Python 3.9 o superior recomendado")
        return False
    return True


def verificar_estructura():
    """Verifica la estructura de directorios."""
    print("📁 Verificando estructura...")
    print("-" * 50)
    
    from pathlib import Path
    base = Path(__file__).parent
    
    directorios = [
        'config', 'core', 'analysis', 'trading',
        'data', 'mt5', 'noticias', 'notificaciones', 'utils', 'logs'
    ]
    
    ok = True
    for d in directorios:
        ruta = base / d
        if ruta.exists() and ruta.is_dir():
            print(f"  ✅ {d}/")
        else:
            print(f"  ❌ {d}/ NO ENCONTRADO")
            ok = False
    
    print("-" * 50)
    return ok


def main():
    """Función principal."""
    print("=" * 50)
    print("  BOT DE TRADING V9.0 - VERIFICACIÓN")
    print("=" * 50)
    print()
    
    # 1. Verificar Python
    py_ok = verificar_python()
    print()
    
    # 2. Verificar módulos
    mod_ok = verificar_modulos()
    print()
    
    # 3. Verificar estructura
    struct_ok = verificar_estructura()
    print()
    
    # Resumen
    print("=" * 50)
    if py_ok and mod_ok and struct_ok:
        print("  ✅ TODO ESTÁ CORRECTO")
        print("  🚀 El bot está listo para ejecutarse")
    else:
        print("  ⚠️ ALGUNOS PROBLEMAS DETECTADOS")
        print("  Revisa los mensajes anteriores")
    print("=" * 50)


if __name__ == "__main__":
    main()