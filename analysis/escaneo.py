#!/usr/bin/env python3
"""
analysis/escaneo.py (V9.1 - CORREGIDO)
Sistema de escaneo de mercado con logs detallados por fase.
"""

import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from analysis.regimen import RegimenMercado
from analysis.capas import AnalisisPorCapas
from utils.logger_latencia import medir_latencia

logger = logging.getLogger('BotTrading.Escaneo')


class Escaneador:
    """
    Sistema de escaneo de mercado con logs detallados por fase.
    V9.1 - Con logs de niveles mejorados.
    """
    
    def __init__(self, orquestador: Any, analisis_capas: AnalisisPorCapas,
             regimen_filter: Any, nivel_tracker: Any, horario: Any,
             score_engine: Any, pipeline: Any):
        """
        Inicializa el escaneador.
        
        Args:
            orquestador: Orquestador principal
            analisis_capas: Análisis por capas
            regimen_filter: Filtro de régimen
            nivel_tracker: Tracker de niveles
            horario: Horario de mercado
        """
        self.orquestador = orquestador
        self.analisis_capas = analisis_capas
        self.regimen_filter = regimen_filter
        self.nivel_tracker = nivel_tracker
        self.horario = horario
        self.score_engine = score_engine  # ✅ AÑADIR ESTO
        self.pipeline = pipeline  # ✅ AÑADIR ESTO
        self.logger = logger
        
        # Estadísticas
        self._stats = {
            'total_escaneos': 0,
            'simbolos_escaneados': 0,
            'oportunidades_encontradas': 0,
            'tiempo_promedio': 0,
            'total_soportes_detectados': 0,
            'total_resistencias_detectadas': 0,
        }
        
        self.logger.info("🔍 Escaneador V9.1 con logs de niveles mejorados inicializado")
    
    @medir_latencia("escaneo_completo", plataforma="SISTEMA")
    def ejecutar_escaneo(self, simbolos: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Ejecuta un escaneo completo del mercado con logs por fase.
        V9.2 - CORREGIDO: No bloquea cripto en domingo.
        """
        inicio = time.time()
        self._stats['total_escaneos'] += 1
        
        # ✅ CORRECCIÓN: NO verificar horario global, verificar por símbolo
        # if not self.horario.mercado_abierto():
        #     self.logger.info("🌙 Mercado cerrado, omitiendo escaneo")
        #     return []
        
        # Si no se especifican símbolos, usar los de la configuración
        if simbolos is None:
            simbolos = self.orquestador.config.SIMBOLOS_OPERABLES
        
        # ✅ CORRECCIÓN: Filtrar SOLO por símbolos operables (cripto 24/7)
        simbolos_operables = []
        simbolos_no_operables = []
        
        for simbolo in simbolos:
            es_operativo, razon = self.horario.es_horario_operativo(simbolo)
            if es_operativo:
                simbolos_operables.append(simbolo)
            else:
                simbolos_no_operables.append(simbolo)
        
        # Log de símbolos no operables
        if simbolos_no_operables:
            self.logger.info(f"⏭️ Símbolos NO operables: {len(simbolos_no_operables)}")
            for simbolo in simbolos_no_operables[:5]:
                es_op, razon = self.horario.es_horario_operativo(simbolo)
                self.logger.info(f"   {simbolo}: {razon}")
        
        self.logger.info(f"📊 Símbolos operables: {len(simbolos_operables)}/{len(simbolos)}")
        
        oportunidades = []
        simbolos_procesados = 0
        total_soportes = 0
        total_resistencias = 0
        
        for simbolo in simbolos_operables:
            try:
                resultado = self._escanear_simbolo(simbolo)
                if resultado:
                    oportunidades.append(resultado)
                    # Acumular estadísticas de niveles
                    if 'niveles' in resultado:
                        total_soportes += len(resultado['niveles'].get('soportes', []))
                        total_resistencias += len(resultado['niveles'].get('resistencias', []))
                simbolos_procesados += 1
            except Exception as e:
                self.logger.warning(f"⚠️ Error escaneando {simbolo}: {e}")
        
        self._stats['simbolos_escaneados'] = simbolos_procesados
        self._stats['oportunidades_encontradas'] = len(oportunidades)
        self._stats['total_soportes_detectados'] += total_soportes
        self._stats['total_resistencias_detectadas'] += total_resistencias
        
        tiempo = time.time() - inicio
        self._stats['tiempo_promedio'] = tiempo
        
        self.logger.info(f"✅ Escaneo completado: {len(oportunidades)} oportunidades encontradas ({simbolos_procesados} símbolos en {tiempo*1000:.0f}ms)")
        self.logger.info(f"📊 Totales acumulados: {total_soportes} soportes, {total_resistencias} resistencias")
        
        return oportunidades
    
    def _escanear_simbolo(self, simbolo: str) -> Optional[Dict]:
        """
        Escanea un símbolo individual con logs detallados por fase.
        """
        self.logger.info(f"🔍 INICIANDO ESCANEO DE {simbolo}")
        
        # ============================================================
        # FASE 1: OBTENER DATOS
        # ============================================================
        
        self.logger.info(f"📊 {simbolo}: FASE 1 - Obteniendo datos H1...")
        df_h1 = self.orquestador.cache.get_datos(
            simbolo=simbolo,
            timeframe=60,
            n_velas=250,
            fetch_func=self.orquestador.mt5.obtener_datos
        )
        
        if df_h1 is None or len(df_h1) < 100:
            self.logger.warning(f"❌ {simbolo}: FASE 1 FALLÓ - Datos insuficientes")
            return None
        
        self.logger.info(f"✅ {simbolo}: FASE 1 COMPLETADA - {len(df_h1)} velas obtenidas")
        self.logger.info(f"   Último precio: {df_h1['Close'].iloc[-1]:.5f}")
        
        # ============================================================
        # FASE 2: ANÁLISIS RÁPIDO
        # ============================================================
        
        self.logger.info(f"⚡ {simbolo}: FASE 2 - Análisis rápido...")
        rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
        
        if rapido is None:
            self.logger.warning(f"❌ {simbolo}: FASE 2 FALLÓ - Análisis rápido devolvió None")
            return None
        
        if not rapido.pasa_filtro:
            self.logger.info(f"⏭️ {simbolo}: FASE 2 RECHAZADA - {rapido.razon_rechazo}")
            return None
        
        self.logger.info(f"✅ {simbolo}: FASE 2 COMPLETADA")
        self.logger.info(f"   RSI: {rapido.rsi:.1f}")
        self.logger.info(f"   Volumen relativo: {rapido.volumen_relativo:.2f}x")
        
        # ============================================================
        # FASE 3: DETECCIÓN DE NIVELES (CON LOGS MEJORADOS)
        # ============================================================
        
        self.logger.info(f"📊 {simbolo}: FASE 3 - Detectando niveles...")
        precio_actual = df_h1['Close'].iloc[-1]
        
        niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
            simbolo=simbolo,
            df=df_h1,
            precio_actual=precio_actual
        )
        
        soportes = niveles.get('soportes', [])
        resistencias = niveles.get('resistencias', [])
        
        self.logger.info(f"✅ {simbolo}: FASE 3 COMPLETADA")
        self.logger.info(f"   Soportes: {len(soportes)}")
        self.logger.info(f"   Resistencias: {len(resistencias)}")
        
        # ✅ LOG DETALLADO DE NIVELES (si hay)
        if soportes:
            self.logger.info(f"   📉 Soportes (top 5):")
            for i, s in enumerate(soportes[:5]):
                if isinstance(s, dict):
                    precio = s['precio']
                    hits = s.get('hits', 0)
                    fuerza = s.get('fuerza', 'N/A')
                    self.logger.info(f"      {i+1}. {precio:.5f} (hits: {hits}, fuerza: {fuerza})")
                else:
                    self.logger.info(f"      {i+1}. {s:.5f}")
        else:
            self.logger.info(f"   ℹ️ No hay soportes acumulados todavía")
        
        if resistencias:
            self.logger.info(f"   📈 Resistencias (top 5):")
            for i, r in enumerate(resistencias[:5]):
                if isinstance(r, dict):
                    precio = r['precio']
                    hits = r.get('hits', 0)
                    fuerza = r.get('fuerza', 'N/A')
                    self.logger.info(f"      {i+1}. {precio:.5f} (hits: {hits}, fuerza: {fuerza})")
                else:
                    self.logger.info(f"      {i+1}. {r:.5f}")
        else:
            self.logger.info(f"   ℹ️ No hay resistencias acumuladas todavía")
        
        # ============================================================
        # FASE 4: ANÁLISIS MEDIO
        # ============================================================
        
        self.logger.info(f"⚙️ {simbolo}: FASE 4 - Análisis medio...")
        medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
        
        if medio is None:
            self.logger.warning(f"❌ {simbolo}: FASE 4 FALLÓ - Análisis medio devolvió None")
            return None
        
        if not medio.pasa_filtro:
            self.logger.info(f"⏭️ {simbolo}: FASE 4 RECHAZADA - {medio.razon_rechazo}")
            return None
        
        self.logger.info(f"✅ {simbolo}: FASE 4 COMPLETADA")
        self.logger.info(f"   ADX: {medio.adx:.0f}")
        self.logger.info(f"   RSI: {medio.rsi:.1f}")
        self.logger.info(f"   MACD: {medio.macd_histogram:.4f}")
        
        # ============================================================
        # FASE 5: ANÁLISIS PESADO
        # ============================================================
        
        self.logger.info(f"🦍 {simbolo}: FASE 5 - Análisis pesado...")
        df_h4 = self.orquestador.cache.get_datos(
            simbolo=simbolo,
            timeframe=240,
            n_velas=100,
            fetch_func=self.orquestador.mt5.obtener_datos
        ) if not self.orquestador.modo_backtest else None
        df_d1 = self.orquestador.cache.get_datos(
            simbolo=simbolo,
            timeframe=1440,
            n_velas=50,
            fetch_func=self.orquestador.mt5.obtener_datos
        ) if not self.orquestador.modo_backtest else None
        
        pesado = self.analisis_capas.analisis_pesado(df_h1, simbolo, df_h4, df_d1, niveles, medio)
        
        if pesado is None:
            self.logger.warning(f"❌ {simbolo}: FASE 5 FALLÓ - Análisis pesado devolvió None")
            return None
        
        self.logger.info(f"✅ {simbolo}: FASE 5 COMPLETADA")
        self.logger.info(f"   Score estructura: {pesado.score_estructura:.1f}")
        self.logger.info(f"   Score momentum: {pesado.score_momentum:.1f}")
        self.logger.info(f"   Score confluencia: {pesado.score_confluencia:.1f}")
        self.logger.info(f"   Score institucional: {pesado.score_institucional:.1f}")
        
        # ============================================================
        # FASE 6: CALCULAR SCORE Y RÉGIMEN
        # ============================================================
        
        self.logger.info(f"🧮 {simbolo}: FASE 6 - Calculando score y régimen...")
        score_h1 = self.orquestador.score_engine.calcular_score_h1(
            score_estructura=pesado.score_estructura,
            score_momentum=pesado.score_momentum,
            score_confluencia=pesado.score_confluencia,
            score_institucional=pesado.score_institucional,
            simbolo=simbolo
        ).score
        
        # ✅ CLASIFICAR RÉGIMEN
        regimen_data = self.orquestador.regimen_filter.clasificar(simbolo, df_h4, df_h1)
        regimen = regimen_data.regimen.value
        
        self.logger.info(f"✅ {simbolo}: FASE 6 COMPLETADA")
        self.logger.info(f"   Score H1: {score_h1:.1f}")
        self.logger.info(f"   Régimen: {regimen}")
        self.logger.info(f"   Confianza régimen: {regimen_data.confianza:.0f}%")
        self.logger.info(f"   Dirección favorita: {regimen_data.direccion_favor}")
        
        # ============================================================
        # FASE 7: DETERMINAR DIRECCIÓN
        # ============================================================
        
        self.logger.info(f"🧭 {simbolo}: FASE 7 - Determinando dirección...")
        direccion = self.orquestador._determinar_direccion_mejorado(
            medio, pesado, df_h4, df_h1, regimen
        )
        
        if direccion == 'NEUTRAL':
            self.logger.info(f"⏭️ {simbolo}: FASE 7 - Dirección NEUTRAL, descartando")
            return None
        
        self.logger.info(f"✅ {simbolo}: FASE 7 COMPLETADA - Dirección: {direccion}")
        
        # ============================================================
        # FASE 8: GUARDAR EN PIPELINE
        # ============================================================
        
        self.logger.info(f"💾 {simbolo}: FASE 8 - Guardando en pipeline...")
        
        # ✅ CONSTRUIR CONTEXTO H1 CON NIVELES
        contexto_h1 = {
            'score': score_h1,
            'direccion': direccion,
            'regimen': regimen,
            'en_nivel_clave': medio.en_nivel_clave if hasattr(medio, 'en_nivel_clave') else False,
            'soporte_cercano': medio.soporte_cercano if hasattr(medio, 'soporte_cercano') else None,
            'resistencia_cercana': medio.resistencia_cercana if hasattr(medio, 'resistencia_cercana') else None,
            'soporte_hits': medio.soporte_hits if hasattr(medio, 'soporte_hits') else 0,
            'resistencia_hits': medio.resistencia_hits if hasattr(medio, 'resistencia_hits') else 0,
            'adx': medio.adx,
            'rsi': medio.rsi,
            'patron_principal': pesado.patron_principal if hasattr(pesado, 'patron_principal') else None,
            'wyckoff_fase': pesado.wyckoff_fase if hasattr(pesado, 'wyckoff_fase') else None,
            'divergencia_rsi': pesado.divergencia_rsi if hasattr(pesado, 'divergencia_rsi') else None,
            'divergencia_macd': pesado.divergencia_macd if hasattr(pesado, 'divergencia_macd') else None,
            'niveles': {
                'soportes': soportes,
                'resistencias': resistencias
            }
        }
        
        estado = self.orquestador.pipeline.actualizar_fase_1(
            simbolo=simbolo,
            analisis={'rapido': rapido, 'medio': medio, 'pesado': pesado},
            score=score_h1,
            direccion=direccion,
            regimen=regimen,
            direccion_regimen=regimen_data.direccion_favor,
            confianza_regimen=regimen_data.confianza,
            tendencia_h4='ALCISTA' if medio.adx > 25 and medio.sma20 > medio.sma50 else 'BAJISTA' if medio.adx > 25 else 'LATERAL',
            contexto_h1=contexto_h1,
            analisis_pesado=pesado
        )
        
        if estado is None:
            self.logger.info(f"⏭️ {simbolo}: FASE 8 RECHAZADA - Pipeline rechazó la oportunidad")
            return None
        
        self.logger.info(f"✅ {simbolo}: FASE 8 COMPLETADA - Oportunidad guardada en pipeline")
        self.logger.info(f"   Estado: {estado.fase_actual.value}")
        self.logger.info(f"   Score acumulado: {estado.score_acumulado:.1f}")
        
        return {
            'simbolo': simbolo,
            'score': score_h1,
            'direccion': direccion,
            'regimen': regimen,
            'estado': estado,
            'niveles': contexto_h1['niveles'],  # ✅ Incluir niveles en el resultado
        }
    
    def _encontrar_niveles_cercanos(self, precio_actual: float, soportes: List, resistencias: List) -> Dict:
        """
        Encuentra niveles cercanos al precio actual (dentro de 1%).
        
        Args:
            precio_actual: Precio actual
            soportes: Lista de soportes
            resistencias: Lista de resistencias
            
        Returns:
            Diccionario con soportes y resistencias cercanos
        """
        cercanos = {'soportes': [], 'resistencias': []}
        
        for s in soportes:
            if isinstance(s, dict):
                dist = abs(precio_actual - s['precio']) / precio_actual * 100
                if dist < 1.0:
                    cercanos['soportes'].append(s)
        
        for r in resistencias:
            if isinstance(r, dict):
                dist = abs(r['precio'] - precio_actual) / precio_actual * 100
                if dist < 1.0:
                    cercanos['resistencias'].append(r)
        
        return cercanos
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del escaneador."""
        return self._stats.copy()
    
    def reset_stats(self):
        """Reinicia estadísticas."""
        self._stats = {
            'total_escaneos': 0,
            'simbolos_escaneados': 0,
            'oportunidades_encontradas': 0,
            'tiempo_promedio': 0,
            'total_soportes_detectados': 0,
            'total_resistencias_detectadas': 0,
        }