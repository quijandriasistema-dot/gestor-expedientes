from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    
    # ============================================
    # DETECTAR ENTORNO: LOCAL vs VERCEL
    # ============================================
    IS_VERCEL = os.environ.get('VERCEL', False) or os.environ.get('VERCEL_ENV', False)
    
    # ============================================
    # CONFIGURACIÓN DE BASE DE DATOS
    # ============================================
    if IS_VERCEL:
        # PRODUCCIÓN (Vercel + Supabase PostgreSQL)
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            # SQLAlchemy 1.4+ requiere postgresql:// en lugar de postgres://
            if database_url.startswith('postgres://'):
                database_url = database_url.replace('postgres://', 'postgresql://', 1)
            app.config['SQLALCHEMY_DATABASE_URI'] = database_url
        else:
            raise ValueError("DATABASE_URL no está configurada en Vercel")
    else:
        # DESARROLLO LOCAL (SQLite)
        basedir = os.path.dirname(os.path.abspath(__file__))
        instance_path = os.path.join(basedir, '..', 'instance')
        os.makedirs(instance_path, exist_ok=True)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'app.db')
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # ============================================
    # SECRET KEY
    # ============================================
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tu-clave-secreta-aqui-2026-cambiar-en-produccion')
    
    # ============================================
    # UPLOADS (solo local, Vercel no permite escritura)
    # ============================================
    if not IS_VERCEL:
        app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads', 'documentos')
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    
    # ============================================
    # INICIALIZAR DB
    # ============================================
    db.init_app(app)
    
    # ============================================
    # FILTROS JINJA2
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
    # BLUEPRINTS
    # ============================================
    from app.routes import bp as main_bp
    app.register_blueprint(main_bp)
    
    # ============================================
    # CREAR TABLAS (solo en desarrollo local)
    # ============================================
    if not IS_VERCEL:
        with app.app_context():
            db.create_all()
    
    return app