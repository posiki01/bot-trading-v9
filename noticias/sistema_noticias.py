#!/usr/bin/env python3
"""
noticias/sistema_noticias.py (V8.0 - REFACTORIZADO)
Sistema de Noticias con Ponderación Temporal y Aprovechamiento de Divisas.

MEJORAS V8.0:
- Integración con LoggerPersistente (logs unificados)
- Integración con AlmacenamientoSQLite (persistencia en DB)
- Integración con DataCache (caché de COT unificada)
- Configuración centralizada desde Config
- Límite de eventos en memoria (máximo 200)
- Limpieza automática de eventos antiguos (>7 días)
- Estadísticas de uso
- Paths usando BASE_DIR
- Soporte para fecha_referencia en todos los métodos (para backtesting)
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
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import threading

# ============================================================
# IMPORTS DE NUEVOS MÓDULOS (V8.0)
# ============================================================

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
    from utils.cache_data import DataCache
except ImportError:
    DataCache = None

try:
    from data.almacenamiento_sqlite import AlmacenamientoSQLite
except ImportError:
    AlmacenamientoSQLite = None

# ============================================================
# IMPORTS LEGACY (Compatibilidad)
# ============================================================

try:
    from utils.retry import retry_http
except ImportError:
    def retry_http(max_retries=3, base_delay=1.0):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                for attempt in range(1, max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        if attempt == max_retries:
                            raise
                        time.sleep(base_delay * attempt)
            return wrapper
        return decorator

try:
    from utils.crypto_client import FreeCryptoAPIClient
except ImportError:
    FreeCryptoAPIClient = None

try:
    from config.news_keywords import PALABRAS_CLAVE_IMPACTO, KEYWORDS_DIVISAS_NLP
except ImportError:
    PALABRAS_CLAVE_IMPACTO = {}
    KEYWORDS_DIVISAS_NLP = {}

# ============================================================
# CONSTANTES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MAX_EVENTOS_MEMORIA = 200
MAX_NOTICIAS_MEMORIA = 50
DIAS_PARA_LIMPIAR = 7
COT_CACHE_TTL_HORAS = 48


class ImpactoNoticia(Enum):
    CRITICO = 4
    ALTO = 3
    MEDIO = 2
    BAJO = 1
    IRRELEVANTE = 0


# ============================================================
# DATACLASS DE EVENTO
# ============================================================

@dataclass
class EventoNoticia:
    nombre: str
    divisa: str
    impacto: ImpactoNoticia
    hora: datetime
    sentimiento_esperado: float = 0.0
    fuente: str = ""
    descripcion: str = ""
    pais: str = ""
    actual: Optional[float] = None
    previo: Optional[float] = None
    consenso: Optional[float] = None
    
    hora_inicio_ventana: Optional[datetime] = None
    hora_fin_ventana: Optional[datetime] = None
    hora_pico: Optional[datetime] = None
    
    def __post_init__(self):
        if self.hora_inicio_ventana is None:
            self.hora_inicio_ventana = self.hora - timedelta(hours=2)
        if self.hora_fin_ventana is None:
            self.hora_fin_ventana = self.hora + timedelta(hours=2)
        if self.hora_pico is None:
            self.hora_pico = self.hora
    
    def ponderacion_actual(self, momento: datetime) -> float:
        """Calcula la ponderación actual del evento."""
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)
        if self.hora.tzinfo is None:
            self.hora = self.hora.replace(tzinfo=timezone.utc)
        if self.hora_inicio_ventana.tzinfo is None:
            self.hora_inicio_ventana = self.hora_inicio_ventana.replace(tzinfo=timezone.utc)
        if self.hora_fin_ventana.tzinfo is None:
            self.hora_fin_ventana = self.hora_fin_ventana.replace(tzinfo=timezone.utc)
        
        if momento < self.hora_inicio_ventana or momento > self.hora_fin_ventana:
            return 0.0
        
        if momento < self.hora:
            horas_antes = (self.hora - momento).total_seconds() / 3600.0
            ponderacion = 1.0 - (horas_antes / 2.0) ** 1.5
        else:
            horas_despues = (momento - self.hora).total_seconds() / 3600.0
            ponderacion = max(0.0, 1.0 - (horas_despues / 2.0) ** 1.2)
        
        return max(0.0, min(1.0, ponderacion))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'nombre': self.nombre,
            'divisa': self.divisa,
            'impacto': self.impacto.value,
            'hora': self.hora.isoformat(),
            'sentimiento_esperado': self.sentimiento_esperado,
            'fuente': self.fuente,
            'descripcion': self.descripcion,
            'pais': self.pais,
            'actual': self.actual,
            'previo': self.previo,
            'consenso': self.consenso,
            'hora_inicio_ventana': self.hora_inicio_ventana.isoformat() if self.hora_inicio_ventana else None,
            'hora_fin_ventana': self.hora_fin_ventana.isoformat() if self.hora_fin_ventana else None,
            'hora_pico': self.hora_pico.isoformat() if self.hora_pico else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EventoNoticia':
        return cls(
            nombre=data.get('nombre', ''),
            divisa=data.get('divisa', 'ALL'),
            impacto=ImpactoNoticia(data.get('impacto', 0)),
            hora=datetime.fromisoformat(data['hora']),
            sentimiento_esperado=data.get('sentimiento_esperado', 0.0),
            fuente=data.get('fuente', ''),
            descripcion=data.get('descripcion', ''),
            pais=data.get('pais', ''),
            actual=data.get('actual'),
            previo=data.get('previo'),
            consenso=data.get('consenso'),
            hora_inicio_ventana=datetime.fromisoformat(data['hora_inicio_ventana']) if data.get('hora_inicio_ventana') else None,
            hora_fin_ventana=datetime.fromisoformat(data['hora_fin_ventana']) if data.get('hora_fin_ventana') else None,
            hora_pico=datetime.fromisoformat(data['hora_pico']) if data.get('hora_pico') else None,
        )


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class SistemaNoticias:
    """
    Sistema completo de noticias con ponderación temporal y deduplicación.
    V8.0: Integración con nuevos módulos.
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
        
        # Fuentes RSS
        self.fuentes = [
            'https://feeds.reuters.com/reuters/businessNews',
            'https://www.cnbc.com/id/100727362/device/rss/rss.html',
            'https://www.marketwatch.com/rss/topstories',
            'https://finance.yahoo.com/news/rssindex'
        ]
        
        # Cargar datos desde almacenamiento
        self._cargar_desde_almacen()
        
        self.logger.info(f"📰 SistemaNoticias V8.0 inicializado")
        self.logger.info(f"   Eventos: {len(self.eventos)}")
        self.logger.info(f"   Noticias: {len(self.noticias)}")
    
    # ============================================================
    # CONFIGURACIÓN
    # ============================================================
    
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
                    
                    # Convertir a datetime
                    if isinstance(fecha_str, str):
                        fecha = datetime.fromisoformat(fecha_str)
                        if fecha.tzinfo is None:
                            fecha = fecha.replace(tzinfo=timezone.utc)
                    elif isinstance(fecha_str, datetime):
                        fecha = fecha_str
                    else:
                        fecha = datetime.now(timezone.utc)
                    
                    noticia = {
                        'fecha': fecha,  # <-- Siempre datetime
                        'titulo': item.get('titulo', ''),
                        'sentimiento': item.get('sentimiento', 0.0),
                        'impacto': item.get('impacto', 0.0),
                        'divisa': item.get('divisa', 'ALL'),
                        'texto': item.get('texto', ''),
                        'fuente': item.get('fuente', ''),
                        'url': item.get('url', '')
                    }
                    noticias_cargadas.append(noticia)
                except Exception as e:
                    self.logger.debug(f"Error procesando noticia: {e}")
                    continue
            
            if noticias_cargadas:
                self.noticias = noticias_cargadas[-MAX_NOTICIAS_MEMORIA:]
                self.logger.info(f"📰 {len(self.noticias)} noticias RSS cargadas desde JSON")
                return True
        except Exception as e:
            self.logger.warning(f"Error cargando noticias RSS: {e}")
    
        return False
    
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
        V8.0: Usa DataCache si está disponible.
        
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
    # MÉTODOS PÚBLICOS
    # ============================================================
    
    def actualizar(self, forzar: bool = False) -> bool:
        """Actualiza fuentes de noticias."""
        self.logger.info("🔄 Actualizando fuentes de noticias...")
        
        exito_calendario = self._actualizar_calendario(forzar)
        self._actualizar_noticias()
        
        if exito_calendario or self.eventos:
            self._guardar_en_almacen()
            self._ultima_actualizacion_calendario = datetime.now(timezone.utc)
        
        return exito_calendario
    
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
    # MÉTODOS DE ACTUALIZACIÓN DE CALENDARIO
    # ============================================================
    
    def _actualizar_calendario(self, forzar: bool = False) -> bool:
        """Actualiza el calendario de eventos."""
        if not forzar and self.eventos and self._ultima_actualizacion_calendario:
            if (datetime.now(timezone.utc) - self._ultima_actualizacion_calendario).total_seconds() < 3600:
                return True
        
        # Obtener API keys
        fmp_key = ''
        finnhub_key = ''
        
        if self.config is not None:
            fmp_key = getattr(self.config, 'FMP_API_KEY', '')
            finnhub_key = getattr(self.config, 'FINNHUB_API_KEY', '')
        
        if not fmp_key or not finnhub_key:
            try:
                from config.settings import Config
                if not fmp_key:
                    fmp_key = Config.FMP_API_KEY
                if not finnhub_key:
                    finnhub_key = Config.FINNHUB_API_KEY
            except Exception:
                pass
        
        if fmp_key and self._actualizar_calendario_fmp(fmp_key):
            self._ultima_actualizacion_calendario = datetime.now(timezone.utc)
            return True
        
        if finnhub_key and self._actualizar_calendario_finnhub(finnhub_key):
            self._ultima_actualizacion_calendario = datetime.now(timezone.utc)
            return True
        
        if self._actualizar_calendario_dailyfx():
            self._ultima_actualizacion_calendario = datetime.now(timezone.utc)
            return True
        
        if self._actualizar_calendario_forexfactory():
            self._ultima_actualizacion_calendario = datetime.now(timezone.utc)
            return True
        
        return False
    
    @retry_http(max_retries=3, base_delay=1.5)
    def _actualizar_calendario_fmp(self, api_key: str) -> bool:
        """Actualiza calendario desde FMP."""
        try:
            fecha_inicio = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            fecha_fin = (datetime.now(timezone.utc) + timedelta(days=7)).strftime('%Y-%m-%d')
            url = f"https://financialmodelingprep.com/stable/economic-calendar?from={fecha_inicio}&to={fecha_fin}"
            headers = {'apikey': api_key}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                datos = response.json()
                eventos_procesados = []
                
                for item in datos:
                    try:
                        fecha_str = item.get('date', '')
                        if not fecha_str:
                            continue
                        
                        try:
                            hora = datetime.strptime(fecha_str, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            hora = datetime.fromisoformat(fecha_str)
                        hora = hora.replace(tzinfo=timezone.utc)
                        
                        nombre = item.get('event', 'Evento Económico')
                        divisa = item.get('currency', 'ALL').upper()
                        impacto_str = item.get('impact', 'Low')
                        
                        impacto = ImpactoNoticia.MEDIO
                        if impacto_str == 'High':
                            impacto = ImpactoNoticia.ALTO
                        elif impacto_str == 'Low':
                            impacto = ImpactoNoticia.BAJO
                        
                        sentimiento = self._predecir_sentimiento_evento(nombre, divisa)
                        
                        evento = EventoNoticia(
                            nombre=nombre, divisa=divisa, impacto=impacto, hora=hora,
                            sentimiento_esperado=sentimiento, fuente='FMP',
                            descripcion=item.get('description', ''),
                            pais=item.get('country', ''),
                            actual=item.get('actual'), previo=item.get('previous'),
                            consenso=item.get('consensus'),
                        )
                        eventos_procesados.append(evento)
                    except Exception:
                        continue
                
                if eventos_procesados:
                    vistos = set()
                    eventos_unicos = []
                    for ev in eventos_procesados:
                        clave = (ev.nombre, ev.divisa, ev.hora.strftime('%Y-%m-%d %H:%M'))
                        if clave not in vistos:
                            vistos.add(clave)
                            eventos_unicos.append(ev)
                    
                    with self._eventos_lock:
                        self.eventos = eventos_unicos
                    
                    self.logger.info(f"📰 FMP: {len(eventos_unicos)} eventos únicos cargados")
                    self._guardar_en_almacen()
                    return True
        except Exception as e:
            self.logger.warning(f"FMP calendario: {e}")
        
        return False
    
    @retry_http(max_retries=3, base_delay=1.5)
    def _actualizar_calendario_finnhub(self, api_key: str) -> bool:
        """Actualiza calendario desde Finnhub."""
        try:
            url = f"https://finnhub.io/api/v1/calendar/economic?token={api_key}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                datos = response.json().get('economicCalendar', [])
                eventos_procesados = []
                
                for item in datos:
                    try:
                        fecha_str = item.get('time', '')
                        if not fecha_str:
                            continue
                        
                        hora = datetime.strptime(fecha_str, '%Y-%m-%d %H:%M:%S')
                        hora = hora.replace(tzinfo=timezone.utc)
                        
                        nombre = item.get('event', 'Evento Económico')
                        divisa = item.get('country', 'ALL').upper()
                        impacto_str = item.get('impact', 'low')
                        
                        impacto = ImpactoNoticia.MEDIO
                        if impacto_str == 'high':
                            impacto = ImpactoNoticia.ALTO
                        elif impacto_str == 'low':
                            impacto = ImpactoNoticia.BAJO
                        
                        sentimiento = self._predecir_sentimiento_evento(nombre, divisa)
                        
                        evento = EventoNoticia(
                            nombre=nombre, divisa=divisa, impacto=impacto, hora=hora,
                            sentimiento_esperado=sentimiento, fuente='Finnhub',
                        )
                        eventos_procesados.append(evento)
                    except Exception:
                        continue
                
                if eventos_procesados:
                    vistos = set()
                    eventos_unicos = []
                    for ev in eventos_procesados:
                        clave = (ev.nombre, ev.divisa, ev.hora.strftime('%Y-%m-%d %H:%M'))
                        if clave not in vistos:
                            vistos.add(clave)
                            eventos_unicos.append(ev)
                    
                    with self._eventos_lock:
                        self.eventos = eventos_unicos
                    
                    self.logger.info(f"📰 Finnhub: {len(eventos_unicos)} eventos únicos cargados")
                    self._guardar_en_almacen()
                    return True
        except Exception as e:
            self.logger.warning(f"Finnhub calendario: {e}")
        
        return False
    
    @retry_http(max_retries=3, base_delay=1.5)
    def _actualizar_calendario_dailyfx(self) -> bool:
        """Actualiza calendario desde DailyFX."""
        try:
            hoy = datetime.now(timezone.utc)
            start_date = hoy.strftime('%Y-%m-%dT00:00:00Z')
            end_date = (hoy + timedelta(days=7)).strftime('%Y-%m-%dT23:59:59Z')
            url = f"https://www.dailyfx.com/api/v1/calendar?start_date={start_date}&end_date={end_date}"
            headers = {
                'Referer': 'https://www.dailyfx.com/economic-calendar',
                'Accept': 'application/json, text/plain, */*',
            }
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                datos = response.json()
                eventos_procesados = []
                
                for item in datos:
                    try:
                        fecha_str = item.get('date', '').replace('Z', '+00:00')
                        hora = datetime.fromisoformat(fecha_str)
                        if hora.tzinfo is None:
                            hora = hora.replace(tzinfo=timezone.utc)
                        
                        nombre = item.get('title', 'Evento Económico')
                        divisa = item.get('currency', 'ALL').upper()
                        imp = item.get('importance', 'low').lower()
                        
                        impacto = ImpactoNoticia.MEDIO
                        if imp == 'high':
                            impacto = ImpactoNoticia.ALTO
                        elif imp == 'medium':
                            impacto = ImpactoNoticia.MEDIO
                        else:
                            impacto = ImpactoNoticia.BAJO
                        
                        sentimiento = self._predecir_sentimiento_evento(nombre, divisa)
                        
                        evento = EventoNoticia(
                            nombre=nombre, divisa=divisa, impacto=impacto, hora=hora,
                            sentimiento_esperado=sentimiento, fuente='DailyFX',
                        )
                        eventos_procesados.append(evento)
                    except Exception:
                        continue
                
                if eventos_procesados:
                    vistos = set()
                    eventos_unicos = []
                    for ev in eventos_procesados:
                        clave = (ev.nombre, ev.divisa, ev.hora.strftime('%Y-%m-%d %H:%M'))
                        if clave not in vistos:
                            vistos.add(clave)
                            eventos_unicos.append(ev)
                    
                    with self._eventos_lock:
                        self.eventos = eventos_unicos
                    
                    self.logger.info(f"📰 DailyFX: {len(eventos_unicos)} eventos únicos cargados")
                    self._guardar_en_almacen()
                    return True
        except Exception as e:
            self.logger.warning(f"DailyFX calendario: {e}")
        
        return False
    
    @retry_http(max_retries=3, base_delay=1.5)
    def _actualizar_calendario_forexfactory(self) -> bool:
        """Actualiza calendario desde ForexFactory."""
        try:
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                datos = response.json()
                eventos_procesados = []
                
                for item in datos:
                    try:
                        fecha_str = item.get('date', '')
                        if not fecha_str:
                            continue
                        
                        hora = datetime.fromisoformat(fecha_str)
                        if hora.tzinfo is None:
                            hora = hora.replace(tzinfo=timezone.utc)
                        
                        nombre = item.get('title', 'Evento Económico')
                        divisa = item.get('country', 'ALL').upper()
                        imp = item.get('impact', '').lower()
                        
                        if imp not in ['high', 'medium']:
                            continue
                        
                        impacto = ImpactoNoticia.ALTO if imp == 'high' else ImpactoNoticia.MEDIO
                        sentimiento = self._predecir_sentimiento_evento(nombre, divisa)
                        
                        evento = EventoNoticia(
                            nombre=nombre, divisa=divisa, impacto=impacto, hora=hora,
                            sentimiento_esperado=sentimiento, fuente='ForexFactory',
                        )
                        eventos_procesados.append(evento)
                    except Exception:
                        continue
                
                if eventos_procesados:
                    vistos = set()
                    eventos_unicos = []
                    for ev in eventos_procesados:
                        clave = (ev.nombre, ev.divisa, ev.hora.strftime('%Y-%m-%d %H:%M'))
                        if clave not in vistos:
                            vistos.add(clave)
                            eventos_unicos.append(ev)
                    
                    with self._eventos_lock:
                        self.eventos = eventos_unicos
                    
                    self.logger.info(f"📰 ForexFactory: {len(eventos_unicos)} eventos únicos cargados")
                    self._guardar_en_almacen()
                    return True
        except Exception as e:
            self.logger.warning(f"ForexFactory calendario: {e}")
        
        return False
    
    # ============================================================
    # MÉTODOS DE NOTICIAS RSS
    # ============================================================
    
    def _actualizar_noticias(self):
        """Actualiza noticias generales desde RSS con deduplicación."""
        nuevas_noticias = []
        titulos_existentes = [n.get('titulo', '') for n in self.noticias if n.get('titulo')]
        urls_existentes = [n.get('url', '') for n in self.noticias if n.get('url')]
        max_nuevas = 20
        
        for fuente in self.fuentes:
            if len(nuevas_noticias) >= max_nuevas:
                break
            
            try:
                feed = feedparser.parse(fuente)
                for entry in feed.entries[:5]:
                    if len(nuevas_noticias) >= max_nuevas:
                        break
                    
                    titulo = entry.title
                    url = entry.get('link', '')
                    
                    if self._es_noticia_similar(titulo, url, titulos_existentes, urls_existentes):
                        continue
                    
                    texto = f"{titulo} {getattr(entry, 'description', '')}"
                    sentimiento = self._analizar_sentimiento(texto)
                    impacto = self._calcular_impacto(texto)
                    divisa = self._extraer_divisa(texto)
                    
                    noticia = {
                        'fecha': datetime.now(timezone.utc),
                        'titulo': titulo,
                        'sentimiento': sentimiento,
                        'impacto': impacto,
                        'divisa': divisa,
                        'texto': texto[:500],
                        'fuente': fuente,
                        'url': url
                    }
                    nuevas_noticias.append(noticia)
                    titulos_existentes.append(titulo)
                    if url:
                        urls_existentes.append(url)
            except Exception as e:
                self.logger.debug(f"Error en fuente {fuente}: {e}")
                continue
        
        if nuevas_noticias:
            # Combinar y ordenar de forma segura
            todas_noticias = self.noticias + nuevas_noticias
            
            def get_fecha_segura(noticia):
                fecha = noticia.get('fecha')
                if isinstance(fecha, str):
                    try:
                        return datetime.fromisoformat(fecha)
                    except Exception:
                        return datetime(2000, 1, 1, tzinfo=timezone.utc)
                elif isinstance(fecha, datetime):
                    return fecha
                return datetime(2000, 1, 1, tzinfo=timezone.utc)
            
            todas_noticias.sort(key=get_fecha_segura, reverse=True)
            self.noticias = todas_noticias[:MAX_NOTICIAS_MEMORIA]
            self.logger.info(f"📰 {len(nuevas_noticias)} noticias nuevas añadidas (total {len(self.noticias)})")
            self._guardar_en_almacen()
        else:
            self.logger.info("📭 No se añadieron noticias nuevas")
    # ============================================================
    # MÉTODOS DE COMPATIBILIDAD (LEGACY)
    # ============================================================
    
    def actualizar_calendario_fmp(self, api_key: str) -> bool:
        return self._actualizar_calendario_fmp(api_key)
    
    def actualizar_calendario_finnhub(self, api_key: str) -> bool:
        return self._actualizar_calendario_finnhub(api_key)
    
    def actualizar_calendario_dailyfx(self) -> bool:
        return self._actualizar_calendario_dailyfx()
    
    def actualizar_calendario_forexfactory(self) -> bool:
        return self._actualizar_calendario_forexfactory()
    
    def actualizar_calendario_investing_rss(self) -> bool:
        return self._actualizar_calendario_investing_rss()
    
    @retry_http(max_retries=3, base_delay=1.5)
    def _actualizar_calendario_investing_rss(self) -> bool:
        """Actualiza calendario desde Investing RSS."""
        try:
            url = "https://www.investing.com/rss/news.rss"
            feed = feedparser.parse(url)
            
            if not feed.entries:
                return False
            
            eventos_procesados = []
            for entry in feed.entries[:10]:
                try:
                    titulo = entry.title
                    desc = getattr(entry, 'description', '')
                    texto = f"{titulo} {desc}"
                    divisa = self._extraer_divisa(texto)
                    
                    if divisa == 'ALL':
                        continue
                    
                    sentimiento = self._analizar_sentimiento(texto)
                    if abs(sentimiento) < 0.1:
                        continue
                    
                    pub_date = entry.get('published', '')
                    if not pub_date:
                        continue
                    
                    try:
                        hora = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z')
                        if hora.tzinfo is None:
                            hora = hora.replace(tzinfo=timezone.utc)
                    except:
                        continue
                    
                    impacto = ImpactoNoticia.MEDIO if abs(sentimiento) > 0.5 else ImpactoNoticia.BAJO
                    evento = EventoNoticia(
                        nombre=titulo[:80], divisa=divisa, impacto=impacto, hora=hora,
                        sentimiento_esperado=sentimiento, fuente='Investing_RSS',
                        descripcion=desc[:200],
                    )
                    eventos_procesados.append(evento)
                except Exception:
                    continue
            
            if eventos_procesados:
                vistos = set()
                eventos_unicos = []
                for ev in eventos_procesados:
                    clave = (ev.nombre, ev.divisa, ev.hora.strftime('%Y-%m-%d %H:%M'))
                    if clave not in vistos:
                        vistos.add(clave)
                        eventos_unicos.append(ev)
                
                with self._eventos_lock:
                    self.eventos.extend(eventos_unicos)
                    # Deduplicar globalmente
                    vistos_global = set()
                    eventos_global = []
                    for ev in self.eventos:
                        clave = (ev.nombre, ev.divisa, ev.hora.strftime('%Y-%m-%d %H:%M'))
                        if clave not in vistos_global:
                            vistos_global.add(clave)
                            eventos_global.append(ev)
                    self.eventos = eventos_global
                
                self._guardar_en_almacen()
                self.logger.info(f"📰 Investing RSS: {len(eventos_unicos)} eventos añadidos")
                return True
        except Exception as e:
            self.logger.warning(f"Investing RSS calendario: {e}")
        
        return False
    
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
        }