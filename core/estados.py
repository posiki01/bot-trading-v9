#!/usr/bin/env python3
"""
core/estados.py (V9.0)
Estado global del bot - Singleton thread-safe.
"""

import threading
from typing import Dict, Any, Optional, Set
from datetime import datetime, timezone
from dataclasses import dataclass, field


@dataclass
class EstadoGlobal:
    """Estado global del bot."""
    
    # ============================================================
    # ESTADO DE EJECUCIÓN
    # ============================================================
    operando: bool = False
    modo_depuracion: bool = False
    modo_backtest: bool = False
    modo_solo_contexto: bool = False
    
    # ============================================================
    # BLOQUEOS Y COOLDOWNS
    # ============================================================
    bloqueo_emergencia_hasta: Optional[datetime] = None
    cooldowns_simbolos: Dict[str, datetime] = field(default_factory=dict)
    simbolos_en_proceso: Set[str] = field(default_factory=set)
    
    # ============================================================
    # POSICIONES Y WATCHLIST
    # ============================================================
    posiciones_abiertas: Dict[int, Dict] = field(default_factory=dict)
    watchlist: Dict[str, datetime] = field(default_factory=dict)
    
    # ============================================================
    # CONTEXTOS
    # ============================================================
    contexto_h1: Dict[str, Dict] = field(default_factory=dict)
    regimen_mercado: Dict[str, Any] = field(default_factory=dict)
    
    # ============================================================
    # SNIPER
    # ============================================================
    sniper_error_counts: Dict[str, int] = field(default_factory=dict)
    sniper_cooldown: Dict[str, datetime] = field(default_factory=dict)
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    perdidas_consecutivas: int = 0
    equity_inicio_dia: Optional[float] = None
    
    # ============================================================
    # LOCK
    # ============================================================
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    
    def adquirir_lock(self):
        """Adquiere el lock global."""
        self._lock.acquire()
    
    def liberar_lock(self):
        """Libera el lock global."""
        self._lock.release()
    
    def __enter__(self):
        self.adquirir_lock()
        return self
    
    def __exit__(self, *args):
        self.liberar_lock()