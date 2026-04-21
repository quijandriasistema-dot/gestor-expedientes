# app/__init__.py - Inicialización de la aplicación

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object('app.config.Config')

    # Crear carpeta instance si no existe
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    db.init_app(app)

    with app.app_context():
        # Importar y registrar Blueprint
        from app import routes
        app.register_blueprint(routes.bp)
        
        # Crear tablas
        db.create_all()

    return app