# actualizar_estados.py - Script para actualizar estados sin borrar la base de datos
# Ejecutar UNA SOLA VEZ: python actualizar_estados.py

import sys
import os

# Agregar el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from sqlalchemy import text

def actualizar_estados():
    """Actualiza todos los estados antiguos a los nuevos valores compatibles usando SQL directo"""
    
    app = create_app()
    
    with app.app_context():
        print("=" * 60)
        print("ACTUALIZACIÓN DE ESTADOS - Quijandria Abogados")
        print("=" * 60)
        
        # Mapeo de estados antiguos a nuevos
        mapeo_estados = {
            'ingresado': 'ingresado',
            'en_proceso': 'en_proceso',
            'resuelto': 'proceso_completado',
            'archivado': 'archivado',
            'anulado': 'anulado',
            'Ingresado a mesa de partes': 'ingresado',
        }
        
        # Usar SQL directo para evitar problemas con el Enum
        print("\n📁 Actualizando estados en expedientes...")
        
        # Actualizar cada estado individualmente usando SQL
        for estado_antiguo, estado_nuevo in mapeo_estados.items():
            sql = text("""
                UPDATE expedientes 
                SET estado_actual = :nuevo 
                WHERE estado_actual = :antiguo
            """)
            result = db.session.execute(sql, {'nuevo': estado_nuevo, 'antiguo': estado_antiguo})
            print(f"   '{estado_antiguo}' → '{estado_nuevo}': {result.rowcount} registros")
        
        # Estados desconocidos poner como 'actualizado'
        sql = text("""
            UPDATE expedientes 
            SET estado_actual = 'actualizado' 
            WHERE estado_actual NOT IN ('ingresado', 'actualizado', 'en_proceso', 'seguimiento',
                                        'espera_documentos', 'derivado_juzgado', 'audiencia_programada',
                                        'proceso_completado', 'resuelto_favorable', 'resuelto_desfavorable',
                                        'archivado', 'anulado', 'otro')
        """)
        result = db.session.execute(sql)
        print(f"   Estados desconocidos → 'actualizado': {result.rowcount} registros")
        
        print("\n📋 Actualizando historial de estados...")
        
        # Actualizar historial
        for estado_antiguo, estado_nuevo in mapeo_estados.items():
            sql = text("""
                UPDATE estados_historial 
                SET estado = :nuevo 
                WHERE estado = :antiguo
            """)
            result = db.session.execute(sql, {'nuevo': estado_nuevo, 'antiguo': estado_antiguo})
            if result.rowcount > 0:
                print(f"   '{estado_antiguo}' → '{estado_nuevo}': {result.rowcount} registros")
        
        # Estados especiales del sistema los dejamos igual
        # Solo cambiamos los que no son especiales
        estados_especiales = ['Expediente editado', 'ingresado', 'actualizado', 'en_proceso',
                              'seguimiento', 'espera_documentos', 'derivado_juzgado',
                              'audiencia_programada', 'proceso_completado', 'resuelto_favorable',
                              'resuelto_desfavorable', 'archivado', 'anulado', 'otro']
        
        # Crear string de placeholders para la consulta
        placeholders = ','.join([f"'{e}'" for e in estados_especiales])
        
        sql = text(f"""
            UPDATE estados_historial 
            SET estado = 'actualizado' 
            WHERE estado NOT IN ({placeholders})
        """)
        result = db.session.execute(sql)
        print(f"   Estados desconocidos → 'actualizado': {result.rowcount} registros")
        
        # Guardar cambios
        print("\n💾 Guardando cambios en la base de datos...")
        db.session.commit()
        
        # Verificar resultados
        sql = text("SELECT estado_actual, COUNT(*) as total FROM expedientes GROUP BY estado_actual")
        resultados = db.session.execute(sql).fetchall()
        
        print("\n📊 ESTADOS ACTUALES EN EXPEDIENTES:")
        for row in resultados:
            print(f"   - {row.estado_actual}: {row.total} expediente(s)")
        
        sql = text("SELECT estado, COUNT(*) as total FROM estados_historial GROUP BY estado")
        resultados = db.session.execute(sql).fetchall()
        
        print("\n📊 ESTADOS ACTUALES EN HISTORIAL:")
        for row in resultados:
            print(f"   - {row.estado}: {row.total} registro(s)")
        
        print("\n" + "=" * 60)
        print("✅ ACTUALIZACIÓN COMPLETADA EXITOSAMENTE")
        print("=" * 60)
        print("\n⚠️  Este script ya se ejecutó. NO lo vuelvas a ejecutar.")
        print("   Ahora puedes reiniciar el servidor Flask.")
        print("=" * 60)

if __name__ == '__main__':
    try:
        actualizar_estados()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("\nVerifica que:")
        print("   1. El servidor Flask NO esté corriendo")
        print("   2. El archivo instance/app.db existe")
        sys.exit(1)