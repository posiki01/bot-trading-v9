#!/usr/bin/env python3
"""
scripts/precargar_niveles.py (V1.0)
Precarga de niveles de soporte y resistencia desde datos históricos.

PROPÓSITO:
- Poblar la base de datos SQLite con niveles desde el día 1
- Acumular hits iniciales usando datos históricos
- Permitir que el bot detecte modos como NIVEL_FUERTE desde el inicio
"""

import logging
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

# Agregar raíz al path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Config
from analysis.niveles import NivelTracker
from analysis.niveles_deteccion import DetectorNiveles

logger = logging.getLogger('BotTrading.PrecargaNiveles')


class PrecargadorNiveles:
    """
    Precarga niveles de soporte y resistencia desde datos históricos.
    V1.0 - COMPLETO.
    """
    
    def __init__(self, almacen: Any, modo_inicial: bool = True, dias_historia: int = 90):
        """
        Inicializa el precargador de niveles.
        
        Args:
            almacen: Almacenamiento SQLite
            modo_inicial: Modo inicial (más permisivo)
            dias_historia: Días de historia a cargar
        """
        self.almacen = almacen
        self.modo_inicial = modo_inicial
        self.dias_historia = dias_historia
        self.logger = logging.getLogger('BotTrading.PrecargaNiveles')
        
        # Crear detector de niveles
        self.detector = DetectorNiveles(modo_inicial=modo_inicial)
        
        # Configuración
        self.umbrales = {
            'hits_minimos': 1 if modo_inicial else 2,
            'distancia_agrupacion': 0.005 if modo_inicial else 0.002,
            'max_niveles': 20,
        }
        
        self.logger.info(f"🔍 PrecargadorNiveles V1.0 inicializado")
        self.logger.info(f"   Modo inicial: {modo_inicial}")
        self.logger.info(f"   Días de historia: {dias_historia}")
    
    def precargar_todos(self, simbolos: List[str]) -> Dict[str, Any]:
        """
        Precarga niveles para todos los símbolos.
        
        Args:
            simbolos: Lista de símbolos a precargar
        
        Returns:
            Estadísticas de la precarga
        """
        self.logger.info(f"🚀 Iniciando precarga de niveles para {len(simbolos)} símbolos...")
        
        estadisticas = {
            'total_soportes': 0,
            'total_resistencias': 0,
            'simbolos_procesados': 0,
            'simbolos_errores': 0,
        }
        
        for simbolo in simbolos:
            try:
                niveles = self._precargar_simbolo(simbolo)
                
                if niveles:
                    self.almacen.guardar_niveles(
                        simbolo,
                        niveles.get('soportes', []),
                        niveles.get('resistencias', [])
                    )
                    
                    estadisticas['total_soportes'] += len(niveles.get('soportes', []))
                    estadisticas['total_resistencias'] += len(niveles.get('resistencias', []))
                    estadisticas['simbolos_procesados'] += 1
                    
                    self.logger.info(f"✅ {simbolo}: {len(niveles.get('soportes', []))} soportes, {len(niveles.get('resistencias', []))} resistencias precargados")
                else:
                    estadisticas['simbolos_errores'] += 1
                    self.logger.warning(f"⚠️ {simbolo}: No se pudieron precargar niveles")
                    
            except Exception as e:
                estadisticas['simbolos_errores'] += 1
                self.logger.error(f"❌ Error precargando {simbolo}: {e}")
        
        self.logger.info(f"✅ Precarga completada:")
        self.logger.info(f"   Símbolos procesados: {estadisticas['simbolos_procesados']}")
        self.logger.info(f"   Símbolos con errores: {estadisticas['simbolos_errores']}")
        self.logger.info(f"   Total soportes: {estadisticas['total_soportes']}")
        self.logger.info(f"   Total resistencias: {estadisticas['total_resistencias']}")
        
        return estadisticas
    
    def _precargar_simbolo(self, simbolo: str) -> Optional[Dict[str, List]]:
        """
        Precarga niveles para un símbolo individual.
        
        Args:
            simbolo: Símbolo a precargar
        
        Returns:
            Diccionario con 'soportes' y 'resistencias'
        """
        # 1. Conectar a MT5
        if not mt5.initialize():
            self.logger.error(f"❌ {simbolo}: No se pudo inicializar MT5")
            return None
        
        if not mt5.symbol_select(simbolo, True):
            self.logger.error(f"❌ {simbolo}: No existe en Market Watch")
            mt5.shutdown()
            return None
        
        # 2. Definir rango de fechas
        fecha_fin = datetime.now(timezone.utc)
        fecha_inicio = fecha_fin - timedelta(days=self.dias_historia)
        
        # 3. Descargar datos H1
        self.logger.debug(f"📥 {simbolo}: Descargando {self.dias_historia} días de H1...")
        
        try:
            rates = mt5.copy_rates_range(simbolo, mt5.TIMEFRAME_H1, fecha_inicio, fecha_fin)
        except Exception as e:
            self.logger.error(f"❌ {simbolo}: Error descargando datos: {e}")
            mt5.shutdown()
            return None
        
        mt5.shutdown()
        
        if rates is None or len(rates) < 50:
            self.logger.warning(f"⚠️ {simbolo}: Datos insuficientes ({len(rates) if rates else 0} velas < 50)")
            return None
        
        # 4. Crear DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'tick_volume': 'Volume'
        }, inplace=True)
        
        # 5. Detectar niveles
        niveles = self.detector.detectar_niveles(df, simbolo, 'H1')
        
        # 6. Filtrar y limitar
        soportes = self._filtrar_niveles(niveles.get('soportes', []), 'soporte')
        resistencias = self._filtrar_niveles(niveles.get('resistencias', []), 'resistencia')
        
        # 7. Añadir metadata
        ahora = datetime.now(timezone.utc).isoformat()
        
        for s in soportes:
            s['timeframe'] = 'H1'
            s['ultima_fecha'] = ahora
            s['simbolo'] = simbolo
            s['fuerza'] = min(100, 20 + s.get('hits', 0) * 10)
        
        for r in resistencias:
            r['timeframe'] = 'H1'
            r['ultima_fecha'] = ahora
            r['simbolo'] = simbolo
            r['fuerza'] = min(100, 20 + r.get('hits', 0) * 10)
        
        return {
            'soportes': soportes[:self.umbrales['max_niveles']],
            'resistencias': resistencias[:self.umbrales['max_niveles']],
        }
    
    def _filtrar_niveles(self, niveles: List[Dict], tipo: str) -> List[Dict]:
        """
        Filtra niveles por hits y fuerza.
        
        Args:
            niveles: Lista de niveles
            tipo: 'soporte' o 'resistencia'
        
        Returns:
            Lista de niveles filtrados
        """
        hits_min = self.umbrales['hits_minimos']
        
        return [
            n for n in niveles
            if n.get('hits', 0) >= hits_min
        ]


# ============================================================
# EJECUCIÓN DIRECTA
# ============================================================

if __name__ == "__main__":
    print("🧪 PrecargadorNiveles - Prueba")
    print("   (Requiere MT5 conectado)")
    
    # Configurar logging
    logging.basicConfig(level=logging.INFO)
    
    from data.almacenamiento_sqlite import AlmacenamientoSQLite
    
    almacen = AlmacenamientoSQLite(base_dir=Path("data"))
    precargador = PrecargadorNiveles(almacen=almacen, modo_inicial=True)
    
    simbolos = ['EURUSD', 'GBPUSD', 'USDJPY']
    estadisticas = precargador.precargar_todos(simbolos)
    
    print(f"\n✅ Precarga completada:")
    print(f"   Soportes: {estadisticas['total_soportes']}")
    print(f"   Resistencias: {estadisticas['total_resistencias']}")