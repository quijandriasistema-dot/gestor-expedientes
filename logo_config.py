import base64
import io
import os
from reportlab.lib.utils import ImageReader

LOGO_PATH = os.path.join(os.path.dirname(__file__), 'app', 'static', 'images', 'logo-quijandria.png')

def get_logo_image():
    if not os.path.exists(LOGO_PATH):
        print(f"⚠️ Logo no encontrado en: {LOGO_PATH}")
        return None
    
    try:
        with open(LOGO_PATH, 'rb') as f:
            img_data = f.read()
        return ImageReader(io.BytesIO(img_data))
    except Exception as e:
        print(f"❌ Error cargando logo: {e}")
        return None

def get_logo_base64():
    if not os.path.exists(LOGO_PATH):
        return None
    
    try:
        with open(LOGO_PATH, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        print(f"❌ Error convirtiendo logo: {e}")
        return None