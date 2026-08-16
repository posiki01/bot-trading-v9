#!/usr/bin/env python3
"""
trading/riesgo_circuit.py (V9.0)
Circuit Breaker para protección de capital.
RESPONSABILIDAD: Solo gestionar circuit breaker.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger('BotTrading.RiesgoCircuit')


class CircuitBreaker:
    """
    Sistema de Circuit Breaker para protección de capital.
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self, 
                 config: Optional[Any] = None,
                 almacen: Optional[Any] = None,
                 notificador: Optional[Any] = None):
        """
        Inicializa el Circuit Breaker.
        
        Args:
            config: Configuración
            almacen: Almacenamiento para persistencia
            notificador: Sistema de notificaciones
        """
        self.config = config
        self.almacen = almacen
        self.notificador = notificador
        self.logger = logging.getLogger('BotTrading.RiesgoCircuit')
        
        # Estado
        self.activo = False
        self.hasta: Optional[datetime] = None
        self.motivo: str = ""
        
        # Cargar configuración
        self._cargar_configuracion()
        
        # Restaurar estado
        self._restaurar_estado()
    
    def _cargar_configuracion(self):
        """Carga configuración desde Config."""
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
        
        # En demo, cooldown más corto
        if self.es_demo:
            self.cooldown_horas = min(self.cooldown_horas, 2)
    
    def _restaurar_estado(self):
        """Restaura el estado desde almacenamiento."""
        if not self.almacen:
            return
        
        try:
            config = self.almacen.obtener_configuracion()
            cb_data = config.get('circuit_breaker', {})
            
            if cb_data.get('activo', False):
                hasta_str = cb_data.get('hasta')
                if hasta_str:
                    hasta = datetime.fromisoformat(hasta_str)
                    ahora = datetime.now(timezone.utc)
                    
                    if ahora < hasta:
                        self.activo = True
                        self.hasta = hasta
                        self.motivo = cb_data.get('motivo', 'Restaurado')
                        self.logger.warning(f"🛡️ Circuit Breaker restaurado hasta {hasta}")
                    else:
                        # Expirado, desactivar
                        self._desactivar()
        except Exception as e:
            self.logger.warning(f"Error restaurando Circuit Breaker: {e}")
    
    # ============================================================
    # MÉTODOS PRINCIPALES
    # ============================================================
    
    def activar(self, motivo: str, horas: Optional[int] = None):
        """
        Activa el Circuit Breaker.
        
        Args:
            motivo: Motivo de activación
            horas: Duración en horas (opcional)
        """
        if self.activo:
            self.logger.info(f"Circuit Breaker ya activo: {self.motivo}")
            return
        
        # Duración
        if horas is None:
            horas = self.cooldown_horas
        
        # Seguridad
        horas = max(1, min(72, horas))
        if self.es_demo:
            horas = min(horas, 2)
        
        # Activar
        self.activo = True
        self.hasta = datetime.now(timezone.utc) + timedelta(hours=horas)
        self.motivo = motivo
        
        self.logger.error(f"🛡️ CIRCUIT BREAKER ACTIVADO: {motivo} (duración: {horas}h)")
        
        # Persistir
        self._persistir_estado()
        
        # Notificar
        if self.notificador:
            self.notificador.enviar(
                "🛡️ CIRCUIT BREAKER ACTIVADO",
                f"Motivo: {motivo}\nDuración: {horas} horas\nHasta: {self.hasta.strftime('%Y-%m-%d %H:%M UTC')}",
                tipo='error'
            )
    
    def desactivar(self):
        """
        Desactiva el Circuit Breaker.
        """
        if not self.activo:
            return
        
        self._desactivar()
        self.logger.info("✅ Circuit Breaker desactivado")
        
        # Notificar
        if self.notificador:
            self.notificador.enviar(
                "✅ CIRCUIT BREAKER DESACTIVADO",
                "El Circuit Breaker ha sido desactivado manualmente.",
                tipo='exito'
            )
    
    def _desactivar(self):
        """Desactiva internamente."""
        self.activo = False
        self.hasta = None
        self.motivo = ""
        self._persistir_estado()
    
    def verificar(self) -> bool:
        """
        Verifica si el Circuit Breaker está activo.
        
        Returns:
            True si está activo (no se puede operar)
        """
        if not self.activo:
            return False
        
        # Verificar si expiró
        if self.hasta and datetime.now(timezone.utc) >= self.hasta:
            self._desactivar()
            self.logger.info("✅ Circuit Breaker expirado automáticamente")
            return False
        
        return True
    
    def tiempo_restante(self) -> Optional[float]:
        """
        Obtiene el tiempo restante en minutos.
        
        Returns:
            Tiempo restante en minutos o None si no está activo
        """
        if not self.activo or not self.hasta:
            return None
        
        diff = (self.hasta - datetime.now(timezone.utc)).total_seconds() / 60
        return max(0, diff)
    
    # ============================================================
    # CONDICIONES DE ACTIVACIÓN
    # ============================================================
    
    def evaluar_perdidas_consecutivas(self, perdidas: int) -> bool:
        """
        Evalúa si se debe activar por pérdidas consecutivas.
        
        Args:
            perdidas: Número de pérdidas consecutivas
        
        Returns:
            True si se debe activar
        """
        if perdidas >= self.max_consecutive_losses:
            self.activar(
                f"{perdidas} pérdidas consecutivas (máx: {self.max_consecutive_losses})",
                self.cooldown_horas
            )
            return True
        return False
    
    def evaluar_drawdown(self, drawdown_actual: float, drawdown_max: float) -> bool:
        """
        Evalúa si se debe activar por drawdown.
        
        Args:
            drawdown_actual: Drawdown actual (0-1)
            drawdown_max: Drawdown máximo permitido (0-1)
        
        Returns:
            True si se debe activar
        """
        if drawdown_actual > drawdown_max and not self.es_demo:
            self.activar(
                f"Drawdown excedido: {drawdown_actual:.2%} > {drawdown_max:.2%}",
                24
            )
            return True
        return False
    
    def evaluar_capital(self, capital_actual: float, capital_inicial: float) -> bool:
        """
        Evalúa si se debe activar por pérdida de capital.
        
        Args:
            capital_actual: Capital actual
            capital_inicial: Capital inicial
        
        Returns:
            True si se debe activar
        """
        if capital_actual <= 0:
            self.activar("Capital agotado", 72)
            return True
        
        if capital_actual < capital_inicial * 0.7:
            self.activar(f"Capital bajo: ${capital_actual:.2f} (70% del inicial)", 48)
            return True
        
        return False
    
    # ============================================================
    # PERSISTENCIA
    # ============================================================
    
    def _persistir_estado(self):
        """Persiste el estado en almacenamiento."""
        if not self.almacen:
            return
        
        try:
            config = self.almacen.obtener_configuracion()
            config['circuit_breaker'] = {
                'activo': self.activo,
                'hasta': self.hasta.isoformat() if self.hasta else None,
                'motivo': self.motivo,
                'actualizado': datetime.now(timezone.utc).isoformat()
            }
            self.almacen.guardar_configuracion(config)
        except Exception as e:
            self.logger.warning(f"Error persistiendo Circuit Breaker: {e}")
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del Circuit Breaker."""
        return {
            'activo': self.activo,
            'motivo': self.motivo,
            'hasta': self.hasta.isoformat() if self.hasta else None,
            'tiempo_restante_minutos': self.tiempo_restante(),
            'cooldown_horas': self.cooldown_horas,
            'es_demo': self.es_demo,
        }