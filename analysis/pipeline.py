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
    
    # Contexto
    regimen: str = 'UNCERTAIN'
    direccion_regimen: str = 'NONE'
    confianza_regimen: float = 0
    tendencia_h4: str = 'LATERAL'
    calidad_horario: str = 'REGULAR'
    
    # Scores específicos
    score_m15: float = 0.0
    score_final: float = 0.0
    contexto_h1: Optional[Dict] = None
    
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
                 modo_backtest: bool = False):
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
        self.logger = logging.getLogger('BotTrading.Pipeline')
        
        # Umbrales
        self.umbral_fase_1 = self._cargar_umbral('fase_1', umbral_fase_1, 30)
        self.umbral_fase_2 = self._cargar_umbral('fase_2', umbral_fase_2, 45)
        self.umbral_fase_3 = self._cargar_umbral('fase_3', umbral_fase_3, 55)
        self.max_edad_horas = max_edad_horas
        
        # Almacenamiento
        self.estados: Dict[str, EstadoOportunidad] = {}
        
        # Estadísticas
        self._stats = {
            'creadas': 0,
            'promovidas_f1_f2': 0,
            'promovidas_f2_f3': 0,
            'ejecutadas': 0,
            'canceladas': 0,
            'expiradas': 0,
        }
        
        self.logger.info(f"🔀 PipelineOportunidades V9.0 inicializado")
        self.logger.info(f"   Umbrales: F1={self.umbral_fase_1}, F2={self.umbral_fase_2}, F3={self.umbral_fase_3}")
        self.logger.info(f"   Max edad: {max_edad_horas}h")
        self.logger.info(f"   Backtest: {modo_backtest}")
    
    def _cargar_umbral(self, fase: str, personalizado: Optional[float], default: float) -> float:
        """
        Carga umbral desde configuración.
        
        Args:
            fase: Nombre de la fase
            personalizado: Valor personalizado
            default: Valor por defecto
        
        Returns:
            Umbral
        """
        if personalizado is not None:
            return float(personalizado)
        
        if self.config:
            if hasattr(self.config, f'PIPELINE_UMBRAL_{fase.upper()}'):
                return float(getattr(self.config, f'PIPELINE_UMBRAL_{fase.upper()}', default))
        
        if Umbrales is not None:
            if hasattr(Umbrales, 'SCORES'):
                key = f'score_minimo_{fase}'
                if key in Umbrales.SCORES:
                    return float(Umbrales.SCORES[key])
        
        if self.modo_backtest:
            return max(5, default * 0.3)
        
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
                          tendencia_h4: str = 'LATERAL') -> Optional[EstadoOportunidad]:
        """
        Actualiza la oportunidad en Fase 1 (H1).
        
        Args:
            simbolo: Símbolo
            analisis: Análisis completo
            score: Score H1
            direccion: Dirección
            regimen: Régimen de mercado
            direccion_regimen: Dirección del régimen
            confianza_regimen: Confianza del régimen
            tendencia_h4: Tendencia H4
        
        Returns:
            EstadoOportunidad o None
        """
        # Validar score mínimo
        if score < self.umbral_fase_1 * 0.5:
            return None
        
        # Buscar estado existente
        estado = self.estados.get(simbolo)
        
        if estado is None:
            # Crear nuevo estado
            estado = EstadoOportunidad(
                simbolo=simbolo,
                fase_actual=FaseOportunidad.FASE_1,
                direccion=direccion,
                score_acumulado=score,
                timestamp_creacion=datetime.now(timezone.utc),
                timestamp_ultima_actualizacion=datetime.now(timezone.utc),
                analisis_h1=analisis,
                regimen=regimen,
                direccion_regimen=direccion_regimen,
                confianza_regimen=confianza_regimen,
                tendencia_h4=tendencia_h4
            )
            
            # Agregar condiciones iniciales
            estado.agregar_condicion("Score_Fase1")
            estado.agregar_condicion("Direccion_Definida")
            
            self.estados[simbolo] = estado
            self._stats['creadas'] += 1
            
            self.logger.debug(f"📝 Nueva oportunidad: {simbolo} (F1, score={score:.1f}, dir={direccion})")
        else:
            # Actualizar estado existente
            if estado.fase_actual.es_terminal():
                # Si está en fase terminal, no actualizar
                return estado
            
            # Actualizar análisis y score
            estado.analisis_h1 = analisis
            estado.direccion = direccion
            estado.regimen = regimen
            estado.direccion_regimen = direccion_regimen
            estado.confianza_regimen = confianza_regimen
            estado.tendencia_h4 = tendencia_h4
            estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            
            if score > estado.score_acumulado:
                estado.score_acumulado = score
        
        # Intentar cumplir condiciones
        if score >= self.umbral_fase_1:
            estado.cumplir_condicion("Score_Fase1")
        
        if direccion != 'NEUTRAL':
            estado.cumplir_condicion("Direccion_Definida")
        
        # Promover automáticamente si es posible
        self._promover_automaticamente(simbolo)
        
        return estado
    
    def actualizar_fase_2(self,
                          simbolo: str,
                          analisis_m15: Dict,
                          score: float) -> Optional[EstadoOportunidad]:
        """
        Actualiza la oportunidad en Fase 2 (M15).
        
        Args:
            simbolo: Símbolo
            analisis_m15: Análisis M15
            score: Score M15
        
        Returns:
            EstadoOportunidad o None
        """
        estado = self.estados.get(simbolo)
        if not estado:
            return None
        
        if estado.fase_actual.es_terminal():
            return estado
        
        # Solo permitir actualización desde FASE_1 o FASE_2
        if estado.fase_actual not in [FaseOportunidad.FASE_1, FaseOportunidad.FASE_2]:
            self.logger.debug(f"⏭️ {simbolo}: no se puede actualizar Fase 2 desde {estado.fase_actual.value}")
            return estado
        
        # Actualizar análisis M15
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
                self.logger.info(f"⬆️ {simbolo}: promovido a FASE_2 (score: {score:.1f})")
        
        # En FASE_2, intentar cumplir condiciones
        if estado.fase_actual == FaseOportunidad.FASE_2:
            if score >= self.umbral_fase_2:
                estado.cumplir_condicion("Score_Fase2")
                estado.cumplir_condicion("M15_Confirmacion")
        
        # Promover automáticamente si es posible
        self._promover_automaticamente(simbolo)
        
        return estado
    
    def actualizar_fase_3(self,
                          simbolo: str,
                          analisis_m5: Dict,
                          score: float) -> Optional[EstadoOportunidad]:
        """
        Actualiza la oportunidad en Fase 3 (M5).
        
        Args:
            simbolo: Símbolo
            analisis_m5: Análisis M5
            score: Score M5
        
        Returns:
            EstadoOportunidad o None
        """
        estado = self.estados.get(simbolo)
        if not estado:
            return None
        
        if estado.fase_actual.es_terminal():
            return estado
        
        # Solo permitir desde FASE_2 o FASE_3
        if estado.fase_actual not in [FaseOportunidad.FASE_2, FaseOportunidad.FASE_3]:
            self.logger.debug(f"⏭️ {simbolo}: no se puede actualizar Fase 3 desde {estado.fase_actual.value}")
            return estado
        
        # Actualizar análisis M5
        estado.analisis_m5 = analisis_m5
        estado.score_final = max(estado.score_final, score)
        estado.score_acumulado = max(estado.score_acumulado, score)
        estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
        
        # Si estaba en FASE_2 y pasa el umbral, promover a FASE_3
        if estado.fase_actual == FaseOportunidad.FASE_2:
            if score >= self.umbral_fase_3:
                estado.fase_actual = FaseOportunidad.FASE_3
                estado.agregar_condicion("Score_Fase3")
                estado.agregar_condicion("M5_Sniper")
                self._stats['promovidas_f2_f3'] += 1
                self.logger.info(f"⬆️ {simbolo}: promovido a FASE_3 (score: {score:.1f})")
        
        # En FASE_3, intentar cumplir condiciones
        if estado.fase_actual == FaseOportunidad.FASE_3:
            if score >= self.umbral_fase_3:
                estado.cumplir_condicion("Score_Fase3")
                estado.cumplir_condicion("M5_Sniper")
        
        return estado
    
    # ============================================================
    # PROMOCIÓN AUTOMÁTICA
    # ============================================================
    
    def _promover_automaticamente(self, simbolo: str):
        """
        Promueve la oportunidad a la siguiente fase si es posible.
        
        Args:
            simbolo: Símbolo
        """
        estado = self.estados.get(simbolo)
        if not estado:
            return
        
        if estado.fase_actual.es_terminal():
            return
        
        # Incrementar contador de intentos
        estado.intentos_promocion += 1
        
        # Prevenir bucles infinitos
        if estado.intentos_promocion > 10:
            estado.ultimo_error = "Demasiados intentos de promoción"
            return
        
        # --- FASE_1 → FASE_2 ---
        if estado.fase_actual == FaseOportunidad.FASE_1:
            if not estado.tiene_condiciones_pendientes():
                estado.fase_actual = FaseOportunidad.FASE_2
                estado.agregar_condicion("Score_Fase2")
                estado.agregar_condicion("M15_Confirmacion")
                self._stats['promovidas_f1_f2'] += 1
                self.logger.info(f"⬆️ {simbolo}: promovido a FASE_2 (score: {estado.score_acumulado:.1f})")
            else:
                self.logger.debug(f"⏳ {simbolo}: esperando condiciones F1: {estado.condiciones_pendientes}")
        
        # --- FASE_2 → FASE_3 ---
        elif estado.fase_actual == FaseOportunidad.FASE_2:
            if not estado.tiene_condiciones_pendientes():
                estado.fase_actual = FaseOportunidad.FASE_3
                estado.agregar_condicion("Score_Fase3")
                estado.agregar_condicion("M5_Sniper")
                self._stats['promovidas_f2_f3'] += 1
                self.logger.info(f"⬆️ {simbolo}: promovido a FASE_3 (score: {estado.score_acumulado:.1f})")
            else:
                self.logger.debug(f"⏳ {simbolo}: esperando condiciones F2: {estado.condiciones_pendientes}")
    
    def promover_automaticamente(self):
        """
        Promueve automáticamente todas las oportunidades elegibles.
        """
        for simbolo in list(self.estados.keys()):
            self._promover_automaticamente(simbolo)
    
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
    
    def marcar_cancelada(self, simbolo: str, razon: str = ""):
        """Marca una oportunidad como cancelada."""
        estado = self.estados.get(simbolo)
        if estado:
            estado.fase_actual = FaseOportunidad.CANCELADA
            estado.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
            estado.ultimo_error = razon
            self._stats['canceladas'] += 1
            self.logger.debug(f"❌ {simbolo}: cancelada ({razon})")
    
    def liberar_simbolo(self, simbolo: str):
        """Libera un símbolo del pipeline."""
        if simbolo in self.estados:
            del self.estados[simbolo]
            self.logger.debug(f"🗑️ {simbolo}: liberado del pipeline")
    
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
    
    def obtener_por_fase(self, fase: FaseOportunidad) -> List[EstadoOportunidad]:
        """Obtiene estados por fase."""
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