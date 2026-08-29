#!/usr/bin/env python3
"""
analysis/pipeline.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Pipeline de 3 fases para oportunidades de trading.

RESPONSABILIDADES:
- Gestionar el ciclo de vida de oportunidades
- Controlar transiciones entre fases
- Almacenar contexto de cada fase
- Validar condiciones de promoción
- Limpiar oportunidades antiguas

ESTRUCTURA:
- FASE_1: H1_ESCANEO - Análisis inicial
- FASE_2: M15_CONFIRMACION - Validación en M15
- FASE_3: M5_SNIPER - Disparo en M5
- EJECUTADA: Oportunidad ejecutada
- CANCELADA: Oportunidad cancelada

MEJORAS V9.0:
- Transiciones validadas (no saltos de fase)
- Integración con umbrales centralizados
- Logs detallados de transiciones
- Métodos de consulta mejorados
- Limpieza automática
- Soporte para persistencia (opcional)
"""

import time
import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

# ============================================================
# IMPORTS REFACTORIZADOS
# ============================================================

from config.umbrales import Umbrales
from utils.helpers import safe_float

logger = logging.getLogger('BotTrading.Pipeline')


# ============================================================
# ENUMS
# ============================================================

class FaseOportunidad(Enum):
    """Fases del pipeline."""
    FASE_1 = "H1_ESCANEO"
    FASE_2 = "M15_CONFIRMACION"
    FASE_3 = "M5_SNIPER"
    EJECUTADA = "EJECUTADA"
    CANCELADA = "CANCELADA"
    
    def es_activa(self) -> bool:
        """Verifica si la fase es activa (no terminal)."""
        return self not in [FaseOportunidad.EJECUTADA, FaseOportunidad.CANCELADA]
    
    def es_terminal(self) -> bool:
        """Verifica si la fase es terminal."""
        return self in [FaseOportunidad.EJECUTADA, FaseOportunidad.CANCELADA]


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class EstadoOportunidad:
    """Estado de una oportunidad en el pipeline."""
    simbolo: str
    fase_actual: FaseOportunidad
    direccion: str
    score_acumulado: float
    timestamp_creacion: datetime
    timestamp_ultima_actualizacion: datetime
    
    # Condiciones
    condiciones_pendientes: List[str] = field(default_factory=list)
    condiciones_cumplidas: List[str] = field(default_factory=list)
    
    # Análisis por fase
    analisis_h1: Optional[Dict] = None
    analisis_m15: Optional[Dict] = None
    analisis_m5: Optional[Dict] = None
    analisis_pesado: Optional[Dict] = None  # ✅ Campo explícito
    
    # Contexto
    regimen: str = 'UNCERTAIN'
    direccion_regimen: str = 'NONE'
    confianza_regimen: float = 0
    tendencia_h4: str = 'LATERAL'
    calidad_horario: str = 'REGULAR'
    
    # Scores específicos
    score_m15: float = 0.0
    score_final: float = 0.0
    score_pesado: float = 0.0
    contexto_h1: Optional[Dict] = None  # ✅ Campo explícito
    contexto_m15: Optional[Dict] = None
    contexto_m5: Optional[Dict] = None
    
    # Metadata
    intentos_promocion: int = 0
    ultimo_error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validaciones post-inicialización."""
        if self.timestamp_creacion.tzinfo is None:
            self.timestamp_creacion = self.timestamp_creacion.replace(tzinfo=timezone.utc)
        if self.timestamp_ultima_actualizacion.tzinfo is None:
            self.timestamp_ultima_actualizacion = self.timestamp_ultima_actualizacion.replace(tzinfo=timezone.utc)
    
    def obtener_condiciones_pendientes(self) -> List[str]:
        """Obtiene condiciones pendientes."""
        return self.condiciones_pendientes.copy()
    
    def cumplir_condicion(self, condicion: str) -> bool:
        """Marca una condición como cumplida."""
        if condicion in self.condiciones_pendientes:
            self.condiciones_pendientes.remove(condicion)
            self.condiciones_cumplidas.append(condicion)
            self.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            return True
        return False
    
    def agregar_condicion(self, condicion: str) -> bool:
        """Agrega una condición pendiente."""
        if condicion not in self.condiciones_pendientes and \
           condicion not in self.condiciones_cumplidas:
            self.condiciones_pendientes.append(condicion)
            self.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            return True
        return False
    
    def tiene_condiciones_pendientes(self) -> bool:
        """Verifica si hay condiciones pendientes."""
        return len(self.condiciones_pendientes) > 0
    
    def porcentaje_completado(self) -> float:
        """Calcula el porcentaje de condiciones completadas."""
        total = len(self.condiciones_pendientes) + len(self.condiciones_cumplidas)
        if total == 0:
            return 0.0
        return (len(self.condiciones_cumplidas) / total) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para serialización."""
        return {
            'simbolo': self.simbolo,
            'fase': self.fase_actual.value,
            'direccion': self.direccion,
            'score_acumulado': self.score_acumulado,
            'timestamp_creacion': self.timestamp_creacion.isoformat(),
            'timestamp_actualizacion': self.timestamp_ultima_actualizacion.isoformat(),
            'condiciones_pendientes': self.condiciones_pendientes,
            'condiciones_cumplidas': self.condiciones_cumplidas,
            'regimen': self.regimen,
            'calidad_horario': self.calidad_horario,
            'score_m15': self.score_m15,
            'score_final': self.score_final,
            'porcentaje_completado': self.porcentaje_completado(),
            'analisis_pesado': self.analisis_pesado,
        }


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class PipelineOportunidades:
    """
    Pipeline de 3 fases para oportunidades de trading.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    
    USO:
        pipeline = PipelineOportunidades(config)
        
        # Actualizar Fase 1
        pipeline.actualizar_fase_1(simbolo, analisis, score, direccion)
        
        # Promover automáticamente
        pipeline.promover_automaticamente()
        
        # Obtener oportunidades activas
        activas = pipeline.obtener_activos()
    """
    
    def __init__(self,
                 config: Optional[Any] = None,
                 umbral_fase_1: Optional[float] = None,
                 umbral_fase_2: Optional[float] = None,
                 umbral_fase_3: Optional[float] = None,
                 max_edad_horas: int = 48,
                 modo_backtest: bool = False,
                 almacen: Optional[Any] = None):  # ✅ AÑADIR ESTE PARÁMETRO
        """
        Inicializa el pipeline.
        
        Args:
            config: Configuración
            umbral_fase_1: Score mínimo para Fase 1
            umbral_fase_2: Score mínimo para Fase 2
            umbral_fase_3: Score mínimo para Fase 3
            max_edad_horas: Edad máxima de una oportunidad
            modo_backtest: Modo backtest
        """
        self.config = config
        self.modo_backtest = modo_backtest
        self.almacen = almacen  # ✅ GUARDAR EL ALMACENAMIENTO
        self.logger = logging.getLogger('BotTrading.Pipeline')
        
        # Umbrales
        self.umbral_fase_1 = self._cargar_umbral('fase_1', umbral_fase_1, 30)
        self.umbral_fase_2 = self._cargar_umbral('fase_2', umbral_fase_2, 45)
        self.umbral_fase_3 = self._cargar_umbral('fase_3', umbral_fase_3, 55)
        self.max_edad_horas = max_edad_horas
        
        # Almacenamiento
        self.estados: Dict[str, EstadoOportunidad] = {}
        self.logger.info("✅ PipelineOportunidades inicializado con almacenamiento")
        if self.almacen:
            self._cargar_estados_desde_sqlite()
        # Estadísticas
        self._stats = {
            'creadas': 0,
            'promovidas_f1_f2': 0,
            'promovidas_f2_f3': 0,
            'ejecutadas': 0,
            'canceladas': 0,
            'expiradas': 0,
        }
        # ============================================================
        # ✅ CONFIGURACIÓN DE CALIDAD Y DEGRADACIÓN (AQUÍ)
        # ============================================================
        MAX_INTENTOS_SNIPER = 5
        MAX_INTENTOS_FASE2 = 3
        
        # Límites de intentos por calidad (0-4)
        LIMITES_INTENTOS_POR_CALIDAD = {
            4: 10,  # Élite: 10 intentos
            3: 7,   # Prometedora: 7 intentos
            2: 5,   # Media: 5 intentos
            1: 3,   # Débil: 3 intentos
            0: 2,   # Muy débil: 2 intentos
        }
        
        self.logger.info(f"🔀 PipelineOportunidades V9.0 inicializado")
        self.logger.info(f"   Umbrales: F1={self.umbral_fase_1}, F2={self.umbral_fase_2}, F3={self.umbral_fase_3}")
        self.logger.info(f"   Max edad: {max_edad_horas}h")
        self.logger.info(f"   Backtest: {modo_backtest}")
        if self.almacen:
            self.logger.info(f"   Almacenamiento SQLite: ✅")
        else:
            self.logger.info(f"   Almacenamiento SQLite: ❌")

    def _cargar_estados_desde_sqlite(self):
        """
        Carga los estados del pipeline desde SQLite.
        V9.1 - CORREGIDO: Recupera contexto_h1 con niveles correctamente.
        """
        if not self.almacen:
            return
        
        try:
            config = self.almacen.obtener_configuracion()
            pipeline_data = config.get('pipeline_estados', {})
            
            for simbolo, data in pipeline_data.items():
                try:
                    # ✅ Recuperar contexto_h1 con validación
                    contexto_h1 = data.get('contexto_h1')
                    if contexto_h1 is None or not isinstance(contexto_h1, dict):
                        contexto_h1 = {}
                    
                    # ✅ Si hay niveles, asegurar estructura
                    if 'niveles' not in contexto_h1:
                        contexto_h1['niveles'] = {'soportes': [], 'resistencias': []}
                    
                    # ✅ Recuperar otros contextos
                    contexto_m15 = data.get('contexto_m15')
                    if contexto_m15 is None or not isinstance(contexto_m15, dict):
                        contexto_m15 = {}
                    
                    contexto_m5 = data.get('contexto_m5')
                    if contexto_m5 is None or not isinstance(contexto_m5, dict):
                        contexto_m5 = {}
                    
                    # ✅ Crear estado con todos los datos
                    estado = EstadoOportunidad(
                        simbolo=data['simbolo'],
                        fase_actual=FaseOportunidad(data['fase']),
                        direccion=data['direccion'],
                        score_acumulado=data['score_acumulado'],
                        timestamp_creacion=datetime.fromisoformat(data['timestamp_creacion']),
                        timestamp_ultima_actualizacion=datetime.fromisoformat(data['timestamp_actualizacion']),
                        condiciones_pendientes=data.get('condiciones_pendientes', []),
                        condiciones_cumplidas=data.get('condiciones_cumplidas', []),
                        analisis_h1=data.get('analisis_h1'),
                        analisis_m15=data.get('analisis_m15'),
                        analisis_m5=data.get('analisis_m5'),
                        analisis_pesado=data.get('analisis_pesado'),
                        regimen=data.get('regimen', 'UNCERTAIN'),
                        direccion_regimen=data.get('direccion_regimen', 'NONE'),
                        confianza_regimen=data.get('confianza_regimen', 0),
                        tendencia_h4=data.get('tendencia_h4', 'LATERAL'),
                        calidad_horario=data.get('calidad_horario', 'REGULAR'),
                        score_m15=data.get('score_m15', 0),
                        score_final=data.get('score_final', 0),
                        contexto_h1=contexto_h1,  # ✅ CONTEXTO CON NIVELES
                        contexto_m15=contexto_m15,
                        contexto_m5=contexto_m5,
                        intentos_promocion=data.get('intentos_promocion', 0),
                        ultimo_error=data.get('ultimo_error'),
                        metadata=data.get('metadata', {})
                    )
                    
                    self.estados[simbolo] = estado
                    self.logger.debug(f"📂 Pipeline: Estado de {simbolo} cargado desde SQLite")
                    
                except Exception as e:
                    self.logger.warning(f"⚠️ Error cargando estado de {simbolo}: {e}")
            
            self.logger.info(f"📂 Pipeline: {len(self.estados)} estados cargados desde SQLite")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando pipeline desde SQLite: {e}")

    def _calcular_calidad_oportunidad(self, estado: EstadoOportunidad) -> int:
        """
        Calcula la calidad de una oportunidad.
        0 = Muy débil, 4 = Élite.
        
        V9.10 - NUEVO: Prioriza oportunidades por condiciones cumplidas.
        """
        calidad = 0
        
        # Puntuar por condiciones cumplidas
        if 'Score_Fase1' in estado.condiciones_cumplidas:
            calidad += 1
        if 'Direccion_Definida' in estado.condiciones_cumplidas:
            calidad += 1
        if 'Score_Fase2' in estado.condiciones_cumplidas:
            calidad += 1
        if 'M15_Confirmacion' in estado.condiciones_cumplidas:
            calidad += 1
        
        # Bono por régimen favorable
        if estado.regimen in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
            calidad += 1  # Bono por tendencia fuerte (máx 4)
        
        # Bono por score alto
        if estado.score_acumulado >= 80:
            calidad += 1  # Bono por score alto (máx 4)
        
        # Limitar a 4
        return min(4, max(0, calidad))

    def _calcular_limite_intentos(self, calidad: int) -> int:
        """
        Calcula el límite de intentos según calidad.
        Calidad alta = más intentos permitidos.
        
        V9.10 - NUEVO: Permite más intentos a oportunidades prometedoras.
        """
        return self.LIMITES_INTENTOS_POR_CALIDAD.get(calidad, 5)

    def _degradar_oportunidad(self, simbolo: str, razon: str = ""):
        """
        Degrada una oportunidad a FASE_1 para re-análisis.
        V9.2 - CORREGIDO: No intenta re-analizar (solo degradar).
        """
        estado = self.estados.get(simbolo)
        if not estado:
            return
        
        # ✅ SIEMPRE DEGRADAR A FASE_1 (NUNCA A FASE_2)
        if estado.fase_actual == FaseOportunidad.FASE_3:
            estado.fase_actual = FaseOportunidad.FASE_1  # ← CAMBIADO DE FASE_2 a FASE_1
            estado.ultimo_error = razon
            estado.metadata['sniper_fallos'] = 0
            estado.metadata['intentos_sniper'] = 0
            estado.condiciones_pendientes = []
            estado.condiciones_cumplidas = []
            estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            self.logger.info(f"⬇️ {simbolo}: Degradado de FASE_3 a FASE_1 ({razon})")
            self.logger.info(f"🔄 {simbolo}: Se re-analizará en el próximo ciclo de precarga (5 min)")
        
        elif estado.fase_actual == FaseOportunidad.FASE_2:
            estado.fase_actual = FaseOportunidad.FASE_1
            estado.ultimo_error = razon
            estado.metadata['intentos_fase2'] = 0
            estado.condiciones_pendientes = []
            estado.condiciones_cumplidas = []
            estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            self.logger.info(f"⬇️ {simbolo}: Degradado de FASE_2 a FASE_1 ({razon})")
            self.logger.info(f"🔄 {simbolo}: Se re-analizará en el próximo ciclo de precarga (5 min)")
        
        # Guardar cambios
        self._guardar_estados_en_sqlite()
        
        # ✅ CORREGIDO: NO intentar re-analizar (depende del orquestador)
        # Solo degradar, el orquestador se encargará de re-analizar

    def _degradar_oportunidad_por_tiempo(self, simbolo: str, max_horas: float = 4.0):
        """
        Degrada una oportunidad si ha estado demasiado tiempo en una fase.
        
        Args:
            simbolo: Símbolo a degradar
            max_horas: Máximo de horas permitidas en la fase actual
        """
        estado = self.estados.get(simbolo)
        if not estado:
            return
        
        ahora = datetime.now(timezone.utc)
        tiempo_en_fase = (ahora - estado.timestamp_ultima_actualizacion).total_seconds() / 3600
        
        if tiempo_en_fase > max_horas:
            self.logger.info(f"⬇️ {simbolo}: Degradando por tiempo ({tiempo_en_fase:.1f}h > {max_horas}h)")
            self._degradar_oportunidad(
                simbolo,
                razon=f"Tiempo excedido en {estado.fase_actual.value} ({tiempo_en_fase:.1f}h)"
            )

    def _degradar_oportunidad_por_intentos(self, simbolo: str, fase: str, max_intentos: int):
        """
        Degrada una oportunidad después de varios intentos fallidos.
        
        Args:
            simbolo: Símbolo
            fase: Fase actual
            max_intentos: Máximo de intentos permitidos
        """
        estado = self.estados.get(simbolo)
        if not estado:
            return
        
        if fase == 'FASE_2':
            intentos = estado.metadata.get('intentos_fase2', 0)
        elif fase == 'FASE_3':
            intentos = estado.metadata.get('intentos_sniper', 0)
        else:
            intentos = 0
        
        if intentos > max_intentos:
            self.logger.info(f"⬇️ {simbolo}: Degradando por intentos ({intentos} > {max_intentos})")
            self._degradar_oportunidad(
                simbolo,
                razon=f"Demasiados intentos en {fase} ({intentos})"
            )

        def _reanalizar_simbolo(self, simbolo: str):
            """
            Re-analiza un símbolo después de degradación.
            V9.2 - CORREGIDO: Solo degrada, no intenta re-analizar.
            
            NOTA: Esta función se mantiene por compatibilidad, pero NO debe usarse.
            El orquestador se encarga de re-analizar los símbolos degradados.
            """
            self.logger.info(f"⏭️ {simbolo}: Degradado, será re-analizado por el orquestador")
            # No intentar acceder a self.cache o self.mt5
            # Solo loggear, el orquestador se encargará de re-analizar
        
    def _guardar_estados_en_sqlite(self):
        """
        Guarda los estados del pipeline en SQLite.
        V9.1 - CORREGIDO: Asegura que contexto_h1 se guarde correctamente.
        """
        if not self.almacen:
            return
        
        try:
            config = self.almacen.obtener_configuracion()
            pipeline_data = {}
            
            for simbolo, estado in self.estados.items():
                # ✅ Serializar contexto_h1 correctamente
                contexto_h1_serializado = None
                if estado.contexto_h1 is not None:
                    contexto_h1_serializado = estado.contexto_h1.copy()
                    # Asegurar que los niveles estén en formato serializable
                    if 'niveles' in contexto_h1_serializado:
                        # Ya son diccionarios, no necesitan conversión adicional
                        pass
                
                # ✅ Serializar otros contextos
                contexto_m15_serializado = estado.contexto_m15.copy() if estado.contexto_m15 else None
                contexto_m5_serializado = estado.contexto_m5.copy() if estado.contexto_m5 else None
                
                pipeline_data[simbolo] = {
                    'simbolo': estado.simbolo,
                    'fase': estado.fase_actual.value,
                    'direccion': estado.direccion,
                    'score_acumulado': estado.score_acumulado,
                    'timestamp_creacion': estado.timestamp_creacion.isoformat(),
                    'timestamp_actualizacion': estado.timestamp_ultima_actualizacion.isoformat(),
                    'condiciones_pendientes': estado.condiciones_pendientes,
                    'condiciones_cumplidas': estado.condiciones_cumplidas,
                    'analisis_h1': estado.analisis_h1,
                    'analisis_m15': estado.analisis_m15,
                    'analisis_m5': estado.analisis_m5,
                    'analisis_pesado': estado.analisis_pesado,
                    'regimen': estado.regimen,
                    'direccion_regimen': estado.direccion_regimen,
                    'confianza_regimen': estado.confianza_regimen,
                    'tendencia_h4': estado.tendencia_h4,
                    'calidad_horario': estado.calidad_horario,
                    'score_m15': estado.score_m15,
                    'score_final': estado.score_final,
                    'contexto_h1': contexto_h1_serializado,  # ✅ AHORA SE GUARDA
                    'contexto_m15': contexto_m15_serializado,
                    'contexto_m5': contexto_m5_serializado,
                    'intentos_promocion': estado.intentos_promocion,
                    'ultimo_error': estado.ultimo_error,
                    'metadata': estado.metadata,
                }
            
            config['pipeline_estados'] = pipeline_data
            self.almacen.guardar_configuracion(config)
            self.logger.debug(f"💾 Pipeline: {len(self.estados)} estados guardados en SQLite")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando pipeline en SQLite: {e}")
    
    def _cargar_umbral(self, fase: str, personalizado: Optional[float], default: float) -> float:
        """
        Carga umbral desde configuración o usa el valor personalizado.
        CORREGIDO: Ahora el valor personalizado tiene prioridad absoluta.
        """
        # ✅ PRIORIDAD 1: Valor personalizado (pasado en el __init__)
        if personalizado is not None:
            return float(personalizado)
        
        # ✅ PRIORIDAD 2: Configuración
        if self.config:
            if hasattr(self.config, f'PIPELINE_UMBRAL_{fase.upper()}'):
                return float(getattr(self.config, f'PIPELINE_UMBRAL_{fase.upper()}', default))
        
        # ✅ PRIORIDAD 3: Umbrales centralizados
        if Umbrales is not None:
            if hasattr(Umbrales, 'SCORES'):
                key = f'score_minimo_{fase}'
                if key in Umbrales.SCORES:
                    return float(Umbrales.SCORES[key])
        
        # ✅ PRIORIDAD 4: Backtest
        if self.modo_backtest:
            return max(5, default * 0.3)
        
        # ✅ PRIORIDAD 5: Default
        return default
    # ============================================================
    # MÉTODOS PRINCIPALES
    # ============================================================
    
    def actualizar_fase_1(self,
                      simbolo: str,
                      analisis: Dict,
                      score: float,
                      direccion: str,
                      regimen: str = 'UNCERTAIN',
                      direccion_regimen: str = 'NONE',
                      confianza_regimen: float = 0,
                      tendencia_h4: str = 'LATERAL',
                      contexto_h1: Optional[Dict] = None,
                      analisis_pesado: Optional[Dict] = None) -> Optional[EstadoOportunidad]:
        """
        Actualiza la oportunidad en Fase 1 (H1) - V9.30 REFACTORIZADO.
        PROMOCIÓN INMEDIATA a FASE_2 y FASE_3 según score.
        
        V9.2 - CORREGIDO: try/except para evitar que el pipeline falle.
        """
        try:
            # ============================================================
            # 1. VALIDAR SCORE MÍNIMO
            # ============================================================
            if score < self.umbral_fase_1 * 0.5:
                self.logger.info(f"⏭️ {simbolo}: Score insuficiente ({score:.1f} < {self.umbral_fase_1 * 0.5:.1f})")
                return None
            
            # ============================================================
            # 2. BUSCAR O CREAR ESTADO
            # ============================================================
            estado = self.estados.get(simbolo)
            
            if estado is None:
                # Crear nuevo estado - SIN condiciones pendientes
                estado = EstadoOportunidad(
                    simbolo=simbolo,
                    fase_actual=FaseOportunidad.FASE_1,
                    direccion=direccion,
                    score_acumulado=score,
                    timestamp_creacion=datetime.now(timezone.utc),
                    timestamp_ultima_actualizacion=datetime.now(timezone.utc),
                    condiciones_pendientes=[],  # ✅ VACÍO
                    condiciones_cumplidas=[],   # ✅ VACÍO
                    analisis_h1=analisis,
                    analisis_pesado=analisis_pesado,
                    regimen=regimen,
                    direccion_regimen=direccion_regimen,
                    confianza_regimen=confianza_regimen,
                    tendencia_h4=tendencia_h4,
                    contexto_h1=contexto_h1 if contexto_h1 is not None else {},
                )
                self.estados[simbolo] = estado
                self._stats['creadas'] += 1
                self.logger.info(f"📝 {simbolo}: Nueva oportunidad creada en FASE_1 (score: {score:.1f})")
            
            else:
                # Estado existente - actualizar
                if estado.fase_actual.es_terminal():
                    return estado
                
                # Actualizar datos
                if contexto_h1 is not None and len(contexto_h1) > 0:
                    if estado.contexto_h1 is None:
                        estado.contexto_h1 = {}
                    if 'niveles' not in contexto_h1 and 'niveles' in estado.contexto_h1:
                        contexto_h1['niveles'] = estado.contexto_h1['niveles']
                    estado.contexto_h1.update(contexto_h1)
                
                estado.analisis_h1 = analisis
                estado.analisis_pesado = analisis_pesado
                estado.direccion = direccion
                estado.regimen = regimen
                estado.direccion_regimen = direccion_regimen
                estado.confianza_regimen = confianza_regimen
                estado.tendencia_h4 = tendencia_h4
                estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                
                if score > estado.score_acumulado:
                    estado.score_acumulado = score
                
                self.logger.info(f"🔄 {simbolo}: Actualizado en FASE_1 (score: {estado.score_acumulado:.1f})")
            
            # ============================================================
            # 3. ✅ PROMOCIÓN INMEDIATA A FASE_2
            # ============================================================
            if estado.score_acumulado >= self.umbral_fase_2:
                if estado.fase_actual == FaseOportunidad.FASE_1:
                    estado.fase_actual = FaseOportunidad.FASE_2
                    estado.agregar_condicion("Score_Fase2")
                    estado.agregar_condicion("M15_Confirmacion")
                    self._stats['promovidas_f1_f2'] += 1
                    self.logger.info(f"⬆️ {simbolo}: PROMOVIDO INMEDIATO a FASE_2 (score: {estado.score_acumulado:.1f} >= {self.umbral_fase_2})")
                elif estado.fase_actual == FaseOportunidad.FASE_2:
                    # Ya está en FASE_2, mantener
                    pass
            
            # ============================================================
            # 4. ✅ PROMOCIÓN INMEDIATA A FASE_3 (si score es muy alto)
            # ============================================================
            if estado.score_acumulado >= self.umbral_fase_3:
                if estado.fase_actual == FaseOportunidad.FASE_2:
                    estado.fase_actual = FaseOportunidad.FASE_3
                    estado.agregar_condicion("Score_Fase3")
                    estado.agregar_condicion("M5_Sniper")
                    self._stats['promovidas_f2_f3'] += 1
                    self.logger.info(f"⬆️ {simbolo}: PROMOVIDO INMEDIATO a FASE_3 (score: {estado.score_acumulado:.1f} >= {self.umbral_fase_3})")
                elif estado.fase_actual == FaseOportunidad.FASE_1:
                    # Si está en FASE_1 y el score es suficiente para FASE_3, promover directamente
                    # Pero primero pasar por FASE_2 (flujo normal)
                    if estado.score_acumulado >= self.umbral_fase_2:
                        estado.fase_actual = FaseOportunidad.FASE_2
                        estado.agregar_condicion("Score_Fase2")
                        estado.agregar_condicion("M15_Confirmacion")
                        self._stats['promovidas_f1_f2'] += 1
                        self.logger.info(f"⬆️ {simbolo}: PROMOVIDO a FASE_2 (score: {estado.score_acumulado:.1f})")
                        
                        # Y luego a FASE_3
                        if estado.score_acumulado >= self.umbral_fase_3:
                            estado.fase_actual = FaseOportunidad.FASE_3
                            estado.agregar_condicion("Score_Fase3")
                            estado.agregar_condicion("M5_Sniper")
                            self._stats['promovidas_f2_f3'] += 1
                            self.logger.info(f"⬆️ {simbolo}: PROMOVIDO INMEDIATO a FASE_3 (score: {estado.score_acumulado:.1f} >= {self.umbral_fase_3})")
            
            # ============================================================
            # 5. ✅ GUARDAR NIVEL ESPERADO PARA ESPERA ACTIVA
            # ============================================================
            if estado.contexto_h1:
                soporte_cercano = estado.contexto_h1.get('soporte_cercano')
                resistencia_cercana = estado.contexto_h1.get('resistencia_cercana')
                precio_actual = estado.contexto_h1.get('precio_actual', 0)
                
                if soporte_cercano and soporte_cercano > 0 and precio_actual > 0:
                    distancia_soporte = (precio_actual - soporte_cercano) / precio_actual * 100
                    if distancia_soporte < 2.0:
                        estado.contexto_h1['nivel_esperado'] = soporte_cercano
                        estado.contexto_h1['modo_esperado'] = 'RETEST'
                        estado.metadata['esperando_nivel'] = True
                
                if resistencia_cercana and resistencia_cercana > 0 and precio_actual > 0:
                    distancia_resistencia = (resistencia_cercana - precio_actual) / precio_actual * 100
                    if distancia_resistencia < 0.5:
                        estado.contexto_h1['nivel_esperado'] = resistencia_cercana
                        estado.contexto_h1['modo_esperado'] = 'PULLBACK'
                        estado.metadata['esperando_nivel'] = True
            
            # ============================================================
            # 6. ✅ GUARDAR EN SQLITE
            # ============================================================
            self._guardar_estados_en_sqlite()
            
            return estado
            
        except Exception as e:
            # ✅ CORREGIDO V9.2: Capturar cualquier excepción
            self.logger.error(f"❌ Error en actualizar_fase_1({simbolo}): {e}", exc_info=True)
            return None

        
    def actualizar_fase_2(self, simbolo: str, analisis_m15: Dict, score: float) -> Optional[EstadoOportunidad]:
        """
        Actualiza la oportunidad en Fase 2 (M15 Confirmación).
        V9.15 - CORREGIDO: Promueve automáticamente a FASE_3.
        """
        estado = self.estados.get(simbolo)
        if not estado:
            return None
        
        if estado.fase_actual.es_terminal():
            return estado
        
        # Contar intento de Fase 2
        estado.metadata['intentos_fase2'] = estado.metadata.get('intentos_fase2', 0) + 1
        
        # ============================================================
        # LÍMITE DE INTENTOS PARA FASE 2
        # ============================================================
        calidad = self._calcular_calidad_oportunidad(estado)
        limite_intentos = 3 if calidad < 3 else 5
        
        # SI SUPERA EL LÍMITE, DEGRADAR A FASE_1
        if estado.metadata.get('intentos_fase2', 0) >= limite_intentos:
            self._degradar_oportunidad(
                simbolo,
                razon=f"Demasiados intentos en Fase 2 ({estado.metadata['intentos_fase2']})"
            )
            return estado
        
        # Actualizar análisis
        estado.analisis_m15 = analisis_m15
        estado.score_m15 = max(estado.score_m15, score)
        estado.score_acumulado = max(estado.score_acumulado, score)
        estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
        
        # Si estaba en FASE_1 y pasa el umbral, promover a FASE_2
        if estado.fase_actual == FaseOportunidad.FASE_1:
            if score >= self.umbral_fase_2:
                estado.fase_actual = FaseOportunidad.FASE_2
                estado.agregar_condicion("Score_Fase2")
                estado.agregar_condicion("M15_Confirmacion")
                self._stats['promovidas_f1_f2'] += 1
                self.logger.info(f"⬆️ {simbolo}: Promovido a FASE_2 (score: {score:.1f})")
        
        # En FASE_2, intentar cumplir condiciones
        if estado.fase_actual == FaseOportunidad.FASE_2:
            if score >= self.umbral_fase_2:
                estado.cumplir_condicion("Score_Fase2")
                estado.cumplir_condicion("M15_Confirmacion")
                
                # ✅ PROMOVER AUTOMÁTICAMENTE A FASE_3
                if score >= self.umbral_fase_3:
                    estado.fase_actual = FaseOportunidad.FASE_3
                    estado.agregar_condicion("Score_Fase3")
                    estado.agregar_condicion("M5_Sniper")
                    self._stats['promovidas_f2_f3'] += 1
                    self.logger.info(f"⬆️ {simbolo}: Promovido a FASE_3 (score: {score:.1f})")
        
        # Promover automáticamente si es posible
        self._promover_automaticamente(simbolo)
        
        self._guardar_estados_en_sqlite()
        
        return estado
    
    def actualizar_fase_3(self, simbolo: str, analisis_m5: Dict, score: float):
        estado = self.estados.get(simbolo)
        if not estado:
            return None
        
        if estado.fase_actual.es_terminal():
            return estado
        
        # Contar intento de sniper
        estado.metadata['intentos_sniper'] = estado.metadata.get('intentos_sniper', 0) + 1
        
        # ============================================================
        # CALCULAR CALIDAD DE LA OPORTUNIDAD
        # ============================================================
        calidad = self._calcular_calidad_oportunidad(estado)
        limite_intentos = self._calcular_limite_intentos(calidad)
        
        # SI SUPERA EL LÍMITE, DEGRADAR
        if estado.metadata.get('intentos_sniper', 0) >= limite_intentos:
            # Si la calidad es alta, mantener en pipeline (degradar a FASE_2)
            if calidad >= 3:
                self._degradar_oportunidad(simbolo, razon=f"Calidad alta ({calidad}/4) - {estado.metadata['intentos_sniper']} intentos")
            else:
                self._degradar_oportunidad(simbolo, razon=f"Calidad baja ({calidad}/4) - {estado.metadata['intentos_sniper']} intentos")
            return estado
        
        # ============================================================
        # SI EL SCORE ES BAJO, EVALUAR SEGÚN CALIDAD
        # ============================================================
        if score < self.umbral_fase_3 * 0.5:
            if calidad < 3:
                self._degradar_oportunidad(simbolo, razon=f"Score bajo ({score:.1f}) y calidad baja ({calidad}/4)")
            else:
                estado.metadata['esperando_condicion'] = True
                self.logger.info(f"⏳ {simbolo}: Esperando condición (calidad alta, score bajo)")
            return estado
        
        # ============================================================
        # ACTUALIZAR ANÁLISIS Y SCORE
        # ============================================================
        estado.analisis_m5 = analisis_m5
        estado.score_final = max(estado.score_final, score)
        estado.score_acumulado = max(estado.score_acumulado, score)
        estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
        
        # ============================================================
        # PROMOVER A FASE_3 SI ES NECESARIO
        # ============================================================
        if estado.fase_actual == FaseOportunidad.FASE_2:
            if score >= self.umbral_fase_3:
                estado.fase_actual = FaseOportunidad.FASE_3
                estado.agregar_condicion("Score_Fase3")
                estado.agregar_condicion("M5_Sniper")
                self._stats['promovidas_f2_f3'] += 1
                self.logger.info(f"⬆️ {simbolo}: Promovido a FASE_3 (score: {score:.1f})")
        
        # ============================================================
        # CUMPLIR CONDICIONES SI ESTÁ EN FASE_3
        # ============================================================
        if estado.fase_actual == FaseOportunidad.FASE_3:
            if score >= self.umbral_fase_3:
                estado.cumplir_condicion("Score_Fase3")
                estado.cumplir_condicion("M5_Sniper")
        
        self._guardar_estados_en_sqlite()
        
        return estado

    
    # ============================================================
    # PROMOCIÓN AUTOMÁTICA
    # ============================================================
    
    def _promover_automaticamente(self, simbolo: str):
        """
        Promueve automáticamente una oportunidad basada en SCORE ACUMULADO.
        V9.31 - UNIFICADO: NO usa condiciones pendientes.
        """
        estado = self.estados.get(simbolo)
        if not estado:
            return
        
        if estado.fase_actual.es_terminal():
            return
        
        # ============================================================
        # ✅ PROMOCIÓN POR SCORE (SIN CONDICIONES)
        # ============================================================
        
        # FASE_1 → FASE_2
        if estado.fase_actual == FaseOportunidad.FASE_1:
            if estado.score_acumulado >= self.umbral_fase_2:
                estado.fase_actual = FaseOportunidad.FASE_2
                estado.agregar_condicion("Score_Fase2")
                estado.agregar_condicion("M15_Confirmacion")
                self._stats['promovidas_f1_f2'] += 1
                self.logger.info(f"⬆️ {simbolo}: Promovido a FASE_2 (score: {estado.score_acumulado:.1f} >= {self.umbral_fase_2})")
                self._guardar_estados_en_sqlite()
            else:
                self.logger.debug(f"⏳ {simbolo}: Score {estado.score_acumulado:.1f} < {self.umbral_fase_2} para FASE_2")
        
        # FASE_2 → FASE_3
        elif estado.fase_actual == FaseOportunidad.FASE_2:
            if estado.score_acumulado >= self.umbral_fase_3:
                estado.fase_actual = FaseOportunidad.FASE_3
                estado.agregar_condicion("Score_Fase3")
                estado.agregar_condicion("M5_Sniper")
                self._stats['promovidas_f2_f3'] += 1
                self.logger.info(f"⬆️ {simbolo}: Promovido a FASE_3 (score: {estado.score_acumulado:.1f} >= {self.umbral_fase_3})")
                self._guardar_estados_en_sqlite()
            else:
                self.logger.debug(f"⏳ {simbolo}: Score {estado.score_acumulado:.1f} < {self.umbral_fase_3} para FASE_3")
        
        # ============================================================
        # ⚠️ SI ALGO SALE MAL, FORZAR PROMOCIÓN POR SCORE ALTO
        # ============================================================
        if estado.score_acumulado >= 80:
            if estado.fase_actual == FaseOportunidad.FASE_1:
                # Promover directamente a FASE_2
                estado.fase_actual = FaseOportunidad.FASE_2
                estado.agregar_condicion("Score_Fase2")
                estado.agregar_condicion("M15_Confirmacion")
                self._stats['promovidas_f1_f2'] += 1
                self.logger.info(f"⬆️ {simbolo}: FORZADO a FASE_2 (score alto: {estado.score_acumulado:.1f})")
                self._guardar_estados_en_sqlite()
            
            elif estado.fase_actual == FaseOportunidad.FASE_2:
                # Promover directamente a FASE_3
                estado.fase_actual = FaseOportunidad.FASE_3
                estado.agregar_condicion("Score_Fase3")
                estado.agregar_condicion("M5_Sniper")
                self._stats['promovidas_f2_f3'] += 1
                self.logger.info(f"⬆️ {simbolo}: FORZADO a FASE_3 (score alto: {estado.score_acumulado:.1f})")
                self._guardar_estados_en_sqlite()
    
    def promover_automaticamente(self):
        """
        Promueve TODAS las oportunidades automáticamente.
        V9.31 - UNIFICADO: Usa el método por SCORE.
        """
        if not self.estados:
            return
        
        # ============================================================
        # 1. LOG DE ESTADO ACTUAL
        # ============================================================
        from analysis.pipeline import FaseOportunidad
        
        activos = self.obtener_activos()
        fase1 = [o for o in activos if o.fase_actual == FaseOportunidad.FASE_1]
        fase2 = [o for o in activos if o.fase_actual == FaseOportunidad.FASE_2]
        fase3 = [o for o in activos if o.fase_actual == FaseOportunidad.FASE_3]
        
        self.logger.info(f"🔄 Promoviendo: F1:{len(fase1)} F2:{len(fase2)} F3:{len(fase3)}")
        
        # ============================================================
        # 2. PROMOVER CADA SÍMBOLO
        # ============================================================
        for simbolo in list(self.estados.keys()):
            estado = self.estados.get(simbolo)
            if not estado or estado.fase_actual.es_terminal():
                continue
            
            fase_anterior = estado.fase_actual.value
            score = estado.score_acumulado
            
            self._promover_automaticamente(simbolo)
            
            # Verificar cambio
            estado_actualizado = self.estados.get(simbolo)
            if estado_actualizado and estado_actualizado.fase_actual.value != fase_anterior:
                self.logger.info(f"⬆️ {simbolo}: {fase_anterior} → {estado_actualizado.fase_actual.value} (score: {score:.1f})")
        
        # ============================================================
        # 3. ✅ DIAGNÓSTICO: ¿HAY OPORTUNIDADES QUE DEBERÍAN PROMOVER?
        # ============================================================
        for simbolo, estado in self.estados.items():
            if estado.fase_actual == FaseOportunidad.FASE_1 and estado.score_acumulado >= self.umbral_fase_2:
                self.logger.warning(f"⚠️ {simbolo}: Score {estado.score_acumulado:.1f} >= {self.umbral_fase_2} pero en FASE_1 - FORZANDO...")
                # FORZAR PROMOCIÓN DIRECTA
                estado.fase_actual = FaseOportunidad.FASE_2
                estado.agregar_condicion("Score_Fase2")
                estado.agregar_condicion("M15_Confirmacion")
                self._stats['promovidas_f1_f2'] += 1
                self.logger.info(f"⬆️ {simbolo}: FORZADO a FASE_2")
            
            elif estado.fase_actual == FaseOportunidad.FASE_2 and estado.score_acumulado >= self.umbral_fase_3:
                self.logger.warning(f"⚠️ {simbolo}: Score {estado.score_acumulado:.1f} >= {self.umbral_fase_3} pero en FASE_2 - FORZANDO...")
                estado.fase_actual = FaseOportunidad.FASE_3
                estado.agregar_condicion("Score_Fase3")
                estado.agregar_condicion("M5_Sniper")
                self._stats['promovidas_f2_f3'] += 1
                self.logger.info(f"⬆️ {simbolo}: FORZADO a FASE_3")
        
        # ============================================================
        # 4. GUARDAR Y LOG FINAL
        # ============================================================
        self._guardar_estados_en_sqlite()
        
        activos = self.obtener_activos()
        fase1 = [o for o in activos if o.fase_actual == FaseOportunidad.FASE_1]
        fase2 = [o for o in activos if o.fase_actual == FaseOportunidad.FASE_2]
        fase3 = [o for o in activos if o.fase_actual == FaseOportunidad.FASE_3]
        
        self.logger.info(f"📊 Pipeline después: F1:{len(fase1)} F2:{len(fase2)} F3:{len(fase3)}")
        
        if fase3:
            for estado in fase3:
                self.logger.info(f"🎯 {estado.simbolo}: FASE_3 (score: {estado.score_acumulado:.1f})")

    
    
    # ============================================================
    # GESTIÓN DE ESTADOS
    # ============================================================
    
    def marcar_ejecutada(self, simbolo: str):
        """Marca una oportunidad como ejecutada."""
        estado = self.estados.get(simbolo)
        if estado:
            estado.fase_actual = FaseOportunidad.EJECUTADA
            estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            self._stats['ejecutadas'] += 1
            self.logger.debug(f"✅ {simbolo}: marcada como EJECUTADA")
        self._guardar_estados_en_sqlite()
    
    def marcar_cancelada(self, simbolo: str, razon: str = ""):
        """Marca una oportunidad como cancelada."""
        estado = self.estados.get(simbolo)
        if estado:
            estado.fase_actual = FaseOportunidad.CANCELADA
            estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            estado.ultimo_error = razon
            self._stats['canceladas'] += 1
            self.logger.debug(f"❌ {simbolo}: cancelada ({razon})")
        self._guardar_estados_en_sqlite()

    def liberar_simbolo(self, simbolo: str):
        """Libera un símbolo del pipeline."""
        if simbolo in self.estados:
            del self.estados[simbolo]
            self.logger.debug(f"🗑️ {simbolo}: liberado del pipeline")
        self._guardar_estados_en_sqlite()
    # ============================================================
    # CONSULTAS
    # ============================================================
    
    def obtener_estado(self, simbolo: str) -> Optional[EstadoOportunidad]:
        """Obtiene el estado de un símbolo."""
        return self.estados.get(simbolo)
    
    def obtener_todos_estados(self) -> List[EstadoOportunidad]:
        """Obtiene todos los estados."""
        return list(self.estados.values())
    
    def obtener_activos(self) -> List[EstadoOportunidad]:
        """Obtiene estados activos (no terminales)."""
        return [
            e for e in self.estados.values()
            if e.fase_actual.es_activa()
        ]

    def obtener_fase_3(self) -> List[EstadoOportunidad]:
        """
        Devuelve solo oportunidades en FASE_3 (listas para sniper).
        """
        return [
            e for e in self.estados.values()
            if e.fase_actual == FaseOportunidad.FASE_3
        ]
    
    def obtener_por_fase(self, fase) -> List:
        """Obtiene estados por fase."""
        from analysis.pipeline import FaseOportunidad  # <-- IMPORT CORRECTO
        return [
            e for e in self.estados.values()
            if e.fase_actual == fase
        ]
    
    def obtener_priorizados(self, max_resultados: int = 10) -> List[EstadoOportunidad]:
        """
        Obtiene oportunidades priorizadas por score.
        
        Args:
            max_resultados: Número máximo de resultados
        
        Returns:
            Lista de estados ordenados por score
        """
        activos = self.obtener_activos()
        activos.sort(key=lambda x: (x.score_acumulado, x.fase_actual.value), reverse=True)
        return activos[:max_resultados]
    
    def existe_oportunidad(self, simbolo: str) -> bool:
        """Verifica si existe una oportunidad para un símbolo."""
        return simbolo in self.estados
    
    def es_activa(self, simbolo: str) -> bool:
        """Verifica si la oportunidad de un símbolo está activa."""
        estado = self.estados.get(simbolo)
        return estado is not None and estado.fase_actual.es_activa()
    
    # ============================================================
    # LIMPIEZA
    # ============================================================
    
    def limpiar_antiguos(self, horas: Optional[int] = None) -> int:
        """
        Limpia oportunidades antiguas.
        
        Args:
            horas: Edad máxima en horas (None = usar config)
        
        Returns:
            Número de oportunidades eliminadas
        """
        if horas is None:
            horas = self.max_edad_horas
        
        ahora = datetime.now(timezone.utc)
        to_remove = []
        
        for simbolo, estado in self.estados.items():
            edad = (ahora - estado.timestamp_creacion).total_seconds() / 3600
            
            # Eliminar si excede la edad máxima
            if edad > horas:
                to_remove.append(simbolo)
                self._stats['expiradas'] += 1
                continue
            
            # Eliminar estados terminales antiguos (1 hora)
            if estado.fase_actual.es_terminal():
                edad_terminal = (ahora - estado.timestamp_ultima_actualizacion).total_seconds() / 3600
                if edad_terminal > 1:  # 1 hora después de terminal
                    to_remove.append(simbolo)
                    continue
        
        for simbolo in to_remove:
            del self.estados[simbolo]
            self.logger.debug(f"🧹 {simbolo}: eliminado del pipeline (antiguo)")
        
        if to_remove:
            self.logger.info(f"🧹 {len(to_remove)} oportunidades eliminadas del pipeline")

        self._guardar_estados_en_sqlite()
        return len(to_remove)
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del pipeline."""
        stats = self._stats.copy()
        stats['total_estados'] = len(self.estados)
        stats['activos'] = len(self.obtener_activos())
        stats['por_fase'] = {
            fase.value: len(self.obtener_por_fase(fase))
            for fase in FaseOportunidad
        }
        stats['edad_promedio_horas'] = self._calcular_edad_promedio()
        
        return stats
    
    def _calcular_edad_promedio(self) -> float:
        """Calcula la edad promedio de las oportunidades activas."""
        activos = self.obtener_activos()
        if not activos:
            return 0.0
        
        ahora = datetime.now(timezone.utc)
        edades = [(ahora - e.timestamp_creacion).total_seconds() / 3600 for e in activos]
        return sum(edades) / len(edades)
    
    def print_stats(self):
        """Imprime estadísticas en formato legible."""
        stats = self.get_stats()
        
        print("\n" + "=" * 50)
        print("📊 ESTADÍSTICAS DEL PIPELINE")
        print("=" * 50)
        print(f"Total estados: {stats['total_estados']}")
        print(f"Activos: {stats['activos']}")
        print(f"Edad promedio: {stats['edad_promedio_horas']:.1f}h")
        print("\nPor fase:")
        for fase, count in stats['por_fase'].items():
            print(f"  {fase}: {count}")
        print("\nTransiciones:")
        print(f"  F1→F2: {stats['promovidas_f1_f2']}")
        print(f"  F2→F3: {stats['promovidas_f2_f3']}")
        print(f"  Ejecutadas: {stats['ejecutadas']}")
        print(f"  Canceladas: {stats['canceladas']}")
        print("=" * 50)
    
    # ============================================================
    # PERSISTENCIA (OPCIONAL)
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """Serializa todo el pipeline a diccionario."""
        return {
            'estados': {s: e.to_dict() for s, e in self.estados.items()},
            'stats': self._stats,
            'umbrales': {
                'fase_1': self.umbral_fase_1,
                'fase_2': self.umbral_fase_2,
                'fase_3': self.umbral_fase_3,
            }
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], config: Optional[Any] = None) -> 'PipelineOportunidades':
        """
        Restaura un pipeline desde diccionario.
        
        Args:
            data: Diccionario con datos serializados
            config: Configuración
        
        Returns:
            PipelineOportunidades
        """
        pipeline = cls(config=config)
        
        # Restaurar umbrales
        if 'umbrales' in data:
            pipeline.umbral_fase_1 = data['umbrales'].get('fase_1', pipeline.umbral_fase_1)
            pipeline.umbral_fase_2 = data['umbrales'].get('fase_2', pipeline.umbral_fase_2)
            pipeline.umbral_fase_3 = data['umbrales'].get('fase_3', pipeline.umbral_fase_3)
        
        # Restaurar estadísticas
        if 'stats' in data:
            pipeline._stats.update(data['stats'])
        
        # Nota: Los estados requieren reconstrucción compleja,
        # mejor limpiar y dejar que se reconstruyan desde cero
        pipeline.limpiar_antiguos(0)
        
        return pipeline


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_pipeline(config: Optional[Any] = None,
                    umbral_fase_1: Optional[float] = None,
                    umbral_fase_2: Optional[float] = None,
                    umbral_fase_3: Optional[float] = None,
                    modo_backtest: bool = False) -> PipelineOportunidades:
    """
    Crea una instancia de PipelineOportunidades.
    
    Args:
        config: Configuración
        umbral_fase_1: Score mínimo Fase 1
        umbral_fase_2: Score mínimo Fase 2
        umbral_fase_3: Score mínimo Fase 3
        modo_backtest: Modo backtest
    
    Returns:
        PipelineOportunidades
    """
    return PipelineOportunidades(
        config=config,
        umbral_fase_1=umbral_fase_1,
        umbral_fase_2=umbral_fase_2,
        umbral_fase_3=umbral_fase_3,
        modo_backtest=modo_backtest
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida
    print("🧪 Probando PipelineOportunidades...")
    
    pipeline = PipelineOportunidades(modo_backtest=True)
    
    # Simular Fase 1
    estado = pipeline.actualizar_fase_1(
        simbolo='EURUSD',
        analisis={},
        score=55,
        direccion='COMPRA',
        regimen='TREND_ALCISTA_FUERTE'
    )
    
    print(f"Fase 1: {estado.fase_actual.value} (score: {estado.score_acumulado:.1f})")
    
    # Simular Fase 2
    estado = pipeline.actualizar_fase_2(
        simbolo='EURUSD',
        analisis_m15={},
        score=50
    )
    
    print(f"Fase 2: {estado.fase_actual.value} (score: {estado.score_acumulado:.1f})")
    
    # Simular Fase 3
    estado = pipeline.actualizar_fase_3(
        simbolo='EURUSD',
        analisis_m5={},
        score=60
    )
    
    print(f"Fase 3: {estado.fase_actual.value} (score: {estado.score_acumulado:.1f})")
    
    # Estadísticas
    pipeline.print_stats()
    
    print("\n✅ Prueba completada")