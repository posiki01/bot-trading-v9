#!/usr/bin/env python3
"""
trading/riesgo_circuit.py (V10.0 - REFACTORIZADO)
Circuit Breaker con análisis post-mortem y reactivación gradual.

MEJORAS V10.0:
- ✅ Bloqueo por SCOPE: GLOBAL, SIMBOLO, REGIMEN, SESION, MODO
- ✅ Análisis post-mortem: detecta patrones en las últimas pérdidas
- ✅ Reactivación gradual: 50% → 100% tras N ganadoras consecutivas
- ✅ Persistencia con SQLite
- ✅ Interfaz compatible con la versión anterior
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from dataclasses import dataclass, field
from utils.reloj import now_utc

logger = logging.getLogger('BotTrading.RiesgoCircuit')


# ============================================================
# ENUMS Y DATACLASSES
# ============================================================

class ScopeBloqueo(Enum):
    """Alcance del bloqueo."""
    GLOBAL = "GLOBAL"       # Bloquea todo
    SIMBOLO = "SIMBOLO"     # Bloquea solo un símbolo
    REGIMEN = "REGIMEN"     # Bloquea operaciones en un régimen
    SESION = "SESION"       # Bloquea operaciones en una sesión
    MODO = "MODO"           # Bloquea operaciones en un modo específico


@dataclass
class AnalisisPostMortem:
    """Resultado del análisis post-mortem."""
    patron_dominante: Optional[str] = None
    scope_recomendado: ScopeBloqueo = ScopeBloqueo.GLOBAL
    scope_valor: str = ""
    razon: str = ""
    detalles: Dict[str, Any] = field(default_factory=dict)
    simbolos: List[str] = field(default_factory=list)
    regimenes: List[str] = field(default_factory=list)
    sesiones: List[str] = field(default_factory=list)
    modos: List[str] = field(default_factory=list)


@dataclass
class EstadoReactivacion:
    """Estado de la reactivación gradual."""
    activa: bool = False
    factor_riesgo: float = 1.0     # 1.0 = normal, 0.5 = reactivando
    ganadoras_consecutivas: int = 0
    perdidas_en_reactivacion: int = 0
    operaciones_desde_reactivacion: int = 0


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class CircuitBreaker:
    """
    Circuit Breaker con análisis post-mortem y reactivación gradual.
    V10.0 - REFACTORIZADO.
    """

    # ============================================================
    # CONFIGURACIÓN
    # ============================================================

    # Cuántas operaciones consecutivas considerar para post-mortem
    N_OPS_ANALIZAR = 10

    # Umbral para considerar un "patrón dominante" (ej: 70% mismo símbolo)
    UMBRAL_PATRON_PCT = 60

    # Reactivación gradual
    FACTOR_REACTIVACION = 0.5      # Arranca al 50%
    GANADORAS_PARA_100 = 3          # 3 ganadoras → 100%
    PERDIDAS_EN_REACTIVACION = 1    # 1 pérdida → pausa de nuevo

    def __init__(
        self,
        config: Optional[Any] = None,
        almacen: Optional[Any] = None,
        notificador: Optional[Any] = None,
    ):
        self.config = config
        self.almacen = almacen
        self.notificador = notificador
        self.logger = logging.getLogger('BotTrading.RiesgoCircuit')

        # Estado activo
        self.activo = False
        self.hasta: Optional[datetime] = None
        self.motivo: str = ""
        self.scope: ScopeBloqueo = ScopeBloqueo.GLOBAL
        self.scope_valor: str = ""

        # Reactivación
        self.reactivacion = EstadoReactivacion()

        # Último post-mortem
        self.ultimo_post_mortem: Optional[AnalisisPostMortem] = None

        # Cargar config
        self._cargar_configuracion()

        # Restaurar estado persistido
        self._restaurar_estado()

    def _cargar_configuracion(self):
        """Carga config."""
        if self.config:
            self.cooldown_horas = getattr(self.config, 'CIRCUIT_BREAKER_COOLDOWN_HOURS', 24)
            self.max_consecutive_losses = getattr(self.config, 'MAX_CONSECUTIVE_LOSSES', 3)
            self.max_daily_drawdown = getattr(self.config, 'MAX_DAILY_DRAWDOWN_PCT', 0.06)
            self.es_demo = getattr(self.config, 'MT5_DEMO', True)
        else:
            self.cooldown_horas = 24
            self.max_consecutive_losses = 3
            self.max_daily_drawdown = 0.06
            self.es_demo = True

        if self.es_demo:
            self.cooldown_horas = min(self.cooldown_horas, 2)

    # ============================================================
    # API PRINCIPAL
    # ============================================================

    def verificar(self) -> bool:
        """
        Retorna True si hay bloqueo activo (no se puede operar).
        Auto-desactiva si expiró.
        """
        if not self.activo:
            return False

        if self.hasta and now_utc() >= self.hasta:
            self._desactivar_y_reactivar()
            return False

        return True

    def verificar_simbolo(self, simbolo: str) -> Tuple[bool, str]:
        """
        Verifica si un símbolo específico puede operar.
        Considera bloqueos de scope SIMBOLO, REGIMEN, SESION, MODO, GLOBAL.
        """
        if not self.activo:
            # Bloqueo expirado
            return True, "OK"

        # Verificar expiración
        if self.hasta and now_utc() >= self.hasta:
            self._desactivar_y_reactivar()
            return True, "OK"

        # Bloqueo GLOBAL afecta a todos
        if self.scope == ScopeBloqueo.GLOBAL:
            return False, f"Bloqueo GLOBAL activo: {self.motivo}"

        # Bloqueo por SÍMBOLO
        if self.scope == ScopeBloqueo.SIMBOLO:
            if self.scope_valor.upper() == simbolo.upper():
                return False, f"Bloqueo de símbolo {simbolo}: {self.motivo}"
            return True, "OK"

        # Bloqueos por RÉGIMEN/SESIÓN/MODO se verifican fuera de aquí
        # (el orquestador los consulta con verificar_regimen/sesion/modo)
        return True, "OK"

    def verificar_regimen(self, regimen: str) -> Tuple[bool, str]:
        """Verifica si un régimen está bloqueado."""
        if not self.activo or not self._esta_vigente():
            return True, "OK"
        if self.scope == ScopeBloqueo.REGIMEN and self.scope_valor == regimen:
            return False, f"Régimen {regimen} bloqueado: {self.motivo}"
        return True, "OK"

    def verificar_sesion(self, sesion: str) -> Tuple[bool, str]:
        """Verifica si una sesión está bloqueada."""
        if not self.activo or not self._esta_vigente():
            return True, "OK"
        if self.scope == ScopeBloqueo.SESION and self.scope_valor == sesion:
            return False, f"Sesión {sesion} bloqueada: {self.motivo}"
        return True, "OK"

    def verificar_modo(self, modo: str) -> Tuple[bool, str]:
        """Verifica si un modo está bloqueado."""
        if not self.activo or not self._esta_vigente():
            return True, "OK"
        if self.scope == ScopeBloqueo.MODO and self.scope_valor == modo:
            return False, f"Modo {modo} bloqueado: {self.motivo}"
        return True, "OK"

    def _esta_vigente(self) -> bool:
        """Retorna True si el bloqueo sigue vigente (no expiró)."""
        if not self.activo:
            return False
        if self.hasta and now_utc() >= self.hasta:
            self._desactivar_y_reactivar()
            return False
        return True

    # ============================================================
    # ACTIVACIÓN
    # ============================================================

    def activar(
        self,
        motivo: str,
        scope: ScopeBloqueo = ScopeBloqueo.GLOBAL,
        scope_valor: str = "",
        horas: Optional[int] = None,
    ):
        """
        Activa el Circuit Breaker.
        Si ya hay uno activo, mantiene el más restrictivo.
        """
        if self.activo:
            # Si ya hay GLOBAL, no cambiar a algo más específico
            if self.scope == ScopeBloqueo.GLOBAL:
                self.logger.info(f"CB GLOBAL ya activo: {self.motivo}")
                return
            # Si el nuevo es GLOBAL, reemplazar
            if scope != ScopeBloqueo.GLOBAL:
                self.logger.info(f"CB ya activo ({self.scope.value}); nuevo scope {scope.value} ignorado")
                return

        if horas is None:
            horas = self.cooldown_horas

        horas = max(1, min(72, horas))
        if self.es_demo:
            horas = min(horas, 2)

        self.activo = True
        self.hasta = now_utc() + timedelta(hours=horas)
        self.motivo = motivo
        self.scope = scope
        self.scope_valor = scope_valor

        self.logger.error(
            f"🛡️ CIRCUIT BREAKER ACTIVADO "
            f"[{scope.value}{':' + scope_valor if scope_valor else ''}] "
            f"({horas}h): {motivo}"
        )

        self._persistir_estado()

        if self.notificador:
            try:
                self.notificador.enviar(
                    "🛡️ CIRCUIT BREAKER ACTIVADO",
                    f"Scope: {scope.value}"
                    + (f" ({scope_valor})" if scope_valor else "")
                    + f"\nMotivo: {motivo}"
                    + f"\nDuración: {horas}h"
                    + f"\nHasta: {self.hasta.strftime('%Y-%m-%d %H:%M UTC')}",
                    tipo='error',
                )
            except Exception:
                pass

    def desactivar(self):
        """Desactiva manualmente."""
        if not self.activo:
            return
        self._desactivar_y_reactivar()
        self.logger.info("✅ Circuit Breaker desactivado manualmente")

    def _desactivar_y_reactivar(self):
        """Desactiva el CB e inicia reactivación gradual."""
        self.activo = False
        self.hasta = None
        self.motivo = ""
        self.scope = ScopeBloqueo.GLOBAL
        self.scope_valor = ""

        # Iniciar reactivación gradual
        self.reactivacion = EstadoReactivacion(
            activa=True,
            factor_riesgo=self.FACTOR_REACTIVACION,
            ganadoras_consecutivas=0,
            perdidas_en_reactivacion=0,
            operaciones_desde_reactivacion=0,
        )

        self.logger.info(
            f"🔄 Reactivación gradual iniciada "
            f"(riesgo al {self.FACTOR_REACTIVACION*100:.0f}%, "
            f"{self.GANADORAS_PARA_100} ganadoras para 100%)"
        )

        self._persistir_estado()

        if self.notificador:
            try:
                self.notificador.enviar(
                    "🔄 REACTIVACIÓN GRADUAL",
                    f"Riesgo al {self.FACTOR_REACTIVACION*100:.0f}%\n"
                    f"Recuperar 100% tras {self.GANADORAS_PARA_100} ganadoras consecutivas",
                    tipo='info',
                )
            except Exception:
                pass

    # ============================================================
    # REACTIVACIÓN GRADUAL
    # ============================================================

    def registrar_operacion_reactivacion(self, ganancia: float):
        """
        Registra una operación durante reactivación.
        Ajusta el factor de riesgo.
        """
        if not self.reactivacion.activa:
            return

        self.reactivacion.operaciones_desde_reactivacion += 1

        if ganancia > 0:
            self.reactivacion.ganadoras_consecutivas += 1
            self.reactivacion.perdidas_en_reactivacion = 0

            # Escalar el factor
            progreso = self.reactivacion.ganadoras_consecutivas / self.GANADORAS_PARA_100
            self.reactivacion.factor_riesgo = min(
                1.0,
                self.FACTOR_REACTIVACION + (1 - self.FACTOR_REACTIVACION) * progreso,
            )

            self.logger.info(
                f"✅ Reactivación: {self.reactivacion.ganadoras_consecutivas}/{self.GANADORAS_PARA_100} "
                f"ganadoras → riesgo {self.reactivacion.factor_riesgo*100:.0f}%"
            )

            if self.reactivacion.ganadoras_consecutivas >= self.GANADORAS_PARA_100:
                self._completar_reactivacion()

        else:
            # Pérdida
            self.reactivacion.ganadoras_consecutivas = 0
            self.reactivacion.perdidas_en_reactivacion += 1

            # Resetear factor
            self.reactivacion.factor_riesgo = self.FACTOR_REACTIVACION

            self.logger.warning(
                f"⚠️ Reactivación: pérdida detectada → riesgo reset a "
                f"{self.FACTOR_REACTIVACION*100:.0f}%"
            )

            # Si supera el límite, volver a activar CB
            if self.reactivacion.perdidas_en_reactivacion >= self.PERDIDAS_EN_REACTIVACION:
                self.logger.warning("🛡️ Reactivación fallida, reactivando Circuit Breaker")
                self.reactivacion.activa = False
                self.activar(
                    motivo=f"Reactivación fallida ({self.reactivacion.perdidas_en_reactivacion} pérdida)",
                    scope=ScopeBloqueo.GLOBAL,
                )

        self._persistir_estado()

    def _completar_reactivacion(self):
        """Reactiva al 100%."""
        self.reactivacion.activa = False
        self.reactivacion.factor_riesgo = 1.0

        self.logger.info("🎉 Reactivación COMPLETA: riesgo al 100%")

        if self.notificador:
            try:
                self.notificador.enviar(
                    "🎉 REACTIVACIÓN COMPLETA",
                    "Riesgo restaurado al 100%",
                    tipo='exito',
                )
            except Exception:
                pass

    def forzar_reactivacion_completa(self):
        """Fuerza 100% (admin)."""
        self.reactivacion.activa = False
        self.reactivacion.factor_riesgo = 1.0
        self.logger.info("⚡ Reactivación forzada al 100%")

    def obtener_factor_riesgo(self) -> float:
        """
        Factor multiplicador de riesgo (1.0 = normal, 0.5 = reactivando).
        """
        if self.reactivacion.activa:
            return self.reactivacion.factor_riesgo
        return 1.0

    # ============================================================
    # ANÁLISIS POST-MORTEM
    # ============================================================

    def evaluar_perdidas_consecutivas(
        self,
        perdidas_consecutivas: int,
        historial_operaciones: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Evalúa si se debe activar el CB por pérdidas consecutivas.
        Hace post-mortem para decidir el scope.

        Returns:
            True si se activa
        """
        if perdidas_consecutivas < self.max_consecutive_losses:
            return False

        # Post-mortem: analizar las últimas N pérdidas
        analisis = self.analizar_ultimas_perdidas(historial_operaciones or [])
        self.ultimo_post_mortem = analisis

        motivo = (
            f"{perdidas_consecutivas} pérdidas consecutivas "
            f"[{analisis.patron_dominante or 'sin patrón'}]"
        )

        self.activar(
            motivo=motivo,
            scope=analisis.scope_recomendado,
            scope_valor=analisis.scope_valor,
            horas=self.cooldown_horas,
        )

        # Notificar con detalle
        if self.notificador and analisis.patron_dominante:
            try:
                self.notificador.enviar(
                    "🛡️ POST-MORTEM",
                    f"Patrón: {analisis.patron_dominante}\n"
                    f"Scope: {analisis.scope_recomendado.value} "
                    f"({analisis.scope_valor})\n"
                    f"Razón: {analisis.razon}",
                    tipo='alerta',
                )
            except Exception:
                pass

        return True

    def analizar_ultimas_perdidas(
        self,
        historial: List[Dict[str, Any]],
        n_ops: Optional[int] = None,
    ) -> AnalisisPostMortem:
        """
        Analiza las últimas N operaciones para detectar patrones.
        Devuelve el scope más probable de la causa.
        """
        n_ops = n_ops or self.N_OPS_ANALIZAR
        resultado = AnalisisPostMortem()

        if not historial:
            resultado.razon = "Sin historial"
            resultado.scope_recomendado = ScopeBloqueo.GLOBAL
            return resultado

        # Filtrar últimas N CERRADAS
        cerradas = [op for op in historial if op.get('estado') == 'CERRADA']
        recientes = cerradas[-n_ops:] if len(cerradas) > n_ops else cerradas

        if not recientes:
            resultado.razon = "Sin operaciones cerradas"
            resultado.scope_recomendado = ScopeBloqueo.GLOBAL
            return resultado

        # Filtrar solo las perdedoras
        perdedoras = [op for op in recientes if op.get('ganancia', 0) < 0]
        if not perdedoras:
            resultado.razon = "Sin pérdidas recientes"
            resultado.scope_recomendado = ScopeBloqueo.GLOBAL
            return resultado

        total = len(perdedoras)

        # Contar por dimensión
        conteo_simbolos: Dict[str, int] = {}
        conteo_regimen: Dict[str, int] = {}
        conteo_sesion: Dict[str, int] = {}
        conteo_modo: Dict[str, int] = {}

        for op in perdedoras:
            s = op.get('simbolo', '')
            if s:
                conteo_simbolos[s] = conteo_simbolos.get(s, 0) + 1

            ctx = op.get('contexto_apertura', {}) or {}
            r = ctx.get('regimen') or op.get('regimen')
            if r:
                conteo_regimen[r] = conteo_regimen.get(r, 0) + 1

            ses = ctx.get('sesion') or op.get('sesion')
            if ses:
                conteo_sesion[ses] = conteo_sesion.get(ses, 0) + 1

            m = op.get('modo')
            if m:
                conteo_modo[m] = conteo_modo.get(m, 0) + 1

        resultado.simbolos = list(conteo_simbolos.keys())
        resultado.regimenes = list(conteo_regimen.keys())
        resultado.sesiones = list(conteo_sesion.keys())
        resultado.modos = list(conteo_modo.keys())

        # Buscar patrón dominante (por prioridad)
        def dominante(conteo: Dict[str, int]) -> Optional[Tuple[str, int]]:
            if not conteo:
                return None
            mejor = max(conteo.items(), key=lambda x: x[1])
            return mejor

        # 1. Símbolo específico
        if conteo_simbolos:
            sim, n = dominante(conteo_simbolos)
            if n / total * 100 >= self.UMBRAL_PATRON_PCT:
                resultado.patron_dominante = f"Símbolo {sim}"
                resultado.scope_recomendado = ScopeBloqueo.SIMBOLO
                resultado.scope_valor = sim
                resultado.razon = f"{n}/{total} pérdidas en {sim}"
                resultado.detalles = {'simbolos': conteo_simbolos}
                return resultado

        # 2. Régimen específico
        if conteo_regimen:
            reg, n = dominante(conteo_regimen)
            if n / total * 100 >= self.UMBRAL_PATRON_PCT:
                resultado.patron_dominante = f"Régimen {reg}"
                resultado.scope_recomendado = ScopeBloqueo.REGIMEN
                resultado.scope_valor = reg
                resultado.razon = f"{n}/{total} pérdidas en {reg}"
                resultado.detalles = {'regimenes': conteo_regimen}
                return resultado

        # 3. Sesión específica
        if conteo_sesion:
            ses, n = dominante(conteo_sesion)
            if n / total * 100 >= self.UMBRAL_PATRON_PCT:
                resultado.patron_dominante = f"Sesión {ses}"
                resultado.scope_recomendado = ScopeBloqueo.SESION
                resultado.scope_valor = ses
                resultado.razon = f"{n}/{total} pérdidas en {ses}"
                resultado.detalles = {'sesiones': conteo_sesion}
                return resultado

        # 4. Modo específico
        if conteo_modo:
            mod, n = dominante(conteo_modo)
            if n / total * 100 >= self.UMBRAL_PATRON_PCT:
                resultado.patron_dominante = f"Modo {mod}"
                resultado.scope_recomendado = ScopeBloqueo.MODO
                resultado.scope_valor = mod
                resultado.razon = f"{n}/{total} pérdidas en {mod}"
                resultado.detalles = {'modos': conteo_modo}
                return resultado

        # 5. Sin patrón → GLOBAL
        resultado.patron_dominante = "Sin patrón específico"
        resultado.scope_recomendado = ScopeBloqueo.GLOBAL
        resultado.scope_valor = ""
        resultado.razon = "Pérdidas dispersas → bloqueo global"
        resultado.detalles = {
            'simbolos': conteo_simbolos,
            'regimenes': conteo_regimen,
            'sesiones': conteo_sesion,
            'modos': conteo_modo,
        }
        return resultado

    # ============================================================
    # OTROS EVALUADORES
    # ============================================================

    def evaluar_drawdown(self, dd_actual: float, dd_max: float) -> bool:
        """Activa si drawdown excede."""
        if dd_actual > dd_max and not self.es_demo:
            self.activar(
                motivo=f"Drawdown excedido: {dd_actual*100:.2f}% > {dd_max*100:.2f}%",
                scope=ScopeBloqueo.GLOBAL,
                horas=24,
            )
            return True
        return False

    def evaluar_capital(self, capital_actual: float, capital_inicial: float) -> bool:
        """Activa si capital cae mucho."""
        if capital_actual <= 0:
            self.activar("Capital agotado", ScopeBloqueo.GLOBAL, horas=72)
            return True

        if capital_inicial > 0 and capital_actual < capital_inicial * 0.7:
            self.activar(
                f"Capital bajo: ${capital_actual:.2f} (70% del inicial)",
                ScopeBloqueo.GLOBAL,
                horas=48,
            )
            return True
        return False

    # ============================================================
    # PERSISTENCIA
    # ============================================================

    def _persistir_estado(self):
        """Guarda estado."""
        if not self.almacen:
            return
        try:
            config = self.almacen.obtener_configuracion()
            config['circuit_breaker'] = {
                'activo': self.activo,
                'hasta': self.hasta.isoformat() if self.hasta else None,
                'motivo': self.motivo,
                'scope': self.scope.value,
                'scope_valor': self.scope_valor,
                'reactivacion': {
                    'activa': self.reactivacion.activa,
                    'factor_riesgo': self.reactivacion.factor_riesgo,
                    'ganadoras_consecutivas': self.reactivacion.ganadoras_consecutivas,
                    'perdidas_en_reactivacion': self.reactivacion.perdidas_en_reactivacion,
                    'operaciones_desde_reactivacion': self.reactivacion.operaciones_desde_reactivacion,
                },
                'actualizado': now_utc().isoformat(),
            }
            self.almacen.guardar_configuracion(config)
        except Exception as e:
            self.logger.warning(f"Error persistiendo CB: {e}")

    def _restaurar_estado(self):
        """Restaura desde SQLite."""
        if not self.almacen:
            return
        try:
            config = self.almacen.obtener_configuracion()
            cb = config.get('circuit_breaker', {})

            if cb.get('activo', False):
                hasta_str = cb.get('hasta')
                if hasta_str:
                    hasta = datetime.fromisoformat(hasta_str)
                    ahora = now_utc()
                    if ahora < hasta:
                        self.activo = True
                        self.hasta = hasta
                        self.motivo = cb.get('motivo', 'Restaurado')
                        self.scope = ScopeBloqueo(cb.get('scope', 'GLOBAL'))
                        self.scope_valor = cb.get('scope_valor', '')
                        self.logger.warning(
                            f"🛡️ CB restaurado [{self.scope.value}:{self.scope_valor}] "
                            f"hasta {hasta}"
                        )
                    else:
                        self._desactivar_y_reactivar()

            # Restaurar reactivación
            r = cb.get('reactivacion', {})
            if r.get('activa', False):
                self.reactivacion = EstadoReactivacion(
                    activa=True,
                    factor_riesgo=r.get('factor_riesgo', self.FACTOR_REACTIVACION),
                    ganadoras_consecutivas=r.get('ganadoras_consecutivas', 0),
                    perdidas_en_reactivacion=r.get('perdidas_en_reactivacion', 0),
                    operaciones_desde_reactivacion=r.get('operaciones_desde_reactivacion', 0),
                )
                self.logger.info(
                    f"🔄 Reactivación restaurada: factor "
                    f"{self.reactivacion.factor_riesgo*100:.0f}% "
                    f"({self.reactivacion.ganadoras_consecutivas} ganadoras)"
                )
        except Exception as e:
            self.logger.warning(f"Error restaurando CB: {e}")

    # ============================================================
    # ESTADÍSTICAS
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        return {
            'activo': self.activo,
            'motivo': self.motivo,
            'scope': self.scope.value,
            'scope_valor': self.scope_valor,
            'hasta': self.hasta.isoformat() if self.hasta else None,
            'tiempo_restante_minutos': self.tiempo_restante(),
            'cooldown_horas': self.cooldown_horas,
            'es_demo': self.es_demo,
            'reactivacion': {
                'activa': self.reactivacion.activa,
                'factor_riesgo': self.reactivacion.factor_riesgo,
                'ganadoras_consecutivas': self.reactivacion.ganadoras_consecutivas,
                'perdidas_en_reactivacion': self.reactivacion.perdidas_en_reactivacion,
            },
            'ultimo_post_mortem': {
                'patron': self.ultimo_post_mortem.patron_dominante,
                'scope': self.ultimo_post_mortem.scope_recomendado.value,
                'razon': self.ultimo_post_mortem.razon,
            } if self.ultimo_post_mortem else None,
        }

    def tiempo_restante(self) -> Optional[float]:
        """Minutos restantes."""
        if not self.activo or not self.hasta:
            return None
        diff = (self.hasta - now_utc()).total_seconds() / 60
        return max(0, diff)


# ============================================================
# FACTORY
# ============================================================

def create_circuit_breaker(
    config: Optional[Any] = None,
    almacen: Optional[Any] = None,
    notificador: Optional[Any] = None,
) -> CircuitBreaker:
    return CircuitBreaker(config=config, almacen=almacen, notificador=notificador)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando CircuitBreaker V10.0...")

    cb = CircuitBreaker()

    # TEST 1: sin bloqueo
    print(f"\nTEST 1: activo={cb.verificar()}, factor={cb.obtener_factor_riesgo()}")
    assert cb.verificar() is False
    assert cb.obtener_factor_riesgo() == 1.0

    # TEST 2: activar GLOBAL 1 hora
    cb.activar("Test manual", ScopeBloqueo.GLOBAL, horas=1)
    print(f"TEST 2: activo={cb.verificar()}, scope={cb.scope.value}")
    assert cb.verificar() is True

    # TEST 3: verificar símbolo (bloqueo global)
    puede, razon = cb.verificar_simbolo('EURUSD')
    print(f"TEST 3: EURUSD puede operar={puede} ({razon})")
    assert puede is False

    # TEST 4: desactivar → reactivación
    cb.desactivar()
    print(f"TEST 4: activo={cb.verificar()}, factor={cb.obtener_factor_riesgo()}")
    assert cb.verificar() is False
    assert cb.obtener_factor_riesgo() == 0.5

    # TEST 5: registrar 3 ganadoras → 100%
    cb.registrar_operacion_reactivacion(10)
    cb.registrar_operacion_reactivacion(10)
    cb.registrar_operacion_reactivacion(10)
    print(f"TEST 5: factor={cb.obtener_factor_riesgo()}, reactivando={cb.reactivacion.activa}")
    assert cb.obtener_factor_riesgo() == 1.0
    assert cb.reactivacion.activa is False

    # TEST 6: post-mortem con patrón SÍMBOLO
    cb2 = CircuitBreaker()
    historial = [
        {'estado': 'CERRADA', 'simbolo': 'EURUSD', 'ganancia': -10},
        {'estado': 'CERRADA', 'simbolo': 'EURUSD', 'ganancia': -5},
        {'estado': 'CERRADA', 'simbolo': 'EURUSD', 'ganancia': -8},
        {'estado': 'CERRADA', 'simbolo': 'EURUSD', 'ganancia': -3},
    ]
    analisis = cb2.analizar_ultimas_perdidas(historial)
    print(f"\nTEST 6: patrón={analisis.patron_dominante}, "
          f"scope={analisis.scope_recomendado.value}, "
          f"valor={analisis.scope_valor}")
    assert analisis.scope_recomendado == ScopeBloqueo.SIMBOLO
    assert analisis.scope_valor == 'EURUSD'

    # TEST 7: post-mortem con patrón RÉGIMEN
    historial2 = [
        {'estado': 'CERRADA', 'simbolo': 'EURUSD', 'ganancia': -10,
         'contexto_apertura': {'regimen': 'CHOP_VOLATIL'}},
        {'estado': 'CERRADA', 'simbolo': 'GBPUSD', 'ganancia': -5,
         'contexto_apertura': {'regimen': 'CHOP_VOLATIL'}},
        {'estado': 'CERRADA', 'simbolo': 'USDJPY', 'ganancia': -8,
         'contexto_apertura': {'regimen': 'CHOP_VOLATIL'}},
    ]
    analisis2 = cb2.analizar_ultimas_perdidas(historial2)
    print(f"TEST 7: patrón={analisis2.patron_dominante}, "
          f"scope={analisis2.scope_recomendado.value}, valor={analisis2.scope_valor}")
    assert analisis2.scope_recomendado == ScopeBloqueo.REGIMEN
    assert analisis2.scope_valor == 'CHOP_VOLATIL'

    # TEST 8: post-mortem sin patrón → GLOBAL
    historial3 = [
        {'estado': 'CERRADA', 'simbolo': 'EURUSD', 'ganancia': -10,
         'contexto_apertura': {'regimen': 'R1'}, 'modo': 'M1'},
        {'estado': 'CERRADA', 'simbolo': 'GBPUSD', 'ganancia': -5,
         'contexto_apertura': {'regimen': 'R2'}, 'modo': 'M2'},
        {'estado': 'CERRADA', 'simbolo': 'USDJPY', 'ganancia': -8,
         'contexto_apertura': {'regimen': 'R3'}, 'modo': 'M3'},
    ]
    analisis3 = cb2.analizar_ultimas_perdidas(historial3)
    print(f"TEST 8: patrón={analisis3.patron_dominante}, "
          f"scope={analisis3.scope_recomendado.value}")
    assert analisis3.scope_recomendado == ScopeBloqueo.GLOBAL

    print("\n✅ Todos los tests pasan")