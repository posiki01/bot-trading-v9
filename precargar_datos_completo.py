#!/usr/bin/env python3
"""
precargar_datos_completo_corregido.py
Precarga COMPLETA de datos: H1, H4, D1, M15, M5 y niveles de cada timeframe.
VERSIÓN CORREGIDA - Usa timeframes numéricos.
"""

import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
import MetaTrader5 as mt5
import pandas as pd
import sqlite3

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from data.almacenamiento_sqlite import AlmacenamientoSQLite
from analysis.niveles import NivelTracker
from analysis.regimen import MarketRegimeFilter, RegimenData
from analysis.scoring import ScoreEngine
from analysis.capas import AnalisisPorCapas
from analysis.capas_deteccion import DetectorNivelesLocal
from utils.tiempo import HorarioMercado
from utils.cache import CacheUnificado

logger = logging.getLogger('BotTrading.PrecargaCompleta')


class PrecargadorCompleto:
    """
    Precarga COMPLETA de datos: H1, H4, D1, M15, M5 y niveles de cada timeframe.
    VERSIÓN CORREGIDA - Con timeframes numéricos.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.base_dir = Path(__file__).parent
        self.simbolos = self.config.SIMBOLOS_COMPLETOS
        
        # Timeframes a descargar (MT5) - CONVERTIDOS A NÚMEROS
        self.TIMEFRAMES = {
            60: mt5.TIMEFRAME_H1,
            240: mt5.TIMEFRAME_H4,
            1440: mt5.TIMEFRAME_D1,
            15: mt5.TIMEFRAME_M15,
            5: mt5.TIMEFRAME_M5,
        }
        
        # Velas por timeframe
        self.VELAS = {
            60: 500,
            240: 300,
            1440: 200,
            15: 1000,
            5: 2000,
        }
        
        # ============================================================
        # 1. Eliminar base de datos existente
        # ============================================================
        
        db_path = self.base_dir / "data" / "bot_data.db"
        backup_path = self.base_dir / "data" / "bot_data.db.backup"
        
        if db_path.exists():
            db_path.unlink()
            print(f"🗑️ Base de datos eliminada: {db_path}")
        if backup_path.exists():
            backup_path.unlink()
            print(f"🗑️ Backup eliminado: {backup_path}")
        
        # ============================================================
        # 2. Inicializar módulos y crear nuevas tablas
        # ============================================================
        
        print("📦 Inicializando módulos...")
        self.almacen = AlmacenamientoSQLite(base_dir=self.base_dir / "data")
        
        # ✅ CREAR TABLAS NECESARIAS
        self._crear_tabla_niveles_por_timeframe()
        self._crear_tabla_regimenes()
        
        self.cache = CacheUnificado(
            max_size=500,
            persist_dir=self.base_dir / "data" / "cache",
            modo_backtest=True,
            almacen=self.almacen
        )
        self.horario = HorarioMercado(
            zona_usuario='COLOMBIA',
            config_activos=self.config.CONFIG_ACTIVOS,
            modo_backtest=True
        )
        self.score_engine = ScoreEngine(
            config=self.config,
            analysis_cache=self.cache,
            modo_backtest=True
        )
        self.regimen_filter = MarketRegimeFilter(
            config=self.config,
            modo_backtest=True
        )
        self.nivel_tracker = NivelTracker(
            almacen=self.almacen,
            config=self.config,
            modo_backtest=True
        )
        self.analisis_capas = AnalisisPorCapas(
            analisis_tecnico=None,
            config=self.config,
            score_engine=self.score_engine
        )
        
        # Obtener umbrales desde analisis_capas
        umbrales = self.analisis_capas.umbrales if hasattr(self.analisis_capas, 'umbrales') else None
        self.detector_local = DetectorNivelesLocal(umbrales=umbrales)
        
        # ============================================================
        # 3. Conectar a MT5
        # ============================================================
        
        print("🔌 Conectando a MT5...")
        if not mt5.initialize():
            logger.error("❌ No se pudo inicializar MT5")
            return
        
        # ============================================================
        # 4. Descargar y analizar TODOS los timeframes
        # ============================================================
        
        print(f"📊 Analizando {len(self.simbolos)} símbolos en {len(self.TIMEFRAMES)} timeframes...")
        start_time = time.time()
        total_datos = 0
        total_niveles = 0
        
        for simbolo in self.simbolos:
            print(f"\n🔍 PROCESANDO {simbolo}...")
            
            # ============================================================
            # 4a. Descargar datos de todos los timeframes
            # ============================================================
            
            datos_por_tf = {}
            
            for tf, tf_const in self.TIMEFRAMES.items():
                try:
                    n_velas = self.VELAS[tf]
                    rates = mt5.copy_rates_from_pos(simbolo, tf_const, 0, n_velas)
                    
                    if rates is None or len(rates) < 50:
                        print(f"   ⏭️ {tf}: Datos insuficientes")
                        continue
                    
                    df = pd.DataFrame(rates)
                    df['time'] = pd.to_datetime(df['time'], unit='s')
                    df.set_index('time', inplace=True)
                    df.index = df.index.tz_localize('UTC')
                    df.rename(columns={
                        'open': 'Open', 'high': 'High', 'low': 'Low',
                        'close': 'Close', 'tick_volume': 'Volume'
                    }, inplace=True)
                    
                    datos_por_tf[tf] = df
                    total_datos += len(df)
                    
                    # Guardar en SQLite y caché
                    self.almacen.guardar_datos_historicos(simbolo, tf, df)
                    self.cache.set((simbolo, tf), df, ttl=3600)
                    
                    print(f"   ✅ {tf}: {len(df)} velas guardadas")
                    
                except Exception as e:
                    print(f"   ❌ {tf}: Error - {e}")
            
            # ============================================================
            # 4b. Detectar niveles en cada timeframe
            # ============================================================
            
            for tf, df in datos_por_tf.items():
                precio_actual = df['Close'].iloc[-1]
                
                if tf == 60:
                    niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
                        simbolo=simbolo,
                        df=df,
                        precio_actual=precio_actual
                    )
                    self._guardar_niveles_por_timeframe(
                        simbolo=simbolo,
                        timeframe=tf,
                        soportes=niveles.get('soportes', []),
                        resistencias=niveles.get('resistencias', [])
                    )
                else:
                    niveles = self.detector_local.detectar(df, simbolo)
                    self._guardar_niveles_por_timeframe(
                        simbolo=simbolo,
                        timeframe=tf,
                        soportes=niveles.get('soportes', []),
                        resistencias=niveles.get('resistencias', [])
                    )
                
                # ✅ GUARDAR NIVELES CON TIMEFRAME
                self._guardar_niveles_por_timeframe(
                    simbolo=simbolo,
                    timeframe=tf,
                    soportes=niveles.get('soportes', []),
                    resistencias=niveles.get('resistencias', [])
                )
                total_niveles += len(niveles.get('soportes', [])) + len(niveles.get('resistencias', []))
                print(f"   📊 {tf}: {len(niveles.get('soportes', []))} soportes, {len(niveles.get('resistencias', []))} resistencias")
            
            # ============================================================
            # 4c. Guardar análisis de régimen (H4 y D1)
            # ============================================================
            
            if 240 in datos_por_tf and 60 in datos_por_tf:
                try:
                    regimen_data = self.regimen_filter.clasificar(
                        simbolo, datos_por_tf[240], datos_por_tf[60]
                    )
                    self.almacen.guardar_regimen(simbolo, regimen_data)
                    print(f"   🌍 Régimen: {regimen_data.regimen.value} (conf: {regimen_data.confianza:.0f}%)")
                except Exception as e:
                    print(f"   ⚠️ Régimen falló: {e}")
        
        mt5.shutdown()
        
        elapsed = time.time() - start_time
        
        print("\n" + "=" * 60)
        print("✅ PRECARGA COMPLETA FINALIZADA")
        print("=" * 60)
        print(f"📊 Símbolos procesados: {len(self.simbolos)}")
        print(f"📊 Velas totales guardadas: {total_datos}")
        print(f"📊 Niveles totales guardados: {total_niveles}")
        print(f"⏱️ Tiempo: {elapsed:.0f}s")
        print(f"💾 Base de datos: {self.base_dir / 'data' / 'bot_data.db'}")
        print("=" * 60)
    
    # ============================================================
    # MÉTODOS AUXILIARES
    # ============================================================
    
    def _crear_tabla_niveles_por_timeframe(self):
        """Crea la tabla niveles_por_timeframe si no existe."""
        try:
            conn = sqlite3.connect(self.base_dir / "data" / "bot_data.db")
            cursor = conn.cursor()
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS niveles_por_timeframe (
                simbolo TEXT NOT NULL,
                timeframe INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                precio REAL NOT NULL,
                hits INTEGER DEFAULT 0,
                fuerza TEXT DEFAULT 'DEBIL',
                fecha_deteccion TEXT,
                fecha_ultimo_toque TEXT,
                PRIMARY KEY (simbolo, timeframe, tipo, precio)
            )
            """)
            
            conn.commit()
            conn.close()
            print("✅ Tabla 'niveles_por_timeframe' creada correctamente")
        except Exception as e:
            print(f"❌ Error creando tabla: {e}")
            raise
    
    def _crear_tabla_regimenes(self):
        """Crea la tabla regimenes si no existe."""
        try:
            conn = sqlite3.connect(self.base_dir / "data" / "bot_data.db")
            cursor = conn.cursor()
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS regimenes (
                simbolo TEXT PRIMARY KEY,
                regimen TEXT NOT NULL,
                confianza REAL,
                adx_h4 REAL,
                adx_h1 REAL,
                er_kaufman REAL,
                bb_width_pct REAL,
                atr_pct REAL,
                estructura_swings TEXT,
                direccion_favor TEXT,
                timestamp TEXT
            )
            """)
            
            conn.commit()
            conn.close()
            print("✅ Tabla 'regimenes' creada correctamente")
        except Exception as e:
            print(f"❌ Error creando tabla: {e}")
            raise
    
    def _guardar_niveles_por_timeframe(self, simbolo: str, timeframe: int,
                                       soportes: List[Dict], resistencias: List[Dict]):
        """Guarda niveles por timeframe en la tabla niveles_por_timeframe."""
        try:
            conn = sqlite3.connect(self.base_dir / "data" / "bot_data.db")
            cursor = conn.cursor()
            
            # Guardar soportes
            for s in soportes:
                precio = s['precio'] if isinstance(s, dict) else s
                hits = s.get('hits', 0) if isinstance(s, dict) else 0
                fuerza = s.get('fuerza', 'DEBIL') if isinstance(s, dict) else 'DEBIL'
                
                fecha_deteccion = s.get('fecha_deteccion', datetime.now())
                if isinstance(fecha_deteccion, datetime):
                    fecha_deteccion = fecha_deteccion.isoformat()
                
                fecha_ultimo_toque = s.get('fecha_ultimo_toque', datetime.now())
                if isinstance(fecha_ultimo_toque, datetime):
                    fecha_ultimo_toque = fecha_ultimo_toque.isoformat()
                
                cursor.execute("""
                INSERT OR REPLACE INTO niveles_por_timeframe
                (simbolo, timeframe, tipo, precio, hits, fuerza, fecha_deteccion, fecha_ultimo_toque)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (simbolo, timeframe, 'soporte', precio, hits, fuerza, fecha_deteccion, fecha_ultimo_toque))
            
            # Guardar resistencias
            for r in resistencias:
                precio = r['precio'] if isinstance(r, dict) else r
                hits = r.get('hits', 0) if isinstance(r, dict) else 0
                fuerza = r.get('fuerza', 'DEBIL') if isinstance(r, dict) else 'DEBIL'
                
                fecha_deteccion = r.get('fecha_deteccion', datetime.now())
                if isinstance(fecha_deteccion, datetime):
                    fecha_deteccion = fecha_deteccion.isoformat()
                
                fecha_ultimo_toque = r.get('fecha_ultimo_toque', datetime.now())
                if isinstance(fecha_ultimo_toque, datetime):
                    fecha_ultimo_toque = fecha_ultimo_toque.isoformat()
                
                cursor.execute("""
                INSERT OR REPLACE INTO niveles_por_timeframe
                (simbolo, timeframe, tipo, precio, hits, fuerza, fecha_deteccion, fecha_ultimo_toque)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (simbolo, timeframe, 'resistencia', precio, hits, fuerza, fecha_deteccion, fecha_ultimo_toque))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"❌ Error guardando niveles: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("🚀 PRECARGADOR COMPLETO - TODOS LOS TIMEFRAMES Y NIVELES")
    print("=" * 60)
    
    config = Config()
    precargador = PrecargadorCompleto(config)
    
    print("\n✅ Proceso completado")