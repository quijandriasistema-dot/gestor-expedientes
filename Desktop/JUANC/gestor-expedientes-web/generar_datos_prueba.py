#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para generar datos de prueba en el Sistema de Gestión de Expedientes
Quijandria Abogados EIRL

Genera:
- 35 expedientes distribuidos por tipo
- 15 audiencias programadas
- 20 documentos adjuntos
"""

import random
from datetime import datetime, timedelta, date
import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import Expediente, EstadoHistorial, Audiencia, Documento

app = create_app()

# ============================================
# DATOS DE PRUEBA
# ============================================

NOMBRES_CLIENTES = [
    "Juan Carlos Mendoza García", "María Elena Quispe Flores", "Pedro Antonio López Rojas",
    "Ana Lucía Vargas Campos", "Luis Alberto Huamán Chávez", "Carmen Rosa Quispe Mamani",
    "Jorge Luis Castillo Paredes", "Rosa María Díaz Torres", "Carlos Enrique Ramos Vega",
    "Patricia Isabel Sánchez Luna", "Miguel Ángel Herrera Cruz", "Laura Beatriz Mendoza Silva",
    "Fernando José Ruiz Palacios", "Diana Carolina Espinoza León", "Roberto Carlos Vega Castillo",
    "Gabriela Alejandra Flores Rojas", "Andrés Felipe Medina Guerrero", "Silvia Patricia Castro Mendoza",
    "Diego Alonso Ramírez Pérez", "Valeria Nicole Torres Vargas", "Ricardo Enrique Palacios Vega",
    "Alejandra María Quispe Flores", "Martín Sebastián López Chávez", "Daniela Fernanda Ruiz Campos",
    "Francisco Javier Mendoza Luna", "Camila Andrea Díaz Herrera", "Antonio José García Ramos",
    "Isabella Sofía Vargas Silva", "Emilio Andrés Castillo Palacios", "Victoria Elena Quispe Torres",
    "Mateo Alejandro Sánchez Vega", "Luciana María Flores Cruz", "Santiago José Mendoza Rojas",
    "Mariana Isabel Campos León", "Adrián Felipe Huamán Paredes"
]

MATERIAS = {
    'civil': [
        "Demanda de alimentos", "Divorcio por causal", "Desalojo por falta de pago", 
        "Indemnización por daños", "Incumplimiento de contrato", "Sucesión intestada", 
        "Nulidad de acto jurídico", "Obligación de dar suma de dinero"
    ],
    'penal': [
        "Denuncia por estafa", "Lesiones culposas", "Robo agravado", "Defraudación", 
        "Violencia familiar", "Amenazas", "Homicidio culposo", "Microcomercialización de drogas"
    ],
    'administrativo': [
        "Solicitud de pensión de jubilación", "Reconsideración de sanción", 
        "Solicitud de licencia de funcionamiento", "Apelación de multa", 
        "Solicitud de rectificación de partida", "Reclamo de indebida cobranza"
    ],
    'conciliacion': [
        "Conflicto vecinal", "Desalojo voluntario", "Régimen de visitas", 
        "Liquidación de sociedad de hecho", "Tenencia de mascotas", "Ruidos molestos"
    ],
    'archivo': [
        "Caso resuelto - Alimentos 2023", "Divorcio concluido 2022", 
        "Sentencia firme - Desalojo 2023", "Acuerdo conciliatorio cumplido", 
        "Caso prescrito - Penal", "Archivo definitivo - Sucesión",
        "Caso cerrado - Indemnización", "Expediente histórico 2019-2020"
    ]
}

ESTADOS = ['ingresado', 'en_proceso', 'audiencia_programada', 'resuelto', 'archivado']

TIPOS_AUDIENCIA = ["oral", "conciliación", "mediación", "lectura de sentencia", "apelación"]
LUGARES = ["Palacio de Justicia", "Centro de Conciliación", "Sede Principal", "Juzgado Virtual"]
CATEGORIAS_DOC = ["escrito", "contrato", "evidencia", "sentencia", "certificado", "identificación", "otro"]

def generar_dni():
    """Genera DNI peruano válido (8 dígitos)"""
    return str(random.randint(10000000, 99999999))

def generar_telefono():
    """Genera teléfono peruano"""
    return f"9{random.randint(10000000, 99999999)}"

def generar_numero_expediente(tipo, index):
    """Genera número de expediente según tipo"""
    año = random.choice([2023, 2024, 2025])
    if tipo == 'civil':
        return f"{index+1:04d}-{año}-CIV"
    elif tipo == 'penal':
        return f"{index+1:04d}-{año}-PEN"
    elif tipo == 'conciliacion':
        return f"{index+1:04d}-{año}-CON"
    elif tipo == 'archivo':
        return f"{index+1:04d}-{año}-ARC"
    return f"{index+1:04d}-{año}"

def generar_fecha_registro():
    """Genera fecha de registro aleatoria en los últimos 6 meses"""
    dias_atras = random.randint(1, 180)
    return datetime.now() - timedelta(days=dias_atras)

def crear_expediente(tipo, index, nombre_cliente):
    """Crea un expediente según su tipo"""

    dni = generar_dni()
    telefono = generar_telefono()
    materia = random.choice(MATERIAS[tipo])
    fecha_reg = generar_fecha_registro()

    # Determinar estado según tipo
    if tipo == 'archivo':
        estado = random.choice(['resuelto', 'archivado'])
    else:
        estado = random.choice(ESTADOS[:-1])  # Excluir 'archivado' para activos

    # Datos base
    exp_data = {
        'tipo': tipo,
        'cliente': nombre_cliente,
        'telefono': telefono,
        'materia': materia,
        'descripcion': f"Caso de {materia.lower()} iniciado el {fecha_reg.strftime('%d/%m/%Y')}",
        'estado_actual': estado,
        'fecha_registro': fecha_reg,
        'usuario_registro': 'Sistema de Prueba'
    }

    # Datos específicos por tipo
    if tipo == 'administrativo':
        exp_data['dni'] = dni
        exp_data['numero_expediente'] = '-'
        exp_data['entidad_receptora'] = random.choice(["ONP", "SUNAT", "Municipalidad", "MINSA", "SUNARP"])
        exp_data['tramite'] = materia
    else:
        exp_data['numero_expediente'] = generar_numero_expediente(tipo, index)
        if tipo == 'civil':
            exp_data['juez'] = f"Juez {random.choice(['Primero', 'Segundo', 'Tercero'])} Civil"
            exp_data['secretario'] = "Dr. " + random.choice(["García", "López", "Martínez"])
        elif tipo == 'penal':
            exp_data['dni'] = dni
            exp_data['numero_cf'] = f"CF-{random.randint(1000, 9999)}-2024"
            exp_data['fiscal'] = f"Fiscal {random.choice(['Primero', 'Segundo'])} Provincial"
            exp_data['juzgado'] = random.choice(["1° Juzgado Penal", "2° Juzgado Penal"])
        elif tipo == 'conciliacion':
            exp_data['dni'] = dni
            exp_data['conciliador'] = "Conciliador " + random.choice(["Pérez", "Gómez", "Ruiz"])
            exp_data['solicitante'] = nombre_cliente
            exp_data['invitados'] = random.choice(["Parte contraria", "Abogado contrario", "Testigos"])
        elif tipo == 'archivo':
            exp_data['dni'] = dni
            exp_data['ubicacion_archivo'] = random.choice(["Estante A-1", "Estante A-2", "Estante B-1", "Depósito Principal"])

    return Expediente(**exp_data)

def crear_audiencia(expediente, fecha_base):
    """Crea una audiencia para un expediente"""
    # Fecha entre hoy y 30 días adelante
    dias_adelante = random.randint(0, 30)
    fecha_audiencia = date.today() + timedelta(days=dias_adelante)

    hora = f"{random.randint(8, 16):02d}:{random.choice(['00', '15', '30', '45'])}"

    return Audiencia(
        expediente_id=expediente.id,
        fecha=fecha_audiencia,
        hora=datetime.strptime(hora, "%H:%M").time(),
        tipo_audiencia=random.choice(TIPOS_AUDIENCIA),
        lugar=random.choice(LUGARES),
        sala=f"Sala {random.randint(1, 5)}",
        magistrado=f"Juez {random.choice(['Carlos Ruiz', 'Ana López', 'Pedro Gómez'])}",
        observaciones=f"Audiencia programada para {expediente.materia}",
        estado='programada',
        recordatorio_dias=random.choice([1, 3, 7]),
        usuario_registro='Sistema de Prueba',
        fecha_registro=datetime.now()
    )

def crear_documento(expediente=None):
    """Crea un documento (puede ser general o vinculado a expediente)"""
    categoria = random.choice(CATEGORIAS_DOC)
    tipo_archivo = random.choice(['pdf', 'docx', 'jpg', 'pdf'])

    titulos = {
        'escrito': ['Demanda inicial', 'Contestación', 'Réplica', 'Dúplica', 'Escrito de prueba'],
        'contrato': ['Contrato de arrendamiento', 'Contrato de trabajo', 'Contrato de compraventa'],
        'evidencia': ['Fotografía de evidencia', 'Video de incidente', 'Documento probatorio'],
        'sentencia': ['Sentencia de primera instancia', 'Resolución judicial', 'Auto judicial'],
        'certificado': ['Certificado de nacimiento', 'Certificado de matrimonio', 'Certificado de trabajo'],
        'identificación': ['DNI escaneado', 'Pasaporte', 'Carné de extranjería'],
        'otro': ['Recibo de pago', 'Constancia de estudios', 'Boleta de venta']
    }

    titulo = random.choice(titulos[categoria])

    return Documento(
        expediente_id=expediente.id if expediente else None,
        titulo=titulo,
        descripcion=f"Documento {categoria} generado para pruebas",
        categoria=categoria,
        nombre_archivo=f"{titulo.lower().replace(' ', '_')}.{tipo_archivo}",
        tipo_archivo=tipo_archivo,
        tamaño_bytes=random.randint(100000, 5000000),
        ruta_archivo=f"doc_{random.randint(1000, 9999)}.{tipo_archivo}",
        fecha_documento=datetime.now() - timedelta(days=random.randint(1, 60)),
        usuario_subida='Sistema de Prueba',
        fecha_subida=datetime.now() - timedelta(days=random.randint(1, 30))
    )

def main():
    with app.app_context():
        print("=" * 60)
        print("GENERADOR DE DATOS DE PRUEBA - QUIJANDRIA ABOGADOS")
        print("=" * 60)

        # Verificar si ya hay datos
        count = Expediente.query.count()
        if count > 0:
            print(f"\n⚠️  Ya existen {count} expedientes en la base de datos.")
            respuesta = input("¿Deseas eliminarlos y crear nuevos? (s/n): ")
            if respuesta.lower() != 's':
                print("Operación cancelada.")
                return

            # Limpiar datos existentes
            print("🗑️  Eliminando datos existentes...")
            Documento.query.delete()
            Audiencia.query.delete()
            EstadoHistorial.query.delete()
            Expediente.query.delete()
            db.session.commit()
            print("✅ Datos anteriores eliminados")

        print("\n📊 Generando 35 expedientes de prueba...")
        print("-" * 60)

        # Distribución: 8 Civil, 7 Penal, 6 Admin, 6 Conciliación, 8 Archivo
        distribucion = [
            ('civil', 8), ('penal', 7), ('administrativo', 6), 
            ('conciliacion', 6), ('archivo', 8)
        ]

        expedientes_creados = []
        cliente_idx = 0

        for tipo, cantidad in distribucion:
            print(f"\n🏷️  Creando {cantidad} casos de tipo: {tipo.upper()}")

            for i in range(cantidad):
                # Crear expediente
                exp = crear_expediente(tipo, i, NOMBRES_CLIENTES[cliente_idx])
                db.session.add(exp)
                db.session.flush()  # Para obtener el ID

                # Crear estado inicial en historial
                historial = EstadoHistorial(
                    expediente_id=exp.id,
                    estado=exp.estado_actual,
                    descripcion=f"Expediente registrado en el sistema",
                    usuario='Sistema de Prueba',
                    fecha=exp.fecha_registro
                )
                db.session.add(historial)

                expedientes_creados.append(exp)
                cliente_idx += 1

                print(f"   ✓ {exp.get_identificador_principal()} - {exp.cliente[:30]}...")

        db.session.commit()
        print(f"\n✅ {len(expedientes_creados)} expedientes creados")

        # Crear audiencias (15 aprox)
        print("\n📅 Generando audiencias...")
        audiencias_count = 0

        # Seleccionar expedientes para audiencias (excluir archivados)
        exp_con_audiencia = [e for e in expedientes_creados if e.estado_actual not in ['archivado', 'resuelto']]
        exp_con_audiencia = random.sample(exp_con_audiencia, min(15, len(exp_con_audiencia)))

        for exp in exp_con_audiencia:
            audiencia = crear_audiencia(exp, date.today())
            db.session.add(audiencia)

            # Actualizar estado del expediente
            exp.estado_actual = 'audiencia_programada'

            # Agregar al historial
            historial = EstadoHistorial(
                expediente_id=exp.id,
                estado='audiencia_programada',
                descripcion=f"Audiencia programada para el {audiencia.fecha.strftime('%d/%m/%Y')}",
                usuario='Sistema de Prueba'
            )
            db.session.add(historial)
            audiencias_count += 1

        db.session.commit()
        print(f"✅ {audiencias_count} audiencias programadas")

        # Crear documentos (20)
        print("\n📄 Generando documentos...")
        documentos_count = 0

        # 15 documentos vinculados a expedientes
        for exp in random.sample(expedientes_creados, 15):
            doc = crear_documento(exp)
            db.session.add(doc)
            documentos_count += 1

        # 5 documentos generales
        for _ in range(5):
            doc = crear_documento(None)
            db.session.add(doc)
            documentos_count += 1

        db.session.commit()
        print(f"✅ {documentos_count} documentos creados")

        # Resumen final
        print("\n" + "=" * 60)
        print("RESUMEN DE DATOS GENERADOS")
        print("=" * 60)
        print(f"📁 Expedientes: {Expediente.query.count()}")
        print(f"   • Civil: {Expediente.query.filter_by(tipo='civil').count()}")
        print(f"   • Penal: {Expediente.query.filter_by(tipo='penal').count()}")
        print(f"   • Administrativo: {Expediente.query.filter_by(tipo='administrativo').count()}")
        print(f"   • Conciliación: {Expediente.query.filter_by(tipo='conciliacion').count()}")
        print(f"   • Archivo: {Expediente.query.filter_by(tipo='archivo').count()}")
        print(f"📅 Audiencias: {Audiencia.query.count()}")
        print(f"📄 Documentos: {Documento.query.count()}")
        print("=" * 60)
        print("✅ Datos de prueba generados exitosamente!")
        print("\n🌐 Accede al sistema en: http://localhost:5001")
        print("   Usuario: dev | Contraseña: dev123")
        print("=" * 60)

if __name__ == '__main__':
    main()