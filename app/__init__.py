from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    
    # ============================================
    # CONFIGURACIÓN
    # ============================================
    
    app.config['SECRET_KEY'] = 'tu-clave-secreta-aqui-2026-cambiar-en-produccion'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gestor_expedientes.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # ============================================
    # UPLOADS - Detectar Vercel
    # ============================================
    
    is_vercel = os.environ.get('VERCEL') == '1' or os.environ.get('VERCEL_ENV') is not None
    
    if is_vercel:
        # En Vercel: usar /tmp (única carpeta writable)
        app.config['UPLOAD_FOLDER'] = '/tmp/uploads/documentos'
    else:
        # En local: carpeta del proyecto
        app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads', 'documentos')
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    
    # ============================================
    # INICIALIZAR BASE DE DATOS
    # ============================================
    
    db.init_app(app)
    
    # ============================================
    # FILTROS JINJA2 SEGUROS PARA FECHAS
    # ============================================
    
    @app.template_filter('fecha')
    def fecha_filter(value, formato='%d/%m/%Y'):
        if value is None:
            return 'Sin fecha'
        return value.strftime(formato)
    
    @app.template_filter('hora')
    def hora_filter(value, formato='%H:%M'):
        if value is None:
            return '--:--'
        return value.strftime(formato)
    
    @app.template_filter('fecha_hora')
    def fecha_hora_filter(value, formato='%d/%m/%Y %H:%M'):
        if value is None:
            return 'Sin fecha'
        return value.strftime(formato)
    
    # ============================================
    # REGISTRAR RUTAS
    # ============================================
    
    from app.routes import bp as main_bp
    app.register_blueprint(main_bp)
    
    # ============================================
    # CREAR TABLAS AL INICIAR
    # ============================================
    
    with app.app_context():
        db.create_all()
    
    return app