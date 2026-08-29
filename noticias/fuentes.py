#!/usr/bin/env python3
"""
noticias/fuentes.py (V9.1 - REFACTORIZADO)
Sistema de fuentes de noticias con arquitectura basada en clases.

MEJORAS V9.1:
- Clase base abstracta para todas las fuentes
- Cada fuente implementa solo la lógica de obtención de datos
- Fácil de extender con nuevas fuentes
"""

import logging
import requests
import feedparser
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from noticias.eventos import EventoNoticia, ImpactoNoticia

logger = logging.getLogger('BotTrading.NoticiasFuentes')


# ============================================================
# CLASE BASE ABSTRACTA
# ============================================================

class FuenteNoticias(ABC):
    """
    Clase base para todas las fuentes de noticias.
    V9.1 - NUEVO.
    """
    
    def __init__(self, nombre: str, prioridad: int = 1):
        """
        Inicializa la fuente.
        
        Args:
            nombre: Nombre de la fuente
            prioridad: Prioridad (1 = más alta)
        """
        self.nombre = nombre
        self.prioridad = prioridad
        self.logger = logging.getLogger(f'BotTrading.Fuente.{nombre}')
    
    @abstractmethod
    def obtener_eventos(self) -> List[EventoNoticia]:
        """
        Obtiene los eventos de esta fuente.
        
        Returns:
            Lista de EventoNoticia
        """
        pass
    
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


# ============================================================
# FUENTE: FINANCIAL MODELING PREP (FMP)
# ============================================================

class FuenteFMP(FuenteNoticias):
    """Fuente de noticias desde Financial Modeling Prep."""
    
    def __init__(self, api_key: str, prioridad: int = 1):
        super().__init__("FMP", prioridad)
        self.api_key = api_key
    
    def obtener_eventos(self) -> List[EventoNoticia]:
        if not self.api_key:
            self.logger.warning("⚠️ FMP API key no configurada")
            return []
        
        try:
            fecha_inicio = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            fecha_fin = (datetime.now(timezone.utc) + timedelta(days=7)).strftime('%Y-%m-%d')
            url = f"https://financialmodelingprep.com/stable/economic-calendar?from={fecha_inicio}&to={fecha_fin}"
            headers = {'apikey': self.api_key}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                self.logger.warning(f"⚠️ FMP error: {response.status_code}")
                return []
            
            datos = response.json()
            eventos = []
            
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
                        nombre=nombre,
                        divisa=divisa,
                        impacto=impacto,
                        hora=hora,
                        sentimiento_esperado=sentimiento,
                        fuente='FMP',
                        descripcion=item.get('description', ''),
                        pais=item.get('country', ''),
                        actual=item.get('actual'),
                        previo=item.get('previous'),
                        consenso=item.get('consensus'),
                    )
                    eventos.append(evento)
                except Exception as e:
                    self.logger.debug(f"Error procesando evento FMP: {e}")
                    continue
            
            self.logger.info(f"📰 FMP: {len(eventos)} eventos cargados")
            return eventos
            
        except Exception as e:
            self.logger.warning(f"⚠️ FMP error: {e}")
            return []


# ============================================================
# FUENTE: FINNHUB
# ============================================================

class FuenteFinnhub(FuenteNoticias):
    """Fuente de noticias desde Finnhub."""
    
    def __init__(self, api_key: str, prioridad: int = 2):
        super().__init__("Finnhub", prioridad)
        self.api_key = api_key
    
    def obtener_eventos(self) -> List[EventoNoticia]:
        if not self.api_key:
            self.logger.warning("⚠️ Finnhub API key no configurada")
            return []
        
        try:
            url = f"https://finnhub.io/api/v1/calendar/economic?token={self.api_key}"
            response = requests.get(url, timeout=10)
            
            if response.status_code != 200:
                self.logger.warning(f"⚠️ Finnhub error: {response.status_code}")
                return []
            
            datos = response.json().get('economicCalendar', [])
            eventos = []
            
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
                        nombre=nombre,
                        divisa=divisa,
                        impacto=impacto,
                        hora=hora,
                        sentimiento_esperado=sentimiento,
                        fuente='Finnhub',
                    )
                    eventos.append(evento)
                except Exception as e:
                    self.logger.debug(f"Error procesando evento Finnhub: {e}")
                    continue
            
            self.logger.info(f"📰 Finnhub: {len(eventos)} eventos cargados")
            return eventos
            
        except Exception as e:
            self.logger.warning(f"⚠️ Finnhub error: {e}")
            return []


# ============================================================
# FUENTE: DAILYFX
# ============================================================

class FuenteDailyFX(FuenteNoticias):
    """Fuente de noticias desde DailyFX."""
    
    def __init__(self, prioridad: int = 3):
        super().__init__("DailyFX", prioridad)
    
    def obtener_eventos(self) -> List[EventoNoticia]:
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
            
            if response.status_code != 200:
                self.logger.warning(f"⚠️ DailyFX error: {response.status_code}")
                return []
            
            datos = response.json()
            eventos = []
            
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
                        nombre=nombre,
                        divisa=divisa,
                        impacto=impacto,
                        hora=hora,
                        sentimiento_esperado=sentimiento,
                        fuente='DailyFX',
                    )
                    eventos.append(evento)
                except Exception as e:
                    self.logger.debug(f"Error procesando evento DailyFX: {e}")
                    continue
            
            self.logger.info(f"📰 DailyFX: {len(eventos)} eventos cargados")
            return eventos
            
        except Exception as e:
            self.logger.warning(f"⚠️ DailyFX error: {e}")
            return []


# ============================================================
# FUENTE: FOREXFACTORY
# ============================================================

class FuenteForexFactory(FuenteNoticias):
    """Fuente de noticias desde ForexFactory."""
    
    def __init__(self, prioridad: int = 4):
        super().__init__("ForexFactory", prioridad)
    
    def obtener_eventos(self) -> List[EventoNoticia]:
        try:
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code != 200:
                self.logger.warning(f"⚠️ ForexFactory error: {response.status_code}")
                return []
            
            datos = response.json()
            eventos = []
            
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
                        nombre=nombre,
                        divisa=divisa,
                        impacto=impacto,
                        hora=hora,
                        sentimiento_esperado=sentimiento,
                        fuente='ForexFactory',
                    )
                    eventos.append(evento)
                except Exception as e:
                    self.logger.debug(f"Error procesando evento ForexFactory: {e}")
                    continue
            
            self.logger.info(f"📰 ForexFactory: {len(eventos)} eventos cargados")
            return eventos
            
        except Exception as e:
            self.logger.warning(f"⚠️ ForexFactory error: {e}")
            return []


# ============================================================
# FUENTE: INVESTING RSS
# ============================================================

class FuenteInvestingRSS(FuenteNoticias):
    """Fuente de noticias desde Investing RSS."""
    
    def __init__(self, prioridad: int = 5):
        super().__init__("InvestingRSS", prioridad)
    
    def obtener_eventos(self) -> List[EventoNoticia]:
        try:
            url = "https://www.investing.com/rss/news.rss"
            feed = feedparser.parse(url)
            
            if not feed.entries:
                return []
            
            eventos = []
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
                        nombre=titulo[:80],
                        divisa=divisa,
                        impacto=impacto,
                        hora=hora,
                        sentimiento_esperado=sentimiento,
                        fuente='Investing_RSS',
                        descripcion=desc[:200],
                    )
                    eventos.append(evento)
                except Exception as e:
                    self.logger.debug(f"Error procesando evento Investing RSS: {e}")
                    continue
            
            self.logger.info(f"📰 Investing RSS: {len(eventos)} eventos cargados")
            return eventos
            
        except Exception as e:
            self.logger.warning(f"⚠️ Investing RSS error: {e}")
            return []
    
    def _extraer_divisa(self, texto: str) -> str:
        """Extrae la divisa mencionada en un texto."""
        texto_lower = texto.lower()
        
        from noticias.sistema_noticias import KEYWORDS_DIVISAS_NLP
        for divisa, keywords in KEYWORDS_DIVISAS_NLP.items():
            for kw in keywords:
                if kw.lower() in texto_lower:
                    return divisa
        return 'ALL'
    
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