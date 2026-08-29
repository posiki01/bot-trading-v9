#!/usr/bin/env python3
"""
scripts/precargar_niveles.py
Precarga masiva de niveles de soporte/resistencia desde datos históricos en SQLite.
"""

import logging
import sys
from pathlib import Path
from typing import Dict, List, Any

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


class PrecargadorNiveles:
    """
    Precarga niveles de soporte/resistencia desde datos históricos.
    """
    
    def __init__(self, almacen: AlmacenamientoSQLite, modo_inicial: bool = True):
        """
        Inicializa el precargador.
        
        Args:
            almacen: Almacenamiento SQLite
            modo_inicial: Modo inicial (más permisivo)
        """
        self.almacen = almacen
        self.detector = DetectorNiveles(modo_inicial=modo_inicial)
        self.logger = logging.getLogger('PrecargaNiveles')
        self.logger.info("🔧 PrecargadorNiveles inicializado")
        self.logger.info(f"   Modo inicial: {modo_inicial}")
    
    def precargar_para_simbolo(self, simbolo: str, timeframes: List[int] = None) -> Dict[str, List]:
        """
        Precarga niveles para un símbolo desde datos históricos.
        
        Args:
            simbolo: Símbolo
            timeframes: Lista de timeframes a procesar (por defecto H1, H4, D1)
        
        Returns:
            Diccionario con soportes y resistencias detectados
        """
        if timeframes is None:
            timeframes = [60, 240, 1440]  # H1, H4, D1
        
        niveles_totales = {'soportes': [], 'resistencias': []}
        
        for tf in timeframes:
            try:
                # Cargar datos desde SQLite
                df = self.almacen.obtener_datos_historicos(simbolo, tf)
                if df is None or len(df) < 50:
                    self.logger.debug(f"⏭️ {simbolo} TF{tf}: Datos insuficientes ({len(df) if df else 0} velas)")
                    continue
                
                # Detectar niveles
                tf_nombre = {
                    60: 'H1',
                    240: 'H4',
                    1440: 'D1',
                }.get(tf, f'TF{tf}')
                
                niveles = self.detector.detectar_niveles(df, simbolo, tf_nombre)
                
                self.logger.info(f"📊 {simbolo} {tf_nombre}: {len(niveles.get('soportes', []))} soportes, {len(niveles.get('resistencias', []))} resistencias")
                
                niveles_totales['soportes'].extend(niveles.get('soportes', []))
                niveles_totales['resistencias'].extend(niveles.get('resistencias', []))
                
            except Exception as e:
                self.logger.warning(f"⚠️ Error procesando {simbolo} TF{tf}: {e}")
        
        # Guardar en SQLite
        if niveles_totales['soportes'] or niveles_totales['resistencias']:
            self.almacen.guardar_niveles(
                simbolo,
                niveles_totales['soportes'],
                niveles_totales['resistencias']
            )
            self.logger.info(f"✅ {simbolo}: {len(niveles_totales['soportes'])} soportes, {len(niveles_totales['resistencias'])} resistencias guardados en SQLite")
        else:
            self.logger.warning(f"⚠️ {simbolo}: No se detectaron niveles")
        
        return niveles_totales
    
    def precargar_todos(self, simbolos: List[str] = None) -> Dict[str, Any]:
        """
        Precarga niveles para todos los símbolos.
        
        Args:
            simbolos: Lista de símbolos (por defecto todos los de Config)
        
        Returns:
            Estadísticas de la precarga
        """
        if simbolos is None:
            simbolos = Config.SIMBOLOS_COMPLETOS
        
        self.logger.info(f"🚀 Iniciando precarga de niveles para {len(simbolos)} símbolos...")
        
        estadisticas = {
            'total_simbolos': len(simbolos),
            'simbolos_con_niveles': 0,
            'total_soportes': 0,
            'total_resistencias': 0,
            'detalles_por_simbolo': {}
        }
        
        for simbolo in simbolos:
            try:
                niveles = self.precargar_para_simbolo(simbolo)
                
                if niveles['soportes'] or niveles['resistencias']:
                    estadisticas['simbolos_con_niveles'] += 1
                    estadisticas['total_soportes'] += len(niveles['soportes'])
                    estadisticas['total_resistencias'] += len(niveles['resistencias'])
                    estadisticas['detalles_por_simbolo'][simbolo] = {
                        'soportes': len(niveles['soportes']),
                        'resistencias': len(niveles['resistencias'])
                    }
            except Exception as e:
                self.logger.error(f"❌ Error en {simbolo}: {e}")
        
        self.logger.info("=" * 60)
        self.logger.info("📊 RESUMEN DE PRECARGA:")
        self.logger.info(f"   Símbolos procesados: {estadisticas['total_simbolos']}")
        self.logger.info(f"   Símbolos con niveles: {estadisticas['simbolos_con_niveles']}")
        self.logger.info(f"   Total soportes: {estadisticas['total_soportes']}")
        self.logger.info(f"   Total resistencias: {estadisticas['total_resistencias']}")
        self.logger.info("=" * 60)
        
        return estadisticas


def main():
    """Función principal."""
    logger.info("🚀 INICIANDO PRECARGA DE NIVELES...")
    
    # Inicializar almacenamiento
    almacen = AlmacenamientoSQLite()
    
    # Crear precargador
    precargador = PrecargadorNiveles(
        almacen=almacen,
        modo_inicial=True
    )
    
    # Ejecutar precarga
    estadisticas = precargador.precargar_todos()
    
    # Mostrar detalles
    logger.info("📊 Detalles por símbolo:")
    for simbolo, datos in sorted(estadisticas['detalles_por_simbolo'].items()):
        logger.info(f"   {simbolo}: {datos['soportes']} soportes, {datos['resistencias']} resistencias")
    
    logger.info("✅ PRECARGA COMPLETADA")


if __name__ == "__main__":
    main()