# app/drive_service_account.py
# Subida directa al Drive corporativo SIN login de usuario
# Usa Service Account - todos los documentos van al mismo Drive

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError
import io
import os
import json

# ============================================
# CONFIGURACIÓN - DATOS CONFIRMADOS POR USUARIO
# ============================================

# ID de la carpeta compartida en Drive del estudio
DRIVE_FOLDER_ID = "1onwHI6s26r3FPzpclFYGoWRAGY77nZX2"

# Email del Service Account
SERVICE_ACCOUNT_EMAIL = "quijandria-drive-service@direct-volt-494302-h1.iam.gserviceaccount.com"

SCOPES = ['https://www.googleapis.com/auth/drive']


def get_drive_service_account():
    """
    Crea servicio de Drive usando cuenta de servicio (robot).
    NO requiere que ningún usuario inicie sesión.
    """
    credentials_info = None
    
    # Opción 1: Variables de entorno (Vercel/Producción)
    creds_env = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if creds_env:
        credentials_info = json.loads(creds_env)
    else:
        # Opción 2: Archivo local (desarrollo)
        creds_path = os.path.join(os.path.dirname(__file__), '..', 'service-account.json')
        if os.path.exists(creds_path):
            with open(creds_path, 'r') as f:
                credentials_info = json.load(f)
        else:
            raise Exception(
                "No se encontró configuración de Service Account. "
                "Configura GOOGLE_SERVICE_ACCOUNT_JSON en variables de entorno "
                "o coloca service-account.json en la raíz del proyecto."
            )
    
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=SCOPES
    )
    
    service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
    return service


def subir_archivo_drive(file_content, filename, mime_type='application/pdf'):
    """
    Sube archivo DIRECTAMENTE al Drive corporativo del estudio.
    SOLUCIÓN ALTERNATIVA: Usa upload simple en lugar de resumable para evitar error 403.
    """
    try:
        service = get_drive_service_account()
        
        file_metadata = {
            'name': filename,
            'parents': [DRIVE_FOLDER_ID]
        }
        
        # SOLUCIÓN: Usar MediaIoBaseUpload SIN resumable (upload simple)
        # El parámetro resumable=True causa el error 403 en Service Accounts sin Drive propio
        media = MediaIoBaseUpload(
            io.BytesIO(file_content),
            mimetype=mime_type,
            resumable=False  # <-- CAMBIO CLAVE: upload simple
        )
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, webContentLink'
        ).execute()
        
        return {
            'id': file['id'],
            'url': file.get('webViewLink', f"https://drive.google.com/file/d/{file['id']}/view"),
            'download_url': file.get('webContentLink')
        }
        
    except HttpError as e:
        error_msg = str(e)
        if "storageQuotaExceeded" in error_msg:
            raise Exception(
                f"Error 403 - Storage Quota: La cuenta de servicio no tiene espacio propio. "
                f"Verifique que la carpeta {DRIVE_FOLDER_ID} esté compartida como EDITOR. "
                f"Error original: {error_msg}"
            )
        raise Exception(f"Error de Google Drive ({e.resp.status}): {error_msg}")
    except Exception as e:
        raise Exception(f"Error subiendo a Drive: {str(e)}")


def subir_archivo_drive_resumable(file_content, filename, mime_type='application/pdf'):
    """
    MÉTODO ALTERNATIVO para archivos grandes (>5MB).
    Si el simple upload falla, intenta con resumable pero con manejo especial.
    """
    try:
        service = get_drive_service_account()
        
        file_metadata = {
            'name': filename,
            'parents': [DRIVE_FOLDER_ID]
        }
        
        # Para resumable, necesitamos que la cuenta de servicio tenga un "espacio"
        # Solución: Crear el archivo primero SIN contenido, luego subir el contenido
        # Paso 1: Crear archivo vacío
        file = service.files().create(
            body=file_metadata,
            fields='id'
        ).execute()
        
        file_id = file['id']
        
        # Paso 2: Subir contenido al archivo existente
        media = MediaIoBaseUpload(
            io.BytesIO(file_content),
            mimetype=mime_type,
            resumable=True
        )
        
        # Usar update en lugar de create
        updated = service.files().update(
            fileId=file_id,
            media_body=media,
            fields='id, webViewLink, webContentLink'
        ).execute()
        
        return {
            'id': updated['id'],
            'url': updated.get('webViewLink', f"https://drive.google.com/file/d/{updated['id']}/view"),
            'download_url': updated.get('webContentLink')
        }
        
    except Exception as e:
        raise Exception(f"Error en upload resumable: {str(e)}")


def eliminar_archivo_drive(file_id):
    """Elimina archivo del Drive corporativo"""
    service = get_drive_service_account()
    service.files().delete(fileId=file_id).execute()
    return True


def obtener_espacio_usado_drive():
    """Obtiene espacio usado estimado en la carpeta del estudio"""
    service = get_drive_service_account()
    
    results = service.files().list(
        q=f"'{DRIVE_FOLDER_ID}' in parents and trashed=false",
        fields='files(id, size, name)'
    ).execute()
    
    archivos = results.get('files', [])
    total_bytes = sum(int(f.get('size', 0)) for f in archivos)
    
    # Drive de cuenta de servicio = 15GB gratis
    total_gb = 15
    usado_gb = total_bytes / (1024**3)
    porcentaje = (usado_gb / total_gb) * 100
    
    return {
        'usado_gb': usado_gb,
        'total_gb': total_gb,
        'porcentaje': porcentaje,
        'archivos_count': len(archivos)
    }


def descargar_archivo_drive(file_id):
    """Descarga archivo del Drive corporativo"""
    service = get_drive_service_account()
    
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
    
    return fh.getvalue()