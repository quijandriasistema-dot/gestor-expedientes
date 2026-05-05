# app/drive_service_account.py
# Subida al Drive corporativo usando OAuth 2.0 con cuenta central
# Todos los usuarios suben a quijandria.sistema@gmail.com

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import io
import os
import json

# ============================================
# CONFIGURACIÓN
# ============================================

# ID de la carpeta Expedientes_Legales en Drive
DRIVE_FOLDER_ID = "1onwHI6s26r3FPzpclFYGoWRAGY77nZX2"

# Email de la cuenta corporativa
DRIVE_ACCOUNT_EMAIL = "quijandria.sistema@gmail.com"

SCOPES = ['https://www.googleapis.com/auth/drive']


def get_drive_credentials():
    """
    Crea credenciales OAuth 2.0 desde el refresh_token guardado en Vercel.
    NO requiere que ningún usuario inicie sesión con Google.
    """
    # Obtener valores de variables de entorno (Vercel)
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    refresh_token = os.environ.get('GOOGLE_REFRESH_TOKEN')
    
    # Validar que existan todas las variables
    if not all([client_id, client_secret, refresh_token]):
        raise Exception(
            "Faltan variables de entorno de Google OAuth. "
            "Configura GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET y GOOGLE_REFRESH_TOKEN en Vercel."
        )
    
    # Crear credenciales desde refresh_token
    creds = Credentials(
        token=None,  # Se refresca automáticamente
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES
    )
    
    # Refrescar el token (obtener access_token nuevo)
    creds.refresh(Request())
    
    return creds


def get_drive_service():
    """Crea servicio de Drive con credenciales OAuth 2.0"""
    creds = get_drive_credentials()
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    return service


def subir_archivo_drive(file_content, filename, mime_type='application/pdf'):
    """
    Sube archivo al Drive corporativo (quijandria.sistema@gmail.com).
    """
    try:
        service = get_drive_service()
        
        file_metadata = {
            'name': filename,
            'parents': [DRIVE_FOLDER_ID]
        }
        
        media = MediaIoBaseUpload(
            io.BytesIO(file_content),
            mimetype=mime_type,
            resumable=False  # Upload simple para evitar problemas
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
        if e.resp.status == 403:
            raise Exception(
                f"Error 403: La cuenta {DRIVE_ACCOUNT_EMAIL} no tiene permisos sobre la carpeta. "
                f"Verifica que la carpeta {DRIVE_FOLDER_ID} esté compartida con {DRIVE_ACCOUNT_EMAIL} como EDITOR. "
                f"Error original: {error_msg}"
            )
        raise Exception(f"Error de Google Drive ({e.resp.status}): {error_msg}")
    except Exception as e:
        raise Exception(f"Error subiendo a Drive: {str(e)}")


def eliminar_archivo_drive(file_id):
    """Elimina archivo del Drive corporativo"""
    service = get_drive_service()
    service.files().delete(fileId=file_id).execute()
    return True


def obtener_espacio_usado_drive():
    """Obtiene espacio usado en la cuenta de Google Drive"""
    try:
        service = get_drive_service()
        
        # Obtener quota de la cuenta
        about = service.about().get(fields="storageQuota").execute()
        quota = about.get('storageQuota', {})
        
        usage = int(quota.get('usage', 0))
        limit = int(quota.get('limit', 16106127360))  # 15GB por defecto
        
        usado_gb = usage / (1024**3)
        total_gb = limit / (1024**3)
        porcentaje = (usage / limit) * 100 if limit > 0 else 0
        
        return {
            'usado_gb': round(usado_gb, 2),
            'total_gb': round(total_gb, 2),
            'porcentaje': round(porcentaje, 1),
            'archivos_count': None  # No aplicable para quota general
        }
        
    except Exception as e:
        print(f"Error obteniendo espacio Drive: {e}")
        return {
            'usado_gb': 0.0,
            'total_gb': 15.0,
            'porcentaje': 0.0,
            'archivos_count': None
        }


def descargar_archivo_drive(file_id):
    """Descarga archivo del Drive corporativo"""
    service = get_drive_service()
    
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
    
    return fh.getvalue()