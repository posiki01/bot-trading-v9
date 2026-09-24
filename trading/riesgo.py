#!/usr/bin/env python3
"""
trading/riesgo.py (V10.0 - REFACTORIZADO COMPLETAMENTE)
Sistema de Gestión de Riesgo para el Bot de Trading.

CAMBIOS V10.0:
- ✅ Integración completa con CircuitBreaker V10.0 (post-mortem + reactivación gradual)
- ✅ historial_operaciones para análisis post-mortem
- ✅ puede_operar_simbolo() — verifica bloqueo por símbolo específico
- ✅ obtener_factor_riesgo_reactivacion() — riesgo reducido post-bloqueo
- ✅ analizar_post_mortem() — para el informe diario
- ✅ registrar_operacion() notifica al CB para reactivación
- ✅ estadisticas() incluye info de reactivación

MANTIENE:
- Cálculo de lotes con valor de pip REAL (JPY corregido)
- Decimal para precisión financiera
- Apalancamiento dinámico por tipo de activo
- Persistencia SQLite de capital y pérdidas
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal, getcontext
from datetime import datetime, timezone, timedelta

from trading.riesgo_circuit import CircuitBreaker, ScopeBloqueo
from trading.riesgo_lotes import CalculadorLotes
from utils.reloj import now_utc

try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Riesgo')


class GestionRiesgo:
    """
    Gestión de riesgo completa para el bot.
    V10.0 - REFACTORIZADO.
    """

    # ============================================================
    # CONFIGURACIÓN
    # ============================================================

    MAX_HISTORIAL_OPERACIONES = 200  # Para post-mortem
    PERDIDAS_CONSECUTIVAS_SIMBOLO = 3  # Antes de bloquear ese símbolo

    def __init__(
        self,
        capital_inicial: float = 100.0,
        aporte_mensual: float = 50.0,
        almacen: Optional[Any] = None,
        notificador: Optional[Any] = None,
        config: Optional[Any] = None,
        modo_backtest: bool = False,
        mt5: Optional[Any] = None,
    ):
        """
        Inicializa la gestión de riesgo.
        """
        getcontext().prec = 10

        self.config = config
        self.almacen = almacen
        self.notificador = notificador
        self.modo_backtest = modo_backtest
        self.mt5 = mt5
        self.logger = logging.getLogger('BotTrading.Riesgo')

        # ============================================================
        # 1. CAPITAL
        # ============================================================
        capital_desde_mt5 = None
        if not modo_backtest and mt5 is not None:
            try:
                cuenta = mt5.info_cuenta()
                if cuenta and cuenta.get('balance', 0) > 0:
                    capital_desde_mt5 = Decimal(str(cuenta['balance']))
            except Exception:
                pass

        if capital_desde_mt5 is not None:
            self.capital_inicial = capital_desde_mt5
            self.capital_actual = capital_desde_mt5
            self.total_aportado = capital_desde_mt5
            self.logger.info(f"💰 Capital desde MT5: ${float(self.capital_actual):,.2f}")
        else:
            self.capital_inicial = Decimal(str(capital_inicial))
            self.capital_actual = Decimal(str(capital_inicial))
            self.total_aportado = Decimal(str(capital_inicial))
            self.logger.info(f"💰 Capital inicial (config): ${float(self.capital_actual):,.2f}")

        self.historial_capital: List[Decimal] = [self.capital_actual]

        # ============================================================
        # 2. APORTES
        # ============================================================
        self.aporte_mensual = Decimal(str(aporte_mensual))
        self.ultimo_aporte = now_utc()
        self.proximo_aporte = self.ultimo_aporte + timedelta(days=30)

        # ============================================================
        # 3. OPERACIONES
        # ============================================================
        self.operaciones: List[Dict[str, Any]] = []
        self.historial_operaciones: List[Dict[str, Any]] = []  # ✅ V10.0
        self.operaciones_hoy = 0
        self.ganancia_diaria = Decimal('0.0')
        self.perdida_diaria = Decimal('0.0')

        # ============================================================
        # 4. PÉRDIDAS CONSECUTIVAS
        # ============================================================
        self.perdidas_consecutivas = 0
        self.perdidas_consecutivas_por_simbolo: Dict[str, int] = {}

        # ============================================================
        # 5. CIRCUIT BREAKER (V10.0)
        # ============================================================
        self.circuit_breaker = CircuitBreaker(
            config=config,
            almacen=almacen,
            notificador=notificador,
        )

        # ============================================================
        # 6. CALCULADOR DE LOTES
        # ============================================================
        self.calculador_lotes = CalculadorLotes(config)

        # ============================================================
        # 7. ESTADO
        # ============================================================
        self.ultima_etapa = self._calcular_etapa()
        self.equity_inicio_dia: Optional[float] = None
        self.sim_current_time: Optional[datetime] = None

        # ============================================================
        # 8. CARGAR ESTADO
        # ============================================================
        self._cargar_estado()

        self.logger.info("💰 GestionRiesgo V10.0 REFACTORIZADO inicializado")
        self.logger.info(f"   Capital: ${float(self.capital_actual):,.2f}")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   MT5: {'✅' if mt5 else '❌'}")

    # ============================================================
    # CARGA Y PERSISTENCIA DE ESTADO
    # ============================================================

    def _cargar_estado(self):
        """Carga estado desde almacenamiento."""
        if not self.almacen:
            return

        try:
            config = self.almacen.obtener_configuracion()

            # Capital
            if self.capital_actual == self.capital_inicial and not self.modo_backtest:
                last_cap = config.get('capital_actual')
                if last_cap is not None and float(last_cap) > 0:
                    self.capital_actual = Decimal(str(float(last_cap)))
                    self.total_aportado = Decimal(
                        str(float(config.get('total_aportado', last_cap)))
                    )
                    self.logger.info(
                        f"💰 Capital restaurado: ${float(self.capital_actual):,.2f}"
                    )

            # Etapa
            etapa = config.get('ultima_etapa')
            if etapa is not None:
                self.ultima_etapa = int(etapa)

            # Pérdidas por símbolo
            perdidas = config.get('perdidas_por_simbolo', {})
            if perdidas:
                self.perdidas_consecutivas_por_simbolo = {
                    k: int(v) for k, v in perdidas.items()
                }

            self.perdidas_consecutivas = int(config.get('consecutivas_perdidas', 0))

            # Último aporte
            ultimo_aporte_str = config.get('ultimo_aporte')
            if ultimo_aporte_str:
                try:
                    self.ultimo_aporte = datetime.fromisoformat(ultimo_aporte_str)
                    self.proximo_aporte = self.ultimo_aporte + timedelta(days=30)
                except Exception:
                    pass

        except Exception as e:
            self.logger.warning(f"Error cargando estado: {e}")

    def _guardar_estado(self):
        """Guarda estado en almacenamiento."""
        if not self.almacen:
            return

        try:
            config = self.almacen.obtener_configuracion()
            config['capital_actual'] = float(self.capital_actual)
            config['total_aportado'] = float(self.total_aportado)
            config['ultima_etapa'] = self.ultima_etapa
            config['perdidas_por_simbolo'] = self.perdidas_consecutivas_por_simbolo
            config['consecutivas_perdidas'] = self.perdidas_consecutivas
            config['ultimo_aporte'] = self.ultimo_aporte.isoformat()
            self.almacen.guardar_configuracion(config)
        except Exception as e:
            self.logger.warning(f"Error guardando estado: {e}")

    # ============================================================
    # CAPITAL Y MARGEN
    # ============================================================

    def obtener_capital_real(self) -> float:
        """Obtiene capital REAL desde MT5."""
        if self.modo_backtest or self.mt5 is None:
            return float(self.capital_actual)

        try:
            cuenta = self.mt5.info_cuenta()
            if cuenta and cuenta.get('balance', 0) > 0:
                balance_real = float(cuenta['balance'])
                if Decimal(str(balance_real)) != self.capital_actual:
                    self.logger.info(
                        f"💰 Capital actualizado desde MT5: ${balance_real:,.2f}"
                    )
                    self.capital_actual = Decimal(str(balance_real))
                    self.historial_capital.append(self.capital_actual)
                return balance_real
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo capital de MT5: {e}")

        return float(self.capital_actual)

    def _obtener_precio_actual(self, simbolo: str) -> float:
        """Obtiene precio actual del símbolo."""
        if self.mt5 and hasattr(self.mt5, 'obtener_precio'):
            try:
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    return float(tick.get('bid', tick.get('ask', 0)))
            except Exception:
                pass
        return 1.0

    def obtener_margen_libre(self) -> float:
        """Obtiene margen libre REAL desde MT5."""
        if self.modo_backtest or self.mt5 is None:
            return float(self.capital_actual) * 0.8

        try:
            cuenta = self.mt5.info_cuenta()
            if cuenta:
                margen_libre = float(cuenta.get('margen_libre', 0) or 0)
                if margen_libre <= 0:
                    margen_libre = float(cuenta.get('margin_free', 0) or 0)
                if margen_libre <= 0:
                    margen_libre = float(cuenta.get('equity', 0) or 0)
                return margen_libre
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo margen libre: {e}")

        return float(self.capital_actual) * 0.8

    # ============================================================
    # PIP Y CONTRATOS
    # ============================================================

    def _obtener_pip_val(self, simbolo: str) -> float:
        """Obtiene pip_val para el símbolo."""
        try:
            from utils.parametros_simbolo import get_pip_val
            return get_pip_val(simbolo, self.mt5)
        except (ImportError, RecursionError):
            pass

        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.10
        if 'XAG' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001

    def _obtener_tamano_contrato(self, simbolo: str) -> float:
        """Obtiene tamaño de contrato."""
        simbolo_upper = simbolo.upper()

        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        if 'XAU' in simbolo_upper:
            return 100.0
        if 'XAG' in simbolo_upper:
            return 5000.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        return 100000.0

    def _calcular_valor_pip_real(self, simbolo: str, lotes: float) -> float:
        """
        Calcula el valor REAL de 1 pip en USD para la posición.
        Corregido para JPY.
        """
        simbolo_upper = simbolo.upper()
        contract_size = self._obtener_tamano_contrato(simbolo)
        pip_val = self._obtener_pip_val(simbolo)

        if 'JPY' in simbolo_upper:
            precio_actual = self._obtener_precio_actual(simbolo)
            if precio_actual > 0:
                valor_1_lote = (contract_size * pip_val) / precio_actual
            else:
                valor_1_lote = contract_size * pip_val / 100
        else:
            valor_1_lote = contract_size * pip_val

        valor_posicion = valor_1_lote * lotes
        return max(0.001, valor_posicion)

    def _estimar_margen(self, simbolo: str, lotes: float, precio: float) -> float:
        """Estima margen requerido."""
        simbolo_upper = simbolo.upper()
        apalancamiento = 30

        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            apalancamiento = 20
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            apalancamiento = 20
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            apalancamiento = 10

        contract_size = 100000
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            contract_size = 100
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            contract_size = 1
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            contract_size = 1

        valor_operacion = lotes * contract_size * precio
        return valor_operacion / apalancamiento

    # ============================================================
    # ✅ V10.0: VERIFICAR OPERABILIDAD
    # ============================================================

    def puede_operar(
        self,
        equity_actual: Optional[float] = None,
        margin_level: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Verifica si se puede operar (general)."""
        if self.circuit_breaker.verificar():
            return False, f"Circuit Breaker activo: {self.circuit_breaker.motivo}"

        capital_real = self.obtener_capital_real()
        if capital_real <= 1.0:
            return False, "Capital insuficiente"

        if self.operaciones_hoy >= self._obtener_max_ops_dia():
            return False, "Límite diario de operaciones alcanzado"

        if self.perdida_diaria >= self._calcular_limite_perdida_diaria():
            return False, "Pérdida diaria máxima alcanzada"

        if self._calcular_drawdown() > self._obtener_drawdown_maximo():
            if not self.modo_backtest:
                return False, "Drawdown máximo excedido"

        if equity_actual and Decimal(str(equity_actual)) < self.capital_actual * Decimal('0.95'):
            if not self.modo_backtest:
                return False, "Equity por debajo del 95% del capital"

        if margin_level is not None and margin_level < 200.0:
            return False, "Nivel de margen insuficiente"

        margen_libre = self.obtener_margen_libre()
        if margen_libre < 50.0:
            self.logger.info(f"⚠️ Margen libre bajo: ${margen_libre:.2f}")
            return False, f"Margen libre insuficiente (${margen_libre:.2f} < $50)"

        return True, "OK"

    def puede_operar_simbolo(self, simbolo: str) -> Tuple[bool, str]:
        """
        ✅ V10.0: Verifica si un símbolo específico puede operar.
        Considera bloqueos por scope: GLOBAL, SIMBOLO, y pérdidas por símbolo.
        """
        # 1. CB general
        if self.circuit_breaker.verificar():
            return False, f"CB activo: {self.circuit_breaker.motivo}"

        # 2. CB por símbolo específico
        puede, razon = self.circuit_breaker.verificar_simbolo(simbolo)
        if not puede:
            return False, razon

        # 3. Pérdidas consecutivas por símbolo
        perdidas_simbolo = self.perdidas_consecutivas_por_simbolo.get(simbolo, 0)
        if perdidas_simbolo >= self.PERDIDAS_CONSECUTIVAS_SIMBOLO:
            return False, f"{simbolo}: {perdidas_simbolo} pérdidas consecutivas"

        return True, "OK"

    # ============================================================
    # ✅ V10.0: REACTIVACIÓN GRADUAL
    # ============================================================

    def obtener_factor_riesgo_reactivacion(self) -> float:
        """
        ✅ V10.0: Factor multiplicador de riesgo durante reactivación.
        1.0 = normal, 0.5 = reactivando.
        """
        return self.circuit_breaker.obtener_factor_riesgo()

    # ============================================================
    # CÁLCULO DE LOTES
    # ============================================================

    def calcular_lotes(
        self,
        entrada: float,
        stop_loss: float,
        probabilidad: float,
        simbolo: str,
        capital: Optional[float] = None,
        **kwargs,
    ) -> float:
        """
        Calcula el tamaño de lote óptimo.
        V10.0: aplica factor de reactivación gradual.
        """
        # 1. Capital
        if capital is None:
            capital = self.obtener_capital_real()

        if capital is None or capital <= 0:
            return 0.0

        if entrada <= 0 or stop_loss <= 0:
            return 0.0

        # 2. Distancia del SL
        sl_dist = abs(entrada - stop_loss)
        if sl_dist <= 0:
            return 0.0

        # 3. Pip size
        pip_size = kwargs.get('pip_size', 0.0001)
        if pip_size <= 0:
            pip_size = self._obtener_pip_val(simbolo)

        sl_pips = sl_dist / pip_size if pip_size > 0 else 10
        if sl_pips <= 0:
            sl_pips = 10

        # 4. Riesgo por activo
        simbolo_upper = simbolo.upper()
        riesgo_max_por_operacion = getattr(Umbrales, 'RIESGO_MAX_POR_OPERACION', {}) if Umbrales else {}
        riesgo_pct = riesgo_max_por_operacion.get(simbolo_upper, 0.01)

        # Ajuste por probabilidad
        if probabilidad > 70:
            riesgo_pct = min(riesgo_pct * 1.1, 0.02)
        elif probabilidad < 40:
            riesgo_pct = riesgo_pct * 0.7

        riesgo_pct = min(riesgo_pct, 0.02)
        riesgo_pct = max(riesgo_pct, 0.001)

        # ✅ V10.0: aplicar factor de reactivación gradual
        factor_react = self.obtener_factor_riesgo_reactivacion()
        if factor_react < 1.0:
            riesgo_pct *= factor_react
            self.logger.info(
                f"🔄 Reactivación activa: riesgo ajustado a {riesgo_pct*100:.2f}%"
            )

        # 5. Valor del pip real
        lotes_prueba = 1.0
        valor_pip_real = self._calcular_valor_pip_real(simbolo, lotes_prueba)
        if valor_pip_real <= 0:
            valor_pip_real = 0.01

        # 6. Lotes por riesgo
        riesgo_dinero = capital * riesgo_pct
        lotes_por_riesgo = riesgo_dinero / (sl_pips * valor_pip_real)

        # 7. Límites por activo
        lotes_max_por_activo = getattr(Umbrales, 'LOTES_MAX_POR_ACTIVO', {}) if Umbrales else {}
        lotes_min_por_activo = getattr(Umbrales, 'LOTES_MIN_POR_ACTIVO', {}) if Umbrales else {}

        lote_min = lotes_min_por_activo.get(simbolo_upper, 0.01)
        lote_max = lotes_max_por_activo.get(simbolo_upper, 0.10)

        # Límites especiales
        if 'XAU' in simbolo_upper:
            lote_max = min(lote_max, 0.05)
            if capital < 1000:
                lote_max = min(lote_max, 0.02)
            elif capital < 2000:
                lote_max = min(lote_max, 0.03)

        if capital < 5000:
            factor_capital = max(0.3, capital / 5000)
            lote_max = max(lote_min, lote_max * factor_capital)

        # 8. Límite por margen
        margen_libre = self.obtener_margen_libre()
        margen_por_lote = self._estimar_margen(simbolo, 1.0, entrada)

        if margen_por_lote > 0:
            lotes_max_por_margen = margen_libre / margen_por_lote
            lotes_max_por_margen = round(lotes_max_por_margen / 0.01) * 0.01
            if lotes_max_por_margen < lote_min:
                self.logger.warning(f"⚠️ {simbolo}: Margen insuficiente para lote mínimo")
                return 0.0
            lote_max = min(lote_max, lotes_max_por_margen)

        # 9. Aplicar límites
        lotes = max(lote_min, min(lote_max, lotes_por_riesgo))
        paso = 0.01
        lotes = round(lotes / paso) * paso
        if lotes < lote_min:
            lotes = lote_min

        # 10. Log
        riesgo_real = (lotes * sl_pips * valor_pip_real) / capital * 100
        self.logger.info(
            f"📊 {simbolo}: Lotes={lotes:.3f} | "
            f"SL={sl_pips:.1f}pips | Valor pip=${valor_pip_real:.4f} | "
            f"Riesgo real={riesgo_real:.2f}%"
        )
        if factor_react < 1.0:
            self.logger.info(f"   ⚠️ Factor reactivación: {factor_react*100:.0f}%")

        return lotes

    # ============================================================
    # ✅ V10.0: REGISTRAR OPERACIÓN (integra con CB)
    # ============================================================

    def registrar_operacion(self, resultado: Dict[str, Any]):
        """
        Registra una operación cerrada.
        V10.0: notifica al CB para reactivación gradual + guarda historial.
        """
        ganancia_bruta = Decimal(str(resultado.get('ganancia', 0.0)))
        comision = Decimal(str(resultado.get('comision', 0.0)))
        swap = Decimal(str(resultado.get('swap', 0.0)))
        ganancia_neta = ganancia_bruta + comision + swap

        simbolo = resultado.get('simbolo', '')
        ticket = resultado.get('ticket')

        # Evitar duplicados
        if ticket:
            existe = any(o.get('ticket') == ticket for o in self.operaciones)
            if existe:
                self.logger.debug(f"Operación {ticket} ya registrada")
                return

        self.operaciones_hoy += 1

        # Actualizar contadores
        if ganancia_neta > 0:
            self.ganancia_diaria += ganancia_neta
            self.perdidas_consecutivas = 0
            if simbolo:
                self.perdidas_consecutivas_por_simbolo[simbolo] = 0
        else:
            self.perdida_diaria += abs(ganancia_neta)
            self.perdidas_consecutivas += 1
            if simbolo:
                self.perdidas_consecutivas_por_simbolo[simbolo] = \
                    self.perdidas_consecutivas_por_simbolo.get(simbolo, 0) + 1

        # Actualizar capital
        self.capital_actual += ganancia_neta
        self.historial_capital.append(self.capital_actual)

        # Crear op con timestamp y capital_despues
        # Crear op con timestamp y capital_despues
        # ✅ V10.1: garantizar regimen y modo disponibles para filtros SQL
        op = {
            **resultado,
            'ganancia_neta': float(ganancia_neta),
            'timestamp': resultado.get('timestamp', now_utc().isoformat()),
            'capital_despues': float(self.capital_actual),
            'regimen': resultado.get('regimen', 'INCERTO'),
            'modo': resultado.get('modo', 'RETEST'),
            'direccion': resultado.get('direccion', 'COMPRA'),
        }
        self.operaciones.append(op)

        # ✅ V10.0: guardar en historial para post-mortem
        self.historial_operaciones.append(op)
        if len(self.historial_operaciones) > self.MAX_HISTORIAL_OPERACIONES:
            self.historial_operaciones = self.historial_operaciones[-self.MAX_HISTORIAL_OPERACIONES:]

        # ✅ V10.0: notificar al CB para reactivación gradual
        try:
            self.circuit_breaker.registrar_operacion_reactivacion(float(ganancia_neta))
        except Exception as e:
            self.logger.warning(f"⚠️ Error notificando reactivación al CB: {e}")

        # Guardar en SQLite
        if self.almacen:
            try:
                self.almacen.guardar_operacion(op)
            except Exception as e:
                self.logger.warning(f"Error guardando operación: {e}")

        self._guardar_estado()
        self._verificar_circuit_breaker()
        self._verificar_cambio_etapa()

        self.logger.info(
            f"📊 Operación registrada: {simbolo} | "
            f"PnL: {ganancia_neta:+.2f} | "
            f"Capital: ${float(self.capital_actual):,.2f}"
        )

        # Alerta por pérdidas consecutivas por símbolo
        if simbolo and self.perdidas_consecutivas_por_simbolo.get(simbolo, 0) >= 3:
            self.logger.warning(
                f"⚠️ {simbolo}: {self.perdidas_consecutivas_por_simbolo[simbolo]} "
                f"pérdidas consecutivas"
            )
            if self.notificador:
                try:
                    self.notificador.enviar(
                        "⚠️ ALERTA PÉRDIDAS",
                        f"{simbolo}: {self.perdidas_consecutivas_por_simbolo[simbolo]} "
                        f"pérdidas consecutivas",
                        tipo='warning',
                    )
                except Exception:
                    pass

    # ============================================================
    # ✅ V10.0: CIRCUIT BREAKER (con historial)
    # ============================================================

    def _verificar_circuit_breaker(self):
        """Verifica condiciones de CB y lo activa si corresponde."""
        # Pérdidas consecutivas (con post-mortem)
        if self.circuit_breaker.evaluar_perdidas_consecutivas(
            self.perdidas_consecutivas,
            historial_operaciones=self.historial_operaciones,
        ):
            self.logger.warning(
                f"🛡️ CB activado por {self.perdidas_consecutivas} pérdidas consecutivas"
            )

        # Drawdown
        drawdown = self._calcular_drawdown()
        drawdown_max = self._obtener_drawdown_maximo()
        if self.circuit_breaker.evaluar_drawdown(drawdown, drawdown_max):
            self.logger.warning(f"🛡️ CB activado por drawdown: {drawdown:.2%}")

        # Capital
        if self.circuit_breaker.evaluar_capital(
            float(self.capital_actual), float(self.capital_inicial)
        ):
            self.logger.warning("🛡️ CB activado por capital bajo")

    # ============================================================
    # ✅ V10.0: ANÁLISIS POST-MORTEM
    # ============================================================

    def analizar_post_mortem(self) -> Dict[str, Any]:
        """
        Análisis de las últimas operaciones para el reporte diario.
        Retorna dict con patrones detectados.
        """
        analisis = self.circuit_breaker.analizar_ultimas_perdidas(
            self.historial_operaciones
        )
        return {
            'patron_dominante': analisis.patron_dominante,
            'scope_recomendado': analisis.scope_recomendado.value,
            'scope_valor': analisis.scope_valor,
            'razon': analisis.razon,
            'simbolos': analisis.detalles.get('simbolos', {}),
            'regimenes': analisis.detalles.get('regimenes', {}),
            'sesiones': analisis.detalles.get('sesiones', {}),
            'modos': analisis.detalles.get('modos', {}),
        }

    # ============================================================
    # APORTES
    # ============================================================

    def verificar_aporte(self) -> bool:
        """Verifica si se debe realizar el aporte mensual."""
        ahora = self.sim_current_time if self.sim_current_time else now_utc()
        if ahora >= self.proximo_aporte and self.aporte_mensual > 0:
            return self._realizar_aporte(ahora)
        return False

    def _realizar_aporte(self, fecha: datetime) -> bool:
        """Realiza el aporte mensual."""
        self.capital_actual += self.aporte_mensual
        self.total_aportado += self.aporte_mensual
        self.ultimo_aporte = fecha
        self.proximo_aporte = fecha + timedelta(days=30)
        self.historial_capital.append(self.capital_actual)

        self._guardar_estado()
        self._verificar_cambio_etapa()

        self.logger.info(f"💰 Aporte mensual: +${float(self.aporte_mensual):.2f}")

        if self.notificador:
            try:
                self.notificador.enviar(
                    "💰 APORTE MENSUAL",
                    f"Monto: +${float(self.aporte_mensual):.2f}\n"
                    f"Capital actual: ${float(self.capital_actual):,.2f}",
                    tipo='exito',
                )
            except Exception:
                pass

        return True

    # ============================================================
    # ✅ V10.0: ESTADÍSTICAS (con reactivación)
    # ============================================================

    def estadisticas(self) -> Dict[str, Any]:
        """Obtiene estadísticas completas."""
        capital_real = self.obtener_capital_real()

        stats = {
            'capital_actual': capital_real,
            'capital_inicial': float(self.capital_inicial),
            'total_aportado': float(self.total_aportado),
            'ganancia_neta': float(capital_real - float(self.capital_inicial)),
            'rendimiento': float((capital_real / float(self.capital_inicial) - 1) * 100)
                if float(self.capital_inicial) > 0 else 0,
            'ganancia_diaria': float(self.ganancia_diaria),
            'perdida_diaria': float(self.perdida_diaria),
            'operaciones_hoy': self.operaciones_hoy,
            'total_operaciones': len(self.operaciones),
            'perdidas_consecutivas': self.perdidas_consecutivas,
            'etapa': self.ultima_etapa,
            'circuit_breaker': self.circuit_breaker.get_stats(),
            'margen_libre': self.obtener_margen_libre(),

            # ✅ V10.0: Reactivación gradual
            'factor_riesgo_reactivacion': self.obtener_factor_riesgo_reactivacion(),
            'reactivacion_activa': self.circuit_breaker.reactivacion.activa,
            'ganadoras_en_reactivacion': self.circuit_breaker.reactivacion.ganadoras_consecutivas,
        }

        # Win rate
        if self.operaciones:
            ganadoras = sum(1 for o in self.operaciones if o.get('ganancia_neta', 0) > 0)
            stats['win_rate'] = (ganadoras / len(self.operaciones)) * 100
        else:
            stats['win_rate'] = 0.0

        # Factor de beneficio
        gross_profit = sum(
            o.get('ganancia_neta', 0) for o in self.operaciones
            if o.get('ganancia_neta', 0) > 0
        )
        gross_loss = sum(
            abs(o.get('ganancia_neta', 0)) for o in self.operaciones
            if o.get('ganancia_neta', 0) < 0
        )
        stats['factor_beneficio'] = gross_profit / gross_loss if gross_loss > 0 else 0

        # Por símbolo
        por_simbolo: Dict[str, Dict] = {}
        for op in self.operaciones:
            simbolo = op.get('simbolo', 'DESCONOCIDO')
            if simbolo not in por_simbolo:
                por_simbolo[simbolo] = {'total': 0, 'ganadoras': 0, 'pnl': 0.0}
            por_simbolo[simbolo]['total'] += 1
            pnl = op.get('ganancia_neta', 0)
            por_simbolo[simbolo]['pnl'] += pnl
            if pnl > 0:
                por_simbolo[simbolo]['ganadoras'] += 1
        stats['por_simbolo'] = por_simbolo

        return stats

    # ============================================================
    # ETAPA Y DRAWDOWN
    # ============================================================

    def _calcular_etapa(self) -> int:
        """Calcula la etapa actual basada en el capital."""
        cap = self.obtener_capital_real()
        if cap < 350.0:
            return 1
        elif cap < 500.0:
            return 2
        elif cap < 1000.0:
            return 3
        else:
            return 4

    def _verificar_cambio_etapa(self):
        """Verifica y notifica cambio de etapa."""
        etapa_actual = self._calcular_etapa()
        if etapa_actual != self.ultima_etapa:
            self.ultima_etapa = etapa_actual
            self._guardar_estado()

            if self.notificador:
                try:
                    self.notificador.enviar(
                        "🎯 CAMBIO DE ETAPA",
                        f"Capital: ${float(self.capital_actual):,.2f}\n"
                        f"Etapa: {etapa_actual}",
                        tipo='exito',
                    )
                except Exception:
                    pass

    def _calcular_limite_perdida_diaria(self) -> Decimal:
        """Límite de pérdida diaria."""
        return self.capital_actual * Decimal('0.03')

    def _obtener_drawdown_maximo(self) -> float:
        """Drawdown máximo permitido."""
        if self.config:
            return getattr(self.config, 'MAX_DAILY_DRAWDOWN_PCT', 0.06)
        return 0.06

    def _obtener_max_ops_dia(self) -> int:
        """Máximo de operaciones por día."""
        if self.config:
            return getattr(self.config, 'MAX_OPERATIONS_PER_DAY', 8)
        return 8

    def _calcular_drawdown(self) -> float:
        """Drawdown actual."""
        if self.total_aportado > 0:
            return float(
                (self.total_aportado - self.capital_actual) / self.total_aportado
            )
        return 0.0

    def obtener_max_simultaneas(self, equity_actual: Optional[float] = None) -> int:
        """Máximo de operaciones simultáneas."""
        etapa = self._calcular_etapa()
        base_por_etapa = {1: 3, 2: 3, 3: 4, 4: 5}
        max_base = base_por_etapa.get(etapa, 3)

        if equity_actual:
            equity = Decimal(str(equity_actual))
            if self.capital_actual > 0 and equity < self.capital_actual * Decimal('0.95'):
                return max(1, max_base - 1)

        return max_base

    def obtener_etapa_actual(self) -> int:
        """Etapa actual."""
        return self.ultima_etapa

    def reset_diario(self, current_time: Optional[datetime] = None):
        """Resetea contadores diarios."""
        self.perdida_diaria = Decimal('0.0')
        self.ganancia_diaria = Decimal('0.0')
        self.operaciones_hoy = 0
        self.sim_current_time = current_time
        self.equity_inicio_dia = float(self.capital_actual)
        self.logger.info("📊 Contadores diarios reseteados")


# ============================================================
# FACTORY
# ============================================================

def create_gestion_riesgo(
    capital_inicial: float = 100.0,
    aporte_mensual: float = 50.0,
    almacen: Optional[Any] = None,
    notificador: Optional[Any] = None,
    config: Optional[Any] = None,
    modo_backtest: bool = False,
    mt5: Optional[Any] = None,
) -> GestionRiesgo:
    """Crea una instancia de GestionRiesgo."""
    return GestionRiesgo(
        capital_inicial=capital_inicial,
        aporte_mensual=aporte_mensual,
        almacen=almacen,
        notificador=notificador,
        config=config,
        modo_backtest=modo_backtest,
        mt5=mt5,
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando GestionRiesgo V10.0...")

    # Sin MT5, sin almacén, backtest
    g = GestionRiesgo(capital_inicial=1000.0, modo_backtest=True)

    # Test 1: puede_operar
    puede, razon = g.puede_operar()
    print(f"\nTEST 1 (puede_operar): {puede} - {razon}")
    assert puede is True

    # Test 2: puede_operar_simbolo
    puede, razon = g.puede_operar_simbolo('EURUSD')
    print(f"TEST 2 (EURUSD): {puede} - {razon}")
    assert puede is True

    # Test 3: factor de reactivación (normal)
    factor = g.obtener_factor_riesgo_reactivacion()
    print(f"TEST 3 (factor normal): {factor}")
    assert factor == 1.0

    # Test 4: registrar operación ganadora
    g.registrar_operacion({
        'ticket': 1, 'simbolo': 'EURUSD', 'ganancia': 10.0,
        'comision': -1.0, 'swap': 0.0, 'estado': 'CERRADA',
    })
    print(f"TEST 4 (post-ganadora): capital={float(g.capital_actual):.2f}, "
          f"perdidas={g.perdidas_consecutivas}")
    assert float(g.capital_actual) == 1009.0  # 1000 + 10 - 1

    # Test 5: 3 pérdidas consecutivas → CB
    for i in range(3):
        g.registrar_operacion({
            'ticket': 10 + i, 'simbolo': 'EURUSD', 'ganancia': -5.0,
            'comision': -1.0, 'swap': 0.0, 'estado': 'CERRADA',
            'contexto_apertura': {'regimen': 'CHOP_VOLATIL'},
        })

    print(f"TEST 5 (post-3 pérdidas): perdidas={g.perdidas_consecutivas}, "
          f"CB activo={g.circuit_breaker.verificar()}, "
          f"scope={g.circuit_breaker.scope.value}, "
          f"valor={g.circuit_breaker.scope_valor}")

    # Debería haber activado CB por símbolo o régimen
    assert g.circuit_breaker.activo is True
    assert g.circuit_breaker.scope in (ScopeBloqueo.SIMBOLO, ScopeBloqueo.REGIMEN)

    # Test 6: puede_operar_simbolo con CB activo
    puede, razon = g.puede_operar_simbolo('EURUSD')
    print(f"TEST 6 (EURUSD con CB): {puede} - {razon}")

    # Test 7: post-mortem
    pm = g.analizar_post_mortem()
    print(f"TEST 7 (post-mortem): patron={pm['patron_dominante']}, "
          f"scope={pm['scope_recomendado']}, valor={pm['scope_valor']}")

    # Test 8: desactivar CB → reactivación
    g.circuit_breaker.desactivar()
    factor = g.obtener_factor_riesgo_reactivacion()
    print(f"TEST 8 (post-desactivar): factor={factor}, reactivando={g.circuit_breaker.reactivacion.activa}")
    assert factor == 0.5
    assert g.circuit_breaker.reactivacion.activa is True

    # Test 9: 3 ganadoras → 100%
    for i in range(3):
        g.registrar_operacion({
            'ticket': 100 + i, 'simbolo': 'GBPUSD', 'ganancia': 5.0,
            'comision': -1.0, 'swap': 0.0, 'estado': 'CERRADA',
        })
    factor = g.obtener_factor_riesgo_reactivacion()
    print(f"TEST 9 (post-3 ganadoras): factor={factor}, reactivando={g.circuit_breaker.reactivacion.activa}")
    assert factor == 1.0
    assert g.circuit_breaker.reactivacion.activa is False

    # Test 10: estadísticas
    stats = g.estadisticas()
    print(f"\nTEST 10 (estadísticas):")
    print(f"   Capital: ${stats['capital_actual']:.2f}")
    print(f"   Total ops: {stats['total_operaciones']}")
    print(f"   Win rate: {stats['win_rate']:.1f}%")
    print(f"   Factor beneficio: {stats['factor_beneficio']:.2f}")
    print(f"   Reactivación activa: {stats['reactivacion_activa']}")
    print(f"   Factor reactivación: {stats['factor_riesgo_reactivacion']}")

    print("\n✅ Todos los tests pasan")