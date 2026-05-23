import sqlite3
import os
from datetime import datetime

# Ruta a la base de datos
DB_PATH = os.path.join('instance', 'app.db')

def insertar_expediente_prueba():
    """Inserta un expediente de prueba en la base de datos."""
    
    # Verificar que existe la base de datos
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: No se encontró la base de datos en {DB_PATH}")
        print("Asegúrate de haber inicializado la base de datos primero (flask db upgrade)")
        return
    
    try:
        # Conectar a la base de datos
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Datos del expediente de prueba
        expediente = {
            'numero': '001-2024',
            'titulo': 'Divorcio Pérez',
            'cliente': 'Juan Pérez',
            'estado': 'En proceso',
            'fecha_inicio': datetime.now().strftime('%Y-%m-%d'),
            'descripcion': 'Expediente de divorcio incoado por el cliente Juan Pérez'
        }
        
        # Insertar el expediente
        # Nota: Ajusta los nombres de columnas según tu modelo real
        cursor.execute("""
            INSERT INTO expediente (numero, titulo, cliente, estado, fecha_inicio, descripcion)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            expediente['numero'],
            expediente['titulo'],
            expediente['cliente'],
            expediente['estado'],
            expediente['fecha_inicio'],
            expediente['descripcion']
        ))
        
        # Confirmar cambios
        conn.commit()
        expediente_id = cursor.lastrowid
        
        print(f"✅ ¡Expediente insertado correctamente!")
        print(f"   ID: {expediente_id}")
        print(f"   Número: {expediente['numero']}")
        print(f"   Título: {expediente['titulo']}")
        print(f"   Cliente: {expediente['cliente']}")
        print(f"   Estado: {expediente['estado']}")
        print(f"   Fecha de inicio: {expediente['fecha_inicio']}")
        
        # Verificar que se insertó correctamente
        cursor.execute("SELECT * FROM expediente WHERE id = ?", (expediente_id,))
        resultado = cursor.fetchone()
        print(f"\n📋 Verificación en base de datos: {resultado}")
        
    except sqlite3.IntegrityError as e:
        print(f"⚠️ Error de integridad (posiblemente el expediente ya existe): {e}")
    except sqlite3.OperationalError as e:
        print(f"❌ Error operacional (verifica el nombre de la tabla/columnas): {e}")
        print("Tip: Revisa tu modelo SQLAlchemy para confirmar los nombres exactos")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def ver_tablas_disponibles():
    """Muestra las tablas disponibles en la base de datos."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tablas = cursor.fetchall()
        print("\n📊 Tablas disponibles en la base de datos:")
        for tabla in tablas:
            print(f"   - {tabla[0]}")
        conn.close()
    except Exception as e:
        print(f"Error al consultar tablas: {e}")

if __name__ == '__main__':
    print("=" * 50)
    print("INSERTAR EXPEDIENTE DE PRUEBA")
    print("=" * 50)
    
    # Primero mostrar tablas disponibles (útil para debug)
    ver_tablas_disponibles()
    
    print("\n" + "-" * 50)
    print("Insertando expediente...")
    print("-" * 50)
    
    insertar_expediente_prueba()