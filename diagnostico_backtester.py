# diagnostico_backtester.py
import sys
from pathlib import Path

print("=" * 70)
print("DIAGNÓSTICO backtester_v10.py")
print("=" * 70)

ruta = Path("backtesting/backtester_v10.py")

# 1. ¿Existe?
if not ruta.exists():
    print(f"❌ NO existe: {ruta.absolute()}")
    sys.exit(1)

# 2. Tamaño
tamaño = ruta.stat().st_size
print(f"✅ Existe: {ruta.absolute()}")
print(f"   Tamaño: {tamaño} bytes ({tamaño/1024:.1f} KB)")

if tamaño < 5000:
    print(f"   ⚠️  MUY PEQUEÑO (debería tener ~30KB). Archivo truncado?")

# 3. ¿Contiene la clase?
contenido = ruta.read_text(encoding='utf-8')
print(f"   Líneas: {len(contenido.splitlines())}")
print(f"   Contiene 'class BacktesterV10': {'class BacktesterV10' in contenido}")
print(f"   Contiene 'def run': {'def run' in contenido}")
print(f"   Contiene 'def cargar_datos_backtest': {'def cargar_datos_backtest' in contenido}")

# 4. Últimas 10 líneas
print(f"\n📄 Últimas 10 líneas:")
for line in contenido.splitlines()[-10:]:
    print(f"   {line}")

# 5. ¿Compila?
print(f"\n🔧 ¿Compila?")
try:
    import py_compile
    py_compile.compile(str(ruta), doraise=True)
    print("   ✅ Compila sin errores")
except py_compile.PyCompileError as e:
    print(f"   ❌ Error de compilación: {e}")

# 6. ¿Se puede importar?
print(f"\n📦 Import directo:")
try:
    import backtesting.backtester_v10 as mod
    print(f"   ✅ Módulo cargado")
    print(f"   Atributos públicos: {[x for x in dir(mod) if not x.startswith('_')]}")
    print(f"   ¿Tiene BacktesterV10?: {hasattr(mod, 'BacktesterV10')}")
except Exception as e:
    print(f"   ❌ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("=" * 70)