#!/usr/bin/env python3
"""
trading/riesgo.py (V9.65 - CORREGIDO DEFINITIVO)
Sistema de Gestión de Riesgo para el Bot de Trading.

V9.65 - CORRECCIONES CRÍTICAS:
- ✅ Obtiene capital REAL de MT5
- ✅ Verifica margen disponible real
- ✅ Previene operaciones con capital insuficiente
- ✅ Validación de lotes con límites estrictos por activo
- ✅ Contador de pérdidas por símbolo con alertas
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal, getcontext
from datetime import datetime, timezone, timedelta

# Importar submódulos
from trading.riesgo_lotes import CalculadorLotes
from trading.riesgo_circuit import CircuitBreaker

# Importar umbrales centralizados
try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Riesgo')


class GestionRiesgo:
    """
    Gestión de riesgo completa para el bot.
    V9.65 - CORREGIDO DEFINITIVO.
    """
    
    def __init__(self,
                 capital_inicial: float = 100.0,
                 aporte_mensual: float = 50.0,
                 almacen: Optional[Any] = None,
                 notificador: Optional[Any] = None,
                 config: Optional[Any] = None,
                 modo_backtest: bool = False,
                 mt5: Optional[Any] = None):
        """
        Inicializa la gestión de riesgo.
        V9.65 - CORREGIDO: Usa capital real de MT5 si está disponible.
        """
        getcontext().prec = 10
        
        self.config = config
        self.almacen = almacen
        self.notificador = notificador
        self.modo_backtest = modo_backtest
        self.mt5 = mt5
        self.logger = logging.getLogger('BotTrading.Riesgo')
        
        # ============================================================
        # 1. CAPITAL (✅ CORREGIDO V9.65)
        # ============================================================
        
        # ✅ Intentar obtener capital desde MT5 primero
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
        
        # Historial de capital
        self.historial_capital = [self.capital_actual]
        
        # ============================================================
        # 2. APORTES
        # ============================================================
        
        self.ultimo_aporte = datetime.now(timezone.utc)
        self.proximo_aporte = self.ultimo_aporte + timedelta(days=30)
        
        # ============================================================
        # 3. OPERACIONES
        # ============================================================
        
        self.operaciones: List[Dict[str, Any]] = []
        self.operaciones_hoy = 0
        self.ganancia_diaria = Decimal('0.0')
        self.perdida_diaria = Decimal('0.0')
        
        # ============================================================
        # 4. PÉRDIDAS CONSECUTIVAS
        # ============================================================
        
        self.perdidas_consecutivas = 0
        self.perdidas_consecutivas_por_simbolo: Dict[str, int] = {}
        
        # ============================================================
        # 5. CIRCUIT BREAKER
        # ============================================================
        
        self.circuit_breaker = CircuitBreaker(
            config=config,
            almacen=almacen,
            notificador=notificador
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
        # 8. CARGAR ESTADO (✅ CORREGIDO V9.65)
        # ============================================================
        
        self._cargar_estado()
        
        self.logger.info(f"💰 GestionRiesgo V9.65 CORREGIDO inicializado")
        self.logger.info(f"   Capital: ${float(self.capital_actual):,.2f}")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   MT5: {'✅' if mt5 else '❌'}")
    
    # ============================================================
    # CARGA DE ESTADO
    # ============================================================
    
    def _cargar_estado(self):
        """
        Carga estado desde almacenamiento.
        V9.65 - CORREGIDO: No sobrescribe capital si ya viene de MT5.
        """
        if not self.almacen:
            return
        
        try:
            config = self.almacen.obtener_configuracion()
            
            # Capital (✅ SOLO si no vino de MT5)
            if self.capital_actual == self.capital_inicial and not self.modo_backtest:
                last_cap = config.get('capital_actual')
                if last_cap is not None and float(last_cap) > 0:
                    self.capital_actual = Decimal(str(float(last_cap)))
                    self.total_aportado = Decimal(str(float(config.get('total_aportado', last_cap))))
                    self.logger.info(f"💰 Capital restaurado: ${float(self.capital_actual):,.2f}")
            
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
            
            # Pérdidas globales
            self.perdidas_consecutivas = int(config.get('consecutivas_perdidas', 0))
            
            # Último aporte
            ultimo_aporte_str = config.get('ultimo_aporte')
            if ultimo_aporte_str:
                try:
                    self.ultimo_aporte = datetime.fromisoformat(ultimo_aporte_str)
                    self.proximo_aporte = self.ultimo_aporte + timedelta(days=30)
                except:
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
    # ✅ NUEVO V9.65: OBTENER CAPITAL REAL DE MT5
    # ============================================================
    
    def obtener_capital_real(self) -> float:
        """
        Obtiene capital REAL desde MT5.
        V9.65 - CRÍTICO: Siempre usar capital actualizado.
        
        Returns:
            Capital actual en USD
        """
        if self.modo_backtest or self.mt5 is None:
            return float(self.capital_actual)
        
        try:
            cuenta = self.mt5.info_cuenta()
            if cuenta and cuenta.get('balance', 0) > 0:
                balance_real = float(cuenta['balance'])
                
                # Actualizar si es diferente
                if Decimal(str(balance_real)) != self.capital_actual:
                    self.logger.info(f"💰 Capital actualizado desde MT5: ${balance_real:,.2f}")
                    self.capital_actual = Decimal(str(balance_real))
                    self.historial_capital.append(self.capital_actual)
                
                return balance_real
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo capital de MT5: {e}")
        
        return float(self.capital_actual)
    
    def obtener_margen_libre(self) -> float:
        """
        Obtiene margen libre REAL desde MT5.
        V9.65 - CRÍTICO: Para validar si se puede abrir posiciones.
        
        Returns:
            Margen libre en USD
        """
        if self.modo_backtest or self.mt5 is None:
            return float(self.capital_actual) * 0.8  # Estimación
        
        try:
            cuenta = self.mt5.info_cuenta()
            if cuenta and cuenta.get('margin_free', 0) > 0:
                return float(cuenta['margin_free'])
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo margen libre: {e}")
        
        return float(self.capital_actual) * 0.8
    
    # ============================================================
    # MÉTODOS PRINCIPALES
    # ============================================================
    
    def puede_operar(self, 
                     equity_actual: Optional[float] = None,
                     margin_level: Optional[float] = None) -> Tuple[bool, str]:
        """
        Verifica si se puede operar.
        
        Args:
            equity_actual: Equity actual (opcional)
            margin_level: Nivel de margen (opcional)
        
        Returns:
            (puede_operar, razon)
        """
        # 1. Circuit Breaker
        if self.circuit_breaker.verificar():
            return False, f"Circuit Breaker activo: {self.circuit_breaker.motivo}"
        
        # 2. ✅ Obtener capital real
        capital_real = self.obtener_capital_real()
        
        if capital_real <= 1.0:
            return False, "Capital insuficiente"
        
        # 3. Límite de operaciones diarias
        if self.operaciones_hoy >= self._obtener_max_ops_dia():
            return False, "Límite diario de operaciones alcanzado"
        
        # 4. Pérdida diaria
        if self.perdida_diaria >= self._calcular_limite_perdida_diaria():
            return False, "Pérdida diaria máxima alcanzada"
        
        # 5. Drawdown
        if self._calcular_drawdown() > self._obtener_drawdown_maximo():
            if not self.modo_backtest:
                return False, "Drawdown máximo excedido"
        
        # 6. Equity
        if equity_actual and Decimal(str(equity_actual)) < self.capital_actual * Decimal('0.95'):
            if not self.modo_backtest:
                return False, "Equity por debajo del 95% del capital"
        
        # 7. Margen
        if margin_level is not None and margin_level < 200.0:
            return False, "Nivel de margen insuficiente"
        
        # 8. ✅ VERIFICAR MARGEN LIBRE
        margen_libre = self.obtener_margen_libre()
        if margen_libre < 50.0:
            return False, f"Margen libre insuficiente (${margen_libre:.2f} < $50)"
        
        return True, "OK"
    
    # ============================================================
    # CÁLCULO DE LOTES (CORREGIDO V9.65)
    # ============================================================
    
    def calcular_lotes(self, entrada: float, stop_loss: float, 
                   probabilidad: float, simbolo: str,
                   capital: Optional[float] = None,
                   **kwargs) -> float:
        """
        Calcula el tamaño de lote óptimo basado en el riesgo.
        V9.65 - CORREGIDO: Usa capital REAL de MT5.
        """
        from config.umbrales import Umbrales
        
        # ============================================================
        # 1. CAPITAL (✅ OBTENER REAL)
        # ============================================================
        if capital is None:
            capital = self.obtener_capital_real()
        
        if capital is None or capital <= 0:
            self.logger.error(f"❌ {simbolo}: Capital insuficiente")
            return 0.0
        
        if entrada <= 0 or stop_loss <= 0:
            self.logger.error(f"❌ {simbolo}: Precios inválidos")
            return 0.0
        
        # ============================================================
        # 2. DISTANCIA DEL SL
        # ============================================================
        sl_dist = abs(entrada - stop_loss)
        if sl_dist <= 0:
            self.logger.error(f"❌ {simbolo}: SL en entrada")
            return 0.0
        
        # ============================================================
        # 3. PIP SIZE
        # ============================================================
        pip_size = kwargs.get('pip_size', 0.0001)
        if pip_size <= 0:
            pip_size = self._obtener_pip_size(simbolo)
        
        sl_pips = sl_dist / pip_size if pip_size > 0 else 10
        if sl_pips <= 0:
            sl_pips = 10
        
        # ============================================================
        # 4. RIESGO POR ACTIVO
        # ============================================================
        simbolo_upper = simbolo.upper()
        riesgo_max_por_operacion = getattr(Umbrales, 'RIESGO_MAX_POR_OPERACION', {})
        riesgo_pct = riesgo_max_por_operacion.get(simbolo_upper, 0.01)
        
        # Ajuste por probabilidad
        if probabilidad > 70:
            riesgo_pct = min(riesgo_pct * 1.1, 0.02)
        elif probabilidad < 40:
            riesgo_pct = riesgo_pct * 0.7
        
        # Límites
        riesgo_pct = min(riesgo_pct, 0.02)
        riesgo_pct = max(riesgo_pct, 0.001)
        
        # ============================================================
        # 5. ✅ VERIFICAR MARGEN DISPONIBLE
        # ============================================================
        margen_libre = self.obtener_margen_libre()
        
        # Calcular lotes por riesgo
        riesgo_dinero = capital * riesgo_pct
        tick_value = kwargs.get('tick_value', 0.01)
        tick_size = kwargs.get('tick_size', 0.00001)
        point = kwargs.get('point', 0.00001)
        
        valor_pip = self._calcular_valor_pip(simbolo, entrada, tick_value, tick_size, point, pip_size)
        if valor_pip <= 0:
            valor_pip = 1.0
        
        lotes_por_riesgo = riesgo_dinero / (sl_pips * valor_pip) if sl_pips > 0 and valor_pip > 0 else 0.01
        
        # ============================================================
        # 6. LÍMITES POR ACTIVO
        # ============================================================
        lotes_max_por_activo = getattr(Umbrales, 'LOTES_MAX_POR_ACTIVO', {})
        lotes_min_por_activo = getattr(Umbrales, 'LOTES_MIN_POR_ACTIVO', {})
        
        lote_min = lotes_min_por_activo.get(simbolo_upper, 0.01)
        lote_max = lotes_max_por_activo.get(simbolo_upper, 0.10)
        
        # Límites especiales para XAUUSD
        if 'XAU' in simbolo_upper:
            lote_max = min(lote_max, 0.05)
            if capital < 1000:
                lote_max = min(lote_max, 0.02)
            elif capital < 2000:
                lote_max = min(lote_max, 0.03)
        
        # Factor por capital
        if capital < 5000:
            factor_capital = max(0.3, capital / 5000)
            lote_max = max(lote_min, lote_max * factor_capital)
        
        # ============================================================
        # 7. ✅ LIMITAR POR MARGEN DISPONIBLE
        # ============================================================
        margen_por_lote = self._estimar_margen(simbolo, 1.0, entrada)
        
        if margen_por_lote > 0:
            lotes_max_por_margen = margen_libre / margen_por_lote
            lotes_max_por_margen = round(lotes_max_por_margen / 0.01) * 0.01
            
            if lotes_max_por_margen < lote_min:
                self.logger.warning(f"⚠️ {simbolo}: Margen insuficiente para lote mínimo")
                return 0.0
            
            lote_max = min(lote_max, lotes_max_por_margen)
        
        # ============================================================
        # 8. APLICAR LÍMITES
        # ============================================================
        lotes = max(lote_min, min(lote_max, lotes_por_riesgo))
        
        # Redondear
        paso = 0.01
        lotes = round(lotes / paso) * paso
        if lotes < lote_min:
            lotes = lote_min
        
        self.logger.info(f"📊 {simbolo}: Lotes={lotes:.3f} (riesgo: {riesgo_pct*100:.2f}%)")
        self.logger.info(f"   Capital: ${capital:.2f} | Margen libre: ${margen_libre:.2f}")
        
        return lotes

    def _obtener_pip_size(self, simbolo: str) -> float:
        """Obtiene el tamaño del pip para el símbolo."""
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 0.01
        elif 'XAU' in simbolo_upper:
            return 0.01
        elif 'XAG' in simbolo_upper:
            return 0.1
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        else:
            return 0.0001


    def _calcular_valor_pip(self,
                            simbolo: str,
                            entrada: float,
                            tick_value: Optional[float],
                            tick_size: Optional[float],
                            point: Optional[float],
                            pip_size: float) -> float:
        """Calcula el valor de 1 pip en la moneda de la cuenta."""
        try:
            simbolo_upper = simbolo.upper()
            
            # 1. Usar tick_value del broker si está disponible
            if tick_value is not None and tick_size is not None and tick_value > 0 and tick_size > 0:
                return tick_value / tick_size * pip_size
            
            # 2. Fallback por tipo de activo
            if 'XAU' in simbolo_upper:
                return 0.10  # $0.10 por pip para 0.01 lotes
            elif 'XAG' in simbolo_upper:
                return 1.0
            elif 'JPY' in simbolo_upper:
                return 1.0 / 100
            elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
                return 1.0
            elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                return 1.0
            else:
                return 1.0  # Forex estándar: $1 por pip para 0.01 lotes
                
        except Exception as e:
            self.logger.warning(f"⚠️ Error calculando valor pip para {simbolo}: {e}")
            return 1.0


    def _estimar_margen(self, simbolo: str, lotes: float, precio: float) -> float:
        """Estima el margen requerido para una operación."""
        simbolo_upper = simbolo.upper()
        
        # Apalancamiento típico
        apalancamiento = 30
        
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            apalancamiento = 20
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            apalancamiento = 20
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            apalancamiento = 10
        
        # Tamaño del contrato
        contract_size = 100000
        
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            contract_size = 100
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            contract_size = 1
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            contract_size = 1
        
        valor_operacion = lotes * contract_size * precio
        margen = valor_operacion / apalancamiento
        
        return margen
    
    # ============================================================
    # REGISTRO DE OPERACIONES
    # ============================================================
    
    def registrar_operacion(self, resultado: Dict[str, Any]):
        """
        Registra una operación cerrada.
        
        Args:
            resultado: Datos de la operación
        """
        ganancia_bruta = Decimal(str(resultado.get('ganancia', 0.0)))
        comision = Decimal(str(resultado.get('comision', 0.0)))
        swap = Decimal(str(resultado.get('swap', 0.0)))
        ganancia_neta = ganancia_bruta + comision + swap
        
        simbolo = resultado.get('simbolo', '')
        ticket = resultado.get('ticket')
        
        # Verificar si ya existe
        if ticket:
            existe = any(o.get('ticket') == ticket for o in self.operaciones)
            if existe:
                self.logger.debug(f"Operación {ticket} ya registrada")
                return
        
        # Actualizar contadores
        self.operaciones_hoy += 1
        
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
        
        # Guardar operación
        op = {
            **resultado,
            'ganancia_neta': float(ganancia_neta),
            'timestamp': resultado.get('timestamp', datetime.now(timezone.utc).isoformat()),
            'capital_despues': float(self.capital_actual),
        }
        self.operaciones.append(op)
        
        # Guardar en almacenamiento
        if self.almacen:
            try:
                self.almacen.guardar_operacion(op)
            except Exception as e:
                self.logger.warning(f"Error guardando operación: {e}")
        
        # Guardar estado
        self._guardar_estado()
        
        # Verificar Circuit Breaker
        self._verificar_circuit_breaker()
        
        # Verificar cambio de etapa
        self._verificar_cambio_etapa()
        
        self.logger.info(
            f"📊 Operación registrada: {simbolo} | PnL: {ganancia_neta:+.2f} | "
            f"Capital: ${float(self.capital_actual):,.2f}"
        )
        
        # ✅ NUEVO V9.65: ALERTA POR PÉRDIDAS CONSECUTIVAS EN SÍMBOLO
        if self.perdidas_consecutivas_por_simbolo.get(simbolo, 0) >= 3:
            self.logger.warning(f"⚠️ {simbolo}: {self.perdidas_consecutivas_por_simbolo[simbolo]} pérdidas consecutivas")
            if self.notificador:
                self.notificador.enviar(
                    "⚠️ ALERTA PÉRDIDAS",
                    f"{simbolo}: {self.perdidas_consecutivas_por_simbolo[simbolo]} pérdidas consecutivas",
                    tipo='warning'
                )
    
    def _verificar_circuit_breaker(self):
        """Verifica condiciones de Circuit Breaker."""
        # Pérdidas consecutivas
        if self.circuit_breaker.evaluar_perdidas_consecutivas(self.perdidas_consecutivas):
            self.logger.warning(f"🛡️ Circuit Breaker activado por {self.perdidas_consecutivas} pérdidas consecutivas")
        
        # Drawdown
        drawdown = self._calcular_drawdown()
        drawdown_max = self._obtener_drawdown_maximo()
        if self.circuit_breaker.evaluar_drawdown(drawdown, drawdown_max):
            self.logger.warning(f"🛡️ Circuit Breaker activado por drawdown: {drawdown:.2%}")
        
        # Capital
        if self.circuit_breaker.evaluar_capital(float(self.capital_actual), float(self.capital_inicial)):
            self.logger.warning(f"🛡️ Circuit Breaker activado por capital bajo")
    
    # ============================================================
    # APORTES
    # ============================================================
    
    def verificar_aporte(self) -> bool:
        """
        Verifica si se debe realizar el aporte mensual.
        
        Returns:
            True si se realizó el aporte
        """
        ahora = self.sim_current_time if self.sim_current_time else datetime.now(timezone.utc)
        
        if ahora >= self.proximo_aporte and self.aporte_mensual > 0:
            return self._realizar_aporte(ahora)
        
        return False
    
    def _realizar_aporte(self, fecha: datetime) -> bool:
        """
        Realiza el aporte mensual.
        
        Args:
            fecha: Fecha del aporte
        
        Returns:
            True si se realizó correctamente
        """
        self.capital_actual += self.aporte_mensual
        self.total_aportado += self.aporte_mensual
        self.ultimo_aporte = fecha
        self.proximo_aporte = fecha + timedelta(days=30)
        self.historial_capital.append(self.capital_actual)
        
        self._guardar_estado()
        self._verificar_cambio_etapa()
        
        self.logger.info(f"💰 Aporte mensual: +${float(self.aporte_mensual):.2f}")
        
        if self.notificador:
            self.notificador.enviar(
                "💰 APORTE MENSUAL",
                f"Monto: +${float(self.aporte_mensual):.2f}\n"
                f"Capital actual: ${float(self.capital_actual):,.2f}",
                tipo='exito'
            )
        
        return True
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def estadisticas(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas completas.
        
        Returns:
            Diccionario con estadísticas
        """
        # ✅ Obtener capital real
        capital_real = self.obtener_capital_real()
        
        # Estadísticas básicas
        stats = {
            'capital_actual': capital_real,
            'capital_inicial': float(self.capital_inicial),
            'total_aportado': float(self.total_aportado),
            'ganancia_neta': float(capital_real - float(self.capital_inicial)),
            'rendimiento': float((capital_real / float(self.capital_inicial) - 1) * 100),
            'ganancia_diaria': float(self.ganancia_diaria),
            'perdida_diaria': float(self.perdida_diaria),
            'operaciones_hoy': self.operaciones_hoy,
            'total_operaciones': len(self.operaciones),
            'perdidas_consecutivas': self.perdidas_consecutivas,
            'etapa': self.ultima_etapa,
            'circuit_breaker': self.circuit_breaker.get_stats(),
            'margen_libre': self.obtener_margen_libre(),
        }
        
        # Win Rate
        if self.operaciones:
            ganadoras = sum(1 for o in self.operaciones if o.get('ganancia_neta', 0) > 0)
            stats['win_rate'] = (ganadoras / len(self.operaciones)) * 100
        else:
            stats['win_rate'] = 0.0
        
        # Factor de beneficio
        gross_profit = sum(o.get('ganancia_neta', 0) for o in self.operaciones if o.get('ganancia_neta', 0) > 0)
        gross_loss = sum(abs(o.get('ganancia_neta', 0)) for o in self.operaciones if o.get('ganancia_neta', 0) < 0)
        stats['factor_beneficio'] = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Operaciones por símbolo
        por_simbolo = {}
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
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def _calcular_etapa(self) -> int:
        """
        Calcula la etapa actual basada en el capital.
        
        Returns:
            Etapa (1-4)
        """
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
                self.notificador.enviar(
                    "🎯 CAMBIO DE ETAPA",
                    f"Capital: ${float(self.capital_actual):,.2f}\n"
                    f"Etapa: {etapa_actual}",
                    tipo='exito'
                )
    
    def _calcular_limite_perdida_diaria(self) -> Decimal:
        """
        Calcula el límite de pérdida diaria.
        
        Returns:
            Límite de pérdida diaria
        """
        return self.capital_actual * Decimal('0.03')
    
    def _obtener_drawdown_maximo(self) -> float:
        """
        Obtiene el drawdown máximo permitido.
        
        Returns:
            Drawdown máximo (0-1)
        """
        if self.config:
            return getattr(self.config, 'MAX_DAILY_DRAWDOWN_PCT', 0.06)
        return 0.06
    
    def _obtener_max_ops_dia(self) -> int:
        """
        Obtiene el máximo de operaciones por día.
        
        Returns:
            Máximo de operaciones
        """
        if self.config:
            return getattr(self.config, 'MAX_OPERATIONS_PER_DAY', 8)
        return 8
    
    def _calcular_drawdown(self) -> float:
        """
        Calcula el drawdown actual.
        
        Returns:
            Drawdown (0-1)
        """
        if self.total_aportado > 0:
            return float((self.total_aportado - self.capital_actual) / self.total_aportado)
        return 0.0
    
    def obtener_max_simultaneas(self, equity_actual: Optional[float] = None) -> int:
        """
        Obtiene el máximo de operaciones simultáneas.
        
        Args:
            equity_actual: Equity actual (opcional)
        
        Returns:
            Máximo de operaciones simultáneas
        """
        etapa = self._calcular_etapa()
        base_por_etapa = {1: 3, 2: 3, 3: 4, 4: 5}
        max_base = base_por_etapa.get(etapa, 3)
        
        if equity_actual:
            equity = Decimal(str(equity_actual))
            if self.capital_actual > 0 and equity < self.capital_actual * Decimal('0.95'):
                return max(1, max_base - 1)
        
        return max_base
    
    def obtener_etapa_actual(self) -> int:
        """Obtiene la etapa actual."""
        return self.ultima_etapa
    
    def reset_diario(self, current_time: Optional[datetime] = None):
        """
        Resetea los contadores diarios.
        
        Args:
            current_time: Tiempo de referencia
        """
        self.perdida_diaria = Decimal('0.0')
        self.ganancia_diaria = Decimal('0.0')
        self.operaciones_hoy = 0
        self.sim_current_time = current_time
        self.equity_inicio_dia = float(self.capital_actual)
        
        self.logger.info("📊 Contadores diarios reseteados")


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_gestion_riesgo(capital_inicial: float = 100.0,
                          aporte_mensual: float = 50.0,
                          almacen: Optional[Any] = None,
                          notificador: Optional[Any] = None,
                          config: Optional[Any] = None,
                          modo_backtest: bool = False,
                          mt5: Optional[Any] = None) -> GestionRiesgo:
    """
    Crea una instancia de GestionRiesgo.
    
    Args:
        capital_inicial: Capital inicial
        aporte_mensual: Aporte mensual
        almacen: Almacenamiento SQLite
        notificador: Sistema de notificaciones
        config: Configuración
        modo_backtest: Modo backtest
        mt5: Conector MT5 (para capital real)
    
    Returns:
        GestionRiesgo
    """
    return GestionRiesgo(
        capital_inicial=capital_inicial,
        aporte_mensual=aporte_mensual,
        almacen=almacen,
        notificador=notificador,
        config=config,
        modo_backtest=modo_backtest,
        mt5=mt5
    )