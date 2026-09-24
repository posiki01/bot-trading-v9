# check_parches.py
import pathlib

archivos = [
    'utils/tiempo.py',
    'trading/monitoreo.py',
    'trading/riesgo_circuit.py',
    'trading/riesgo.py',
    'analysis/pipeline.py',
    'trading/sniper/sniper_checklist.py',
    'core/orquestador.py',
    'reportes/informe_diario.py',
]

print("=" * 70)
print("VERIFICACIÓN DE PARCHES DE RELOJ")
print("=" * 70)

faltantes = []
for a in archivos:
    p = pathlib.Path(a)
    if not p.exists():
        print(f"⚠️  {a}: no existe")
        continue

    contenido = p.read_text(encoding='utf-8')
    tiene_import = 'from utils.reloj import' in contenido
    tiene_now_utc = 'now_utc()' in contenido
    tiene_old_now = 'datetime.now(timezone.utc)' in contenido

    if tiene_import and tiene_now_utc:
        if tiene_old_now:
            print(f"⚠️  {a}: import OK pero AÚN tiene datetime.now(timezone.utc)")
            faltantes.append(a)
        else:
            print(f"✅ {a}: parcheado correctamente")
    else:
        print(f"❌ {a}: FALTA parche "
              f"(import={tiene_import}, now_utc={tiene_now_utc})")
        faltantes.append(a)

print("=" * 70)
if faltantes:
    print(f"\n⚠️  {len(faltantes)} archivos con problemas:")
    for f in faltantes:
        print(f"   - {f}")
else:
    print("\n✅ Todos los parches aplicados correctamente")