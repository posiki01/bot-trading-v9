import pandas as pd
import requests
import os
import sys
from datetime import datetime, timezone, timedelta
from colorama import Fore, Style, init

# Añadir el directorio raíz al path para importar la configuración
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.settings import Config

init(autoreset=True)

def descargar_noticias_historia(meses_atras=6):
    """
    Descarga noticias históricas específicas por símbolo (Company News)
    que permiten filtrar por fechas desde Finnhub y las acumula en el CSV.
    """
    api_key = getattr(Config, 'FINNHUB_API_KEY', None)
    
    if not api_key:
        print(f"{Fore.RED}❌ Error: No se encontró FINNHUB_API_KEY en la configuración.{Style.RESET_ALL}")
        return

    # Definir rango de fechas para el pasado
    fecha_fin = datetime.now(timezone.utc)
    fecha_inicio = fecha_fin - timedelta(days=meses_atras * 30)
    
    fmt_api = "%Y-%m-%d"
    f_from = fecha_inicio.strftime(fmt_api)
    f_to = fecha_fin.strftime(fmt_api)

    print(f"{Fore.CYAN}📥 Viajando al pasado: Descargando noticias desde {f_from} hasta {f_to}...{Style.RESET_ALL}")
    
    # Símbolos para consultar (Majors + Cripto + Índices traducidos a formato Finnhub)
    # AMPLIADO: Incluimos más símbolos para cubrir la expansión de Etapa 1
    simbolos_consulta = [
        "AAPL", "TSLA", "BTC", "ETH", "EUR", "USD", "GBP", "JPY", "GOLD", 
        "AUD", "CAD", "CHF", "SPY", "QQQ"
    ]
    noticias_finales = []

    for sym in simbolos_consulta:
        print(f"   🔎 Trayendo historial para: {Fore.YELLOW}{sym}{Style.RESET_ALL}...")
        # Endpoint de Company News que SÍ soporta fechas
        url = f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={f_from}&to={f_to}&token={api_key}"
        
        try:
            response = requests.get(url, timeout=20)
            if response.status_code == 200:
                data = response.json()
                conteo_sym = 0
                for item in data:
                    dt = datetime.fromtimestamp(item['datetime'], tz=timezone.utc)
                    # Solo guardamos si tiene contenido relevante
                    if len(item.get('headline', '')) > 10:
                        noticias_finales.append({
                            'fecha': dt.strftime('%Y-%m-%d %H:%M:%S'),
                            'titulo': item.get('headline', ''),
                            'texto': item.get('summary', '')
                        })
                        conteo_sym += 1
                print(f"      ✅ {conteo_sym} noticias encontradas.")
                
            elif response.status_code == 429:
                print(f"{Fore.RED}      ⚠️ Límite de API alcanzado. Abortando para evitar baneo...{Style.RESET_ALL}")
                break
            else:
                print(f"{Fore.RED}      ❌ Error {response.status_code} en {sym}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}      ❌ Error de conexión: {e}{Style.RESET_ALL}")

    if noticias_finales:
        # Asegurar que la carpeta data existe
        os.makedirs('data', exist_ok=True)
        ruta_csv = os.path.join('data', 'noticias_historia.csv')
        
        # NUEVA LÓGICA: Acumular en lugar de sobrescribir
        df_nuevas = pd.DataFrame(noticias_finales)
        
        if os.path.exists(ruta_csv):
            # Leer lo que ya tenemos
            df_existente = pd.read_csv(ruta_csv)
            # Combinar
            df_total = pd.concat([df_existente, df_nuevas], ignore_index=True)
            print(f"   🔄 Combinando con {len(df_existente)} noticias previas...")
        else:
            df_total = df_nuevas

        # Limpiar: Eliminar duplicados por título y ordenar por fecha
        total_antes = len(df_total)
        df_total['fecha'] = pd.to_datetime(df_total['fecha'])
        df_total.drop_duplicates(subset=['titulo'], inplace=True)
        df_total.sort_values(by='fecha', ascending=True, inplace=True)
        
        # Guardar la base de datos actualizada
        df_total.to_csv(ruta_csv, index=False, encoding='utf-8')
        
        nuevas_reales = len(df_total) - (total_antes if os.path.exists(ruta_csv) else 0)
        
        print(f"\n{Fore.GREEN}✨ PROCESO COMPLETADO{Style.RESET_ALL}")
        print(f"� Archivo actualizado: {Fore.WHITE}{ruta_csv}{Style.RESET_ALL}")
        print(f"� Nuevas noticias añadidas: {Fore.CYAN}{max(0, nuevas_reales)}{Style.RESET_ALL}")
        print(f"📊 Base de datos total: {Fore.YELLOW}{len(df_total)} noticias{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ No se pudo descargar ninguna noticia.{Style.RESET_ALL}")

if __name__ == "__main__":
    try:
        meses = input("📅 ¿Cuántos meses de historia quieres descargar? (Default 6): ").strip()
        n_meses = int(meses) if meses else 6
        descargar_noticias_historia(n_meses)
    except ValueError:
        descargar_noticias_historia(6)