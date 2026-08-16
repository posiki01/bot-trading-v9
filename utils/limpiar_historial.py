import json
import os
from pathlib import Path

def limpiar_historial():
    """
    Script de utilidad para unificar el lenguaje de las direcciones de trading.
    Traduce 'BUY' -> 'COMPRA' y 'SELL' -> 'VENTA' en los archivos JSON de historial.
    """
    # Localización automática de la carpeta data basándose en la estructura del proyecto
    base_path = Path(__file__).parent.parent / "data"
    
    if not base_path.exists():
        print(f"📁 Creando carpeta de datos en: {base_path}")
        base_path.mkdir(parents=True, exist_ok=True)

    archivos = [
        base_path / "historial_operaciones.json",
        base_path / "historial_operaciones_demo.json"
    ]
    
    mapping = {
        'BUY': 'COMPRA',
        'SELL': 'VENTA',
        'buy': 'COMPRA',
        'sell': 'VENTA'
    }
    
    print(f"🧹 Iniciando limpieza de historial en: {base_path}")
    
    for archivo in archivos:
        if not archivo.exists():
            print(f"ℹ️ {archivo.name} no existe aún (el bot no ha generado historial).")
            continue
            
        try:
            with open(archivo, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            conteo = 0
            if 'operaciones' in data:
                for op in data['operaciones']:
                    original = op.get('direccion')
                    if original in mapping:
                        op['direccion'] = mapping[original]
                        conteo += 1
            
            if conteo > 0:
                with open(archivo, 'w', encoding='utf-8') as f:
                    # Guardamos con el mismo formato que usa AlmacenamientoPersistente
                    json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                print(f"✅ Archivo {archivo.name}: {conteo} entradas unificadas con éxito.")
            else:
                print(f"ℹ️ El archivo {archivo.name} ya es consistente o no tiene operaciones.")
                
        except Exception as e:
            print(f"❌ Error procesando {archivo.name}: {e}")

if __name__ == "__main__":
    limpiar_historial()