# patch_reloj.py
"""
Aplica el parche de now_utc() a los módulos críticos.
Ejecutar UNA VEZ desde la raíz del proyecto.
"""
import re
from pathlib import Path

ARCHIVOS = [
    'utils/tiempo.py',
    'trading/trailing.py',
    'trading/monitoreo.py',
    'trading/riesgo_circuit.py',
    'trading/riesgo.py',
    'analysis/pipeline.py',
    'trading/sniper/sniper_checklist.py',
    'core/orquestador.py',
    'reportes/informe_diario.py',
]

# Patrones a reemplazar
PATRONES = [
    # datetime.now(timezone.utc) → now_utc()
    (r'\bdatetime\.now\(timezone\.utc\)', 'now_utc()'),
    # datetime.now(tz=timezone.utc) → now_utc()
    (r'\bdatetime\.now\(tz=timezone\.utc\)', 'now_utc()'),
]

def patch_archivo(ruta: Path) -> int:
    if not ruta.exists():
        print(f"  ⚠️  No existe: {ruta}")
        return 0

    contenido = ruta.read_text(encoding='utf-8')
    original = contenido

    cambios = 0
    for patron, reemplazo in PATRONES:
        nuevo, n = re.subn(patron, reemplazo, contenido)
        cambios += n
        contenido = nuevo

    if cambios == 0:
        print(f"  ℹ️  Sin cambios: {ruta}")
        return 0

    # Añadir import si no existe
    if 'from utils.reloj import now_utc' not in contenido:
        # Insertar después del último import del bloque superior
        lineas = contenido.split('\n')
        idx_ultimo_import = 0
        for i, linea in enumerate(lineas[:50]):
            if linea.startswith('import ') or linea.startswith('from '):
                idx_ultimo_import = i

        # Añadir import
        lineas.insert(idx_ultimo_import + 1, 'from utils.reloj import now_utc')
        contenido = '\n'.join(lineas)

    ruta.write_text(contenido, encoding='utf-8')
    print(f"  ✅ {ruta}: {cambios} reemplazos")
    return cambios

def main():
    print("🔧 Aplicando parche now_utc()...")
    base = Path.cwd()
    total = 0

    for archivo in ARCHIVOS:
        ruta = base / archivo
        total += patch_archivo(ruta)

    print(f"\n✅ Total: {total} reemplazos")
    print("\n⚠️  Verifica manualmente:")
    print("   1. Que los imports se hayan insertado en el sitio correcto")
    print("   2. Que no haya falsos positivos")
    print("   3. Que el código sigue compilando")

if __name__ == "__main__":
    main()