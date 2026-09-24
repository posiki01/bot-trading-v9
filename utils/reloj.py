#!/usr/bin/env python3
"""
utils/reloj.py (V1.0 - NUEVO)
Sistema de reloj inyectable para backtest con tiempo simulado.

PROPÓSITO:
- En producción: now_utc() == datetime.now(timezone.utc)
- En backtest:   now_utc() == tiempo de la vela simulada

USO EN MÓDULOS:
    # ❌ Antes
    from datetime import datetime, timezone
    dt = datetime.now(timezone.utc)

    # ✅ Después
    from utils.reloj import now_utc
    dt = now_utc()

USO EN BACKTEST:
    from utils.reloj import set_clock, activate_clock, deactivate_clock

    activate_clock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    set_clock(datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc))
    # ... ejecutar vela ...
    deactivate_clock()
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

# ============================================================
# SIMULATED CLOCK
# ============================================================

class SimulatedClock:
    """
    Reloj simulado thread-safe.
    Si está activo, `now()` retorna el tiempo simulado.
    Si no, retorna el tiempo real del sistema.
    """

    def __init__(self):
        self._active = False
        self._current: datetime = datetime.now(timezone.utc)
        self._lock = threading.RLock()
        self._history: list = []  # Opcional: trazabilidad

    # ---------- Control ----------

    def activate(self, initial: Optional[datetime] = None):
        """Activa el modo simulado."""
        with self._lock:
            self._active = True
            if initial is not None:
                self._current = self._normalize(initial)

    def deactivate(self):
        """Desactiva el modo simulado (vuelve al tiempo real)."""
        with self._lock:
            self._active = False
            self._current = datetime.now(timezone.utc)

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    # ---------- Avance ----------

    def set(self, dt: datetime):
        """Fija el tiempo simulado."""
        with self._lock:
            self._current = self._normalize(dt)

    def advance(self, delta: timedelta):
        """Avanza el tiempo simulado."""
        with self._lock:
            self._current += delta
            if len(self._history) > 1000:
                self._history = self._history[-500:]
            self._history.append(self._current)

    def advance_to(self, dt: datetime):
        """Avanza hasta un tiempo específico."""
        with self._lock:
            self._current = self._normalize(dt)

    # ---------- Consulta ----------

    def now(self, tz: Optional[timezone] = None) -> datetime:
        """Retorna el tiempo actual (simulado o real)."""
        with self._lock:
            if self._active:
                dt = self._current
                if tz is not None and dt.tzinfo != tz:
                    dt = dt.astimezone(tz)
                return dt
            return datetime.now(tz) if tz is not None else datetime.now()

    def elapsed(self) -> timedelta:
        """Tiempo transcurrido desde activación."""
        with self._lock:
            if not self._active:
                return timedelta(0)
            return self._current - self._history[0] if self._history else timedelta(0)

    # ---------- Helpers ----------

    def _normalize(self, dt: datetime) -> datetime:
        """Asegura timezone UTC."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)


# ============================================================
# INSTANCIA GLOBAL
# ============================================================

_clock = SimulatedClock()


# ============================================================
# API PÚBLICA (para módulos)
# ============================================================

def now_utc() -> datetime:
    """
    Retorna el tiempo actual en UTC.
    Reemplaza a `datetime.now(timezone.utc)`.
    """
    return _clock.now(timezone.utc)


def now(tz: Optional[timezone] = None) -> datetime:
    """
    Retorna el tiempo actual (opcionalmente en zona específica).
    Reemplaza a `datetime.now()`.
    """
    return _clock.now(tz)


def hoy_utc():
    """Fecha actual UTC."""
    return now_utc().date()


def timestamp_utc() -> float:
    """Timestamp unix del tiempo actual."""
    return now_utc().timestamp()


def iso_utc() -> str:
    """ISO 8601 del tiempo actual."""
    return now_utc().isoformat()


# ============================================================
# API PÚBLICA (para backtest)
# ============================================================

def activate_clock(initial: Optional[datetime] = None):
    """Activa el reloj simulado."""
    _clock.activate(initial)


def deactivate_clock():
    """Desactiva el reloj simulado."""
    _clock.deactivate()


def set_clock(dt: datetime):
    """Fija el tiempo simulado."""
    _clock.set(dt)


def advance_clock(delta: timedelta):
    """Avanza el tiempo simulado."""
    _clock.advance(delta)


def advance_clock_to(dt: datetime):
    """Avanza hasta un tiempo específico."""
    _clock.advance_to(dt)


def is_clock_active() -> bool:
    """Indica si el reloj simulado está activo."""
    return _clock.is_active()


def get_clock() -> SimulatedClock:
    """Obtiene la instancia global (para uso avanzado)."""
    return _clock


# ============================================================
# CONTEXTO (context manager)
# ============================================================

class TiempoSimulado:
    """
    Context manager para simular un tiempo específico.

    USO:
        with TiempoSimulado(datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)):
            # dentro del bloque, now_utc() retorna ese tiempo
            pass
        # fuera del bloque, vuelve a la normalidad
    """

    def __init__(self, dt: datetime):
        self.dt = dt
        self._was_active = False

    def __enter__(self):
        self._was_active = _clock.is_active()
        if not self._was_active:
            _clock.activate()
        _clock.set(self.dt)
        return self

    def __exit__(self, *args):
        if not self._was_active:
            _clock.deactivate()


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando utils/reloj.py...")

    # 1. Modo normal
    real = now_utc()
    print(f"1. Modo normal: {real.isoformat()}")
    assert not is_clock_active()

    # 2. Activar y fijar tiempo
    fake = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
    activate_clock(fake)
    print(f"2. Modo simulado activado: {now_utc().isoformat()}")
    assert is_clock_active()
    assert now_utc() == fake

    # 3. Avanzar
    advance_clock(timedelta(hours=2))
    esperado = fake + timedelta(hours=2)
    print(f"3. Después de +2h: {now_utc().isoformat()}")
    assert now_utc() == esperado

    # 4. Avanzar a tiempo específico
    nuevo = datetime(2024, 1, 20, 15, 0, tzinfo=timezone.utc)
    advance_clock_to(nuevo)
    print(f"4. Avanzado a: {now_utc().isoformat()}")
    assert now_utc() == nuevo

    # 5. Context manager
    with TiempoSimulado(datetime(2024, 2, 1, tzinfo=timezone.utc)):
        assert now_utc() == datetime(2024, 2, 1, tzinfo=timezone.utc)
    print(f"5. Post-context: {now_utc().isoformat()}")

    # 6. Desactivar
    deactivate_clock()
    print(f"6. Desactivado: activo={is_clock_active()}")
    assert not is_clock_active()

    # 7. Timezone específica
    activate_clock(datetime(2024, 3, 15, 12, 0, tzinfo=timezone.utc))
    from zoneinfo import ZoneInfo
    col = now(ZoneInfo("America/Bogota"))
    print(f"7. Hora UTC: 12:00 → Colombia: {col.hour}:00")
    assert col.hour == 7  # UTC-5
    deactivate_clock()

    print("\n✅ Todos los tests pasan")