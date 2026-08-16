#!/usr/bin/env python3
"""
analysis/sniper.py (V9.0)
Lógica del sniper - Evaluación y decisión de entrada.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger('BotTrading.Sniper')


class SniperLoop:
    """
    Bucle del sniper - Evalúa oportunidades y decide entradas.
    RESPONSABILIDAD: Evaluar oportunidades, no ejecutar órdenes.
    """
    
    def __init__(self, orquestador, sniper, pipeline, horario):
        self.orquestador = orquestador
        self.sniper = sniper
        self.pipeline = pipeline
        self.horario = horario
        self.logger = logging.getLogger('BotTrading.Sniper')
    
    def ejecutar_ciclo(self):
        """Ejecuta un ciclo del sniper."""
        # Verificar horario
        if not self.horario.mercado_abierto():
            return
        
        # Obtener oportunidades del pipeline
        oportunidades = self._obtener_oportunidades()
        
        if not oportunidades:
            return
        
        # Evaluar cada oportunidad
        for oportunidad in oportunidades:
            self._evaluar_oportunidad(oportunidad)
    
    def _obtener_oportunidades(self) -> List[Dict]:
        """Obtiene oportunidades del pipeline."""
        estados = self.pipeline.obtener_activos()
        
        # Filtrar y ordenar
        oportunidades = []
        for estado in estados:
            if estado.fase_actual.value in ['FASE_2', 'FASE_3']:
                oportunidades.append({
                    'simbolo': estado.simbolo,
                    'estado': estado
                })
        
        oportunidades.sort(key=lambda x: x['estado'].score_acumulado, reverse=True)
        return oportunidades[:5]  # Máximo 5 por ciclo
    
    def _evaluar_oportunidad(self, oportunidad: Dict):
        """Evalúa una oportunidad específica."""
        simbolo = oportunidad['simbolo']
        estado = oportunidad['estado']
        
        # Verificar cooldown
        if simbolo in self.orquestador.estado.sniper_cooldown:
            if datetime.now(timezone.utc) < self.orquestador.estado.sniper_cooldown[simbolo]:
                return
        
        # Verificar posición abierta
        posiciones = self.orquestador.mt5.obtener_posiciones()
        if posiciones and any(p['simbolo'] == simbolo for p in posiciones):
            return
        
        # Obtener datos M5
        df_m5 = self.orquestador.obtener_datos_cached(
            simbolo=simbolo,
            n_velas=150,
            timeframe=5  # M5
        )
        
        if df_m5 is None or len(df_m5) < 50:
            return
        
        # Obtener contexto H1
        contexto_h1 = self.orquestador.estado.contexto_h1.get(simbolo, {})
        
        # Evaluar sniper
        resultado = self.sniper.evaluar(
            simbolo=simbolo,
            df_m5=df_m5,
            estado_pipeline=estado,
            contexto_h1=contexto_h1
        )
        
        if resultado:
            # Ejecutar operación
            self.orquestador.ejecutar_operacion(resultado)