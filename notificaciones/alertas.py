#!/usr/bin/env python3
"""
notificaciones/alertas.py (V8.0 - REFACTORIZADO)
Sistema de notificaciones con comandos remotos vía Discord y Telegram.

MEJORAS V8.0:
- Integración con LoggerPersistente
- Integración con AlmacenamientoSQLite (para estadísticas)
- Métricas de uso
- Limpieza de código redundante
"""

import requests
import json
import queue
import threading
import time
import os
import logging  # <-- AÑADIR ESTE IMPORT
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# ============================================================
# IMPORTS V8.0
# ============================================================

try:
    from utils.logger_persistente import LoggerPersistente
    _logger_persistente = LoggerPersistente()
    logger = _logger_persistente.get_logger()
except ImportError:
    import logging
    logger = logging.getLogger('BotTrading.Notificaciones')

try:
    from data.almacenamiento_sqlite import AlmacenamientoSQLite
except ImportError:
    AlmacenamientoSQLite = None


class Notificaciones:
    """
    Sistema de notificaciones con cola, embeds y comandos remotos.
    V8.0: Integración con nuevos módulos.
    """

    def __init__(self, discord=None, tg_token=None, tg_chat=None, almacen=None):
        self.discord_webhook = discord
        self.telegram_token = tg_token
        self.telegram_chat = tg_chat
        self.almacen = almacen
        self.logger = logger

        self.queue = queue.Queue()
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True, name="NotifWorker")
        self.thread.start()

        self.comando_callback = None

        self.COLORES = {
            'exito': 0x00ff00,
            'error': 0xff0000,
            'alerta': 0xffaa00,
            'info': 0x0099ff,
            'operacion': 0x9b59b6,
            'cierre': 0xe67e22,
            'heartbeat': 0x2ecc71,
            'sniper': 0xff0066,
            'pipeline': 0x3498db,
            'rechazo': 0xff4444,
            'calidad': 0x00cc88,
            'retest': 0xf1c40f,
            'estado': 0x00ccff,
        }

        self.ultimo_heartbeat = None
        self.ultimo_estado = None
        
        # Estadísticas
        self._stats = {
            'total_enviados': 0,
            'discord_exitosos': 0,
            'discord_fallidos': 0,
            'telegram_exitosos': 0,
            'telegram_fallidos': 0,
            'comandos_procesados': 0,
        }
        
        self.logger.info("📢 Notificaciones V8.0 inicializadas")

    # ============================================================
    # MÉTODOS PRINCIPALES
    # ============================================================

    def _worker(self):
        """Worker de la cola de notificaciones."""
        while self.running:
            try:
                msg, kwargs = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._enviar_mensaje(msg, **kwargs)
                self._stats['total_enviados'] += 1
            except Exception as e:
                self.logger.error(f"Error en worker de notificaciones: {e}")
            finally:
                self.queue.task_done()

    def _enviar_mensaje(self, mensaje: str, tipo: str = 'info',
                        titulo: str = None, campos: List[Dict] = None,
                        color: int = None, footer: str = None):
        """Envía un mensaje a todos los canales configurados."""
        if not mensaje and not titulo:
            return

        embed = self._crear_embed(mensaje, tipo, titulo, campos, color, footer)

        if not embed.get('title') and not embed.get('description'):
            return

        if self.discord_webhook:
            try:
                self._enviar_discord(embed)
                self._stats['discord_exitosos'] += 1
            except Exception as e:
                self._stats['discord_fallidos'] += 1
                self.logger.warning(f"Discord falló: {e}")

        if self.telegram_token and self.telegram_chat:
            try:
                self._enviar_telegram(mensaje, tipo, titulo, campos)
                self._stats['telegram_exitosos'] += 1
            except Exception as e:
                self._stats['telegram_fallidos'] += 1
                self.logger.warning(f"Telegram falló: {e}")

    def _crear_embed(self, mensaje: str, tipo: str = 'info',
                     titulo: str = None, campos: List[Dict] = None,
                     color: int = None, footer: str = None) -> Dict:
        """Crea un embed para Discord."""
        if color is None:
            color = self.COLORES.get(tipo, 0x0099ff)

        if titulo is None:
            titulos = {
                'exito': '✅ Éxito', 'error': '❌ Error', 'alerta': '⚠️ Alerta',
                'info': 'ℹ️ Información', 'operacion': '📈 Nueva Operación',
                'cierre': '📊 Operación Cerrada', 'heartbeat': '💓 Heartbeat',
                'sniper': '🎯 Sniper', 'pipeline': '📊 Pipeline',
                'rechazo': '⛔ Rechazado', 'estado': '📊 Estado del Bot'
            }
            titulo = titulos.get(tipo, '📊 Información')

        if not mensaje:
            mensaje = "Sin contenido adicional"

        mensaje_truncado = mensaje[:4000]
        if len(mensaje) > 4000:
            mensaje_truncado += "\n...(truncado)"

        embed = {
            'title': titulo,
            'description': mensaje_truncado,
            'color': color,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'footer': {'text': footer or f'🤖 Bot Pepperstone | {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} COT'}
        }

        if campos:
            embed['fields'] = []
            for campo in campos[:10]:
                nombre = (campo.get('name') or '').strip()[:256]
                valor = (campo.get('value') or '').strip()[:1024]
                if nombre and valor:
                    embed['fields'].append({
                        'name': nombre,
                        'value': valor,
                        'inline': campo.get('inline', True)
                    })
            if not embed['fields']:
                del embed['fields']

        if not embed['title'] or not embed['title'].strip():
            embed['title'] = 'Notificación del sistema'
        if not embed['description'] or not embed['description'].strip():
            embed['description'] = 'Sin contenido adicional'

        return embed

    def _enviar_discord(self, embed: Dict):
        """Envía embed a Discord con validación robusta."""
        # Asegurar título y descripción
        if not embed.get('title') or not embed.get('title').strip():
            embed['title'] = 'Notificación del sistema'
        if not embed.get('description') or not embed.get('description').strip():
            embed['description'] = 'Sin contenido adicional'
        
        # Truncar descripción si es muy larga
        if len(embed['description']) > 4000:
            embed['description'] = embed['description'][:3997] + "..."
        
        # Limpiar campos
        if 'fields' in embed and isinstance(embed['fields'], list):
            campos_limpios = []
            for campo in embed['fields']:
                nombre = (campo.get('name') or '').strip()
                valor = (campo.get('value') or '').strip()
                if nombre and valor and len(nombre) <= 256:
                    if len(valor) > 1024:
                        valor = valor[:1021] + "..."
                    campos_limpios.append({
                        'name': nombre,
                        'value': valor,
                        'inline': campo.get('inline', True)
                    })
            embed['fields'] = campos_limpios
        else:
            embed.pop('fields', None)
        
        try:
            data = {'embeds': [embed]}
            response = requests.post(self.discord_webhook, json=data, timeout=5)
            if response.status_code not in [200, 204]:
                self.logger.warning(f"Discord error: {response.status_code}")
        except Exception as e:
            self.logger.error(f"Error Discord: {e}")

    def _escape_markdown(self, texto: str) -> str:
        """Escapa caracteres especiales de Markdown."""
        chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for c in chars:
            texto = texto.replace(c, f'\\{c}')
        return texto

    def _enviar_telegram(self, mensaje: str, tipo: str = 'info', 
                         titulo: str = None, campos: List[Dict] = None):
        """Envía mensaje a Telegram."""
        emojis = {
            'exito': '✅', 'error': '❌', 'alerta': '⚠️', 'info': 'ℹ️',
            'operacion': '📈', 'cierre': '📊', 'heartbeat': '💓',
            'sniper': '🎯', 'pipeline': '📊', 'rechazo': '⛔', 'estado': '📊'
        }
        emoji = emojis.get(tipo, '📊')

        titulo_escapado = self._escape_markdown(titulo or 'Bot Pepperstone')
        mensaje_escapado = self._escape_markdown(mensaje)

        texto = f"{emoji} *{titulo_escapado}*\n\n{mensaje_escapado}"
        
        if campos:
            for c in campos:
                nombre = self._escape_markdown(c.get('name', ''))
                valor = self._escape_markdown(str(c.get('value', '')))
                if nombre and valor:
                    texto += f"\n• *{nombre}:* {valor}"

        if len(texto) > 4096:
            texto = texto[:4093] + "..."

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        data = {
            'chat_id': self.telegram_chat,
            'text': texto,
            'parse_mode': 'Markdown'
        }
        requests.post(url, json=data, timeout=5)

    def enviar(self, mensaje: str, titulo: str = None, tipo: str = 'info',
               campos: List[Dict] = None, color: int = None, footer: str = None):
        """Envía una notificación a la cola."""
        if not mensaje and not titulo:
            return
        self.queue.put((mensaje, {
            'tipo': tipo, 'titulo': titulo, 'campos': campos,
            'color': color, 'footer': footer
        }))

    def enviar_urgente(self, mensaje: str, titulo: str = None, tipo: str = 'error',
                       campos: List[Dict] = None, color: int = None, footer: str = None):
        """Envía una notificación urgente (fuera de la cola)."""
        try:
            self._enviar_mensaje(mensaje, tipo, titulo, campos, color, footer)
        except Exception as e:
            self.logger.error(f"Error enviando mensaje urgente: {e}")

    def esperar_finalizacion(self, timeout: float = 10.0):
        """Espera a que la cola se vacíe."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.queue.empty():
                break
            time.sleep(0.1)

    def desactivar(self, timeout: float = 5.0):
        """Desactiva el sistema de notificaciones."""
        self.running = False
        self.esperar_finalizacion(timeout=timeout)
        self.thread.join(timeout=timeout)
        self.logger.info("🛑 Notificaciones desactivadas")

    # ============================================================
    # ESTADÍSTICAS
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas de uso."""
        stats = self._stats.copy()
        
        # Calcular tasa de éxito
        total_discord = stats['discord_exitosos'] + stats['discord_fallidos']
        total_telegram = stats['telegram_exitosos'] + stats['telegram_fallidos']
        
        stats['discord_tasa_exito'] = (stats['discord_exitosos'] / total_discord * 100) if total_discord > 0 else 0
        stats['telegram_tasa_exito'] = (stats['telegram_exitosos'] / total_telegram * 100) if total_telegram > 0 else 0
        
        return stats

    # ============================================================
    # COMANDOS REMOTOS
    # ============================================================

    def procesar_comando(self, mensaje: str) -> str:
        """Procesa un comando remoto."""
        if not self.comando_callback:
            return "⚠️ El bot no ha registrado el callback de comandos."

        mensaje = mensaje.strip()
        if not mensaje.startswith('!'):
            return "ℹ️ Los comandos deben empezar con `!`"

        comando = mensaje[1:].strip().lower()
        self._stats['comandos_procesados'] += 1

        try:
            if comando in ('estado', 'e'):
                return self.comando_callback('estado') or "✅ Comando ejecutado."
            elif comando in ('stats', 's'):
                return self.comando_callback('stats') or "✅ Comando ejecutado."
            elif comando == 'cot':
                return self.comando_callback('cot') or "✅ Comando ejecutado."
            elif comando in ('analisis', 'a'):
                return self.comando_callback('analisis') or "✅ Comando ejecutado."
            elif comando in ('outlook', 'o'):
                return self.comando_callback('outlook') or "✅ Comando ejecutado."
            elif comando.startswith('close'):
                partes = comando.split()
                if len(partes) >= 2:
                    if partes[1] == 'all':
                        return self.comando_callback('close_all') or "✅ Comando ejecutado."
                    else:
                        return self.comando_callback(f'close {partes[1]}') or "✅ Comando ejecutado."
                return "❌ Especifica '!close all' o '!close EURUSD'"
            elif comando == 'log':
                return self.comando_callback('log') or "✅ Comando ejecutado."
            elif comando in ('dashboard', 'd'):
                return self.comando_callback('dashboard') or "✅ Comando ejecutado."
            else:
                return f"❌ Comando desconocido: `{comando}`"
        except Exception as e:
            self.logger.error(f"Error procesando comando {comando}: {e}")
            return f"❌ Error al ejecutar comando: {e}"

    # ============================================================
    # MÉTODOS DE NOTIFICACIÓN (MANTENIDOS)
    # ============================================================

    def notificar_error_critico(self, error: Exception, contexto: str = ""):
        """Notifica un error crítico."""
        pid = os.getpid()
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        mensaje = (
            f"**Excepción fatal:**\n"
            f"```\n{str(error)[:500]}\n```\n"
            f"**PID:** {pid}\n"
            f"**Hora:** {timestamp}\n"
        )
        if contexto:
            mensaje += f"**Contexto:** {contexto}\n"
        self.enviar(mensaje, titulo="💥 ERROR CRÍTICO", tipo='error')

    def notificar_operacion(self, op: Dict[str, Any]):
        """Notifica una nueva operación."""
        try:
            simbolo = op.get('simbolo', '')
            direccion = op.get('direccion', '')
            entrada = op.get('entrada', 0)
            sl = op.get('stop_loss', 0)
            tp = op.get('take_profit', 0)
            lotes = op.get('lotes', 0)
            score = op.get('probabilidad', 0)
            patron = op.get('patron', 'N/A')
            es_sniper = op.get('es_sniper', False)

            emoji_dir = '🟢' if direccion == 'COMPRA' else '🔴'
            sniper_tag = '🎯 **SNIPER**' if es_sniper else '📊 **SETUP**'

            campos = [
                {'name': '📊 Par', 'value': f'**{simbolo}**', 'inline': True},
                {'name': '📈 Dirección', 'value': f'{emoji_dir} **{direccion}**', 'inline': True},
                {'name': '💰 Entrada', 'value': f'`{entrada:.5f}`', 'inline': True},
                {'name': '🛑 SL', 'value': f'`{sl:.5f}`', 'inline': True},
                {'name': '🎯 TP', 'value': f'`{tp:.5f}`', 'inline': True},
                {'name': '📦 Lotes', 'value': f'`{lotes:.2f}`', 'inline': True},
                {'name': '🎯 Score', 'value': f'`{score:.1f}`', 'inline': True},
                {'name': '📊 Patrón', 'value': f'`{patron}`', 'inline': True},
            ]

            self.enviar(
                mensaje=f"{sniper_tag}\nOperación ejecutada en **{simbolo}**",
                titulo=f"{emoji_dir} {direccion} en {simbolo}",
                tipo='sniper' if es_sniper else 'operacion',
                campos=campos
            )
        except Exception as e:
            self.logger.error(f"Error en notificar_operacion: {e}")

    def notificar_cierre(self, op: Dict[str, Any]):
        """Notifica el cierre de una operación."""
        try:
            simbolo = op.get('simbolo', '')
            ganancia = op.get('ganancia', 0)
            motivo = op.get('motivo_cierre', 'N/A')

            emoji = '🟢' if ganancia > 0 else '🔴'
            estado = '✅ GANANCIA' if ganancia > 0 else '❌ PÉRDIDA'

            self.enviar(
                mensaje=f"Operación cerrada en **{simbolo}**\nPnL: `${ganancia:+.2f}`\nMotivo: `{motivo}`",
                titulo=f"{emoji} {estado} en {simbolo}",
                tipo='exito' if ganancia > 0 else 'error',
                campos=[
                    {'name': '📊 Par', 'value': f'**{simbolo}**', 'inline': True},
                    {'name': '💰 PnL', 'value': f'`${ganancia:+.2f}`', 'inline': True},
                    {'name': '📋 Motivo', 'value': f'`{motivo}`', 'inline': True},
                ]
            )
        except Exception as e:
            self.logger.error(f"Error en notificar_cierre: {e}")

    def notificar_escaneo(self, analisis_list: List[Dict[str, Any]]):
        """Notifica resultados de escaneo."""
        if not analisis_list:
            return
        top = sorted(analisis_list, key=lambda x: x.get('puntuacion_final', 0), reverse=True)[:5]
        mensaje = "**Top 5 oportunidades detectadas:**\n\n"
        for i, item in enumerate(top, 1):
            simb = item.get('simbolo', '?')
            score = item.get('puntuacion_final', 0)
            direc = item.get('direccion', 'NEUTRAL')
            mensaje += f"{i}. **{simb}** → {direc} | Score: `{score:.1f}`\n"
        self.enviar(mensaje, titulo="🔍 Escaneo de Oportunidades", tipo='pipeline')

    def notificar_heartbeat(self, stats: Dict[str, Any]):
        """Notifica heartbeat del bot."""
        capital = stats.get('capital_actual', 0)
        ops_hoy = stats.get('ops_hoy', 0)
        ganancia_hoy = stats.get('ganancia_hoy', 0)
        n_pos = stats.get('n_posiciones', 0)
        modo = stats.get('modo', 'NORMAL')
        cpu = stats.get('cpu', 0)
        ram = stats.get('ram', 0)

        mensaje = (
            f"**Capital:** ${capital:,.2f}\n"
            f"**Operaciones hoy:** {ops_hoy}\n"
            f"**PnL diario:** ${ganancia_hoy:+,.2f}\n"
            f"**Posiciones abiertas:** {n_pos}\n"
            f"**Modo noticias:** {modo}\n"
            f"**CPU:** {cpu:.1f}% | **RAM:** {ram:.1f}%"
        )
        tipo = 'alerta' if cpu > 80 or ram > 85 else 'heartbeat'
        self.enviar(mensaje, titulo="💓 Heartbeat del Bot", tipo=tipo)

    def notificar_resumen(self, stats: Dict[str, Any]):
        """Notifica resumen de sesión."""
        capital = stats.get('capital_actual', 0)
        pnl_hoy = stats.get('ganancia_diaria', 0) - stats.get('perdida_diaria', 0)
        ops_hoy = stats.get('operaciones_hoy', 0)
        win_rate = stats.get('win_rate', 0)
        total_ops = stats.get('total_operaciones', 0)

        mensaje = (
            f"**Capital actual:** ${capital:,.2f}\n"
            f"**PnL de hoy:** ${pnl_hoy:+,.2f}\n"
            f"**Operaciones hoy:** {ops_hoy}\n"
            f"**Win Rate global:** {win_rate:.1f}%\n"
            f"**Total operaciones:** {total_ops}"
        )
        self.enviar(mensaje, titulo="📊 Resumen de Sesión", tipo='info')

    def notificar_aporte(self, monto: float, capital_nuevo: float):
        """Notifica aporte mensual."""
        self.enviar(
            f"**Aporte mensual procesado:** +${monto:,.2f}\n"
            f"**Capital actualizado:** ${capital_nuevo:,.2f}",
            titulo="💰 Aporte Mensual",
            tipo='exito'
        )

    def notificar_estado_completo(self, bot):
        """Notifica estado completo del bot."""
        try:
            gestion = getattr(bot, 'gestion', None)
            if gestion:
                stats = gestion.estadisticas() if hasattr(gestion, 'estadisticas') else {}
            else:
                stats = {}
            
            capital = stats.get('capital_actual', 0)
            pnl_hoy = stats.get('ganancia_diaria', 0) - stats.get('perdida_diaria', 0)
            win_rate = stats.get('win_rate', 0)
            total_ops = stats.get('total_operaciones', 0)
            
            etapa = gestion.obtener_etapa_actual() if gestion else 1
            
            pos_texto = "📭 Sin posiciones abiertas"
            try:
                mt5 = getattr(bot, 'mt5', None)
                if mt5 and hasattr(mt5, 'obtener_posiciones'):
                    pos = mt5.obtener_posiciones()
                    if pos:
                        pos_lines = []
                        for p in pos[:5]:
                            pnl = p.get('ganancia', 0)
                            emoji = "🟢" if pnl > 0 else "🔴"
                            pos_lines.append(f"{emoji} {p['simbolo']} | {p['tipo']} | ${pnl:+.2f}")
                        pos_texto = "\n".join(pos_lines)
            except Exception:
                pass
            
            watchlist_texto = "📭 Watchlist vacía"
            try:
                watchlist = getattr(bot, 'watchlist', {})
                if watchlist:
                    watchlist_lines = []
                    for s in list(watchlist.keys())[:8]:
                        watchlist_lines.append(f"• {s}")
                    watchlist_texto = "\n".join(watchlist_lines)
            except Exception:
                pass
            
            modo = getattr(bot, 'modo_noticias', 'NORMAL')

            campos = [
                {'name': '💰 Capital', 'value': f"${capital:,.2f}", 'inline': True},
                {'name': '📊 PnL Hoy', 'value': f"${pnl_hoy:+,.2f}", 'inline': True},
                {'name': '🎯 Win Rate', 'value': f"{win_rate:.1f}%", 'inline': True},
                {'name': '📈 Posiciones Abiertas', 'value': pos_texto, 'inline': False},
                {'name': '📋 Watchlist', 'value': watchlist_texto, 'inline': False},
                {'name': '⏱️ Modo', 'value': f"{modo} | Etapa {etapa}", 'inline': True},
            ]

            self.enviar(
                mensaje="**Estado completo del bot**",
                titulo="📊 Dashboard",
                tipo='estado',
                campos=campos
            )
        except Exception as e:
            self.logger.error(f"Error en notificar_estado_completo: {e}")