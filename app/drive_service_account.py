# app/drive_service_account.py
# Subida directa al Drive corporativo SIN login de usuario
# Usa Service Account - todos los documentos van al mismo Drive

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
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
    
    service = build('drive', 'v3', credentials=credentials)
    return service


def subir_archivo_drive(file_content, filename, mime_type='application/pdf'):
    """
    Sube archivo DIRECTAMENTE al Drive corporativo del estudio.
    """
    service = get_drive_service_account()
    
    file_metadata = {
        'name': filename,
        'parents': [DRIVE_FOLDER_ID]
    }
    
    media = MediaIoBaseUpload(
        io.BytesIO(file_content),
        mimetype=mime_type,
        resumable=True
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