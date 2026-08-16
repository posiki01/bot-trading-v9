#!/usr/bin/env python3
"""
trading/riesgo.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Sistema de Gestión de Riesgo para el Bot de Trading.

RESPONSABILIDADES:
- Gestión de capital y drawdown
- Circuit Breaker
- Registro de operaciones
- Estadísticas de rendimiento
- Control de pérdidas consecutivas

MEJORAS V9.0:
- Separación de responsabilidades en submódulos
- Integración con umbrales centralizados
- Cálculo de lotes optimizado
- Circuit Breaker independiente
- Validaciones robustas
- Logs más informativos
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
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    def __init__(self,
                 capital_inicial: float = 100.0,
                 aporte_mensual: float = 50.0,
                 almacen: Optional[Any] = None,
                 notificador: Optional[Any] = None,
                 config: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa la gestión de riesgo.
        
        Args:
            capital_inicial: Capital inicial
            aporte_mensual: Aporte mensual
            almacen: Almacenamiento SQLite
            notificador: Sistema de notificaciones
            config: Configuración
            modo_backtest: Modo backtest
        """
        getcontext().prec = 10
        
        self.config = config
        self.almacen = almacen
        self.notificador = notificador
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Riesgo')
        
        # ============================================================
        # 1. CAPITAL
        # ============================================================
        
        self.capital_inicial = Decimal(str(capital_inicial))
        self.capital_actual = Decimal(str(capital_inicial))
        self.total_aportado = Decimal(str(capital_inicial))
        self.aporte_mensual = Decimal(str(aporte_mensual))
        
        # Historial de capital
        self.historial_capital = [Decimal(str(capital_inicial))]
        
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
        # 8. CARGAR ESTADO
        # ============================================================
        
        self._cargar_estado()
        
        self.logger.info(f"💰 GestionRiesgo V9.0 inicializado")
        self.logger.info(f"   Capital: ${float(self.capital_actual):,.2f}")
        self.logger.info(f"   Backtest: {modo_backtest}")
    
    # ============================================================
    # CARGA DE ESTADO
    # ============================================================
    
    def _cargar_estado(self):
        """Carga estado desde almacenamiento."""
        if not self.almacen:
            return
        
        try:
            config = self.almacen.obtener_configuracion()
            
            # Capital
            last_cap = config.get('capital_actual')
            if last_cap is not None:
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
        
        # 2. Capital
        if self.capital_actual <= Decimal('1.0'):
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
        
        return True, "OK"
    
    # ============================================================
    # CÁLCULO DE LOTES
    # ============================================================
    
    def calcular_lotes(self,
                       entrada: float,
                       stop_loss: float,
                       probabilidad: float,
                       tick_value: float = 0.01,
                       tick_size: float = 0.00001,
                       point: float = 0.00001,
                       simbolo: str = "",
                       atr: float = 0.001,
                       atr_medio: float = 0.001,
                       spread: float = 0.0,
                       margin_level: Optional[float] = None,
                       equity_referencia: Optional[float] = None) -> float:
        """
        Calcula el tamaño de posición.
        
        Args:
            entrada: Precio de entrada
            stop_loss: Precio de stop loss
            probabilidad: Probabilidad de éxito (0-100)
            tick_value: Valor del tick
            tick_size: Tamaño del tick
            point: Punto del símbolo
            simbolo: Símbolo
            atr: ATR actual
            atr_medio: ATR medio
            spread: Spread actual
            margin_level: Nivel de margen
            equity_referencia: Equity de referencia
        
        Returns:
            Lotes calculados
        """
        # Si Circuit Breaker está activo, no calcular lotes
        if self.circuit_breaker.verificar():
            return 0.0
        
        # Capital de referencia
        cap_ref = float(equity_referencia) if equity_referencia else float(self.capital_actual)
        if cap_ref <= 0:
            cap_ref = float(self.capital_actual)
        
        # Factores
        factor_volatilidad = self.calculador_lotes.calcular_factor_volatilidad(atr, entrada) if atr > 0 and entrada > 0 else 1.0
        
        # Factor de convicción (Kelly simplificado)
        if probabilidad >= 90.0:
            factor_conviccion = 1.2
        elif probabilidad >= 80.0:
            factor_conviccion = 1.0
        elif probabilidad >= 65.0:
            factor_conviccion = 0.8
        else:
            factor_conviccion = 0.5
        
        # Calcular lotes
        lotes = self.calculador_lotes.calcular_lotes(
            entrada=entrada,
            stop_loss=stop_loss,
            probabilidad=probabilidad,
            simbolo=simbolo,
            capital=cap_ref,
            tick_value=tick_value,
            tick_size=tick_size,
            point=point,
            atr=atr,
            atr_medio=atr_medio,
            spread=spread,
            margin_level=margin_level,
            factor_volatilidad=factor_volatilidad,
            factor_conviccion=factor_conviccion
        )
        
        # Ajuste por pérdidas consecutivas
        if self.perdidas_consecutivas >= 2:
            lotes *= 0.7
        elif self.perdidas_consecutivas >= 1:
            lotes *= 0.9
        
        return max(0.01, min(self.calculador_lotes.max_lote_absoluto, lotes))
    
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
        # Estadísticas básicas
        stats = {
            'capital_actual': float(self.capital_actual),
            'capital_inicial': float(self.capital_inicial),
            'total_aportado': float(self.total_aportado),
            'ganancia_neta': float(self.capital_actual - self.capital_inicial),
            'rendimiento': float((self.capital_actual / self.capital_inicial - 1) * 100),
            'ganancia_diaria': float(self.ganancia_diaria),
            'perdida_diaria': float(self.perdida_diaria),
            'operaciones_hoy': self.operaciones_hoy,
            'total_operaciones': len(self.operaciones),
            'perdidas_consecutivas': self.perdidas_consecutivas,
            'etapa': self.ultima_etapa,
            'circuit_breaker': self.circuit_breaker.get_stats(),
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
        cap = self.capital_actual
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
                          modo_backtest: bool = False) -> GestionRiesgo:
    """
    Crea una instancia de GestionRiesgo.
    
    Args:
        capital_inicial: Capital inicial
        aporte_mensual: Aporte mensual
        almacen: Almacenamiento SQLite
        notificador: Sistema de notificaciones
        config: Configuración
        modo_backtest: Modo backtest
    
    Returns:
        GestionRiesgo
    """
    return GestionRiesgo(
        capital_inicial=capital_inicial,
        aporte_mensual=aporte_mensual,
        almacen=almacen,
        notificador=notificador,
        config=config,
        modo_backtest=modo_backtest
    )