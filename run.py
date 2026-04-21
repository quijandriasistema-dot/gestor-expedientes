from app import create_app

app = create_app()

if __name__ == '__main__':
    # Forzamos el puerto 5001 (por si el 8080 tiene algún conflicto de caché)
    app.run(debug=True, host='127.0.0.1', port=5001)
