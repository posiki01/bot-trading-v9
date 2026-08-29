#!/usr/bin/env python3
"""
testing/limpiar_y_recargar.py (V4.0 - REFACTORIZADO DEFINITIVO)
Limpia datos antiguos y descarga datos frescos de MT5.

V4.0 - CORRECCIONES:
- ✅ Usa ConectorPepperstone en lugar de módulo MT5 directamente
- ✅ Verifica mercado cerrado antes de descargar (_es_horario_cerrado)
- ✅ Limpia caché del conector correctamente
- ✅ Verifica estructura de DB antes de guardar
- ✅ Construye timeframes H1, H4, D1 desde M5 cuando broker no los tiene
- ✅ Usa caché unificada correctamente
- ✅ Logs más informativos
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from colorama import Fore, Style, init

# Añadir directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

init(autoreset=True)

# ============================================================
# COLORES
# ============================================================

CYAN = Fore.CYAN
GREEN = Fore.GREEN
YELLOW = Fore.YELLOW
RED = Fore.RED
WHITE = Fore.WHITE
RESET = Style.RESET_ALL

# ============================================================
# IMPORTS
# ============================================================

import pandas as pd
import MetaTrader5 as mt5

from config.settings import Config
from data.almacenamiento_sqlite import AlmacenamientoSQLite
from mt5.conector_mt5 import ConectorPepperstone
from utils.construir_timeframes import construir_desde_m5
from utils.tiempo import HorarioMercado


class LimpiarYRecargar:
    """
    Limpia datos antiguos y descarga datos frescos de MT5.
    V4.0 - REFACTORIZADO DEFINITIVO.
    """
    
    def __init__(self, modo_depuracion: bool = False):
        """
        Inicializa la limpieza y recarga.
        
        Args:
            modo_depuracion: Modo depuración (logs más detallados)
        """
        self.modo_depuracion = modo_depuracion
        self.almacen = AlmacenamientoSQLite()
        self.base_dir = Path(__file__).parent.parent / "data"
        self.horario = HorarioMercado(zona_usuario='COLOMBIA')
        
        # Conector MT5 (se crea al ejecutar)
        self.conector = None
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def ejecutar(self, simbolos: list = None, timeframes: list = None):
        """
        Ejecuta la limpieza y recarga completa.
        
        Args:
            simbolos: Lista de símbolos (default: todos los completos)
            timeframes: Lista de timeframes (default: [5, 15, 60, 240, 1440])
        """
        if simbolos is None:
            simbolos = Config.SIMBOLOS_COMPLETOS
        
        if timeframes is None:
            timeframes = [5, 15, 60, 240, 1440]
        
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}🧹 LIMPIEZA Y RECARGA COMPLETA DE DATOS (V4.0){RESET}")
        print(f"{CYAN}{'='*80}{RESET}")
        print(f"{WHITE}Fecha: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC{RESET}")
        print(f"{WHITE}Símbolos: {len(simbolos)}{RESET}")
        print(f"{WHITE}Timeframes: {timeframes}{RESET}")
        print(f"{WHITE}Modo depuración: {self.modo_depuracion}{RESET}")
        
        # ============================================================
        # 1. DIAGNÓSTICO DE ESTRUCTURA DE DB
        # ============================================================
        self._diagnosticar_estructura_db()
        
        # ============================================================
        # 2. CREAR CONECTOR MT5
        # ============================================================
        self._crear_conector()
        
        if self.conector is None:
            print(f"{RED}❌ No se pudo crear el conector MT5{RESET}")
            return
        
        # ============================================================
        # 3. LIMPIAR CACHÉ EN MEMORIA (CORREGIDO)
        # ============================================================
        self._limpiar_cache_memoria()
        
        # ============================================================
        # 4. LIMPIAR CACHÉ UNIFICADA
        # ============================================================
        self._limpiar_cache_unificado()
        
        # ============================================================
        # 5. LIMPIAR BASE DE DATOS
        # ============================================================
        self._limpiar_base_datos(simbolos, timeframes)
        
        # ============================================================
        # 6. DESCARGAR DATOS FRESCOS (CON CONSTRUCCIÓN DESDE M5)
        # ============================================================
        self._descargar_datos_frescos_v4(simbolos, timeframes)
        
        # ============================================================
        # 7. DESCONECTAR
        # ============================================================
        self.conector.desconectar()
        
        print(f"\n{GREEN}✅ LIMPIEZA Y RECARGA COMPLETADA{RESET}")
        print(f"{WHITE}📊 Total de datos en DB: {self._total_datos_en_db()}{RESET}")
    
    # ============================================================
    # CREAR CONECTOR MT5
    # ============================================================
    
    def _crear_conector(self):
        """Crea y conecta el conector MT5."""
        print(f"\n{WHITE}📍 CONECTANDO A MT5...{RESET}")
        
        self.conector = ConectorPepperstone(
            login=Config.MT5_LOGIN,
            password=Config.MT5_PASSWORD,
            server=Config.MT5_SERVER,
            magic_number=Config.MAGIC_NUMBER,
            demo=Config.MT5_DEMO
        )
        
        if not self.conector.conectar():
            print(f"  {RED}❌ No se pudo conectar a MT5{RESET}")
            self.conector = None
            return
        
        print(f"  {GREEN}✅ Conectado a MT5{RESET}")
        
        # Obtener info de cuenta
        cuenta = self.conector.info_cuenta()
        if cuenta:
            print(f"  {WHITE}Balance: ${cuenta['balance']:.2f}{RESET}")
            print(f"  {WHITE}Equity: ${cuenta['equity']:.2f}{RESET}")
    
    # ============================================================
    # DIAGNÓSTICO DE ESTRUCTURA DE DB
    # ============================================================
    
    def _diagnosticar_estructura_db(self):
        """Diagnostica la estructura de la base de datos."""
        print(f"\n{WHITE}📍 DIAGNÓSTICO DE ESTRUCTURA DE DB...{RESET}")
        
        try:
            import sqlite3
            conn = sqlite3.connect(self.almacen.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tablas = [row[0] for row in cursor.fetchall()]
            
            print(f"  {WHITE}Tablas en la base de datos ({len(tablas)}):{RESET}")
            
            tablas_historico = [t for t in tablas if t.startswith('historico_')]
            print(f"  {WHITE}Tablas de histórico: {len(tablas_historico)}{RESET}")
            
            # Mostrar solo las primeras 15 tablas
            for tabla in tablas[:15]:
                print(f"    {GREEN}✅ {tabla}{RESET}")
            
            if len(tablas) > 15:
                print(f"    {WHITE}... y {len(tablas) - 15} más{RESET}")
            
            conn.close()
            
        except Exception as e:
            print(f"  {RED}❌ Error diagnosticando DB: {e}{RESET}")
    
    # ============================================================
    # LIMPIAR CACHÉ EN MEMORIA (CORREGIDO)
    # ============================================================
    
    def _limpiar_cache_memoria(self):
        """Limpia la caché en memoria del conector MT5."""
        print(f"\n{WHITE}📍 LIMPIANDO CACHÉ EN MEMORIA...{RESET}")
        
        if self.conector is None:
            print(f"  {RED}❌ Conector no disponible{RESET}")
            return
        
        # Limpiar caché de datos de símbolos
        if hasattr(self.conector, '_cache_simbolos_data'):
            self.conector._cache_simbolos_data.clear()
            print(f"  {GREEN}✅ Caché de datos de símbolos limpiada{RESET}")
        
        # Limpiar caché de info de símbolos
        if hasattr(self.conector, '_cache_simbolos'):
            self.conector._cache_simbolos.clear()
            print(f"  {GREEN}✅ Caché de info de símbolos limpiada{RESET}")
        
        # Limpiar selección de símbolos
        if hasattr(self.conector, '_symbol_selected'):
            self.conector._symbol_selected.clear()
            print(f"  {GREEN}✅ Selección de símbolos limpiada{RESET}")
        
        # Limpiar caché de ticks
        if hasattr(self.conector, '_tick_cache'):
            self.conector._tick_cache.clear()
            print(f"  {GREEN}✅ Caché de ticks limpiada{RESET}")
        
        # Limpiar caché de posiciones
        if hasattr(self.conector, '_cache_posiciones'):
            self.conector._cache_posiciones = []
            print(f"  {GREEN}✅ Caché de posiciones limpiada{RESET}")
        
        print(f"  {GREEN}✅ Caché en memoria limpiada completamente{RESET}")
    
    # ============================================================
    # LIMPIAR CACHÉ UNIFICADA
    # ============================================================
    
    def _limpiar_cache_unificado(self):
        """Limpia la caché unificada."""
        print(f"\n{WHITE}📍 LIMPIANDO CACHÉ UNIFICADA...{RESET}")
        
        try:
            cache_dir = self.base_dir / "cache"
            if cache_dir.exists():
                archivos_eliminados = 0
                for archivo in cache_dir.glob("*.pkl"):
                    archivo.unlink()
                    archivos_eliminados += 1
                    print(f"  {GREEN}✅ {archivo.name} eliminado{RESET}")
                
                for archivo in cache_dir.glob("*.json"):
                    archivo.unlink()
                    archivos_eliminados += 1
                    print(f"  {GREEN}✅ {archivo.name} eliminado{RESET}")
                
                if archivos_eliminados == 0:
                    print(f"  {YELLOW}⚠️ No hay archivos de caché{RESET}")
                else:
                    print(f"  {GREEN}✅ {archivos_eliminados} archivos de caché eliminados{RESET}")
            else:
                print(f"  {YELLOW}⚠️ Directorio de caché no existe: {cache_dir}{RESET}")
            
            print(f"  {GREEN}✅ Caché unificada limpiada{RESET}")
        except Exception as e:
            print(f"  {RED}❌ Error limpiando caché unificada: {e}{RESET}")
    
    # ============================================================
    # LIMPIAR BASE DE DATOS
    # ============================================================
    
    def _limpiar_base_datos(self, simbolos: list, timeframes: list):
        """Limpia los datos históricos de la base de datos."""
        print(f"\n{WHITE}📍 LIMPIANDO BASE DE DATOS...{RESET}")
        
        if not self.almacen:
            print(f"  {RED}❌ No se pudo acceder al almacenamiento{RESET}")
            return
        
        try:
            import sqlite3
            conn = sqlite3.connect(self.almacen.db_path)
            cursor = conn.cursor()
            
            total_eliminadas = 0
            
            for simbolo in simbolos:
                for timeframe in timeframes:
                    tabla = f"historico_{simbolo}_{timeframe}"
                    
                    try:
                        cursor.execute(f"DELETE FROM {tabla}")
                        total_eliminadas += cursor.rowcount
                        print(f"  {GREEN}✅ {tabla}: {cursor.rowcount} registros eliminados{RESET}")
                    except Exception as e:
                        print(f"  {YELLOW}⚠️ {tabla}: No existe o error: {e}{RESET}")
            
            cursor.execute("DELETE FROM cache_analisis")
            print(f"  {GREEN}✅ cache_analisis: {cursor.rowcount} registros eliminados{RESET}")
            
            conn.commit()
            conn.close()
            
            print(f"  {GREEN}✅ BASE DE DATOS LIMPIADA: {total_eliminadas} registros eliminados{RESET}")
            
        except Exception as e:
            print(f"  {RED}❌ Error limpiando base de datos: {e}{RESET}")
    
    # ============================================================
    # DESCARGAR DATOS FRESCOS (V4 - CON MERCADO CERRADO)
    # ============================================================
    
    def _descargar_datos_frescos_v4(self, simbolos: list, timeframes: list):
        """
        Descarga datos frescos de MT5 y construye timeframes mayores desde M5.
        V6.0 - CORREGIDO: Descarga INCLUSO con mercado cerrado.
        """
        print(f"\n{WHITE}📍 DESCARGANDO DATOS FRESCOS DE MT5 (V6.0)...{RESET}")
        
        if self.conector is None:
            print(f"  {RED}❌ Conector no disponible{RESET}")
            return
        
        # ✅ AUMENTAR VELAS PARA TENER 90 DÍAS DE DATOS
        VELAS_POR_TIMEFRAME = {
            5: 30000,    # M5: 30000 velas (≈ 104 días) - Base para construir
            15: 10000,   # M15: 10000 velas (≈ 104 días)
            60: 2500,    # H1: 2500 velas (≈ 104 días) - Si broker lo tiene
            240: 600,    # H4: 600 velas (≈ 100 días) - Si broker lo tiene
            1440: 100,   # D1: 100 velas (≈ 100 días) - Si broker lo tiene
        }
        
        for simbolo in simbolos:
            print(f"\n  {CYAN}📊 {simbolo}:{RESET}")
            
            # ============================================================
            # ✅ CORRECCIÓN V6.0: NO BLOQUEAR POR MERCADO CERRADO
            # ============================================================
            # Solo informar que el mercado está cerrado, NO bloquear descarga
            if self.conector._es_horario_cerrado(simbolo):
                print(f"    {YELLOW}ℹ️ Mercado CERRADO para {simbolo} - Intentando descargar del broker{RESET}")
            
            # ============================================================
            # VERIFICAR QUE EL SÍMBOLO EXISTE
            # ============================================================
            info = self.conector.obtener_info_simbolo(simbolo)
            if info is None:
                print(f"    {RED}❌ {simbolo}: No existe en MT5{RESET}")
                continue
            
            print(f"    {GREEN}✅ {simbolo}: Info obtenida (digits: {info.digits}){RESET}")
            
            # ============================================================
            # PASO 1: DESCARGAR M5 (BASE PARA CONSTRUIR OTROS)
            # ============================================================
            print(f"    {WHITE}📥 Descargando M5 ({VELAS_POR_TIMEFRAME[5]} velas)...{RESET}")
            df_m5 = self.conector.obtener_datos(simbolo, n_velas=VELAS_POR_TIMEFRAME[5], timeframe=5)
            
            if df_m5 is not None and len(df_m5) > 0:
                self._verificar_estructura_db(simbolo, 5)
                self.almacen.guardar_datos_historicos(simbolo, 5, df_m5)
                print(f"    {GREEN}✅ TF5: {len(df_m5)} velas guardadas{RESET}")
            else:
                print(f"    {YELLOW}⚠️ TF5: No se obtuvieron datos{RESET}")
                df_m5 = None
            
            # ============================================================
            # PASO 2: DESCARGAR M15 DIRECTAMENTE
            # ============================================================
            print(f"    {WHITE}📥 Descargando M15 ({VELAS_POR_TIMEFRAME[15]} velas)...{RESET}")
            df_m15 = self.conector.obtener_datos(simbolo, n_velas=VELAS_POR_TIMEFRAME[15], timeframe=15)
            
            if df_m15 is not None and len(df_m15) > 0:
                self._verificar_estructura_db(simbolo, 15)
                self.almacen.guardar_datos_historicos(simbolo, 15, df_m15)
                print(f"    {GREEN}✅ TF15: {len(df_m15)} velas guardadas{RESET}")
            else:
                print(f"    {YELLOW}⚠️ TF15: No se obtuvieron datos{RESET}")
            
            # ============================================================
            # PASO 3: DESCARGAR H1, H4, D1 DIRECTAMENTE (SI BROKER LOS TIENE)
            # ============================================================
            for tf in [60, 240, 1440]:
                print(f"    {WHITE}📥 Descargando TF{tf} ({VELAS_POR_TIMEFRAME[tf]} velas)...{RESET}")
                df_tf = self.conector.obtener_datos(simbolo, n_velas=VELAS_POR_TIMEFRAME[tf], timeframe=tf)
                
                if df_tf is not None and len(df_tf) > 0:
                    self._verificar_estructura_db(simbolo, tf)
                    self.almacen.guardar_datos_historicos(simbolo, tf, df_tf)
                    print(f"    {GREEN}✅ TF{tf}: {len(df_tf)} velas guardadas desde broker{RESET}")
                else:
                    print(f"    {YELLOW}⚠️ TF{tf}: No disponible en broker, construyendo desde M5...{RESET}")
            
            # ============================================================
            # PASO 4: CONSTRUIR H1, H4, D1 DESDE M5 (SI NO EXISTEN)
            # ============================================================
            if df_m5 is not None and len(df_m5) > 0:
                print(f"    {WHITE}🏗️ Construyendo timeframes mayores desde M5...{RESET}")
                
                # Construir H1, H4, D1 con más velas
                timeframes_construidos = construir_desde_m5(df_m5, [60, 240, 1440])
                
                for tf in [60, 240, 1440]:
                    if tf in timeframes_construidos and len(timeframes_construidos[tf]) > 0:
                        # ✅ SOLO GUARDAR SI NO HAY DATOS DEL BROKER
                        df_existente = self.almacen.obtener_datos_historicos(simbolo, tf)
                        if df_existente is None or len(df_existente) == 0:
                            self._verificar_estructura_db(simbolo, tf)
                            self.almacen.guardar_datos_historicos(simbolo, tf, timeframes_construidos[tf])
                            print(f"    {GREEN}✅ TF{tf}: {len(timeframes_construidos[tf])} velas construidas desde M5{RESET}")
                        else:
                            print(f"    {GREEN}✅ TF{tf}: Ya tiene {len(df_existente)} velas del broker{RESET}")
                    else:
                        print(f"    {YELLOW}⚠️ TF{tf}: No se pudo construir desde M5{RESET}")
            else:
                print(f"    {YELLOW}⚠️ No se pudieron construir timeframes (sin datos M5){RESET}")
            
            print(f"    {GREEN}✅ {simbolo}: Completado{RESET}")
        
        print(f"\n  {GREEN}✅ Descarga completada{RESET}")
    
    # ============================================================
    # VERIFICAR ESTRUCTURA DE DB
    # ============================================================
    
    def _verificar_estructura_db(self, simbolo: str, timeframe: int) -> bool:
        """
        Verifica que la tabla historico_{simbolo}_{timeframe} exista.
        Si no existe, la crea.
        """
        tabla = f"historico_{simbolo}_{timeframe}"
        
        try:
            import sqlite3
            conn = sqlite3.connect(self.almacen.db_path)
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='{tabla}'
            """)
            
            existe = cursor.fetchone() is not None
            
            if not existe:
                print(f"    {YELLOW}⚠️ {tabla}: No existe, creando...{RESET}")
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {tabla} (
                        timestamp TEXT PRIMARY KEY,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume REAL
                    )
                """)
                conn.commit()
                print(f"    {GREEN}✅ {tabla}: Tabla creada correctamente{RESET}")
            
            conn.close()
            return True
            
        except Exception as e:
            print(f"    {RED}❌ Error verificando {tabla}: {e}{RESET}")
            return False
    
    # ============================================================
    # TOTAL DE DATOS EN DB
    # ============================================================
    
    def _total_datos_en_db(self) -> int:
        """Cuenta el total de registros en tablas históricas."""
        total = 0
        
        try:
            import sqlite3
            conn = sqlite3.connect(self.almacen.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'historico_%'")
            tablas = [row[0] for row in cursor.fetchall()]
            
            for tabla in tablas:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {tabla}")
                    total += cursor.fetchone()[0]
                except:
                    pass
            
            conn.close()
            
        except Exception as e:
            print(f"  {RED}❌ Error contando datos: {e}{RESET}")
        
        return total


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Limpia y recarga datos frescos de MT5")
    parser.add_argument("--simbolos", type=str, help="Lista de símbolos separados por coma")
    parser.add_argument("--timeframes", type=str, help="Lista de timeframes separados por coma (ej: 5,15,60,240)")
    parser.add_argument("--depuracion", action="store_true", help="Modo depuración")
    
    args = parser.parse_args()
    
    simbolos = args.simbolos.split(',') if args.simbolos else None
    timeframes = [int(x) for x in args.timeframes.split(',')] if args.timeframes else None
    
    limpiador = LimpiarYRecargar(modo_depuracion=args.depuracion)
    limpiador.ejecutar(simbolos=simbolos, timeframes=timeframes)