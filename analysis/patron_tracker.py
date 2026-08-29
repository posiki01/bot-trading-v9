#!/usr/bin/env python3
"""
analysis/patron_tracker.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Tracker de patrones y ejecuciones con persistencia en SQLite.

RESPONSABILIDADES:
- Detectar y registrar patrones chartistas
- Rastrear ejecuciones de patrones
- Gestionar pérdidas consecutivas por símbolo
- Persistir datos en almacenamiento
- Proporcionar estadísticas de rendimiento por patrón

MEJORAS V9.0:
- Integración con umbrales centralizados
- Persistencia mejorada
- Logs detallados
- Estadísticas completas
- Limpieza automática de patrones antiguos
- Soporte para caché
- Métodos de compatibilidad
"""

import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from dataclasses import dataclass, field
import pandas as pd

# ============================================================
# IMPORTS REFACTORIZADOS
# ============================================================

from config.umbrales import Umbrales
from utils.helpers import safe_float

logger = logging.getLogger('BotTrading.PatronTracker')


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class PatronRegistro:
    """Registro de un patrón detectado."""
    simbolo: str
    patron: str
    direccion: str
    score: float
    timestamp: datetime
    activo: bool = True
    precio: float = 0.0
    calidad: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'simbolo': self.simbolo,
            'patron': self.patron,
            'direccion': self.direccion,
            'score': self.score,
            'timestamp': self.timestamp.isoformat(),
            'activo': self.activo,
            'precio': self.precio,
            'calidad': self.calidad,
            'metadata': self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PatronRegistro':
        return cls(
            simbolo=data['simbolo'],
            patron=data['patron'],
            direccion=data['direccion'],
            score=data['score'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            activo=data.get('activo', True),
            precio=data.get('precio', 0.0),
            calidad=data.get('calidad', 0.0),
            metadata=data.get('metadata', {}),
        )


@dataclass
class EjecucionRegistro:
    """Registro de una ejecución de patrón."""
    simbolo: str
    patron: str
    timestamp: datetime
    resultado: float = 0.0  # PnL
    score_entrada: float = 0.0
    duracion_minutos: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'simbolo': self.simbolo,
            'patron': self.patron,
            'timestamp': self.timestamp.isoformat(),
            'resultado': self.resultado,
            'score_entrada': self.score_entrada,
            'duracion_minutos': self.duracion_minutos,
            'metadata': self.metadata,
        }


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class PatronTracker:
    """
    Tracker de patrones de trading.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # CONFIGURACIÓN
    # ============================================================
    
    MAX_PATRONES_ACTIVOS_POR_SIMBOLO = 5
    MAX_EJECUCIONES_POR_SIMBOLO = 100
    DIAS_MAX_ANTIGUEDAD = 7
    LIMITE_PERDIDAS_CONSECUTIVAS = 3
    
    # Pesos para calidad de patrón
    PESOS_CALIDAD = {
        'PIN_BAR': 1.2,
        'ENGULFING': 1.3,
        'DOJI': 0.8,
        'HAMMER': 1.1,
        'SHOOTING_STAR': 1.1,
        'MORNING_STAR': 1.4,
        'EVENING_STAR': 1.4,
        'BULLISH_FLAG': 1.2,
        'BEARISH_FLAG': 1.2,
    }
    
    def __init__(self,
                 almacen: Optional[Any] = None,
                 config: Optional[Any] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el tracker de patrones.
        
        Args:
            almacen: Almacenamiento SQLite
            config: Configuración
            modo_backtest: Modo backtest
            modo_depuracion: Modo depuración
        """
        self.almacen = almacen
        self.config = config
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.PatronTracker')
        
        # ============================================================
        # 1. ESTADO
        # ============================================================
        
        self._patrones_activos: Dict[str, List[PatronRegistro]] = {}
        self._ejecuciones: Dict[str, List[EjecucionRegistro]] = defaultdict(list)
        self._perdidas_consecutivas: Dict[str, int] = defaultdict(int)
        self._estadisticas_por_patron: Dict[str, Dict] = defaultdict(lambda: {
            'total': 0,
            'ganadoras': 0,
            'perdedoras': 0,
            'pnl_total': 0.0,
            'winrate': 0.0,
        })
        
        # ============================================================
        # 2. CARGAR DATOS
        # ============================================================
        
        self._cargar_desde_almacen()
        self._cargar_configuracion()
        
        self.logger.info(f"📊 PatronTracker V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Depuración: {modo_depuracion}")
        self.logger.info(f"   Patrones activos: {self._contar_patrones_activos()}")
    
    def _cargar_configuracion(self):
        """Carga configuración desde umbrales centralizados."""
        if Umbrales is not None:
            if hasattr(Umbrales, 'PATRONES'):
                patrones_config = Umbrales.PATRONES
                if 'max_patrones_activos' in patrones_config:
                    self.MAX_PATRONES_ACTIVOS_POR_SIMBOLO = patrones_config['max_patrones_activos']
                if 'limite_perdidas_consecutivas' in patrones_config:
                    self.LIMITE_PERDIDAS_CONSECUTIVAS = patrones_config['limite_perdidas_consecutivas']
    
    # ================================================================
    # CARGA Y PERSISTENCIA
    # ================================================================
    
    def _cargar_desde_almacen(self):
        """Carga datos desde almacenamiento."""
        if not self.almacen:
            return
        
        try:
            config = self.almacen.obtener_configuracion()
            
            # Cargar pérdidas consecutivas
            perdidas = config.get('perdidas_consecutivas_patrones', {})
            if perdidas:
                self._perdidas_consecutivas = defaultdict(int, perdidas)
                if self.modo_depuracion:
                    self.logger.debug(f"📊 Pérdidas consecutivas cargadas: {dict(self._perdidas_consecutivas)}")
            
            # Cargar patrones activos
            patrones_data = config.get('patrones_activos', {})
            if patrones_data:
                for simbolo, lista in patrones_data.items():
                    if simbolo not in self._patrones_activos:
                        self._patrones_activos[simbolo] = []
                    for p in lista:
                        try:
                            registro = PatronRegistro.from_dict(p)
                            self._patrones_activos[simbolo].append(registro)
                        except Exception as e:
                            self.logger.debug(f"Error cargando patrón: {e}")
                
                if self.modo_depuracion:
                    self.logger.debug(f"📊 {len(patrones_data)} patrones activos cargados")
            
            # Cargar ejecuciones
            ejecuciones_data = config.get('ejecuciones_patrones', {})
            if ejecuciones_data:
                for simbolo, lista in ejecuciones_data.items():
                    if simbolo not in self._ejecuciones:
                        self._ejecuciones[simbolo] = []
                    for e in lista:
                        try:
                            registro = EjecucionRegistro(
                                simbolo=e['simbolo'],
                                patron=e['patron'],
                                timestamp=datetime.fromisoformat(e['timestamp']),
                                resultado=e.get('resultado', 0.0),
                                score_entrada=e.get('score_entrada', 0.0),
                                duracion_minutos=e.get('duracion_minutos', 0.0),
                            )
                            self._ejecuciones[simbolo].append(registro)
                        except Exception:
                            continue
                
                if self.modo_depuracion:
                    self.logger.debug(f"📊 {len(ejecuciones_data)} ejecuciones cargadas")
                    
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando datos: {e}")
    
    def _guardar_en_almacen(self):
        """Guarda datos en almacenamiento."""
        if not self.almacen:
            return
        
        try:
            config = self.almacen.obtener_configuracion()
            
            # Guardar pérdidas consecutivas
            config['perdidas_consecutivas_patrones'] = dict(self._perdidas_consecutivas)
            
            # Guardar patrones activos (solo los recientes)
            patrones_para_guardar = {}
            for simbolo, lista in self._patrones_activos.items():
                if lista:
                    # Limitar a los más recientes
                    lista_ordenada = sorted(lista, key=lambda x: x.timestamp, reverse=True)
                    patrones_para_guardar[simbolo] = [
                        p.to_dict() for p in lista_ordenada[:self.MAX_PATRONES_ACTIVOS_POR_SIMBOLO]
                    ]
            config['patrones_activos'] = patrones_para_guardar
            
            # Guardar ejecuciones (últimas 100 por símbolo)
            ejecuciones_para_guardar = {}
            for simbolo, lista in self._ejecuciones.items():
                if lista:
                    lista_ordenada = sorted(lista, key=lambda x: x.timestamp, reverse=True)
                    ejecuciones_para_guardar[simbolo] = [
                        e.to_dict() for e in lista_ordenada[:self.MAX_EJECUCIONES_POR_SIMBOLO]
                    ]
            config['ejecuciones_patrones'] = ejecuciones_para_guardar
            
            self.almacen.guardar_configuracion(config)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando datos: {e}")
    
    # ================================================================
    # DETECCIÓN DE PATRONES
    # ================================================================
    
    def detectar_y_actualizar(self,
                              simbolo: str,
                              df: pd.DataFrame,
                              fecha_referencia: Optional[datetime] = None) -> List[Dict]:
        """
        Detecta patrones en el DataFrame y actualiza el tracker.
        
        Args:
            simbolo: Símbolo
            df: DataFrame con datos
            fecha_referencia: Fecha de referencia (opcional)
        
        Returns:
            Lista de patrones detectados
        """
        if df is None or len(df) < 30:
            return []
        
        try:
            fecha = fecha_referencia or datetime.now(timezone.utc)
            patrones_detectados = []
            
            # ============================================================
            # 1. DETECTAR PATRONES
            # ============================================================
            
            # Limpiar patrones antiguos
            self._limpiar_patrones_antiguos(simbolo, fecha)
            
            # Detectar patrones
            patrones = self._detectar_patrones(df)
            
            if not patrones:
                return []
            
            # Registrar cada patrón
            for patron in patrones:
                registro = PatronRegistro(
                    simbolo=simbolo,
                    patron=patron['nombre'],
                    direccion=patron['direccion'],
                    score=patron.get('calidad', 60),
                    timestamp=fecha,
                    activo=True,
                    precio=df['Close'].iloc[-1],
                    calidad=patron.get('calidad', 0),
                    metadata=patron
                )
                
                self._agregar_patron(simbolo, registro)
                patrones_detectados.append(patron)
            
            if patrones_detectados and self.modo_depuracion:
                self.logger.debug(f"📊 {simbolo}: {len(patrones_detectados)} patrones detectados")
            
            # Guardar cambios
            self._guardar_en_almacen()
            
            return patrones_detectados
            
        except Exception as e:
            self.logger.error(f"❌ Error detectando patrones para {simbolo}: {e}")
            return []
    
    def _detectar_patrones(self, df: pd.DataFrame) -> List[Dict]:
        """
        Detecta patrones chartistas básicos.
        
        Args:
            df: DataFrame con columnas Open, High, Low, Close
        
        Returns:
            Lista de patrones detectados
        """
        patrones = []
        
        if df is None or len(df) < 5:
            return patrones
        
        try:
            # Obtener últimas velas
            vela_actual = df.iloc[-1]
            vela_anterior = df.iloc[-2] if len(df) > 1 else vela_actual
            vela_anterior2 = df.iloc[-3] if len(df) > 2 else vela_actual
            
            # Calcular métricas de la vela
            rango = vela_actual['High'] - vela_actual['Low']
            cuerpo = abs(vela_actual['Close'] - vela_actual['Open'])
            
            if rango <= 0:
                return patrones
            
            sombra_sup = vela_actual['High'] - max(vela_actual['Open'], vela_actual['Close'])
            sombra_inf = min(vela_actual['Open'], vela_actual['Close']) - vela_actual['Low']
            
            # ============================================================
            # PIN BAR
            # ============================================================
            
            # Pin Bar Alcista (sombra inferior larga)
            if sombra_inf / rango > 0.6 and cuerpo / rango < 0.3:
                calidad = 70 + min(30, (sombra_inf / rango) * 100)
                patrones.append({
                    'nombre': 'PIN_BAR_ALCISTA',
                    'calidad': min(100, calidad),
                    'direccion': 'COMPRA',
                    'precio': vela_actual['Close'],
                })
            
            # Pin Bar Bajista (sombra superior larga)
            if sombra_sup / rango > 0.6 and cuerpo / rango < 0.3:
                calidad = 70 + min(30, (sombra_sup / rango) * 100)
                patrones.append({
                    'nombre': 'PIN_BAR_BAJISTA',
                    'calidad': min(100, calidad),
                    'direccion': 'VENTA',
                    'precio': vela_actual['Close'],
                })
            
            # ============================================================
            # ENGULFING
            # ============================================================
            
            if len(df) > 1:
                # Engulfing Alcista
                if (vela_actual['Close'] > vela_anterior['Open'] and 
                    vela_actual['Open'] < vela_anterior['Close'] and
                    vela_anterior['Close'] < vela_anterior['Open']):
                    patrones.append({
                        'nombre': 'ENGULFING_ALCISTA',
                        'calidad': 75,
                        'direccion': 'COMPRA',
                        'precio': vela_actual['Close'],
                    })
                
                # Engulfing Bajista
                if (vela_actual['Close'] < vela_anterior['Open'] and 
                    vela_actual['Open'] > vela_anterior['Close'] and
                    vela_anterior['Close'] > vela_anterior['Open']):
                    patrones.append({
                        'nombre': 'ENGULFING_BAJISTA',
                        'calidad': 75,
                        'direccion': 'VENTA',
                        'precio': vela_actual['Close'],
                    })
            
            # ============================================================
            # DOJI
            # ============================================================
            
            if cuerpo / rango < 0.1 and rango > 0:
                patrones.append({
                    'nombre': 'DOJI',
                    'calidad': 60,
                    'direccion': 'NEUTRAL',
                    'precio': vela_actual['Close'],
                })
            
            # ============================================================
            # HAMMER / SHOOTING STAR
            # ============================================================
            
            # Martillo (alcista)
            if sombra_inf / rango > 0.6 and cuerpo / rango < 0.3 and cuerpo > 0:
                patrones.append({
                    'nombre': 'HAMMER',
                    'calidad': 65,
                    'direccion': 'COMPRA',
                    'precio': vela_actual['Close'],
                })
            
            # Estrella fugaz (bajista)
            if sombra_sup / rango > 0.6 and cuerpo / rango < 0.3 and cuerpo > 0:
                patrones.append({
                    'nombre': 'SHOOTING_STAR',
                    'calidad': 65,
                    'direccion': 'VENTA',
                    'precio': vela_actual['Close'],
                })
            
        except Exception as e:
            self.logger.debug(f"Error detectando patrones: {e}")
        
        return patrones
    
    # ================================================================
    # GESTIÓN DE PATRONES
    # ================================================================
    
    def _agregar_patron(self, simbolo: str, registro: PatronRegistro):
        """
        Agrega un patrón al tracker.
        
        Args:
            simbolo: Símbolo
            registro: Registro del patrón
        """
        if simbolo not in self._patrones_activos:
            self._patrones_activos[simbolo] = []
        
        # Limitar número de patrones activos
        if len(self._patrones_activos[simbolo]) >= self.MAX_PATRONES_ACTIVOS_POR_SIMBOLO:
            # Eliminar el más antiguo
            self._patrones_activos[simbolo].sort(key=lambda x: x.timestamp)
            self._patrones_activos[simbolo].pop(0)
        
        self._patrones_activos[simbolo].append(registro)
    
    def obtener_patron_activo(self, simbolo: str) -> Optional[Dict]:
        """
        Obtiene el patrón activo más reciente.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Patrón activo o None
        """
        if simbolo not in self._patrones_activos:
            return None
        
        activos = [p for p in self._patrones_activos[simbolo] if p.activo]
        if not activos:
            return None
        
        # Ordenar por timestamp (más reciente primero)
        activos.sort(key=lambda x: x.timestamp, reverse=True)
        return activos[0].to_dict()
    
    def _limpiar_patrones_antiguos(self, simbolo: str, fecha: datetime):
        """
        Limpia patrones antiguos.
        
        Args:
            simbolo: Símbolo
            fecha: Fecha de referencia
        """
        if simbolo not in self._patrones_activos:
            return
        
        limite = fecha - timedelta(days=self.DIAS_MAX_ANTIGUEDAD)
        self._patrones_activos[simbolo] = [
            p for p in self._patrones_activos[simbolo]
            if p.timestamp > limite
        ]
    
    def marcar_ejecutado(self, simbolo: str, resultado: float = 0.0) -> bool:
        """
        Marca un patrón como ejecutado.
        
        Args:
            simbolo: Símbolo
            resultado: Resultado de la ejecución (PnL)
        
        Returns:
            True si se marcó correctamente
        """
        if simbolo not in self._patrones_activos:
            return False
        
        # Buscar patrón activo más reciente
        for i, patron in enumerate(self._patrones_activos[simbolo]):
            if patron.activo:
                patron.activo = False
                
                # Registrar ejecución
                ejecucion = EjecucionRegistro(
                    simbolo=simbolo,
                    patron=patron.patron,
                    timestamp=datetime.now(timezone.utc),
                    resultado=resultado,
                    score_entrada=patron.score,
                )
                self._ejecuciones[simbolo].append(ejecucion)
                
                # Actualizar estadísticas
                self._actualizar_estadisticas(patron.patron, resultado)
                
                self.logger.info(f"✅ Patrón ejecutado: {simbolo} - {patron.patron} (PnL: ${resultado:.2f})")
                self._guardar_en_almacen()
                return True
        
        return False
    
    def registrar_resultado(self, simbolo: str, ganancia: float):
        """
        Registra el resultado de una ejecución y actualiza pérdidas consecutivas.
        
        Args:
            simbolo: Símbolo
            ganancia: Ganancia/Pérdida
        """
        if ganancia < 0:
            self._perdidas_consecutivas[simbolo] += 1
        else:
            self._perdidas_consecutivas[simbolo] = 0
        
        self._guardar_en_almacen()
        
        if self.modo_depuracion:
            perdidas = self._perdidas_consecutivas[simbolo]
            self.logger.debug(f"📊 {simbolo}: pérdidas consecutivas = {perdidas}")
        
        # Verificar límite de pérdidas consecutivas
        if self._perdidas_consecutivas[simbolo] >= self.LIMITE_PERDIDAS_CONSECUTIVAS:
            self.logger.warning(f"⚠️ {simbolo}: {self._perdidas_consecutivas[simbolo]} pérdidas consecutivas")
    
    def _actualizar_estadisticas(self, patron: str, resultado: float):
        """
        Actualiza estadísticas por patrón.
        
        Args:
            patron: Nombre del patrón
            resultado: Resultado de la ejecución
        """
        stats = self._estadisticas_por_patron[patron]
        stats['total'] += 1
        stats['pnl_total'] += resultado
        
        if resultado > 0:
            stats['ganadoras'] += 1
        else:
            stats['perdedoras'] += 1
        
        if stats['total'] > 0:
            stats['winrate'] = (stats['ganadoras'] / stats['total']) * 100
    
    # ================================================================
    # CONSULTAS
    # ================================================================
    
    def obtener_perdidas_consecutivas(self, simbolo: str) -> int:
        """
        Obtiene el número de pérdidas consecutivas.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Número de pérdidas consecutivas
        """
        return self._perdidas_consecutivas.get(simbolo, 0)
    
    def obtener_ejecuciones(self, simbolo: str, limite: int = 20) -> List[Dict]:
        """
        Obtiene ejecuciones de un símbolo.
        
        Args:
            simbolo: Símbolo
            limite: Número máximo de ejecuciones
        
        Returns:
            Lista de ejecuciones
        """
        if simbolo not in self._ejecuciones:
            return []
        
        ejecuciones = sorted(self._ejecuciones[simbolo], key=lambda x: x.timestamp, reverse=True)
        return [e.to_dict() for e in ejecuciones[:limite]]
    
    def obtener_estadisticas_patron(self, patron: Optional[str] = None) -> Dict:
        """
        Obtiene estadísticas de patrones.
        
        Args:
            patron: Nombre del patrón (None = todos)
        
        Returns:
            Estadísticas
        """
        if patron:
            return dict(self._estadisticas_por_patron.get(patron, {}))
        
        return dict(self._estadisticas_por_patron)
    
    def obtener_mejores_patrones(self, limite: int = 5) -> List[Dict]:
        """
        Obtiene los mejores patrones por winrate.
        
        Args:
            limite: Número máximo de patrones
        
        Returns:
            Lista de patrones con estadísticas
        """
        resultados = []
        for patron, stats in self._estadisticas_por_patron.items():
            if stats['total'] >= 3:  # Mínimo 3 ejecuciones para ser válido
                resultados.append({
                    'patron': patron,
                    'total': stats['total'],
                    'winrate': stats['winrate'],
                    'pnl_total': stats['pnl_total'],
                    'pnl_promedio': stats['pnl_total'] / stats['total'] if stats['total'] > 0 else 0,
                })
        
        resultados.sort(key=lambda x: x['winrate'], reverse=True)
        return resultados[:limite]
    
    def _contar_patrones_activos(self) -> int:
        """Cuenta patrones activos en total."""
        total = 0
        for lista in self._patrones_activos.values():
            total += len([p for p in lista if p.activo])
        return total
    
    # ================================================================
    # LIMPIEZA
    # ================================================================
    
    def limpiar_antiguos(self, horas: int = 48) -> int:
        """
        Limpia patrones antiguos.
        
        Args:
            horas: Edad máxima en horas
        
        Returns:
            Número de patrones eliminados
        """
        ahora = datetime.now(timezone.utc)
        limite = ahora - timedelta(hours=horas)
        eliminados = 0
        
        for simbolo in list(self._patrones_activos.keys()):
            original_len = len(self._patrones_activos[simbolo])
            self._patrones_activos[simbolo] = [
                p for p in self._patrones_activos[simbolo]
                if p.timestamp > limite
            ]
            eliminados += original_len - len(self._patrones_activos[simbolo])
            
            # Si no hay patrones, eliminar la entrada
            if not self._patrones_activos[simbolo]:
                del self._patrones_activos[simbolo]
        
        if eliminados > 0:
            self.logger.info(f"🧹 {eliminados} patrones antiguos limpiados")
            self._guardar_en_almacen()
        
        return eliminados
    
    # ================================================================
    # ESTADÍSTICAS
    # ================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas del tracker.
        
        Returns:
            Diccionario con estadísticas
        """
        total_activos = self._contar_patrones_activos()
        total_ejecuciones = sum(len(e) for e in self._ejecuciones.values())
        total_perdidas = sum(self._perdidas_consecutivas.values())
        simbolos_con_perdidas = len([s for s, p in self._perdidas_consecutivas.items() if p > 0])
        
        return {
            'patrones_activos': total_activos,
            'patrones_por_simbolo': {s: len([p for p in l if p.activo]) 
                                    for s, l in self._patrones_activos.items()},
            'ejecuciones_totales': total_ejecuciones,
            'ejecuciones_por_simbolo': {s: len(l) for s, l in self._ejecuciones.items()},
            'simbolos_con_perdidas': simbolos_con_perdidas,
            'perdidas_totales': total_perdidas,
            'estadisticas_por_patron': dict(self._estadisticas_por_patron),
            'mejores_patrones': self.obtener_mejores_patrones(5),
        }
    
    def print_stats(self):
        """Imprime estadísticas en formato legible."""
        stats = self.get_stats()
        
        print("\n" + "=" * 50)
        print("📊 ESTADÍSTICAS DE PATRONES")
        print("=" * 50)
        print(f"Patrones activos: {stats['patrones_activos']}")
        print(f"Ejecuciones totales: {stats['ejecuciones_totales']}")
        print(f"Símbolos con pérdidas: {stats['simbolos_con_perdidas']}")
        print(f"Pérdidas totales: {stats['perdidas_totales']}")
        
        if stats['mejores_patrones']:
            print("\n🏆 Mejores patrones:")
            for p in stats['mejores_patrones']:
                print(f"  {p['patron']}: {p['winrate']:.1f}% ({p['total']} ops, PnL: ${p['pnl_total']:.2f})")
        
        print("=" * 50)
    
    # ================================================================
    # MÉTODOS DE COMPATIBILIDAD (LEGACY)
    # ================================================================
    
    def registrar_patron_legacy(self, simbolo: str, patron: str, 
                                direccion: str, score: float) -> Dict:
        """
        Versión legacy de registro de patrón.
        DEPRECADO - Usar detectar_y_actualizar() en su lugar.
        """
        registro = PatronRegistro(
            simbolo=simbolo,
            patron=patron,
            direccion=direccion,
            score=score,
            timestamp=datetime.now(timezone.utc)
        )
        self._agregar_patron(simbolo, registro)
        self._guardar_en_almacen()
        return registro.to_dict()


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_patron_tracker(almacen: Optional[Any] = None,
                          config: Optional[Any] = None,
                          modo_backtest: bool = False,
                          modo_depuracion: bool = False) -> PatronTracker:
    """
    Crea una instancia de PatronTracker.
    
    Args:
        almacen: Almacenamiento SQLite
        config: Configuración
        modo_backtest: Modo backtest
        modo_depuracion: Modo depuración
    
    Returns:
        PatronTracker
    """
    return PatronTracker(
        almacen=almacen,
        config=config,
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import numpy as np
    
    print("🧪 Probando PatronTracker...")
    
    # Crear tracker
    tracker = PatronTracker(modo_backtest=True, modo_depuracion=True)
    
    # Crear datos de prueba
    np.random.seed(42)
    n = 30
    dates = pd.date_range('2024-01-01', periods=n, freq='H')
    df = pd.DataFrame({
        'Open': np.random.randn(n) * 10 + 100,
        'High': np.random.randn(n) * 10 + 102,
        'Low': np.random.randn(n) * 10 + 98,
        'Close': np.random.randn(n) * 10 + 100,
        'Volume': np.random.randint(100, 1000, n)
    }, index=dates)
    df['Close'] = df['Close'].cumsum() / 10 + 100
    
    # Detectar patrones
    patrones = tracker.detectar_y_actualizar('EURUSD', df)
    print(f"Patrones detectados: {len(patrones)}")
    for p in patrones:
        print(f"  {p['nombre']} - {p['direccion']} (calidad: {p['calidad']:.0f})")
    
    # Marcar ejecutado
    tracker.marcar_ejecutado('EURUSD', 10.5)
    tracker.registrar_resultado('EURUSD', 10.5)
    
    # Estadísticas
    tracker.print_stats()
    
    print("\n✅ Prueba completada")