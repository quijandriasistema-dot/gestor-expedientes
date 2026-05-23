# test_template.py
import sys
sys.path.insert(0, r'C:\Users\usuario\Desktop\JUANC\gestor-expedientes-web')

from app import create_app
from app.models import db, Expediente
from flask import url_for

app = create_app()

with app.app_context():
    db.create_all()
    
    # Crear expediente de prueba si no existe
    if not Expediente.query.first():
        exp = Expediente(
            tipo='civil',
            numero_expediente='TEST-001',
            cliente='Cliente Test',
            materia='Materia Test',
            usuario_registro='Test'
        )
        db.session.add(exp)
        db.session.commit()
        print("✅ Expediente de prueba creado")
    
    # Testear la ruta
    with app.test_client() as client:
        # Simular login
        with client.session_transaction() as sess:
            sess['usuario'] = 'dev'
            sess['nombre'] = 'Test'
            sess['rol'] = 'DESARROLLADOR'
            sess['modulos'] = ['todo']
        
        print("\n🧪 Probando GET /audiencia/nueva...")
        response = client.get('/audiencia/nueva', follow_redirects=True)
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.content_type}")
        
        if response.status_code == 200:
            content = response.data.decode('utf-8', errors='ignore')
            if 'Programar' in content or 'Audiencia' in content:
                print("✅ El template se renderiza correctamente")
                print(f"Tamaño de respuesta: {len(content)} bytes")
            else:
                print("❌ El template no contiene el texto esperado")
                print(f"Primeros 500 caracteres: {content[:500]}")
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.data.decode('utf-8', errors='ignore')[:500])

print("\n✅ Test completado")