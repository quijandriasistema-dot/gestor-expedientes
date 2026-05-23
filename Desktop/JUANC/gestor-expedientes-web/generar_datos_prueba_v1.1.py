# generar_datos_prueba_v1.1.py - Datos de prueba para v1.1 (Audit Trail + Backup)
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import Expediente, EstadoHistorial, Audiencia, Documento, Notificacion, AuditLog
from datetime import datetime, timedelta, date
import random

app = create_app()

def generar_dni():
    return str(random.randint(10000000, 99999999))

def generar_telefono():
    return f"9{random.randint(10000000, 99999999)}"

def fecha_random(dias_atras=365, dias_adelante=30):
    hoy = date.today()
    delta = random.randint(-dias_atras, dias_adelante)
    return hoy + timedelta(days=delta)

def generar_datos_prueba():
    with app.app_context():
        print("🗑️ Limpiando datos anteriores...")
        Notificacion.query.delete()
        Documento.query.delete()
        Audiencia.query.delete()
        EstadoHistorial.query.delete()
        Expediente.query.delete()
        
        db.session.commit()
        print("✅ Base limpia")
        
        print("\n📁 Generando expedientes de prueba...")
        
        # ============================================
        # EXPEDIENTES CIVILES (8 casos)
        # ============================================
        civiles = [
            {"cliente": "García López, María Elena", "materia": "Divorcio por causal", "estado": "activo"},
            {"cliente": "Rodríguez Pérez, Juan Carlos", "materia": "Demanda de alimentos", "estado": "activo"},
            {"cliente": "Mendoza Quispe, Rosa", "materia": "Sucesión intestada", "estado": "archivado"},
            {"cliente": "Torres Vargas, Luis Alberto", "materia": "Desalojo por falta de pago", "estado": "activo"},
            {"cliente": "Flores Castillo, Carmen Rosa", "materia": "Rectificación de partida", "estado": "concluido"},
            {"cliente": "Díaz Chávez, Pedro Pablo", "materia": "Indemnización por daños", "estado": "activo"},
            {"cliente": "Ruiz García, Ana María", "materia": "Cumplimiento de contrato", "estado": "activo"},
            {"cliente": "Silva Paredes, Jorge Luis", "materia": "Nulidad de acto jurídico", "estado": "archivado"},
        ]
        
        expedientes_creados = []
        
        for i, data in enumerate(civiles, 1):
            exp = Expediente(
                tipo='civil',
                numero_expediente=f"2024-00{i:03d}",
                cliente=data["cliente"],
                dni=generar_dni(),
                telefono=generar_telefono(),
                materia=data["materia"],
                descripcion=f"Caso civil generado automáticamente para pruebas. {data['materia']}. Cliente requiere atención prioritaria.",
                estado_actual=data["estado"],
                fecha_registro=fecha_random(300, 0),
                secretario=f"Dr. {random.choice(['Pérez', 'García', 'López', 'Martínez'])}",
                juez=f"Juez {random.choice(['Torres', 'Vargas', 'Chávez', 'Castillo'])}",
                usuario_registro='dev'
            )
            db.session.add(exp)
            db.session.flush()
            expedientes_creados.append(exp)
            
            hist = EstadoHistorial(
                expediente_id=exp.id,
                estado='activo',
                fecha=exp.fecha_registro,
                descripcion='Expediente creado en sistema',
                usuario='dev'
            )
            db.session.add(hist)
            
            if data["estado"] != 'activo':
                hist2 = EstadoHistorial(
                    expediente_id=exp.id,
                    estado=data["estado"],
                    fecha=fecha_random(30, 0),
                    descripcion=f'Cambio a estado: {data["estado"]}',
                    usuario='admin'
                )
                db.session.add(hist2)
            
            print(f"   ✅ Civil {exp.numero_expediente}: {exp.cliente[:30]}...")
        
        # ============================================
        # EXPEDIENTES PENALES (7 casos)
        # ============================================
        penales = [
            {"cliente": "Quispe Mamani, José Luis", "materia": "Defensa por hurto agravado", "estado": "activo", "cf": "CF-2024-001"},
            {"cliente": "Huamán Rojas, Rosa María", "materia": "Denuncia por lesiones", "estado": "activo", "cf": "CF-2024-002"},
            {"cliente": "Vega Torres, Carlos Alberto", "materia": "Defensa por estafa", "estado": "archivado", "cf": "CF-2024-003"},
            {"cliente": "Paredes Soto, Ana Lucía", "materia": "Denuncia por violencia familiar", "estado": "activo", "cf": "CF-2024-004"},
            {"cliente": "Mendoza Cruz, Luis Enrique", "materia": "Defensa por tráfico ilícito", "estado": "concluido", "cf": "CF-2024-005"},
            {"cliente": "Castillo Vega, María Teresa", "materia": "Denuncia por difamación", "estado": "activo", "cf": "CF-2024-006"},
            {"cliente": "Ramos Pérez, Jorge Antonio", "materia": "Defensa por receptación", "estado": "activo", "cf": "CF-2024-007"},
        ]
        
        for i, data in enumerate(penales, 1):
            exp = Expediente(
                tipo='penal',
                numero_expediente=f"2024-P{i:03d}",
                dni=generar_dni(),
                cliente=data["cliente"],
                telefono=generar_telefono(),
                materia=data["materia"],
                descripcion=f"Caso penal generado para pruebas. {data['materia']}. Requiere seguimiento de fiscalía.",
                estado_actual=data["estado"],
                fecha_registro=fecha_random(250, 0),
                numero_cf=data["cf"],
                fiscal=f"Fiscal {random.choice(['García', 'López', 'Martínez', 'Rodríguez'])}",
                juzgado=f"Juzgado Penal {random.choice(['1°', '2°', '3°'])}",
                usuario_registro='admin'
            )
            db.session.add(exp)
            db.session.flush()
            expedientes_creados.append(exp)
            
            hist = EstadoHistorial(
                expediente_id=exp.id,
                estado='activo',
                fecha=exp.fecha_registro,
                descripcion='Expediente penal creado',
                usuario='admin'
            )
            db.session.add(hist)
            
            if data["estado"] != 'activo':
                hist2 = EstadoHistorial(
                    expediente_id=exp.id,
                    estado=data["estado"],
                    fecha=fecha_random(20, 0),
                    descripcion=f'Resolución fiscal: {data["estado"]}',
                    usuario='admin'
                )
                db.session.add(hist2)
            
            print(f"   ✅ Penal {exp.numero_expediente}: {exp.cliente[:30]}...")
        
        # ============================================
        # EXPEDIENTES ADMINISTRATIVOS (6 casos)
        # ============================================
        administrativos = [
            {"cliente": "Empresa Constructora Los Andes S.A.C.", "materia": "Licencia de construcción", "entidad": "Municipalidad de Lima", "tramite": "Aprobación de planos"},
            {"cliente": "Transportes Rápidos del Norte E.I.R.L.", "materia": "Permiso de operación", "entidad": "MTC", "tramite": "Autorización de flota"},
            {"cliente": "Restaurante El Sabor Criollo S.R.L.", "materia": "Licencia de funcionamiento", "entidad": "Municipalidad de Miraflores", "tramite": "Inspección técnica"},
            {"cliente": "Clínica San José S.A.", "materia": "Autorización sanitaria", "entidad": "DIGESA", "tramite": "Certificación de equipos"},
            {"cliente": "Inmobiliaria Horizonte Verde S.A.C.", "materia": "Subdivisión de predio", "entidad": "SUNARP", "tramite": "Inscripción de lotes"},
            {"cliente": "Consultora Tech Solutions S.A.C.", "materia": "Registro de proveedor", "entidad": "OSCE", "tramite": "Habilitación de empresa"},
        ]
        
        for i, data in enumerate(administrativos, 1):
            exp = Expediente(
                tipo='administrativo',
                numero_expediente='-',
                dni=generar_dni(),
                cliente=data["cliente"],
                telefono=generar_telefono(),
                materia=data["materia"],
                descripcion=f"Trámite administrativo: {data['tramite']} ante {data['entidad']}.",
                estado_actual='activo',
                fecha_registro=fecha_random(200, 0),
                entidad_receptora=data["entidad"],
                tramite=data["tramite"],
                usuario_registro='usuario1'
            )
            db.session.add(exp)
            db.session.flush()
            expedientes_creados.append(exp)
            
            hist = EstadoHistorial(
                expediente_id=exp.id,
                estado='activo',
                fecha=exp.fecha_registro,
                descripcion=f'Trámite iniciado: {data["tramite"]}',
                usuario='usuario1'
            )
            db.session.add(hist)
            
            print(f"   ✅ Admin {exp.dni}: {exp.cliente[:25]}...")
        
        # ============================================
        # EXPEDIENTES CONCILIACIÓN (6 casos)
        # ============================================
        conciliaciones = [
            {"cliente": "López Torres, María", "materia": "Conciliación familiar - pensión", "solicitante": "López Torres, María", "conciliador": "Dr. Vega"},
            {"cliente": "Pérez García, Juan", "materia": "Conciliación contractual", "solicitante": "Empresa ABC S.A.", "conciliador": "Dra. Castillo"},
            {"cliente": "Ruiz Flores, Ana", "materia": "Conciliación vecinal", "solicitante": "Ruiz Flores, Ana", "conciliador": "Dr. Mendoza"},
            {"cliente": "Chávez Díaz, Pedro", "materia": "Conciliación laboral", "solicitante": "Chávez Díaz, Pedro", "conciliador": "Dra. Ramírez"},
            {"cliente": "Soto Vargas, Luisa", "materia": "Conciliación comercial", "solicitante": "Soto Vargas, Luisa", "conciliador": "Dr. Huamán"},
            {"cliente": "Mendoza Cruz, Rosa", "materia": "Conciliación de alimentos", "solicitante": "Mendoza Cruz, Rosa", "conciliador": "Dra. Quispe"},
        ]
        
        for i, data in enumerate(conciliaciones, 1):
            exp = Expediente(
                tipo='conciliacion',
                numero_expediente=f"CN-{2024}-{i:03d}",
                dni=generar_dni(),
                cliente=data["cliente"],
                telefono=generar_telefono(),
                materia=data["materia"],
                descripcion=f"Proceso de conciliación: {data['materia']}. Solicitante: {data['solicitante']}",
                estado_actual=random.choice(['activo', 'concluido', 'archivado']),
                fecha_registro=fecha_random(150, 0),
                solicitante=data["solicitante"],
                conciliador=data["conciliador"],
                invitados=random.choice(['No aplica', 'Parte contraria', 'Abogados de ambas partes']),
                usuario_registro='dev'
            )
            db.session.add(exp)
            db.session.flush()
            expedientes_creados.append(exp)
            
            hist = EstadoHistorial(
                expediente_id=exp.id,
                estado='activo',
                fecha=exp.fecha_registro,
                descripcion='Acta de conciliación generada',
                usuario='dev'
            )
            db.session.add(hist)
            
            print(f"   ✅ Conciliación {exp.numero_expediente}: {exp.cliente[:30]}...")
        
        # ============================================
        # EXPEDIENTES EN ARCHIVO (8 casos)
        # ============================================
        archivos = [
            {"cliente": "Vargas Pérez, José", "materia": "Caso civil 2019 - resuelto", "ubicacion": "Estante A-12, Caja 45"},
            {"cliente": "García Torres, María", "materia": "Caso penal 2020 - archivado", "ubicacion": "Estante B-05, Caja 23"},
            {"cliente": "López Mendoza, Carlos", "materia": "Trámite admin 2021 - concluido", "ubicacion": "Estante C-08, Caja 67"},
            {"cliente": "Quispe Flores, Ana", "materia": "Conciliación 2022 - terminada", "ubicacion": "Estante A-03, Caja 12"},
            {"cliente": "Rodríguez Chávez, Luis", "materia": "Caso civil 2018 - resuelto", "ubicacion": "Estante B-15, Caja 89"},
            {"cliente": "Castillo Vega, Rosa", "materia": "Caso penal 2019 - prescrito", "ubicacion": "Estante C-22, Caja 34"},
            {"cliente": "Huamán Paredes, Jorge", "materia": "Trámite 2020 - cancelado", "ubicacion": "Estante A-18, Caja 56"},
            {"cliente": "Díaz Ruiz, Carmen", "materia": "Caso civil 2021 - archivado", "ubicacion": "Estante B-09, Caja 78"},
        ]
        
        for i, data in enumerate(archivos, 1):
            exp = Expediente(
                tipo='archivo',
                numero_expediente=f"ARCH-{2018+i}-{i:03d}",
                dni=generar_dni(),
                cliente=data["cliente"],
                telefono=generar_telefono(),
                materia=data["materia"],
                descripcion=f"Expediente archivado. {data['materia']}. Consultar físicamente en {data['ubicacion']}",
                estado_actual='archivado',
                fecha_registro=fecha_random(2000, -1000),
                ubicacion_archivo=data["ubicacion"],
                usuario_registro='admin'
            )
            db.session.add(exp)
            db.session.flush()
            expedientes_creados.append(exp)
            
            hist = EstadoHistorial(
                expediente_id=exp.id,
                estado='archivado',
                fecha=exp.fecha_registro,
                descripcion=f'Archivado en: {data["ubicacion"]}',
                usuario='admin'
            )
            db.session.add(hist)
            
            print(f"   ✅ Archivo {exp.numero_expediente}: {exp.cliente[:30]}...")
        
        db.session.commit()
        print(f"\n📊 Total expedientes creados: {len(expedientes_creados)}")
        
        # ============================================
        # AUDIENCIAS (15 casos)
        # ============================================
        print("\n📅 Generando audiencias...")
        
        tipos_audiencia = ['Audiencia de conciliación', 'Audiencia de juicio oral', 'Audiencia de prisión preventiva', 
                           'Audiencia de lectura de sentencia', 'Audiencia de medida cautelar', 'Audiencia de prueba']
        lugares = ['Palacio de Justicia', 'Sede Central', 'Juzgado Civil', 'Juzgado Penal', 'Centro de Conciliación']
        
        # 5 audiencias para hoy
        for i in range(5):
            exp = random.choice(expedientes_creados)
            aud = Audiencia(
                expediente_id=exp.id,
                fecha=date.today(),
                hora=datetime.strptime(f"{9+i}:00", "%H:%M").time(),
                tipo_audiencia=random.choice(tipos_audiencia),
                lugar=random.choice(lugares),
                sala=f"Sala {random.randint(1, 5)}",
                magistrado=f"Juez {random.choice(['Torres', 'García', 'López', 'Martínez'])}",
                estado='programada',
                observaciones='Audiencia programada para hoy. Puntualidad requerida.',
                usuario_registro='dev'
            )
            db.session.add(aud)
            print(f"   ✅ Hoy {aud.hora}: {aud.tipo_audiencia[:30]}...")
        
        # 5 audiencias para mañana
        for i in range(5):
            exp = random.choice(expedientes_creados)
            aud = Audiencia(
                expediente_id=exp.id,
                fecha=date.today() + timedelta(days=1),
                hora=datetime.strptime(f"{10+i}:00", "%H:%M").time(),
                tipo_audiencia=random.choice(tipos_audiencia),
                lugar=random.choice(lugares),
                sala=f"Sala {random.randint(1, 5)}",
                magistrado=f"Juez {random.choice(['Vargas', 'Chávez', 'Castillo', 'Rodríguez'])}",
                estado='programada',
                observaciones='Audiencia programada para mañana.',
                usuario_registro='admin'
            )
            db.session.add(aud)
            print(f"   ✅ Mañana {aud.hora}: {aud.tipo_audiencia[:30]}...")
        
        # 5 audiencias pasadas
        for i in range(5):
            exp = random.choice(expedientes_creados)
            aud = Audiencia(
                expediente_id=exp.id,
                fecha=date.today() - timedelta(days=random.randint(5, 30)),
                hora=datetime.strptime(f"{9+i}:00", "%H:%M").time(),
                tipo_audiencia=random.choice(tipos_audiencia),
                lugar=random.choice(lugares),
                sala=f"Sala {random.randint(1, 5)}",
                magistrado=f"Juez {random.choice(['Pérez', 'García', 'López', 'Martínez'])}",
                estado=random.choice(['realizada', 'aplazada', 'cancelada']),
                observaciones='Audiencia concluida. Acta generada.',
                usuario_registro='usuario1'
            )
            db.session.add(aud)
            print(f"   ✅ Pasada ({aud.fecha}): {aud.tipo_audiencia[:30]}...")
        
        db.session.commit()
        print(f"\n📅 Total audiencias creadas: 15")
        
        # ============================================
        # DOCUMENTOS (20 casos)
        # ============================================
        print("\n📄 Generando documentos...")
        
        categorias = ['demanda', 'contrato', 'escritura', 'certificado', 'informe', 'otro']
        tipos_archivo = ['pdf', 'docx', 'jpg', 'xlsx']
        
        for i in range(20):
            exp = random.choice(expedientes_creados)
            cat = random.choice(categorias)
            tipo = random.choice(tipos_archivo)
            
            doc = Documento(
                expediente_id=exp.id,
                titulo=f"{cat.title()} - {exp.cliente[:20]}...",
                descripcion=f"Documento {cat} adjunto al expediente. Generado automáticamente para pruebas.",
                categoria=cat,
                nombre_archivo=f"doc_{exp.id}_{i+1}.{tipo}",
                tipo_archivo=tipo,
                tamaño_bytes=random.randint(100000, 5000000),
                ruta_archivo=f"doc_{exp.id}_{i+1}.{tipo}",
                fecha_documento=fecha_random(100, 0),
                usuario_subida=random.choice(['dev', 'admin', 'usuario1'])
            )
            db.session.add(doc)
            print(f"   ✅ Doc {i+1}: {doc.titulo[:40]}...")
        
        db.session.commit()
        print(f"\n📄 Total documentos creados: 20")
        
        # ============================================
        # NOTIFICACIONES (10 casos)
        # ============================================
        print("\n🔔 Generando notificaciones...")
        
        notificaciones_data = [
            ("Audiencia próxima", "Tienes una audiencia programada para mañana", "warning"),
            ("Expediente actualizado", "Se ha agregado un nuevo estado al expediente", "info"),
            ("Documento recibido", "Nuevo documento adjunto al expediente", "success"),
            ("Audiencia hoy", "Audiencia programada para las 10:00 AM", "danger"),
            ("Recordatorio", "No olvides revisar el expediente civil 2024", "info"),
        ]
        
        for i in range(10):
            exp = random.choice(expedientes_creados) if random.choice([True, False]) else None
            titulo, mensaje, color = random.choice(notificaciones_data)
            
            notif = Notificacion(
                tipo='sistema',
                titulo=titulo,
                mensaje=f"{mensaje}. Expediente: {exp.numero_expediente if exp else 'General'}.",
                expediente_id=exp.id if exp else None,
                icono=random.choice(['📅', '📄', '🔔', '⚠️', '✅']),
                color=color,
                leida=random.choice([True, False])
            )
            db.session.add(notif)
            print(f"   ✅ Notif {i+1}: {titulo[:30]}...")
        
        db.session.commit()
        print(f"\n🔔 Total notificaciones creadas: 10")
        
        # ============================================
        # AUDIT TRAIL - Logs de prueba (20 registros)
        # ============================================
        print("\n📋 Generando logs de auditoría...")
        
        acciones = [
            ('crear', 'expediente', 'Creado expediente nuevo'),
            ('editar', 'expediente', 'Modificado estado del expediente'),
            ('login', 'usuario', 'Inicio de sesión'),
            ('logout', 'usuario', 'Cierre de sesión'),
            ('crear', 'audiencia', 'Programada nueva audiencia'),
            ('editar', 'audiencia', 'Modificada fecha de audiencia'),
            ('crear', 'documento', 'Subido nuevo documento'),
        ]
        
        usuarios_audit = ['dev', 'admin', 'usuario1']
        
        for i in range(20):
            accion, tabla, desc = random.choice(acciones)
            usuario = random.choice(usuarios_audit)
            
            log = AuditLog(
                tabla=tabla,
                registro_id=random.randint(1, 35),
                accion=accion,
                campo=random.choice([None, 'estado', 'cliente', 'fecha', 'descripcion']),
                valor_anterior=random.choice([None, 'activo', 'Juan Pérez', '2024-01-01']),
                valor_nuevo=random.choice(['concluido', 'Pedro García', '2024-02-01', 'Nuevo valor']),
                usuario=usuario,
                fecha=datetime.now() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23)),
                ip_address=f"192.168.1.{random.randint(1, 255)}",
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            )
            db.session.add(log)
            print(f"   ✅ Log {i+1}: {accion} {tabla} por {usuario}")
        
        db.session.commit()
        print(f"\n📋 Total logs de auditoría creados: 20")
        
        # ============================================
        # RESUMEN FINAL
        # ============================================
        print("\n" + "="*50)
        print("✅ BASE DE DATOS DE PRUEBA V1.1 COMPLETADA")
        print("="*50)
        print(f"📁 Expedientes: 35 (Civil: 8, Penal: 7, Admin: 6, Conciliación: 6, Archivo: 8)")
        print(f"📅 Audiencias: 15 (Hoy: 5, Mañana: 5, Pasadas: 5)")
        print(f"📄 Documentos: 20")
        print(f"🔔 Notificaciones: 10")
        print(f"📋 Logs Auditoría: 20")
        print("="*50)
        print("\n🚀 Para probar:")
        print("   1. Inicia sesión con dev/dev123")
        print("   2. Revisa el Dashboard (debe mostrar contadores reales)")
        print("   3. Ve a /auditoria (debe mostrar logs de prueba)")
        print("   4. Crea un expediente nuevo (debe registrarse en auditoría)")
        print("   5. Edita un expediente (debe registrar cambios en auditoría)")

if __name__ == '__main__':
    generar_datos_prueba()