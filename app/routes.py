# app/routes.py - Rutas de la aplicación
# Sistema de Gestión de Expedientes Legales - Quijandria Abogados EIRL
# Versión con Service Account para Google Drive

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, after_this_request, send_file
from functools import wraps
from datetime import datetime, timedelta, date
from app import db
from app.models import Expediente, EstadoHistorial, Audiencia, Documento, Notificacion, Usuario
from app.forms import ExpedienteForm, EstadoForm, BusquedaForm, AudienciaForm, BusquedaAudienciaForm, DocumentoForm, BusquedaDocumentoForm
import json
import os
import bcrypt
import time

# ============================================
# IMPORTS PARA EXPORTACIÓN (PDF/EXCEL)
# ============================================
import io
import base64
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage
from logo_config import get_logo_image

# ============================================
# IMPORTS PARA GOOGLE DRIVE - SERVICE ACCOUNT
# ============================================
from app.drive_service_account import (
    subir_archivo_drive,
    eliminar_archivo_drive,
    obtener_espacio_usado_drive,
    descargar_archivo_drive
)

bp = Blueprint('main', __name__)

# ============================================
# CONFIGURACIÓN DE USUARIOS - SUPABASE (tabla: usuario)
# ============================================

USUARIOS = {}

def _cargar_usuarios():
    """Carga usuarios activos desde Supabase (tabla usuario) - BAJO DEMANDA"""
    usuarios = {}
    try:
        for u in Usuario.query.filter_by(activo=True).all():
            usuarios[u.username] = {
                'password_hash': u.password_hash,
                'nombre': u.nombre,
                'rol': u.rol,
                'modulos': u.get_modulos_list()
            }
    except Exception as e:
        print(f"Error cargando usuarios: {e}")
    return usuarios

def _guardar_usuarios():
    """Ya no se usa - los usuarios se guardan directamente en Supabase"""
    pass

# Cargar usuarios al inicio
USUARIOS = _cargar_usuarios()

# ============================================
# FUNCIONES AUXILIARES DE USUARIOS
# ============================================

def _get_usuario(username):
    """Obtiene un usuario de Supabase por username"""
    return Usuario.query.filter_by(username=username, activo=True).first()

def _verificar_password(username, password):
    """Verifica contraseña usando bcrypt"""
    usuario = _get_usuario(username)
    if usuario and usuario.check_password(password):
        return True
    return False

# ============================================
# DECORADOR ANTI-CACHÉ
# ============================================

def no_cache(f):
    """Decorador para evitar caché en páginas protegidas"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        @after_this_request
        def apply_no_cache(response):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            response.headers['Vary'] = 'Cookie'
            return response
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# DECORADORES DE PERMISOS
# ============================================

def requiere_login(f):
    """Decorador que verifica si hay sesión activa"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session:
            flash('Debe iniciar sesión primero', 'warning')
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function

def puede_ver_modulo(modulo):
    """Verifica si el usuario actual puede ver un módulo"""
    if 'rol' not in session:
        return False

    if session['rol'] == 'DESARROLLADOR':
        return True

    if session['rol'] == 'ADMINISTRADOR':
        return True

    if 'modulos' in session:
        modulos = session['modulos']

        if 'todo' in modulos:
            return True

        modulo_general = modulo
        if modulo in ['civil', 'penal', 'administrativo', 'conciliacion', 'archivo']:
            modulo_general = 'expedientes'

        if modulo in modulos or modulo_general in modulos:
            return True

    return False

def puede_exportar():
    """Verifica si el usuario puede exportar (Admin o Desarrollador)"""
    return session.get('rol') in ['ADMINISTRADOR', 'DESARROLLADOR']

# ============================================
# FUNCIONES DE NOTIFICACIONES
# ============================================

def crear_notificacion(tipo, titulo, mensaje, expediente_id=None, 
                       audiencia_id=None, usuario_destino=None, 
                       link=None, icono='🔔', color='info'):
    """Crea una nueva notificación en el sistema"""
    try:
        notif = Notificacion(
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            expediente_id=expediente_id,
            audiencia_id=audiencia_id,
            usuario_destino=usuario_destino,
            link=link,
            icono=icono,
            color=color
        )
        db.session.add(notif)
        db.session.commit()
        return notif
    except Exception as e:
        db.session.rollback()
        print(f"Error creando notificación: {e}")
        return None


def verificar_audiencias_y_notificar():
    """Verifica audiencias próximas y crea notificaciones automáticas"""
    hoy = date.today()
    manana = hoy + timedelta(days=1)

    # Audiencias de HOY
    audiencias_hoy = Audiencia.query.filter(
        Audiencia.fecha == hoy,
        Audiencia.estado == 'programada'
    ).all()

    for aud in audiencias_hoy:
        existe = Notificacion.query.filter_by(
            audiencia_id=aud.id,
            tipo='audiencia_hoy'
        ).filter(
            Notificacion.fecha_creacion >= datetime.combine(hoy, datetime.min.time())
        ).first()

        if not existe and aud.expediente:
            crear_notificacion(
                tipo='audiencia_hoy',
                titulo='📅 Audiencia Hoy',
                mensaje=f'Tienes audiencia a las {aud.hora.strftime("%H:%M")} - {aud.expediente.cliente}',
                expediente_id=aud.expediente_id,
                audiencia_id=aud.id,
                link=url_for('main.ver_audiencia', id=aud.id),
                icono='🔴',
                color='danger'
            )

    # Audiencias de MAÑANA
    audiencias_manana = Audiencia.query.filter(
        Audiencia.fecha == manana,
        Audiencia.estado == 'programada'
    ).all()

    for aud in audiencias_manana:
        existe = Notificacion.query.filter_by(
            audiencia_id=aud.id,
            tipo='audiencia_manana'
        ).first()

        if not existe and aud.expediente:
            crear_notificacion(
                tipo='audiencia_manana',
                titulo='⏰ Audiencia Mañana',
                mensaje=f'Audiencia programada para mañana a las {aud.hora.strftime("%H:%M")}',
                expediente_id=aud.expediente_id,
                audiencia_id=aud.id,
                link=url_for('main.ver_audiencia', id=aud.id),
                icono='⏰',
                color='warning'
            )

    # Audiencias en 3 días (recordatorio)
    tres_dias = hoy + timedelta(days=3)
    audiencias_3dias = Audiencia.query.filter(
        Audiencia.fecha == tres_dias,
        Audiencia.estado == 'programada'
    ).all()

    for aud in audiencias_3dias:
        existe = Notificacion.query.filter_by(
            audiencia_id=aud.id,
            tipo='audiencia_proxima'
        ).first()

        if not existe and aud.expediente:
            crear_notificacion(
                tipo='audiencia_proxima',
                titulo='📢 Audiencia en 3 Días',
                mensaje=f'Recuerda: Audiencia el {aud.fecha.strftime("%d/%m/%Y")} a las {aud.hora.strftime("%H:%M")}',
                expediente_id=aud.expediente_id,
                audiencia_id=aud.id,
                link=url_for('main.ver_audiencia', id=aud.id),
                icono='📢',
                color='info'
            )


def get_notificaciones_usuario(usuario, rol, solo_no_leidas=False, limite=10):
    """Obtiene notificaciones para un usuario específico"""
    query = Notificacion.query

    if rol != 'DESARROLLADOR':
        query = query.filter(
            db.or_(
                Notificacion.usuario_destino == usuario,
                Notificacion.usuario_destino == None
            )
        )

    if solo_no_leidas:
        query = query.filter_by(leida=False)

    return query.order_by(Notificacion.fecha_creacion.desc()).limit(limite).all()


def contar_notificaciones_no_leidas(usuario, rol):
    """Cuenta notificaciones pendientes"""
    query = Notificacion.query.filter_by(leida=False)

    if rol != 'DESARROLLADOR':
        query = query.filter(
            db.or_(
                Notificacion.usuario_destino == usuario,
                Notificacion.usuario_destino == None
            )
        )

    return query.count()


def marcar_notificacion_leida(notificacion_id, usuario):
    """Marca una notificación como leída"""
    notif = Notificacion.query.get(notificacion_id)
    if notif and (notif.usuario_destino == usuario or notif.usuario_destino is None):
        notif.leida = True
        notif.fecha_lectura = datetime.now()
        db.session.commit()
        return True
    return False

# ============================================
# API PARA BUSCAR CLIENTE POR DNI
# ============================================

@bp.route('/api/buscar-cliente/<dni>')
@requiere_login
@no_cache
def buscar_cliente_por_dni(dni):
    """API para buscar datos de cliente por DNI"""
    expediente = Expediente.query.filter_by(dni=dni).order_by(Expediente.fecha_registro.desc()).first()

    if expediente:
        return jsonify({
            'encontrado': True,
            'cliente': expediente.cliente,
            'telefono': expediente.telefono or '',
            'dni': expediente.dni or ''
        })

    return jsonify({'encontrado': False})

# ============================================
# RUTAS DE AUTENTICACIÓN
# ============================================

@bp.route('/')
@no_cache
def root():
    """Raíz redirige a login o index"""
    if 'usuario' in session:
        return redirect(url_for('main.index'))
    return redirect(url_for('main.login'))

@bp.route('/login', methods=['GET', 'POST'])
@no_cache
def login():
    """Página de login - consulta Supabase tabla usuario"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        usuario = _get_usuario(username)

        if usuario:
            if usuario.check_password(password):
                usuario.ultimo_acceso = datetime.now()
                db.session.commit()

                session['usuario'] = username
                session['usuario_id'] = usuario.id
                session['nombre'] = usuario.nombre
                session['rol'] = usuario.rol
                session['modulos'] = usuario.get_modulos_list()
                flash(f'Bienvenido, {usuario.nombre}', 'success')
                return redirect(url_for('main.index'))
            else:
                flash('Contraseña incorrecta', 'error')
        else:
            flash('Usuario no encontrado', 'error')

    return render_template('login.html', title='Iniciar Sesión')

@bp.route('/logout')
@no_cache
def logout():
    """Cerrar sesión"""
    session.clear()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('main.login'))

# ============================================
# RUTA PRINCIPAL - DASHBOARD
# ============================================

@bp.route('/index')
@requiere_login
@no_cache
def index():
    """Dashboard principal con datos reales de la BD"""

    total_expedientes = Expediente.query.count()
    civil_count = Expediente.query.filter_by(tipo='civil').count()
    penal_count = Expediente.query.filter_by(tipo='penal').count()
    admin_count = Expediente.query.filter_by(tipo='administrativo').count()
    conciliacion_count = Expediente.query.filter_by(tipo='conciliacion').count()
    archivo_count = Expediente.query.filter_by(tipo='archivo').count()

    expedientes_recientes = Expediente.query.order_by(
        Expediente.fecha_registro.desc()
    ).limit(5).all()

    # AUDIENCIAS - Datos reales
    hoy = date.today()
    audiencias_hoy = Audiencia.query.filter(
        db.func.date(Audiencia.fecha) == hoy,
        Audiencia.estado == 'programada'
    ).count()

    manana = hoy + timedelta(days=1)
    audiencias_manana = Audiencia.query.filter(
        db.func.date(Audiencia.fecha) == manana,
        Audiencia.estado == 'programada'
    ).count()

    semana_fin = hoy + timedelta(days=7)
    audiencias_semana = Audiencia.query.filter(
        db.func.date(Audiencia.fecha) >= hoy,
        db.func.date(Audiencia.fecha) <= semana_fin,
        Audiencia.estado == 'programada'
    ).count()

    # Próximas audiencias para mostrar en dashboard
    proximas_audiencias = Audiencia.query.filter(
        Audiencia.fecha >= hoy,
        Audiencia.estado == 'programada'
    ).order_by(Audiencia.fecha, Audiencia.hora).limit(5).all()

    form_busqueda = BusquedaForm()

    # ALERTA DE ESPACIO EN GOOGLE DRIVE (solo Admin/Dev)
    espacio_drive = None
    if session.get('rol') in ['ADMINISTRADOR', 'DESARROLLADOR']:
        try:
            espacio_drive = obtener_espacio_usado_drive()
        except Exception as e:
            print(f"Error obteniendo espacio Drive: {e}")
            espacio_drive = None

    return render_template('index.html',
                         title='Panel Principal',
                         usuario=session.get('nombre', 'Usuario'),
                         rol=session.get('rol', 'USUARIO'),
                         modulos_permitidos=session.get('modulos', []),
                         total_expedientes=total_expedientes,
                         civil_count=civil_count,
                         penal_count=penal_count,
                         admin_count=admin_count,
                         conciliacion_count=conciliacion_count,
                         archivo_count=archivo_count,
                         expedientes_recientes=expedientes_recientes,
                         audiencias_hoy=audiencias_hoy,
                         audiencias_manana=audiencias_manana,
                         audiencias_semana=audiencias_semana,
                         proximas_audiencias=proximas_audiencias,
                         espacio_drive=espacio_drive,
                         form_busqueda=form_busqueda)
# ============================================
# RUTAS DE EXPEDIENTES
# ============================================

@bp.route('/expedientes', methods=['GET'])
@requiere_login
@no_cache
def expedientes():
    """Lista todos los expedientes con búsqueda y filtros"""

    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para ver expedientes', 'error')
        return redirect(url_for('main.index'))

    buscar_numero = request.args.get('buscar_numero', '').strip()
    buscar_cliente = request.args.get('buscar_cliente', '').strip()
    filtro_tipo = request.args.get('filtro_tipo', '').strip()
    filtro_estado = request.args.get('filtro_estado', '').strip()

    query = Expediente.query

    if buscar_numero:
        query = query.filter(
            db.or_(
                Expediente.numero_expediente.ilike(f'%{buscar_numero}%'),
                Expediente.dni.ilike(f'%{buscar_numero}%')
            )
        )

    if buscar_cliente:
        query = query.filter(Expediente.cliente.ilike(f'%{buscar_cliente}%'))

    if filtro_tipo:
        query = query.filter(Expediente.tipo == filtro_tipo)

    if filtro_estado:
        query = query.filter(Expediente.estado == filtro_estado)

    expedientes = query.order_by(Expediente.fecha_registro.desc()).all()

    return render_template('expedientes.html',
                         title='Gestión de Expedientes',
                         expedientes=expedientes,
                         rol=session.get('rol', 'USUARIO'))


@bp.route('/expedientes/tipo/<string:tipo>')
@requiere_login
@no_cache
def expedientes_por_tipo(tipo):
    """Listado de expedientes filtrados por tipo"""

    tipos_permitidos = ['civil', 'penal', 'administrativo', 'conciliacion', 'archivo']
    if tipo not in tipos_permitidos:
        flash('Tipo de expediente no válido', 'error')
        return redirect(url_for('main.expedientes'))

    if not puede_ver_modulo(tipo):
        flash(f'No tiene permisos para ver expedientes de {tipo}', 'error')
        return redirect(url_for('main.index'))

    lista_expedientes = Expediente.query.filter_by(tipo=tipo).order_by(
        Expediente.fecha_registro.desc()
    ).all()

    titulos = {
        'civil': 'Expedientes de Derecho Civil',
        'penal': 'Expedientes de Derecho Penal',
        'administrativo': 'Expedientes Administrativos',
        'conciliacion': 'Expedientes de Conciliación',
        'archivo': 'Expedientes en Archivo'
    }

    return render_template('expedientes.html',
                         title=titulos.get(tipo, 'Expedientes'),
                         expedientes=lista_expedientes,
                         rol=session.get('rol', 'USUARIO'),
                         filtro_tipo=tipo,
                         total_expedientes=len(lista_expedientes))


def verificar_unicidad_expediente(numero_expediente, tipo, id_excluir=None):
    """Verifica que el número de expediente sea único para el tipo (excepto administrativos)"""
    if tipo == 'administrativo':
        return True, None

    query = Expediente.query.filter(
        Expediente.tipo == tipo,
        Expediente.numero_expediente == numero_expediente.strip()
    )

    if id_excluir:
        query = query.filter(Expediente.id != id_excluir)

    existe = query.first()

    if existe:
        return False, f'El N° de Expediente "{numero_expediente}" ya existe en otro caso {tipo}'

    return True, None

@bp.route('/expediente/nuevo', methods=['GET', 'POST'])
@requiere_login
@no_cache
def nuevo_expediente():
    """Formulario para crear nuevo expediente"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para crear expedientes', 'error')
        return redirect(url_for('main.index'))

    form = ExpedienteForm()

    if form.validate_on_submit():
        try:
            if form.tipo.data != 'administrativo':
                es_unico, mensaje_error = verificar_unicidad_expediente(
                    form.numero_expediente.data, 
                    form.tipo.data
                )
                if not es_unico:
                    flash(mensaje_error, 'error')
                    return render_template('nuevo_expediente.html',
                                         title='Nuevo Expediente',
                                         form=form,
                                         rol=session.get('rol', 'USUARIO'))

            expediente = Expediente(
                tipo=form.tipo.data,
                numero_expediente=form.numero_expediente.data,
                cliente=form.cliente.data,
                telefono=form.telefono.data,
                materia=form.materia.data,
                descripcion=form.descripcion.data,
                dni=form.dni.data,
                entidad_receptora=form.entidad_receptora.data,
                tramite=form.tramite.data,
                secretario=form.secretario.data,
                juez=form.juez.data,
                juzgado=form.juzgado.data,
                numero_cf=form.numero_cf.data,
                fiscal=form.fiscal.data,
                conciliador=form.conciliador.data,
                solicitante=form.solicitante.data,
                invitados=form.invitados.data,
                ubicacion_archivo=form.ubicacion_archivo.data,
                usuario_registro=session.get('nombre', 'Sistema'),
                estado_actual='ingresado'
            )

            db.session.add(expediente)
            db.session.commit()

            estado_inicial = EstadoHistorial(
                expediente_id=expediente.id,
                estado='ingresado',
                descripcion='Expediente registrado en el sistema',
                usuario=session.get('nombre', 'Sistema')
            )
            db.session.add(estado_inicial)
            db.session.commit()

            flash(f'Expediente {expediente.get_identificador_principal()} creado correctamente (ID: {expediente.id})', 'success')
            return redirect(url_for('main.expedientes'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear expediente: {str(e)}', 'error')
            import traceback
            traceback.print_exc()

    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'error')

    return render_template('nuevo_expediente.html',
                         title='Nuevo Expediente',
                         form=form,
                         rol=session.get('rol', 'USUARIO'))

@bp.route('/expediente/<int:id>')
@requiere_login
@no_cache
def ver_expediente(id):
    """Ver detalle de un expediente específico"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para ver expedientes', 'error')
        return redirect(url_for('main.index'))

    form_estado = EstadoForm()

    expediente = Expediente.query.get_or_404(id)
    historial = EstadoHistorial.query.filter_by(
        expediente_id=id
    ).order_by(EstadoHistorial.fecha.desc()).all()

    audiencias = Audiencia.query.filter_by(
        expediente_id=id
    ).order_by(Audiencia.fecha.desc(), Audiencia.hora.desc()).all()

    return render_template('expediente_detalle.html',
                         title=f'Expediente {expediente.get_identificador_principal()}',
                         expediente=expediente,
                         historial=historial,
                         audiencias=audiencias,
                         form_estado=form_estado,
                         rol=session.get('rol', 'USUARIO'))

@bp.route('/expediente/<int:id>/eliminar', methods=['POST'])
@requiere_login
@no_cache
def eliminar_expediente(id):
    """Eliminar un expediente completo (solo ADMINISTRADOR o DESARROLLADOR)"""
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para eliminar expedientes', 'error')
        return redirect(url_for('main.ver_expediente', id=id))

    expediente = Expediente.query.get_or_404(id)

    try:
        # Eliminar documentos de Drive primero
        documentos = Documento.query.filter_by(expediente_id=id).all()
        for doc in documentos:
            if doc.drive_file_id:
                try:
                    eliminar_archivo_drive(doc.drive_file_id)
                except Exception as e:
                    print(f"Error eliminando doc {doc.id} de Drive: {e}")

        # Eliminar registros relacionados
        EstadoHistorial.query.filter_by(expediente_id=id).delete()
        Audiencia.query.filter_by(expediente_id=id).delete()
        Documento.query.filter_by(expediente_id=id).delete()
        Notificacion.query.filter_by(expediente_id=id).delete()

        identificador = expediente.get_identificador_principal()
        db.session.delete(expediente)
        db.session.commit()

        flash(f'Expediente {identificador} eliminado correctamente', 'success')
        return redirect(url_for('main.expedientes'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar expediente: {str(e)}', 'error')
        return redirect(url_for('main.ver_expediente', id=id))

@bp.route('/expediente/<int:id>/editar', methods=['GET', 'POST'])
@requiere_login
@no_cache
def editar_expediente(id):
    """Editar un expediente existente"""
    expediente = Expediente.query.get_or_404(id)

    if request.method == 'POST':
        try:
            tipo_original = expediente.tipo

            numero_expediente = request.form.get('numero_expediente', '').strip()
            dni = request.form.get('dni', '').strip() or None
            telefono = request.form.get('telefono', '').strip()
            descripcion = request.form.get('descripcion', '').strip()

            cliente = request.form.get('cliente', '').strip()
            solicitante = request.form.get('solicitante', '').strip()

            if tipo_original == 'conciliacion' and not cliente and solicitante:
                cliente = solicitante

            if not cliente:
                flash('El cliente es obligatorio', 'error')
                return redirect(url_for('main.editar_expediente', id=id))

            expediente.cliente = cliente
            expediente.telefono = telefono
            expediente.descripcion = descripcion

            if tipo_original == 'administrativo':
                dni_val = request.form.get('dni', '').strip()

                if not dni_val:
                    flash('El DNI es obligatorio para casos administrativos', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                materia = request.form.get('materia', '').strip()
                if not materia:
                    flash('La materia es obligatoria', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                expediente.dni = dni_val
                expediente.numero_expediente = '-'
                expediente.materia = materia
                expediente.entidad_receptora = request.form.get('entidad_receptora', '').strip()
                expediente.tramite = request.form.get('tramite', '').strip()

                expediente.juzgado = None
                expediente.juez = None
                expediente.secretario = None
                expediente.numero_cf = None
                expediente.fiscal = None
                expediente.conciliador = None
                expediente.solicitante = None
                expediente.invitados = None
                expediente.ubicacion_archivo = None

            elif tipo_original == 'civil':
                numero_exp = request.form.get('numero_expediente', '').strip()

                if not numero_exp:
                    flash('El N° de Expediente es obligatorio para casos civiles', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                materia = request.form.get('materia', '').strip()
                if not materia:
                    flash('La materia es obligatoria', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                existe = Expediente.query.filter(
                    Expediente.tipo == 'civil',
                    Expediente.numero_expediente == numero_exp,
                    Expediente.id != id
                ).first()

                if existe:
                    flash(f'El N° de Expediente "{numero_exp}" ya existe en otro caso civil', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                expediente.numero_expediente = numero_exp
                expediente.dni = None
                expediente.materia = materia
                expediente.juzgado = None
                expediente.juez = request.form.get('juez', '').strip()
                expediente.secretario = request.form.get('secretario', '').strip()

                expediente.entidad_receptora = None
                expediente.tramite = None
                expediente.numero_cf = None
                expediente.fiscal = None
                expediente.conciliador = None
                expediente.solicitante = None
                expediente.invitados = None
                expediente.ubicacion_archivo = None

            elif tipo_original == 'penal':
                numero_exp = request.form.get('numero_expediente', '').strip()

                if not numero_exp:
                    flash('El N° de Expediente es obligatorio para casos penales', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                materia = request.form.get('materia', '').strip()
                if not materia:
                    flash('La materia es obligatoria', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                existe = Expediente.query.filter(
                    Expediente.tipo == 'penal',
                    Expediente.numero_expediente == numero_exp,
                    Expediente.id != id
                ).first()

                if existe:
                    flash(f'El N° de Expediente "{numero_exp}" ya existe en otro caso penal', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                expediente.numero_expediente = numero_exp
                expediente.dni = dni
                expediente.materia = materia
                expediente.numero_cf = request.form.get('numero_cf', '').strip()
                expediente.fiscal = request.form.get('fiscal', '').strip()
                expediente.juzgado = request.form.get('juzgado', '').strip()

                expediente.entidad_receptora = None
                expediente.tramite = None
                expediente.juez = None
                expediente.secretario = None
                expediente.conciliador = None
                expediente.solicitante = None
                expediente.invitados = None
                expediente.ubicacion_archivo = None

            elif tipo_original == 'conciliacion':
                numero_exp = request.form.get('numero_expediente', '').strip()

                if not numero_exp:
                    flash('El N° de Expediente es obligatorio para casos de conciliación', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                materia = request.form.get('materia', '').strip()
                if not materia:
                    flash('La materia es obligatoria', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                existe = Expediente.query.filter(
                    Expediente.tipo == 'conciliacion',
                    Expediente.numero_expediente == numero_exp,
                    Expediente.id != id
                ).first()

                if existe:
                    flash(f'El N° de Expediente "{numero_exp}" ya existe en otro caso de conciliación', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                expediente.numero_expediente = numero_exp
                expediente.dni = dni
                expediente.materia = materia
                expediente.conciliador = request.form.get('conciliador', '').strip()
                expediente.solicitante = solicitante
                expediente.invitados = request.form.get('invitados', '').strip()

                expediente.entidad_receptora = None
                expediente.tramite = None
                expediente.juzgado = None
                expediente.juez = None
                expediente.secretario = None
                expediente.numero_cf = None
                expediente.fiscal = None
                expediente.ubicacion_archivo = None

            elif tipo_original == 'archivo':
                numero_exp = request.form.get('numero_expediente', '').strip()

                if not numero_exp:
                    flash('El N° de Expediente es obligatorio para casos de archivo', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                materia = request.form.get('materia', '').strip()
                if not materia:
                    flash('La materia es obligatoria', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                existe = Expediente.query.filter(
                    Expediente.tipo == 'archivo',
                    Expediente.numero_expediente == numero_exp,
                    Expediente.id != id
                ).first()

                if existe:
                    flash(f'El N° de Expediente "{numero_exp}" ya existe en otro caso de archivo', 'error')
                    return redirect(url_for('main.editar_expediente', id=id))

                expediente.numero_expediente = numero_exp
                expediente.dni = dni
                expediente.materia = materia
                expediente.ubicacion_archivo = request.form.get('ubicacion_archivo', '').strip()

                expediente.entidad_receptora = None
                expediente.tramite = None
                expediente.juzgado = None
                expediente.juez = None
                expediente.secretario = None
                expediente.numero_cf = None
                expediente.fiscal = None
                expediente.conciliador = None
                expediente.solicitante = None
                expediente.invitados = None

            historial = EstadoHistorial(
                expediente_id=expediente.id,
                estado='Expediente editado',
                descripcion=f'Expediente editado por {session.get("usuario", "Sistema")}',
                usuario=session.get('usuario', 'Sistema')
            )
            db.session.add(historial)

            db.session.commit()
            flash('Expediente actualizado correctamente', 'success')
            return redirect(url_for('main.ver_expediente', id=expediente.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
            return redirect(url_for('main.editar_expediente', id=id))

    form = ExpedienteForm()

    return render_template('editar_expediente.html', 
                         expediente=expediente, 
                         form=form,
                         title='Editar Expediente')

@bp.route('/expediente/<int:id>/estado', methods=['POST'])
@requiere_login
@no_cache
def agregar_estado(id):
    """Agregar nuevo estado a un expediente"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para modificar expedientes', 'error')
        return redirect(url_for('main.index'))

    form = EstadoForm()

    if form.validate_on_submit():
        try:
            nuevo_estado = EstadoHistorial(
                expediente_id=id,
                estado=form.estado.data,
                descripcion=form.descripcion.data,
                usuario=session.get('nombre', 'Sistema')
            )
            db.session.add(nuevo_estado)

            expediente = Expediente.query.get_or_404(id)
            expediente.estado_actual = form.estado.data
            expediente.fecha_actualizacion = datetime.now()

            db.session.commit()

            flash('Estado agregado correctamente', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al agregar estado: {str(e)}', 'error')
    else:
        flash('Error al agregar estado. Verifique los datos.', 'error')

    return redirect(url_for('main.ver_expediente', id=id))

# ============================================
# RUTAS DE BÚSQUEDA
# ============================================

@bp.route('/buscar', methods=['GET', 'POST'])
@requiere_login
@no_cache
def buscar():
    """Buscar expedientes por N° de Expediente o DNI"""
    form = BusquedaForm()

    if form.validate_on_submit():
        tipo_busqueda = form.tipo_busqueda.data
        termino = form.termino.data.strip()

        if tipo_busqueda == 'expediente':
            expedientes = Expediente.query.filter(
                Expediente.numero_expediente.ilike(f'%{termino}%')
            ).order_by(Expediente.fecha_registro.desc()).all()
        else:
            expedientes = Expediente.query.filter(
                Expediente.dni.ilike(f'%{termino}%')
            ).order_by(Expediente.fecha_registro.desc()).all()

        if not expedientes:
            flash(f'No se encontraron expedientes con {tipo_busqueda}: {termino}', 'warning')
            return redirect(url_for('main.index'))

        if len(expedientes) == 1:
            return redirect(url_for('main.ver_expediente', id=expedientes[0].id))

        return render_template('expedientes.html',
                             title='Resultados de Búsqueda',
                             expedientes=expedientes,
                             rol=session.get('rol', 'USUARIO'),
                             busqueda=True,
                             termino=termino,
                             tipo_busqueda=tipo_busqueda)

    return redirect(url_for('main.index'))
# ============================================
# RUTAS DE GESTIÓN DE USUARIOS - COMPLETAS
# ============================================

@bp.route('/admin/usuarios')
@requiere_login
@no_cache
def gestion_usuarios_admin():
    """
    ADMINISTRADOR: 
    - Puede crear usuarios (no administradores)
    - Puede eliminar usuarios (no desarrollador ni otros admins)
    """
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para acceder a esta sección', 'error')
        return redirect(url_for('main.index'))

    if session.get('rol') == 'DESARROLLADOR':
        return redirect(url_for('main.gestion_usuarios_dev'))

    usuarios_db = {}
    for u in Usuario.query.filter_by(activo=True).all():
        usuarios_db[u.username] = {
            'nombre': u.nombre,
            'rol': u.rol,
            'modulos': u.get_modulos_list(),
            'email': u.email,
            'fecha_registro': u.fecha_registro
        }

    return render_template('admin_usuarios.html',
                         title='Gestión de Usuarios',
                         usuarios=usuarios_db,
                         rol=session.get('rol', 'USUARIO'))

@bp.route('/dev/usuarios')
@requiere_login
@no_cache
def gestion_usuarios_dev():
    """
    DESARROLLADOR:
    - Vista completa de todos los usuarios
    - Puede crear administradores y usuarios
    - Puede eliminar cualquier usuario
    """
    if session.get('rol') != 'DESARROLLADOR':
        flash('No tiene permisos para acceder a esta sección', 'error')
        return redirect(url_for('main.index'))

    usuarios_db = {}
    for u in Usuario.query.filter_by(activo=True).all():
        usuarios_db[u.username] = {
            'nombre': u.nombre,
            'rol': u.rol,
            'modulos': u.get_modulos_list(),
            'email': u.email,
            'fecha_registro': u.fecha_registro
        }

    return render_template('admin_usuarios_dev.html',
                         title='Gestión de Usuarios - Desarrollador',
                         usuarios=usuarios_db,
                         rol=session.get('rol', 'USUARIO'))

@bp.route('/api/usuario/<username>')
@requiere_login
@no_cache
def api_obtener_usuario(username):
    """API para obtener datos de un usuario específico desde Supabase"""
    rol_actual = session.get('rol')

    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    usuario = _get_usuario(username)
    if not usuario:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404

    if rol_actual == 'ADMINISTRADOR':
        if usuario.rol == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede ver detalles del desarrollador'}), 403
        if usuario.rol == 'ADMINISTRADOR' and username != session.get('usuario'):
            return jsonify({'success': False, 'error': 'No puede ver detalles de otros administradores'}), 403

    return jsonify({
        'success': True,
        'username': usuario.username,
        'nombre': usuario.nombre,
        'rol': usuario.rol,
        'modulos': usuario.get_modulos_list(),
        'email': usuario.email
    })

@bp.route('/api/usuario/crear', methods=['POST'])
@requiere_login
@no_cache
def api_crear_usuario():
    """API para crear usuarios en Supabase (tabla usuario)"""
    rol_actual = session.get('rol')

    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    data = request.get_json()
    username = data.get('username', '').strip().lower()
    nombre = data.get('nombre', '').strip()
    password = data.get('password', '').strip()
    rol_nuevo = data.get('rol', 'USUARIO')
    modulos = data.get('modulos', ['civil'])
    email = data.get('email', '').strip()

    if not username or not nombre or not password:
        return jsonify({'success': False, 'error': 'Datos incompletos'}), 400

    if Usuario.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'El usuario ya existe'}), 400

    if rol_actual == 'ADMINISTRADOR':
        if rol_nuevo in ['ADMINISTRADOR', 'DESARROLLADOR']:
            return jsonify({'success': False, 'error': 'No puede crear administradores o desarrolladores'}), 403

    try:
        nuevo = Usuario(
            username=username,
            nombre=nombre,
            email=email or f'{username}@quijandria.com',
            rol=rol_nuevo
        )
        nuevo.set_password(password)
        nuevo.set_modulos_list(modulos if isinstance(modulos, list) else [modulos])

        db.session.add(nuevo)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Usuario creado correctamente en Supabase'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/api/usuario/eliminar/<username>', methods=['DELETE'])
@requiere_login
@no_cache
def api_eliminar_usuario(username):
    """API para eliminar usuarios en Supabase (soft delete)"""
    rol_actual = session.get('rol')

    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    if username == session.get('usuario'):
        return jsonify({'success': False, 'error': 'No puede eliminarse a sí mismo'}), 400

    usuario = _get_usuario(username)
    if not usuario:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404

    if rol_actual == 'ADMINISTRADOR':
        if usuario.rol == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede eliminar al desarrollador'}), 403
        if usuario.rol == 'ADMINISTRADOR':
            return jsonify({'success': False, 'error': 'No puede eliminar a otros administradores'}), 403

    try:
        usuario.activo = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'Usuario eliminado correctamente'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/api/usuario/editar/<username>', methods=['PUT'])
@requiere_login
@no_cache
def api_editar_usuario(username):
    """API para editar usuarios en Supabase"""
    rol_actual = session.get('rol')

    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    usuario = _get_usuario(username)
    if not usuario:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404

    data = request.get_json()

    if rol_actual == 'ADMINISTRADOR':
        if usuario.rol == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede editar al desarrollador'}), 403
        if usuario.rol == 'ADMINISTRADOR' and username != session.get('usuario'):
            return jsonify({'success': False, 'error': 'No puede editar a otros administradores'}), 403

        nuevo_rol = data.get('rol')
        if nuevo_rol in ['ADMINISTRADOR', 'DESARROLLADOR']:
            return jsonify({'success': False, 'error': 'No puede asignar ese rol'}), 403

    try:
        if 'nombre' in data:
            usuario.nombre = data['nombre']
        if 'password' in data and data['password']:
            usuario.set_password(data['password'])
        if 'modulos' in data:
            usuario.set_modulos_list(data['modulos'] if isinstance(data['modulos'], list) else [data['modulos']])
        if 'email' in data:
            usuario.email = data['email']
        if 'rol' in data and rol_actual == 'DESARROLLADOR':
            usuario.rol = data['rol']

        db.session.commit()
        return jsonify({'success': True, 'message': 'Usuario actualizado correctamente'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# RUTAS DE AUDIENCIAS - MÓDULO AUDIENCIAS
# ============================================

@bp.route('/audiencias')
@requiere_login
@no_cache
def audiencias():
    """Calendario y listado de audiencias"""
    if not puede_ver_modulo('audiencias'):
        flash('No tiene permisos para ver audiencias', 'error')
        return redirect(url_for('main.index'))

    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    tipo_filtro = request.args.get('tipo', '')
    estado_filtro = request.args.get('estado', '')

    query = Audiencia.query

    if fecha_desde:
        try:
            desde = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(Audiencia.fecha >= desde)
        except:
            pass

    if fecha_hasta:
        try:
            hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(Audiencia.fecha <= hasta)
        except:
            pass

    if tipo_filtro:
        query = query.filter_by(tipo_audiencia=tipo_filtro)

    if estado_filtro:
        query = query.filter_by(estado=estado_filtro)

    query = query.order_by(Audiencia.fecha, Audiencia.hora)
    lista_audiencias = query.all()

    form_busqueda = BusquedaAudienciaForm()

    hoy = date.today()
    total_programadas = Audiencia.query.filter_by(estado='programada').count()
    audiencias_hoy = Audiencia.query.filter(
        db.func.date(Audiencia.fecha) == hoy,
        Audiencia.estado == 'programada'
    ).count()
    audiencias_semana = Audiencia.query.filter(
        Audiencia.fecha >= hoy,
        Audiencia.fecha <= hoy + timedelta(days=7),
        Audiencia.estado == 'programada'
    ).count()

    return render_template('audiencias.html',
                         title='Calendario de Audiencias',
                         audiencias=lista_audiencias,
                         form_busqueda=form_busqueda,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         tipo_filtro=tipo_filtro,
                         estado_filtro=estado_filtro,
                         total_programadas=total_programadas,
                         audiencias_hoy=audiencias_hoy,
                         audiencias_semana=audiencias_semana,
                         rol=session.get('rol', 'USUARIO'),
                         hoy=hoy)


@bp.route('/audiencia/nueva', methods=['GET', 'POST'])
@requiere_login
@no_cache
def nueva_audiencia():
    """Programar nueva audiencia (sin expediente pre-seleccionado)"""
    if not puede_ver_modulo('audiencias'):
        flash('No tiene permisos para programar audiencias', 'error')
        return redirect(url_for('main.index'))

    form = AudienciaForm()

    try:
        expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()
    except Exception as e:
        expedientes = []
        flash(f'Error al cargar expedientes: {str(e)}', 'warning')

    if request.method == 'POST':
        try:
            expediente_id_str = request.form.get('expediente_id', '0')
            try:
                expediente_id = int(expediente_id_str)
            except ValueError:
                expediente_id = 0

            if expediente_id == 0:
                flash('Debe seleccionar un expediente', 'error')
                return render_template('nueva_audiencia.html',
                                     title='Programar Audiencia',
                                     form=form,
                                     expedientes=expedientes,
                                     rol=session.get('rol', 'USUARIO'))

            expediente = Expediente.query.get(expediente_id)
            if not expediente:
                flash('El expediente seleccionado no existe', 'error')
                return render_template('nueva_audiencia.html',
                                     title='Programar Audiencia',
                                     form=form,
                                     expedientes=expedientes,
                                     rol=session.get('rol', 'USUARIO'))

            fecha_audiencia = form.fecha.data
            if not fecha_audiencia:
                flash('Debe ingresar una fecha', 'error')
                return render_template('nueva_audiencia.html',
                                     title='Programar Audiencia',
                                     form=form,
                                     expedientes=expedientes,
                                     rol=session.get('rol', 'USUARIO'))

            if fecha_audiencia < date.today():
                flash('No puede programar audiencias en fechas pasadas', 'error')
                return render_template('nueva_audiencia.html',
                                     title='Programar Audiencia',
                                     form=form,
                                     expedientes=expedientes,
                                     rol=session.get('rol', 'USUARIO'))

            hora_audiencia = form.hora.data
            if not hora_audiencia:
                flash('Debe ingresar una hora', 'error')
                return render_template('nueva_audiencia.html',
                                     title='Programar Audiencia',
                                     form=form,
                                     expedientes=expedientes,
                                     rol=session.get('rol', 'USUARIO'))

            nueva_audiencia = Audiencia(
                expediente_id=expediente_id,
                fecha=fecha_audiencia,
                hora=hora_audiencia,
                tipo_audiencia=form.tipo_audiencia.data,
                lugar=form.lugar.data or '',
                sala=form.sala.data or '',
                magistrado=form.magistrado.data or '',
                link_videollamada=form.link_videollamada.data or '',
                observaciones=form.observaciones.data or '',
                estado='programada',
                recordatorio_dias=form.recordatorio_dias.data or 1,
                usuario_registro=session.get('nombre', 'Sistema')
            )

            db.session.add(nueva_audiencia)
            db.session.commit()

            if expediente.estado_actual != 'audiencia_programada':
                expediente.estado_actual = 'audiencia_programada'

                historial = EstadoHistorial(
                    expediente_id=expediente_id,
                    estado='audiencia_programada',
                    descripcion=f'Audiencia programada para el {nueva_audiencia.get_fecha_hora_formateada()}',
                    usuario=session.get('nombre', 'Sistema')
                )
                db.session.add(historial)
                db.session.commit()

            flash(f'📅 Audiencia programada correctamente para el {nueva_audiencia.get_fecha_hora_formateada()}', 'success')
            return redirect(url_for('main.audiencias'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al programar audiencia: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
            return render_template('nueva_audiencia.html',
                                 title='Programar Audiencia',
                                 form=form,
                                 expedientes=expedientes,
                                 rol=session.get('rol', 'USUARIO'))

    return render_template('nueva_audiencia.html',
                         title='Programar Audiencia',
                         form=form,
                         expedientes=expedientes,
                         rol=session.get('rol', 'USUARIO'))


@bp.route('/expediente/<int:id>/audiencia/nueva', methods=['GET', 'POST'])
@requiere_login
@no_cache
def nueva_audiencia_expediente(id):
    """Programar audiencia desde un expediente específico"""
    if not puede_ver_modulo('audiencias'):
        flash('No tiene permisos para programar audiencias', 'error')
        return redirect(url_for('main.index'))

    expediente = Expediente.query.get_or_404(id)
    form = AudienciaForm()

    if form.validate_on_submit():
        try:
            fecha_audiencia = form.fecha.data
            if fecha_audiencia < date.today():
                flash('No puede programar audiencias en fechas pasadas', 'error')
                return render_template('nueva_audiencia.html',
                                     title=f'Programar Audiencia - {expediente.get_identificador_principal()}',
                                     form=form,
                                     expediente=expediente,
                                     rol=session.get('rol', 'USUARIO'))

            nueva_audiencia = Audiencia(
                expediente_id=id,
                fecha=fecha_audiencia,
                hora=form.hora.data,
                tipo_audiencia=form.tipo_audiencia.data,
                lugar=form.lugar.data,
                sala=form.sala.data,
                magistrado=form.magistrado.data,
                link_videollamada=form.link_videollamada.data,
                observaciones=form.observaciones.data,
                estado='programada',
                recordatorio_dias=form.recordatorio_dias.data,
                usuario_registro=session.get('nombre', 'Sistema')
            )

            db.session.add(nueva_audiencia)
            db.session.commit()

            if expediente.estado_actual != 'audiencia_programada':
                expediente.estado_actual = 'audiencia_programada'

                historial = EstadoHistorial(
                    expediente_id=id,
                    estado='audiencia_programada',
                    descripcion=f'Audiencia programada para el {nueva_audiencia.get_fecha_hora_formateada()}',
                    usuario=session.get('nombre', 'Sistema')
                )
                db.session.add(historial)
                db.session.commit()

            flash(f'📅 Audiencia programada correctamente', 'success')
            return redirect(url_for('main.ver_expediente', id=id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al programar audiencia: {str(e)}', 'error')

    return render_template('nueva_audiencia.html',
                         title=f'Programar Audiencia - {expediente.get_identificador_principal()}',
                         form=form,
                         expediente=expediente,
                         rol=session.get('rol', 'USUARIO'))


@bp.route('/audiencia/<int:id>')
@requiere_login
@no_cache
def ver_audiencia(id):
    """Ver detalle de una audiencia"""
    if not puede_ver_modulo('audiencias'):
        flash('No tiene permisos para ver audiencias', 'error')
        return redirect(url_for('main.index'))

    audiencia = Audiencia.query.get_or_404(id)

    return render_template('audiencia_detalle.html',
                         title=f'Audiencia - {audiencia.get_fecha_hora_formateada()}',
                         audiencia=audiencia,
                         rol=session.get('rol', 'USUARIO'))


@bp.route('/audiencia/<int:id>/editar', methods=['GET', 'POST'])
@requiere_login
@no_cache
def editar_audiencia(id):
    """Editar una audiencia programada"""
    if not puede_ver_modulo('audiencias'):
        flash('No tiene permisos para editar audiencias', 'error')
        return redirect(url_for('main.index'))

    audiencia = Audiencia.query.get_or_404(id)
    form = AudienciaForm(obj=audiencia)

    if form.validate_on_submit():
        try:
            audiencia.fecha = form.fecha.data
            audiencia.hora = form.hora.data
            audiencia.tipo_audiencia = form.tipo_audiencia.data
            audiencia.lugar = form.lugar.data
            audiencia.sala = form.sala.data
            audiencia.magistrado = form.magistrado.data
            audiencia.link_videollamada = form.link_videollamada.data
            audiencia.observaciones = form.observaciones.data
            audiencia.recordatorio_dias = form.recordatorio_dias.data
            audiencia.fecha_actualizacion = datetime.now()

            db.session.commit()

            flash('Audiencia actualizada correctamente', 'success')
            return redirect(url_for('main.ver_audiencia', id=id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'error')

    return render_template('editar_audiencia.html',
                         title='Editar Audiencia',
                         form=form,
                         audiencia=audiencia,
                         rol=session.get('rol', 'USUARIO'))


@bp.route('/audiencia/<int:id>/estado', methods=['POST'])
@requiere_login
@no_cache
def cambiar_estado_audiencia(id):
    """Cambiar estado de una audiencia (realizada, aplazada, cancelada)"""
    if not puede_ver_modulo('audiencias'):
        flash('No tiene permisos para modificar audiencias', 'error')
        return redirect(url_for('main.index'))

    audiencia = Audiencia.query.get_or_404(id)
    nuevo_estado = request.form.get('estado', '')

    estados_validos = ['programada', 'realizada', 'aplazada', 'cancelada', 'pendiente']

    if nuevo_estado in estados_validos:
        try:
            audiencia.estado = nuevo_estado
            audiencia.fecha_actualizacion = datetime.now()
            db.session.commit()

            if nuevo_estado == 'aplazada':
                flash('Audiencia marcada como aplazada. Programe una nueva fecha.', 'warning')
            else:
                flash(f'Audiencia marcada como: {audiencia.get_estado_label()}', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    else:
        flash('Estado no válido', 'error')

    return redirect(url_for('main.ver_audiencia', id=id))


@bp.route('/audiencia/<int:id>/eliminar', methods=['POST'])
@requiere_login
@no_cache
def eliminar_audiencia(id):
    """Eliminar una audiencia"""
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para eliminar audiencias', 'error')
        return redirect(url_for('main.audiencias'))

    audiencia = Audiencia.query.get_or_404(id)
    expediente_id = audiencia.expediente_id

    try:
        db.session.delete(audiencia)
        db.session.commit()

        flash('Audiencia eliminada correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar: {str(e)}', 'error')

    referer = request.headers.get('Referer', '')
    if 'expediente' in referer:
        return redirect(url_for('main.ver_expediente', id=expediente_id))

    return redirect(url_for('main.audiencias'))
# ============================================
# RUTAS DE DOCUMENTOS - MÓDULO DOCUMENTOS
# ============================================
# CONFIGURACIÓN: Solo Google Drive con Service Account (sin almacenamiento local)
# LÓGICA DUAL:
#   1. ELIMINACIÓN NORMAL: Elimina de Drive + Supabase (todo)
#   2. ARCHIVADO/LIBERAR ESPACIO: Solo elimina de Drive, marca como 'archivado_local' en Supabase
#      (mantiene historial de búsqueda, muestra "Documento archivado en oficina")

import os
from werkzeug.utils import secure_filename

def get_expedientes_choices():
    expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()
    choices = [(0, 'Ninguno / Documento General')]
    for exp in expedientes:
        choices.append((exp.id, f"{exp.get_identificador_principal()} - {exp.cliente}"))
    return choices


@bp.route('/documentos')
@requiere_login
@no_cache
def documentos():
    """Listado de todos los documentos"""
    if not puede_ver_modulo('documentos'):
        flash('No tiene permisos para ver documentos', 'error')
        return redirect(url_for('main.index'))

    page = request.args.get('page', 1, type=int)
    per_page = 20

    categoria_filtro = request.args.get('categoria', '')
    expediente_filtro = request.args.get('expediente_id', 0, type=int)
    termino_busqueda = request.args.get('q', '')

    query = Documento.query

    if categoria_filtro:
        query = query.filter_by(categoria=categoria_filtro)

    if expediente_filtro:
        query = query.filter_by(expediente_id=expediente_filtro)

    if termino_busqueda:
        query = query.filter(Documento.titulo.ilike(f'%{termino_busqueda}%'))

    query = query.order_by(Documento.fecha_subida.desc())

    documentos_paginados = query.paginate(page=page, per_page=per_page, error_out=False)

    form_busqueda = BusquedaDocumentoForm()
    form_busqueda.expediente_id.choices = get_expedientes_choices()

    return render_template('documentos.html',
                         title='Gestión de Documentos',
                         documentos=documentos_paginados,
                         form_busqueda=form_busqueda,
                         categoria_filtro=categoria_filtro,
                         expediente_filtro=expediente_filtro,
                         termino_busqueda=termino_busqueda,
                         rol=session.get('rol', 'USUARIO'))


# ============================================
# SUBIR DOCUMENTO (REDIRECCIÓN AUTOMÁTICA A DRIVE)
# ============================================

@bp.route('/documento/subir', methods=['GET', 'POST'])
@requiere_login
@no_cache
def subir_documento():
    """
    Todos los documentos se suben a Google Drive corporativo.
    Redirección automática a subir_documento_drive.
    """
    if not puede_ver_modulo('documentos'):
        flash('No tiene permisos para subir documentos', 'error')
        return redirect(url_for('main.index'))

    # Todos los documentos van al Drive corporativo del estudio
    return redirect(url_for('main.subir_documento_drive'))


# ============================================
# SUBIR DOCUMENTO A GOOGLE DRIVE (SERVICE ACCOUNT)
# ============================================

@bp.route('/subir-documento-drive', methods=['GET', 'POST'])
@requiere_login
def subir_documento_drive():
    """
    Sube documento al Drive corporativo del estudio.
    Usa Service Account - ningún usuario necesita login de Google.
    """
    if not puede_ver_modulo('documentos'):
        flash('No tiene permisos para subir documentos', 'error')
        return redirect(url_for('main.index'))

    if request.method == 'GET':
        form = DocumentoForm()
        form.expediente_id.choices = get_expedientes_choices()

        expediente_id = request.args.get('expediente_id', type=int)
        expediente = None
        if expediente_id:
            expediente = Expediente.query.get(expediente_id)

        expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()

        return render_template('subir_documento.html',
                             title='Subir a Google Drive',
                             form=form,
                             expediente=expediente,
                             expedientes=expedientes,
                             rol=session.get('rol', 'USUARIO'),
                             modo_drive=True)

    # POST: Procesar subida
    if 'archivo' not in request.files:
        flash('No se seleccionó archivo', 'danger')
        return redirect(request.referrer or url_for('main.documentos'))

    archivo = request.files['archivo']
    expediente_id = request.form.get('expediente_id', type=int)
    if expediente_id == 0:
        expediente_id = None

    if archivo.filename == '':
        flash('Nombre de archivo vacío', 'danger')
        return redirect(request.referrer or url_for('main.documentos'))

    try:
        # Verificar espacio antes de subir
        espacio = obtener_espacio_usado_drive()

        if espacio['porcentaje'] >= 80:
            flash(f'⚠️ Drive corporativo al {espacio["porcentaje"]:.1f}%. Contacte al administrador.', 'warning')
            return redirect(url_for('main.gestionar_espacio'))

        # Leer archivo
        file_content = archivo.read()
        mime_type = archivo.content_type or 'application/octet-stream'

        # Subir a Drive corporativo (service account - sin login usuario)
        resultado = subir_archivo_drive(file_content, archivo.filename, mime_type)

        # Guardar en base de datos
        fecha_doc = None
        if request.form.get('fecha_documento'):
            try:
                fecha_doc = datetime.strptime(request.form['fecha_documento'], '%Y-%m-%d').date()
            except:
                pass

        nuevo_documento = Documento(
            expediente_id=expediente_id,
            titulo=request.form.get('titulo', archivo.filename),
            nombre_archivo=archivo.filename,
            url_drive=resultado['url'],
            drive_file_id=resultado['id'],
            ubicacion='drive',
            categoria=request.form.get('categoria', 'otros'),
            descripcion=request.form.get('descripcion'),
            fecha_documento=fecha_doc,
            usuario_subida=session.get('nombre', 'Sistema'),
            tipo_archivo=archivo.filename.split('.')[-1].lower(),
            tamaño_bytes=len(file_content),
        )

        db.session.add(nuevo_documento)
        db.session.commit()

        flash('✅ Documento subido al Drive corporativo correctamente', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error subiendo a Drive: {str(e)}', 'danger')

    if expediente_id:
        return redirect(url_for('main.expediente_documentos', id=expediente_id))
    return redirect(url_for('main.documentos'))


# ============================================
# VER DOCUMENTO DESDE GOOGLE DRIVE
# ============================================

@bp.route('/documento/<int:id>/ver')
@requiere_login
@no_cache
def ver_documento(id):
    """Abre vista previa del documento en Google Drive"""
    documento = Documento.query.get_or_404(id)

    # Si está archivado localmente (liberación de espacio), mostrar mensaje especial
    if documento.ubicacion == 'archivado_local':
        flash('📁 Este documento ha sido archivado en la oficina. Consulte con el administrador.', 'info')
        return redirect(url_for('main.expediente_documentos', id=documento.expediente_id))

    # Verificar que tenga enlace a Drive
    if not documento.drive_file_id:
        flash('❌ Este documento no tiene vista previa disponible. El archivo puede haber sido eliminado de Drive.', 'warning')
        return redirect(url_for('main.expediente_documentos', id=documento.expediente_id))

    return render_template('ver_documento.html', documento=documento)


# ============================================
# ELIMINAR DOCUMENTO - ELIMINACIÓN COMPLETA (Drive + Supabase)
# ============================================
# ESTA FUNCIÓN ELIMINA TODO: del Drive, de Supabase, y registros relacionados
# Usar solo cuando se quiere borrar definitivamente un documento

@bp.route('/documento/<int:id>/eliminar', methods=['POST'])
@requiere_login
@no_cache
def eliminar_documento(id):
    """
    ELIMINACIÓN COMPLETA: Elimina documento del Drive + Supabase + registros relacionados.
    Solo Admin/Dev. Esta acción es IRREVERSIBLE.
    """
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para eliminar documentos', 'error')
        return redirect(url_for('main.documentos'))

    documento = Documento.query.get_or_404(id)
    expediente_id = documento.expediente_id

    try:
        # PASO 1: Eliminar de Google Drive si tiene file_id
        if documento.drive_file_id:
            try:
                eliminar_archivo_drive(documento.drive_file_id)
            except Exception as e:
                print(f"Advertencia: No se pudo eliminar de Drive (quizás ya no existe): {e}")

        # PASO 2: Eliminar registro de base de datos (Supabase)
        db.session.delete(documento)
        db.session.commit()

        flash('🗑️ Documento eliminado completamente (Drive + Sistema)', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar: {str(e)}', 'error')

    if expediente_id:
        return redirect(url_for('main.expediente_documentos', id=expediente_id))
    return redirect(url_for('main.documentos'))


# ============================================
# ELIMINAR DOCUMENTO DE DRIVE (SOLO DEL DRIVE, MANTIENE EN SUPABASE)
# ============================================
# ESTA FUNCIÓN solo elimina del Drive pero MANTIENE el registro en Supabase
# marcado como 'archivado_local'. Sirve para liberar espacio manteniendo historial.

@bp.route('/documento/<int:id>/eliminar-drive', methods=['POST'])
@requiere_login
@no_cache
def eliminar_documento_drive(id):
    """
    ELIMINACIÓN PARCIAL: Elimina solo del Drive, mantiene registro en Supabase como 'archivado_local'.
    El documento seguirá apareciendo en búsquedas con nota 'Archivado en oficina'.
    Solo Admin/Dev.
    """
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos', 'error')
        return redirect(url_for('main.documentos'))

    documento = Documento.query.get_or_404(id)

    try:
        # PASO 1: Eliminar SOLO de Google Drive
        if documento.drive_file_id:
            eliminar_archivo_drive(documento.drive_file_id)

        # PASO 2: MARCAR en Supabase como archivado_local (NO eliminar registro)
        # Esto mantiene el historial de búsqueda
        documento.ubicacion = 'archivado_local'
        documento.url_drive = None
        documento.drive_file_id = None
        # Agregar nota en descripción sobre archivado
        fecha_arch = datetime.now().strftime('%d/%m/%Y %H:%M')
        arch_note = f"[ARCHIVADO EN OFICINA - {fecha_arch} por {session.get('nombre', 'Sistema')}]"
        if documento.descripcion:
            documento.descripcion = f"{documento.descripcion}\n{arch_note}"
        else:
            documento.descripcion = arch_note

        db.session.commit()

        flash('📁 Documento eliminado del Drive. Registro mantenido en sistema como "Archivado en oficina".', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('main.expediente_documentos', id=documento.expediente_id))


# ============================================
# DOCUMENTOS DE UN EXPEDIENTE
# ============================================

@bp.route('/expediente/<int:id>/documentos')
@requiere_login
@no_cache
def expediente_documentos(id):
    """Ver documentos de un expediente específico"""
    if not puede_ver_modulo('documentos'):
        flash('No tiene permisos para ver documentos', 'error')
        return redirect(url_for('main.index'))

    expediente = Expediente.query.get_or_404(id)
    documentos = Documento.query.filter_by(expediente_id=id).order_by(Documento.fecha_subida.desc()).all()

    return render_template('expediente_documentos.html',
                         title=f'Documentos - {expediente.get_identificador_principal()}',
                         expediente=expediente,
                         documentos=documentos,
                         rol=session.get('rol', 'USUARIO'))


# ============================================
# GESTIONAR ESPACIO EN DRIVE CORPORATIVO
# ============================================

@bp.route('/gestionar-espacio')
@requiere_login
@no_cache
def gestionar_espacio():
    """Muestra espacio usado en Drive corporativo (solo Admin/Dev)"""
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos', 'error')
        return redirect(url_for('main.index'))

    try:
        espacio = obtener_espacio_usado_drive()

        documentos_drive = Documento.query.filter(
            Documento.ubicacion == 'drive',
            Documento.drive_file_id.isnot(None)
        ).order_by(Documento.fecha_subida.asc()).all()

        return render_template('gestionar_espacio.html',
                             espacio=espacio,
                             documentos=documentos_drive)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('main.index'))


# ============================================
# LIBERAR ESPACIO - ELIMINAR DEL DRIVE, MANTENER EN SUPABASE
# ============================================
# Esta función es para liberar espacio en Drive. 
# Elimina del Drive pero marca como 'archivado_local' en Supabase.
# Los documentos siguen apareciendo en búsquedas.

@bp.route('/liberar-espacio', methods=['POST'])
@requiere_login
@no_cache
def liberar_espacio():
    """
    LIBERAR ESPACIO: Elimina documentos del Drive pero MANTIENE registros en Supabase.
    Los documentos quedan marcados como 'archivado_local' para historial de búsqueda.
    Solo Admin/Dev.
    """
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos', 'error')
        return redirect(url_for('main.index'))

    documento_ids = request.form.getlist('documentos[]')

    if not documento_ids:
        flash('No seleccionaste documentos', 'warning')
        return redirect(url_for('main.gestionar_espacio'))

    liberados = 0

    try:
        for doc_id in documento_ids:
            documento = Documento.query.get(doc_id)
            if not documento or not documento.drive_file_id:
                continue

            try:
                # PASO 1: Eliminar del Drive
                eliminar_archivo_drive(documento.drive_file_id)

                # PASO 2: Marcar como archivado_local (NO eliminar de Supabase)
                documento.ubicacion = 'archivado_local'
                documento.url_drive = None
                documento.drive_file_id = None
                fecha_arch = datetime.now().strftime('%d/%m/%Y %H:%M')
                arch_note = f"[ARCHIVADO EN OFICINA - {fecha_arch} por {session.get('nombre', 'Sistema')}]"
                if documento.descripcion:
                    documento.descripcion = f"{documento.descripcion}\n{arch_note}"
                else:
                    documento.descripcion = arch_note

                liberados += 1
            except Exception as e:
                print(f"Error liberando espacio doc {doc_id}: {e}")
                continue

        db.session.commit()
        flash(f'📁 {liberados} documentos liberados del Drive. Registros mantenidos en sistema.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('main.gestionar_espacio'))


# ============================================
# ARCHIVAR DOCUMENTOS POR PERÍODO - LIBERAR ESPACIO MASIVO
# ============================================
# Esta función archiva documentos antiguos por período.
# Elimina del Drive pero mantiene en Supabase como 'archivado_local'.
# Útil para casos antiguos donde se quiere liberar espacio pero mantener historial.

@bp.route('/archivar-documentos', methods=['GET', 'POST'])
@requiere_login
@no_cache
def archivar_documentos():
    """
    ARCHIVAR POR PERÍODO: Elimina documentos antiguos del Drive por período.
    MANTIENE registros en Supabase como 'archivado_local' para historial.
    Los documentos archivados muestran "Documento archivado en oficina" en búsquedas.
    Solo Admin/Dev.
    """
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos', 'error')
        return redirect(url_for('main.index'))

    # Obtener documentos que están en Drive (no archivados)
    documentos_drive = Documento.query.filter(
        Documento.ubicacion == 'drive',
        Documento.drive_file_id.isnot(None)
    ).order_by(Documento.fecha_subida.desc()).all()

    if request.method == 'POST':
        if not request.form.get('confirmar'):
            flash('Debe confirmar la operación.', 'warning')
            return redirect(url_for('main.archivar_documentos'))

        tipo_periodo = request.form.get('tipo_periodo', 'mes')
        hoy = datetime.now()
        fecha_inicio = None
        fecha_fin = None

        try:
            if tipo_periodo == 'dia':
                fecha_str = request.form.get('fecha', hoy.strftime('%Y-%m-%d'))
                fecha_inicio = datetime.strptime(fecha_str, '%Y-%m-%d')
                fecha_fin = fecha_inicio + timedelta(days=1)

            elif tipo_periodo == 'semana':
                semana_str = request.form.get('semana', hoy.strftime('%Y-W%W'))
                partes = semana_str.split('-W')
                año = int(partes[0])
                semana = int(partes[1])
                fecha_inicio = datetime.strptime(f'{año}-W{semana:02d}-1', '%G-W%V-%u')
                fecha_fin = fecha_inicio + timedelta(days=7)

            elif tipo_periodo == 'mes':
                mes_str = request.form.get('mes', hoy.strftime('%Y-%m'))
                partes = mes_str.split('-')
                año = int(partes[0])
                mes = int(partes[1])
                fecha_inicio = datetime(año, mes, 1)
                fecha_fin = datetime(año, mes + 1, 1) if mes < 12 else datetime(año + 1, 1, 1)

            elif tipo_periodo == 'año':
                año = int(request.form.get('año', hoy.year))
                fecha_inicio = datetime(año, 1, 1)
                fecha_fin = datetime(año + 1, 1, 1)
            else:
                flash('Tipo de período no válido.', 'error')
                return redirect(url_for('main.archivar_documentos'))

        except Exception as e:
            flash(f'Error en la fecha: {str(e)}', 'error')
            return redirect(url_for('main.archivar_documentos'))

        # Filtrar documentos del período que están en Drive
        documentos_archivar = Documento.query.filter(
            Documento.ubicacion == 'drive',
            Documento.drive_file_id.isnot(None),
            Documento.fecha_subida >= fecha_inicio,
            Documento.fecha_subida < fecha_fin
        ).all()

        if not documentos_archivar:
            flash('No hay documentos en ese período para archivar.', 'info')
            return redirect(url_for('main.archivar_documentos'))

        # Archivar: eliminar de Drive, mantener en Supabase como archivado_local
        archivados = 0

        for doc in documentos_archivar:
            try:
                # PASO 1: Eliminar de Drive
                eliminar_archivo_drive(doc.drive_file_id)

                # PASO 2: Marcar como archivado_local (mantener en Supabase)
                doc.ubicacion = 'archivado_local'
                doc.url_drive = None
                doc.drive_file_id = None
                fecha_arch = datetime.now().strftime('%d/%m/%Y %H:%M')
                arch_note = f"[ARCHIVADO EN OFICINA - {fecha_arch} por {session.get('nombre', 'Sistema')}]"
                if doc.descripcion:
                    doc.descripcion = f"{doc.descripcion}\n{arch_note}"
                else:
                    doc.descripcion = arch_note

                archivados += 1
            except Exception as e:
                print(f"Error archivando doc {doc.id}: {e}")
                continue

        db.session.commit()

        flash(f'📁 {archivados} documentos archivados. Eliminados del Drive pero mantenidos en sistema como "Archivado en oficina".', 'success')
        return redirect(url_for('main.documentos'))

    # GET: Mostrar formulario
    return render_template('archivar_documentos.html',
                         title='Archivar Documentos por Período',
                         documentos_drive=documentos_drive,
                         fecha_hoy=datetime.now().strftime('%Y%m%d'),
                         rol=session.get('rol', 'USUARIO'))
# ============================================
# RUTAS DE NOTIFICACIONES
# ============================================

@bp.route('/notificaciones')
@requiere_login
@no_cache
def notificaciones():
    """Centro de notificaciones del usuario"""
    verificar_audiencias_y_notificar()

    todas = get_notificaciones_usuario(
        session.get('nombre'),
        session.get('rol'),
        solo_no_leidas=False,
        limite=50
    )

    no_leidas_count = contar_notificaciones_no_leidas(
        session.get('nombre'),
        session.get('rol')
    )

    return render_template('notificaciones.html',
                         title='Notificaciones',
                         notificaciones=todas,
                         no_leidas=no_leidas_count,
                         rol=session.get('rol', 'USUARIO'))


@bp.route('/notificaciones/no-leidas')
@requiere_login
@no_cache
def notificaciones_no_leidas():
    """API: Obtener cantidad de notificaciones no leídas"""
    verificar_audiencias_y_notificar()

    count = contar_notificaciones_no_leidas(
        session.get('nombre'),
        session.get('rol')
    )

    ultimas = get_notificaciones_usuario(
        session.get('nombre'),
        session.get('rol'),
        solo_no_leidas=True,
        limite=5
    )

    data = {
        'count': count,
        'notificaciones': [{
            'id': n.id,
            'titulo': n.titulo,
            'mensaje': n.mensaje[:100] + '...' if len(n.mensaje) > 100 else n.mensaje,
            'icono': n.icono,
            'color': n.color,
            'tiempo': n.get_tiempo_transcurrido(),
            'link': n.link
        } for n in ultimas]
    }

    return jsonify(data)


@bp.route('/notificacion/<int:id>/leer', methods=['POST'])
@requiere_login
@no_cache
def marcar_leida(id):
    """Marcar notificación como leída"""
    if marcar_notificacion_leida(id, session.get('nombre')):
        return jsonify({'success': True})
    return jsonify({'success': False}), 403


@bp.route('/notificaciones/marcar-todas', methods=['POST'])
@requiere_login
@no_cache
def marcar_todas_leidas():
    """Marcar todas las notificaciones como leídas"""
    notifs = get_notificaciones_usuario(
        session.get('nombre'),
        session.get('rol'),
        solo_no_leidas=True,
        limite=100
    )

    for n in notifs:
        n.leida = True
        n.fecha_lectura = datetime.now()

    db.session.commit()
    return jsonify({'success': True, 'message': 'Todas las notificaciones marcadas como leídas'})

# ============================================
# RUTAS DE EXPORTACIÓN (SOLO ADMIN/DEV)
# ============================================

@bp.route('/exportar/excel/<string:tipo>')
@requiere_login
@no_cache
def exportar_excel(tipo):
    """Exportar expedientes a Excel (solo Admin/Dev)"""
    if not puede_exportar():
        flash('No tiene permisos para exportar datos', 'error')
        return redirect(url_for('main.index'))

    tipos_permitidos = ['todos', 'civil', 'penal', 'administrativo', 'conciliacion', 'archivo']
    if tipo not in tipos_permitidos:
        flash('Tipo de exportación no válido', 'error')
        return redirect(url_for('main.index'))

    if tipo == 'todos':
        expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()
        nombre_archivo = 'Todos_los_Expedientes'
    else:
        expedientes = Expediente.query.filter_by(tipo=tipo).order_by(Expediente.fecha_registro.desc()).all()
        nombre_archivo = f'Expedientes_{tipo.title()}'

    data = []
    for exp in expedientes:
        data.append({
            'ID': exp.id,
            'Tipo': exp.get_tipo_label(),
            'N° Expediente': exp.numero_expediente if exp.numero_expediente != '-' else f'DNI: {exp.dni}',
            'Cliente': exp.cliente,
            'DNI': exp.dni or 'N/A',
            'Teléfono': exp.telefono or 'N/A',
            'Materia': exp.materia,
            'Estado': exp.get_estado_label(),
            'Fecha Registro': exp.fecha_registro.strftime('%d/%m/%Y') if exp.fecha_registro else 'N/A',
            'Última Actualización': exp.fecha_actualizacion.strftime('%d/%m/%Y') if exp.fecha_actualizacion else 'N/A'
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Expedientes', index=False)
        worksheet = writer.sheets['Expedientes']

        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width

    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'{nombre_archivo}_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )


@bp.route('/exportar/pdf/<string:tipo>')
@requiere_login
@no_cache
def exportar_pdf(tipo):
    """Exportar expedientes a PDF (solo Admin/Dev)"""
    if not puede_exportar():
        flash('No tiene permisos para exportar datos', 'error')
        return redirect(url_for('main.index'))

    tipos_permitidos = ['todos', 'civil', 'penal', 'administrativo', 'conciliacion', 'archivo']
    if tipo not in tipos_permitidos:
        flash('Tipo de exportación no válido', 'error')
        return redirect(url_for('main.index'))

    if tipo == 'todos':
        expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()
        titulo = 'Todos los Expedientes'
    else:
        expedientes = Expediente.query.filter_by(tipo=tipo).order_by(Expediente.fecha_registro.desc()).all()
        titulos = {
            'civil': 'Expedientes de Derecho Civil',
            'penal': 'Expedientes de Derecho Penal',
            'administrativo': 'Expedientes Administrativos',
            'conciliacion': 'Expedientes de Conciliación',
            'archivo': 'Expedientes en Archivo'
        }
        titulo = titulos.get(tipo, 'Expedientes')

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1e3a8a'),
        spaceAfter=20,
        alignment=1
    )

# --- LOGO DEL ESTUDIO ---
    # Intentar cargar desde archivo local primero
    logo_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'logo-quijandria.png')
    logo = None

    if os.path.exists(logo_path):
        try:
            logo = ImageReader(logo_path)
        except Exception as e:
            print(f"Error cargando logo local: {e}")

    # Si no existe localmente, usar base64 incrustado
    if logo is None:
        try:
            # Logo en base64 (reemplazar esta cadena con tu logo real convertido a base64)
            LOGO_BASE64 = "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"
            if LOGO_BASE64 != "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":
                logo_bytes = base64.b64decode(LOGO_BASE64)
                logo = ImageReader(io.BytesIO(logo_bytes))
        except Exception as e:
            print(f"Error cargando logo base64: {e}")

    if logo:
        try:
            logo_img = Table([[logo]], colWidths=[1.5*inch], rowHeights=[1.2*inch])
            logo_img.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(logo_img)
            elements.append(Spacer(1, 8))
        except Exception as e:
            print(f"Error mostrando logo: {e}")
    # -------------------------

    elements.append(Paragraph("QUIJANDRIA ABOGADOS EIRL", title_style))
    elements.append(Paragraph(f"{titulo}", styles['Heading2']))
    elements.append(Paragraph(f"Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 20))

    table_data = [['ID', 'Tipo', 'Identificación', 'Cliente', 'Materia', 'Estado', 'Fecha']]

    for exp in expedientes:
        identificacion = exp.numero_expediente if exp.numero_expediente != '-' else f'DNI: {exp.dni}'
        table_data.append([
            str(exp.id),
            exp.get_tipo_label(),
            identificacion,
            exp.cliente[:25] + '...' if len(exp.cliente) > 25 else exp.cliente,
            exp.materia[:20] + '...' if len(exp.materia) > 20 else exp.materia,
            exp.get_estado_label(),
            exp.fecha_registro.strftime('%d/%m/%Y') if exp.fecha_registro else 'N/A'
        ])

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(f"Total de expedientes: {len(expedientes)}", styles['Normal']))
    elements.append(Paragraph("Sistema de Gestión de Expedientes Legales - Quijandria Abogados", styles['Italic']))

    doc.build(elements)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{titulo.replace(" ", "_")}_{datetime.now().strftime("%Y%m%d")}.pdf'
    )

# ============================================
# RUTA PARA IMPRIMIR EXPEDIENTE EN PDF
# ============================================

@bp.route('/expediente/<int:id>/imprimir')
@requiere_login
@no_cache
def imprimir_expediente_pdf(id):
    """Generar PDF del detalle de expediente con historial y audiencias (solo Admin/Dev)"""

    if not puede_exportar():
        flash('No tiene permisos para imprimir expedientes', 'error')
        return redirect(url_for('main.ver_expediente', id=id))

    expediente = Expediente.query.get_or_404(id)
    historial = EstadoHistorial.query.filter_by(expediente_id=id).order_by(EstadoHistorial.fecha.desc()).all()
    audiencias = Audiencia.query.filter_by(expediente_id=id).order_by(Audiencia.fecha.desc()).all()
    documentos = Documento.query.filter_by(expediente_id=id).all()

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, 
        pagesize=letter,
        topMargin=1.8*inch,
        bottomMargin=0.5*inch,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch
    )
    elements = []

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1e3a8a'),
        spaceAfter=12,
        alignment=1
    )

    section_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#1e3a8a'),
        spaceAfter=8,
        spaceBefore=12
    )

    elements.append(Paragraph("QUIJANDRIA ABOGADOS EIRL", title_style))
    elements.append(Paragraph("Sistema de Gestión de Expedientes Legales", styles['Normal']))
    elements.append(Paragraph("<b>Reporte de Expediente</b>", styles['Heading3']))
    elements.append(Spacer(1, 10))

    elements.append(Table([['']], colWidths=[7*inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#1e3a8a')),
    ])))
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("📋 INFORMACIÓN GENERAL", section_style))

    wrap_style = ParagraphStyle(
        'WrapStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        wordWrap='CJK'
    )

    # Estilo negrita para valores importantes
    bold_wrap_style = ParagraphStyle(
        'BoldWrapStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        wordWrap='CJK',
        fontName='Helvetica-Bold'
    )

    info_data = [
        ['Campo', 'Valor'],
        ['Tipo de Expediente', Paragraph(expediente.get_tipo_label(), wrap_style)],
        ['N° de Expediente', Paragraph(f"<b>{expediente.numero_expediente if expediente.numero_expediente != '-' else 'N/A'}</b>", wrap_style)],
        ['Cliente', Paragraph(expediente.cliente, wrap_style)],
        ['DNI', Paragraph(expediente.dni or 'No aplica', wrap_style)],
        ['Teléfono', Paragraph(expediente.telefono or 'No registrado', wrap_style)],
        ['Materia', Paragraph(expediente.materia, wrap_style)],
        ['Estado Actual', Paragraph(expediente.get_estado_label(), wrap_style)],
        ['Fecha de Registro', Paragraph(expediente.fecha_registro.strftime('%d/%m/%Y %H:%M') if expediente.fecha_registro else 'N/A', wrap_style)],
    ]

    if expediente.tipo == 'civil':
        info_data.append(['Juez', Paragraph(expediente.juez or 'No asignado', wrap_style)])
        info_data.append(['Secretario', Paragraph(expediente.secretario or 'No asignado', wrap_style)])
    elif expediente.tipo == 'penal':
        info_data.append(['N° Caso Fiscal', Paragraph(expediente.numero_cf or 'No asignado', wrap_style)])
        info_data.append(['Fiscal', Paragraph(expediente.fiscal or 'No asignado', wrap_style)])
        info_data.append(['Juzgado', Paragraph(expediente.juzgado or 'No asignado', wrap_style)])
    elif expediente.tipo == 'administrativo':
        info_data.append(['Entidad Receptora', Paragraph(expediente.entidad_receptora or 'No especificada', wrap_style)])
        info_data.append(['Trámite', Paragraph(expediente.tramite or 'No especificado', wrap_style)])
    elif expediente.tipo == 'conciliacion':
        info_data.append(['Conciliador', Paragraph(expediente.conciliador or 'No asignado', wrap_style)])
        info_data.append(['Solicitante', Paragraph(expediente.solicitante or 'No especificado', wrap_style)])
        info_data.append(['Invitados', Paragraph(expediente.invitados or 'No especificados', wrap_style)])
    elif expediente.tipo == 'archivo':
        info_data.append(['Ubicación en Archivo', Paragraph(expediente.ubicacion_archivo or 'No especificada', wrap_style)])

    descripcion_texto = expediente.descripcion or 'Sin descripción'
    descripcion_formateada = '<br/>'.join(descripcion_texto.split('\n')) if descripcion_texto else 'Sin descripción'
    info_data.append(['Descripción', Paragraph(descripcion_formateada, wrap_style)])

    info_table = Table(info_data, colWidths=[2*inch, 5*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f3f4f6')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    elements.append(info_table)

    if historial:
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("📈 HISTORIAL DE ESTADOS", section_style))

        hist_data = [['Fecha', 'Estado', 'Descripción', 'Usuario']]
        hist_style_body = ParagraphStyle('HistBody', parent=styles['Normal'], fontSize=8, leading=11, wordWrap='CJK')
        for h in historial:
            desc_text = h.descripcion or 'Sin descripción'
            desc_text_formateado = '<br/>'.join(desc_text.split('\n')) if desc_text else 'Sin descripción'
            desc_para = Paragraph(desc_text_formateado, hist_style_body)
            hist_data.append([
                Paragraph(h.fecha.strftime('%d/%m/%Y %H:%M') if h.fecha else 'N/A', hist_style_body),
                Paragraph(h.estado, hist_style_body),
                desc_para,
                Paragraph(h.usuario or 'Sistema', hist_style_body)
            ])

        hist_table = Table(hist_data, colWidths=[1.1*inch, 1.0*inch, 3.8*inch, 1.1*inch])
        hist_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#047857')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ecfdf5')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ]))
        elements.append(hist_table)

    if audiencias:
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("📅 AUDIENCIAS PROGRAMADAS", section_style))

        aud_data = [['Fecha', 'Hora', 'Tipo', 'Lugar', 'Estado']]
        aud_style = ParagraphStyle('AudStyle', parent=styles['Normal'], fontSize=8, leading=11, wordWrap='CJK')
        for a in audiencias:
            aud_data.append([
                Paragraph(a.fecha.strftime('%d/%m/%Y') if a.fecha else 'N/A', aud_style),
                Paragraph(a.hora.strftime('%H:%M') if a.hora else 'N/A', aud_style),
                Paragraph(a.get_tipo_label() if hasattr(a, 'get_tipo_label') else a.tipo_audiencia, aud_style),
                Paragraph(a.lugar or 'No especificado', aud_style),
                Paragraph(a.get_estado_label() if hasattr(a, 'get_estado_label') else a.estado, aud_style)
            ])

        aud_table = Table(aud_data, colWidths=[1*inch, 0.8*inch, 1.5*inch, 2.2*inch, 1.5*inch])
        aud_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#b45309')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fffbeb')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ]))
        elements.append(aud_table)

    if documentos:
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("📄 DOCUMENTOS ADJUNTOS", section_style))

        doc_data = [['Título', 'Categoría', 'Tipo', 'Fecha', 'Ubicación']]
        doc_style = ParagraphStyle('DocStyle', parent=styles['Normal'], fontSize=8, leading=11, wordWrap='CJK')
        for d in documentos:
            ubicacion_label = 'Drive' if d.ubicacion == 'drive' else 'Oficina' if d.ubicacion == 'archivado_local' else d.ubicacion
            titulo_corto = d.titulo[:30] + '...' if len(d.titulo) > 30 else d.titulo
            doc_data.append([
                Paragraph(titulo_corto, doc_style),
                Paragraph(d.categoria.title() if d.categoria else 'Otro', doc_style),
                Paragraph(d.tipo_archivo.upper() if d.tipo_archivo else 'N/A', doc_style),
                Paragraph(d.fecha_subida.strftime('%d/%m/%Y') if d.fecha_subida else 'N/A', doc_style),
                Paragraph(ubicacion_label, doc_style)
            ])

        doc_table = Table(doc_data, colWidths=[2.5*inch, 1.2*inch, 1*inch, 1.2*inch, 1.1*inch])
        doc_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4b5563')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f9fafb')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ]))
        elements.append(doc_table)

    elements.append(Spacer(1, 30))
    elements.append(Table([['']], colWidths=[7*inch], style=TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.grey),
    ])))
    elements.append(Spacer(1, 10))

    footer_data = [
        [f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')}", "Quijandria Abogados EIRL"],
        [f"Usuario: {session.get('nombre', 'Sistema')}", "Sistema de Gestión de Expedientes v1.0"]
    ]
    footer_table = Table(footer_data, colWidths=[3.5*inch, 3.5*inch])
    footer_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.grey),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    elements.append(footer_table)

    def draw_logo_first_page(canvas, doc):
        """Dibuja logo SOLO en la primera página"""
        try:
            logo = get_logo_image()
            if logo:
                # Logo más grande: 2.0 x 1.6 pulgadas
                logo_width = 2.0 * inch
                logo_height = 1.6 * inch
                page_width = letter[0]
                x = (page_width - logo_width) / 2
                y = letter[1] - 1.7 * inch
                canvas.drawImage(logo, x, y, width=logo_width, height=logo_height, preserveAspectRatio=True, mask='auto')
        except Exception as e:
            print(f"Error dibujando logo: {e}")

    def draw_no_logo(canvas, doc):
        """Páginas siguientes sin logo"""
        pass

    doc.build(elements, onFirstPage=draw_logo_first_page, onLaterPages=draw_no_logo)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Expediente_{expediente.numero_expediente.replace("/", "_")}_{datetime.now().strftime("%Y%m%d")}.pdf'
    )
# ============================================
# RUTA PARA EXPORTAR SEGUIMIENTO A EXCEL
# ============================================

@bp.route('/expediente/<int:id>/exportar-seguimiento')
@requiere_login
@no_cache
def exportar_seguimiento_excel(id):
    """Exportar seguimiento completo de expediente a Excel profesional (solo Admin/Dev)"""

    if not puede_exportar():
        flash('No tiene permisos para exportar seguimientos', 'error')
        return redirect(url_for('main.ver_expediente', id=id))

    expediente = Expediente.query.get_or_404(id)
    historial = EstadoHistorial.query.filter_by(expediente_id=id).order_by(EstadoHistorial.fecha.desc()).all()
    audiencias = Audiencia.query.filter_by(expediente_id=id).order_by(Audiencia.fecha.desc()).all()
    documentos = Documento.query.filter_by(expediente_id=id).order_by(Documento.fecha_subida.desc()).all()

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # HOJA 1: RESUMEN DEL EXPEDIENTE
        resumen_data = {
            'Campo': [
                'ID', 'Tipo', 'N° Expediente', 'Cliente', 'DNI', 'Teléfono',
                'Materia', 'Descripción', 'Estado Actual', 'Fecha de Registro',
                'Última Actualización', 'Usuario de Registro'
            ],
            'Valor': [
                expediente.id,
                expediente.get_tipo_label(),
                expediente.numero_expediente if expediente.numero_expediente != '-' else f'DNI: {expediente.dni}',
                expediente.cliente,
                expediente.dni or 'No aplica',
                expediente.telefono or 'No registrado',
                expediente.materia,
                expediente.descripcion or 'Sin descripción',
                expediente.get_estado_label(),
                expediente.fecha_registro.strftime('%d/%m/%Y %H:%M') if expediente.fecha_registro else 'N/A',
                expediente.fecha_actualizacion.strftime('%d/%m/%Y %H:%M') if expediente.fecha_actualizacion else 'N/A',
                expediente.usuario_registro or 'Sistema'
            ]
        }

        if expediente.tipo == 'civil':
            resumen_data['Campo'].extend(['Juez', 'Secretario'])
            resumen_data['Valor'].extend([
                expediente.juez or 'No asignado',
                expediente.secretario or 'No asignado'
            ])
        elif expediente.tipo == 'penal':
            resumen_data['Campo'].extend(['N° Caso Fiscal', 'Fiscal', 'Juzgado'])
            resumen_data['Valor'].extend([
                expediente.numero_cf or 'No asignado',
                expediente.fiscal or 'No asignado',
                expediente.juzgado or 'No asignado'
            ])
        elif expediente.tipo == 'administrativo':
            resumen_data['Campo'].extend(['Entidad Receptora', 'Trámite'])
            resumen_data['Valor'].extend([
                expediente.entidad_receptora or 'No especificada',
                expediente.tramite or 'No especificado'
            ])
        elif expediente.tipo == 'conciliacion':
            resumen_data['Campo'].extend(['Conciliador', 'Solicitante', 'Invitados'])
            resumen_data['Valor'].extend([
                expediente.conciliador or 'No asignado',
                expediente.solicitante or 'No especificado',
                expediente.invitados or 'No especificados'
            ])
        elif expediente.tipo == 'archivo':
            resumen_data['Campo'].append('Ubicación en Archivo')
            resumen_data['Valor'].append(expediente.ubicacion_archivo or 'No especificada')

        df_resumen = pd.DataFrame(resumen_data)
        df_resumen.to_excel(writer, sheet_name='Resumen', index=False)

        worksheet_resumen = writer.sheets['Resumen']
        worksheet_resumen.column_dimensions['A'].width = 25
        worksheet_resumen.column_dimensions['B'].width = 50

        # HOJA 2: HISTORIAL DE ESTADOS
        if historial:
            hist_data = []
            for h in historial:
                hist_data.append({
                    'N°': len(hist_data) + 1,
                    'Fecha': h.fecha.strftime('%d/%m/%Y %H:%M') if h.fecha else 'N/A',
                    'Estado': h.estado,
                    'Descripción': h.descripcion or 'Sin descripción',
                    'Usuario': h.usuario or 'Sistema'
                })

            df_historial = pd.DataFrame(hist_data)
            df_historial.to_excel(writer, sheet_name='Historial de Estados', index=False)

            worksheet_hist = writer.sheets['Historial de Estados']
            worksheet_hist.column_dimensions['A'].width = 5
            worksheet_hist.column_dimensions['B'].width = 18
            worksheet_hist.column_dimensions['C'].width = 15
            worksheet_hist.column_dimensions['D'].width = 40
            worksheet_hist.column_dimensions['E'].width = 15

        # HOJA 3: AUDIENCIAS
        if audiencias:
            aud_data = []
            for a in audiencias:
                aud_data.append({
                    'N°': len(aud_data) + 1,
                    'Fecha': a.fecha.strftime('%d/%m/%Y') if a.fecha else 'N/A',
                    'Hora': a.hora.strftime('%H:%M') if a.hora else 'N/A',
                    'Tipo': a.get_tipo_label() if hasattr(a, 'get_tipo_label') else a.tipo_audiencia,
                    'Lugar': a.lugar or 'No especificado',
                    'Sala': a.sala or 'No especificada',
                    'Magistrado': a.magistrado or 'No asignado',
                    'Estado': a.get_estado_label() if hasattr(a, 'get_estado_label') else a.estado,
                    'Observaciones': a.observaciones or 'Sin observaciones'
                })

            df_audiencias = pd.DataFrame(aud_data)
            df_audiencias.to_excel(writer, sheet_name='Audiencias', index=False)

            worksheet_aud = writer.sheets['Audiencias']
            for idx, col in enumerate(df_audiencias.columns, 1):
                worksheet_aud.column_dimensions[chr(64 + idx)].width = 15 if idx <= 3 else 20

        # HOJA 4: DOCUMENTOS
        if documentos:
            doc_data = []
            for d in documentos:
                ubicacion_label = 'Drive' if d.ubicacion == 'drive' else 'Archivado en Oficina' if d.ubicacion == 'archivado_local' else d.ubicacion
                doc_data.append({
                    'N°': len(doc_data) + 1,
                    'Título': d.titulo,
                    'Categoría': d.categoria.title() if d.categoria else 'Otro',
                    'Tipo': d.tipo_archivo.upper() if d.tipo_archivo else 'N/A',
                    'Tamaño': d.get_tamaño_formateado() if hasattr(d, 'get_tamaño_formateado') else f"{d.tamaño_bytes} bytes",
                    'Ubicación': ubicacion_label,
                    'Fecha Documento': d.fecha_documento.strftime('%d/%m/%Y') if d.fecha_documento else 'N/A',
                    'Fecha Subida': d.fecha_subida.strftime('%d/%m/%Y %H:%M') if d.fecha_subida else 'N/A',
                    'Subido por': d.usuario_subida or 'Sistema',
                    'Descripción': d.descripcion or 'Sin descripción'
                })

            df_documentos = pd.DataFrame(doc_data)
            df_documentos.to_excel(writer, sheet_name='Documentos', index=False)

            worksheet_doc = writer.sheets['Documentos']
            worksheet_doc.column_dimensions['A'].width = 5
            worksheet_doc.column_dimensions['B'].width = 30
            worksheet_doc.column_dimensions['C'].width = 15
            worksheet_doc.column_dimensions['D'].width = 10
            worksheet_doc.column_dimensions['E'].width = 12
            worksheet_doc.column_dimensions['F'].width = 18
            worksheet_doc.column_dimensions['G'].width = 15
            worksheet_doc.column_dimensions['H'].width = 18
            worksheet_doc.column_dimensions['I'].width = 15
            worksheet_doc.column_dimensions['J'].width = 30

    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'Seguimiento_{expediente.numero_expediente.replace("/", "_")}_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )


# ============================================
# RUTA PARA EXPORTAR RESUMEN PDF PROFESIONAL
# ============================================

@bp.route('/expediente/<int:id>/exportar-pdf')
@requiere_login
@no_cache
def exportar_resumen_pdf(id):
    """Generar PDF resumen profesional del expediente (solo Admin/Dev)"""

    if not puede_exportar():
        flash('No tiene permisos para exportar expedientes', 'error')
        return redirect(url_for('main.ver_expediente', id=id))

    expediente = Expediente.query.get_or_404(id)

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, 
        pagesize=letter,
        topMargin=1.8*inch,
        bottomMargin=0.75*inch,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch
    )

    elements = []
    styles = getSampleStyleSheet()

    titulo_estudio = ParagraphStyle(
        'TituloEstudio',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=1,
        spaceAfter=6,
        fontName='Helvetica-Bold'
    )

    subtitulo_sistema = ParagraphStyle(
        'SubtituloSistema',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#64748b'),
        alignment=1,
        spaceAfter=24,
        fontName='Helvetica'
    )

    titulo_documento = ParagraphStyle(
        'TituloDocumento',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#334155'),
        alignment=1,
        spaceAfter=20,
        fontName='Helvetica-Bold'
    )

    nota_estilo = ParagraphStyle(
        'Nota',
        parent=styles['Italic'],
        fontSize=8,
        textColor=colors.HexColor('#94a3b8'),
        alignment=1,
        spaceBefore=30
    )

    wrap_style = ParagraphStyle(
        'WrapStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        wordWrap='CJK'
    )

    elements.append(Paragraph("QUIJANDRIA ABOGADOS EIRL", titulo_estudio))
    elements.append(Paragraph("Sistema de Gestión de Expedientes Legales", subtitulo_sistema))

    elements.append(Table([['']], colWidths=[6.5*inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#1e3a8a')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ])))

    tipo_label = expediente.get_tipo_label()
    elements.append(Paragraph(f"RESUMEN DE {tipo_label.upper()}", titulo_documento))

    datos_principales = [
        ['INFORMACIÓN GENERAL', ''],
        ['N° de Expediente:', f"<b>{expediente.numero_expediente if expediente.numero_expediente != '-' else 'No aplica (Administrativo)'}</b>"],
        ['Tipo de Proceso:', expediente.get_tipo_label()],
        ['Estado Actual:', expediente.get_estado_label()],
        ['', ''],
        ['PARTES DEL PROCESO', ''],
        ['Cliente:', expediente.cliente],
        ['DNI:', expediente.dni or 'No aplica'],
        ['Teléfono:', expediente.telefono or 'No registrado'],
        ['', ''],
        ['DETALLES DEL CASO', ''],
        ['Materia:', expediente.materia],
    ]

    if expediente.tipo == 'civil':
        datos_principales.extend([
            ['Juez:', expediente.juez or 'Por asignar'],
            ['Secretario:', expediente.secretario or 'Por asignar'],
        ])
    elif expediente.tipo == 'penal':
        datos_principales.extend([
            ['N° Caso Fiscal:', expediente.numero_cf or 'Por asignar'],
            ['Fiscal:', expediente.fiscal or 'Por asignar'],
            ['Juzgado:', expediente.juzgado or 'Por asignar'],
        ])
    elif expediente.tipo == 'administrativo':
        datos_principales.extend([
            ['Entidad Receptora:', expediente.entidad_receptora or 'Por definir'],
            ['Trámite:', expediente.tramite or 'Por definir'],
        ])
    elif expediente.tipo == 'conciliacion':
        datos_principales.extend([
            ['Conciliador:', expediente.conciliador or 'Por asignar'],
            ['Solicitante:', expediente.solicitante or expediente.cliente],
            ['Invitados:', expediente.invitados or 'No especificados'],
        ])
    elif expediente.tipo == 'archivo':
        datos_principales.extend([
            ['Ubicación Física:', expediente.ubicacion_archivo or 'Por definir'],
        ])

    datos_principales.extend([
        ['', ''],
        ['REGISTRO Y SEGUIMIENTO', ''],
        ['Fecha de Ingreso:', expediente.fecha_registro.strftime('%d de %B de %Y').upper() if expediente.fecha_registro else 'No registrada'],
        ['Última Actualización:', expediente.fecha_actualizacion.strftime('%d de %B de %Y - %H:%M').upper() if expediente.fecha_actualizacion else 'Sin actualizaciones'],
        ['Registrado por:', expediente.usuario_registro or 'Sistema'],
    ])

    tabla_data = []
    for fila in datos_principales:
        if fila[0] == '' and fila[1] == '':
            tabla_data.append(['', ''])
        elif fila[1] == '':
            tabla_data.append([fila[0], ''])
        else:
            tabla_data.append([fila[0], Paragraph(fila[1], wrap_style)])

    tabla = Table(tabla_data, colWidths=[2*inch, 4.5*inch])

    header_rows = []
    for idx, fila in enumerate(tabla_data):
        if fila[0] in ['INFORMACIÓN GENERAL', 'PARTES DEL PROCESO', 'DETALLES DEL CASO', 'REGISTRO Y SEGUIMIENTO']:
            header_rows.append(idx)

    style_commands = [
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (0, -1), 9),
        ('TEXTCOLOR', (0, 1), (0, -1), colors.HexColor('#475569')),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f8fafc')),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('LEFTPADDING', (0, 1), (0, -1), 12),
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica'),
        ('FONTSIZE', (1, 1), (1, -1), 10),
        ('TEXTCOLOR', (1, 1), (1, -1), colors.HexColor('#1e293b')),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('LEFTPADDING', (1, 1), (1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]

    for h_row in header_rows:
        style_commands.extend([
            ('BACKGROUND', (0, h_row), (-1, h_row), colors.HexColor('#1e3a8a')),
            ('TEXTCOLOR', (0, h_row), (-1, h_row), colors.white),
            ('FONTNAME', (0, h_row), (-1, h_row), 'Helvetica-Bold'),
            ('FONTSIZE', (0, h_row), (-1, h_row), 10),
            ('SPAN', (0, h_row), (-1, h_row)),
            ('ALIGN', (0, h_row), (-1, h_row), 'CENTER'),
            ('BOTTOMPADDING', (0, h_row), (-1, h_row), 8),
            ('TOPPADDING', (0, h_row), (-1, h_row), 8),
        ])

    tabla.setStyle(TableStyle(style_commands))

    elements.append(tabla)
    elements.append(Spacer(1, 20))

    if expediente.descripcion:
        desc_style = ParagraphStyle(
            'Desc',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#334155'),
            alignment=0,
            spaceAfter=6,
            leading=14,
            wordWrap='CJK'
        )
        elements.append(Paragraph("<b>DESCRIPCIÓN DEL CASO:</b>", desc_style))

        descripcion_texto = expediente.descripcion
        descripcion_formateada = '<br/>'.join(descripcion_texto.split('\n')) if descripcion_texto else 'Sin descripción'
        
        desc_data = [[Paragraph(descripcion_formateada, desc_style)]]
        desc_tabla = Table(desc_data, colWidths=[6.5*inch])
        desc_tabla.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#334155')),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
        ]))
        elements.append(desc_tabla)

    elements.append(Spacer(1, 40))
    elements.append(Table([['']], colWidths=[6.5*inch], style=TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, 0), 20),
    ])))

    elements.append(Paragraph(
        "Este documento es confidencial y de uso exclusivo del estudio jurídico. "
        "Generado el " + datetime.now().strftime('%d/%m/%Y a las %H:%M') + 
        " por " + session.get('nombre', 'Sistema'),
        nota_estilo
    ))

    def draw_logo_first_page(canvas, doc):
        """Dibuja logo SOLO en la primera página"""
        try:
            logo = get_logo_image()
            if logo:
                # Logo más grande: 2.0 x 1.6 pulgadas
                logo_width = 2.0 * inch
                logo_height = 1.6 * inch
                page_width = letter[0]
                x = (page_width - logo_width) / 2
                y = letter[1] - 1.7 * inch
                canvas.drawImage(logo, x, y, width=logo_width, height=logo_height, preserveAspectRatio=True, mask='auto')
        except Exception as e:
            print(f"Error dibujando logo: {e}")

    def draw_no_logo(canvas, doc):
        """Páginas siguientes sin logo"""
        pass

    doc.build(elements, onFirstPage=draw_logo_first_page, onLaterPages=draw_no_logo)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Resumen_{expediente.numero_expediente.replace("/", "_")}_{datetime.now().strftime("%Y%m%d")}.pdf'
    )

# RUTA: ENVIAR EXPEDIENTE A ARCHIVO
# ============================================

@bp.route('/expediente/<int:id>/enviar-a-archivo', methods=['GET', 'POST'])
@requiere_login
@no_cache
def enviar_a_archivo(id):
    """Envía un expediente concluido al módulo Archivo (Opción B: Copiar)"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para archivar expedientes', 'error')
        return redirect(url_for('main.index'))

    expediente_original = Expediente.query.get_or_404(id)

    if expediente_original.tipo == 'archivo':
        flash('Este expediente ya está en archivo', 'warning')
        return redirect(url_for('main.ver_expediente', id=id))

    estados_permitidos = ['proceso_completado', 'resuelto_favorable', 'resuelto_desfavorable', 
                          'archivado', 'enviado_a_archivo', 'ingresado', 'en_proceso', 
                          'audiencia_programada', 'seguimiento', 'derivado_juzgado']

    if expediente_original.estado_actual not in estados_permitidos:
        flash('El expediente debe estar concluido para enviarlo a archivo', 'warning')
        return redirect(url_for('main.ver_expediente', id=id))

    if request.method == 'POST':
        try:
            ubicacion = request.form.get('ubicacion_archivo', '').strip()
            fecha_archivado_str = request.form.get('fecha_archivado', '').strip()
            nota_final = request.form.get('nota_final', '').strip()

            if not ubicacion:
                flash('La ubicación física es obligatoria', 'error')
                return render_template('enviar_a_archivo.html',
                                     title='Enviar a Archivo',
                                     expediente_original=expediente_original,
                                     hoy=date.today().isoformat(),
                                     rol=session.get('rol', 'USUARIO'))

            try:
                fecha_archivado = datetime.strptime(fecha_archivado_str, '%Y-%m-%d').date() if fecha_archivado_str else date.today()
            except ValueError:
                fecha_archivado = date.today()

            # 1. Crear nuevo expediente tipo 'archivo'
            expediente_archivo = Expediente(
                tipo='archivo',
                numero_expediente=expediente_original.numero_expediente,
                cliente=expediente_original.cliente,
                telefono=expediente_original.telefono,
                dni=expediente_original.dni,
                materia=expediente_original.materia,
                descripcion=(expediente_original.descripcion or '') + 
                           f"\n\n=== ENVIADO A ARCHIVO ===\nFecha: {fecha_archivado.strftime('%d/%m/%Y')}\n" +
                           (f"Nota final: {nota_final}" if nota_final else ""),
                ubicacion_archivo=ubicacion,
                fecha_archivado=fecha_archivado,
                estado_actual='archivado',
                usuario_registro=session.get('nombre', 'Sistema')
            )

            db.session.add(expediente_archivo)
            db.session.flush()

            # 2. Marcar original como enviado a archivo
            expediente_original.estado_actual = 'enviado_a_archivo'
            expediente_original.fecha_actualizacion = datetime.now()

            # 3. Agregar historial al original
            historial_original = EstadoHistorial(
                expediente_id=expediente_original.id,
                estado='enviado_a_archivo',
                descripcion=f'Expediente enviado a archivo. Ubicación: {ubicacion}. ' +
                           (f'Nota: {nota_final}' if nota_final else ''),
                usuario=session.get('nombre', 'Sistema')
            )
            db.session.add(historial_original)

            # 4. Agregar historial al NUEVO archivo
            historial_archivo = EstadoHistorial(
                expediente_id=expediente_archivo.id,
                estado='archivado',
                descripcion=f'Expediente archivado desde {expediente_original.get_tipo_label()} N° {expediente_original.get_identificador_principal()}. ' +
                           f'Ubicación: {ubicacion}. ' +
                           (f'Resumen: {nota_final}' if nota_final else ''),
                usuario=session.get('nombre', 'Sistema')
            )
            db.session.add(historial_archivo)

            db.session.commit()

            flash(f'✅ Expediente archivado correctamente. Nuevo ID en archivo: {expediente_archivo.id}', 'success')
            return redirect(url_for('main.ver_expediente', id=expediente_archivo.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al archivar expediente: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
            return render_template('enviar_a_archivo.html',
                                 title='Enviar a Archivo',
                                 expediente_original=expediente_original,
                                 hoy=date.today().isoformat(),
                                 rol=session.get('rol', 'USUARIO'))

    return render_template('enviar_a_archivo.html',
                         title='Enviar a Archivo',
                         expediente_original=expediente_original,
                         hoy=date.today().isoformat(),
                         rol=session.get('rol', 'USUARIO'))


# ============================================
# RUTAS LEGACY - OAuth (ya no se usan)
# ============================================

@bp.route('/auth/google')
@requiere_login
def auth_google():
    """Legacy: Ya no requiere OAuth. Redirige a subida directa."""
    flash('El sistema usa almacenamiento corporativo automático. No se requiere vincular cuenta Google.', 'info')
    return redirect(url_for('main.subir_documento_drive'))

@bp.route('/oauth2callback')
def oauth2callback():
    """Legacy: Callback OAuth (ya no se usa)"""
    flash('Autenticación OAuth desactivada. Use subida directa.', 'info')
    return redirect(url_for('main.index'))


# ============================================
# NOTA SOBRE DOCUMENTOS - LÓGICA DUAL
# ============================================
#
# TODOS los documentos se almacenan en Google Drive corporativo
# usando Service Account (quijandria-drive-service).
# Ningún usuario necesita vincular su Gmail personal.
#
# LÓGICA DUAL DE ELIMINACIÓN:
#
# 1. ELIMINACIÓN COMPLETA (eliminar_documento):
#    - Elimina del Drive (file_id)
#    - Elimina registro de Supabase (db.session.delete)
#    - Elimina todo rastro del documento
#    - Usar cuando se quiere borrar DEFINITIVAMENTE
#
# 2. ARCHIVADO / LIBERAR ESPACIO (eliminar_documento_drive, liberar_espacio, archivar_documentos):
#    - Elimina SOLO del Drive (libera espacio)
#    - MANTIENE registro en Supabase
#    - Marca ubicacion = 'archivado_local'
#    - Agrega nota en descripción: "[ARCHIVADO EN OFICINA - fecha]"
#    - El documento sigue apareciendo en búsquedas
#    - Al ver el documento muestra: "Documento archivado en oficina"
#    - Útil para casos antiguos donde se quiere mantener historial
#
# Flujo de documentos:
#   1. Subida: /subir-documento-drive → Drive corporativo
#   2. Visualización: /documento/<id>/ver → iframe de Drive (o mensaje si archivado)
#   3. Eliminación completa: /documento/<id>/eliminar → Drive + Supabase
#   4. Archivado (liberar espacio): /documento/<id>/eliminar-drive → solo Drive
#   5. Limpieza masiva: /archivar-documentos o /liberar-espacio → Drive (mantener Supabase)
#
# ============================================
# FIN DEL ARCHIVO
# ============================================