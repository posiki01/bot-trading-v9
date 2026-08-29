#!/usr/bin/env python3
"""
noticias/sistema_noticias.py (V9.2 - REFACTORIZADO)
Sistema de Noticias con Ponderación Temporal y Aprovechamiento de Divisas.

MEJORAS V9.2:
- Eliminada dependencia circular con fuentes.py
- Importa EventoNoticia e ImpactoNoticia desde eventos.py
- Código más limpio y mantenible
"""

import os
import json
import time
import logging
import re
import difflib
import requests
import feedparser
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple, Set
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
import threading

# ============================================================
# IMPORTS DE MÓDULOS INTERNOS
# ============================================================

from noticias.eventos import ImpactoNoticia, EventoNoticia
from noticias.fuentes import (
    FuenteFMP, FuenteFinnhub, FuenteDailyFX,
    FuenteForexFactory, FuenteInvestingRSS
)

try:
    from utils.logger_persistente import LoggerPersistente
    _logger_persistente = LoggerPersistente()
    logger = _logger_persistente.get_logger()
except ImportError:
    logger = logging.getLogger('BotTrading.Noticias')

try:
    from config.settings import Config
except ImportError:
    Config = None

try:
    from utils.cache import CacheUnificado
except ImportError:
    DataCache = None

try:
    from data.almacenamiento_sqlite import AlmacenamientoSQLite
except ImportError:
    AlmacenamientoSQLite = None

try:
    from config.news_keywords import PALABRAS_CLAVE_IMPACTO, KEYWORDS_DIVISAS_NLP
except ImportError:
    PALABRAS_CLAVE_IMPACTO = {}
    KEYWORDS_DIVISAS_NLP = {}

try:
    from utils.crypto_client import FreeCryptoAPIClient
except ImportError:
    FreeCryptoAPIClient = None

# ============================================================
# CONSTANTES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MAX_EVENTOS_MEMORIA = 200
MAX_NOTICIAS_MEMORIA = 50
DIAS_PARA_LIMPIAR = 7
COT_CACHE_TTL_HORAS = 48


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class SistemaNoticias:
    """
    Sistema completo de noticias con ponderación temporal y deduplicación.
    V9.2 - REFACTORIZADO.
    """

    def __init__(self, config=None, notificador=None, almacen=None, data_cache=None):
        """
        Inicializa el sistema de noticias.
        
        Args:
            config: Configuración (Config o None)
            notificador: Sistema de notificaciones
            almacen: Almacenamiento SQLite (opcional)
            data_cache: Caché de datos (opcional)
        """
        self.config = config or Config
        self.notificador = notificador
        self.almacen = almacen
        self.data_cache = data_cache
        self.logger = logger
        
        # Cargar configuración
        self._cargar_configuracion()
        
        # Estado
        self.eventos: List[EventoNoticia] = []
        self.noticias: List[Dict[str, Any]] = []
        self._cache_sentimiento_divisa: Dict[str, Tuple[float, datetime]] = {}
        self._ultima_actualizacion_calendario: Optional[datetime] = None
        self._cftc_failure_count = 0
        self._cftc_last_failure_time = None
        self._eventos_lock = threading.RLock()
        
        # Inicializar cliente crypto
        self._crypto_client = None
        if FreeCryptoAPIClient is not None:
            try:
                self._crypto_client = FreeCryptoAPIClient()
            except Exception as e:
                self.logger.warning(f"No se pudo inicializar FreeCryptoAPIClient: {e}")
        
        # ============================================================
        # INICIALIZAR FUENTES DE NOTICIAS
        # ============================================================
        
        self._fuentes = self._inicializar_fuentes()
        self.logger.info(f"📰 {len(self._fuentes)} fuentes de noticias inicializadas")
        
        # Palabras clave
        self.palabras_clave = PALABRAS_CLAVE_IMPACTO
        self.keywords_divisas = KEYWORDS_DIVISAS_NLP
        
        # Regex para divisas
        self._regex_divisas_cache = {
            div: re.compile("|".join([rf"\b{re.escape(kw)}\b" for kw in kws]), re.IGNORECASE)
            for div, kws in self.keywords_divisas.items()
        }
        
        # Eventos críticos para bloqueo
        self.eventos_criticos_bloqueo = [
            'NFP', 'Nonfarm Payrolls', 'FOMC', 'Federal Reserve',
            'CPI', 'Inflation', 'GDP', 'PIB',
            'War', 'Guerra', 'Nuclear', 'Black Swan'
        ]
        
        # Cargar datos desde almacenamiento
        self._cargar_desde_almacen()
        
        self.logger.info(f"📰 SistemaNoticias V9.2 inicializado")
        self.logger.info(f"   Eventos: {len(self.eventos)}")
        self.logger.info(f"   Noticias: {len(self.noticias)}")
        self.logger.info(f"   Fuentes: {len(self._fuentes)}")
    
    def _cargar_configuracion(self):
        """Carga configuración desde Config."""
        if self.config is None:
            self.modo = 'APROVECHAR'
            self.sent_fuerte = 0.6
            self.sent_negativo = -0.6
            self.lote_bonus = 1.3
            self.lote_penalty = 0.7
            self.cache_ttl_minutos = 5
            return
        
        self.modo = getattr(self.config, 'NOTICIAS_MODO', 'APROVECHAR')
        self.sent_fuerte = getattr(self.config, 'SENTIMIENTO_FUERTE', 0.6)
        self.sent_negativo = getattr(self.config, 'SENTIMIENTO_NEGATIVO', -0.6)
        self.lote_bonus = getattr(self.config, 'LOTE_BONUS_NOTICIA_FAVORABLE', 1.3)
        self.lote_penalty = getattr(self.config, 'LOTE_PENALTY_NOTICIA_CONTRA', 0.7)
        self.cache_ttl_minutos = getattr(self.config, 'MINUTOS_CACHE_NOTICIAS', 5)
    
    def _inicializar_fuentes(self) -> List:
        """Inicializa las fuentes de noticias con manejo de errores."""
        fuentes = []
        
        # ✅ OBTENER KEYS DEL ENTORNO
        import os
        fmp_key = os.getenv('FMP_API_KEY', '')
        finnhub_key = os.getenv('FINNHUB_API_KEY', '')
        
        # ✅ LOG DE DIAGNÓSTICO
        self.logger.info(f"🔑 FMP_API_KEY: {'✅' if fmp_key else '❌'} Configurada")
        self.logger.info(f"🔑 FINNHUB_API_KEY: {'✅' if finnhub_key else '❌'} Configurada")
        
        # ✅ FMP
        if fmp_key:
            try:
                fuentes.append(FuenteFMP(fmp_key))
                self.logger.info(f"📰 Fuente FMP añadida")
            except Exception as e:
                self.logger.warning(f"⚠️ FMP no disponible: {e}")
        
        # ✅ Finnhub
        if finnhub_key:
            try:
                fuentes.append(FuenteFinnhub(finnhub_key))
                self.logger.info(f"📰 Fuente Finnhub añadida")
            except Exception as e:
                self.logger.warning(f"⚠️ Finnhub no disponible: {e}")
        
        # ✅ Fuentes gratuitas
        fuentes.append(FuenteDailyFX())
        fuentes.append(FuenteForexFactory())
        fuentes.append(FuenteInvestingRSS())
        
        self.logger.info(f"📰 {len(fuentes)} fuentes de noticias inicializadas")
        return fuentes
    
    # ============================================================
    # ALMACENAMIENTO (SQLite + JSON Fallback)
    # ============================================================
    
    def _cargar_desde_almacen(self):
        """Carga datos desde almacenamiento (SQLite o JSON)."""
        # Intentar SQLite primero
        if self.almacen is not None:
            try:
                # Cargar eventos
                eventos_data = self.almacen.obtener_configuracion().get('eventos_noticias', [])
                if eventos_data:
                    self.eventos = [EventoNoticia.from_dict(ev) for ev in eventos_data]
                    self.logger.info(f"📰 {len(self.eventos)} eventos cargados desde SQLite")
                
                # Cargar noticias
                noticias_data = self.almacen.obtener_configuracion().get('noticias_rss', [])
                if noticias_data:
                    self.noticias = noticias_data
                    self.logger.info(f"📰 {len(self.noticias)} noticias cargadas desde SQLite")
                
                return
            except Exception as e:
                self.logger.warning(f"Error cargando desde SQLite: {e}, usando JSON fallback")
        
        # Fallback: JSON
        self._cargar_calendario_cache()
        self._cargar_noticias_rss()
    
    def _guardar_en_almacen(self):
        """Guarda datos en almacenamiento (SQLite o JSON)."""
        # Intentar SQLite
        if self.almacen is not None:
            try:
                config = self.almacen.obtener_configuracion()
                
                # Limpiar eventos antiguos
                self._limpiar_eventos_antiguos()
                
                config['eventos_noticias'] = [ev.to_dict() for ev in self.eventos[:MAX_EVENTOS_MEMORIA]]
                config['noticias_rss'] = self.noticias[:MAX_NOTICIAS_MEMORIA]
                config['ultima_actualizacion_noticias'] = datetime.now(timezone.utc).isoformat()
                
                self.almacen.guardar_configuracion(config)
                self.logger.debug("💾 Datos guardados en SQLite")
                return
            except Exception as e:
                self.logger.warning(f"Error guardando en SQLite: {e}, usando JSON fallback")
        
        # Fallback: JSON
        self._guardar_calendario_cache()
        self._guardar_noticias_rss()
    
    def _cargar_calendario_cache(self, max_edad_horas: int = 24) -> bool:
        """Carga calendario desde JSON (fallback)."""
        ruta_cache = DATA_DIR / "calendario_noticias_v2.json"
        if not ruta_cache.exists():
            return False
        
        try:
            with open(ruta_cache, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, dict) or 'eventos' not in data:
                return False
            
            ultima_act = datetime.fromisoformat(data.get('fecha_actualizacion', ''))
            if ultima_act.tzinfo is None:
                ultima_act = ultima_act.replace(tzinfo=timezone.utc)
            
            ahora = datetime.now(timezone.utc)
            if (ahora - ultima_act).total_seconds() > max_edad_horas * 3600:
                return False
            
            self.eventos = [EventoNoticia.from_dict(ev) for ev in data.get('eventos', [])]
            self._ultima_actualizacion_calendario = ultima_act
            self.logger.info(f"📰 Calendario cargado desde JSON ({len(self.eventos)} eventos)")
            return True
        except Exception as e:
            self.logger.warning(f"Error cargando caché de calendario: {e}")
            return False
    
    def _guardar_calendario_cache(self):
        """Guarda calendario en JSON (fallback)."""
        try:
            ruta_cache = DATA_DIR / "calendario_noticias_v2.json"
            ruta_cache.parent.mkdir(parents=True, exist_ok=True)
            
            temp_path = ruta_cache.with_suffix('.tmp')
            data = {
                'fecha_actualizacion': datetime.now(timezone.utc).isoformat(),
                'eventos': [ev.to_dict() for ev in self.eventos[:MAX_EVENTOS_MEMORIA]]
            }
            
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(ruta_cache)
        except Exception as e:
            self.logger.warning(f"Error guardando caché: {e}")
    
    def _cargar_noticias_rss(self) -> bool:
        """Carga noticias RSS desde JSON (fallback)."""
        ruta_noticias = DATA_DIR / "noticias_rss.json"
        if not ruta_noticias.exists():
            return False
        
        try:
            with open(ruta_noticias, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                return False
            
            noticias_cargadas = []
            for item in data:
                try:
                    fecha_str = item.get('fecha')
                    if not fecha_str:
                        continue
                    fecha = datetime.fromisoformat(fecha_str)
                    if fecha.tzinfo is None:
                        fecha = fecha.replace(tzinfo=timezone.utc)
                    
                    noticia = {
                        'fecha': fecha,
                        'titulo': item.get('titulo', ''),
                        'sentimiento': item.get('sentimiento', 0.0),
                        'impacto': item.get('impacto', 0.0),
                        'divisa': item.get('divisa', 'ALL'),
                        'texto': item.get('texto', ''),
                        'fuente': item.get('fuente', ''),
                        'url': item.get('url', '')
                    }
                    noticias_cargadas.append(noticia)
                except Exception:
                    continue
            
            if noticias_cargadas:
                self.noticias = noticias_cargadas[-MAX_NOTICIAS_MEMORIA:]
                self.logger.info(f"📰 {len(self.noticias)} noticias RSS cargadas desde JSON")
                return True
        except Exception as e:
            self.logger.warning(f"Error cargando noticias RSS: {e}")
        
        return False
    
    def _guardar_noticias_rss(self):
        """Guarda noticias RSS en JSON (fallback)."""
        try:
            ruta_noticias = DATA_DIR / "noticias_rss.json"
            ruta_noticias.parent.mkdir(parents=True, exist_ok=True)
            
            temp_path = ruta_noticias.with_suffix('.tmp')
            noticias_para_guardar = []
            for n in self.noticias[:MAX_NOTICIAS_MEMORIA]:
                fecha = n.get('fecha')
                if isinstance(fecha, datetime):
                    fecha = fecha.isoformat()
                noticias_para_guardar.append({
                    **n,
                    'fecha': fecha
                })
            
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(noticias_para_guardar, f, indent=2, ensure_ascii=False)
            temp_path.replace(ruta_noticias)
        except Exception as e:
            self.logger.warning(f"Error guardando noticias RSS: {e}")
    
    def _limpiar_eventos_antiguos(self):
        """Limpia eventos más antiguos que DIAS_PARA_LIMPIAR."""
        ahora = datetime.now(timezone.utc)
        limite = ahora - timedelta(days=DIAS_PARA_LIMPIAR)
        
        with self._eventos_lock:
            self.eventos = [e for e in self.eventos if e.hora > limite]
            if len(self.eventos) > MAX_EVENTOS_MEMORIA:
                self.eventos.sort(key=lambda e: e.hora, reverse=True)
                self.eventos = self.eventos[:MAX_EVENTOS_MEMORIA]
    
    # ============================================================
    # MÉTODOS DE SENTIMIENTO Y DIVISAS
    # ============================================================
    
    def _predecir_sentimiento_evento(self, nombre: str, divisa: str) -> float:
        """Predice el sentimiento esperado de un evento."""
        nombre_lower = nombre.lower()
        
        positivos = ['hawkish', 'subida de tipos', 'rate hike', 'aumento de tasas',
                     'empleo fuerte', 'strong employment', 'jobs growth', 'nfp beat',
                     'pib crece', 'gdp growth', 'economía fuerte',
                     'ventas minoristas suben', 'retail sales beat',
                     'pmis expansion', 'manufacturing growth',
                     'deficit baja', 'deficit narrows', 'superavit', 'surplus']
        
        negativos = ['dovish', 'bajada de tipos', 'rate cut', 'reduccion de tasas',
                     'empleo debil', 'weak employment', 'jobs miss', 'nfp miss',
                     'pib contrae', 'gdp contraction', 'recesion',
                     'ventas minoristas caen', 'retail sales miss',
                     'pmis contraccion', 'manufacturing decline',
                     'deficit sube', 'deficit widens', 'inflacion alta']
        
        for p in positivos:
            if p in nombre_lower:
                return 0.7
        for n in negativos:
            if n in nombre_lower:
                return -0.7
        
        # Políticas monetarias
        if 'ecb' in nombre_lower or 'bce' in nombre_lower:
            return 0.3 if divisa == 'EUR' else 0.0
        if 'fed' in nombre_lower or 'fomc' in nombre_lower:
            return 0.3 if divisa == 'USD' else 0.0
        if 'boj' in nombre_lower:
            return 0.3 if divisa == 'JPY' else 0.0
        if 'boe' in nombre_lower:
            return 0.3 if divisa == 'GBP' else 0.0
        
        return 0.0
    
    def _analizar_sentimiento(self, texto: str) -> float:
        """Analiza el sentimiento de un texto."""
        texto_lower = texto.lower()
        sentimiento = 0.0
        contador = 0
        
        positivos = ['hawkish', 'subida', 'aumento', 'crecimiento', 'fuerte', 'beat',
                     'superavit', 'surplus', 'expansión', 'mejor de lo esperado']
        negativos = ['dovish', 'bajada', 'reduccion', 'caida', 'contraccion',
                     'deficit', 'inflacion', 'recesion', 'peor de lo esperado']
        
        for p in positivos:
            if p in texto_lower:
                sentimiento += 0.3
                contador += 1
        for n in negativos:
            if n in texto_lower:
                sentimiento -= 0.3
                contador += 1
        
        if contador > 0:
            return max(-1.0, min(1.0, sentimiento / max(1, contador // 2)))
        return 0.0
    
    def _calcular_impacto(self, texto: str) -> float:
        """Calcula el impacto de una noticia."""
        texto_lower = texto.lower()
        
        if any(p in texto_lower for p in self.palabras_clave.get('CRITICO', [])):
            return 0.8
        if any(p in texto_lower for p in self.palabras_clave.get('POLITICO', [])):
            return 0.6
        if any(p in texto_lower for p in self.palabras_clave.get('ALTO', [])):
            return 0.4
        if any(p in texto_lower for p in self.palabras_clave.get('MEDIO', [])):
            return 0.2
        return 0.0
    
    def _extraer_divisa(self, texto: str) -> str:
        """Extrae la divisa mencionada en un texto."""
        texto_lower = texto.lower()
        
        for divisa, keywords in self.keywords_divisas.items():
            for kw in keywords:
                if kw.lower() in texto_lower:
                    return divisa
        return 'ALL'
    
    def _normalizar_utc(self, obj):
        """Normaliza un objeto a datetime UTC."""
        if obj is None:
            return datetime.now(timezone.utc)
        if isinstance(obj, datetime):
            if obj.tzinfo is None:
                return obj.replace(tzinfo=timezone.utc)
            return obj.astimezone(timezone.utc)
        if isinstance(obj, str):
            try:
                dt = datetime.fromisoformat(obj)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                return None
        return None
    
    def _es_noticia_similar(self, titulo_nuevo: str, url_nueva: Optional[str] = None,
                            titulos_existentes: List[str] = None,
                            urls_existentes: List[str] = None,
                            umbral_similitud: float = 0.75) -> bool:
        """Verifica si una noticia ya existe por URL o similitud."""
        if url_nueva and urls_existentes:
            if url_nueva in urls_existentes:
                return True
        
        if titulos_existentes:
            for titulo_existente in titulos_existentes:
                similitud = difflib.SequenceMatcher(
                    None, titulo_nuevo.lower(), titulo_existente.lower()
                ).ratio()
                if similitud >= umbral_similitud:
                    return True
        return False
    
    def _obtener_eventos_relevantes(self, simbolo: str, horas: int = 4, 
                                     fecha_referencia: Optional[datetime] = None) -> List[EventoNoticia]:
        """Obtiene eventos relevantes para un símbolo."""
        ahora = fecha_referencia if fecha_referencia is not None else datetime.now(timezone.utc)
        limite = ahora + timedelta(hours=horas)
        
        if len(simbolo) == 6:
            divisas = [simbolo[:3], simbolo[3:]]
        else:
            divisas = [simbolo, 'USD']
        
        relevantes = []
        for evento in self.eventos:
            if evento.hora.tzinfo is None:
                evento.hora = evento.hora.replace(tzinfo=timezone.utc)
            if evento.hora < ahora - timedelta(hours=1):
                continue
            if evento.hora > limite:
                continue
            if evento.divisa in divisas or evento.divisa == 'ALL':
                relevantes.append(evento)
        
        relevantes.sort(key=lambda e: abs((e.hora - ahora).total_seconds()))
        return relevantes
    
    # ============================================================
    # COT (Commitment of Traders) CON DATACACHE
    # ============================================================
    
    def obtener_cot_fmp(self, divisa: str, fecha_referencia: Optional[datetime] = None) -> float:
        """
        Obtiene el COT para una divisa o activo.
        V9.1 - Usa DataCache si está disponible.
        
        Args:
            divisa: Código de divisa (EUR, USD, etc.)
            fecha_referencia: Fecha de referencia (para backtesting)
        
        Returns:
            Sentimiento COT (-1 a 1)
        """
        divisa = divisa.upper()
        ahora = fecha_referencia if fecha_referencia is not None else datetime.now(timezone.utc)
        
        # Obtener API key
        fmp_key = ''
        if self.config is not None:
            fmp_key = getattr(self.config, 'FMP_API_KEY', '')
        if not fmp_key:
            try:
                from config.settings import Config
                fmp_key = Config.FMP_API_KEY
            except Exception:
                pass
        
        mapping_fmp = {
            'EUR': 'EUR', 'GBP': 'GBP', 'JPY': 'JPY', 'AUD': 'AUD',
            'CAD': 'CAD', 'CHF': 'CHF', 'NZD': 'NZD', 'USD': 'USD',
            'XAU': 'GC', 'XAG': 'SI',
            'US30': 'YM', 'NAS100': 'NQ', 'US500': 'ES',
            'BTC': 'BTC', 'ETH': 'ETH', 'SOL': 'SOL'
        }
        
        map_cftc_nombres = {
            'EUR': 'EURO FX',
            'GBP': 'BRITISH POUND',
            'JPY': 'JAPANESE YEN',
            'AUD': 'AUSTRALIAN DOLLAR',
            'CAD': 'CANADIAN DOLLAR',
            'CHF': 'SWISS FRANC',
            'NZD': 'NZ DOLLAR',
            'USD': 'U.S. DOLLAR INDEX',
            'XAU': 'GOLD',
            'XAG': 'SILVER',
            'US30': 'DOW JONES',
            'NAS100': 'NASDAQ',
            'US500': 'S&P 500',
        }
        
        simbolo_cot = mapping_fmp.get(divisa)
        if not simbolo_cot:
            self.logger.debug(f"⚠️ No hay mapeo COT para {divisa}")
            return 0.0
        
        # 1. Intentar DataCache
        if self.data_cache is not None:
            try:
                cache_key = f"cot_{simbolo_cot}"
                cached = self.data_cache._cache.get((cache_key, 0, 0))
                if cached:
                    entry = cached
                    if not entry.is_expired(time.time()):
                        valor = entry.data.get('sentimiento', 0.0)
                        self.logger.debug(f"📊 COT {divisa}: Usando DataCache ({valor:.2f})")
                        return float(valor)
            except Exception:
                pass
        
        # 2. FMP API
        if fmp_key:
            try:
                url = f"https://financialmodelingprep.com/api/v4/commitment_of_traders_report_analysis/{simbolo_cot}"
                headers = {'User-Agent': 'Mozilla/5.0', 'apikey': fmp_key}
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    datos = response.json()
                    if datos and len(datos) > 0:
                        net_pos = float(datos[0].get('netNonCommercialPosition', 0.0))
                        sentimiento = 1.0 if net_pos > 0.0 else -1.0
                        
                        # Guardar en DataCache
                        if self.data_cache is not None:
                            try:
                                import pandas as pd
                                df = pd.DataFrame({'sentimiento': [sentimiento], 'net_pos': [net_pos]})
                                self.data_cache._set(
                                    (f"cot_{simbolo_cot}", 0, 0),
                                    df,
                                    time.time()
                                )
                            except Exception:
                                pass
                        
                        self.logger.info(f"📊 COT {divisa}: FMP → {sentimiento:.2f} (Net: {net_pos:.0f})")
                        return sentimiento
            except Exception as e:
                self.logger.warning(f"⚠️ FMP COT falló para {divisa}: {e}")
        
        # 3. CFTC Directo (solo para divisas tradicionales)
        if divisa in map_cftc_nombres:
            return self._obtener_cot_cftc_directo(divisa, ahora, map_cftc_nombres)
        
        return 0.0
    
    def _obtener_cot_cftc_directo(self, divisa: str, ahora: datetime, map_cftc_nombres: dict) -> float:
        """Obtiene COT directamente de CFTC."""
        import requests
        import re
        
        nombre_buscar = map_cftc_nombres.get(divisa)
        if not nombre_buscar:
            return 0.0
        
        # Circuit Breaker
        if self._cftc_failure_count >= 3:
            if self._cftc_last_failure_time:
                if (datetime.now(timezone.utc) - self._cftc_last_failure_time).total_seconds() < 3600:
                    self.logger.debug(f"⏳ Circuit Breaker COT activo para {divisa}")
                    return 0.0
                else:
                    self._cftc_failure_count = 0
                    self._cftc_last_failure_time = None
        
        try:
            url = "https://www.cftc.gov/dea/futures/financial_lf.htm"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            content = response.text
            
            patron = re.compile(
                rf"{re.escape(nombre_buscar)}.*?Positions\s+([\d,]+)\s+([\d,]+)",
                re.DOTALL | re.IGNORECASE
            )
            match = patron.search(content)
            
            if not match:
                self._cftc_failure_count += 1
                self._cftc_last_failure_time = datetime.now(timezone.utc)
                return 0.0
            
            long_str = match.group(1).replace(',', '')
            short_str = match.group(2).replace(',', '')
            longs = int(long_str)
            shorts = int(short_str)
            net_pos = longs - shorts
            sentimiento = 1.0 if net_pos > 0 else -1.0
            
            self.logger.info(
                f"📊 COT {divisa}: CFTC → {sentimiento:.2f} "
                f"(Long: {longs:,}, Short: {shorts:,}, Net: {net_pos:,})"
            )
            self._cftc_failure_count = 0
            self._cftc_last_failure_time = None
            return sentimiento
            
        except Exception as e:
            self.logger.error(f"❌ Error en CFTC para {divisa}: {e}")
            self._cftc_failure_count += 1
            self._cftc_last_failure_time = datetime.now(timezone.utc)
            return 0.0
    
    def forzar_actualizacion_cot(self):
        """Fuerza actualización de COT para todas las divisas."""
        divisas = ['EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD', 'USD']
        self.logger.info("🔄 Forzando actualización de COT...")
        
        # Limpiar caché de DataCache
        if self.data_cache is not None:
            self.data_cache.invalidate()
        
        self._cftc_failure_count = 0
        self._cftc_last_failure_time = None
        
        for d in divisas:
            cot = self.obtener_cot_fmp(d)
            self.logger.info(f"   📊 {d}: COT = {cot:.2f}")
        
        self.logger.info("✅ Actualización COT completada")
    
    # ============================================================
    # MÉTODOS DE ACTUALIZACIÓN
    # ============================================================
    
    def actualizar(self, forzar: bool = False) -> bool:
        """Actualiza fuentes de noticias."""
        self.logger.info("🔄 Actualizando fuentes de noticias...")
        
        nuevos_eventos = []
        
        # Iterar sobre todas las fuentes
        for fuente in self._fuentes:
            try:
                eventos = fuente.obtener_eventos()
                nuevos_eventos.extend(eventos)
            except Exception as e:
                self.logger.warning(f"⚠️ Error en fuente {fuente.nombre}: {e}")
                continue
        
        if nuevos_eventos:
            # Deduplicar eventos (por nombre, divisa y hora)
            vistos = set()
            eventos_unicos = []
            for ev in nuevos_eventos:
                clave = (ev.nombre, ev.divisa, ev.hora.strftime('%Y-%m-%d %H:%M'))
                if clave not in vistos:
                    vistos.add(clave)
                    eventos_unicos.append(ev)
            
            # Reemplazar eventos
            with self._eventos_lock:
                self.eventos = eventos_unicos
            
            self.logger.info(f"📰 {len(eventos_unicos)} eventos únicos cargados desde {len(self._fuentes)} fuentes")
            self._guardar_en_almacen()
            self._ultima_actualizacion_calendario = datetime.now(timezone.utc)
            return True
        
        self.logger.info("📭 No se cargaron eventos nuevos")
        return False
    
    # ============================================================
    # MÉTODOS PÚBLICOS
    # ============================================================
    
    def obtener_sentimiento_divisa(self, divisa: str, fecha_referencia: Optional[datetime] = None) -> float:
        """Obtiene sentimiento de una divisa."""
        ahora = fecha_referencia if fecha_referencia is not None else datetime.now(timezone.utc)
        
        if divisa in self._cache_sentimiento_divisa:
            sentimiento, timestamp = self._cache_sentimiento_divisa[divisa]
            if (ahora - timestamp).total_seconds() < self.cache_ttl_minutos * 60:
                return sentimiento
        
        eventos_divisa = [
            e for e in self.eventos 
            if e.divisa == divisa and e.ponderacion_actual(ahora) > 0
        ]
        
        if not eventos_divisa:
            return 0.0
        
        sentimiento_total = 0.0
        ponderacion_total = 0.0
        
        for evento in eventos_divisa:
            pond = evento.ponderacion_actual(ahora)
            sentimiento_total += evento.sentimiento_esperado * pond * evento.impacto.value
            ponderacion_total += pond * evento.impacto.value
        
        if ponderacion_total > 0:
            sentimiento = sentimiento_total / ponderacion_total
        else:
            sentimiento = 0.0
        
        self._cache_sentimiento_divisa[divisa] = (sentimiento, ahora)
        return sentimiento
    
    def obtener_sentimiento_simbolo(self, simbolo: str, fecha_referencia: Optional[datetime] = None) -> float:
        """Obtiene sentimiento de un símbolo."""
        if simbolo in ['BTCUSD', 'ETHUSD', 'SOLUSD']:
            base = simbolo.replace('USD', '')
            try:
                if self._crypto_client is not None:
                    result = self._crypto_client.get_sentiment(base)
                    return result.get('sentiment', 0.0)
                return 0.0
            except Exception as e:
                self.logger.warning(f"Error obteniendo sentimiento de {simbolo}: {e}")
                return 0.0
        
        if len(simbolo) == 6:
            base = simbolo[:3]
            quote = simbolo[3:]
            return self.obtener_sentimiento_divisa(base, fecha_referencia) - \
                   self.obtener_sentimiento_divisa(quote, fecha_referencia)
        
        return 0.0
    
    def obtener_eventos_dict(self) -> List[Dict[str, Any]]:
        """Obtiene eventos como diccionarios."""
        return [ev.to_dict() for ev in self.eventos]
    
    def obtener_proximos_eventos_importantes(self, n: int = 3) -> List[Dict[str, Any]]:
        """Obtiene los próximos eventos importantes."""
        ahora = datetime.now(timezone.utc)
        eventos_futuros = [e for e in self.eventos if e.hora > ahora]
        eventos_futuros.sort(key=lambda e: e.hora)
        return [e.to_dict() for e in eventos_futuros[:n]]
    
    def obtener_eventos_hoy(self) -> List[Dict[str, Any]]:
        """Obtiene eventos de hoy."""
        ahora = datetime.now(timezone.utc)
        hoy = ahora.date()
        eventos_hoy = [e for e in self.eventos if e.hora.date() == hoy]
        
        resultado = []
        for e in eventos_hoy:
            resultado.append({
                'nombre': e.nombre,
                'divisa': e.divisa,
                'impacto': e.impacto.name,
                'hora': e.hora.isoformat(),
                'ponderacion_actual': e.ponderacion_actual(ahora),
                'sentimiento': e.sentimiento_esperado,
                'divisa_favorable': 'BASE' if e.sentimiento_esperado > 0 else 'QUOTE',
            })
        return resultado
    
    def get_eventos_proximos(self, simbolo: str, horas: int = 4) -> List[Dict[str, Any]]:
        """Obtiene eventos próximos para un símbolo."""
        eventos = self._obtener_eventos_relevantes(simbolo, horas)
        return [e.to_dict() for e in eventos]
    
    def evaluar_riesgo(self) -> Dict[str, Any]:
        """Evalúa el riesgo general del mercado."""
        ahora = datetime.now(timezone.utc)
        criticas = 0
        
        for evento in self.eventos:
            if evento.impacto in [ImpactoNoticia.CRITICO, ImpactoNoticia.ALTO]:
                if evento.ponderacion_actual(ahora) > 0.5:
                    criticas += 1
        
        if criticas >= 3:
            return {'riesgo': 40, 'accion': 'NO_OPERAR', 'noticias_criticas': criticas}
        elif criticas >= 1:
            return {'riesgo': 20, 'accion': 'PRECAUCION', 'noticias_criticas': criticas}
        else:
            return {'riesgo': 0, 'accion': 'NORMAL', 'noticias_criticas': criticas}
    
    def verificar_bloqueo_calendario(self, ventana_antes: Optional[int] = None,
                                     ventana_despues: Optional[int] = None) -> List[Dict[str, Any]]:
        """Verifica bloqueos por calendario."""
        ahora = datetime.now(timezone.utc)
        bloqueos = []
        
        for evento in self.eventos:
            if evento.impacto in [ImpactoNoticia.CRITICO, ImpactoNoticia.ALTO]:
                ponderacion = evento.ponderacion_actual(ahora)
                if ponderacion > 0.5:
                    bloqueos.append({
                        'nombre': evento.nombre,
                        'divisa': evento.divisa,
                        'ponderacion': ponderacion
                    })
        return bloqueos
    
    def evaluar_riesgo_y_oportunidad(self, simbolo: str, direccion_sugerida: str) -> Dict[str, Any]:
        """Evalúa riesgo y oportunidad para un símbolo."""
        ahora = datetime.now(timezone.utc)
        
        if len(simbolo) == 6:
            base = simbolo[:3]
            quote = simbolo[3:]
        else:
            base = simbolo
            quote = 'USD'
        
        eventos_relevantes = self._obtener_eventos_relevantes(simbolo, horas=4)
        
        if not eventos_relevantes:
            return {
                'direccion_ajustada': direccion_sugerida,
                'factor_lote': 1.0,
                'confianza': 0.0,
                'ponderacion': 0.0,
                'divisa_favorable': None,
                'bloquear': False,
                'motivo': 'Sin noticias relevantes'
            }
        
        sentimiento_total = 0.0
        ponderacion_total = 0.0
        eventos_bloqueo = []
        eventos_favorables = []
        eventos_contra = []
        divisa_favorable = None
        
        for evento in eventos_relevantes:
            ponderacion = evento.ponderacion_actual(ahora)
            if ponderacion == 0.0:
                continue
            
            es_critico_bloqueo = any(c in evento.nombre for c in self.eventos_criticos_bloqueo)
            if es_critico_bloqueo and ponderacion > 0.5:
                eventos_bloqueo.append({
                    'nombre': evento.nombre,
                    'ponderacion': ponderacion,
                    'horas_restantes': (evento.hora - ahora).total_seconds() / 3600
                })
                continue
            
            divisa_evento = evento.divisa
            sentimiento = evento.sentimiento_esperado
            
            if divisa_evento == base:
                if sentimiento > 0:
                    direccion_favorable = 'COMPRA'
                    divisa_favorable = base
                else:
                    direccion_favorable = 'VENTA'
                    divisa_favorable = base
            elif divisa_evento == quote:
                if sentimiento > 0:
                    direccion_favorable = 'VENTA'
                    divisa_favorable = quote
                else:
                    direccion_favorable = 'COMPRA'
                    divisa_favorable = quote
            else:
                direccion_favorable = None
            
            contribucion = sentimiento * ponderacion * evento.impacto.value
            
            if direccion_favorable == 'COMPRA':
                sentimiento_total += contribucion
            elif direccion_favorable == 'VENTA':
                sentimiento_total -= contribucion
            
            ponderacion_total += ponderacion * evento.impacto.value
            
            if sentimiento > 0 and direccion_sugerida == 'COMPRA':
                eventos_favorables.append(evento.nombre)
            elif sentimiento < 0 and direccion_sugerida == 'VENTA':
                eventos_favorables.append(evento.nombre)
            else:
                eventos_contra.append(evento.nombre)
        
        if eventos_bloqueo and self.modo == 'BLOQUEAR':
            return {
                'direccion_ajustada': 'NEUTRAL',
                'factor_lote': 0.0,
                'confianza': 0.0,
                'ponderacion': 0.0,
                'divisa_favorable': divisa_favorable,
                'bloquear': True,
                'motivo': f"Evento crítico: {eventos_bloqueo[0]['nombre']}",
                'eventos_bloqueo': eventos_bloqueo
            }
        
        if ponderacion_total > 0:
            sentimiento_neto = sentimiento_total / ponderacion_total
        else:
            sentimiento_neto = 0.0
        
        direccion_ajustada = direccion_sugerida
        
        if sentimiento_neto > self.sent_fuerte and direccion_sugerida == 'VENTA':
            direccion_ajustada = 'NEUTRAL'
        elif sentimiento_neto < self.sent_negativo and direccion_sugerida == 'COMPRA':
            direccion_ajustada = 'NEUTRAL'
        
        factor_lote = 1.0
        if eventos_favorables and direccion_ajustada == direccion_sugerida:
            factor_lote = self.lote_bonus
        elif eventos_contra and direccion_ajustada != direccion_sugerida:
            factor_lote = self.lote_penalty
        
        confianza = min(1.0, abs(sentimiento_neto) * 1.5) * min(1.0, ponderacion_total / 2.0)
        
        return {
            'direccion_ajustada': direccion_ajustada,
            'factor_lote': factor_lote,
            'confianza': confianza,
            'ponderacion': ponderacion_total,
            'divisa_favorable': divisa_favorable,
            'bloquear': False,
            'sentimiento_neto': sentimiento_neto,
            'eventos_favorables': eventos_favorables,
            'eventos_contra': eventos_contra,
            'eventos_activos': len(eventos_relevantes),
            'motivo': f"Sentimiento: {sentimiento_neto:.2f}, Ponderación: {ponderacion_total:.2f}",
        }
    
    def obtener_puntuacion_noticias(self, simbolo: str, direccion: str) -> float:
        """Obtiene puntuación de noticias para un símbolo."""
        analisis = self.evaluar_riesgo_y_oportunidad(simbolo, direccion)
        
        if analisis['bloquear']:
            return 0.0
        
        score = analisis['sentimiento_neto'] * 50.0
        score += analisis['ponderacion'] * 10.0
        score -= len(analisis['eventos_contra']) * 5.0
        
        if direccion == 'COMPRA' and analisis['divisa_favorable'] == simbolo[:3]:
            score += 15.0
        elif direccion == 'VENTA' and analisis['divisa_favorable'] == simbolo[3:]:
            score += 15.0
        
        return max(-100.0, min(100.0, score))
    
    def obtener_factor_calendario_inteligente(self, simbolo: str) -> float:
        """Obtiene factor de calendario inteligente."""
        ahora = datetime.now(timezone.utc)
        
        if len(simbolo) == 6:
            divisas = [simbolo[:3], simbolo[3:]]
        else:
            divisas = [simbolo, 'USD']
        
        factor = 1.0
        
        for evento in self.eventos:
            if evento.divisa not in divisas and evento.divisa != 'ALL':
                continue
            
            diff_horas = (evento.hora - ahora).total_seconds() / 3600
            
            if evento.impacto == ImpactoNoticia.CRITICO and 0 < diff_horas <= 1:
                factor = min(factor, 0.7)
            elif evento.impacto == ImpactoNoticia.ALTO and 0 < diff_horas <= 0.5:
                factor = min(factor, 0.85)
            elif evento.impacto == ImpactoNoticia.CRITICO and -1 < diff_horas <= 0:
                factor = min(factor, 0.8)
        
        return factor
    
    def obtener_divisa_favorable(self, simbolo: str) -> Optional[str]:
        """Obtiene divisa favorable para un símbolo."""
        analisis = self.evaluar_riesgo_y_oportunidad(simbolo, 'NEUTRAL')
        return analisis.get('divisa_favorable')
    
    def obtener_trm_colombia_oficial(self) -> Optional[float]:
        """Obtiene TRM de Colombia oficial."""
        try:
            url = "https://www.datos.gov.co/resource/m96n-972d.json?$limit=1&$order=vigenciahasta%20DESC"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                datos = response.json()
                if datos and len(datos) > 0:
                    return float(datos[0].get('valor', 0.0))
            return None
        except Exception as e:
            self.logger.error(f"Error al obtener TRM: {e}")
            return None
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del sistema de noticias."""
        ahora = datetime.now(timezone.utc)
        
        eventos_futuros = len([e for e in self.eventos if e.hora > ahora])
        eventos_hoy = len([e for e in self.eventos if e.hora.date() == ahora.date()])
        
        return {
            'total_eventos': len(self.eventos),
            'eventos_futuros': eventos_futuros,
            'eventos_hoy': eventos_hoy,
            'total_noticias': len(self.noticias),
            'ultima_actualizacion': self._ultima_actualizacion_calendario.isoformat() if self._ultima_actualizacion_calendario else None,
            'cftc_failures': self._cftc_failure_count,
            'cache_sentimiento_size': len(self._cache_sentimiento_divisa),
            'fuentes_activas': len(self._fuentes),
        }