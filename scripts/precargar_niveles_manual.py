#!/usr/bin/env python3
"""
scripts/precargar_niveles_manual.py
Precarga manual de niveles desde datos históricos en SQLite.
VERSIÓN FINAL - SIN errores de clave.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

# Añadir el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.almacenamiento_sqlite import AlmacenamientoSQLite
from analysis.niveles_deteccion import DetectorNiveles
from config.settings import Config

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('PrecargaNiveles')


class PrecargadorNivelesManual:
    """
    Precarga manual de niveles desde datos históricos.
    Guarda niveles por timeframe por separado.
    """
    
    def __init__(self, almacen: AlmacenamientoSQLite):
        self.almacen = almacen
        self.detector = DetectorNiveles(modo_inicial=True)
        logger.info("🔧 PrecargadorNivelesManual inicializado")
    
    def precargar_simbolo(self, simbolo: str, timeframes: list = None):
        """
        Precarga niveles para un símbolo desde todos los timeframes.
        Cada timeframe guarda sus propios niveles.
        """
        if timeframes is None:
            timeframes = [60, 240, 1440]  # H1, H4, D1
        
        todos_los_niveles = {}
        
        for tf in timeframes:
            try:
                df = self.almacen.obtener_datos_historicos(simbolo, tf)
                if df is None or len(df) < 50:
                    logger.debug(f"⏭️ {simbolo} TF{tf}: Datos insuficientes")
                    continue
                
                tf_nombre = {60: 'H1', 240: 'H4', 1440: 'D1'}.get(tf, f'TF{tf}')
                niveles = self.detector.detectar_niveles(df, simbolo, tf_nombre)
                
                # ✅ ASEGURAR QUE CADA NIVEL TENGA TIMEFRAME
                for s in niveles.get('soportes', []):
                    s['timeframe'] = tf_nombre
                for r in niveles.get('resistencias', []):
                    r['timeframe'] = tf_nombre
                
                logger.info(f"📊 {simbolo} {tf_nombre}: {len(niveles.get('soportes', []))} soportes, {len(niveles.get('resistencias', []))} resistencias")
                
                # ✅ GUARDAR CADA TIMEFRAME POR SEPARADO
                self.almacen.guardar_niveles(
                    simbolo,
                    niveles.get('soportes', []),
                    niveles.get('resistencias', [])
                )
                
                # Acumular para estadísticas
                if tf_nombre not in todos_los_niveles:
                    todos_los_niveles[tf_nombre] = {'soportes': 0, 'resistencias': 0}
                todos_los_niveles[tf_nombre]['soportes'] += len(niveles.get('soportes', []))
                todos_los_niveles[tf_nombre]['resistencias'] += len(niveles.get('resistencias', []))
                
            except Exception as e:
                logger.warning(f"⚠️ Error en {simbolo} TF{tf}: {e}")
        
        return todos_los_niveles
    
    def precargar_todos(self, simbolos: list = None):
        """
        Precarga niveles para todos los símbolos.
        """
        if simbolos is None:
            simbolos = Config.SIMBOLOS_COMPLETOS
        
        logger.info(f"🚀 Precargando niveles para {len(simbolos)} símbolos...")
        
        estadisticas = {
            'total': len(simbolos),
            'con_niveles': 0,
            'total_soportes': 0,
            'total_resistencias': 0,
            'por_timeframe': {},
            'detalles': {}
        }
        
        for simbolo in simbolos:
            try:
                niveles_por_tf = self.precargar_simbolo(simbolo)
                if niveles_por_tf:
                    estadisticas['con_niveles'] += 1
                    for tf, counts in niveles_por_tf.items():
                        estadisticas['total_soportes'] += counts['soportes']
                        estadisticas['total_resistencias'] += counts['resistencias']
                        if tf not in estadisticas['por_timeframe']:
                            estadisticas['por_timeframe'][tf] = {'soportes': 0, 'resistencias': 0}
                        estadisticas['por_timeframe'][tf]['soportes'] += counts['soportes']
                        estadisticas['por_timeframe'][tf]['resistencias'] += counts['resistencias']
                    estadisticas['detalles'][simbolo] = niveles_por_tf
            except Exception as e:
                logger.error(f"❌ Error en {simbolo}: {e}")
        
        logger.info("=" * 60)
        logger.info("📊 RESUMEN DE PRECARGA:")
        logger.info(f"   Símbolos procesados: {estadisticas['total']}")
        logger.info(f"   Símbolos con niveles: {estadisticas['con_niveles']}")
        logger.info(f"   Total soportes: {estadisticas['total_soportes']}")
        logger.info(f"   Total resistencias: {estadisticas['total_resistencias']}")
        logger.info("")
        logger.info("📊 Por timeframe:")
        for tf, counts in sorted(estadisticas['por_timeframe'].items()):
            logger.info(f"   {tf}: {counts['soportes']} soportes, {counts['resistencias']} resistencias")
        logger.info("=" * 60)
        
        return estadisticas


def main():
    logger.info("🚀 INICIANDO PRECARGA MANUAL DE NIVELES...")
    
    almacen = AlmacenamientoSQLite()
    precargador = PrecargadorNivelesManual(almacen)
    
    # Precargar todos los símbolos
    simbolos = Config.SIMBOLOS_COMPLETOS
    estadisticas = precargador.precargar_todos(simbolos)
    
    logger.info("\n📊 Detalles por símbolo:")
    for simbolo, datos in sorted(estadisticas['detalles'].items()):
        logger.info(f"   {simbolo}:")
        for tf, counts in sorted(datos.items()):
            logger.info(f"      {tf}: {counts['soportes']} soportes, {counts['resistencias']} resistencias")
    
    logger.info("\n✅ PRECARGA COMPLETADA")


if __name__ == "__main__":
    main()