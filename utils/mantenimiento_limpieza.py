import os
import ast
import sys
from pathlib import Path
import argparse
from colorama import Fore, Style, init

init(autoreset=True)

def verificar_sintaxis(ruta_archivo: Path) -> bool:
    """Verifica si un archivo Python tiene errores de sintaxis usando AST."""
    try:
        with open(ruta_archivo, "r", encoding="utf-8") as f:
            ast.parse(f.read())
        return True
    except SyntaxError as e:
        print(f"{Fore.RED}❌ Error de sintaxis en {ruta_archivo.name}: {e}")
        return False
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️ No se pudo leer {ruta_archivo.name}: {e}")
        return False

def ejecutar_mantenimiento():
    base_dir = Path(__file__).parent.parent
    core_dir = base_dir / "core"
    
    # 1. Definir archivos redundantes conocidos
    # En este caso, trading_bot_principal.py es la copia obsoleta de bot_principal.py
    archivos_redundantes = [
        core_dir / "trading_bot_principal.py"
    ]

    print(f"{Fore.CYAN}🧹 Iniciando mantenimiento del Core en: {core_dir}")
    print("-" * 60)

    # 2. Eliminación de redundantes
    for archivo in archivos_redundantes:
        if archivo.exists():
            try:
                archivo.unlink()
                print(f"{Fore.GREEN}✅ Archivo redundante eliminado: {archivo.name}")
            except Exception as e:
                print(f"{Fore.RED}❌ Error al eliminar {archivo.name}: {e}")

    # 3. Escaneo de sintaxis en todo el core
    print(f"\n{Fore.CYAN}🔍 Verificando integridad de archivos .py restantes...")
    
    archivos_python = list(core_dir.glob("*.py"))
    errores_encontrados = 0

    for py_file in archivos_python:
        if not verificar_sintaxis(py_file):
            errores_encontrados += 1
            
            cuarentena_dir = core_dir / "cuarentena"
            cuarentena_dir.mkdir(exist_ok=True)
            
            respuesta = input(f"¿Deseas mover el archivo con errores {py_file.name} a la carpeta de cuarentena? (s/n): ").lower()
            if respuesta == 's': # Si el usuario confirma, mover a cuarentena
                try:
                    py_file.rename(cuarentena_dir / py_file.name)
                    print(f"{Fore.GREEN}🗑️  Archivo movido a cuarentena: {cuarentena_dir / py_file.name}")
                except Exception as e:
                    print(f"{Fore.RED}❌ Fallo al eliminar: {e}")
        else:
            print(f"{Fore.WHITE}✔️  {py_file.name}: Sintaxis OK")

    print("-" * 60)
    if errores_encontrados == 0:
        print(f"{Fore.GREEN}✨ Mantenimiento completado. El Core está limpio y funcional.")
    else:
        print(f"{Fore.YELLOW}⚠️ Se encontraron {errores_encontrados} archivos con problemas.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Herramienta de mantenimiento y limpieza del bot.")
    parser.add_argument("--check-syntax", type=str, help="Verifica la sintaxis de un archivo Python específico.")
    args = parser.parse_args()

    if args.check_syntax:
        file_to_check = Path(args.check_syntax)
        if not verificar_sintaxis(file_to_check):
            sys.exit(1) # Salir con código de error si la verificación de sintaxis falla
    else:
        # Comportamiento por defecto si no se especifica --check-syntax
        try:
            ejecutar_mantenimiento()
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Proceso cancelado por el usuario.")
            sys.exit(0)