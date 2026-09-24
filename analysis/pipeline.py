#!/usr/bin/env python3
"""
analysis/pipeline.py (V11.1 - FIX LOOP M15)
Pipeline de 3 fases para oportunidades de trading.

CAMBIOS V11.1 (CRÍTICO):
- ✅ FIX LOOP INFINITO: bloqueo escalado cuando M15 contradice H1
  - Antes: ETHUSD degradaba → re-promovía inmediatamente → loop cada 30s
  - Ahora: bloqueo de 30min → 60min → 120min → 240min (escalado)
- ✅ Cooldown también verificado en _evaluar_promocion_f1_f2
  (antes solo se verificaba en actualizar_fase_1)
- ✅ Bloqueo M15 solo se activa si las direcciones son LAS MISMAS
  (si M15 se alinea con H1, se limpia automáticamente)
- ✅ Limpieza automática de bloqueos expirados
- ✅ Stats de bloqueos M15

MANTIENE:
- Fix M15_Confirmacion real (V11.0)
- Degradación por tiempo
- Promoción por evidencia
- Interfaces públicas
"""

import time
import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from config.umbrales import Umbrales
from utils.reloj import now_utc

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
        return self not in (FaseOportunidad.EJECUTADA, FaseOportunidad.CANCELADA)

    def es_terminal(self) -> bool:
        return self in (FaseOportunidad.EJECUTADA, FaseOportunidad.CANCELADA)


class MotivoDegradacion:
    """Motivos tipificados de degradación."""
    TIEMPO_EXCEDIDO = "TIEMPO_EXCEDIDO"
    SCORE_INSUFICIENTE = "SCORE_INSUFICIENTE"
    DIRECCION_INVALIDA = "DIRECCION_INVALIDA"
    REGIMEN_CAMBIO = "REGIMEN_CAMBIO"
    M15_NO_CONFIRMA = "M15_NO_CONFIRMA"
    M15_CONTRADICE = "M15_CONTRADICE"
    M5_NO_CONFIRMA = "M5_NO_CONFIRMA"
    SNIPER_FALLOS = "SNIPER_FALLOS"
    NIVEL_PERDIDO = "NIVEL_PERDIDO"
    MANUAL = "MANUAL"


# ============================================================
# DATACLASS EstadoOportunidad
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

    condiciones_pendientes: List[str] = field(default_factory=list)
    condiciones_cumplidas: List[str] = field(default_factory=list)

    analisis_h1: Optional[Dict] = None
    analisis_m15: Optional[Dict] = None
    analisis_m5: Optional[Dict] = None
    analisis_pesado: Optional[Dict] = None

    regimen: str = 'UNCERTAIN'
    direccion_regimen: str = 'NONE'
    confianza_regimen: float = 0.0
    tendencia_h4: str = 'LATERAL'
    calidad_horario: str = 'REGULAR'

    score_m15: float = 0.0
    score_final: float = 0.0
    score_pesado: float = 0.0
    contexto_h1: Optional[Dict] = None
    contexto_m15: Optional[Dict] = None
    contexto_m5: Optional[Dict] = None

    direccion_m15: str = 'NEUTRAL'
    m15_confirmo: bool = False

    intentos_promocion: int = 0
    ultimo_error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    degradaciones: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if self.timestamp_creacion.tzinfo is None:
            self.timestamp_creacion = self.timestamp_creacion.replace(tzinfo=timezone.utc)
        if self.timestamp_ultima_actualizacion.tzinfo is None:
            self.timestamp_ultima_actualizacion = self.timestamp_ultima_actualizacion.replace(tzinfo=timezone.utc)

    def obtener_condiciones_pendientes(self) -> List[str]:
        return self.condiciones_pendientes.copy()

    def cumplir_condicion(self, condicion: str) -> bool:
        if condicion in self.condiciones_pendientes:
            self.condiciones_pendientes.remove(condicion)
            self.condiciones_cumplidas.append(condicion)
            self.timestamp_ultima_actualizacion = now_utc()
            return True
        return False

    def agregar_condicion(self, condicion: str) -> bool:
        if condicion in self.condiciones_pendientes or condicion in self.condiciones_cumplidas:
            return False
        self.condiciones_pendientes.append(condicion)
        self.timestamp_ultima_actualizacion = now_utc()
        return True

    def tiene_condiciones_pendientes(self) -> bool:
        return len(self.condiciones_pendientes) > 0

    def porcentaje_completado(self) -> float:
        total = len(self.condiciones_pendientes) + len(self.condiciones_cumplidas)
        if total == 0:
            return 0.0
        return (len(self.condiciones_cumplidas) / total) * 100

    def registrar_degradacion(self, motivo: str, razon: str, fase_origen: FaseOportunidad):
        self.degradaciones.append({
            'timestamp': now_utc().isoformat(),
            'fase_origen': fase_origen.value,
            'motivo': motivo,
            'razon': razon,
            'score': self.score_acumulado,
            'intentos_promocion': self.intentos_promocion,
        })
        if len(self.degradaciones) > 20:
            self.degradaciones = self.degradaciones[-20:]

    def to_dict(self) -> Dict[str, Any]:
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
            'direccion_m15': self.direccion_m15,
            'm15_confirmo': self.m15_confirmo,
            'porcentaje_completado': self.porcentaje_completado(),
            'analisis_pesado': self.analisis_pesado,
            'degradaciones': self.degradaciones,
            'intentos_promocion': self.intentos_promocion,
            'ultimo_error': self.ultimo_error,
        }


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class PipelineOportunidades:
    """
    Pipeline de 3 fases con promoción por evidencia real.
    V11.1 - FIX LOOP M15.
    """

    # ============================================================
    # ✅ CONFIGURACIÓN DEL BLOQUEO M15
    # ============================================================

    # Duraciones escaladas según intentos consecutivos (en minutos)
    DURACIONES_BLOQUEO_M15 = [30, 60, 120, 240]

    # Máximo de intentos antes de forzar cancelación (opcional)
    MAX_INTENTOS_M15 = 5

    # ============================================================
    # CONFIGURACIÓN GENERAL
    # ============================================================

    LIMITES_INTENTOS_POR_CALIDAD = {
        4: 10,
        3: 7,
        2: 5,
        1: 3,
        0: 2,
    }

    MAX_INTENTOS_FASE_2 = 5
    MAX_INTENTOS_FASE_3 = 8

    LIMITES_TIEMPO_FASE = {
        FaseOportunidad.FASE_1: 3.0,
        FaseOportunidad.FASE_2: 1.5,
        FaseOportunidad.FASE_3: 0.75,
    }

    COOLDOWN_DEGRADACION_MINUTOS = 15

    def __init__(
        self,
        config: Optional[Any] = None,
        umbral_fase_1: Optional[float] = None,
        umbral_fase_2: Optional[float] = None,
        umbral_fase_3: Optional[float] = None,
        max_edad_horas: int = 48,
        modo_backtest: bool = False,
        almacen: Optional[Any] = None,
    ):
        self.config = config
        self.modo_backtest = modo_backtest
        self.almacen = almacen
        self.logger = logging.getLogger('BotTrading.Pipeline')

        self.umbral_fase_1 = self._cargar_umbral('fase_1', umbral_fase_1, 30)
        self.umbral_fase_2 = self._cargar_umbral('fase_2', umbral_fase_2, 45)
        self.umbral_fase_3 = self._cargar_umbral('fase_3', umbral_fase_3, 55)
        self.max_edad_horas = max_edad_horas

        self.estados: Dict[str, EstadoOportunidad] = {}
        self._cooldowns: Dict[str, datetime] = {}

        # ✅ V11.1: bloqueos M15
        self._m15_blocks: Dict[str, Dict[str, Any]] = {}

        self._stats = {
            'creadas': 0,
            'promovidas_f1_f2': 0,
            'promovidas_f2_f3': 0,
            'degradadas_f3_f1': 0,
            'degradadas_f2_f1': 0,
            'ejecutadas': 0,
            'canceladas': 0,
            'expiradas': 0,
            'm15_confirmadas': 0,
            'm15_contradijeron': 0,
            'm15_neutral': 0,
            'bloqueos_m15_activos': 0,
            'bloqueos_m15_aplicados': 0,
            'bloqueos_m15_expirados': 0,
            'por_motivo_degradacion': {},
        }

        if self.almacen:
            self._cargar_estados_desde_sqlite()

        self.logger.info("🔀 PipelineOportunidades V11.1 (FIX LOOP M15) inicializado")
        self.logger.info(f"   Umbrales: F1={self.umbral_fase_1} F2={self.umbral_fase_2} F3={self.umbral_fase_3}")
        self.logger.info(f"   Max edad: {max_edad_horas}h | Backtest: {modo_backtest}")
        self.logger.info(f"   Bloqueos M15: {self.DURACIONES_BLOQUEO_M15} min (escalado)")

    # ============================================================
    # CARGA DE UMBRALES
    # ============================================================

    def _cargar_umbral(self, fase: str, personalizado: Optional[float], default: float) -> float:
        if personalizado is not None:
            return float(personalizado)

        if self.config and hasattr(self.config, f'PIPELINE_UMBRAL_{fase.upper()}'):
            return float(getattr(self.config, f'PIPELINE_UMBRAL_{fase.upper()}', default))

        if Umbrales is not None:
            key = f'score_minimo_{fase}'
            if hasattr(Umbrales, 'SCORES') and key in Umbrales.SCORES:
                return float(Umbrales.SCORES[key])

        if self.modo_backtest:
            return max(5, default * 0.3)

        return default

    # ============================================================
    # ✅ V11.1: GESTIÓN DE BLOQUEOS M15
    # ============================================================

    def _registrar_bloqueo_m15(
        self,
        simbolo: str,
        direccion_h1: str,
        direccion_m15: str,
    ) -> int:
        """
        Registra (o escala) un bloqueo M15 para un símbolo.
        ✅ FIX V11.2: mantiene el historial de intentos tras expiración.
        Devuelve la duración aplicada en minutos.
        """
        info = self._m15_blocks.get(simbolo)

        if info:
            # Verificar si es la MISMA situación (misma dirección H1 + M15)
            misma_situacion = (
                info.get('direccion_h1') == direccion_h1 and
                info.get('direccion_m15') == direccion_m15
            )

            if misma_situacion:
                # Escalar: sumar al contador previo
                intentos = info.get('intentos', 1) + 1
            else:
                # Situación cambió (direcciones distintas) → resetear
                intentos = 1
                self.logger.debug(
                    f"🔄 {simbolo}: Bloqueo M15 reset (cambio de situación)"
                )
        else:
            intentos = 1

        # Duración escalada según intentos
        idx = min(intentos - 1, len(self.DURACIONES_BLOQUEO_M15) - 1)
        duracion_min = self.DURACIONES_BLOQUEO_M15[idx]

        self._m15_blocks[simbolo] = {
            'timestamp': now_utc(),
            'direccion_h1': direccion_h1,
            'direccion_m15': direccion_m15,
            'intentos': intentos,
            'duracion_min': duracion_min,
            'activo': True,   # ✅ NUEVO: flag explícito
        }

        self._stats['bloqueos_m15_aplicados'] += 1

        self.logger.warning(
            f"🔒 {simbolo}: Bloqueo M15 activado ({duracion_min} min, "
            f"intento {intentos}/{self.MAX_INTENTOS_M15}) | "
            f"H1={direccion_h1}, M15={direccion_m15}"
        )

        return duracion_min

    def _bloqueo_m15_activo(self, simbolo: str) -> bool:
        """
        Verifica si hay un bloqueo M15 activo para el símbolo.
        ✅ FIX V11.2: NO elimina el registro al expirar.
        Solo marca 'activo=False' para preservar los intentos.
        """
        info = self._m15_blocks.get(simbolo)
        if not info:
            return False

        # Si no está marcado como activo, retorna False directamente
        if not info.get('activo', True):
            return False

        minutos = (now_utc() - info['timestamp']).total_seconds() / 60
        duracion = info.get('duracion_min', 30)

        if minutos < duracion:
            return True

        # ✅ Expirado → marcar inactivo SIN eliminar (preserva intentos)
        info['activo'] = False
        self._stats['bloqueos_m15_expirados'] += 1

        self.logger.info(
            f"🔓 {simbolo}: Bloqueo M15 expirado "
            f"({minutos:.0f} min > {duracion} min) | "
            f"Intento {info.get('intentos', 1)} completado"
        )
        return False

    def limpiar_bloqueos_expirados(self):
        """
        Limpia bloqueos M15 expirados.
        ✅ FIX V11.2: solo limpia los que llevan mucho tiempo expirados
        para no perder el historial demasiado rápido.
        """
        ahora = now_utc()
        simbolos_a_borrar = []

        for simbolo, info in self._m15_blocks.items():
            # Si está activo, verificar
            if info.get('activo', True):
                self._bloqueo_m15_activo(simbolo)
                continue

            # Si está inactivo, verificar si lleva mucho tiempo
            minutos_desde_expiracion = (
                (ahora - info['timestamp']).total_seconds() / 60
                - info.get('duracion_min', 30)
            )
            # Borrar si lleva más de 24h inactivo (limpieza profunda)
            if minutos_desde_expiracion > 1440:
                simbolos_a_borrar.append(simbolo)

        for simbolo in simbolos_a_borrar:
            del self._m15_blocks[simbolo]
            self.logger.debug(f"🧹 {simbolo}: Registro M15 eliminado (24h inactivo)")

    def limpiar_bloqueo_m15(self, simbolo: str, forzar: bool = False):
        """
        Limpia manualmente el bloqueo M15.
        Si forzar=True → elimina el registro COMPLETO (reset de intentos).
        Si forzar=False → solo marca inactivo (mantiene historial).
        """
        if simbolo in self._m15_blocks:
            if forzar:
                del self._m15_blocks[simbolo]
                self.logger.info(f"🔓 {simbolo}: Bloqueo M15 eliminado (forzado - reset)")
            else:
                self._m15_blocks[simbolo]['activo'] = False
                self._m15_blocks[simbolo]['timestamp'] = now_utc() - timedelta(days=1)
                self.logger.info(f"🔓 {simbolo}: Bloqueo M15 marcado inactivo (historial preservado)")

    # ============================================================
    # PERSISTENCIA
    # ============================================================

    def _cargar_estados_desde_sqlite(self):
        if not self.almacen:
            return
        try:
            config = self.almacen.obtener_configuracion()
            pipeline_data = config.get('pipeline_estados', {})

            for simbolo, data in pipeline_data.items():
                try:
                    estado = self._deserializar_estado(simbolo, data)
                    if estado:
                        self.estados[simbolo] = estado
                except Exception as e:
                    self.logger.warning(f"⚠️ Error cargando estado {simbolo}: {e}")

            if self.estados:
                self.logger.info(f"📂 Pipeline: {len(self.estados)} estados cargados")
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando pipeline: {e}")

    def _deserializar_estado(self, simbolo: str, data: Dict) -> Optional[EstadoOportunidad]:
        if not data:
            return None

        ctx_h1 = data.get('contexto_h1') or {}
        if 'niveles' not in ctx_h1:
            ctx_h1['niveles'] = {'soportes': [], 'resistencias': []}

        return EstadoOportunidad(
            simbolo=data.get('simbolo', simbolo),
            fase_actual=FaseOportunidad(data.get('fase', 'H1_ESCANEO')),
            direccion=data.get('direccion', 'NEUTRAL'),
            score_acumulado=float(data.get('score_acumulado', 0)),
            timestamp_creacion=self._parse_datetime(data.get('timestamp_creacion')),
            timestamp_ultima_actualizacion=self._parse_datetime(data.get('timestamp_actualizacion')),
            condiciones_pendientes=data.get('condiciones_pendientes', []),
            condiciones_cumplidas=data.get('condiciones_cumplidas', []),
            analisis_h1=data.get('analisis_h1'),
            analisis_m15=data.get('analisis_m15'),
            analisis_m5=data.get('analisis_m5'),
            analisis_pesado=data.get('analisis_pesado'),
            regimen=data.get('regimen', 'UNCERTAIN'),
            direccion_regimen=data.get('direccion_regimen', 'NONE'),
            confianza_regimen=float(data.get('confianza_regimen', 0)),
            tendencia_h4=data.get('tendencia_h4', 'LATERAL'),
            calidad_horario=data.get('calidad_horario', 'REGULAR'),
            score_m15=float(data.get('score_m15', 0)),
            score_final=float(data.get('score_final', 0)),
            direccion_m15=data.get('direccion_m15', 'NEUTRAL'),
            m15_confirmo=bool(data.get('m15_confirmo', False)),
            contexto_h1=ctx_h1,
            contexto_m15=data.get('contexto_m15') or {},
            contexto_m5=data.get('contexto_m5') or {},
            intentos_promocion=int(data.get('intentos_promocion', 0)),
            ultimo_error=data.get('ultimo_error'),
            metadata=data.get('metadata', {}),
            degradaciones=data.get('degradaciones', []),
        )

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        return now_utc()

    def _guardar_estados_en_sqlite(self):
        if not self.almacen:
            return
        try:
            config = self.almacen.obtener_configuracion()
            pipeline_data = {}
            for simbolo, estado in self.estados.items():
                pipeline_data[simbolo] = estado.to_dict()
            config['pipeline_estados'] = pipeline_data
            self.almacen.guardar_configuracion(config)
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando pipeline: {e}")

    # ============================================================
    # FASE 1
    # ============================================================

    def actualizar_fase_1(
        self,
        simbolo: str,
        analisis: Dict,
        score: float,
        direccion: str,
        regimen: str = 'UNCERTAIN',
        direccion_regimen: str = 'NONE',
        confianza_regimen: float = 0,
        tendencia_h4: str = 'LATERAL',
        contexto_h1: Optional[Dict] = None,
        analisis_pesado: Optional[Dict] = None,
    ) -> Optional[EstadoOportunidad]:
        try:
            score_min = self.umbral_fase_1 * 0.5
            if score < score_min:
                self.logger.debug(f"⏭️ {simbolo}: Score bajo ({score:.1f} < {score_min:.1f})")
                return None

            if not self._cooldown_ok(simbolo):
                self.logger.debug(f"⏳ {simbolo}: En cooldown post-degradación")
                return None

            estado = self.estados.get(simbolo)

            if estado is None:
                estado = self._crear_estado(
                    simbolo, analisis, score, direccion, regimen,
                    direccion_regimen, confianza_regimen, tendencia_h4,
                    contexto_h1, analisis_pesado,
                )
                self.estados[simbolo] = estado
                self._stats['creadas'] += 1
                self.logger.info(f"📝 {simbolo}: Nueva oportunidad en F1 (score: {score:.1f}, dir: {direccion})")
            else:
                if estado.fase_actual.es_terminal():
                    return estado

                self._actualizar_estado_h1(
                    estado, analisis, score, direccion, regimen,
                    direccion_regimen, confianza_regimen, tendencia_h4,
                    contexto_h1, analisis_pesado,
                )

            self._evaluar_promocion_f1_f2(estado)
            self._guardar_estados_en_sqlite()
            return estado

        except Exception as e:
            self.logger.error(f"❌ Error en actualizar_fase_1({simbolo}): {e}", exc_info=True)
            return None

    def _crear_estado(
        self, simbolo, analisis, score, direccion, regimen,
        direccion_regimen, confianza_regimen, tendencia_h4,
        contexto_h1, analisis_pesado,
    ) -> EstadoOportunidad:
        ahora = now_utc()
        return EstadoOportunidad(
            simbolo=simbolo,
            fase_actual=FaseOportunidad.FASE_1,
            direccion=direccion,
            score_acumulado=score,
            timestamp_creacion=ahora,
            timestamp_ultima_actualizacion=ahora,
            analisis_h1=analisis,
            analisis_pesado=analisis_pesado,
            regimen=regimen,
            direccion_regimen=direccion_regimen,
            confianza_regimen=confianza_regimen,
            tendencia_h4=tendencia_h4,
            contexto_h1=contexto_h1 if contexto_h1 is not None else {},
        )

    def _actualizar_estado_h1(
        self, estado, analisis, score, direccion, regimen,
        direccion_regimen, confianza_regimen, tendencia_h4,
        contexto_h1, analisis_pesado,
    ):
        if contexto_h1:
            if estado.contexto_h1 is None:
                estado.contexto_h1 = {}
            if 'niveles' not in contexto_h1 and 'niveles' in estado.contexto_h1:
                contexto_h1 = {**contexto_h1, 'niveles': estado.contexto_h1['niveles']}
            estado.contexto_h1.update(contexto_h1)

        estado.analisis_h1 = analisis
        estado.analisis_pesado = analisis_pesado
        estado.direccion = direccion
        estado.regimen = regimen
        estado.direccion_regimen = direccion_regimen
        estado.confianza_regimen = confianza_regimen
        estado.tendencia_h4 = tendencia_h4
        estado.timestamp_ultima_actualizacion = now_utc()

        if score > estado.score_acumulado:
            estado.score_acumulado = score

    # ============================================================
    # PROMOCIÓN F1 → F2 (✅ V11.1: con verificación de bloqueos)
    # ============================================================

    def _evaluar_promocion_f1_f2(self, estado: EstadoOportunidad):
        if estado.fase_actual != FaseOportunidad.FASE_1:
            return

        # ✅ V11.1: verificar cooldown post-degradación
        if not self._cooldown_ok(estado.simbolo):
            self.logger.debug(
                f"⏳ {estado.simbolo}: Promoción bloqueada por cooldown"
            )
            return

        # ✅ V11.1: verificar bloqueo M15
        if self._bloqueo_m15_activo(estado.simbolo):
            info = self._m15_blocks.get(estado.simbolo, {})
            minutos_restantes = info.get('duracion_min', 30) - int(
                (now_utc() - info.get('timestamp', now_utc())).total_seconds() / 60
            )
            self.logger.debug(
                f"🔒 {estado.simbolo}: Promoción bloqueada por M15 "
                f"({minutos_restantes} min restantes)"
            )
            return

        # Criterios de promoción
        criterios = {
            'score_suficiente': estado.score_acumulado >= self.umbral_fase_2,
            'direccion_valida': estado.direccion in ('COMPRA', 'VENTA'),
            'regimen_valido': estado.regimen not in ('CHOP_VOLATIL', 'INCERTO'),
        }

        if self.modo_backtest:
            criterios['regimen_valido'] = True

        if all(criterios.values()):
            estado.fase_actual = FaseOportunidad.FASE_2
            estado.agregar_condicion("Score_Fase2")
            estado.agregar_condicion("M15_Confirmacion")
            estado.timestamp_ultima_actualizacion = now_utc()
            self._stats['promovidas_f1_f2'] += 1

            self.logger.info(
                f"⬆️ {estado.simbolo}: PROMOVIDO F1→F2 "
                f"(score: {estado.score_acumulado:.1f}, dir: {estado.direccion}, rég: {estado.regimen})"
            )
        else:
            fallidos = [k for k, v in criterios.items() if not v]
            self.logger.debug(
                f"⏳ {estado.simbolo}: No promueve a F2 "
                f"(score: {estado.score_acumulado:.1f}, falla: {fallidos})"
            )

    # ============================================================
    # FASE 2: M15_CONFIRMACION (con registro de bloqueo V11.1)
    # ============================================================

    def actualizar_fase_2(
        self,
        simbolo: str,
        analisis_m15: Dict,
        score: float,
    ) -> Optional[EstadoOportunidad]:
        estado = self.estados.get(simbolo)
        if not estado or estado.fase_actual.es_terminal():
            return estado

        estado.metadata['intentos_fase2'] = estado.metadata.get('intentos_fase2', 0) + 1

        calidad = self._calcular_calidad(estado)
        limite = self.LIMITES_INTENTOS_POR_CALIDAD.get(calidad, 3)
        if estado.metadata['intentos_fase2'] > limite:
            self._degradar_oportunidad(
                simbolo,
                razon=f"Exceso de intentos F2 ({estado.metadata['intentos_fase2']} > {limite})",
                motivo=MotivoDegradacion.SCORE_INSUFICIENTE,
            )
            return estado

        estado.analisis_m15 = analisis_m15
        estado.score_m15 = max(estado.score_m15, score)
        estado.score_acumulado = max(estado.score_acumulado, score)
        estado.timestamp_ultima_actualizacion = now_utc()

        # Dirección real de M15
        direccion_m15 = analisis_m15.get('direccion', 'NEUTRAL')
        estado.direccion_m15 = direccion_m15

        # ============================================================
        # Lógica M15_Confirmacion
        # ============================================================
        if direccion_m15 == estado.direccion:
            # M15 confirma H1
            estado.m15_confirmo = True
            estado.cumplir_condicion("M15_Confirmacion")
            self._stats['m15_confirmadas'] += 1

            # ✅ V11.1: si hay bloqueo previo y ahora confirma → limpiarlo
            if simbolo in self._m15_blocks:
                self.logger.info(
                    f"🔓 {simbolo}: M15 ahora CONFIRMA {estado.direccion} "
                    f"→ limpiando bloqueo previo"
                )
                del self._m15_blocks[simbolo]

            self.logger.info(
                f"✅ {simbolo}: M15 CONFIRMA {estado.direccion} "
                f"(score_m15: {score:.1f})"
            )

        elif direccion_m15 == 'NEUTRAL':
            # M15 neutral → continuar pero marcar
            self._stats['m15_neutral'] += 1
            estado.metadata['m15_neutral'] = True
            self.logger.debug(
                f"⚠️ {simbolo}: M15 NEUTRAL (score: {score:.1f}) - continúa con cautela"
            )

        else:
            # ✅ V11.1: M15 CONTRADICE → degradar CON BLOQUEO
            self._stats['m15_contradijeron'] += 1
            self.logger.warning(
                f"❌ {simbolo}: M15 CONTRADICE H1 "
                f"(H1={estado.direccion}, M15={direccion_m15}) → DEGRADAR + BLOQUEO"
            )
            self._degradar_oportunidad(
                simbolo,
                razon=f"M15 contradice H1 ({direccion_m15} vs {estado.direccion})",
                motivo=MotivoDegradacion.M15_CONTRADICE,
            )
            return estado

        if score >= self.umbral_fase_2:
            estado.cumplir_condicion("Score_Fase2")

        self._evaluar_promocion_f2_f3(estado)
        self._guardar_estados_en_sqlite()
        return estado

    # ============================================================
    # PROMOCIÓN F2 → F3
    # ============================================================

    def _evaluar_promocion_f2_f3(self, estado: EstadoOportunidad):
        if estado.fase_actual != FaseOportunidad.FASE_2:
            return

        # ✅ V11.1: verificar cooldown y bloqueo M15
        if not self._cooldown_ok(estado.simbolo):
            return
        if self._bloqueo_m15_activo(estado.simbolo):
            return

        score_ok = estado.score_acumulado >= self.umbral_fase_3
        tiene_m15 = 'M15_Confirmacion' in estado.condiciones_cumplidas
        direccion_ok = estado.direccion in ('COMPRA', 'VENTA')

        if self.modo_backtest:
            tiene_m15 = tiene_m15 or estado.score_acumulado >= self.umbral_fase_3 * 1.2

        if score_ok and direccion_ok and tiene_m15:
            estado.fase_actual = FaseOportunidad.FASE_3
            estado.agregar_condicion("Score_Fase3")
            estado.agregar_condicion("M5_Sniper")
            estado.timestamp_ultima_actualizacion = now_utc()
            self._stats['promovidas_f2_f3'] += 1
            self.logger.info(
                f"⬆️ {estado.simbolo}: PROMOVIDO F2→F3 "
                f"(score: {estado.score_acumulado:.1f}, M15_confirmo: {estado.m15_confirmo})"
            )
        else:
            self.logger.debug(
                f"⏳ {estado.simbolo}: No promueve a F3 "
                f"(score: {estado.score_acumulado:.1f}, m15_ok: {tiene_m15})"
            )

    # ============================================================
    # FASE 3
    # ============================================================

    def actualizar_fase_3(
        self,
        simbolo: str,
        analisis_m5: Dict,
        score: float,
    ):
        estado = self.estados.get(simbolo)
        if not estado or estado.fase_actual.es_terminal():
            return estado

        estado.metadata['intentos_sniper'] = estado.metadata.get('intentos_sniper', 0) + 1

        calidad = self._calcular_calidad(estado)
        limite = self.LIMITES_INTENTOS_POR_CALIDAD.get(calidad, 5)

        if estado.metadata['intentos_sniper'] > limite:
            self._degradar_oportunidad(
                simbolo,
                razon=f"Exceso de intentos F3 ({estado.metadata['intentos_sniper']} > {limite})",
                motivo=MotivoDegradacion.SNIPER_FALLOS,
            )
            return estado

        if score < self.umbral_fase_3 * 0.5:
            if calidad < 3:
                self._degradar_oportunidad(
                    simbolo,
                    razon=f"Score F3 bajo ({score:.1f}) y calidad baja ({calidad}/4)",
                    motivo=MotivoDegradacion.SCORE_INSUFICIENTE,
                )
            else:
                estado.metadata['esperando_condicion'] = True
            return estado

        estado.analisis_m5 = analisis_m5
        estado.score_final = max(estado.score_final, score)
        estado.score_acumulado = max(estado.score_acumulado, score)
        estado.timestamp_ultima_actualizacion = now_utc()

        if score >= self.umbral_fase_3:
            estado.cumplir_condicion("Score_Fase3")
            estado.cumplir_condicion("M5_Sniper")

        self._guardar_estados_en_sqlite()
        return estado

    # ============================================================
    # DEGRADACIÓN (con registro de bloqueo V11.1)
    # ============================================================

    def _degradar_oportunidad(
        self,
        simbolo: str,
        razon: str = "",
        motivo: str = MotivoDegradacion.MANUAL,
    ):
        estado = self.estados.get(simbolo)
        if not estado:
            return

        fase_origen = estado.fase_actual

        if fase_origen == FaseOportunidad.FASE_3:
            self._stats['degradadas_f3_f1'] += 1
        elif fase_origen == FaseOportunidad.FASE_2:
            self._stats['degradadas_f2_f1'] += 1

        self._stats['por_motivo_degradacion'][motivo] = \
            self._stats['por_motivo_degradacion'].get(motivo, 0) + 1

        estado.registrar_degradacion(motivo, razon, fase_origen)

        estado.fase_actual = FaseOportunidad.FASE_1
        estado.ultimo_error = razon
        estado.condiciones_pendientes = []
        estado.condiciones_cumplidas = []
        estado.timestamp_ultima_actualizacion = now_utc()

        # Resetear tracking M15
        estado.m15_confirmo = False
        # ⚠️ NO resetear direccion_m15 para auditoría

        if fase_origen == FaseOportunidad.FASE_3:
            estado.metadata['intentos_sniper'] = 0
            estado.metadata['sniper_fallos'] = 0
        elif fase_origen == FaseOportunidad.FASE_2:
            estado.metadata['intentos_fase2'] = 0

        # Cooldown general
        self._cooldowns[simbolo] = now_utc() + \
            timedelta(minutes=self.COOLDOWN_DEGRADACION_MINUTOS)

        # ✅ V11.1: bloqueo M15 si el motivo lo amerita
        if motivo == MotivoDegradacion.M15_CONTRADICE:
            direccion_h1 = estado.direccion
            direccion_m15 = estado.direccion_m15
            duracion = self._registrar_bloqueo_m15(simbolo, direccion_h1, direccion_m15)

            self.logger.info(
                f"⬇️ {simbolo}: DEGRADADO {fase_origen.value} → F1 "
                f"[{motivo}] {razon} | Bloqueo M15: {duracion} min"
            )
        else:
            self.logger.info(
                f"⬇️ {simbolo}: DEGRADADO {fase_origen.value} → F1 "
                f"[{motivo}] {razon}"
            )

        self._guardar_estados_en_sqlite()

    # ============================================================
    # PROMOCIÓN AUTOMÁTICA
    # ============================================================

    def _promover_automaticamente(self, simbolo: str):
        estado = self.estados.get(simbolo)
        if not estado or estado.fase_actual.es_terminal():
            return

        # ✅ V11.1: cooldown y bloqueo verificados dentro de _evaluar
        if estado.fase_actual == FaseOportunidad.FASE_1:
            self._evaluar_promocion_f1_f2(estado)
        elif estado.fase_actual == FaseOportunidad.FASE_2:
            self._evaluar_promocion_f2_f3(estado)

    def promover_automaticamente(self):
        if not self.estados:
            return

        # ✅ V11.1: limpiar bloqueos expirados primero
        self.limpiar_bloqueos_expirados()

        activos = self.obtener_activos()
        f1 = sum(1 for e in activos if e.fase_actual == FaseOportunidad.FASE_1)
        f2 = sum(1 for e in activos if e.fase_actual == FaseOportunidad.FASE_2)
        f3 = sum(1 for e in activos if e.fase_actual == FaseOportunidad.FASE_3)

        self.logger.debug(
            f"🔄 Promoviendo: F1:{f1} F2:{f2} F3:{f3} | "
            f"Bloqueos M15: {len(self._m15_blocks)}"
        )

        for simbolo in list(self.estados.keys()):
            estado = self.estados.get(simbolo)
            if not estado or estado.fase_actual.es_terminal():
                continue
            self._promover_automaticamente(simbolo)

        self._guardar_estados_en_sqlite()

    # ============================================================
    # DEGRADACIÓN POR TIEMPO
    # ============================================================

    def degradar_por_tiempo(self):
        ahora = now_utc()

        for simbolo, estado in list(self.estados.items()):
            if estado.fase_actual.es_terminal():
                continue

            limite = self.LIMITES_TIEMPO_FASE.get(estado.fase_actual)
            if not limite:
                continue

            horas = (ahora - estado.timestamp_ultima_actualizacion).total_seconds() / 3600

            if horas > limite:
                self._degradar_oportunidad(
                    simbolo,
                    razon=f"Tiempo excedido en {estado.fase_actual.value} ({horas:.1f}h > {limite}h)",
                    motivo=MotivoDegradacion.TIEMPO_EXCEDIDO,
                )

    # ============================================================
    # CALIDAD
    # ============================================================

    def _calcular_calidad(self, estado: EstadoOportunidad) -> int:
        calidad = 0

        if 'Score_Fase1' in estado.condiciones_cumplidas:
            calidad += 1
        if 'Direccion_Definida' in estado.condiciones_cumplidas:
            calidad += 1
        if 'Score_Fase2' in estado.condiciones_cumplidas:
            calidad += 1
        if estado.m15_confirmo:
            calidad += 1

        if estado.regimen in ('TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE'):
            calidad += 1
        if estado.score_acumulado >= 80:
            calidad += 1

        return min(4, max(0, calidad))

    # ============================================================
    # COOLDOWNS
    # ============================================================

    def _cooldown_ok(self, simbolo: str) -> bool:
        hasta = self._cooldowns.get(simbolo)
        if not hasta:
            return True
        if now_utc() >= hasta:
            del self._cooldowns[simbolo]
            return True
        return False

    # ============================================================
    # ESTADOS TERMINALES
    # ============================================================

    def marcar_ejecutada(self, simbolo: str):
        estado = self.estados.get(simbolo)
        if estado:
            estado.fase_actual = FaseOportunidad.EJECUTADA
            estado.timestamp_ultima_actualizacion = now_utc()
            self._stats['ejecutadas'] += 1
            self.logger.info(f"✅ {simbolo}: EJECUTADA")

            # ✅ V11.1: limpiar bloqueo al ejecutar
            if simbolo in self._m15_blocks:
                del self._m15_blocks[simbolo]

        self._guardar_estados_en_sqlite()

    def marcar_cancelada(self, simbolo: str, razon: str = ""):
        estado = self.estados.get(simbolo)
        if estado:
            estado.fase_actual = FaseOportunidad.CANCELADA
            estado.timestamp_ultima_actualizacion = now_utc()
            estado.ultimo_error = razon
            self._stats['canceladas'] += 1
            self.logger.info(f"❌ {simbolo}: CANCELADA ({razon})")
        self._guardar_estados_en_sqlite()

    def liberar_simbolo(self, simbolo: str):
        if simbolo in self.estados:
            del self.estados[simbolo]
            self._cooldowns.pop(simbolo, None)
            self._m15_blocks.pop(simbolo, None)
        self._guardar_estados_en_sqlite()

    # ============================================================
    # CONSULTAS
    # ============================================================

    def obtener_estado(self, simbolo: str) -> Optional[EstadoOportunidad]:
        return self.estados.get(simbolo)

    def obtener_todos_estados(self) -> List[EstadoOportunidad]:
        return list(self.estados.values())

    def obtener_activos(self) -> List[EstadoOportunidad]:
        return [e for e in self.estados.values() if e.fase_actual.es_activa()]

    def obtener_fase_3(self) -> List[EstadoOportunidad]:
        return [e for e in self.estados.values() if e.fase_actual == FaseOportunidad.FASE_3]

    def obtener_por_fase(self, fase: FaseOportunidad) -> List[EstadoOportunidad]:
        return [e for e in self.estados.values() if e.fase_actual == fase]

    def obtener_priorizados(self, max_resultados: int = 10) -> List[EstadoOportunidad]:
        activos = self.obtener_activos()
        activos.sort(
            key=lambda e: (e.score_acumulado, self._fase_orden(e.fase_actual)),
            reverse=True,
        )
        return activos[:max_resultados]

    def _fase_orden(self, fase: FaseOportunidad) -> int:
        return {
            FaseOportunidad.FASE_1: 1,
            FaseOportunidad.FASE_2: 2,
            FaseOportunidad.FASE_3: 3,
        }.get(fase, 0)

    def existe_oportunidad(self, simbolo: str) -> bool:
        return simbolo in self.estados

    def es_activa(self, simbolo: str) -> bool:
        estado = self.estados.get(simbolo)
        return estado is not None and estado.fase_actual.es_activa()

    # ============================================================
    # LIMPIEZA
    # ============================================================

    def limpiar_antiguos(self, horas: Optional[int] = None) -> int:
        if horas is None:
            horas = self.max_edad_horas

        ahora = now_utc()
        to_remove: List[str] = []

        for simbolo, estado in self.estados.items():
            edad = (ahora - estado.timestamp_creacion).total_seconds() / 3600

            if edad > horas:
                to_remove.append(simbolo)
                self._stats['expiradas'] += 1
                continue

            if estado.fase_actual.es_terminal():
                edad_terminal = (ahora - estado.timestamp_ultima_actualizacion).total_seconds() / 3600
                if edad_terminal > 1:
                    to_remove.append(simbolo)

        for simbolo in to_remove:
            self.estados.pop(simbolo, None)
            self._cooldowns.pop(simbolo, None)
            self._m15_blocks.pop(simbolo, None)

        if to_remove:
            self.logger.info(f"🧹 {len(to_remove)} oportunidades eliminadas")
            self._guardar_estados_en_sqlite()

        return len(to_remove)

    # ============================================================
    # ESTADÍSTICAS
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        stats = self._stats.copy()
        stats['total_estados'] = len(self.estados)
        stats['activos'] = len(self.obtener_activos())
        stats['por_fase'] = {
            fase.value: len(self.obtener_por_fase(fase))
            for fase in FaseOportunidad
        }
        stats['cooldowns_activos'] = len(self._cooldowns)
        stats['bloqueos_m15_activos'] = len(self._m15_blocks)

        # Info de bloqueos
        stats['bloqueos_m15_detalle'] = {
            simbolo: {
                'intentos': info.get('intentos', 1),
                'duracion_min': info.get('duracion_min', 30),
                'h1': info.get('direccion_h1'),
                'm15': info.get('direccion_m15'),
                'minutos_transcurridos': round(
                    (now_utc() - info['timestamp']).total_seconds() / 60, 1
                ) if info.get('timestamp') else 0,
            }
            for simbolo, info in self._m15_blocks.items()
        }

        return stats

    def print_stats(self):
        stats = self.get_stats()
        print("\n" + "=" * 60)
        print("📊 ESTADÍSTICAS DEL PIPELINE V11.1")
        print("=" * 60)
        print(f"Total estados: {stats['total_estados']}")
        print(f"Activos: {stats['activos']}")
        print(f"Cooldowns: {stats['cooldowns_activos']}")
        print(f"Bloqueos M15 activos: {stats['bloqueos_m15_activos']}")
        print(f"\nTransiciones:")
        print(f"  F1→F2: {stats['promovidas_f1_f2']}")
        print(f"  F2→F3: {stats['promovidas_f2_f3']}")
        print(f"  M15 confirmó: {stats['m15_confirmadas']}")
        print(f"  M15 contradijo: {stats['m15_contradijeron']}")
        print(f"  M15 neutral: {stats['m15_neutral']}")
        print(f"  F3→F1: {stats['degradadas_f3_f1']}")
        print(f"  F2→F1: {stats['degradadas_f2_f1']}")
        print(f"  Ejecutadas: {stats['ejecutadas']}")

        if stats['bloqueos_m15_activos'] > 0:
            print(f"\n🔒 Bloqueos M15 activos:")
            for simbolo, info in stats['bloqueos_m15_detalle'].items():
                print(
                    f"  {simbolo}: intento {info['intentos']}, "
                    f"{info['duracion_min']}min, "
                    f"H1={info['h1']}, M15={info['m15']}, "
                    f"transcurrido {info['minutos_transcurridos']}min"
                )

        if stats['por_motivo_degradacion']:
            print(f"\nDegradaciones por motivo:")
            for motivo, count in stats['por_motivo_degradacion'].items():
                print(f"  {motivo}: {count}")
        print("=" * 60)


# ============================================================
# FACTORY
# ============================================================

def create_pipeline(
    config: Optional[Any] = None,
    umbral_fase_1: Optional[float] = None,
    umbral_fase_2: Optional[float] = None,
    umbral_fase_3: Optional[float] = None,
    modo_backtest: bool = False,
    almacen: Optional[Any] = None,
) -> PipelineOportunidades:
    return PipelineOportunidades(
        config=config,
        umbral_fase_1=umbral_fase_1,
        umbral_fase_2=umbral_fase_2,
        umbral_fase_3=umbral_fase_3,
        modo_backtest=modo_backtest,
        almacen=almacen,
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    if str(Path(__file__).parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent.parent))

    print("🧪 Probando PipelineOportunidades V11.1 (fix loop)...")

    p = PipelineOportunidades(modo_backtest=True)

    # ============================================================
    # TEST 1: Flujo normal (M15 confirma)
    # ============================================================
    print("\n[TEST 1] Flujo normal M15 confirma")
    p.actualizar_fase_1(
        simbolo='EURUSD',
        analisis={'test': True},
        score=65,
        direccion='COMPRA',
        regimen='TREND_ALCISTA_FUERTE',
    )
    estado = p.actualizar_fase_2(
        'EURUSD',
        {'direccion': 'COMPRA', 'score': 70, 'adx': 25},
        score=70,
    )
    assert estado.fase_actual.value == 'M5_SNIPER', f"❌ F1: {estado.fase_actual}"
    print(f"   ✅ EURUSD en {estado.fase_actual.value}")

    # ============================================================
    # TEST 2: M15 contradice (1ª vez) → degrada + bloqueo 30 min
    # ============================================================
    print("\n[TEST 2] M15 contradice (1ª vez)")
    p.actualizar_fase_1(
        simbolo='ETHUSD',
        analisis={'test': True},
        score=85,
        direccion='VENTA',
        regimen='TREND_BAJISTA_FUERTE',
    )
    estado = p.actualizar_fase_2(
        'ETHUSD',
        {'direccion': 'COMPRA', 'score': 70},
        score=70,
    )
    assert estado.fase_actual.value == 'H1_ESCANEO', f"❌ F2: {estado.fase_actual}"
    assert 'M15 contradice' in estado.ultimo_error
    assert 'ETHUSD' in p._m15_blocks
    assert p._m15_blocks['ETHUSD']['duracion_min'] == 30
    print(f"   ✅ ETHUSD degradado + bloqueo 30min")

    # ============================================================
    # TEST 3: Intento de re-promover → bloqueado
    # ============================================================
    print("\n[TEST 3] Intento de re-promover (bloqueado)")
    # Simular 5 ciclos intentando re-promover
    for i in range(5):
        p._evaluar_promocion_f1_f2(estado)

    estado = p.estados.get('ETHUSD')
    assert estado.fase_actual.value == 'H1_ESCANEO', f"❌ Debería seguir en F1: {estado.fase_actual}"
    print(f"   ✅ ETHUSD sigue en {estado.fase_actual.value}")

     # ============================================================
    # TEST 4: Bloqueo expirado (ahora marca inactivo, no elimina)
    # ============================================================
    print("\n[TEST 4] Bloqueo expirado")
    # Hacer que el bloqueo parezca expirado
    p._m15_blocks['ETHUSD']['timestamp'] = now_utc() - timedelta(minutes=45)

    activo = p._bloqueo_m15_activo('ETHUSD')
    assert activo is False, "❌ Debería estar expirado"

    # ✅ NUEVO COMPORTAMIENTO: el registro se preserva con activo=False
    assert 'ETHUSD' in p._m15_blocks, "❌ El registro debería preservarse"
    assert p._m15_blocks['ETHUSD']['activo'] is False, "❌ Debería estar inactivo"
    assert p._m15_blocks['ETHUSD']['intentos'] == 1, "❌ Debería tener 1 intento"
    print(f"   ✅ Bloqueo expirado pero historial preservado (intentos=1)")

    # ============================================================
    # TEST 5: M15 ahora confirma → limpiar bloqueo
    # ============================================================
    print("\n[TEST 5] M15 ahora confirma (limpia bloqueo)")
    p.actualizar_fase_1(
        simbolo='GBPUSD',
        analisis={'test': True},
        score=85,
        direccion='COMPRA',
        regimen='TREND_ALCISTA_FUERTE',
    )
    # Primero M15 contradice
    p.actualizar_fase_2(
        'GBPUSD',
        {'direccion': 'VENTA', 'score': 70},
        score=70,
    )
    assert 'GBPUSD' in p._m15_blocks
    print(f"   ✅ Bloqueo creado")

    # Simular expiración del cooldown
    if 'GBPUSD' in p._cooldowns:
        del p._cooldowns['GBPUSD']
    if 'GBPUSD' in p._m15_blocks:
        p._m15_blocks['GBPUSD']['timestamp'] = now_utc() - timedelta(hours=1)

    # Re-promover
    p._evaluar_promocion_f1_f2(p.estados['GBPUSD'])
    assert p.estados['GBPUSD'].fase_actual.value == 'M15_CONFIRMACION'
    print(f"   ✅ GBPUSD re-promovido a F2")

    # Ahora M15 confirma
    estado = p.actualizar_fase_2(
        'GBPUSD',
        {'direccion': 'COMPRA', 'score': 75},
        score=75,
    )
    assert 'GBPUSD' not in p._m15_blocks, "❌ Debería haberse limpiado"
    print(f"   ✅ Bloqueo limpiado tras confirmación")

    # ============================================================
    # TEST 6: Escalado (2ª contradicción → 60 min)
    # ============================================================
    print("\n[TEST 6] Escalado de bloqueos")
    p2 = PipelineOportunidades(modo_backtest=True)

    p2.actualizar_fase_1('XAUUSD', {}, 85, 'VENTA', 'TREND_BAJISTA_FUERTE')
    p2.actualizar_fase_2('XAUUSD', {'direccion': 'COMPRA', 'score': 70}, score=70)
    dur1 = p2._m15_blocks['XAUUSD']['duracion_min']
    intentos1 = p2._m15_blocks['XAUUSD']['intentos']
    print(f"   1ª contradicción → {dur1} min (intento {intentos1})")
    assert dur1 == 30, f"❌ 1ª debería ser 30: {dur1}"
    assert intentos1 == 1, f"❌ intentos1 debería ser 1: {intentos1}"

    # Simular expiración del bloqueo
    p2._m15_blocks['XAUUSD']['timestamp'] = now_utc() - timedelta(hours=1)
    p2._cooldowns.clear()
    p2._bloqueo_m15_activo('XAUUSD')  # marca inactivo

    # 2ª contradicción
    p2._evaluar_promocion_f1_f2(p2.estados['XAUUSD'])
    p2.actualizar_fase_2('XAUUSD', {'direccion': 'COMPRA', 'score': 70}, score=70)
    dur2 = p2._m15_blocks['XAUUSD']['duracion_min']
    intentos2 = p2._m15_blocks['XAUUSD']['intentos']
    print(f"   2ª contradicción → {dur2} min (intento {intentos2})")

    assert intentos2 == 2, f"❌ intentos2 debería ser 2: {intentos2}"
    assert dur2 == 60, f"❌ Debería escalar a 60: {dur2}"
    print(f"   ✅ Escalado correcto (30 → 60 min)")
    # ============================================================
    # TEST 7: Limpiar bloqueo (forzado)
    # ============================================================
    print("\n[TEST 7] Limpiar bloqueo forzado")
    assert 'XAUUSD' in p2._m15_blocks, "❌ Debería existir el bloqueo"
    p2.limpiar_bloqueo_m15('XAUUSD', forzar=True)
    assert 'XAUUSD' not in p2._m15_blocks, "❌ Debería haberse eliminado"
    print(f"   ✅ Bloqueo eliminado forzado (reset completo)")
    # ============================================================
    # TEST 8: Limpiar bloqueo (sin forzar) → preserva historial
    # ============================================================
    print("\n[TEST 8] Limpiar bloqueo sin forzar (preserva historial)")
    p3 = PipelineOportunidades(modo_backtest=True)
    p3.actualizar_fase_1('GBPJPY', {}, 85, 'VENTA', 'TREND_BAJISTA_FUERTE')
    p3.actualizar_fase_2('GBPJPY', {'direccion': 'COMPRA', 'score': 70}, score=70)
    assert 'GBPJPY' in p3._m15_blocks
    assert p3._m15_blocks['GBPJPY']['intentos'] == 1

    p3.limpiar_bloqueo_m15('GBPJPY', forzar=False)
    assert 'GBPJPY' in p3._m15_blocks, "❌ El registro debería preservarse"
    assert p3._m15_blocks['GBPJPY']['activo'] is False
    assert p3._m15_blocks['GBPJPY']['intentos'] == 1, "❌ Debería mantener intentos"
    print(f"   ✅ Historial preservado (intentos=1)")
    # ============================================================
    # Stats
    # ============================================================
    print("\n[Stats finales]")
    stats = p.get_stats()
    print(f"   Bloqueos aplicados: {stats['bloqueos_m15_aplicados']}")
    print(f"   Bloqueos expirados: {stats['bloqueos_m15_expirados']}")
    print(f"   M15 contradijeron: {stats['m15_contradijeron']}")
    print(f"   Bloqueos activos: {stats['bloqueos_m15_activos']}")

    # Print completo
    p.print_stats()

    print("\n✅ Todas las pruebas pasan (fix loop OK)")