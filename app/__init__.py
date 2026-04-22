from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    
    # Configuración
    app.config['SECRET_KEY'] = 'tu-clave-secreta-aqui-2026-cambiar-en-produccion'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gestor_expedientes.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Uploads
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads', 'documentos')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    
    # Inicializar DB
    db.init_app(app)
    
    # Filtros Jinja2 seguros para fechas
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
    
    # Blueprints
    from app.routes import bp as main_bp
    app.register_blueprint(main_bp)
    
    # Crear tablas
    with app.app_context():
        db.create_all()
    
    return app