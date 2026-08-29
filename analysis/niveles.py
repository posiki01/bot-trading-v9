#!/usr/bin/env python3
"""
analysis/niveles.py (V9.6 - CORRECCIÓN DE ZONAS HORARIAS)
Sistema de detección y acumulación de niveles de soporte y resistencia.

MEJORAS V9.6:
- Corregido error de zonas horarias en _limpiar_niveles_antiguos.
- Carga niveles de TODOS los timeframes desde SQLite.
- Logs mejorados para depuración.
"""

import logging
import sqlite3
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

logger = logging.getLogger('BotTrading.NivelTracker')


class NivelTracker:
    """
    Sistema de detección y acumulación de niveles de soporte/resistencia.
    V9.6 - CORRECCIÓN DE ZONAS HORARIAS.
    """

    # Configuración
    NIVEL_LOOKBACK = 50  # Velas H1 para detectar niveles (en producción)
    NIVEL_TOLERANCIA_PCT = 0.002  # 0.2% de tolerancia para agrupar niveles
    NIVEL_MIN_HITS = 2  # Mínimo de toques para considerar un nivel válido
    NIVEL_MAX_EDAD_DIAS = 7  # Máxima edad de un nivel antes de decaer
    NIVEL_DECAY_HITS = 0.5  # Reducción de hits por cada día de antigüedad

    def __init__(self, almacen: Optional[Any] = None, config: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el tracker de niveles.

        Args:
            almacen: Almacenamiento SQLite (para persistencia real)
            config: Configuración
            modo_backtest: Modo backtest (mayor acumulación)
        """
        self.almacen = almacen
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.NivelTracker')

        # Ajustes para backtest
        if self.modo_backtest:
            self.NIVEL_LOOKBACK = 100
            self.NIVEL_MIN_HITS = 1
            self.NIVEL_MAX_EDAD_DIAS = 14

        # ✅ MEMORIA DE NIVELES
        self._niveles_memoria: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: {
            'soportes': [],
            'resistencias': []
        })

        # ✅ Caché de últimas detecciones
        self._ultima_deteccion: Dict[str, datetime] = {}

        # Cargar niveles desde SQLite (TODOS los timeframes)
        self._cargar_niveles_iniciales()

        self.logger.info(f"📊 NivelTracker V9.6 CORRECCIÓN ZONAS HORARIAS inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")

    # ============================================================
    # CARGA DESDE SQLITE
    # ============================================================

    def _cargar_niveles_iniciales(self):
        """
        Carga niveles desde la base de datos SQLite.
        CORREGIDO: Carga TODOS los timeframes, no solo H1.
        """
        if not self.almacen:
            return
        
        try:
            conn = sqlite3.connect(self.almacen.base_dir / "bot_data.db")
            cursor = conn.cursor()
            
            cursor.execute("""
            SELECT simbolo, timeframe, tipo, precio, hits, fuerza, fecha_deteccion, fecha_ultimo_toque
            FROM niveles_por_timeframe
            """)
            
            rows = cursor.fetchall()
            conn.close()
            
            simbolos_cargados = set()
            total_niveles = 0
            
            for row in rows:
                simbolo = row[0]
                timeframe = row[1]
                tipo = row[2]
                precio = row[3]
                hits = row[4]
                fuerza = row[5]
                fecha_deteccion = row[6]
                fecha_ultimo_toque = row[7]
                
                nivel = {
                    'precio': precio,
                    'hits': hits,
                    'fuerza': fuerza,
                    'fecha_deteccion': fecha_deteccion,
                    'fecha_ultimo_toque': fecha_ultimo_toque,
                    'tipo': tipo,
                    'timeframe': timeframe  # ✅ Añadir timeframe al nivel
                }
                
                if tipo == 'soporte':
                    self._niveles_memoria[simbolo]['soportes'].append(nivel)
                elif tipo == 'resistencia':
                    self._niveles_memoria[simbolo]['resistencias'].append(nivel)
                
                simbolos_cargados.add(simbolo)
                total_niveles += 1
            
            self.logger.info(f"📦 Niveles cargados desde SQLite para {len(simbolos_cargados)} símbolos")
            self.logger.info(f"   Total niveles: {total_niveles}")
            
            # Log detallado por símbolo
            for simbolo in simbolos_cargados:
                soportes = len(self._niveles_memoria[simbolo]['soportes'])
                resistencias = len(self._niveles_memoria[simbolo]['resistencias'])
                if soportes > 0 or resistencias > 0:
                    self.logger.info(f"   {simbolo}: {soportes} soportes, {resistencias} resistencias")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando niveles desde SQLite: {e}")

    def _guardar_niveles(self, simbolo: str):
        """Guarda niveles en almacenamiento (opcional)."""
        if self.almacen:
            try:
                soportes = self._niveles_memoria[simbolo]['soportes']
                resistencias = self._niveles_memoria[simbolo]['resistencias']
                
                self.almacen.guardar_niveles_por_timeframe(
                    simbolo=simbolo,
                    timeframe=60,
                    soportes=soportes,
                    resistencias=resistencias
                )
            except Exception as e:
                self.logger.debug(f"No se pudieron guardar niveles: {e}")

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    def detectar_y_actualizar_niveles(self,
                                      simbolo: str,
                                      df: pd.DataFrame,
                                      precio_actual: float) -> Dict[str, List[float]]:
        """
        Detecta nuevos niveles y los acumula en la memoria.
        """
        if df is None or len(df) < self.NIVEL_LOOKBACK:
            return {
                'soportes': self._niveles_memoria[simbolo]['soportes'],
                'resistencias': self._niveles_memoria[simbolo]['resistencias']
            }

        # ✅ 1. Limpiar niveles antiguos
        self._limpiar_niveles_antiguos(simbolo)

        # ✅ 2. Detectar nuevos niveles en la última vela
        nuevos_soportes, nuevas_resistencias = self._detectar_niveles_ultima_vela(
            simbolo, df, precio_actual
        )

        # ✅ 3. Acumular nuevos niveles
        if nuevos_soportes:
            for nivel in nuevos_soportes:
                precio = nivel['precio']
                hits = nivel.get('hits', 1)
                self._acumular_nivel(simbolo, 'soportes', precio, hits)

        if nuevas_resistencias:
            for nivel in nuevas_resistencias:
                precio = nivel['precio']
                hits = nivel.get('hits', 1)
                self._acumular_nivel(simbolo, 'resistencias', precio, hits)

        # ✅ 4. Ordenar y devolver niveles acumulados
        soportes = sorted(self._niveles_memoria[simbolo]['soportes'],
                         key=lambda x: x['precio'], reverse=False)
        resistencias = sorted(self._niveles_memoria[simbolo]['resistencias'],
                            key=lambda x: x['precio'], reverse=True)

        # ✅ 5. Actualizar caché
        self._ultima_deteccion[simbolo] = datetime.now(timezone.utc)

        return {
            'soportes': soportes,
            'resistencias': resistencias
        }

    # ============================================================
    # DETECCIÓN DE NIVELES
    # ============================================================

    def _detectar_niveles_ultima_vela(self,
                                      simbolo: str,
                                      df: pd.DataFrame,
                                      precio_actual: float) -> Tuple[List[Dict], List[Dict]]:
        """Detecta nuevos niveles basados en la última vela."""
        if len(df) < self.NIVEL_LOOKBACK:
            return [], []

        ventana = df.iloc[-self.NIVEL_LOOKBACK:]
        high = ventana['High']
        low = ventana['Low']

        soportes_nuevos = []
        resistencias_nuevas = []

        for i in range(5, len(ventana) - 5):
            if low.iloc[i] == low.iloc[i-5:i+5].min():
                precio_nivel = low.iloc[i]
                if abs(precio_actual - precio_nivel) / precio_actual < 0.02:
                    continue
                if not self._nivel_existe(simbolo, 'soportes', precio_nivel):
                    hits = self._contar_toques_nivel(ventana, precio_nivel, 'soporte')
                    if hits >= self.NIVEL_MIN_HITS:
                        soportes_nuevos.append({
                            'precio': precio_nivel,
                            'hits': hits,
                            'fecha_deteccion': ventana.index[i],
                            'fecha_ultimo_toque': ventana.index[-1],
                            'tipo': 'soporte'
                        })

            if high.iloc[i] == high.iloc[i-5:i+5].max():
                precio_nivel = high.iloc[i]
                if abs(precio_actual - precio_nivel) / precio_actual < 0.02:
                    continue
                if not self._nivel_existe(simbolo, 'resistencias', precio_nivel):
                    hits = self._contar_toques_nivel(ventana, precio_nivel, 'resistencia')
                    if hits >= self.NIVEL_MIN_HITS:
                        resistencias_nuevas.append({
                            'precio': precio_nivel,
                            'hits': hits,
                            'fecha_deteccion': ventana.index[i],
                            'fecha_ultimo_toque': ventana.index[-1],
                            'tipo': 'resistencia'
                        })

        return soportes_nuevos, resistencias_nuevas

    def _contar_toques_nivel(self, df: pd.DataFrame, precio_nivel: float, tipo: str) -> int:
        hits = 0
        tolerancia = self.NIVEL_TOLERANCIA_PCT * precio_nivel
        for i in range(len(df)):
            if tipo == 'soporte':
                if abs(df['Low'].iloc[i] - precio_nivel) <= tolerancia:
                    hits += 1
            else:
                if abs(df['High'].iloc[i] - precio_nivel) <= tolerancia:
                    hits += 1
        return hits

    # ============================================================
    # ACUMULACIÓN DE NIVELES
    # ============================================================

    def _acumular_nivel(self, simbolo: str, tipo: str, precio: float, hits: int = 1):
        nivel_existente = None
        tolerancia = self.NIVEL_TOLERANCIA_PCT * precio
        for nivel in self._niveles_memoria[simbolo][tipo]:
            if abs(nivel['precio'] - precio) <= tolerancia:
                nivel_existente = nivel
                break
        if nivel_existente:
            nivel_existente['hits'] += hits
            nivel_existente['fecha_ultimo_toque'] = datetime.now(timezone.utc)
            if nivel_existente['hits'] >= 5:
                nivel_existente['fuerza'] = 'FUERTE'
            elif nivel_existente['hits'] >= 3:
                nivel_existente['fuerza'] = 'MEDIO'
            else:
                nivel_existente['fuerza'] = 'DEBIL'
        else:
            nuevo_nivel = {
                'precio': precio,
                'hits': hits,
                'fecha_deteccion': datetime.now(timezone.utc),
                'fecha_ultimo_toque': datetime.now(timezone.utc),
                'tipo': tipo,
                'fuerza': 'DEBIL' if hits < 3 else 'MEDIO' if hits < 5 else 'FUERTE'
            }
            self._niveles_memoria[simbolo][tipo].append(nuevo_nivel)

    def _nivel_existe(self, simbolo: str, tipo: str, precio: float) -> bool:
        tolerancia = self.NIVEL_TOLERANCIA_PCT * precio
        for nivel in self._niveles_memoria[simbolo][tipo]:
            if abs(nivel['precio'] - precio) <= tolerancia:
                return True
        return False

    # ============================================================
    # LIMPIEZA DE NIVELES ANTIGUOS (CORREGIDO)
    # ============================================================

    def _limpiar_niveles_antiguos(self, simbolo: str):
        """Limpia niveles antiguos con decaimiento progresivo."""
        ahora = datetime.now(timezone.utc)
        max_edad = timedelta(days=self.NIVEL_MAX_EDAD_DIAS)

        for tipo in ['soportes', 'resistencias']:
            niveles = self._niveles_memoria[simbolo][tipo]
            niveles_filtrados = []

            for nivel in niveles:
                fecha_ultimo_toque = nivel.get('fecha_ultimo_toque', nivel.get('fecha_deteccion'))
                
                # ✅ CORREGIDO: Convertir a offset-aware si es offset-naive
                if isinstance(fecha_ultimo_toque, str):
                    try:
                        fecha_ultimo_toque = datetime.fromisoformat(fecha_ultimo_toque)
                    except:
                        fecha_ultimo_toque = ahora - timedelta(days=1)
                
                # ✅ Asegurar que tenga zona horaria UTC
                if fecha_ultimo_toque.tzinfo is None:
                    fecha_ultimo_toque = fecha_ultimo_toque.replace(tzinfo=timezone.utc)

                edad = (ahora - fecha_ultimo_toque).days

                # ✅ Decaimiento por edad
                if edad > self.NIVEL_MAX_EDAD_DIAS:
                    continue
                elif edad > self.NIVEL_MAX_EDAD_DIAS // 2:
                    nivel['hits'] = max(1, nivel['hits'] - self.NIVEL_DECAY_HITS)
                    if nivel['hits'] < self.NIVEL_MIN_HITS:
                        continue

                niveles_filtrados.append(nivel)

            self._niveles_memoria[simbolo][tipo] = niveles_filtrados

    # ============================================================
    # MÉTODOS DE CONSULTA
    # ============================================================

    def obtener_niveles(self, simbolo: str) -> Dict[str, List[Dict]]:
        """Obtiene niveles."""
        if simbolo not in self._niveles_memoria:
            return {'soportes': [], 'resistencias': []}
        self._limpiar_niveles_antiguos(simbolo)
        return {
            'soportes': sorted(self._niveles_memoria[simbolo]['soportes'], key=lambda x: x['precio']),
            'resistencias': sorted(self._niveles_memoria[simbolo]['resistencias'], key=lambda x: x['precio'], reverse=True)
        }
    
    def obtener_nivel_fuerte(self, simbolo: str, direccion: str) -> Optional[float]:
        niveles = self.obtener_niveles(simbolo)
        if direccion == 'COMPRA':
            for soporte in niveles['soportes']:
                if soporte.get('fuerza') == 'FUERTE':
                    return soporte['precio']
        else:
            for resistencia in niveles['resistencias']:
                if resistencia.get('fuerza') == 'FUERTE':
                    return resistencia['precio']
        return None

    def limpiar_memoria(self):
        self._niveles_memoria.clear()
        self.logger.info("🧹 Memoria de niveles limpiada")

    def get_stats(self, simbolo: Optional[str] = None) -> Dict[str, Any]:
        if simbolo:
            if simbolo not in self._niveles_memoria:
                return {}
            return {
                'simbolo': simbolo,
                'soportes': len(self._niveles_memoria[simbolo]['soportes']),
                'resistencias': len(self._niveles_memoria[simbolo]['resistencias']),
                'soportes_fuertes': sum(1 for n in self._niveles_memoria[simbolo]['soportes'] if n.get('fuerza') == 'FUERTE'),
                'resistencias_fuertes': sum(1 for n in self._niveles_memoria[simbolo]['resistencias'] if n.get('fuerza') == 'FUERTE'),
            }
        else:
            return {simbolo: self.get_stats(simbolo) for simbolo in self._niveles_memoria}


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_nivel_tracker(almacen: Optional[Any] = None,
                         config: Optional[Any] = None,
                         modo_backtest: bool = False) -> NivelTracker:
    return NivelTracker(
        almacen=almacen,
        config=config,
        modo_backtest=modo_backtest
    )