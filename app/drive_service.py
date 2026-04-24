# app/drive_service.py
import os
import base64
import hashlib
import secrets
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# Configuración
SCOPES = ['https://www.googleapis.com/auth/drive.file']
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'https://gestor-expedientes-nine.vercel.app/oauth2callback')

def get_auth_url():
    """Genera URL de autorización con PKCE"""
    # Generar PKCE verifier
    code_verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).decode('utf-8').rstrip('=')
    
    # Generar challenge
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    
    # Crear flujo OAuth con PKCE
    client_config = {
        "web": {
            "client_id": os.environ.get('GOOGLE_CLIENT_ID'),
            "client_secret": os.environ.get('GOOGLE_CLIENT_SECRET'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI]
        }
    }
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    # Construir URL de autorización con PKCE
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        code_challenge=code_challenge,
        code_challenge_method='S256'
    )
    
    # ← FORZAR retorno como diccionario explícito
    resultado = {
        'url': str(auth_url),
        'state': str(state),
        'code_verifier': str(code_verifier)
    }
    
    return resultado

def exchange_code(code, code_verifier):
    """Intercambia código por token usando PKCE verifier"""
    client_config = {
        "web": {
            "client_id": os.environ.get('GOOGLE_CLIENT_ID'),
            "client_secret": os.environ.get('GOOGLE_CLIENT_SECRET'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI]
        }
    }
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    # Intercambiar código con verifier
    flow.fetch_token(
        code=code,
        code_verifier=code_verifier
    )
    
    credentials = flow.credentials
    
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': list(credentials.scopes)
    }

def get_drive_service(credentials_dict):
    """Crea servicio de Drive desde credenciales guardadas"""
    from google.oauth2.credentials import Credentials
    
    creds = Credentials(
        token=credentials_dict['token'],
        refresh_token=credentials_dict.get('refresh_token'),
        token_uri=credentials_dict['token_uri'],
        client_id=credentials_dict['client_id'],
        client_secret=credentials_dict['client_secret'],
        scopes=credentials_dict['scopes']
    )
    
    # Refrescar si expiró
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    
    return build('drive', 'v3', credentials=creds)

def subir_archivo(service, file_content, filename, mime_type='application/pdf'):
    """Sube archivo a Google Drive"""
    from googleapiclient.http import MediaIoBaseUpload
    import io
    
    file_metadata = {'name': filename}
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
        'url': file.get('webViewLink', f"https://drive.google.com/file/d/{file['id']}/view")
    }

def eliminar_archivo(service, file_id):
    """Elimina archivo de Google Drive"""
    service.files().delete(fileId=file_id).execute()
    return True

def obtener_espacio_usado(service):
    """Obtiene información de espacio en Drive"""
    about = service.about().get(fields='storageQuota').execute()
    quota = about['storageQuota']
    
    usado = int(quota.get('usage', 0))
    total = int(quota.get('limit', 15 * 1024**3))  # 15GB default
    
    return {
        'usado_bytes': usado,
        'total_bytes': total,
        'libre_bytes': total - usado,
        'porcentaje': (usado / total) * 100 if total > 0 else 0
    }

def descargar_archivo(service, file_id):
    """Descarga archivo de Google Drive"""
    request = service.files().get_media(fileId=file_id)
    
    from googleapiclient.http import MediaIoBaseDownload
    import io
    
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
    
    return fh.getvalue()