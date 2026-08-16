#!/usr/bin/env python3
"""
analysis/escaneo.py (V9.0)
Escaneo de mercado - Responsabilidad única.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import concurrent.futures

logger = logging.getLogger('BotTrading.Escaneo')


class Escaneador:
    """
    Escanea el mercado en busca de oportunidades.
    RESPONSABILIDAD: Solo escanear, no tomar decisiones.
    """
    
    def __init__(self, orquestador, analisis_capas, regimen_filter,
                 nivel_tracker, horario):
        self.orquestador = orquestador
        self.analisis_capas = analisis_capas
        self.regimen_filter = regimen_filter
        self.nivel_tracker = nivel_tracker
        self.horario = horario
        self.logger = logging.getLogger('BotTrading.Escaneo')
    
    def ejecutar_escaneo(self) -> Dict[str, Any]:
        """
        Ejecuta un escaneo completo del mercado.
        
        Returns:
            Dict con resultados del escaneo
        """
        self.logger.info("🔍 Iniciando escaneo de mercado...")
        
        # Verificar horario
        if not self.horario.mercado_abierto():
            self.logger.info("🌙 Mercado cerrado, omitiendo escaneo")
            return {}
        
        simbolos = self._obtener_simbolos_a_escanear()
        resultados = {}
        
        # Escanear en paralelo
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self._escanear_simbolo, s): s
                for s in simbolos
            }
            
            for future in concurrent.futures.as_completed(futures):
                simbolo = futures[future]
                try:
                    resultado = future.result(timeout=30)
                    if resultado:
                        resultados[simbolo] = resultado
                except Exception as e:
                    self.logger.warning(f"⚠️ Error escaneando {simbolo}: {e}")
        
        self.logger.info(f"✅ Escaneo completado: {len(resultados)} oportunidades encontradas")
        return resultados
    
    def _obtener_simbolos_a_escanear(self) -> List[str]:
        """Obtiene la lista de símbolos a escanear."""
        return self.orquestador.config.SIMBOLOS_COMPLETOS
    
    def _escanear_simbolo(self, simbolo: str) -> Optional[Dict]:
        """Escanea un símbolo individual."""
        try:
            # Obtener datos H1
            df_h1 = self.orquestador.obtener_datos_cached(
                simbolo=simbolo,
                n_velas=250,
                timeframe=60  # H1
            )
            
            if df_h1 is None or len(df_h1) < 100:
                return None
            
            # Análisis rápido
            rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
            if not rapido.pasa_filtro:
                return None
            
            # Detectar niveles
            niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
                simbolo=simbolo,
                df=df_h1,
                precio_actual=df_h1['Close'].iloc[-1]
            )
            
            # Análisis medio
            medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
            if not medio.pasa_filtro:
                return None
            
            # Régimen de mercado
            regimen_data = self.regimen_filter.clasificar(simbolo, df_h1, df_h1)
            
            # Determinar dirección
            direccion = self._determinar_direccion(medio)
            
            # Construir resultado
            return {
                'simbolo': simbolo,
                'score': medio._datos_extra.get('score_h1', 0),
                'direccion': direccion,
                'regimen': regimen_data.regimen.value,
                'niveles': {
                    'soporte': medio.soporte_cercano,
                    'resistencia': medio.resistencia_cercana,
                    'soporte_hits': medio.soporte_hits,
                    'resistencia_hits': medio.resistencia_hits
                },
                'timestamp': datetime.now(timezone.utc),
                'analisis': {
                    'rapido': rapido,
                    'medio': medio,
                }
            }
            
        except Exception as e:
            self.logger.debug(f"Error escaneando {simbolo}: {e}")
            return None
    
    def _determinar_direccion(self, medio) -> str:
        """Determina la dirección del análisis."""
        if medio.rsi > 60 and medio.macd_histogram > 0:
            return 'COMPRA'
        elif medio.rsi < 40 and medio.macd_histogram < 0:
            return 'VENTA'
        return 'NEUTRAL'