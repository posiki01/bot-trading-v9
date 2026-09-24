#!/usr/bin/env python3
"""
backtesting/backtester_v10.py (V1.0 - NUEVO)
Motor de backtest V10.0 — usa los módulos reales del bot.

DIFERENCIA CON backtesting_engine_v2.py:
- engine_v2: reimplementaba RSI/MACD a mano. No usaba el bot real.
- backtester_v10: usa Orquestador(modo_backtest=True) end-to-end.

FLUJO:
1. Backup de SQLite (por seguridad)
2. Crear ConectorSimulado con los dataframes históricos
3. Crear Orquestador(modo_backtest=True)
4. Inyectar ConectorSimulado en todos los módulos del orquestador
5. Iterar por vela M5:
   - set_clock(timestamp)  ← SimulatedClock
   - precargar análisis H1 cada hora
   - actualizar F2 cada 15 min
   - promover F1→F2→F3 cada 15 min
   - ejecutar sniper cada vela M5
   - monitorear posiciones (SL/TP/trailing/timeout)
   - reset diario
6. Generar métricas + informe
7. Restaurar SQLite

USO:
    python -m backtesting.backtester_v10 --inicio 2024-06-01 --fin 2024-09-01
    python -m backtesting.backtester_v10 --inicio 2024-06-01 --fin 2024-09-01 --solo EURUSD,GBPUSD
"""

import os
import sys
import time
import shutil
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta, date as date_cls
from typing import Dict, Any, Optional, List, Tuple

import pandas as pd
import numpy as np

from utils.reloj import (
    activate_clock,
    deactivate_clock,
    set_clock,
    now_utc,
)
from utils.cache import CacheUnificado

from backtesting.conector_simulado import ConectorSimulado, create_conector_simulado

logger = logging.getLogger('BotTrading.Backtesting.BacktesterV10')


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class BacktesterV10:
    """
    Motor de backtest V10.0.
    Usa el orquestador real end-to-end.
    """

    def __init__(
        self,
        dataframes: Dict[str, Dict[int, pd.DataFrame]],
        simbolos: List[str],
        fecha_inicio: datetime,
        fecha_fin: datetime,
        balance_inicial: float = 300.0,
        comision_por_lote: float = 3.5,
        slippage_pips: float = 0.5,
        modo_depuracion: bool = False,
        restaurar_db: bool = True,
    ):
        """
        Args:
            dataframes: {simbolo: {timeframe_min: df}}
            simbolos: lista de símbolos a testear
            fecha_inicio, fecha_fin: rango del backtest
            balance_inicial: capital inicial
            comision_por_lote: comisión round-trip
            slippage_pips: slippage en pips
            modo_depuracion: logs extra
            restaurar_db: si True, restaura SQLite al terminar
        """
        self.dataframes = dataframes
        self.simbolos = simbolos
        self.fecha_inicio = self._normalize_dt(fecha_inicio)
        self.fecha_fin = self._normalize_dt(fecha_fin)
        self.balance_inicial = balance_inicial
        self.comision_por_lote = comision_por_lote
        self.slippage_pips = slippage_pips
        self.modo_depuracion = modo_depuracion
        self.restaurar_db = restaurar_db

        # Estado
        self.orq = None
        self.conector = None
        self._db_backup_path: Optional[Path] = None
        self._ultima_hora_procesada: Optional[datetime] = None
        self._ultimo_m15_procesado: Optional[datetime] = None
        self._ultimo_dia: Optional[date_cls] = None
        self._ultimo_degradado: Optional[datetime] = None

        # Stats de backtest
        self._stats = {
            'velas_m5_totales': 0,
            'velas_m5_procesadas': 0,
            'horas_h1_precargadas': 0,
            'sniper_evaluaciones': 0,
            'errores': 0,
            'inicio': None,
            'fin': None,
            'duracion_seg': 0,
        }

        self.logger = logger

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    def run(self) -> Dict[str, Any]:
        """Ejecuta el backtest."""
        t_inicio = time.time()
        self._stats['inicio'] = now_utc().isoformat()

        self.logger.info("=" * 70)
        self.logger.info("🚀 INICIANDO BACKTEST V10.0")
        self.logger.info("=" * 70)
        self.logger.info(f"   Rango:  {self.fecha_inicio} → {self.fecha_fin}")
        self.logger.info(f"   Símbolos: {len(self.simbolos)}")
        self.logger.info(f"   Capital:  ${self.balance_inicial:.2f}")

        try:
            # ============================================================
            # 1. SETUP
            # ============================================================
            self._backup_db()
            self._crear_orquestador()
            self._inyectar_conector()
            self._deshabilitar_persistencia_backtest()

            # ============================================================
            # 2. PREPARAR VELAS
            # ============================================================
            velas_m5 = self._obtener_velas_m5_globales()
            self._stats['velas_m5_totales'] = len(velas_m5)

            if len(velas_m5) == 0:
                self.logger.error("❌ No hay velas M5 en el rango")
                return {'error': 'Sin velas'}

            self.logger.info(f"   Velas M5 a procesar: {len(velas_m5)}")
            self.logger.info(f"   Duración estimada: {self._estimar_duracion(len(velas_m5))}")

            # ============================================================
            # 3. PRIMERA PRECARGA (calentamiento)
            # ============================================================
            activate_clock(self.fecha_inicio)
            self.logger.info("🔥 Calentamiento inicial...")
            self._precargar_todos()

            # ============================================================
            # 4. BUCLE PRINCIPAL
            # ============================================================
            self._bucle_principal(velas_m5)

            # ============================================================
            # 5. CIERRE FORZADO DE POSICIONES ABIERTAS
            # ============================================================
            self._cerrar_posiciones_finales()

            # ============================================================
            # 6. MÉTRICAS
            # ============================================================
            metricas = self._generar_metricas()

            self._stats['fin'] = now_utc().isoformat()
            self._stats['duracion_seg'] = round(time.time() - t_inicio, 1)

            self.logger.info("=" * 70)
            self.logger.info(f"✅ BACKTEST COMPLETADO en {self._stats['duracion_seg']}s")
            self.logger.info("=" * 70)
            self._log_metricas(metricas)

            return metricas

        except KeyboardInterrupt:
            self.logger.warning("⚠️ Backtest interrumpido por el usuario")
            return {'error': 'Interrumpido'}

        except Exception as e:
            self.logger.error(f"❌ Error en backtest: {e}", exc_info=True)
            return {'error': str(e)}

        finally:
            self._cleanup()

    # ============================================================
    # SETUP
    # ============================================================

    def _backup_db(self):
        """Backup del SQLite antes del backtest."""
        base_dir = Path(__file__).parent.parent
        db_path = base_dir / "data" / "bot_data.db"

        if not db_path.exists():
            self.logger.info("ℹ️ Sin SQLite previo (nuevo)")
            return

        backup = db_path.with_suffix(f".db.backtest_{int(time.time())}.backup")
        try:
            shutil.copy2(db_path, backup)
            self._db_backup_path = backup
            self.logger.info(f"💾 Backup SQLite: {backup.name}")
        except Exception as e:
            self.logger.warning(f"⚠️ Error en backup: {e}")

    def _crear_orquestador(self):
        """Crea el orquestador en modo backtest."""
        from core.orquestador import Orquestador

        self.logger.info("🔧 Creando Orquestador (modo backtest)...")
        self.orq = Orquestador(modo_backtest=True, modo_depuracion=self.modo_depuracion)

    def _inyectar_conector(self):
        """Inyecta ConectorSimulado en el orquestador y todos sus módulos."""
        self.logger.info("🔌 Inyectando ConectorSimulado...")

        self.conector = create_conector_simulado(
            dataframes=self.dataframes,
            balance_inicial=self.balance_inicial,
            comision_por_lote=self.comision_por_lote,
            slippage_pips=self.slippage_pips,
            modo_depuracion=self.modo_depuracion,
        )
        self.conector.conectar()

        # Inyectar en el orquestador (recursivamente en atributos con .mt5)
        self._reemplazar_mt5(self.orq)
        self.logger.info("✅ ConectorSimulado inyectado")

    def _reemplazar_mt5(self, obj: Any, visited: Optional[set] = None):
        """Reemplaza recursivamente .mt5 en un objeto y sus sub-atributos."""
        if obj is None:
            return

        if visited is None:
            visited = set()

        obj_id = id(obj)
        if obj_id in visited:
            return
        visited.add(obj_id)

        # Si tiene .mt5 y no es el conector
        if hasattr(obj, 'mt5') and getattr(obj, 'mt5') is not self.conector:
            try:
                setattr(obj, 'mt5', self.conector)
            except Exception:
                pass

        # Recorrer atributos que puedan tener mt5
        for attr_name in ['cache', 'pipeline', 'monitor_posiciones', 'sniper_checklist',
                          'ejecutor', 'gestor_stops', 'gestion_riesgo', 'escaneador',
                          'nivel_tracker', 'patron_tracker', 'ml_optimizer',
                          'regimen_filter', 'score_engine', 'analisis_capas',
                          'analisis_fases', 'trailing_engine', 'decisor_operabilidad',
                          'modo_selector', 'entry_timer', 'circuit_breaker',
                          'informe_diario', 'analisis_tecnico']:
            try:
                sub = getattr(obj, attr_name, None)
                if sub is not None and not isinstance(sub, (str, int, float, bool)):
                    self._reemplazar_mt5(sub, visited)
            except Exception:
                pass

    def _deshabilitar_persistencia_backtest(self):
        """Reduce persistencia en backtest para acelerar."""
        # Cache: forzar siempre fetch (no usar caché en backtest)
        if hasattr(self.orq, 'cache') and self.orq.cache:
            self.orq.cache.modo_backtest = True
            self.logger.info("🔧 Cache en modo backtest (sin persistencia)")

    # ============================================================
    # VELAS
    # ============================================================

    def _obtener_velas_m5_globales(self) -> List[datetime]:
        """Obtiene todas las velas M5 (union de todos los símbolos) en el rango."""
        fechas_set = set()

        for simbolo in self.simbolos:
            dfs = self.dataframes.get(simbolo, {})
            df_m5 = dfs.get(5)

            if df_m5 is None or len(df_m5) == 0:
                continue

            # Filtrar rango
            mask = (df_m5.index >= self.fecha_inicio) & (df_m5.index <= self.fecha_fin)
            fechas_set.update(df_m5.index[mask].tolist())

        return sorted(fechas_set)

    def _estimar_duracion(self, n_velas: int) -> str:
        """Estimación grosera."""
        # Asumimos ~50ms por vela M5 con 15 símbolos (análisis distribuido)
        seg = n_velas * 0.05
        if seg < 60:
            return f"{seg:.0f}s"
        if seg < 3600:
            return f"{seg/60:.1f} min"
        return f"{seg/3600:.1f} h"

    # ============================================================
    # BUCLE PRINCIPAL
    # ============================================================

    def _bucle_principal(self, velas: List[datetime]):
        """Bucle principal por vela M5."""
        self.logger.info("🔄 Iniciando bucle principal...")

        total = len(velas)
        log_intervalo = max(100, total // 50)  # Log cada ~2% de progreso

        for i, vela in enumerate(velas):
            if i % log_intervalo == 0 and i > 0:
                pct = i / total * 100
                elapsed = time.time() - time.mktime(
                    datetime.fromisoformat(self._stats['inicio']).timetuple()
                ) if self._stats['inicio'] else 0
                self.logger.info(
                    f"⏳ Progreso: {pct:.1f}% "
                    f"({i}/{total}) | "
                    f"balance=${self.conector.balance:.2f} | "
                    f"pos={len(self.conector._posiciones)} | "
                    f"cierres={len(self.conector._historial_cierres)}"
                )

            self._stats['velas_m5_procesadas'] += 1

            # Set clock
            set_clock(vela)

            try:
                self._procesar_vela_m5(vela)
            except Exception as e:
                self._stats['errores'] += 1
                if self.modo_depuracion:
                    self.logger.error(f"❌ Error en vela {vela}: {e}", exc_info=True)

    def _procesar_vela_m5(self, vela: datetime):
        """Procesa una vela M5."""
        # ============================================================
        # 1. PRECARGA H1 (cada hora)
        # ============================================================
        hora_actual = vela.replace(minute=0, second=0, microsecond=0)
        if self._ultima_hora_procesada != hora_actual:
            self._ultima_hora_procesada = hora_actual
            self._precargar_todos()
            self._stats['horas_h1_precargadas'] += 1

        # ============================================================
        # 2. ACTUALIZAR FASE 2 (cada 15 min)
        # ============================================================
        m15_actual = vela.replace(minute=(vela.minute // 15) * 15, second=0, microsecond=0)
        if self._ultimo_m15_procesado != m15_actual:
            self._ultimo_m15_procesado = m15_actual
            self._actualizar_fase2()

        # ============================================================
        # 3. PROMOVER F1→F2→F3
        # ============================================================
        if self.orq.pipeline:
            try:
                self.orq.pipeline.promover_automaticamente()
            except Exception as e:
                if self.modo_depuracion:
                    self.logger.debug(f"⚠️ Error promoviendo: {e}")

        # ============================================================
        # 4. SNIPER (evalúa F3 y ejecuta)
        # ============================================================
        try:
            self.orq._ejecutar_sniper_con_vela_virtual()
            self._stats['sniper_evaluaciones'] += 1
        except Exception as e:
            self._stats['errores'] += 1
            if self.modo_depuracion:
                self.logger.debug(f"⚠️ Error sniper: {e}")

        # ============================================================
        # 5. MONITOREO (SL/TP/trailing/timeout)
        # ============================================================
        try:
            self.orq.monitor_posiciones.ejecutar_ciclo()
        except Exception as e:
            self._stats['errores'] += 1
            if self.modo_depuracion:
                self.logger.debug(f"⚠️ Error monitoreo: {e}")

        # ============================================================
        # 6. RESET DIARIO
        # ============================================================
        dia_actual = vela.date()
        if self._ultimo_dia != dia_actual:
            self._ultimo_dia = dia_actual
            self._reset_diario(vela)

        # ============================================================
        # 7. DEGRADACIÓN POR TIEMPO (cada 25 min)
        # ============================================================
        degradado_actual = vela.replace(
            minute=(vela.minute // 25) * 25, second=0, microsecond=0
        )
        if self._ultimo_degradado != degradado_actual:
            self._ultimo_degradado = degradado_actual
            self._degradar_oportunidades()

    # ============================================================
    # PASOS DEL BUCLE
    # ============================================================

    def _precargar_todos(self):
        """Precarga análisis H1 de todos los símbolos disponibles en este timestamp."""
        ahora = now_utc()

        for simbolo in self.simbolos:
            # ¿Tiene datos H1 para este timestamp?
            df_h1 = self.dataframes.get(simbolo, {}).get(60)
            if df_h1 is None or len(df_h1) == 0:
                continue

            # ¿Hay una vela H1 reciente? (última <= ahora)
            df_h1_actual = df_h1[df_h1.index <= ahora]
            if len(df_h1_actual) < 50:
                continue

            try:
                self.orq._precargar_simbolo(simbolo)
            except Exception as e:
                if self.modo_depuracion:
                    self.logger.debug(f"⚠️ Error precargando {simbolo}: {e}")

    def _actualizar_fase2(self):
        """Actualiza oportunidades F2 con M15 fresco."""
        try:
            self.orq._actualizar_oportunidades_fase2()
        except Exception as e:
            if self.modo_depuracion:
                self.logger.debug(f"⚠️ Error actualizando F2: {e}")

    def _degradar_oportunidades(self):
        """Degrada oportunidades atascadas."""
        if not self.orq.pipeline:
            return
        try:
            self.orq.pipeline.degradar_por_tiempo()
        except Exception as e:
            if self.modo_depuracion:
                self.logger.debug(f"⚠️ Error degradando: {e}")

    def _reset_diario(self, vela: datetime):
        """Reset diario del sistema."""
        self.logger.info(f"📅 Nuevo día: {vela.date()} | balance=${self.conector.balance:.2f}")

        try:
            self.orq.gestion_riesgo.reset_diario(current_time=vela)
        except Exception as e:
            self.logger.debug(f"⚠️ Error reset diario riesgo: {e}")

        try:
            self.orq.pipeline.limpiar_antiguos(horas=48)
        except Exception as e:
            self.logger.debug(f"⚠️ Error limpiando pipeline: {e}")

    def _cerrar_posiciones_finales(self):
        """Cierra posiciones abiertas al final del backtest."""
        self.logger.info("🔚 Cerrando posiciones abiertas al final...")

        posiciones = self.conector.obtener_posiciones()
        for pos in posiciones:
            try:
                self.conector.cerrar_posicion(pos['ticket'])
            except Exception as e:
                self.logger.warning(f"⚠️ Error cerrando {pos['ticket']}: {e}")

    # ============================================================
    # MÉTRICAS
    # ============================================================

    def _generar_metricas(self) -> Dict[str, Any]:
        """Genera métricas finales."""
        cierres = self.conector.obtener_historial_cierres()

        if not cierres:
            return self._metricas_vacias()

        df = pd.DataFrame(cierres)

        total = len(df)
        ganadoras = df[df['pnl_neto'] > 0]
        perdedoras = df[df['pnl_neto'] < 0]
        breakeven = df[df['pnl_neto'] == 0]

        pnl_total = df['pnl_neto'].sum()
        gross_profit = ganadoras['pnl_neto'].sum() if len(ganadoras) > 0 else 0
        gross_loss = abs(perdedoras['pnl_neto'].sum()) if len(perdedoras) > 0 else 0

        # Curva de equity
        equity_curve = [self.balance_inicial]
        for _, row in df.iterrows():
            equity_curve.append(equity_curve[-1] + row['pnl_neto'])

        # Drawdown
        max_dd = 0
        max_dd_pct = 0
        peak = equity_curve[0]
        for val in equity_curve:
            if val > peak:
                peak = val
            dd = peak - val
            dd_pct = (dd / peak * 100) if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct

        # Métricas por dimensión
        por_simbolo = self._metricas_por_dim(df, 'simbolo')
        por_direccion = self._metricas_por_dim(df, 'direccion')
        por_motivo = self._metricas_por_dim(df, 'motivo_cierre')

        # Sharpe (basado en PnL por operación)
        if len(df) > 1 and df['pnl_neto'].std() > 0:
            sharpe = (df['pnl_neto'].mean() / df['pnl_neto'].std()) * np.sqrt(252)
        else:
            sharpe = 0

        # Duración promedio
        duracion_prom = df['duracion_min'].mean() if 'duracion_min' in df.columns else 0

        return {
            'resumen': {
                'total_operaciones': total,
                'ganadoras': len(ganadoras),
                'perdedoras': len(perdedoras),
                'breakeven': len(breakeven),
                'win_rate': round(len(ganadoras) / total * 100, 2),
                'pnl_neto': round(pnl_total, 2),
                'gross_profit': round(gross_profit, 2),
                'gross_loss': round(gross_loss, 2),
                'factor_beneficio': round(gross_profit / gross_loss, 2) if gross_loss > 0 else 'inf',
                'balance_final': round(self.conector.balance, 2),
                'retorno_pct': round((self.conector.balance / self.balance_inicial - 1) * 100, 2),
                'max_drawdown': round(max_dd, 2),
                'max_drawdown_pct': round(max_dd_pct, 2),
                'sharpe_ratio': round(sharpe, 2),
                'duracion_prom_min': round(duracion_prom, 1),
            },
            'por_simbolo': por_simbolo,
            'por_direccion': por_direccion,
            'por_motivo_cierre': por_motivo,
            'equity_curve': [round(x, 2) for x in equity_curve],
            'cierres': cierres,
            'stats_backtest': self._stats.copy(),
        }

    def _metricas_vacias(self) -> Dict[str, Any]:
        return {
            'resumen': {
                'total_operaciones': 0,
                'ganadoras': 0,
                'perdedoras': 0,
                'win_rate': 0,
                'pnl_neto': 0,
                'factor_beneficio': 0,
                'balance_final': self.balance_inicial,
                'retorno_pct': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
            },
            'por_simbolo': {},
            'por_direccion': {},
            'por_motivo_cierre': {},
            'equity_curve': [self.balance_inicial],
            'cierres': [],
            'stats_backtest': self._stats.copy(),
        }

    def _metricas_por_dim(self, df: pd.DataFrame, dim: str) -> Dict[str, Any]:
        """Agrupa métricas por una dimensión."""
        if dim not in df.columns:
            return {}

        resultado = {}
        for valor, grupo in df.groupby(dim):
            total = len(grupo)
            ganadoras = (grupo['pnl_neto'] > 0).sum()
            pnl = grupo['pnl_neto'].sum()
            resultado[str(valor)] = {
                'total': total,
                'ganadoras': int(ganadoras),
                'perdedoras': int(total - ganadoras),
                'pnl': round(pnl, 2),
                'win_rate': round(ganadoras / total * 100, 2) if total > 0 else 0,
            }
        return resultado

    def _log_metricas(self, metricas: Dict[str, Any]):
        """Imprime métricas en formato legible."""
        res = metricas.get('resumen', {})

        self.logger.info("")
        self.logger.info("📊 RESULTADOS DEL BACKTEST")
        self.logger.info("=" * 70)
        self.logger.info(f"   Balance final:  ${res.get('balance_final', 0):.2f}")
        self.logger.info(f"   PnL neto:       ${res.get('pnl_neto', 0):+.2f}")
        self.logger.info(f"   Retorno:        {res.get('retorno_pct', 0):+.2f}%")
        self.logger.info(f"   Ops totales:    {res.get('total_operaciones', 0)}")
        self.logger.info(f"   Ganadoras:      {res.get('ganadoras', 0)}")
        self.logger.info(f"   Perdedoras:     {res.get('perdedoras', 0)}")
        self.logger.info(f"   Win rate:       {res.get('win_rate', 0):.1f}%")
        self.logger.info(f"   Factor benef.:  {res.get('factor_beneficio', 0)}")
        self.logger.info(f"   Max DD:         ${res.get('max_drawdown', 0):.2f} ({res.get('max_drawdown_pct', 0):.1f}%)")
        self.logger.info(f"   Sharpe:         {res.get('sharpe_ratio', 0):.2f}")
        self.logger.info(f"   Duración prom:  {res.get('duracion_prom_min', 0):.1f} min")

        if metricas.get('por_simbolo'):
            self.logger.info("")
            self.logger.info("   Por símbolo:")
            for sim, stats in sorted(
                metricas['por_simbolo'].items(),
                key=lambda x: x[1]['pnl'],
                reverse=True,
            ):
                self.logger.info(
                    f"      {sim}: {stats['total']} ops | "
                    f"WR {stats['win_rate']:.0f}% | "
                    f"${stats['pnl']:+.2f}"
                )

        if metricas.get('por_motivo_cierre'):
            self.logger.info("")
            self.logger.info("   Por motivo de cierre:")
            for motivo, stats in metricas['por_motivo_cierre'].items():
                self.logger.info(
                    f"      {motivo}: {stats['total']} ops | "
                    f"${stats['pnl']:+.2f}"
                )

        self.logger.info("=" * 70)

    # ============================================================
    # CLEANUP
    # ============================================================

    def _cleanup(self):
        """Restaura DB y desactiva reloj."""
        try:
            deactivate_clock()
        except Exception:
            pass

        if self.restaurar_db and self._db_backup_path and self._db_backup_path.exists():
            try:
                base_dir = Path(__file__).parent.parent
                db_path = base_dir / "data" / "bot_data.db"

                # Cerrar conexiones del orquestador
                if self.orq and hasattr(self.orq, 'almacen'):
                    try:
                        self.orq.almacen.cerrar()
                    except Exception:
                        pass

                # Restaurar
                shutil.copy2(self._db_backup_path, db_path)
                self.logger.info(f"♻️ SQLite restaurado desde backup")
            except Exception as e:
                self.logger.warning(f"⚠️ Error restaurando DB: {e}")

    # ============================================================
    # HELPERS
    # ============================================================

    def _normalize_dt(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # ============================================================
    # GUARDADO DE RESULTADOS
    # ============================================================

    def guardar_resultados(self, metricas: Dict[str, Any], ruta: Path):
        """Guarda el resultado en JSON."""
        import json
        ruta.parent.mkdir(parents=True, exist_ok=True)

        # Simplificar: quitar equity_curve y cierres si es muy grande
        resultado = dict(metricas)

        try:
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(resultado, f, indent=2, ensure_ascii=False, default=str)
            self.logger.info(f"💾 Resultados guardados: {ruta}")
        except Exception as e:
            self.logger.error(f"❌ Error guardando: {e}")


# ============================================================
# CARGA DE DATOS
# ============================================================

def cargar_datos_backtest(
    simbolos: List[str],
    fecha_inicio: datetime,
    fecha_fin: datetime,
    usar_sqlite: bool = True,
) -> Dict[str, Dict[int, pd.DataFrame]]:
    """
    Carga datos desde SQLite primero, MT5 si hace falta.

    Returns:
        {simbolo: {timeframe_min: df}}
    """
    logger.info("📥 Cargando datos históricos...")

    dataframes: Dict[str, Dict[int, pd.DataFrame]] = {}
    timeframes = [60, 240, 5, 15]  # H1, H4, M5, M15

    # Fuente 1: SQLite
    if usar_sqlite:
        try:
            from data.almacenamiento_sqlite import AlmacenamientoSQLite
            almacen = AlmacenamientoSQLite(
                base_dir=Path(__file__).parent.parent / "data",
                modo_backup=False,
            )

            for simbolo in simbolos:
                dfs = {}
                for tf in timeframes:
                    try:
                        df = almacen.obtener_datos_historicos(simbolo, tf)
                        if df is not None and len(df) > 0:
                            # Filtrar rango
                            mask = (df.index >= fecha_inicio) & (df.index <= fecha_fin + timedelta(days=1))
                            df_filtrado = df[mask]
                            if len(df_filtrado) > 0:
                                dfs[tf] = df_filtrado
                    except Exception as e:
                        logger.debug(f"⚠️ {simbolo} TF{tf}: error SQLite: {e}")

                if dfs:
                    dataframes[simbolo] = dfs
                    logger.info(f"   {simbolo}: {list(dfs.keys())} desde SQLite")

            almacen.cerrar()
        except Exception as e:
            logger.warning(f"⚠️ Error en SQLite: {e}")

    # Fuente 2: MT5 (para lo que falte)
    simbolos_faltantes = [s for s in simbolos if s not in dataframes]
    if simbolos_faltantes:
        logger.info(f"📥 Descargando {len(simbolos_faltantes)} desde MT5...")

        try:
            import MetaTrader5 as mt5

            if not mt5.initialize():
                logger.warning("⚠️ MT5 no disponible")
            else:
                tf_map = {
                    60: mt5.TIMEFRAME_H1,
                    240: mt5.TIMEFRAME_H4,
                    5: mt5.TIMEFRAME_M5,
                    15: mt5.TIMEFRAME_M15,
                }

                for simbolo in simbolos_faltantes:
                    mt5.symbol_select(simbolo, True)
                    dfs = {}

                    for tf, mt5_tf in tf_map.items():
                        try:
                            rates = mt5.copy_rates_range(simbolo, mt5_tf, fecha_inicio, fecha_fin + timedelta(days=1))
                            if rates is None or len(rates) == 0:
                                continue

                            df = pd.DataFrame(rates)
                            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                            df.set_index('time', inplace=True)
                            df.rename(columns={
                                'open': 'Open', 'high': 'High', 'low': 'Low',
                                'close': 'Close', 'tick_volume': 'Volume',
                            }, inplace=True)
                            dfs[tf] = df
                        except Exception as e:
                            logger.debug(f"⚠️ {simbolo} TF{tf}: {e}")

                    if dfs:
                        dataframes[simbolo] = dfs
                        logger.info(f"   {simbolo}: {list(dfs.keys())} desde MT5")

                mt5.shutdown()
        except ImportError:
            logger.warning("⚠️ MetaTrader5 no instalado")

    logger.info(f"✅ Datos cargados para {len(dataframes)} símbolos")
    return dataframes


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Backtester V10.0')
    parser.add_argument('--inicio', type=str, required=True, help='Fecha inicio (YYYY-MM-DD)')
    parser.add_argument('--fin', type=str, required=True, help='Fecha fin (YYYY-MM-DD)')
    parser.add_argument('--solo', type=str, default=None, help='Símbolos separados por coma (default: los 15)')
    parser.add_argument('--balance', type=float, default=300.0, help='Balance inicial')
    parser.add_argument('--comision', type=float, default=3.5, help='Comisión por lote RT')
    parser.add_argument('--slippage', type=float, default=0.5, help='Slippage en pips')
    parser.add_argument('--output', type=str, default='data/backtest_resultado.json', help='Ruta de salida')
    parser.add_argument('--debug', action='store_true', help='Logs extra')
    parser.add_argument('--no-restaurar-db', action='store_true', help='No restaurar SQLite al final')
    args = parser.parse_args()

    # Fechas
    try:
        fecha_inicio = datetime.fromisoformat(args.inicio).replace(tzinfo=timezone.utc)
        fecha_fin = datetime.fromisoformat(args.fin).replace(tzinfo=timezone.utc)
    except ValueError as e:
        print(f"❌ Fecha inválida: {e}")
        sys.exit(1)

    # Símbolos
    if args.solo:
        simbolos = [s.strip().upper() for s in args.solo.split(',') if s.strip()]
    else:
        from config.settings import Config
        simbolos = Config.SIMBOLOS_COMPLETOS

    print(f"🎯 Símbolos: {len(simbolos)}")
    print(f"📅 Rango: {fecha_inicio.date()} → {fecha_fin.date()}")

    # Cargar datos
    dataframes = cargar_datos_backtest(simbolos, fecha_inicio, fecha_fin)

    if not dataframes:
        print("❌ No se cargaron datos")
        sys.exit(1)

    # Backtest
    backtester = BacktesterV10(
        dataframes=dataframes,
        simbolos=list(dataframes.keys()),
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        balance_inicial=args.balance,
        comision_por_lote=args.comision,
        slippage_pips=args.slippage,
        modo_depuracion=args.debug,
        restaurar_db=not args.no_restaurar_db,
    )

    metricas = backtester.run()

    # Guardar
    if 'error' not in metricas:
        backtester.guardar_resultados(metricas, Path(args.output))
    else:
        print(f"❌ Error: {metricas['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()