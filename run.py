from app import create_app
from app.routes import iniciar_backup_automatico

app = create_app()

# Iniciar backup automático al arrancar el servidor
scheduler = iniciar_backup_automatico(app)

if __name__ == '__main__':
    # Forzamos el puerto 5001 (por si el 8080 tiene algún conflicto de caché)
    app.run(debug=True, host='127.0.0.1', port=5001)