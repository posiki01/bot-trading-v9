#!/usr/bin/env python3
"""
main.py (V11.0 - REFACTORIZADO)
Punto de entrada único del Bot de Trading con soporte CLI completo.

USO:
    # Operación
    python main.py                       # producción (real)
    python main.py --backtest            # backtest
    python main.py --depuracion          # modo depuración
    python main.py --backtest --depuracion

    # Reportes
    python main.py --informe             # genera informe del día y sale
    python main.py --informe --fecha 2026-01-15
    python main.py --metricas            # dashboard de métricas y sale
    python main.py --metricas --dias 7
    python main.py --metricas --exportar-metricas

    # Utilidades
    python main.py --version             # muestra versión y sale
    python main.py --check               # verifica configuración y sale
    python main.py --reset-ml            # resetea el modelo ML y sale

CAMBIOS V11.0:
- ✅ CLI completo (informe, metricas, version, check, reset-ml)
- ✅ Manejo robusto de errores con traceback
- ✅ Banner con estado del sistema
- ✅ Path setup explícito
- ✅ Modo --check para diagnóstico rápido
- ✅ Reset ML integrado
"""

import sys
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import argparse
import traceback
from pathlib import Path
from datetime import datetime, timezone, date as date_cls


# ============================================================
# PATH SETUP (ANTES DE CUALQUIER IMPORT DEL PROYECTO)
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# ============================================================
# CONSTANTES
# ============================================================

VERSION = "11.0"
CODENAME = "ML-CONECTADO"


# ============================================================
# BANNER
# ============================================================

def imprimir_banner():
    """Imprime el banner del bot."""
    print(f"""
    ╔══════════════════════════════════════════════════════════════╗
    ║  🤖 BOT DE TRADING V{VERSION} - {CODENAME:<24}     ║
    ║  ──────────────────────────────────────────────────────────  ║
    ║  Pipeline 3-Fases | Circuit Breaker | ML Aprendizaje Real   ║
    ╚══════════════════════════════════════════════════════════════╝
    """)


# ============================================================
# ARGUMENTOS
# ============================================================

def parse_args():
    """Parsea los argumentos de línea de comandos."""
    p = argparse.ArgumentParser(
        prog='main.py',
        description=f"Bot de Trading V{VERSION} - {CODENAME}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python main.py                        # Producción (real)
  python main.py --backtest             # Backtest
  python main.py --backtest --depuracion
  python main.py --informe              # Informe del día y sale
  python main.py --metricas --dias 30   # Dashboard 30 días
  python main.py --check                # Diagnóstico rápido
  python main.py --reset-ml             # Resetear modelo ML
        """,
    )

    # Modo de operación
    modo = p.add_argument_group('Modo de operación')
    modo.add_argument(
        '--backtest', action='store_true',
        help='Ejecutar en modo backtest'
    )
    modo.add_argument(
        '--depuracion', action='store_true',
        help='Modo depuración (logs DEBUG)'
    )

    # Reportes
    reportes = p.add_argument_group('Reportes')
    reportes.add_argument(
        '--informe', action='store_true',
        help='Generar informe diario y salir'
    )
    reportes.add_argument(
        '--fecha', type=str, default=None,
        help='Fecha del informe (YYYY-MM-DD)'
    )
    reportes.add_argument(
        '--metricas', action='store_true',
        help='Mostrar dashboard de métricas y salir'
    )
    reportes.add_argument(
        '--dias', type=int, default=30,
        help='Ventana en días para métricas (default: 30)'
    )
    reportes.add_argument(
        '--simbolo', type=str, default=None,
        help='Filtrar métricas por símbolo'
    )
    reportes.add_argument(
        '--exportar-metricas', action='store_true',
        help='Exportar métricas a JSON'
    )
    reportes.add_argument(
        '--json', action='store_true',
        help='Salida JSON (para scripts)'
    )

    # Utilidades
    utils = p.add_argument_group('Utilidades')
    utils.add_argument(
        '--version', action='store_true',
        help='Muestra versión y sale'
    )
    utils.add_argument(
        '--check', action='store_true',
        help='Verifica configuración y sale'
    )
    utils.add_argument(
        '--reset-ml', action='store_true',
        help='Resetea el modelo ML y sale'
    )

    return p.parse_args()


# ============================================================
# HANDLERS DE MODOS ESPECIALES
# ============================================================

def modo_version():
    """Muestra la versión y sale."""
    print(f"Bot de Trading V{VERSION} ({CODENAME})")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Path: {BASE_DIR}")
    return 0


def modo_check() -> int:
    """
    Verifica la configuración del sistema.
    Retorna código de salida (0 = OK, 1 = error).
    """
    print("🔍 DIAGNÓSTICO DEL SISTEMA")
    print("=" * 60)

    errores = []
    advertencias = []

    # 1. Config
    try:
        from config.settings import Config
        print(f"✅ Config cargada")
        print(f"   Entorno: {Config.ENTORNO}")
        print(f"   Capital: ${Config.CAPITAL_INICIAL:.2f}")
        print(f"   Símbolos: {len(Config.SIMBOLOS_COMPLETOS)}")
        print(f"   MT5 Demo: {Config.MT5_DEMO}")

        # Validar
        try:
            valido = Config.verificar_env()
            if not valido:
                advertencias.append("Configuración con advertencias")
        except Exception as e:
            advertencias.append(f"Validación falló: {e}")
    except Exception as e:
        errores.append(f"Config: {e}")
        print(f"❌ Config falló: {e}")

    # 2. Umbrales
    try:
        from config.umbrales import Umbrales
        print(f"✅ Umbrales cargados")
        print(f"   Modos: {len(Umbrales.MODOS) if hasattr(Umbrales, 'MODOS') else 'N/A'}")
    except Exception as e:
        errores.append(f"Umbrales: {e}")
        print(f"❌ Umbrales fallaron: {e}")

    # 3. SQLite
    try:
        from data.almacenamiento_sqlite import AlmacenamientoSQLite
        almacen = AlmacenamientoSQLite(base_dir=BASE_DIR / "data")
        ops = almacen.obtener_operaciones({'estado': 'CERRADA', 'limite': 1})
        print(f"✅ SQLite OK")
        print(f"   Operaciones cerradas: {len(ops)}")
        almacen.cerrar()
    except Exception as e:
        errores.append(f"SQLite: {e}")
        print(f"❌ SQLite falló: {e}")

    # 4. Pipeline
    try:
        from analysis.pipeline import PipelineOportunidades
        pipeline = PipelineOportunidades(modo_backtest=True)
        print(f"✅ Pipeline V11.0 OK")
        print(f"   Estados: {len(pipeline.estados)}")
    except Exception as e:
        errores.append(f"Pipeline: {e}")
        print(f"❌ Pipeline falló: {e}")

    # 5. ML
    try:
        from analysis.ml.ml_optimizer import create_ml_optimizer
        ml = create_ml_optimizer(modo_backtest=True)
        info = ml.get_info()
        print(f"✅ ML Optimizer V2.0 OK")
        print(f"   Modelo cargado: {'✅' if info['tiene_modelo'] else '⏳ (aprendiendo)'}")
        if info['ultima_fecha_entreno']:
            print(f"   Último entreno: {info['ultima_fecha_entreno'][:19]}")
    except Exception as e:
        errores.append(f"ML: {e}")
        print(f"❌ ML falló: {e}")

    # 6. Conector MT5 (solo importar, no conectar)
    try:
        from mt5.conector_mt5 import ConectorPepperstone
        print(f"✅ Conector MT5 importable")
    except Exception as e:
        advertencias.append(f"MT5 import: {e}")
        print(f"⚠️ MT5 no disponible: {e}")

    # Resultado
    print("=" * 60)
    if errores:
        print(f"❌ {len(errores)} ERROR(ES):")
        for e in errores:
            print(f"   - {e}")
        return 1
    elif advertencias:
        print(f"⚠️ {len(advertencias)} ADVERTENCIA(S):")
        for a in advertencias:
            print(f"   - {a}")
        print("✅ Sistema operativo con advertencias")
        return 0
    else:
        print("✅ Sistema OK - Listo para operar")
        return 0


def modo_reset_ml() -> int:
    """Resetea el modelo ML."""
    print("🧠 RESET DEL MODELO ML")
    print("=" * 60)

    try:
        from analysis.ml.ml_persistencia import MLCache

        cache = MLCache(base_dir=BASE_DIR / "data")

        # Verificar si existe
        if not cache.existe_modelo():
            print("ℹ️ No hay modelo guardado")
            return 0

        # Preguntar confirmación
        respuesta = input("⚠️ ¿Confirmar reset del modelo ML? (s/N): ").strip().lower()
        if respuesta not in ('s', 'si', 'sí', 'y', 'yes'):
            print("❌ Cancelado")
            return 0

        # Eliminar
        exito = cache.eliminar_modelo()
        if exito:
            print("✅ Modelo eliminado")
            print("   El bot re-entrenará con las próximas operaciones")
            return 0
        else:
            print("❌ Error eliminando modelo")
            return 1

    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


def modo_informe(args) -> int:
    """Genera informe diario y sale."""
    print("📊 Generando informe diario...")

    try:
        from core.orquestador import Orquestador

        bot = Orquestador(
            modo_backtest=args.backtest,
            modo_depuracion=args.depuracion,
        )

        fecha = None
        if args.fecha:
            try:
                fecha = date_cls.fromisoformat(args.fecha)
            except ValueError:
                print(f"❌ Fecha inválida: {args.fecha}")
                return 1

        informe = bot.informe_diario.generar(fecha=fecha)
        bot.informe_diario.guardar(informe)
        bot.informe_diario.enviar(informe)

        print(f"\n✅ Informe generado")
        print(f"   PnL: ${informe['resumen']['pnl_neto']:+.2f}")
        print(f"   Win rate: {informe['resumen']['win_rate']:.1f}%")
        print(f"   Ops: {informe['resumen']['total']}")

        return 0

    except Exception as e:
        print(f"❌ Error generando informe: {e}")
        traceback.print_exc()
        return 1


def modo_metricas(args) -> int:
    """Muestra dashboard de métricas y sale."""
    if not args.json:
        print("📊 Generando dashboard de métricas...")

    try:
        from reportes.metricas_dashboard import DashboardMetricas

        # Cargar ML optimizer (opcional)
        ml_optimizer = None
        try:
            from analysis.ml.ml_optimizer import create_ml_optimizer
            ml_optimizer = create_ml_optimizer(modo_backtest=True)
        except Exception as e:
            if args.depuracion:
                print(f"⚠️ No se pudo cargar ML: {e}")

        dashboard = DashboardMetricas(
            ml_optimizer=ml_optimizer,
            base_dir=BASE_DIR,
        )

        reporte = dashboard.generar_reporte(
            dias=args.dias,
            simbolo=args.simbolo,
        )

        # Salida JSON o texto
        if args.json:
            import json
            print(json.dumps(reporte, indent=2, ensure_ascii=False, default=str))
        else:
            dashboard.imprimir(reporte)

        # Exportar si se pidió
        if args.exportar_metricas:
            ruta = dashboard.exportar(reporte)
            print(f"\n💾 Reporte exportado: {ruta}")

        return 0

    except Exception as e:
        print(f"❌ Error generando métricas: {e}")
        traceback.print_exc()
        return 1


def modo_operacion(args) -> int:
    """Modo normal: arranca el bot."""
    try:
        from core.orquestador import Orquestador

        bot = Orquestador(
            modo_backtest=args.backtest,
            modo_depuracion=args.depuracion,
        )

        try:
            bot.iniciar()
        except KeyboardInterrupt:
            print("\n🛑 Deteniendo bot...")
            bot.detener()
        except Exception as e:
            print(f"❌ Error crítico: {e}")
            if args.depuracion:
                traceback.print_exc()
            try:
                bot.detener()
            except Exception:
                pass
            return 1

        return 0

    except ImportError as e:
        print(f"❌ Error de importación: {e}")
        print("   Verifica que estás ejecutando desde la raíz del proyecto")
        if args.depuracion:
            traceback.print_exc()
        return 1
    except Exception as e:
        print(f"❌ Error inicializando orquestador: {e}")
        if args.depuracion:
            traceback.print_exc()
        return 1


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    """Punto de entrada principal."""
    args = parse_args()

    # Modo version (no muestra banner)
    if args.version:
        return modo_version()

    # Banner
    imprimir_banner()

    # Modo check
    if args.check:
        return modo_check()

    # Modo reset-ml
    if args.reset_ml:
        return modo_reset_ml()

    # Modo métricas
    if args.metricas:
        return modo_metricas(args)

    # Modo informe
    if args.informe:
        return modo_informe(args)

    # Modo normal (operación)
    return modo_operacion(args)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n🛑 Interrumpido por el usuario")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")
        traceback.print_exc()
        sys.exit(1)