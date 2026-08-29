#!/usr/bin/env python3
"""
scripts/diagnosticar_contexto_masivo_con_sniper.py
Diagnóstico masivo del flujo del contexto H1 + ejecución del sniper.
Procesa todos los símbolos y verifica si el sniper detecta modos.
"""

import logging
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

# Añadir el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Config
from data.almacenamiento_sqlite import AlmacenamientoSQLite
from mt5.conector_mt5 import ConectorPepperstone
from utils.cache import CacheUnificado
from utils.logger_persistente import LoggerPersistente
from utils.helpers import safe_float

# Módulos de análisis
from analysis.capas import AnalisisPorCapas
from analysis.regimen import MarketRegimeFilter
from analysis.scoring import ScoreEngine
from analysis.niveles import NivelTracker
from analysis.pipeline import PipelineOportunidades, FaseOportunidad
from analysis.capas_rapido import AnalisisRapidoEngine
from analysis.capas_medio import AnalisisMedioEngine
from analysis.capas_pesado import AnalisisPesadoEngine

# Módulos del sniper
from trading.sniper.sniper_checklist import SniperChecklist, ModoEntrada
from trading.sniper.sniper_validacion import SniperValidador
from trading.sniper.sniper_modos import DetectorModos
from trading.sniper.sniper_scoring import CalculadorScoreSniper
from trading.sniper.sniper_sl_tp import CalculadorSLTP
from trading.sniper.sniper_quality import ValidadorCalidad

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('DiagnosticoContextoSniper')


class DiagnosticadorContextoSniper:
    """
    Diagnostica el flujo del contexto H1 y la ejecución del sniper.
    """
    
    def __init__(self, simbolos: list = None):
        self.simbolos = simbolos or Config.SIMBOLOS_COMPLETOS
        self.logger = logging.getLogger('DiagnosticoContextoSniper')
        self.logger.info("=" * 60)
        self.logger.info(f"🔍 DIAGNÓSTICO MASIVO + SNIPER - {len(self.simbolos)} símbolos")
        self.logger.info("=" * 60)
        
        # Inicializar componentes
        self.almacen = AlmacenamientoSQLite()
        self.mt5 = ConectorPepperstone(
            login=Config.MT5_LOGIN,
            password=Config.MT5_PASSWORD,
            server=Config.MT5_SERVER,
            magic_number=Config.MAGIC_NUMBER,
            demo=Config.MT5_DEMO
        )
        self.cache = CacheUnificado(
            persist_dir=Path("data/cache"),
            almacen=self.almacen
        )
        
        # Análisis
        self.regimen_filter = MarketRegimeFilter(config=Config)
        self.score_engine = ScoreEngine(config=Config, analysis_cache=self.cache)
        self.nivel_tracker = NivelTracker(
            almacen=self.almacen,
            config=Config,
            modo_inicial=True
        )
        self.analisis_capas = AnalisisPorCapas(
            config=Config,
            score_engine=self.score_engine,
            nivel_tracker=self.nivel_tracker
        )
        self.pipeline = PipelineOportunidades(
            config=Config,
            umbral_fase_1=50,
            umbral_fase_2=55,
            umbral_fase_3=60,
            modo_backtest=False,
            almacen=self.almacen
        )
        
        # Sniper
        self.sniper_checklist = SniperChecklist(
            pipeline=self.pipeline,
            config=Config,
            almacen=self.almacen,
            mt5=self.mt5,
            modo_depuracion=False,
            modo_backtest=False
        )
        
        # Estadísticas
        self.estadisticas = {
            'total': 0,
            'datos_h1': 0,
            'rapido_aprobado': 0,
            'niveles_detectados': 0,
            'medio_aprobado': 0,
            'pesado_aprobado': 0,
            'contexto_construido': 0,
            'contexto_guardado': 0,
            'sniper_recibe_contexto': 0,
            'sniper_detecta_modo': 0,
            'modos_detectados': {},
            'soportes_promedio': 0,
            'resistencias_promedio': 0,
            'score_promedio': 0,
        }
        
        self.logger.info("✅ Componentes inicializados")
    
    def conectar_mt5(self) -> bool:
        """Conecta a MT5."""
        self.logger.info("🔗 Conectando a MT5...")
        if self.mt5.conectar():
            self.logger.info("✅ Conectado a MT5")
            return True
        self.logger.error("❌ No se pudo conectar a MT5")
        return False
    
    def obtener_datos_h1(self, simbolo: str) -> any:
        """Obtiene datos H1 desde la caché para un símbolo."""
        self.logger.debug(f"📥 Obteniendo datos H1 para {simbolo}...")
        df = self.cache.get_datos(
            simbolo=simbolo,
            timeframe=60,
            n_velas=250,
            fetch_func=self.mt5.obtener_datos
        )
        return df
    
    def obtener_datos_m5(self, simbolo: str) -> any:
        """Obtiene datos M5 desde la caché para un símbolo."""
        self.logger.debug(f"📥 Obteniendo datos M5 para {simbolo}...")
        df = self.cache.get_datos(
            simbolo=simbolo,
            timeframe=5,
            n_velas=150,
            fetch_func=self.mt5.obtener_datos
        )
        return df
    
    def diagnosticar_simbolo(self, simbolo: str) -> dict:
        """Diagnostica el flujo para un solo símbolo y ejecuta el sniper."""
        resultado = {
            'simbolo': simbolo,
            'datos_h1': False,
            'rapido_aprobado': False,
            'niveles_detectados': 0,
            'niveles_resistencias': 0,
            'medio_aprobado': False,
            'pesado_aprobado': False,
            'contexto_construido': False,
            'contexto_guardado': False,
            'sniper_recibe_contexto': False,
            'sniper_detecta_modo': False,
            'modo_detectado': None,
            'score_h1': 0.0,
            'soportes': 0,
            'resistencias': 0,
        }
        
        try:
            # 1. Obtener datos H1
            df_h1 = self.obtener_datos_h1(simbolo)
            if df_h1 is None or len(df_h1) < 100:
                self.logger.warning(f"⏭️ {simbolo}: Datos H1 insuficientes")
                return resultado
            resultado['datos_h1'] = True
            
            # 2. Análisis rápido
            rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
            if rapido is None or not rapido.pasa_filtro:
                self.logger.debug(f"⏭️ {simbolo}: Filtro rápido falló")
                return resultado
            resultado['rapido_aprobado'] = True
            
            # 3. Detectar niveles
            precio_actual = df_h1['Close'].iloc[-1]
            niveles = self.nivel_tracker.detectar_y_actualizar_niveles(
                simbolo=simbolo,
                df=df_h1,
                precio_actual=precio_actual,
                timeframe='H1'
            )
            soportes = niveles.get('soportes', [])
            resistencias = niveles.get('resistencias', [])
            resultado['niveles_detectados'] = len(soportes)
            resultado['niveles_resistencias'] = len(resistencias)
            
            if not soportes and not resistencias:
                self.logger.debug(f"⏭️ {simbolo}: No se detectaron niveles")
                return resultado
            
            # 4. Análisis medio
            medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
            if medio is None or not medio.pasa_filtro:
                self.logger.debug(f"⏭️ {simbolo}: Filtro medio falló")
                return resultado
            resultado['medio_aprobado'] = True
            
            # 5. Análisis pesado
            pesado = self.analisis_capas.analisis_pesado(df_h1, simbolo, None, None, niveles, medio)
            if pesado is None:
                self.logger.debug(f"⏭️ {simbolo}: Análisis pesado falló")
                return resultado
            resultado['pesado_aprobado'] = True
            
            # 6. Calcular score H1
            score_h1 = self.score_engine.calcular_score_h1(
                score_estructura=pesado.score_estructura,
                score_momentum=pesado.score_momentum,
                score_confluencia=pesado.score_confluencia,
                score_institucional=pesado.score_institucional,
                simbolo=simbolo
            ).score
            resultado['score_h1'] = score_h1
            
            # 7. Determinar dirección y régimen
            direccion = 'COMPRA' if medio.rsi > 60 else 'VENTA' if medio.rsi < 40 else 'NEUTRAL'
            regimen_data = self.regimen_filter.clasificar(simbolo, None, df_h1)
            regimen = regimen_data.regimen.value
            
            # 8. Construir contexto H1
            contexto_h1 = {
                'score': score_h1,
                'direccion': direccion,
                'regimen': regimen,
                'en_nivel_clave': medio.en_nivel_clave,
                'soporte_cercano': medio.soporte_cercano,
                'resistencia_cercana': medio.resistencia_cercana,
                'soporte_hits': medio.soporte_hits,
                'resistencia_hits': medio.resistencia_hits,
                'adx': medio.adx,
                'rsi': medio.rsi,
                'patron_principal': pesado.patron_principal,
                'wyckoff_fase': pesado.wyckoff_fase,
                'divergencia_rsi': pesado.divergencia_rsi,
                'divergencia_macd': pesado.divergencia_macd,
                'niveles': {
                    'soportes': [{'precio': s['precio'], 'hits': s['hits']} for s in soportes[:5]],
                    'resistencias': [{'precio': r['precio'], 'hits': r['hits']} for r in resistencias[:5]]
                }
            }
            resultado['contexto_construido'] = True
            resultado['soportes'] = len(contexto_h1['niveles']['soportes'])
            resultado['resistencias'] = len(contexto_h1['niveles']['resistencias'])
            
            # 9. Guardar en pipeline
            analisis = {'rapido': rapido, 'medio': medio, 'pesado': pesado}
            estado = self.pipeline.actualizar_fase_1(
                simbolo=simbolo,
                analisis=analisis,
                score=score_h1,
                direccion=direccion,
                regimen=regimen,
                contexto_h1=contexto_h1,
                analisis_pesado=pesado
            )
            
            if estado is None:
                self.logger.debug(f"⏭️ {simbolo}: Pipeline rechazó la oportunidad")
                return resultado
            resultado['contexto_guardado'] = True
            
            # 10. Verificar consulta del sniper
            sniper_contexto = estado.contexto_h1
            if sniper_contexto and sniper_contexto.get('niveles'):
                resultado['sniper_recibe_contexto'] = True
            
            # 11. Obtener datos M5 para el sniper
            df_m5 = self.obtener_datos_m5(simbolo)
            if df_m5 is None or len(df_m5) < 50:
                self.logger.debug(f"⏭️ {simbolo}: Datos M5 insuficientes para sniper")
                return resultado
            
            # 12. Ejecutar el sniper
            self.logger.info(f"🎯 {simbolo}: Ejecutando sniper...")
            sniper_resultado = self.sniper_checklist.evaluar_sniper_optimizado(
                simbolo=simbolo,
                df_m5=df_m5,
                precio_actual=df_m5['Close'].iloc[-1],
                direccion=direccion,
                estado_pipeline=estado,
                analisis_rapido=rapido,
                analisis_medio=medio,
                ejecutar_pesado=False,
                contexto_h1=contexto_h1,
                info_tick=None,
                calidad_horario='REGULAR'
            )
            
            if sniper_resultado:
                resultado['sniper_detecta_modo'] = True
                resultado['modo_detectado'] = sniper_resultado.get('modo', 'DESCONOCIDO')
                self.logger.info(f"✅ {simbolo}: Sniper dispara con modo {sniper_resultado.get('modo')}")
            else:
                self.logger.debug(f"⏭️ {simbolo}: Sniper no detectó modo")
            
            self.logger.info(f"✅ {simbolo}: OK (score={score_h1:.1f}, soportes={len(soportes)}, resistencias={len(resistencias)})")
            
            return resultado
            
        except Exception as e:
            self.logger.error(f"❌ Error en {simbolo}: {e}")
            return resultado
    
    def diagnosticar_todos(self):
        """Diagnostica todos los símbolos y ejecuta el sniper."""
        self.logger.info(f"🚀 INICIANDO DIAGNÓSTICO MASIVO + SNIPER...")
        
        start_time = time.time()
        resultados = []
        
        for simbolo in self.simbolos:
            resultado = self.diagnosticar_simbolo(simbolo)
            resultados.append(resultado)
            
            # Actualizar estadísticas
            self.estadisticas['total'] += 1
            if resultado['datos_h1']:
                self.estadisticas['datos_h1'] += 1
            if resultado['rapido_aprobado']:
                self.estadisticas['rapido_aprobado'] += 1
            if resultado['niveles_detectados'] > 0:
                self.estadisticas['niveles_detectados'] += 1
                self.estadisticas['soportes_promedio'] += resultado['niveles_detectados']
                self.estadisticas['resistencias_promedio'] += resultado['niveles_resistencias']
            if resultado['medio_aprobado']:
                self.estadisticas['medio_aprobado'] += 1
            if resultado['pesado_aprobado']:
                self.estadisticas['pesado_aprobado'] += 1
            if resultado['contexto_construido']:
                self.estadisticas['contexto_construido'] += 1
                self.estadisticas['score_promedio'] += resultado['score_h1']
            if resultado['contexto_guardado']:
                self.estadisticas['contexto_guardado'] += 1
            if resultado['sniper_recibe_contexto']:
                self.estadisticas['sniper_recibe_contexto'] += 1
            if resultado['sniper_detecta_modo']:
                self.estadisticas['sniper_detecta_modo'] += 1
                modo = resultado['modo_detectado'] or 'DESCONOCIDO'
                self.estadisticas['modos_detectados'][modo] = self.estadisticas['modos_detectados'].get(modo, 0) + 1
        
        elapsed = time.time() - start_time
        
        # Calcular promedios
        if self.estadisticas['niveles_detectados'] > 0:
            self.estadisticas['soportes_promedio'] /= self.estadisticas['niveles_detectados']
            self.estadisticas['resistencias_promedio'] /= self.estadisticas['niveles_detectados']
        if self.estadisticas['contexto_construido'] > 0:
            self.estadisticas['score_promedio'] /= self.estadisticas['contexto_construido']
        
        # Imprimir resumen
        self.logger.info("=" * 60)
        self.logger.info("📊 RESUMEN DEL DIAGNÓSTICO MASIVO + SNIPER:")
        self.logger.info(f"   Tiempo total: {elapsed:.2f}s")
        self.logger.info(f"   Símbolos procesados: {self.estadisticas['total']}")
        self.logger.info(f"   Datos H1 obtenidos: {self.estadisticas['datos_h1']}")
        self.logger.info(f"   Filtro rápido aprobado: {self.estadisticas['rapido_aprobado']}")
        self.logger.info(f"   Niveles detectados: {self.estadisticas['niveles_detectados']}")
        self.logger.info(f"   Filtro medio aprobado: {self.estadisticas['medio_aprobado']}")
        self.logger.info(f"   Análisis pesado aprobado: {self.estadisticas['pesado_aprobado']}")
        self.logger.info(f"   Contexto H1 construido: {self.estadisticas['contexto_construido']}")
        self.logger.info(f"   Contexto H1 guardado en pipeline: {self.estadisticas['contexto_guardado']}")
        self.logger.info(f"   Sniper recibe contexto: {self.estadisticas['sniper_recibe_contexto']}")
        self.logger.info(f"   Sniper detecta modo: {self.estadisticas['sniper_detecta_modo']}")
        self.logger.info("")
        self.logger.info("📊 MODOS DETECTADOS:")
        for modo, count in sorted(self.estadisticas['modos_detectados'].items()):
            self.logger.info(f"   {modo}: {count}")
        self.logger.info("")
        self.logger.info("📊 PROMEDIOS:")
        self.logger.info(f"   Soportes promedio: {self.estadisticas['soportes_promedio']:.1f}")
        self.logger.info(f"   Resistencias promedio: {self.estadisticas['resistencias_promedio']:.1f}")
        self.logger.info(f"   Score H1 promedio: {self.estadisticas['score_promedio']:.1f}")
        self.logger.info("=" * 60)
        
        # Detalles por símbolo
        self.logger.info("\n📊 DETALLES POR SÍMBOLO:")
        for r in resultados:
            sniper_estado = "✅" if r['sniper_detecta_modo'] else "❌"
            modo = r['modo_detectado'] or 'NINGUNO'
            self.logger.info(f"   {r['simbolo']}: sniper={sniper_estado} modo={modo} score={r['score_h1']:.1f} soportes={r['soportes']} resistencias={r['resistencias']}")
        
        return resultados
    
    def limpiar(self):
        """Limpia recursos."""
        self.mt5.desconectar()
        self.almacen.cerrar()
        self.logger.info("🧹 Recursos limpiados")


def main():
    """Función principal."""
    diagnosticador = DiagnosticadorContextoSniper()
    try:
        diagnosticador.diagnosticar_todos()
    except Exception as e:
        logger.error(f"❌ Error durante el diagnóstico: {e}", exc_info=True)
    finally:
        diagnosticador.limpiar()


if __name__ == "__main__":
    main()