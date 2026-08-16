#!/usr/bin/env python3
# scripts/actualizar_imports.py

import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Mapeo de imports antiguos a nuevos
MAPEO_IMPORTS = {
    # Análisis
    r'from analysis.capas': 'from analysis.capas',
    r'from analysis.fases': 'from analysis.fases',
    r'from analysis.tecnico': 'from analysis.tecnico',
    r'from analysis.regimen': 'from analysis.regimen',
    r'from analysis.scoring': 'from analysis.scoring',
    r'from analysis.niveles': 'from analysis.niveles',
    r'from analysis.pipeline': 'from analysis.pipeline',
    r'import analysis.capas': 'import analysis.capas',
    r'import analysis.fases': 'import analysis.fases',
    r'import analysis.tecnico': 'import analysis.tecnico',
    r'import analysis.regimen': 'import analysis.regimen',
    r'import analysis.scoring': 'import analysis.scoring',
    r'from analysis.niveles': 'from analysis.niveles',
    
    # Trading
    r'from trading.riesgo': 'from trading.riesgo',
    r'from trading.stops': 'from trading.stops',
    r'from trading.trailing': 'from trading.trailing',
    r'from trading.modos': 'from trading.modos',
    r'from trading.timer': 'from trading.timer',
    r'from trading.sniper_checklist': 'from trading.sniper_checklist',
    r'import trading.riesgo': 'import trading.riesgo',
    r'import trading.stops': 'import trading.stops',
    r'import trading.trailing': 'import trading.trailing',
    
    # Utilidad
    r'from utils.tiempo': 'from utils.tiempo',
    r'from utils.cache': 'from utils.cache',
    r'from utils.cache_data': 'from utils.cache_data',
    r'import utils.tiempo': 'import utils.tiempo',
    r'import utils.cache': 'import utils.cache',
    r'import utils.cache_data': 'import utils.cache_data',
    
    # Otros
    r'from trading.operabilidad': 'from trading.operabilidad',
    r'from analysis.patron_tracker': 'from analysis.patron_tracker',
    r'from analysis.ml_optimizer': 'from analysis.ml_optimizer',
}

def detectar_encoding(ruta):
    """Detecta la codificación de un archivo."""
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    for enc in encodings:
        try:
            with open(ruta, 'r', encoding=enc) as f:
                f.read()
            return enc
        except UnicodeDecodeError:
            continue
    return None

def actualizar_archivo(ruta):
    """Actualiza los imports en un archivo."""
    # Detectar encoding
    encoding = detectar_encoding(ruta)
    if encoding is None:
        print(f"⚠️ No se pudo detectar encoding para: {ruta}")
        return False
    
    try:
        with open(ruta, 'r', encoding=encoding) as f:
            contenido = f.read()
    except Exception as e:
        print(f"❌ Error leyendo {ruta}: {e}")
        return False
    
    original = contenido
    for patron, nuevo in MAPEO_IMPORTS.items():
        contenido = re.sub(patron, nuevo, contenido)
    
    if contenido != original:
        try:
            # Guardar en UTF-8 (estandarizar)
            with open(ruta, 'w', encoding='utf-8') as f:
                f.write(contenido)
            print(f"✅ Actualizado: {ruta}")
            return True
        except Exception as e:
            print(f"❌ Error guardando {ruta}: {e}")
            return False
    return False

def main():
    """Ejecuta la actualización de imports."""
    print("🔄 Actualizando imports en toda la estructura...")
    
    # Directorios a procesar
    directorios = ['core', 'analysis', 'trading', 'utils', 'mt5', 'data', 'noticias', 'notificaciones']
    
    contador = 0
    for directorio in directorios:
        ruta_dir = BASE_DIR / directorio
        if not ruta_dir.exists():
            print(f"⚠️ Directorio no encontrado: {directorio}")
            continue
        
        for ruta in ruta_dir.rglob('*.py'):
            if 'venv' in str(ruta) or '__pycache__' in str(ruta):
                continue
            if actualizar_archivo(ruta):
                contador += 1
    
    # Procesar archivos en raíz
    for ruta in BASE_DIR.glob('*.py'):
        if 'venv' in str(ruta) or '__pycache__' in str(ruta):
            continue
        if actualizar_archivo(ruta):
            contador += 1
    
    print(f"✅ {contador} archivos actualizados correctamente")

if __name__ == "__main__":
    main()