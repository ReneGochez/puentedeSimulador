import os
import json
import shutil
import logging
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from datetime import datetime

# ++++++++++++++++++++++++++++++++++++++++++
# CONFIGURACIÓN INICIAL Y CONSTANTES
# ++++++++++++++++++++++++++++++++++++++++++

# Directorios de trabajo (si no tan se crean)
DIR_ENTRADA = './entrada_json'
DIR_EXITO = './procesados_exitosos'
DIR_ERROR = './procesados_fallidos' 

# Config. Firebase
# OJO HAY OJON:  Pon la ruta real nuestra llave privada

RUTA_CREDENCIALES = 'serviceAccountKey.json' 
COLECCION_DB = 'lecturas' # Nombre colección Firestore

# Configuración del Logger (Bitácora de eventos)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ++++++++++++++++++++++++++++++++++++++++++
# FUNCIONES AUXI (LOG DEL NEGOCIO)
# ++++++++++++++++++++++++++++++++++++++++++

def iniciar_firestore():
    """
    Inicializa la conexión con Google Cloud Firestore.
    Patrón Singleton: Verifica si ya existe la app para no reinicializarla.
    """
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(RUTA_CREDENCIALES)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        logger.critical(f"Error fatal conectando a Firebase: {e}")
        exit(1)

def obtener_nombre_por_fecha(datos_json, nombre_original):
    """
    Genera el nuevo nombre del archivo basado en campos 'fecha' y 'hora' dentro del JSON.
    """
    try:
        # NOTA: Ajusta las claves 'fecha' y 'hora' según como vengan en tus JSON reales.
        # Asumimos formato ISO o similar. 
        fecha = datos_json.get('fecha', 'sin_fecha')
        hora = datos_json.get('hora', 'sin_hora')
        
        # Combinamos para crear el nombre base
        nombre_base = f"{fecha}_{hora}"
        
        # Saneamiento: Reemplazamos : y / por guiones para que sea un nombre de archivo válido
        nombre_seguro = nombre_base.replace(':', '-').replace('/', '-').replace(' ', '_')
        
        # Retornamos nombre + extensión original
        return f"{nombre_seguro}.json"
    except Exception as e:
        logger.warning(f"No se pudo extraer fecha/hora para renombrar. Usando nombre original. Error: {e}")
        return nombre_original

def procesar_archivos():
    # 1. Conexión a Base de Datos
    logger.info("--- Iniciando proceso ETL (Extract, Transform, Load) ---")
    db = iniciar_firestore()

    # 2. Asegurar existencia de directorios
    for directorio in [DIR_ENTRADA, DIR_EXITO, DIR_ERROR]:
        if not os.path.exists(directorio):
            os.makedirs(directorio)
            logger.info(f"Directorio creado: {directorio}")

    # 3. Listar archivos en la carpeta de entrada
    archivos = [f for f in os.listdir(DIR_ENTRADA) if f.endswith('.json')]
    
    if not archivos:
        logger.info("No hay archivos .json pendientes en la carpeta de entrada.")
        return

    logger.info(f"Se encontraron {len(archivos)} archivos para procesar.")

    # 4. Iteración sobre cada archivo
    for archivo_nombre in archivos:
        ruta_completa = os.path.join(DIR_ENTRADA, archivo_nombre)
        logger.info(f"Procesando archivo: {archivo_nombre}")

        try:
            # ETAPA A: LECTURA DEL JSON
            # -------------------------------------------------
            with open(ruta_completa, 'r', encoding='utf-8') as f:
                datos = json.load(f)
            
            # ETAPA B: ESCRITURA EN FIRESTORE
            # -------------------------------------------------
            # Usamos add() para dejar que Firestore genere el ID del documento, 
            # o set() si quisieras usar un ID específico.
            # Agregamos metadata de auditoría (opcional pero recomendado)
            datos['_metadata_procesado'] = datetime.now().isoformat()
            datos['_metadata_archivo_origen'] = archivo_nombre
            
            db.collection(COLECCION_DB).add(datos)
            logger.info("-> Datos subidos exitosamente a Firestore.")

            # ETAPA C: RENOMBRADO Y MOVIMIENTO (ARCHIVO EXITOSO)
            # -------------------------------------------------
            # Calculamos el nuevo nombre basado en el contenido
            nuevo_nombre = obtener_nombre_por_fecha(datos, archivo_nombre)
            ruta_destino = os.path.join(DIR_EXITO, nuevo_nombre)

            # Lógica para evitar sobrescribir si ya existe un archivo con esa fecha exacta
            if os.path.exists(ruta_destino):
                timestamp_extra = datetime.now().strftime("%f") # Microsegundos para unicidad
                ruta_destino = os.path.join(DIR_EXITO, f"{nuevo_nombre.replace('.json', '')}_{timestamp_extra}.json")

            # Mover el archivo (shutil.move realiza copia + borrado del origen)
            shutil.move(ruta_completa, ruta_destino)
            logger.info(f"-> Archivo renombrado y movido a: {ruta_destino}")

        except json.JSONDecodeError:
            # Manejo específico si el JSON está mal formado
            logger.error(f"-> Error: El archivo {archivo_nombre} no es un JSON válido.")
            shutil.move(ruta_completa, os.path.join(DIR_ERROR, archivo_nombre))
            
        except Exception as e:
            # Manejo de errores generales (red, permisos, etc.)
            logger.error(f"-> Error procesando {archivo_nombre}: {e}")
            # Opcional: Mover a carpeta de errores para reintentar luego
            # shutil.move(ruta_completa, os.path.join(DIR_ERROR, archivo_nombre))

    logger.info("--- Proceso finalizado ---")

if __name__ == '__main__':
    procesar_archivos()