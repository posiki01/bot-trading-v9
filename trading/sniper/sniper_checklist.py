##!/usr/bin/env python3
"""
trading/sniper/sniper_checklist.py (V9.8 - REFACTORIZADO COMPLETAMENTE)
Sistema de verificación de condiciones para entrada Sniper.
V9.8: Funciona con CUALQUIER símbolo, decimales y spread.
"""

import pandas as pd
import logging
import MetaTrader5 as mt5
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone

from config.umbrales import Umbrales
from utils.logger_latencia import medir_latencia
from trading.sniper.sniper_modos import DetectorModos, ModoEntrada
from utils.adaptacion_mercado import AdaptadorMercado
from utils.tiempo import HorarioMercado

logger = logging.getLogger('BotTrading.SniperChecklist')


class SniperChecklist:
    """
    Sistema de verificación de condiciones para entrada Sniper.
    V9.8 - REFACTORIZADO PARA CUALQUIER SÍMBOLO.
    """

    def __init__(self,
             pipeline: Any,
             analisis_capas: Any,
             modo_selector: Any,
             entry_timer: Any,
             gestor_stops: Any,
             config: Optional[Any] = None,
             almacen: Optional[Any] = None,
             mt5: Optional[Any] = None,
             noticias: Optional[Any] = None,
             patron_tracker: Optional[Any] = None,
             ml_optimizer: Optional[Any] = None,
             analysis_cache: Optional[Any] = None,
             modo_depuracion: bool = False,
             modo_backtest: bool = False,
             horario: Optional[HorarioMercado] = None):
        """
        Inicializa el checklist del sniper.
        """
        self.pipeline = pipeline
        self.analisis_capas = analisis_capas
        self.modo_selector = modo_selector
        self.entry_timer = entry_timer
        self.gestor_stops = gestor_stops
        self.config = config
        self.almacen = almacen
        self.adaptador_mercado = AdaptadorMercado()
        self.mt5 = mt5
        self.noticias = noticias
        self.patron_tracker = patron_tracker
        self.ml_optimizer = ml_optimizer
        self.analysis_cache = analysis_cache
        self.modo_depuracion = modo_depuracion
        self.modo_backtest = modo_backtest
        self.horario = horario or HorarioMercado(zona_usuario='COLOMBIA')
        self.orquestador = getattr(pipeline, 'orquestador', None)
        self._contexto_h1_actual = {}
        
        self.logger = logging.getLogger('BotTrading.SniperChecklist')
        self.detector_modos = DetectorModos(modo_backtest=modo_backtest)

         # ✅ DEFINIR UMBRALES ANTES DE USARLOS
        self.UMBRALES = {
            'score_minimo': 40,
            'score_minimo_backtest': 25,
            'volumen_minimo': 0.30,
            'volumen_minimo_backtest': 0.10,
            'rsi_min': 20,
            'rsi_max': 80,
            'adx_minimo': 10,
            'adx_minimo_backtest': 5,
            'rr_minimo': 1.0,
            'rr_minimo_backtest': 0.8,
            'sl_min_pips': 15,
            'sl_min_pips_backtest': 12,
            'sl_max_pips': 200,
            'distancia_nivel_max': 1.5,
            'distancia_nivel_max_backtest': 3.0,
            'patron_calidad_min': 30,
            'elite_confluencias_min': 3,
            'sl_min_backtest': 12,
        }
        self._cargar_umbrales()
        
        self._stats = {
            'total_evaluaciones': 0,
            'disparos': 0,
            'disparos_por_modo': {},
            'rechazos': {},
            'tiempo_promedio': 0,
        }
        
        self.logger.info(f"🎯 SniperChecklist V9.8 REFACTORIZADO inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Score mínimo: {self.UMBRALES['score_minimo']}")
        self.logger.info(f"   R:R mínimo: {self.UMBRALES['rr_minimo']}")
    
    def _cargar_umbrales(self):
        """Carga umbrales desde configuración centralizada."""
        if Umbrales is not None:
            if hasattr(Umbrales, 'SNIPER'):
                sniper_umbrales = Umbrales.SNIPER
                for key in self.UMBRALES:
                    if key in sniper_umbrales:
                        self.UMBRALES[key] = sniper_umbrales[key]
        
        if self.modo_backtest:
            self.UMBRALES['score_minimo'] = self.UMBRALES['score_minimo_backtest']
            self.UMBRALES['volumen_minimo'] = self.UMBRALES['volumen_minimo_backtest']
            self.UMBRALES['adx_minimo'] = self.UMBRALES['adx_minimo_backtest']
            self.UMBRALES['rr_minimo'] = self.UMBRALES['rr_minimo_backtest']
            self.UMBRALES['sl_min_pips'] = self.UMBRALES['sl_min_pips_backtest']
            self.UMBRALES['distancia_nivel_max'] = self.UMBRALES['distancia_nivel_max_backtest']
    
    # ============================================================
    # MÉTODO PRINCIPAL (REFACTORIZADO V9.65)
    # ============================================================
    
    @medir_latencia("sniper_evaluacion", plataforma="SNIPER")
    def evaluar_sniper_optimizado(self,
                                simbolo: str,
                                df_m5: pd.DataFrame,
                                precio_actual: float,
                                direccion: str,
                                estado_pipeline: Optional[Any] = None,
                                analisis_rapido: Optional[Any] = None,
                                analisis_medio: Optional[Any] = None,
                                ejecutar_pesado: bool = True,
                                contexto_h1: Optional[Dict] = None,
                                calidad_horario: str = 'REGULAR',
                                tick_data: Optional[Dict[str, Any]] = None,
                                precio_entrada: Optional[float] = None,
                                atr_pips: float = 0.0,
                                modo_forzado: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Evalúa una oportunidad con el checklist SNIPER.
        V9.65 - CORREGIDO DEFINITIVO:
        - ✅ PREVENCIÓN DE DUPLICADOS AL INICIO (antes de operaciones costosas)
        - ✅ VALIDACIÓN DE CAPITAL REAL ANTES DE OPERAR
        - ✅ SL/TP usando estructura real (niveles, swings, velas H1)
        - ✅ Valida R:R >= 1.5 en todo momento
        - ✅ Guarda contexto_h1 para cálculos de estructura
        - ✅ Validación de dirección M5 más flexible
        """
        from datetime import datetime, timezone
        
        self._stats['total_evaluaciones'] += 1
        
        # ============================================================
        # 0. ✅ NUEVO V9.65: PREVENCIÓN DE DUPLICADOS (INMEDIATO)
        # ============================================================
        
        # 0.1 VERIFICAR EN MT5 SI YA HAY POSICIÓN EN EL SÍMBOLO
        if not self.modo_backtest and self.mt5 is not None:
            try:
                posiciones = self.mt5.obtener_posiciones()
                if posiciones:
                    for pos in posiciones:
                        if pos.get('simbolo') == simbolo:
                            # Determinar dirección de la posición existente
                            tipo = pos.get('tipo')
                            if tipo in ['BUY', 0, 'COMPRA']:
                                direccion_existente = 'COMPRA'
                            elif tipo in ['SELL', 1, 'VENTA']:
                                direccion_existente = 'VENTA'
                            else:
                                direccion_existente = pos.get('direccion', 'DESCONOCIDO')
                            
                            # ✅ Si es la MISMA dirección, BLOQUEAR INMEDIATAMENTE
                            if direccion_existente == direccion:
                                self.logger.warning(f"⛔ {simbolo}: YA EXISTE posición {direccion} (Ticket: {pos.get('ticket')})")
                                self.logger.warning(f"   Prevención de duplicado - NO se evaluará esta señal")
                                
                                # Actualizar estado del pipeline
                                if estado_original:
                                    estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
                                    estado_original.metadata['sniper_ultimo_fallo'] = datetime.now(timezone.utc).isoformat()
                                
                                return None
                            
                            # ✅ Si es dirección OPUESTA, permitir (según estrategia)
                            if direccion_existente != direccion:
                                self.logger.info(f"ℹ️ {simbolo}: Posición opuesta existente ({direccion_existente}) - permitiendo {direccion}")
            except Exception as e:
                self.logger.debug(f"⚠️ Error verificando posiciones en MT5: {e}")
        
        # 0.2 VERIFICAR EN MEMORIA (después de reinicio)
        if hasattr(self, 'orquestador') and self.orquestador:
            posiciones_memoria = self.orquestador.estado.posiciones_abiertas
            if posiciones_memoria:
                for ticket, meta in posiciones_memoria.items():
                    if meta.get('simbolo') == simbolo:
                        direccion_meta = meta.get('direccion', 'COMPRA')
                        if direccion_meta == direccion:
                            self.logger.warning(f"⛔ {simbolo}: Posición en MEMORIA (Ticket: {ticket})")
                            return None
        
        # 0.3 ✅ VERIFICAR CAPITAL MÍNIMO POR ACTIVO (INMEDIATO)
        valido_capital, razon_capital = self._validar_capital_minimo(simbolo)
        if not valido_capital:
            self.logger.info(f"⏭️ {simbolo}: {razon_capital}")
            if estado_pipeline:
                estado_pipeline.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_pipeline.metadata['sniper_fallos'] = estado_pipeline.metadata.get('sniper_fallos', 0) + 1
            return None
        
        # ============================================================
        # 1. GUARDAR REFERENCIA AL ESTADO PARA ACTUALIZAR TIMESTAMP
        # ============================================================
        estado_original = estado_pipeline
        
        # ============================================================
        # 1.5 ✅ NUEVO: GUARDAR SÍMBOLO Y CONTEXTO PARA SL/TP ESTRUCTURA
        # ============================================================
        self._simbolo_actual = simbolo
        self._contexto_h1_actual = contexto_h1 or {}
        
        # ============================================================
        # 2. IDENTIFICAR TIPO DE ACTIVO (ANTES DE TODO)
        # ============================================================
        simbolo_upper = simbolo.upper()
        es_cripto = any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL'])
        es_metales = any(x in simbolo_upper for x in ['XAU', 'XAG'])
        es_indices = any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500'])
        es_forex = not es_cripto and not es_metales and not es_indices
        
        self.logger.info(f"🔍 INICIANDO EVALUACIÓN SNIPER PARA {simbolo}")
        self.logger.info(f"   Dirección: {direccion}")
        self.logger.info(f"   Tipo: {'CRIPTO' if es_cripto else 'METALES' if es_metales else 'INDICES' if es_indices else 'FOREX'}")
        self.logger.info(f"   Precio actual: {precio_actual:.5f}")
        self.logger.info(f"   Modo forzado: {modo_forzado if modo_forzado else 'N/A'}")
        
        # ============================================================
        # 3. AJUSTES ESTACIONALES
        # ============================================================
        ajustes_estacionales = self._get_ajustes_estacionales(
            simbolo=simbolo,
            df_m5=df_m5,
            df_h1=None
        )
        
        tolerancia_nivel = 0.3 * ajustes_estacionales['tolerancia_nivel']
        volumen_minimo = self.UMBRALES['volumen_minimo'] * ajustes_estacionales['volumen_minimo']
        score_minimo_actual = self.UMBRALES['score_minimo'] * ajustes_estacionales['score_minimo']
        rr_minimo_actual = self.UMBRALES['rr_minimo'] * ajustes_estacionales['rr_minimo']
        sl_min_pips_actual = self.UMBRALES['sl_min_pips'] * ajustes_estacionales['sl_min_pips']
        distancia_nivel_max_actual = self.UMBRALES['distancia_nivel_max'] * ajustes_estacionales['distancia_nivel_max']
        
        if self.modo_backtest:
            volumen_minimo = max(0.01, volumen_minimo * 0.3)
            score_minimo_actual = max(15, score_minimo_actual * 0.6)
            rr_minimo_actual = max(0.5, rr_minimo_actual * 0.8)
            sl_min_pips_actual = max(8, sl_min_pips_actual * 0.8)
            distancia_nivel_max_actual = distancia_nivel_max_actual * 2.0
        
        self.logger.info(f"🌍 Ajustes estacionales aplicados:")
        self.logger.info(f"   Tolerancia nivel: {tolerancia_nivel:.2f}%")
        self.logger.info(f"   Volumen mínimo: {volumen_minimo:.2f}x")
        self.logger.info(f"   Score mínimo: {score_minimo_actual:.1f}")
        self.logger.info(f"   R:R mínimo: {rr_minimo_actual:.2f}")
        self.logger.info(f"   SL mínimo: {sl_min_pips_actual:.0f}pips")
        
        # ============================================================
        # 4. FILTRO DE HORARIO
        # ============================================================
        from utils.tiempo import HorarioMercado
        horario = HorarioMercado(zona_usuario='COLOMBIA')
        hora_col = horario.ahora_usuario()
        hora_col_float = hora_col.hour + hora_col.minute / 60.0
        
        valido, etapa, score_bono = self._validar_horario_por_simbolo(simbolo, hora_col_float)
        
        if not valido:
            self.logger.info(f"⏭️ {simbolo}: Fuera de horario ({etapa} - {hora_col_float:.1f} COT)")
            if estado_original:
                estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
            return None
        
        self.logger.info(f"✅ {simbolo}: Horario válido ({etapa})")
        if score_bono > 0:
            self.logger.info(f"   Bono de score: +{score_bono:.0f} puntos")
        
        # ============================================================
        # 5. VALIDAR SPREAD
        # ============================================================
        spread_pips = 0.0
        
        if not self.modo_backtest:
            tick = tick_data
            if tick is None:
                tick = self.mt5.obtener_precio(simbolo)
            
            if tick is None:
                self.logger.info(f"⏭️ {simbolo}: No se pudo obtener tick")
                if estado_original:
                    estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                    estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
                return None
            
            tick_data = tick
            spread_pips = float(tick.get('spread_pips', 0.0) or 0.0)
            bid = float(tick.get('bid', 0.0) or 0.0)
            ask = float(tick.get('ask', 0.0) or 0.0)
            
            if bid <= 0 or ask <= 0 or ask < bid:
                self.logger.info(f"⏭️ {simbolo}: Tick inválido (bid={bid}, ask={ask})")
                if estado_original:
                    estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                    estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
                return None
            
            if spread_pips <= 0.0:
                self.logger.info(f"⏭️ {simbolo}: Spread inválido ({spread_pips:.2f} pips)")
                if estado_original:
                    estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                    estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
                return None
            
            self.logger.info(f"✅ {simbolo}: Spread válido ({spread_pips:.2f} pips)")
        
        if precio_entrada is None and not self.modo_backtest and tick_data is not None:
            precio_entrada = float(
                tick_data.get('ask' if direccion == 'COMPRA' else 'bid', precio_actual)
            )
        
        if precio_entrada is None:
            precio_entrada = precio_actual
        
        # ============================================================
        # 6. CONTEXTO H1
        # ============================================================
        if contexto_h1 is None:
            contexto_h1 = {}
        
        score_h1 = contexto_h1.get('score', 0)
        regimen = contexto_h1.get('regimen', 'INCERTO')
        en_nivel_clave = contexto_h1.get('en_nivel_clave', False)
        niveles = contexto_h1.get('niveles', {})
        nivel_usado = contexto_h1.get('nivel_usado', 0)
        
        self.logger.info(f"   Score H1: {score_h1:.1f}")
        self.logger.info(f"   Régimen: {regimen}")
        self.logger.info(f"   En nivel clave: {en_nivel_clave}")
        
        if regimen in ['RANGO_APRETADO', 'CHOP_VOLATIL']:
            self.logger.info(f"⏭️ {simbolo}: Régimen no favorable: {regimen}")
            if estado_original:
                estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
            return None
        
        if not self._validar_regimen_para_direccion(regimen, direccion):
            self.logger.info(f"⏭️ {simbolo}: Régimen {regimen} no válido para dirección {direccion}")
            if estado_original:
                estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
            return None
        
        # ============================================================
        # 7. ANÁLISIS RÁPIDO M5
        # ============================================================
        if analisis_rapido is None:
            self.logger.info(f"⚡ {simbolo}: Ejecutando análisis rápido M5...")
            analisis_rapido = self.analisis_capas.analisis_rapido(df_m5, simbolo, precio_actual)
        
        if not analisis_rapido.pasa_filtro:
            self.logger.info(f"⏭️ {simbolo}: Filtro rápido falló - {analisis_rapido.razon_rechazo}")
            if estado_original:
                estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
            return None
        
        self.logger.info(f"✅ {simbolo}: Análisis rápido aprobado")
        self.logger.info(f"   RSI: {analisis_rapido.rsi:.1f}")
        self.logger.info(f"   Volumen relativo: {analisis_rapido.volumen_relativo:.2f}x")
        self.logger.info(f"   Tendencia: {analisis_rapido.tendencia_corta}")
        
        # ============================================================
        # 8. ANÁLISIS MEDIO M5
        # ============================================================
        if analisis_medio is None:
            self.logger.info(f"⚙️ {simbolo}: Ejecutando análisis medio M5...")
            analisis_medio = self.analisis_capas.analisis_medio(df_m5, simbolo, analisis_rapido, niveles)
        
        if analisis_medio is None or not analisis_medio.pasa_filtro:
            razon = analisis_medio.razon_rechazo if analisis_medio else "Análisis medio devolvió None"
            self.logger.info(f"⏭️ {simbolo}: Filtro medio falló - {razon}")
            if estado_original:
                estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
            return None
        
        self.logger.info(f"✅ {simbolo}: Análisis medio aprobado")
        self.logger.info(f"   ADX: {analisis_medio.adx:.0f}")
        self.logger.info(f"   RSI: {analisis_medio.rsi:.1f}")
        self.logger.info(f"   MACD: {analisis_medio.macd_histogram:.4f}")
        
        # ============================================================
        # 9. ANÁLISIS PESADO
        # ============================================================
        analisis_pesado = None
        if ejecutar_pesado:
            self.logger.info(f"🦍 {simbolo}: Ejecutando análisis pesado...")
            df_h4 = contexto_h1.get('h4', None)
            df_d1 = contexto_h1.get('d1', None)
            analisis_pesado = self.analisis_capas.analisis_pesado(
                df_m5, simbolo, df_h4, df_d1, niveles, analisis_medio
            )
            if analisis_pesado:
                self.logger.info(f"✅ {simbolo}: Análisis pesado completado")
                self.logger.info(f"   Score estructura: {analisis_pesado.score_estructura:.1f}")
                self.logger.info(f"   Score momentum: {analisis_pesado.score_momentum:.1f}")
                self.logger.info(f"   Score confluencia: {analisis_pesado.score_confluencia:.1f}")
                self.logger.info(f"   Score institucional: {analisis_pesado.score_institucional:.1f}")
                self.logger.info(f"   Patrón principal: {analisis_pesado.patron_principal}")
                self.logger.info(f"   Divergencia RSI: {analisis_pesado.divergencia_rsi}")
            else:
                self.logger.info(f"⏭️ {simbolo}: Análisis pesado falló")
        
        # ============================================================
        # 10. CLASIFICAR CONFLUENCIAS
        # ============================================================
        contexto_confluencias = {
            'ema9': analisis_medio.sma20 if analisis_medio else 0,
            'ema21': analisis_medio.sma50 if analisis_medio else 0,
            'adx': analisis_medio.adx if analisis_medio else 0,
            'rsi': analisis_medio.rsi if analisis_medio else 50,
            'en_nivel_clave': en_nivel_clave,
            'patron_calidad': analisis_pesado.calidad_patron if analisis_pesado else 0,
            'patron': analisis_pesado.patron_principal if analisis_pesado else 'N/A',
            'volumen_relativo': analisis_rapido.volumen_relativo if analisis_rapido else 0,
            'divergencia_rsi': analisis_pesado.divergencia_rsi if analisis_pesado else None,
        }
        
        categorias = self._clasificar_confluencias(contexto_confluencias)
        confluencias_totales = sum(len(v) for v in categorias.values())
        
        self.logger.info(f"📊 Confluencias por categoría:")
        for cat, lista in categorias.items():
            if lista:
                self.logger.info(f"   {cat}: {', '.join(lista)}")
        self.logger.info(f"   Total confluencias únicas: {confluencias_totales}")
        
        confluencias_favorables = []
        confluencias_conflictos = []
        
        for cat, lista in categorias.items():
            for item in lista:
                if 'Divergencia RSI' in item and direccion == 'COMPRA' and 'BEARISH' in item:
                    confluencias_conflictos.append(item)
                elif 'Divergencia RSI' in item and direccion == 'VENTA' and 'BULLISH' in item:
                    confluencias_conflictos.append(item)
                else:
                    confluencias_favorables.append(item)
        
        # ============================================================
        # 11. CALCULAR SCORES
        # ============================================================
        score_m5 = self._calcular_score_m5(analisis_rapido, analisis_medio, analisis_pesado, en_nivel_clave, direccion)
        score_final = self._calcular_score_final(score_h1, score_m5, direccion, regimen)
        score_final = score_final + score_bono
        
        self.logger.info(f"📊 {simbolo}: Score final: {score_final:.1f} (H1: {score_h1:.1f}, M5: {score_m5:.1f})")
        
        # ============================================================
        # 12. SELECCIÓN DE MODO (CON SOPORTE PARA MODO FORZADO)
        # ============================================================
        self.logger.info(f"🎯 {simbolo}: Seleccionando modo de entrada por jerarquía...")
        
        # ✅ PRIMERO: DEFINIR contexto_modos
        contexto_modos = {
            'simbolo': simbolo,
            'score_h1': score_h1,
            'score_final': score_final,
            'regimen': regimen,
            'en_nivel_clave': en_nivel_clave,
            'niveles': niveles,
            'direccion': direccion,
            'analisis_rapido': analisis_rapido,
            'analisis_medio': analisis_medio,
            'analisis_pesado': analisis_pesado,
            'confluencias_favorables': confluencias_favorables,
            'confluencias_conflictos': confluencias_conflictos,
            'confluencias_totales': confluencias_totales,
            'spread_pips': spread_pips,
            'volumen_relativo': analisis_rapido.volumen_relativo if analisis_rapido else 1.0,
            'patron_calidad': analisis_pesado.calidad_patron if analisis_pesado else 0,
            'patron': analisis_pesado.patron_principal if analisis_pesado else 'N/A',
            'falsa_ruptura': contexto_h1.get('falsa_ruptura', False),
            'vela_borde': contexto_h1.get('vela_borde', False),
            'rr': 0,
        }
        
        # ✅ SEGUNDO: AGREGAR CONTEXTO M5
        if analisis_rapido:
            if analisis_rapido.tendencia_corta == 'ALCISTA':
                tendencia_m5 = 'ALCISTA'
            elif analisis_rapido.tendencia_corta == 'BAJISTA':
                tendencia_m5 = 'BAJISTA'
            else:
                tendencia_m5 = 'LATERAL'
        else:
            tendencia_m5 = 'LATERAL'
        
        distancia_nivel = 0
        if nivel_usado > 0 and precio_actual > 0:
            distancia_nivel = abs(precio_actual - nivel_usado) / precio_actual * 100
        
        contexto_modos.update({
            'precio_actual': precio_actual,
            'nivel_usado': nivel_usado,
            'distancia_nivel': distancia_nivel,
            'tendencia_m5': tendencia_m5,
            'score_m5': score_m5,
        })
        
        # ✅ NUEVO: Si hay modo forzado, usarlo directamente
        if modo_forzado:
            modo = modo_forzado
            razon_modo = f"Modo forzado: {modo_forzado}"
            self.logger.info(f"✅ {simbolo}: MODO FORZADO: {modo} ({razon_modo})")
        else:
            # Seleccionar modo por jerarquía
            modo_seleccionado, razon_modo = self._seleccionar_modo_por_jerarquia(contexto_modos)
            
            if modo_seleccionado is None:
                self.logger.info(f"⏭️ {simbolo}: No se encontró modo válido - {razon_modo}")
                if estado_original:
                    estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                    estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
                return None
            
            modo = modo_seleccionado.value
            self.logger.info(f"✅ {simbolo}: MODO SELECCIONADO: {modo} ({razon_modo})")
        
        # ============================================================
        # 13. VALIDACIÓN DE MOMENTO EXACTO
        # ============================================================
        self.logger.info(f"⏱️ {simbolo}: Validando momento exacto...")
        
        valido_momento, razon_momento, detalles_momento = self.entry_timer.validar_momento_exacto(
            simbolo=simbolo,
            modo=modo,
            df_m5=df_m5,
            precio_actual=precio_actual,
            nivel_usado=nivel_usado,
            direccion=direccion,
            regimen=regimen,
            volumen_relativo=analisis_rapido.volumen_relativo if analisis_rapido else 1.0
        )
        
        if not valido_momento:
            self.logger.info(f"⏭️ {simbolo}: Momento no válido - {razon_momento}")
            if estado_original:
                estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
            return None
        
        self.logger.info(f"✅ {simbolo}: Momento exacto validado para {modo}")
        
        # ============================================================
        # 14. CÁLCULO DE SL/TP (USANDO ESTRUCTURA)
        # ============================================================
        self.logger.info(f"📊 {simbolo}: Calculando SL/TP...")
        
        atr_m5 = self._obtener_atr_m5(df_m5)
        self.logger.info(f"🔍 {simbolo}: ATR M5 = {atr_m5:.2f} pips")
        
        # ✅ AGREGADO: Obtener pip_val y digits
        pip_val = self._obtener_pip_val_universal(simbolo)
        digits = self._obtener_digits_universal(simbolo)
        
        # ✅ NUEVO: Guardar contexto_h1 para cálculos de estructura
        self._contexto_h1_actual = contexto_h1
        
        # ✅ NUEVO: Usar método de estructura
        sl_estructura, tp_estructura, rr_estructura = self._calcular_sl_tp_estructura(
            simbolo=simbolo,
            precio_actual=precio_entrada,
            direccion=direccion,
            modo=modo,
            analisis_medio=analisis_medio,
            analisis_pesado=analisis_pesado,
            contexto_h1=contexto_h1,
            df_m5=df_m5,
            df_h1=contexto_h1.get('h1', None),
            atr_m5=atr_m5
        )
        
        # Usar resultados de estructura
        sl_propuesto = sl_estructura
        
        # Validar SL/TP con gestor de stops (solo para validación)
        valido_stops, razon_stops, sl_final, tp_final, tp2_final = self.gestor_stops.validar_sl_tp(
            simbolo=simbolo,
            entry_price=precio_entrada,
            sl=sl_propuesto,
            tp=tp_estructura,
            tp2=0,
            direccion=direccion,
            regimen=regimen,
            modo=modo,
            es_reversal=contexto_h1.get('es_reversal', False),
            en_nivel_clave=en_nivel_clave,
            calidad_horario=calidad_horario,
            atr_pips=atr_m5
        )
        
        if not valido_stops:
            self.logger.info(f"⏭️ {simbolo}: SL/TP inválido - {razon_stops}")
            if estado_original:
                estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
            return None
        
        # Calcular R:R final
        sl_dist = abs(precio_entrada - sl_final)
        tp_dist = abs(tp_final - precio_entrada)
        rr = tp_dist / sl_dist if sl_dist > 0 else 0
        
        self.logger.info(f"✅ {simbolo}: SL/TP calculado:")
        self.logger.info(f"   SL: {sl_final:.{digits}f}")
        self.logger.info(f"   TP: {tp_final:.{digits}f}")
        self.logger.info(f"   R:R: {rr:.2f}")
        
        # ============================================================
        # 15. VALIDACIÓN DE VOLATILIDAD (MENOS ESTRICTA)
        # ============================================================
        atr_actual = analisis_medio.atr if analisis_medio else 0.001
        atr_pips_calculado = atr_actual / pip_val if pip_val > 0 else 0
        tp_dist_pips = abs(tp_final - precio_entrada) / pip_val if pip_val > 0 else 0
        
        self.logger.info(f"🔍 {simbolo}: atr_actual = {atr_actual:.2f} | atr_pips = {atr_pips_calculado:.2f} | tp_dist_pips = {tp_dist_pips:.2f}")
        
        if atr_pips_calculado > 0:
            # ✅ CORREGIDO: AUMENTAR multiplicadores
            if es_cripto:
                if atr_pips_calculado < 2:
                    max_multiplier = 200.0
                    min_multiplier = 0.02
                elif atr_pips_calculado < 5:
                    max_multiplier = 100.0
                    min_multiplier = 0.05
                elif atr_pips_calculado < 20:
                    max_multiplier = 50.0
                    min_multiplier = 0.08
                elif atr_pips_calculado < 50:
                    max_multiplier = 20.0
                    min_multiplier = 0.15
                else:
                    max_multiplier = 10.0
                    min_multiplier = 0.20
            else:
                if atr_pips_calculado < 2:
                    max_multiplier = 200.0
                    min_multiplier = 0.02
                elif atr_pips_calculado < 5:
                    max_multiplier = 100.0
                    min_multiplier = 0.05
                elif atr_pips_calculado < 20:
                    max_multiplier = 50.0
                    min_multiplier = 0.08
                elif atr_pips_calculado < 50:
                    max_multiplier = 20.0
                    min_multiplier = 0.15
                else:
                    max_multiplier = 10.0
                    min_multiplier = 0.20
            
            self.logger.info(f"🔍 {simbolo}: max_multiplier = {max_multiplier}, min_multiplier = {min_multiplier}")
            
            if tp_dist_pips > (atr_pips_calculado * max_multiplier):
                self.logger.info(f"⏭️ {simbolo}: TP demasiado lejano ({tp_dist_pips:.1f}pips > {atr_pips_calculado*max_multiplier:.1f} ATR)")
                if estado_original:
                    estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                    estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
                return None
            
            if tp_dist_pips < (atr_pips_calculado * min_multiplier):
                self.logger.info(f"⏭️ {simbolo}: TP demasiado cercano ({tp_dist_pips:.1f}pips < {atr_pips_calculado*min_multiplier:.1f} ATR)")
                if estado_original:
                    estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                    estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
                return None
        else:
            self.logger.warning(f"⚠️ {simbolo}: ATR inválido ({atr_actual:.5f}), saltando validación de volatilidad")
        
        # ============================================================
        # 16. VALIDACIÓN DE MOVIMIENTO DE VELA
        # ============================================================
        vela_virtual = df_m5.iloc[-1]
        rango_vela = vela_virtual['High'] - vela_virtual['Low']
        rango_promedio = (df_m5['High'] - df_m5['Low']).rolling(10).mean().iloc[-1]
        
        if rango_vela < (rango_promedio * 0.3):
            self.logger.info(f"⏭️ {simbolo}: Vela demasiado pequeña ({rango_vela:.5f} < {rango_promedio*0.3:.5f})")
            if estado_original:
                estado_original.timestamp_ultima_actualizacion = datetime.now(timezone.utc)
                estado_original.metadata['sniper_fallos'] = estado_original.metadata.get('sniper_fallos', 0) + 1
            return None
        
        # ============================================================
        # 17. ACTUALIZAR R:R EN CONTEXTO DE MODOS
        # ============================================================
        contexto_modos['rr'] = rr
        
        # ============================================================
        # 18. LOG DE DECISIÓN ESTRUCTURADO
        # ============================================================
        self._log_decision_estructurado(simbolo, {
            'modo': modo,
            'score_final': score_final,
            'rr': rr,
            'risk': 0.5,
            'confluencias_favorables': confluencias_favorables,
            'confluencias_conflictos': confluencias_conflictos,
            'decision': 'TRADE' if rr >= 1.5 else 'NO_TRADE'
        })
        
        # ============================================================
        # 19. CREAR SEÑAL
        # ============================================================
        self._stats['disparos'] += 1
        self._stats['disparos_por_modo'][modo] = self._stats['disparos_por_modo'].get(modo, 0) + 1
        
        señal = {
            'simbolo': simbolo,
            'direccion': direccion,
            'modo': modo,
            'entry_price': precio_entrada,
            'sl': sl_final,
            'tp': tp_final,
            'tp2': tp2_final if tp2_final else 0,
            'score': score_final,
            'score_h1': score_h1,
            'score_m5': score_m5,
            'rr': rr,
            'regimen': regimen,
            'calidad_horario': calidad_horario,
            'en_nivel_clave': en_nivel_clave,
            'es_reversal': contexto_h1.get('es_reversal', False),
            'volumen_relativo': analisis_rapido.volumen_relativo,
            'patron_calidad': analisis_pesado.calidad_patron if analisis_pesado else 0,
            'adx_h1': contexto_h1.get('medio', {}).get('adx', 0),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'confluencias_favorables': confluencias_favorables,
            'confluencias_conflictos': confluencias_conflictos,
            'niveles_usados': {
                'soporte_cercano': contexto_h1.get('soporte_cercano'),
                'resistencia_cercana': contexto_h1.get('resistencia_cercana'),
            },
            'puntuacion_modo': contexto_modos.get('puntuacion_modo', 0),
        }
        
        self.logger.info(f"🎯 {simbolo}: ✅ SNIPER DISPARA! Modo: {modo}, Score: {score_final:.1f}, R:R: {rr:.2f}")
        
        # ✅ REINICIAR CONTADOR DE FALLOS EN ÉXITO
        if estado_original:
            estado_original.metadata['sniper_fallos'] = 0
            estado_original.metadata['sniper_ultimo_exito'] = datetime.now(timezone.utc).isoformat()
        
        return señal
        
    # ============================================================
    # MÉTODOS AUXILIARES
    # ============================================================
    
    def _get_ajustes_estacionales(self, simbolo: str = None, df_m5: pd.DataFrame = None, df_h1: pd.DataFrame = None) -> Dict[str, float]:
        """
        Obtiene ajustes dinámicos basados en condiciones actuales del mercado.
        Si no se proporcionan datos, devuelve ajustes neutros (1.0).
        """
        # ✅ VERIFICAR QUE TENGAMOS DATOS
        if simbolo is None or df_m5 is None:
            # Devolver ajustes neutros si no hay datos
            return {
                'tolerancia_nivel': 1.0,
                'volumen_minimo': 1.0,
                'score_minimo': 1.0,
                'rr_minimo': 1.0,
                'sl_min_pips': 1.0,
                'distancia_nivel_max': 1.0,
            }
        
        # Usar el AdaptadorMercado
        return self.adaptador_mercado.obtener_ajustes(
            simbolo=simbolo,
            df_m5=df_m5,
            df_h1=df_h1
        )
    
    def _calcular_score_m5(self, analisis_rapido, analisis_medio, analisis_pesado, en_nivel_clave, direccion) -> float:
        """Calcula score M5 consolidado."""
        score = 25.0
        if analisis_rapido:
            if analisis_rapido.volumen_relativo > 1.5:
                score += 10
            elif analisis_rapido.volumen_relativo > 1.0:
                score += 5
        if analisis_medio:
            if analisis_medio.adx > 30:
                score += 10
            elif analisis_medio.adx > 20:
                score += 7
            if abs(analisis_medio.macd_histogram) > 0.0003:
                score += 8
        if en_nivel_clave:
            score += 10
        if analisis_medio and hasattr(analisis_medio, 'rsi'):
            if direccion == 'COMPRA' and analisis_medio.rsi < 35:
                score += 10
            elif direccion == 'VENTA' and analisis_medio.rsi > 65:
                score += 10
        return min(100.0, max(0.0, score))
    
    def _calcular_score_final(self, score_h1: float, score_m5: float, direccion: str, regimen: str) -> float:
        """Calcula score final con pesos."""
        pesos = {
            'TREND_ALCISTA_FUERTE': {'h1': 0.45, 'm5': 0.55},
            'TREND_BAJISTA_FUERTE': {'h1': 0.45, 'm5': 0.55},
            'TREND_ALCISTA_DEBIL': {'h1': 0.35, 'm5': 0.65},
            'TREND_BAJISTA_DEBIL': {'h1': 0.35, 'm5': 0.65},
            'RANGO_AMPLIO': {'h1': 0.25, 'm5': 0.75},
            'RANGO_APRETADO': {'h1': 0.25, 'm5': 0.75},
            'CHOP_VOLATIL': {'h1': 0.20, 'm5': 0.80},
            'BREAKOUT_INMINENTE': {'h1': 0.30, 'm5': 0.70},
            'INCERTO': {'h1': 0.30, 'm5': 0.70},
        }
        p = pesos.get(regimen, pesos['INCERTO'])
        score = (score_h1 * p['h1']) + (score_m5 * p['m5'])
        
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL'] and direccion == 'COMPRA':
            score += 5
        elif regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL'] and direccion == 'VENTA':
            score += 5
        
        return min(100.0, max(0.0, score))
    
    def _validar_regimen_para_direccion(self, regimen: str, direccion: str) -> bool:
        """Valida que el régimen permita la dirección."""
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            if direccion == 'VENTA':
                return False
        if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            if direccion == 'COMPRA':
                return False
        return True

    # ============================================================
    # ✅ NUEVO: CALCULAR TP REALISTA (BASADO EN ESTRUCTURA)
    # ============================================================
    def _calcular_tp_realista(self,
                          simbolo: str,
                          precio: float,
                          direccion: str,
                          sl: float,
                          analisis_medio: Any,
                          analisis_pesado: Any,
                          contexto_h1: Dict,
                          modo: str = 'RETEST',
                          regimen: str = 'INCERTO',
                          volumen_relativo: float = 1.0) -> float:
        """
        Calcula TP realista basado en estructura y configuración del modo.
        V9.39 - CORREGIDO DEFINITIVO:
        - TP mínimo = 1.5x SL (garantiza R:R >= 1.5)
        - TP máximo = 3x SL (evita TPs poco realistas)
        - Prioriza estructura SOLO si mejora R:R
        """
        from config.umbrales import Umbrales
        
        # Obtener configuración del modo
        sniper_config = getattr(Umbrales, 'SNIPER_CONFIG', {})
        cfg_modo = sniper_config.get(modo, sniper_config.get('RETEST', {}))
        
        # Obtener pip_val y digits
        pip_val = self._obtener_pip_val_universal(simbolo)
        digits = self._obtener_digits_universal(simbolo)
        
        # Calcular distancia del SL
        sl_dist = abs(precio - sl)
        sl_dist_pips = sl_dist / pip_val if pip_val > 0 else 0
        
        # ============================================================
        # 1. BUSCAR ESTRUCTURA (resistencia/soporte cercano)
        # ============================================================
        nivel_estructura = None
        rr_estructura = 0
        
        if direccion == 'COMPRA':
            # Buscar resistencia
            resistencia_cercana = contexto_h1.get('resistencia_cercana')
            
            if resistencia_cercana and resistencia_cercana > precio:
                rr_estructura = (resistencia_cercana - precio) / sl_dist if sl_dist > 0 else 0
                nivel_estructura = resistencia_cercana
        else:
            # Buscar soporte
            soporte_cercano = contexto_h1.get('soporte_cercano')
            
            if soporte_cercano and soporte_cercano < precio:
                rr_estructura = (precio - soporte_cercano) / sl_dist if sl_dist > 0 else 0
                nivel_estructura = soporte_cercano
        
        # ============================================================
        # 2. CALCULAR TP POR R:R OBJETIVO
        # ============================================================
        rr_target = cfg_modo.get('rr_target', 1.5)
        
        # Ajustar R:R por régimen
        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.1,
            'TREND_BAJISTA_FUERTE': 1.1,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.7,
            'BREAKOUT_INMINENTE': 1.1,
            'INCERTO': 0.9,
        }
        rr_target = rr_target * ajustes_regimen.get(regimen, 1.0)
        
        # ✅ CORRECCIÓN V9.39: Asegurar R:R mínimo de 1.5
        rr_target = max(1.5, rr_target)
        
        # Limitar a R:R máximo
        rr_max_config = cfg_modo.get('rr_max', 3.0)
        rr_target = min(rr_max_config, rr_target)
        
        # Ajustar por volumen
        if volumen_relativo > 2.0:
            rr_target = min(rr_max_config, rr_target * 1.1)
        
        # TP por R:R
        if direccion == 'COMPRA':
            tp_rr = precio + (sl_dist * rr_target)
        else:
            tp_rr = precio - (sl_dist * rr_target)
        
        # ============================================================
        # 3. DECIDIR TP FINAL (ESTRUCTURA vs R:R)
        # ============================================================
        tp_final = tp_rr
        
        # ✅ CORRECCIÓN V9.39: Usar estructura SOLO si mejora el R:R
        # NO usar estructura si está demasiado cerca (R:R < 1.5)
        if nivel_estructura is not None and rr_estructura > 0:
            if direccion == 'COMPRA' and nivel_estructura < tp_rr:
                # Usar estructura solo si el R:R es >= 1.5
                if rr_estructura >= 1.5:
                    tp_final = nivel_estructura
                    logger.info(f"📊 {simbolo}: TP ajustado a resistencia ({nivel_estructura:.{digits}f}) - R:R: {rr_estructura:.2f}")
                else:
                    logger.info(f"📊 {simbolo}: Resistencia a R:R {rr_estructura:.2f} < 1.5, usando R:R objetivo")
            elif direccion == 'VENTA' and nivel_estructura > tp_rr:
                if rr_estructura >= 1.5:
                    tp_final = nivel_estructura
                    logger.info(f"📊 {simbolo}: TP ajustado a soporte ({nivel_estructura:.{digits}f}) - R:R: {rr_estructura:.2f}")
                else:
                    logger.info(f"📊 {simbolo}: Soporte a R:R {rr_estructura:.2f} < 1.5, usando R:R objetivo")
        
        # ============================================================
        # 4. ✅ CORREGIDO V9.39: VALIDAR TP MÍNIMO Y MÁXIMO
        # ============================================================
        tp_dist_pips = abs(tp_final - precio) / pip_val if pip_val > 0 else 0
        
        # ✅ CRÍTICO: TP mínimo debe ser 1.5x el SL
        tp_min_pips = max(cfg_modo.get('tp_min_pips', 15), sl_dist_pips * 1.5)
        
        # ✅ CRÍTICO: TP máximo debe ser 3x el SL
        tp_max_pips = max(cfg_modo.get('tp_max_pips', 100), sl_dist_pips * 3.0)
        
        if tp_dist_pips < tp_min_pips:
            # TP demasiado cerca, forzar distancia mínima
            tp_dist_min = tp_min_pips * pip_val
            if direccion == 'COMPRA':
                tp_final = precio + tp_dist_min
            else:
                tp_final = precio - tp_dist_min
            logger.info(f"📊 {simbolo}: TP forzado a mínimo ({tp_min_pips:.0f} pips = {tp_min_pips/sl_dist_pips:.1f}x SL)")
        
        if tp_dist_pips > tp_max_pips:
            # TP demasiado lejos, limitar
            tp_dist_max = tp_max_pips * pip_val
            if direccion == 'COMPRA':
                tp_final = precio + tp_dist_max
            else:
                tp_final = precio - tp_dist_max
            logger.info(f"📊 {simbolo}: TP limitado a máximo ({tp_max_pips:.0f} pips = {tp_max_pips/sl_dist_pips:.1f}x SL)")
        
        # ============================================================
        # 5. LOG FINAL
        # ============================================================
        rr_final = abs(tp_final - precio) / sl_dist if sl_dist > 0 else 0

        if rr_final < 1.5:
        # Forzar TP para R:R = 1.5
            rr_minimo = 1.5
            if direccion == 'COMPRA':
                tp_final = precio + (sl_dist * rr_minimo)
            else:
                tp_final = precio - (sl_dist * rr_minimo)
            logger.info(f"📊 {simbolo}: TP forzado a R:R = {rr_minimo:.2f}")
        logger.info(f"📊 {simbolo}: TP final ({tp_final:.{digits}f}) - R:R: {rr_final:.2f}")

        return round(tp_final, digits)

    def _calcular_lotes_con_limites(self, simbolo: str, entry_price: float, sl: float, 
                                 capital: float, sl_pips: float) -> float:
        """
        Calcula lotes con límites por activo.
        V9.35 - NUEVO.
        """
        from config.umbrales import Umbrales
        
        simbolo_upper = simbolo.upper()
        
        # Obtener límites desde Umbrales
        lotes_max_por_activo = getattr(Umbrales, 'LOTES_MAX_POR_ACTIVO', {})
        lotes_min_por_activo = getattr(Umbrales, 'LOTES_MIN_POR_ACTIVO', {})
        riesgo_max_por_operacion = getattr(Umbrales, 'RIESGO_MAX_POR_OPERACION', {})
        
        # Límites específicos
        lote_max = lotes_max_por_activo.get(simbolo_upper, 0.10)
        lote_min = lotes_min_por_activo.get(simbolo_upper, 0.01)
        riesgo_pct = riesgo_max_por_operacion.get(simbolo_upper, 0.01)
        
        # ✅ Límites especiales por tipo de activo
        if 'XAU' in simbolo_upper:
            lote_max = min(lote_max, 0.05)
            if capital < 1000:
                lote_max = min(lote_max, 0.02)
                riesgo_pct = min(riesgo_pct, 0.005)
            elif capital < 2000:
                lote_max = min(lote_max, 0.03)
            elif capital < 5000:
                lote_max = min(lote_max, 0.04)
        
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            lote_max = min(lote_max, 0.05)
            if capital < 1000:
                lote_max = min(lote_max, 0.02)
                riesgo_pct = min(riesgo_pct, 0.005)
        
        elif 'BTC' in simbolo_upper:
            lote_max = min(lote_max, 0.01)
            riesgo_pct = min(riesgo_pct, 0.003)
        
        elif 'ETH' in simbolo_upper or 'SOL' in simbolo_upper:
            lote_max = min(lote_max, 0.02)
            riesgo_pct = min(riesgo_pct, 0.004)
        
        # Factor por capital
        if capital < 5000:
            factor_capital = max(0.3, capital / 5000)
            lote_max = max(lote_min, lote_max * factor_capital)
        
        # Calcular valor del pip
        pip_size = self._obtener_pip_val_universal(simbolo)
        valor_pip = 0.10 if 'XAU' in simbolo_upper else 1.0
        
        # Calcular riesgo en dinero
        riesgo_dinero = capital * riesgo_pct
        
        # Calcular lotes
        if sl_pips > 0 and valor_pip > 0:
            lotes = riesgo_dinero / (sl_pips * valor_pip)
        else:
            lotes = lote_min
        
        # Aplicar límites
        lotes = max(lote_min, min(lote_max, lotes))
        
        # Redondear al paso
        paso = 0.01
        lotes = round(lotes / paso) * paso
        
        if lotes < lote_min:
            lotes = lote_min
        
        return lotes

    
    # ============================================================
    # ✅ NUEVO: OBTENER R:R OBJETIVO POR MODO
    # ============================================================

    def _obtener_rr_objetivo_modo(self, modo: str, regimen: str) -> float:
        """Obtiene R:R objetivo según modo y régimen."""
        rr = {
            'RETEST': 1.5,
            'BREAKOUT': 2.0,
            'PULLBACK': 1.8,
            'NIVEL_FUERTE': 1.3,
            'PATRON': 1.5,
            'RUPTURA_FALSA': 1.2,
            'VELA_BORDE': 1.2,
            'RETEST_FALLBACK': 1.3,
            'SNIPER_ELITE': 2.0,
        }.get(modo, 1.5)
        
        # Ajuste por régimen
        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.1,
            'TREND_BAJISTA_FUERTE': 1.1,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.8,
            'BREAKOUT_INMINENTE': 1.0,
            'INCERTO': 0.9,
        }
        
        rr = rr * ajustes_regimen.get(regimen, 1.0)
        
        return max(0.8, min(4.0, rr))

    def _validar_capital_minimo(self, simbolo: str) -> Tuple[bool, str]:
        # Obtener capital actual desde el orquestador
        if not hasattr(self, 'orquestador') or not self.orquestador:
            return True, "OK"
        
        capital = self.orquestador.gestion_riesgo.capital_actual
        if capital is None:
            return True, "OK"
        
        capital = float(capital)
        
        simbolo_upper = simbolo.upper()
        
        # ✅ CORREGIDO: Umbrales REALES según apalancamiento del broker (1:500)
        CAPITAL_MINIMO = {
            'US30': 100, 'NAS100': 100, 'US500': 100, 'SP500': 100,
            'XAUUSD': 100, 'XAGUSD': 100,
            'BTCUSD': 200, 'ETHUSD': 200, 'SOLUSD': 200,
            'EURUSD': 50, 'GBPUSD': 50, 'USDJPY': 50,
            'AUDUSD': 50, 'USDCAD': 50, 'USDCHF': 50,
            'EURGBP': 50, 'EURJPY': 50, 'GBPJPY': 50,
            'AUDJPY': 50,
        }
        
        capital_minimo = CAPITAL_MINIMO.get(simbolo_upper, 50)
        
        if capital < capital_minimo:
            return False, f"Capital insuficiente para {simbolo_upper} (${capital:.2f} < ${capital_minimo})"
        
        return True, "OK"
        
    def _calcular_sl_dinamico(self,
                          simbolo: str,
                          precio: float,
                          direccion: str,
                          analisis_medio: Any,
                          analisis_pesado: Any,
                          contexto_h1: Dict,
                          df_m5: Optional[pd.DataFrame] = None,
                          volumen_relativo: float = 1.0,
                          modo: str = 'RETEST',
                          regimen: str = 'INCERTO') -> float:
        """
        Calcula SL dinámico basado en ATR M5 y modo.
        V9.39 - CORREGIDO DEFINITIVO:
        - SL mínimo REALISTA por activo (150 pips oro, 150 pips BTC)
        - SL máximo REALISTA por activo (500 pips oro, 600 pips BTC)
        - Limita punto de invalidación al 1% del precio
        - Usa ATR si estructura está demasiado lejos
        """
        from config.umbrales import Umbrales
        
        # Obtener configuración del modo
        sniper_config = getattr(Umbrales, 'SNIPER_CONFIG', {})
        cfg_modo = sniper_config.get(modo, sniper_config.get('RETEST', {}))
        
        # Obtener pip_val y digits
        pip_val = self._obtener_pip_val_universal(simbolo)
        digits = self._obtener_digits_universal(simbolo)

        # Obtener ATR M5
        atr_m5 = self._obtener_atr_m5(df_m5)
        if atr_m5 <= 0:
            atr_m5 = 0.001

        # ============================================================
        # 1. PUNTO DE INVALIDACIÓN (estructura real)
        # ============================================================
        punto_invalidez = self._obtener_punto_invalidez(
            simbolo=simbolo,
            precio=precio,
            direccion=direccion,
            analisis_medio=analisis_medio,
            analisis_pesado=analisis_pesado,
            contexto_h1=contexto_h1,
            df_m5=df_m5
        )
        
        # ✅ CORRECCIÓN V9.39: LIMITAR DISTANCIA DEL PUNTO DE INVALIDACIÓN
        # El punto de invalidación no puede estar a más del 1% del precio
        distancia_max_punto = precio * 0.01  # 1% del precio
        
        if punto_invalidez is not None:
            dist_punto = abs(precio - punto_invalidez)
            
            if dist_punto > distancia_max_punto:
                logger.info(f"📊 {simbolo}: Punto invalidación demasiado lejos ({dist_punto:.2f} > {distancia_max_punto:.2f}), usando ATR")
                punto_invalidez = None
        
        # ============================================================
        # 2. CALCULAR SL ESTRUCTURAL (SI PUNTO ES VÁLIDO)
        # ============================================================
        if punto_invalidez is not None:
            # SL = punto_invalidez + buffer
            buffer_pips = cfg_modo.get('sl_buffer_pips', 3)
            buffer = buffer_pips * pip_val
            
            if direccion == 'COMPRA':
                sl_candidato = punto_invalidez - buffer
            else:
                sl_candidato = punto_invalidez + buffer
        else:
            # ✅ CORRECCIÓN V9.39: Usar ATR como base si no hay estructura válida
            sl_mult = cfg_modo.get('sl_mult', 1.0)
            
            # Ajustar por régimen
            ajustes_regimen = {
                'TREND_ALCISTA_FUERTE': 1.1,
                'TREND_BAJISTA_FUERTE': 1.1,
                'TREND_ALCISTA_DEBIL': 1.0,
                'TREND_BAJISTA_DEBIL': 1.0,
                'RANGO_AMPLIO': 0.9,
                'RANGO_APRETADO': 0.8,
                'CHOP_VOLATIL': 0.7,
                'BREAKOUT_INMINENTE': 1.0,
                'INCERTO': 1.0,
            }
            sl_mult = sl_mult * ajustes_regimen.get(regimen, 1.0)
            
            # Ajustar por volumen
            if volumen_relativo > 2.0:
                sl_mult = sl_mult * 0.85
            elif volumen_relativo > 1.5:
                sl_mult = sl_mult * 0.90
            elif volumen_relativo < 0.5:
                sl_mult = sl_mult * 1.15
            
            # CALCULAR SL CON ATR
            sl_dist = atr_m5 * sl_mult
            
            # ✅ CORRECCIÓN V9.39: LIMITAR SL A 3% DEL PRECIO MÁXIMO
            sl_max_distancia = precio * 0.03  # 3% del precio
            sl_dist = min(sl_dist, sl_max_distancia)
            
            sl_candidato = precio - sl_dist if direccion == 'COMPRA' else precio + sl_dist
        
        # ============================================================
        # 3. VALIDAR SL MÍNIMO (CORREGIDO V9.39)
        # ============================================================
        sl_min_pips = self._obtener_sl_minimo_universal(simbolo, modo)
        sl_dist_pips = abs(precio - sl_candidato) / pip_val if pip_val > 0 else 0
        
        if sl_dist_pips < sl_min_pips:
            if direccion == 'COMPRA':
                sl_candidato = precio - (sl_min_pips * pip_val)
            else:
                sl_candidato = precio + (sl_min_pips * pip_val)
            sl_dist_pips = sl_min_pips
            logger.info(f"📊 {simbolo}: SL ajustado a mínimo ({sl_min_pips:.1f} pips)")
        
        # ============================================================
        # 4. VALIDAR SL MÁXIMO (CORREGIDO V9.39)
        # ============================================================
        sl_max_pips = self._obtener_sl_maximo_universal(simbolo, modo)
        if sl_dist_pips > sl_max_pips:
            if direccion == 'COMPRA':
                sl_candidato = precio - (sl_max_pips * pip_val)
            else:
                sl_candidato = precio + (sl_max_pips * pip_val)
            sl_dist_pips = sl_max_pips
            logger.info(f"📊 {simbolo}: SL ajustado a máximo ({sl_max_pips:.1f} pips)")
        
        # ============================================================
        # 5. VALIDAR DIRECCIÓN
        # ============================================================
        if direccion == 'COMPRA' and sl_candidato >= precio:
            return 0.0
        if direccion == 'VENTA' and sl_candidato <= precio:
            return 0.0
        
        # ============================================================
        # 6. LOG DE DIAGNÓSTICO
        # ============================================================
        logger.info(f"📊 {simbolo}: SL dinámico CALCULADO:")
        logger.info(f"   Modo: {modo}")
        logger.info(f"   ATR M5: {atr_m5:.2f} pips")
        logger.info(f"   Punto invalidación: {punto_invalidez:.{digits}f}" if punto_invalidez else "   Punto invalidación: N/A (usando ATR)")
        logger.info(f"   SL Distancia: {sl_dist_pips:.1f} pips")
        logger.info(f"   SL Final: {sl_candidato:.{digits}f}")

        return sl_candidato

    def _obtener_atr_m5(self, df_m5: Optional[pd.DataFrame] = None) -> float:
        """
        Obtiene ATR del timeframe M5 en PIPS.
        V9.44 - CORREGIDO: Usa solo las últimas 50 velas para evitar ATR inflado.
        """
        if df_m5 is None or len(df_m5) < 14:
            return 0.001
        
        try:
            # ✅ CORRECCIÓN: Usar solo las últimas 50 velas
            df_reciente = df_m5.iloc[-50:] if len(df_m5) > 50 else df_m5
            
            high = df_reciente['High']
            low = df_reciente['Low']
            close = df_reciente['Close']
            
            tr = pd.concat([
                high - low,
                abs(high - close.shift()),
                abs(low - close.shift())
            ], axis=1).max(axis=1)
            
            atr_precio = float(tr.rolling(14).mean().iloc[-1])
            
            # Convertir ATR a pips
            simbolo_actual = getattr(self, '_simbolo_actual', 'EURUSD')
            pip_val = self._obtener_pip_val_universal(simbolo_actual)
            
            if pip_val > 0:
                atr_pips = atr_precio / pip_val
                return atr_pips if atr_pips > 0 else 0.001
            
            return atr_precio if atr_precio > 0 else 0.001
            
        except Exception:
            return 0.001
    
    def _obtener_atr_promedio(self, simbolo: str) -> float:
        """
        Obtiene el ATR promedio histórico para el símbolo.
        V9.10 - DEFINITIVO: Para detectar volatilidad extrema.
        """
        # Intentar desde caché
        try:
            df_h1 = self.analysis_cache.get_datos(
                simbolo=simbolo,
                timeframe=60,
                n_velas=100,
                fetch_func=self.mt5.obtener_datos
            )
            
            if df_h1 is not None and len(df_h1) >= 14:
                high = df_h1['High']
                low = df_h1['Low']
                close = df_h1['Close']
                
                tr = pd.concat([
                    high - low,
                    abs(high - close.shift()),
                    abs(low - close.shift())
                ], axis=1).max(axis=1)
                
                atr_serie = tr.rolling(14).mean()
                return float(atr_serie.mean())
        except Exception as e:
            self.logger.debug(f"⚠️ Error obteniendo ATR promedio para {simbolo}: {e}")
        
        # Fallback: ATR típico por tipo de activo
        simbolo_upper = simbolo.upper()
        pip_val = self._obtener_pip_val_universal(simbolo)
        
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 100.0 * pip_val
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 5.0 * pip_val
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 50.0 * pip_val
        else:
            return 0.0020

    def _calcular_tp_dinamico(self,
                          precio: float,
                          direccion: str,
                          sl: float,
                          modo: str,
                          regimen: str,
                          rr_minimo: float = 1.0) -> float:
        """
        Calcula TP dinámico basado en el SL y R:R objetivo.
        V9.10 - DEFINITIVO: TP se ajusta según el SL dinámico.
        """
        sl_dist = abs(precio - sl)
        
        # Obtener R:R objetivo según modo
        rr_target = {
            'RETEST': 1.5,
            'BREAKOUT': 2.0,
            'PULLBACK': 1.8,
            'NIVEL_FUERTE': 1.3,
            'PATRON': 1.5,
            'RUPTURA_FALSA': 1.2,
            'VELA_BORDE': 1.2,
            'RETEST_FALLBACK': 1.3,
            'SNIPER_ELITE': 2.0,
        }.get(modo, 1.5)
        
        # Ajuste por régimen
        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.1,
            'TREND_BAJISTA_FUERTE': 1.1,
            'RANGO_APRETADO': 0.9,
            'CHOP_VOLATIL': 0.8,
            'INCERTO': 0.9,
        }
        rr_target = rr_target * ajustes_regimen.get(regimen, 1.0)
        
        # Aplicar R:R mínimo
        rr_target = max(rr_target, rr_minimo)
        
        if direccion == 'COMPRA':
            return precio + (sl_dist * rr_target)
        else:
            return precio - (sl_dist * rr_target)

    
    
    def _obtener_pip_val_universal(self, simbolo: str) -> float:
        """
        Obtiene pip_val para CUALQUIER símbolo.
        V9.45 - CORREGIDO: XAGUSD usa pip_val = 0.01 (NO 0.1)
        """
        simbolo_upper = simbolo.upper()
        
        # 1. Intentar desde MT5 (fuente primaria)
        if self.mt5 is not None:
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'point'):
                    point = float(info.point)
                    digits = int(getattr(info, 'digits', 5))
                    
                    if hasattr(self.mt5, '_pip_size_simbolo'):
                        pip_size = float(self.mt5._pip_size_simbolo(simbolo, info))
                        if pip_size > 0:
                            return pip_size
                    
                    if digits == 5 or digits == 3:
                        return 0.0001 if digits == 5 else 0.01
                    
                    if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
                        return 1.0
                    
                    if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                        return 1.0
                    
                    if point > 0:
                        return point * 10 if digits > 2 else point
            except Exception as e:
                self.logger.debug(f"⚠️ Error obteniendo pip_val de MT5 para {simbolo}: {e}")
        
        # 2. Fallback estático
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.01
        if 'XAG' in simbolo_upper:
            return 0.01  # ✅ CORREGIDO: XAGUSD usa 0.01, NO 0.1
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001
    
    def _obtener_digits_universal(self, simbolo: str) -> int:
        """
        Obtiene el número de decimales para CUALQUIER símbolo.
        V9.10 - DEFINITIVO: Usa MT5 para obtener el valor exacto.
        """
        # 1. Intentar desde MT5
        if self.mt5 is not None:
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'digits'):
                    return int(info.digits)
            except Exception:
                pass
        
        # 2. Fallback estático
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 3  # Pares JPY: 3 decimales
        if 'XAU' in simbolo_upper:
            return 2  # Oro: 2 decimales
        if 'XAG' in simbolo_upper:
            return 3  # Plata: 3 decimales
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1  # Índices: 1 decimal
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 2  # Cripto: 2 decimales
        return 5  # Forex estándar: 5 decimales

    def _obtener_punto_invalidez(self,
                             simbolo: str,
                             precio: float,
                             direccion: str,
                             analisis_medio: Any,
                             analisis_pesado: Any,
                             contexto_h1: Dict,
                             df_m5: Optional[pd.DataFrame] = None) -> Optional[float]:
        """
        Obtiene el punto de invalidación basado en la estructura del mercado.
        V9.10 - DEFINITIVO: Prioriza estructura real sobre fórmulas.
        """
        if direccion == 'COMPRA':
            # PRIORIDAD 1: SOPORTE DEL ANÁLISIS MEDIO
            if analisis_medio is not None and hasattr(analisis_medio, 'soporte_cercano'):
                soporte = analisis_medio.soporte_cercano
                if soporte and soporte > 0 and soporte < precio:
                    return float(soporte)
            
            # PRIORIDAD 2: SOPORTE DEL CONTEXTO H1
            if contexto_h1 and isinstance(contexto_h1, dict):
                soporte_h1 = contexto_h1.get('soporte_cercano')
                if soporte_h1 and soporte_h1 > 0 and soporte_h1 < precio:
                    return float(soporte_h1)
            
            # PRIORIDAD 3: ORDER BLOCK BULLISH
            if analisis_pesado is not None and hasattr(analisis_pesado, 'bull_ob'):
                bull_ob = analisis_pesado.bull_ob
                if bull_ob and isinstance(bull_ob, dict) and 'bottom' in bull_ob:
                    ob_bottom = float(bull_ob.get('bottom', 0))
                    if ob_bottom > 0 and ob_bottom < precio:
                        return ob_bottom
            
            # PRIORIDAD 4: MÍNIMO RECIENTE (df_m5)
            if df_m5 is not None and len(df_m5) >= 5:
                min_reciente = float(df_m5['Low'].iloc[-5:].min())
                if min_reciente > 0 and min_reciente < precio:
                    return min_reciente
            
            # PRIORIDAD 5: MÍNIMO RECIENTE (H1)
            if df_m5 is None:
                niveles = contexto_h1.get('niveles', {}) if contexto_h1 else {}
                soportes = niveles.get('soportes', [])
                
                if soportes:
                    soportes_bajo = [s['precio'] for s in soportes if s.get('precio', 0) < precio]
                    if soportes_bajo:
                        return float(max(soportes_bajo))
            
            # PRIORIDAD 6: FALLBACK - NIVEL DE WYCKOFF
            if analisis_pesado is not None and hasattr(analisis_pesado, 'wyckoff_fase'):
                if analisis_pesado.wyckoff_fase in ['ACUMULACION', 'SPRING']:
                    return precio - (0.01 * precio)
        
        else:  # VENTA
            # PRIORIDAD 1: RESISTENCIA DEL ANÁLISIS MEDIO
            if analisis_medio is not None and hasattr(analisis_medio, 'resistencia_cercana'):
                resistencia = analisis_medio.resistencia_cercana
                if resistencia and resistencia > 0 and resistencia > precio:
                    return float(resistencia)
            
            # PRIORIDAD 2: RESISTENCIA DEL CONTEXTO H1
            if contexto_h1 and isinstance(contexto_h1, dict):
                resistencia_h1 = contexto_h1.get('resistencia_cercana')
                if resistencia_h1 and resistencia_h1 > 0 and resistencia_h1 > precio:
                    return float(resistencia_h1)
            
            # PRIORIDAD 3: ORDER BLOCK BEARISH
            if analisis_pesado is not None and hasattr(analisis_pesado, 'bear_ob'):
                bear_ob = analisis_pesado.bear_ob
                if bear_ob and isinstance(bear_ob, dict) and 'top' in bear_ob:
                    ob_top = float(bear_ob.get('top', 0))
                    if ob_top > 0 and ob_top > precio:
                        return ob_top
            
            # PRIORIDAD 4: MÁXIMO RECIENTE (df_m5)
            if df_m5 is not None and len(df_m5) >= 5:
                max_reciente = float(df_m5['High'].iloc[-5:].max())
                if max_reciente > 0 and max_reciente > precio:
                    return max_reciente
            
            # PRIORIDAD 5: MÁXIMO RECIENTE (H1)
            if df_m5 is None:
                niveles = contexto_h1.get('niveles', {}) if contexto_h1 else {}
                resistencias = niveles.get('resistencias', [])
                
                if resistencias:
                    resistencias_arriba = [r['precio'] for r in resistencias if r.get('precio', 0) > precio]
                    if resistencias_arriba:
                        return float(min(resistencias_arriba))
            
            # PRIORIDAD 6: FALLBACK - NIVEL DE WYCKOFF
            if analisis_pesado is not None and hasattr(analisis_pesado, 'wyckoff_fase'):
                if analisis_pesado.wyckoff_fase in ['DISTRIBUCION', 'UPTHRUST']:
                    return precio + (0.01 * precio)
        
        return None

    def _calcular_sl_tp_estructura(self,
                                simbolo: str,
                                precio_actual: float,
                                direccion: str,
                                modo: str,
                                analisis_medio: Any,
                                analisis_pesado: Any,
                                contexto_h1: Dict,
                                df_m5: pd.DataFrame,
                                df_h1: pd.DataFrame = None,
                                atr_m5: float = 0.0) -> Tuple[float, float, float]:
        """
        Calcula SL/TP usando ESTRUCTURA REAL del mercado.
        V9.47 - NUEVO: Usa niveles, swings, ATR y velas H1.
        
        Returns:
            (sl, tp, rr)
        """
        from config.umbrales import Umbrales
        
        pip_val = self._obtener_pip_val_universal(simbolo)
        digits = self._obtener_digits_universal(simbolo)
        
        # ============================================================
        # 1. OBTENER NIVELES DE ESTRUCTURA
        # ============================================================
        soporte_cercano = contexto_h1.get('soporte_cercano', 0)
        resistencia_cercana = contexto_h1.get('resistencia_cercana', 0)
        
        # Obtener niveles del tracker
        niveles = contexto_h1.get('niveles', {})
        soportes = niveles.get('soportes', [])
        resistencias = niveles.get('resistencias', [])
        
        # ============================================================
        # 2. OBTENER SWINGS RECIENTES (M5)
        # ============================================================
        swing_bajo = 0
        swing_alto = 0
        
        if df_m5 is not None and len(df_m5) >= 20:
            df_reciente = df_m5.iloc[-20:]
            swing_bajo = float(df_reciente['Low'].min())
            swing_alto = float(df_reciente['High'].max())
        
        # ============================================================
        # 3. OBTENER VELA H1 DE REFERENCIA
        # ============================================================
        vela_h1_ref = None
        
        if df_h1 is not None and len(df_h1) >= 5:
            df_h1_reciente = df_h1.iloc[-5:]
            
            if direccion == 'COMPRA':
                # Buscar vela bajista significativa
                for i in range(len(df_h1_reciente) - 1, -1, -1):
                    vela = df_h1_reciente.iloc[i]
                    if vela['Close'] < vela['Open']:
                        vela_h1_ref = {
                            'high': float(vela['High']),
                            'low': float(vela['Low']),
                            'open': float(vela['Open']),
                            'close': float(vela['Close'])
                        }
                        break
            else:
                # Buscar vela alcista significativa
                for i in range(len(df_h1_reciente) - 1, -1, -1):
                    vela = df_h1_reciente.iloc[i]
                    if vela['Close'] > vela['Open']:
                        vela_h1_ref = {
                            'high': float(vela['High']),
                            'low': float(vela['Low']),
                            'open': float(vela['Open']),
                            'close': float(vela['Close'])
                        }
                        break
        
        # ============================================================
        # 4. OBTENER CONFIGURACIÓN DEL MODO
        # ============================================================
        sniper_config = getattr(Umbrales, 'SNIPER_CONFIG', {})
        cfg_modo = sniper_config.get(modo, {})
        buffer_pips = cfg_modo.get('sl_buffer_pips', 3)
        buffer = buffer_pips * pip_val
        
        # ============================================================
        # 5. CALCULAR SL SEGÚN MODO
        # ============================================================
        sl = 0.0
        
        if direccion == 'COMPRA':
            # PRIORIDAD 1: SOPORTE CERCANO
            if soporte_cercano > 0 and soporte_cercano < precio_actual:
                distancia = abs(precio_actual - soporte_cercano) / precio_actual * 100
                if distancia < 2.0:
                    sl = soporte_cercano - buffer
                    self.logger.info(f"📊 {simbolo}: SL usando soporte cercano ({soporte_cercano:.{digits}f})")
                    return self._calcular_tp_estructura_2(
                        simbolo, precio_actual, direccion, modo,
                        sl, soporte_cercano, resistencia_cercana,
                        resistencias, analisis_medio, atr_m5, pip_val, digits
                    )
            
            # PRIORIDAD 2: SWING BAJO (M5)
            if swing_bajo > 0 and swing_bajo < precio_actual:
                distancia = abs(precio_actual - swing_bajo) / precio_actual * 100
                if distancia < 1.5:
                    sl = swing_bajo - buffer
                    self.logger.info(f"📊 {simbolo}: SL usando swing bajo ({swing_bajo:.{digits}f})")
                    return self._calcular_tp_estructura_2(
                        simbolo, precio_actual, direccion, modo,
                        sl, soporte_cercano, resistencia_cercana,
                        resistencias, analisis_medio, atr_m5, pip_val, digits
                    )
            
            # PRIORIDAD 3: VELA H1 DE REFERENCIA
            if vela_h1_ref is not None:
                if vela_h1_ref['low'] < precio_actual:
                    distancia = abs(precio_actual - vela_h1_ref['low']) / precio_actual * 100
                    if distancia < 1.5:
                        sl = vela_h1_ref['low'] - buffer
                        self.logger.info(f"📊 {simbolo}: SL usando vela H1 ({vela_h1_ref['low']:.{digits}f})")
                        return self._calcular_tp_estructura_2(
                            simbolo, precio_actual, direccion, modo,
                            sl, soporte_cercano, resistencia_cercana,
                            resistencias, analisis_medio, atr_m5, pip_val, digits
                        )
            
            # PRIORIDAD 4: ATR (Fallback)
            if atr_m5 > 0:
                sl_mult = cfg_modo.get('sl_mult', 1.0)
                sl_dist = atr_m5 * pip_val * sl_mult
                sl_max_dist = precio_actual * 0.02
                sl_dist = min(sl_dist, sl_max_dist)
                sl = precio_actual - sl_dist
        
        else:  # VENTA
            # PRIORIDAD 1: RESISTENCIA CERCANA
            if resistencia_cercana > 0 and resistencia_cercana > precio_actual:
                distancia = abs(resistencia_cercana - precio_actual) / precio_actual * 100
                if distancia < 2.0:
                    sl = resistencia_cercana + buffer
                    self.logger.info(f"📊 {simbolo}: SL usando resistencia cercana ({resistencia_cercana:.{digits}f})")
                    return self._calcular_tp_estructura_2(
                        simbolo, precio_actual, direccion, modo,
                        sl, soporte_cercano, resistencia_cercana,
                        resistencias, analisis_medio, atr_m5, pip_val, digits
                    )
            
            # PRIORIDAD 2: SWING ALTO (M5)
            if swing_alto > 0 and swing_alto > precio_actual:
                distancia = abs(swing_alto - precio_actual) / precio_actual * 100
                if distancia < 1.5:
                    sl = swing_alto + buffer
                    self.logger.info(f"📊 {simbolo}: SL usando swing alto ({swing_alto:.{digits}f})")
                    return self._calcular_tp_estructura_2(
                        simbolo, precio_actual, direccion, modo,
                        sl, soporte_cercano, resistencia_cercana,
                        resistencias, analisis_medio, atr_m5, pip_val, digits
                    )
            
            # PRIORIDAD 3: VELA H1 DE REFERENCIA
            if vela_h1_ref is not None:
                if vela_h1_ref['high'] > precio_actual:
                    distancia = abs(vela_h1_ref['high'] - precio_actual) / precio_actual * 100
                    if distancia < 1.5:
                        sl = vela_h1_ref['high'] + buffer
                        self.logger.info(f"📊 {simbolo}: SL usando vela H1 ({vela_h1_ref['high']:.{digits}f})")
                        return self._calcular_tp_estructura_2(
                            simbolo, precio_actual, direccion, modo,
                            sl, soporte_cercano, resistencia_cercana,
                            resistencias, analisis_medio, atr_m5, pip_val, digits
                        )
            
            # PRIORIDAD 4: ATR (Fallback)
            if atr_m5 > 0:
                sl_mult = cfg_modo.get('sl_mult', 1.0)
                sl_dist = atr_m5 * pip_val * sl_mult
                sl_max_dist = precio_actual * 0.02
                sl_dist = min(sl_dist, sl_max_dist)
                sl = precio_actual + sl_dist
        
        # Validar SL mínimo
        sl_min_pips = self._obtener_sl_minimo_universal(simbolo, modo)
        sl_dist_pips = abs(precio_actual - sl) / pip_val if pip_val > 0 else 0
        if sl_dist_pips < sl_min_pips:
            if direccion == 'COMPRA':
                sl = precio_actual - (sl_min_pips * pip_val)
            else:
                sl = precio_actual + (sl_min_pips * pip_val)
            self.logger.info(f"📊 {simbolo}: SL ajustado a mínimo ({sl_min_pips} pips)")
        
        return self._calcular_tp_estructura_2(
            simbolo, precio_actual, direccion, modo,
            sl, soporte_cercano, resistencia_cercana,
            resistencias, analisis_medio, atr_m5, pip_val, digits
        )

    def _calcular_sl_tp_estructura(self,
                                simbolo: str,
                                precio_actual: float,
                                direccion: str,
                                modo: str,
                                analisis_medio: Any,
                                analisis_pesado: Any,
                                contexto_h1: Dict,
                                df_m5: pd.DataFrame,
                                df_h1: pd.DataFrame = None,
                                atr_m5: float = 0.0) -> Tuple[float, float, float]:
        """
        Calcula SL/TP usando ESTRUCTURA REAL del mercado.
        V9.63 - CORREGIDO DEFINITIVO:
        - Maneja None en soportes/resistencias
        - Prioriza estructura sobre fórmulas
        - Valida dirección correctamente
        """
        from config.umbrales import Umbrales
        
        pip_val = self._obtener_pip_val_universal(simbolo)
        digits = self._obtener_digits_universal(simbolo)
        
        # ============================================================
        # 1. OBTENER NIVELES DE ESTRUCTURA (CON VALIDACIÓN DE None)
        # ============================================================
        soporte_cercano = contexto_h1.get('soporte_cercano', 0)
        resistencia_cercana = contexto_h1.get('resistencia_cercana', 0)
        
        # ✅ CORREGIDO V9.63: Normalizar None a 0
        if soporte_cercano is None:
            soporte_cercano = 0.0
        if resistencia_cercana is None:
            resistencia_cercana = 0.0
        
        # Obtener niveles del tracker
        niveles = contexto_h1.get('niveles', {})
        soportes = niveles.get('soportes', [])
        resistencias = niveles.get('resistencias', [])
        
        # ============================================================
        # 2. OBTENER SWINGS RECIENTES (M5)
        # ============================================================
        swing_bajo = 0.0
        swing_alto = 0.0
        
        if df_m5 is not None and len(df_m5) >= 20:
            df_reciente = df_m5.iloc[-20:]
            swing_bajo = float(df_reciente['Low'].min())
            swing_alto = float(df_reciente['High'].max())
        
        # ============================================================
        # 3. OBTENER VELA H1 DE REFERENCIA
        # ============================================================
        vela_h1_ref = None
        
        if df_h1 is not None and len(df_h1) >= 5:
            df_h1_reciente = df_h1.iloc[-5:]
            
            if direccion == 'COMPRA':
                # Buscar vela bajista significativa
                for i in range(len(df_h1_reciente) - 1, -1, -1):
                    vela = df_h1_reciente.iloc[i]
                    if vela['Close'] < vela['Open']:
                        vela_h1_ref = {
                            'high': float(vela['High']),
                            'low': float(vela['Low']),
                            'open': float(vela['Open']),
                            'close': float(vela['Close'])
                        }
                        break
            else:
                # Buscar vela alcista significativa
                for i in range(len(df_h1_reciente) - 1, -1, -1):
                    vela = df_h1_reciente.iloc[i]
                    if vela['Close'] > vela['Open']:
                        vela_h1_ref = {
                            'high': float(vela['High']),
                            'low': float(vela['Low']),
                            'open': float(vela['Open']),
                            'close': float(vela['Close'])
                        }
                        break
        
        # ============================================================
        # 4. OBTENER CONFIGURACIÓN DEL MODO
        # ============================================================
        sniper_config = getattr(Umbrales, 'SNIPER_CONFIG', {})
        cfg_modo = sniper_config.get(modo, {})
        buffer_pips = cfg_modo.get('sl_buffer_pips', 3)
        buffer = buffer_pips * pip_val
        
        # ============================================================
        # 5. CALCULAR SL SEGÚN MODO
        # ============================================================
        sl = 0.0
        
        # ✅ CORREGIDO V9.63: Validar dirección
        direccion = direccion.upper().strip()
        if direccion in ['BUY', 'LONG']:
            direccion = 'COMPRA'
        elif direccion in ['SELL', 'SHORT']:
            direccion = 'VENTA'
        
        if direccion == 'COMPRA':
            # ============================================================
            # PRIORIDAD 1: SOPORTE CERCANO
            # ============================================================
            if soporte_cercano > 0 and soporte_cercano < precio_actual:
                distancia = abs(precio_actual - soporte_cercano) / precio_actual * 100
                if distancia < 2.0:
                    sl = soporte_cercano - buffer
                    self.logger.info(f"📊 {simbolo}: SL usando soporte cercano ({soporte_cercano:.{digits}f})")
                    return self._calcular_tp_estructura_2(
                        simbolo, precio_actual, direccion, modo,
                        sl, soporte_cercano, resistencia_cercana,
                        resistencias, analisis_medio, atr_m5, pip_val, digits
                    )
            
            # ============================================================
            # PRIORIDAD 2: SWING BAJO (M5)
            # ============================================================
            if swing_bajo > 0 and swing_bajo < precio_actual:
                distancia = abs(precio_actual - swing_bajo) / precio_actual * 100
                if distancia < 1.5:
                    sl = swing_bajo - buffer
                    self.logger.info(f"📊 {simbolo}: SL usando swing bajo ({swing_bajo:.{digits}f})")
                    return self._calcular_tp_estructura_2(
                        simbolo, precio_actual, direccion, modo,
                        sl, soporte_cercano, resistencia_cercana,
                        resistencias, analisis_medio, atr_m5, pip_val, digits
                    )
            
            # ============================================================
            # PRIORIDAD 3: VELA H1 DE REFERENCIA
            # ============================================================
            if vela_h1_ref is not None:
                if vela_h1_ref['low'] > 0 and vela_h1_ref['low'] < precio_actual:
                    distancia = abs(precio_actual - vela_h1_ref['low']) / precio_actual * 100
                    if distancia < 1.5:
                        sl = vela_h1_ref['low'] - buffer
                        self.logger.info(f"📊 {simbolo}: SL usando vela H1 ({vela_h1_ref['low']:.{digits}f})")
                        return self._calcular_tp_estructura_2(
                            simbolo, precio_actual, direccion, modo,
                            sl, soporte_cercano, resistencia_cercana,
                            resistencias, analisis_medio, atr_m5, pip_val, digits
                        )
            
            # ============================================================
            # PRIORIDAD 4: ATR (Fallback)
            # ============================================================
            if atr_m5 > 0:
                sl_mult = cfg_modo.get('sl_mult', 1.0)
                sl_dist = atr_m5 * pip_val * sl_mult
                sl_max_dist = precio_actual * 0.02
                sl_dist = min(sl_dist, sl_max_dist)
                sl = precio_actual - sl_dist
        
        else:  # VENTA
            # ============================================================
            # PRIORIDAD 1: RESISTENCIA CERCANA
            # ============================================================
            if resistencia_cercana > 0 and resistencia_cercana > precio_actual:
                distancia = abs(resistencia_cercana - precio_actual) / precio_actual * 100
                if distancia < 2.0:
                    sl = resistencia_cercana + buffer
                    self.logger.info(f"📊 {simbolo}: SL usando resistencia cercana ({resistencia_cercana:.{digits}f})")
                    return self._calcular_tp_estructura_2(
                        simbolo, precio_actual, direccion, modo,
                        sl, soporte_cercano, resistencia_cercana,
                        resistencias, analisis_medio, atr_m5, pip_val, digits
                    )
            
            # ============================================================
            # PRIORIDAD 2: SWING ALTO (M5)
            # ============================================================
            if swing_alto > 0 and swing_alto > precio_actual:
                distancia = abs(swing_alto - precio_actual) / precio_actual * 100
                if distancia < 1.5:
                    sl = swing_alto + buffer
                    self.logger.info(f"📊 {simbolo}: SL usando swing alto ({swing_alto:.{digits}f})")
                    return self._calcular_tp_estructura_2(
                        simbolo, precio_actual, direccion, modo,
                        sl, soporte_cercano, resistencia_cercana,
                        resistencias, analisis_medio, atr_m5, pip_val, digits
                    )
            
            # ============================================================
            # PRIORIDAD 3: VELA H1 DE REFERENCIA
            # ============================================================
            if vela_h1_ref is not None:
                if vela_h1_ref['high'] > 0 and vela_h1_ref['high'] > precio_actual:
                    distancia = abs(vela_h1_ref['high'] - precio_actual) / precio_actual * 100
                    if distancia < 1.5:
                        sl = vela_h1_ref['high'] + buffer
                        self.logger.info(f"📊 {simbolo}: SL usando vela H1 ({vela_h1_ref['high']:.{digits}f})")
                        return self._calcular_tp_estructura_2(
                            simbolo, precio_actual, direccion, modo,
                            sl, soporte_cercano, resistencia_cercana,
                            resistencias, analisis_medio, atr_m5, pip_val, digits
                        )
            
            # ============================================================
            # PRIORIDAD 4: ATR (Fallback)
            # ============================================================
            if atr_m5 > 0:
                sl_mult = cfg_modo.get('sl_mult', 1.0)
                sl_dist = atr_m5 * pip_val * sl_mult
                sl_max_dist = precio_actual * 0.02
                sl_dist = min(sl_dist, sl_max_dist)
                sl = precio_actual + sl_dist
        
        # ============================================================
        # 6. VALIDAR SL MÍNIMO
        # ============================================================
        sl_min_pips = self._obtener_sl_minimo_universal(simbolo, modo)
        sl_dist_pips = abs(precio_actual - sl) / pip_val if pip_val > 0 else 0
        
        if sl_dist_pips < sl_min_pips:
            if direccion == 'COMPRA':
                sl = precio_actual - (sl_min_pips * pip_val)
            else:
                sl = precio_actual + (sl_min_pips * pip_val)
            self.logger.info(f"📊 {simbolo}: SL ajustado a mínimo ({sl_min_pips} pips)")
        
        # ============================================================
        # 7. VALIDAR SL SEGÚN DIRECCIÓN (CORREGIDO)
        # ============================================================
        if direccion == 'COMPRA':
            if sl >= precio_actual:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO para COMPRA (SL={sl:.{digits}f} >= precio={precio_actual:.{digits}f})")
                return 0.0, 0.0, 0.0
        else:  # VENTA
            if sl <= precio_actual:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO para VENTA (SL={sl:.{digits}f} <= precio={precio_actual:.{digits}f})")
                return 0.0, 0.0, 0.0
        
        # ============================================================
        # 8. LLAMAR A _calcular_tp_estructura_2
        # ============================================================
        return self._calcular_tp_estructura_2(
            simbolo, precio_actual, direccion, modo,
            sl, soporte_cercano, resistencia_cercana,
            resistencias, analisis_medio, atr_m5, pip_val, digits
        )

    def _calcular_tp_estructura_2(self,
                                    simbolo: str,
                                    precio_actual: float,
                                    direccion: str,
                                    modo: str,
                                    sl: float,
                                    soporte_cercano: Optional[float],
                                    resistencia_cercana: Optional[float],
                                    resistencias: List,
                                    analisis_medio: Any,
                                    atr_m5: float,
                                    pip_val: float,
                                    digits: int) -> Tuple[float, float, float]:
        """
        Calcula TP usando el SIGUIENTE nivel de estructura.
        """
        from config.umbrales import Umbrales
        
        sl_dist = abs(precio_actual - sl)
        
        if soporte_cercano is None:
            soporte_cercano = 0.0
        if resistencia_cercana is None:
            resistencia_cercana = 0.0
        
        tp_estructura = 0.0
        
        if direccion == 'COMPRA':
            if resistencia_cercana > precio_actual:
                tp_estructura = resistencia_cercana
            elif resistencias:
                resistencias_arriba = [r['precio'] for r in resistencias if r.get('precio', 0) > precio_actual and r.get('precio', 0) > 0]
                if resistencias_arriba:
                    tp_estructura = min(resistencias_arriba)
        else:
            if soporte_cercano > 0 and soporte_cercano < precio_actual:
                tp_estructura = soporte_cercano
            else:
                soportes = []
                if hasattr(self, '_contexto_h1_actual') and self._contexto_h1_actual:
                    soportes = self._contexto_h1_actual.get('soportes', [])
                if soportes:
                    soportes_abajo = [s['precio'] for s in soportes if s.get('precio', 0) < precio_actual and s.get('precio', 0) > 0]
                    if soportes_abajo:
                        tp_estructura = max(soportes_abajo)
        
        sniper_config = getattr(Umbrales, 'SNIPER_CONFIG', {})
        cfg_modo = sniper_config.get(modo, {})
        rr_target = cfg_modo.get('rr_target', 1.5)
        
        if direccion == 'COMPRA':
            tp_rr = precio_actual + (sl_dist * rr_target)
        else:
            tp_rr = precio_actual - (sl_dist * rr_target)
        
        tp_final = tp_rr
        
        if tp_estructura > 0:
            rr_estructura = abs(tp_estructura - precio_actual) / sl_dist if sl_dist > 0 else 0
            
            if direccion == 'COMPRA' and tp_estructura < tp_rr:
                if rr_estructura >= 1.5:
                    tp_final = tp_estructura
                    self.logger.info(f"📊 {simbolo}: TP usando resistencia ({tp_estructura:.{digits}f}) - R:R: {rr_estructura:.2f}")
            elif direccion == 'VENTA' and tp_estructura > tp_rr:
                if rr_estructura >= 1.5:
                    tp_final = tp_estructura
                    self.logger.info(f"📊 {simbolo}: TP usando soporte ({tp_estructura:.{digits}f}) - R:R: {rr_estructura:.2f}")
        
        tp_min_dist = sl_dist * 1.5
        if abs(tp_final - precio_actual) < tp_min_dist:
            if direccion == 'COMPRA':
                tp_final = precio_actual + tp_min_dist
            else:
                tp_final = precio_actual - tp_min_dist
            self.logger.info(f"📊 {simbolo}: TP forzado a R:R = 1.50")
        
        rr_final = abs(tp_final - precio_actual) / sl_dist if sl_dist > 0 else 0
        
        return round(sl, digits), round(tp_final, digits), rr_final    

    def _obtener_sl_minimo_universal(self, simbolo: str, modo: str = 'RETEST') -> float:
        """
        Obtiene SL mínimo en pips para CUALQUIER símbolo.
        V9.45 - CORREGIDO: XAGUSD usa 200 pips (NO 2,000)
        """
        simbolo_upper = simbolo.upper()
        
        # 1. CRIPTO (volatilidad muy alta)
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            base_min = 150
        # 2. METALES
        elif 'XAU' in simbolo_upper:
            base_min = 150
        elif 'XAG' in simbolo_upper:
            base_min = 200  # ✅ CORRECTO: 200 pips = 2.00 unidades
        # 3. ÍNDICES
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            base_min = 100
        # 4. FOREX
        elif 'JPY' in simbolo_upper:
            base_min = 25
        elif simbolo_upper in ['EURGBP', 'EURCHF', 'GBPCHF']:
            base_min = 20
        else:
            base_min = 20
        
        return base_min
    
    def _obtener_sl_maximo_universal(self, simbolo: str, modo: str = 'RETEST') -> float:
        """
        Obtiene SL máximo en pips para CUALQUIER símbolo.
        V9.39 - CORREGIDO DEFINITIVO: SL máximo REALISTA.
        
        XAUUSD: 500 pips (antes 300)
        BTCUSD: 600 pips (antes 300)
        """
        simbolo_upper = simbolo.upper()
        
        # 1. CRIPTO (volatilidad muy alta)
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            base_max = 400  # ✅ AUMENTADO de 300 a 600
        # 2. METALES
        elif 'XAU' in simbolo_upper:
            base_max = 500  # ✅ AUMENTADO de 300 a 500
        elif 'XAG' in simbolo_upper:
            base_max = 600  # ✅ AUMENTADO de 300 a 600
        # 3. ÍNDICES
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            base_max = 400  # ✅ AUMENTADO de 200 a 400
        # 4. FOREX
        elif 'JPY' in simbolo_upper:
            base_max = 200  # ✅ AUMENTADO de 150 a 200
        elif simbolo_upper in ['EURGBP', 'EURCHF', 'GBPCHF']:
            base_max = 150  # ✅ MANTENIDO
        else:
            base_max = 150  # ✅ MANTENIDO
        
        # Ajuste por modo
        if modo == 'SNIPER_ELITE':
            base_max = min(base_max, 400)  # Sniper: SL no demasiado amplio
        elif modo == 'BREAKOUT':
            base_max = min(base_max, 500)  # Breakout: puede ser amplio
        elif modo == 'PULLBACK':
            base_max = min(base_max, 400)  # Pullback: SL moderado
        
        return base_max

    def _calcular_buffer_atr(self,
                         simbolo: str,
                         atr: float,
                         modo: str,
                         regimen: str,
                         volumen_relativo: float = 1.0) -> float:
        """
        Calcula el buffer ATR dinámico según modo, régimen y volumen.
        V9.10 - DEFINITIVO: Ajusta el buffer para no ser tocado por ruido.
        """
        # Base: 50% del ATR
        factor_buffer = 0.5
        
        # Ajuste por modo
        ajustes_modo = {
            'RETEST': 0.5,       # SL debajo del soporte + 50% ATR
            'BREAKOUT': 0.3,     # SL ajustado (breakout confirmado)
            'PULLBACK': 0.4,     # SL debajo del mínimo + 40% ATR
            'NIVEL_FUERTE': 0.5,  # SL debajo del nivel + 50% ATR
            'PATRON': 0.4,       # SL según patrón + 40% ATR
            'SNIPER_ELITE': 0.3,  # SL preciso (múltiples confluencias)
            'RUPTURA_FALSA': 0.4, # SL moderado
            'VELA_BORDE': 0.5,    # SL según vela + 50% ATR
            'RETEST_FALLBACK': 0.6 # SL más amplio (fallback)
        }
        
        factor_buffer = ajustes_modo.get(modo, 0.5)
        
        # Ajuste por régimen
        ajustes_regimen = {
            'TREND_ALCISTA_FUERTE': 1.1,  # Más volatilidad en tendencia fuerte
            'TREND_BAJISTA_FUERTE': 1.1,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,          # Menos volatilidad en rango
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.7,          # Muy poca volatilidad
            'BREAKOUT_INMINENTE': 0.9,
            'INCERTO': 1.0
        }
        
        factor_regimen = ajustes_regimen.get(regimen, 1.0)
        
        # Ajuste por volumen
        if volumen_relativo > 2.0:
            factor_volumen = 0.8  # Volumen alto = confirmación fuerte = SL más ajustado
        elif volumen_relativo > 1.5:
            factor_volumen = 0.9
        elif volumen_relativo > 1.0:
            factor_volumen = 1.0
        elif volumen_relativo > 0.5:
            factor_volumen = 1.1  # Volumen bajo = confirmación débil = SL más amplio
        else:
            factor_volumen = 1.2
        
        # Buffer final
        buffer = atr * factor_buffer * factor_regimen * factor_volumen
        
        # Asegurar que el buffer sea al menos 10% del ATR
        buffer = max(buffer, atr * 0.1)
        
        return buffer

    def _obtener_atr_adaptado(self,
                          simbolo: str,
                          analisis_medio: Any,
                          df_m5: Optional[pd.DataFrame] = None) -> float:
        """
        Obtiene ATR adaptado para CUALQUIER símbolo.
        Si el ATR del análisis es 0 o inválido, calcular desde df_m5.
        """
        # 1. Intentar desde análisis medio
        if analisis_medio is not None and hasattr(analisis_medio, 'atr') and analisis_medio.atr > 0:
            return float(analisis_medio.atr)
        
        # 2. Calcular desde df_m5
        if df_m5 is not None and len(df_m5) >= 14:
            try:
                high = df_m5['High']
                low = df_m5['Low']
                close = df_m5['Close']
                
                tr = pd.concat([
                    high - low,
                    abs(high - close.shift()),
                    abs(low - close.shift())
                ], axis=1).max(axis=1)
                
                atr = float(tr.rolling(14).mean().iloc[-1])
                if atr > 0:
                    return atr
            except Exception:
                pass
        
        # 3. Fallback por tipo de activo
        simbolo_upper = simbolo.upper()
        pip_val = self._obtener_pip_val_universal(simbolo)
        
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 100.0 * pip_val  # Cripto: ATR ~100 pips
        elif any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 5.0 * pip_val  # Metales: ATR ~5 pips
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 50.0 * pip_val  # Índices: ATR ~50 pips
        else:
            return 0.0020  # Forex: ATR ~20 pips
    
    # ============================================================
    # SELECCIÓN DE MODO POR PUNTUACIÓN (V9.37 - REFACTORIZADO)
    # ============================================================

    def _seleccionar_modo_por_jerarquia(self, contexto: Dict) -> Tuple[Optional[ModoEntrada], str]:
        """
        Selecciona el modo de entrada según puntuación de condiciones cumplidas.
        V9.41 - CORREGIDO: Variable 'direccion' definida ANTES de usar.
        """
        score_h1 = contexto.get('score_h1', 0)
        score_m5 = contexto.get('score_m5', 0)
        confluencias_favorables = contexto.get('confluencias_favorables', [])
        confluencias_conflictos = contexto.get('confluencias_conflictos', [])
        en_nivel_clave = contexto.get('en_nivel_clave', False)
        regimen = contexto.get('regimen', 'INCERTO')
        volumen_relativo = contexto.get('volumen_relativo', 0)
        rr = contexto.get('rr', 0)
        patron_calidad = contexto.get('patron_calidad', 0)
        patron = contexto.get('patron', 'N/A')
        falsa_ruptura = contexto.get('falsa_ruptura', False)
        vela_borde = contexto.get('vela_borde', False)
        precio_actual = contexto.get('precio_actual', 0)
        nivel_usado = contexto.get('nivel_usado', 0)
        distancia_nivel = contexto.get('distancia_nivel', 0)
        
        # ✅ DEFINIR direccion ANTES DE USAR (CORREGIDO)
        direccion = contexto.get('direccion', 'NEUTRAL')
        tendencia_m5 = contexto.get('tendencia_m5', 'LATERAL')
        
        # ============================================================
        # ✅ NUEVO: VALIDAR DIRECCIÓN DEL M5 (CORREGIDO - MENOS ESTRICTO)
        # ============================================================
        direccion = contexto.get('direccion', 'NEUTRAL')
        tendencia_m5 = contexto.get('tendencia_m5', 'LATERAL')
        regimen = contexto.get('regimen', 'INCERTO')

        # ✅ REGLA CORRECTA: Respetar la dirección H1 como PRIORITARIA
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            # H1 es ALCISTA → SOLO COMPRA
            if direccion == 'VENTA':
                return None, "H1 en tendencia ALCISTA - no permitir VENTA"
            # PERMITIR COMPRA incluso si M5 está en BAJISTA (pullback)
            
        elif regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            # H1 es BAJISTA → SOLO VENTA
            if direccion == 'COMPRA':
                return None, "H1 en tendencia BAJISTA - no permitir COMPRA"
            # PERMITIR VENTA incluso si M5 está en ALCISTA (pullback)
            
        elif regimen in ['RANGO_AMPLIO', 'RANGO_APRETADO']:
            # En rango, ambas direcciones permitidas
            pass
        # ============================================================
        # 1. PUNTUAR CADA MODO (0-100)
        # ============================================================
        puntuaciones = {
            'SNIPER_ELITE': self._puntuar_modo_sniper_elite(
                score_h1, confluencias_favorables, confluencias_conflictos,
                en_nivel_clave, rr
            ),
            'BREAKOUT': self._puntuar_modo_breakout(
                regimen, volumen_relativo, en_nivel_clave, score_h1,
                confluencias_favorables
            ),
            'PULLBACK': self._puntuar_modo_pullback(
                regimen, en_nivel_clave, score_h1, volumen_relativo,
                confluencias_favorables
            ),
            'RETEST': self._puntuar_modo_retest(
                regimen, en_nivel_clave, score_h1,
                confluencias_favorables, confluencias_conflictos
            ),
            'NIVEL_FUERTE': self._puntuar_modo_nivel_fuerte(
                regimen, en_nivel_clave, score_h1
            ),
            'PATRON': self._puntuar_modo_patron(
                confluencias_favorables, patron_calidad
            ),
            'RUPTURA_FALSA': self._puntuar_modo_ruptura_falsa(
                falsa_ruptura, regimen
            ),
            'VELA_BORDE': self._puntuar_modo_vela_borde(
                en_nivel_clave, vela_borde
            ),
            'RETEST_FALLBACK': self._puntuar_modo_fallback(
                score_h1, confluencias_favorables, confluencias_conflictos
            ),
        }
        
        # ============================================================
        # ✅ NUEVO: FILTRAR MODOS QUE NO SON VÁLIDOS PARA M5
        # ============================================================
        
        # BREAKOUT: Solo si el precio está ROMPIENDO el nivel (no en el nivel)
        if 'BREAKOUT' in puntuaciones:
            if precio_actual > 0 and nivel_usado > 0:
                distancia_breakout = abs(precio_actual - nivel_usado) / precio_actual * 100
                if distancia_breakout < 0.1:
                    puntuaciones['BREAKOUT'] = 0
                    self.logger.info(f"⏭️ BREAKOUT descartado - Precio en nivel, no roto ({distancia_breakout:.2f}%)")
        
        # RETEST: Solo si el precio está CERCA del nivel (no lejos)
        if 'RETEST' in puntuaciones:
            if precio_actual > 0 and nivel_usado > 0:
                distancia_retest = abs(precio_actual - nivel_usado) / precio_actual * 100
                if distancia_retest > 0.5:
                    puntuaciones['RETEST'] = 0
                    self.logger.info(f"⏭️ RETEST descartado - Precio lejos del nivel ({distancia_retest:.2f}%)")
        
        # PULLBACK: Solo si hay tendencia clara en M5
        if 'PULLBACK' in puntuaciones:
            if tendencia_m5 == 'LATERAL':
                puntuaciones['PULLBACK'] = 0
                self.logger.info(f"⏭️ PULLBACK descartado - M5 en LATERAL")
        
        # ============================================================
        # 2. LOG DE PUNTUACIONES (CON FILTROS)
        # ============================================================
        if self.modo_depuracion:
            self.logger.info(f"🎯 Puntuaciones de modos para {contexto.get('simbolo', 'N/A')}:")
            for modo, puntuacion in sorted(puntuaciones.items(), key=lambda x: x[1], reverse=True):
                if puntuacion > 0:
                    self.logger.info(f"   {modo}: {puntuacion:.0f}")
        
        # ============================================================
        # 3. FILTRAR MODOS CON PUNTUACIÓN > 0
        # ============================================================
        modos_validos = {k: v for k, v in puntuaciones.items() if v > 0}
        
        if not modos_validos:
            self.logger.info(f"❌ No se encontró modo válido (ninguna puntuación > 0)")
            return None, "No se encontró modo válido"
        
        # ============================================================
        # 4. ORDENAR POR PUNTUACIÓN DESCENDENTE
        # ============================================================
        modos_ordenados = sorted(modos_validos.items(), key=lambda x: x[1], reverse=True)
        
        # ============================================================
        # 5. VERIFICAR UMBRAL MÍNIMO
        # ============================================================
        umbral_minimo = 25
        if self.modo_backtest:
            umbral_minimo = 15
        
        mejor_modo, mejor_puntuacion = modos_ordenados[0]
        
        if mejor_puntuacion < umbral_minimo:
            self.logger.info(f"⏭️ Mejor modo {mejor_modo} con puntuación insuficiente: {mejor_puntuacion:.0f} < {umbral_minimo}")
            return None, f"Puntuación insuficiente ({mejor_puntuacion:.0f})"
        
        # ============================================================
        # 6. VERIFICAR DIRECCIÓN POR RÉGIMEN
        # ============================================================
        if not self._validar_regimen_para_direccion(regimen, direccion):
            self.logger.info(f"⏭️ Dirección {direccion} no válida para régimen {regimen}")
            return None, f"Dirección no válida para régimen"
        
        # ============================================================
        # 7. SELECCIONAR MEJOR MODO
        # ============================================================
        modo_entrada = ModoEntrada(mejor_modo)
        
        self.logger.info(f"✅ MODO SELECCIONADO: {mejor_modo} (puntuación: {mejor_puntuacion:.0f})")
        
        return modo_entrada, f"Mejor puntuación: {mejor_puntuacion:.0f} ({mejor_modo})"

    # ============================================================
    # MÉTODOS DE PUNTUACIÓN POR MODO
    # ============================================================

    def _puntuar_modo_sniper_elite(self, score_h1: float, confluencias_favorables: List,
                                    confluencias_conflictos: List, en_nivel_clave: bool,
                                    rr: float) -> float:
        """
        Puntúa SNIPER_ELITE (máxima calidad, requiere múltiples confluencias).
        """
        puntuacion = 0
        
        # Score H1 alto (30 puntos máx)
        if score_h1 >= 75:
            puntuacion += 30
        elif score_h1 >= 65:
            puntuacion += 20
        elif score_h1 >= 55:
            puntuacion += 10
        
        # Confluencias favorables (40 puntos máx)
        puntuacion += min(len(confluencias_favorables) * 8, 40)
        
        # Penalización por conflictos (-30 puntos máx)
        puntuacion -= len(confluencias_conflictos) * 10
        
        # Nivel clave (15 puntos)
        if en_nivel_clave:
            puntuacion += 15
        
        # R:R favorable (15 puntos)
        if rr >= 2.5:
            puntuacion += 15
        elif rr >= 2.0:
            puntuacion += 12
        elif rr >= 1.5:
            puntuacion += 8
        
        # Penalización por R:R bajo
        if rr < 1.5:
            puntuacion -= 10
        
        return max(0, min(100, puntuacion))


    def _puntuar_modo_breakout(self, regimen: str, volumen_relativo: float,
                                en_nivel_clave: bool, score_h1: float,
                                confluencias_favorables: List) -> float:
        """
        Puntúa BREAKOUT (ruptura con volumen).
        """
        puntuacion = 0
        
        # Régimen adecuado (30 puntos)
        if regimen in ['BREAKOUT_INMINENTE', 'TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
            puntuacion += 30
        elif regimen in ['TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL']:
            puntuacion += 15
        
        # Volumen alto (30 puntos)
        if volumen_relativo > 2.0:
            puntuacion += 30
        elif volumen_relativo > 1.5:
            puntuacion += 25
        elif volumen_relativo > 1.0:
            puntuacion += 15
        elif volumen_relativo > 0.6:
            puntuacion += 8
        
        # Nivel clave (20 puntos)
        if en_nivel_clave:
            puntuacion += 20
        
        # Score H1 (15 puntos)
        if score_h1 >= 70:
            puntuacion += 15
        elif score_h1 >= 60:
            puntuacion += 10
        
        # Confluencias (10 puntos)
        puntuacion += min(len(confluencias_favorables) * 3, 10)
        
        # Penalización por volumen bajo
        if volumen_relativo < 0.6:
            puntuacion -= 15
        
        return max(0, min(100, puntuacion))


    def _puntuar_modo_pullback(self, regimen: str, en_nivel_clave: bool,
                                score_h1: float, volumen_relativo: float,
                                confluencias_favorables: List) -> float:
        """
        Puntúa PULLBACK (retroceso en tendencia).
        """
        puntuacion = 0
        
        # Régimen de tendencia (30 puntos)
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
            puntuacion += 30
        elif regimen in ['TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL']:
            puntuacion += 20
        
        # Nivel clave (20 puntos)
        if en_nivel_clave:
            puntuacion += 20
        
        # Score H1 (20 puntos)
        if score_h1 >= 65:
            puntuacion += 20
        elif score_h1 >= 55:
            puntuacion += 12
        
        # Volumen moderado (15 puntos - no debe ser breakout)
        if 0.4 <= volumen_relativo <= 0.8:
            puntuacion += 15
        elif 0.8 < volumen_relativo <= 1.2:
            puntuacion += 8
        
        # Confluencias (15 puntos)
        puntuacion += min(len(confluencias_favorables) * 5, 15)
        
        # Penalización por volumen alto (es breakout, no pullback)
        if volumen_relativo > 1.5:
            puntuacion -= 10
        
        return max(0, min(100, puntuacion))


    def _puntuar_modo_retest(self, regimen: str, en_nivel_clave: bool,
                            score_h1: float, confluencias_favorables: List,
                            confluencias_conflictos: List) -> float:
        """
        Puntúa RETEST (retoque de nivel).
        """
        puntuacion = 0
        
        # Nivel clave (30 puntos)
        if en_nivel_clave:
            puntuacion += 30
        
        # Régimen de tendencia (20 puntos)
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE',
                    'TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL']:
            puntuacion += 20
        elif regimen in ['RANGO_AMPLIO', 'RANGO_APRETADO']:
            puntuacion += 10
        
        # Score H1 (15 puntos)
        if score_h1 >= 65:
            puntuacion += 15
        elif score_h1 >= 55:
            puntuacion += 10
        elif score_h1 >= 50:
            puntuacion += 5
        
        # Confluencias favorables (20 puntos)
        puntuacion += min(len(confluencias_favorables) * 5, 20)
        
        # Penalización por conflictos (-20 puntos)
        puntuacion -= len(confluencias_conflictos) * 10
        
        return max(0, min(100, puntuacion))


    def _puntuar_modo_nivel_fuerte(self, regimen: str, en_nivel_clave: bool,
                                    score_h1: float) -> float:
        """
        Puntúa NIVEL_FUERTE (nivel con múltiples reacciones).
        """
        puntuacion = 0
        
        # Nivel clave (35 puntos)
        if en_nivel_clave:
            puntuacion += 35
        
        # Régimen de rango (20 puntos)
        if regimen in ['RANGO_AMPLIO', 'RANGO_APRETADO']:
            puntuacion += 20
        
        # Score H1 (15 puntos)
        if score_h1 >= 70:
            puntuacion += 15
        elif score_h1 >= 60:
            puntuacion += 10
        
        # Régimen de tendencia (10 puntos - puede funcionar si el nivel es fuerte)
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
            puntuacion += 10
        
        return max(0, min(100, puntuacion))


    def _puntuar_modo_patron(self, confluencias_favorables: List,
                            patron_calidad: float) -> float:
        """
        Puntúa PATRON (patrón de vela o figura técnica).
        """
        puntuacion = 0
        
        # Calidad del patrón (40 puntos)
        if patron_calidad > 50:
            puntuacion += 40
        elif patron_calidad > 35:
            puntuacion += 30
        elif patron_calidad > 25:
            puntuacion += 20
        elif patron_calidad > 15:
            puntuacion += 10
        
        # Confluencias (20 puntos)
        puntuacion += min(len(confluencias_favorables) * 5, 20)
        
        return max(0, min(100, puntuacion))


    def _puntuar_modo_ruptura_falsa(self, falsa_ruptura: bool, regimen: str) -> float:
        """
        Puntúa RUPTURA_FALSA (falsa ruptura de nivel).
        """
        puntuacion = 0
        
        # Falsa ruptura detectada (40 puntos)
        if falsa_ruptura:
            puntuacion += 40
        
        # Régimen de rango (25 puntos)
        if regimen in ['RANGO_AMPLIO', 'RANGO_APRETADO']:
            puntuacion += 25
        elif regimen in ['BREAKOUT_INMINENTE']:
            puntuacion += 15
        
        return max(0, min(100, puntuacion))


    def _puntuar_modo_vela_borde(self, en_nivel_clave: bool, vela_borde: bool) -> float:
        """
        Puntúa VELA_BORDE (vela rechazando nivel).
        """
        puntuacion = 0
        
        # Vela en borde (30 puntos)
        if vela_borde:
            puntuacion += 30
        
        # Nivel clave (25 puntos)
        if en_nivel_clave:
            puntuacion += 25
        
        return max(0, min(100, puntuacion))


    def _puntuar_modo_fallback(self, score_h1: float, confluencias_favorables: List,
                                confluencias_conflictos: List) -> float:
        """
        Puntúa RETEST_FALLBACK (último recurso).
        """
        puntuacion = 0
        
        # Score H1 suficiente (25 puntos)
        if score_h1 >= 65:
            puntuacion += 25
        elif score_h1 >= 55:
            puntuacion += 15
        elif score_h1 >= 45:
            puntuacion += 8
        
        # Confluencias (10 puntos)
        puntuacion += min(len(confluencias_favorables) * 3, 10)
        
        # Penalización por conflictos (-20 puntos)
        puntuacion -= len(confluencias_conflictos) * 10
        
        # Penalización por score bajo
        if score_h1 < 45:
            puntuacion -= 15
        
        return max(0, min(100, puntuacion))
    
    def _clasificar_confluencias(self, contexto: Dict) -> Dict[str, List[str]]:
        """Clasifica las confluencias por categorías."""
        categorias = {
            'TENDENCIA': [],
            'ESTRUCTURA': [],
            'MOMENTUM': [],
            'PRECIO_VELA': [],
            'CONTEXTO': [],
            'DIVERGENCIA': [],
        }
        
        if contexto.get('ema9') > contexto.get('ema21'):
            categorias['TENDENCIA'].append('EMA alcista')
        
        if contexto.get('adx', 0) > 20:
            categorias['TENDENCIA'].append('ADX > 20')
        
        if contexto.get('en_nivel_clave'):
            categorias['ESTRUCTURA'].append('Nivel clave')
        
        if contexto.get('rsi', 50) > 60:
            categorias['MOMENTUM'].append('RSI > 60')
        
        if contexto.get('patron_calidad', 0) > 30:
            categorias['PRECIO_VELA'].append(f'Patrón {contexto["patron"]}')
        
        if contexto.get('volumen_relativo', 0) > 1.2:
            categorias['CONTEXTO'].append('Volumen alto')
        
        if contexto.get('divergencia_rsi'):
            categorias['DIVERGENCIA'].append(f"Divergencia RSI {contexto['divergencia_rsi']}")
        
        return categorias
    
    def _log_decision_estructurado(self, simbolo: str, decision: Dict):
        """Log detallado de la decisión."""
        self.logger.info(f"📊 {simbolo}: DECISIÓN DE ENTRADA")
        self.logger.info(f"   MODO: {decision['modo']}")
        self.logger.info(f"   CONFIRMATIONS:")
        for c in decision.get('confluencias_favorables', []):
            self.logger.info(f"      ✓ {c}")
        self.logger.info(f"   CONFLICTS:")
        for c in decision.get('confluencias_conflictos', []):
            self.logger.info(f"      ✗ {c}")
        self.logger.info(f"   QUALITY:")
        self.logger.info(f"      Score final: {decision.get('score_final', 0):.1f}")
        self.logger.info(f"      R:R: {decision.get('rr', 0):.2f}")
        self.logger.info(f"      Riesgo: {decision.get('risk', 0):.2f}%")
        self.logger.info(f"   DECISIÓN: {decision['decision']}")
    
    def _validar_horario_por_simbolo(self, simbolo: str, hora_col_float: float) -> Tuple[bool, str, float]:
        """
        Valida el horario según el tipo de activo y DÍA DE LA SEMANA.
        V9.32 - USA HorarioMercado de tiempo.py
        """
        from utils.tiempo import HorarioMercado
        
        # ✅ USAR EL SISTEMA UNIFICADO DE HORARIOS
        horario = HorarioMercado(zona_usuario='COLOMBIA')
        
        # Obtener hora actual con día
        from datetime import datetime, timezone
        ahora = datetime.now(timezone.utc)
        
        # Usar el método de HorarioMercado
        operativo, razon = horario.es_horario_operativo(simbolo, ahora)
        
        if operativo:
            # Si está operativo, obtener calidad
            calidad = horario.obtener_calidad_horario(simbolo, ahora)
            score_minimo = calidad.get('score_minimo', 50)
            
            # Determinar etapa
            if 'EXCELENTE' in calidad['calidad']:
                etapa = 'EXCELENTE'
                bono = 0
            elif 'BUENA' in calidad['calidad']:
                etapa = 'BUENA'
                bono = 0
            elif 'REGULAR' in calidad['calidad']:
                etapa = 'REGULAR'
                bono = 10
            else:
                etapa = 'NORMAL'
                bono = 0
            
            return True, etapa, bono
        else:
            return False, razon, 999.0

    def _validar_capital_minimo(self, simbolo: str) -> Tuple[bool, str]:
        """
        Valida si el capital actual es suficiente para operar el símbolo.
        V9.37 - CRÍTICO: Evita disparar operaciones que no se pueden ejecutar.
        """
        # Obtener capital actual
        if not hasattr(self, 'orquestador') or not self.orquestador:
            return True, "OK"
        
        try:
            capital = self.orquestador.gestion_riesgo.capital_actual
            if capital is None:
                return True, "OK"
            
            # Convertir a float
            capital = float(capital)
            
            if capital <= 0:
                return False, "Capital insuficiente (0)"
            
            simbolo_upper = simbolo.upper()
            
            # Capital mínimo por tipo de activo
            CAPITAL_MINIMO = {
                # Índices
                'US30': 1500, 'NAS100': 1500, 'US500': 1500, 'SP500': 1500,
                # Metales
                'XAUUSD': 500, 'XAGUSD': 500,
                # Cripto
                'BTCUSD': 200, 'ETHUSD': 200, 'SOLUSD': 200,
                # Forex
                'EURUSD': 100, 'GBPUSD': 100, 'USDJPY': 100,
                'AUDUSD': 100, 'USDCAD': 100, 'USDCHF': 100,
                'EURGBP': 100, 'EURJPY': 100, 'GBPJPY': 100,
                'AUDJPY': 100, 'NZDUSD': 100, 'EURNZD': 100,
                'GBPAUD': 100, 'GBPCHF': 100, 'EURCHF': 100,
                'AUDCAD': 100, 'AUDCHF': 100, 'CADJPY': 100,
                'CHFJPY': 100, 'EURAUD': 100, 'EURCAD': 100,
                'GBPCAD': 100, 'NZDJPY': 100,
            }
            
            capital_minimo = CAPITAL_MINIMO.get(simbolo_upper, 100)
            
            if capital < capital_minimo:
                return False, f"Capital insuficiente para {simbolo_upper} (${capital:.2f} < ${capital_minimo})"
            
            return True, "OK"
            
        except Exception as e:
            self.logger.debug(f"⚠️ Error validando capital para {simbolo}: {e}")
            return True, "OK"
    
    def set_modo_backtest(self, modo: bool = True):
        """Activa/desactiva modo backtest."""
        self.modo_backtest = modo
        self._cargar_umbrales()
        self.detector_modos.set_modo_backtest(modo)
        self.logger.info(f"🔧 SniperChecklist: modo backtest {'ACTIVADO' if modo else 'DESACTIVADO'}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del sniper."""
        stats = self._stats.copy()
        total = stats['total_evaluaciones']
        stats['tasa_disparo'] = (stats['disparos'] / total * 100) if total > 0 else 0
        return stats


def create_sniper_checklist(pipeline: Any,
                            analisis_capas: Any,
                            modo_selector: Any,
                            entry_timer: Any,
                            gestor_stops: Any,
                            config: Optional[Any] = None,
                            almacen: Optional[Any] = None,
                            mt5: Optional[Any] = None,
                            noticias: Optional[Any] = None,
                            patron_tracker: Optional[Any] = None,
                            ml_optimizer: Optional[Any] = None,
                            analysis_cache: Optional[Any] = None,
                            modo_depuracion: bool = False,
                            modo_backtest: bool = False) -> SniperChecklist:
    """Crea una instancia de SniperChecklist."""
    return SniperChecklist(
        pipeline=pipeline,
        analisis_capas=analisis_capas,
        modo_selector=modo_selector,
        entry_timer=entry_timer,
        gestor_stops=gestor_stops,
        config=config,
        almacen=almacen,
        mt5=mt5,
        noticias=noticias,
        patron_tracker=patron_tracker,
        ml_optimizer=ml_optimizer,
        analysis_cache=analysis_cache,
        modo_depuracion=modo_depuracion,
        modo_backtest=modo_backtest
    )