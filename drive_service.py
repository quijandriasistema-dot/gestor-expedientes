import os
import io
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', 'https://gestor-expedientes-nine.vercel.app/oauth2callback')

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive.readonly'
]

CLIENT_CONFIG = {
    "web": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT_URI]
    }
}

def get_auth_url():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("Faltan variables de entorno GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET")
    
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    return auth_url

def exchange_code(code):
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    flow.fetch_token(code=code)
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
    credentials = Credentials(
        token=credentials_dict['token'],
        refresh_token=credentials_dict.get('refresh_token'),
        token_uri=credentials_dict['token_uri'],
        client_id=credentials_dict['client_id'],
        client_secret=credentials_dict['client_secret'],
        scopes=credentials_dict['scopes']
    )
    return build('drive', 'v3', credentials=credentials)

def subir_archivo(service, file_content, filename, mime_type, folder_id=None):
    file_metadata = {'name': filename}
    if folder_id:
        file_metadata['parents'] = [folder_id]
    
    media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=mime_type, resumable=True)
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink, webContentLink'
    ).execute()
    
    return {
        'id': file.get('id'),
        'url': file.get('webViewLink'),
        'download_url': file.get('webContentLink')
    }

def eliminar_archivo(service, file_id):
    try:
        service.files().delete(fileId=file_id).execute()
        return True
    except Exception as e:
        print(f"Error eliminando archivo de Drive: {e}")
        return False

def obtener_espacio_usado(service):
    try:
        about = service.about().get(fields='storageQuota').execute()
        quota = about.get('storageQuota', {})
        
        limit = int(quota.get('limit', 15 * 1024**3))
        usage = int(quota.get('usage', 0))
        usage_in_drive = int(quota.get('usageInDrive', usage))
        
        return {
            'limite_gb': limit / (1024**3),
            'usado_gb': usage_in_drive / (1024**3),
            'porcentaje': (usage_in_drive / limit * 100) if limit > 0 else 0
        }
    except Exception as e:
        print(f"Error obteniendo espacio: {e}")
        return {
            'limite_gb': 15,
            'usado_gb': 0,
            'porcentaje': 0
        }

def descargar_archivo(service, file_id):
    try:
        request = service.files().get_media(fileId=file_id)
        file_content = io.BytesIO()
        downloader = MediaIoBaseDownload(file_content, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        return file_content.getvalue()
    except Exception as e:
        print(f"Error descargando archivo: {e}")
        return None