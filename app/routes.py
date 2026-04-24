# app/routes.py - Rutas de la aplicación

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, after_this_request, send_file
from functools import wraps
from datetime import datetime, timedelta, date
from app import db
from app.models import Expediente, EstadoHistorial, Audiencia, Documento, Notificacion, Usuario
from app.forms import ExpedienteForm, EstadoForm, BusquedaForm, AudienciaForm, BusquedaAudienciaForm, DocumentoForm, BusquedaDocumentoForm
import json
import os
import bcrypt

# ============================================
# IMPORTS PARA EXPORTACIÓN (PDF/EXCEL)
# ============================================
import io
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

bp = Blueprint('main', __name__)

# ============================================
# CONFIGURACIÓN DE USUARIOS - SUPABASE (tabla: usuario)
# ============================================

def _cargar_usuarios():
    """Carga usuarios activos desde Supabase (tabla usuario)"""
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
    if 'modulos' in session:
        return 'todo' in session['modulos'] or modulo in session['modulos']
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
                # Actualizar último acceso
                usuario.ultimo_acceso = datetime.now()
                db.session.commit()
                
                # CORREGIDO - Agregar usuario_id:
                session['usuario'] = username
                session['usuario_id'] = usuario.id  # ← AGREGAR ESTA LÍNEA
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
    
    # Obtener parámetros de búsqueda
    buscar_numero = request.args.get('buscar_numero', '').strip()
    buscar_cliente = request.args.get('buscar_cliente', '').strip()
    filtro_tipo = request.args.get('filtro_tipo', '').strip()
    filtro_estado = request.args.get('filtro_estado', '').strip()
    
    # Query base
    query = Expediente.query
    
    # Aplicar filtros si existen
    if buscar_numero:
        # Buscar en número de expediente O en DNI (para administrativos)
        query = query.filter(
            db.or_(
                Expediente.numero_expediente.ilike(f'%{buscar_numero}%'),
                Expediente.dni.ilike(f'%{buscar_numero}%')
            )
        )
    
    if buscar_cliente:
        # Búsqueda parcial en nombre del cliente (insensible a mayúsculas)
        query = query.filter(Expediente.cliente.ilike(f'%{buscar_cliente}%'))
    
    if filtro_tipo:
        query = query.filter(Expediente.tipo == filtro_tipo)
    
    if filtro_estado:
        query = query.filter(Expediente.estado == filtro_estado)
    
    # Ordenar por fecha de registro descendente (más recientes primero)
    expedientes = query.order_by(Expediente.fecha_registro.desc()).all()
    
    return render_template('expedientes.html',
                         title='Gestión de Expedientes',
                         expedientes=expedientes,
                         rol=session.get('rol', 'USUARIO'))


# ============================================
# NUEVA RUTA: FILTRADO POR TIPO DE EXPEDIENTE
# ============================================

@bp.route('/expedientes/tipo/<string:tipo>')
@requiere_login
@no_cache
def expedientes_por_tipo(tipo):
    """Listado de expedientes filtrados por tipo (civil, penal, administrativo, conciliacion, archivo)"""

    # Validar tipo permitido
    tipos_permitidos = ['civil', 'penal', 'administrativo', 'conciliacion', 'archivo']
    if tipo not in tipos_permitidos:
        flash('Tipo de expediente no válido', 'error')
        return redirect(url_for('main.expedientes'))

    # Verificar permisos del módulo
    if not puede_ver_modulo(tipo):
        flash(f'No tiene permisos para ver expedientes de {tipo}', 'error')
        return redirect(url_for('main.index'))

    # Obtener expedientes del tipo específico
    lista_expedientes = Expediente.query.filter_by(tipo=tipo).order_by(
        Expediente.fecha_registro.desc()
    ).all()

    # Títulos por tipo
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

    # Audiencias del expediente
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

    # Cargar usuarios desde Supabase
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

    # Restricciones de ADMINISTRADOR
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

    # Validaciones
    if not username or not nombre or not password:
        return jsonify({'success': False, 'error': 'Datos incompletos'}), 400

    # Verificar si ya existe
    if Usuario.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'El usuario ya existe'}), 400

    # Restricciones de ADMINISTRADOR
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

    # Restricciones de ADMINISTRADOR
    if rol_actual == 'ADMINISTRADOR':
        if usuario.rol == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede eliminar al desarrollador'}), 403
        if usuario.rol == 'ADMINISTRADOR':
            return jsonify({'success': False, 'error': 'No puede eliminar a otros administradores'}), 403

    try:
        # Soft delete: marcar como inactivo
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

    # Restricciones de ADMINISTRADOR
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

    # Filtros
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    tipo_filtro = request.args.get('tipo', '')
    estado_filtro = request.args.get('estado', '')

    # Query base
    query = Audiencia.query

    # Aplicar filtros
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

    # Ordenar por fecha y hora
    query = query.order_by(Audiencia.fecha, Audiencia.hora)

    # Obtener audiencias
    lista_audiencias = query.all()

    # Formulario de búsqueda
    form_busqueda = BusquedaAudienciaForm()

    # Estadísticas
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

    # Cargar expedientes SIEMPRE (tanto para GET como para POST cuando hay errores)
    try:
        expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()
    except Exception as e:
        expedientes = []
        flash(f'Error al cargar expedientes: {str(e)}', 'warning')

    if request.method == 'POST':
        try:
            # Obtener expediente_id del formulario manualmente
            expediente_id_str = request.form.get('expediente_id', '0')
            try:
                expediente_id = int(expediente_id_str)
            except ValueError:
                expediente_id = 0

            # Validar que se seleccionó un expediente
            if expediente_id == 0:
                flash('Debe seleccionar un expediente', 'error')
                return render_template('nueva_audiencia.html',
                                     title='Programar Audiencia',
                                     form=form,
                                     expedientes=expedientes,
                                     rol=session.get('rol', 'USUARIO'))

            # Validar que el expediente existe
            expediente = Expediente.query.get(expediente_id)
            if not expediente:
                flash('El expediente seleccionado no existe', 'error')
                return render_template('nueva_audiencia.html',
                                     title='Programar Audiencia',
                                     form=form,
                                     expedientes=expedientes,
                                     rol=session.get('rol', 'USUARIO'))

            # Validar fecha
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

            # Validar hora
            hora_audiencia = form.hora.data
            if not hora_audiencia:
                flash('Debe ingresar una hora', 'error')
                return render_template('nueva_audiencia.html',
                                     title='Programar Audiencia',
                                     form=form,
                                     expedientes=expedientes,
                                     rol=session.get('rol', 'USUARIO'))

            # Crear la audiencia
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

            # Actualizar estado del expediente
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
            # IMPORTANTE: Pasar expedientes también cuando hay error
            return render_template('nueva_audiencia.html',
                                 title='Programar Audiencia',
                                 form=form,
                                 expedientes=expedientes,
                                 rol=session.get('rol', 'USUARIO'))

    # GET: Mostrar formulario
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
            # Validar fecha no sea pasada
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

            # Actualizar estado del expediente
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

            # Si se aplaza, crear nueva audiencia sugerida (opcional)
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

    # Redirigir al expediente si venía de ahí, o al calendario
    referer = request.headers.get('Referer', '')
    if 'expediente' in referer:
        return redirect(url_for('main.ver_expediente', id=expediente_id))

    return redirect(url_for('main.audiencias'))

# ============================================
# RUTAS DE DOCUMENTOS - MÓDULO DOCUMENTOS
# ============================================

import os
import time
from werkzeug.utils import secure_filename
from flask import send_from_directory

# Configuración de uploads
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads', 'documentos')
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'gif', 'mp4', 'mp3', 'zip', 'rar', 'txt'}

try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass  # En Vercel (serverless) no se puede escribir en disco


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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


@bp.route('/documento/subir', methods=['GET', 'POST'])
@requiere_login
@no_cache
def subir_documento():
    """Formulario para subir nuevo documento"""
    if not puede_ver_modulo('documentos'):
        flash('No tiene permisos para subir documentos', 'error')
        return redirect(url_for('main.index'))

    # En Vercel: redirigir a subir-documento-drive (Google Drive)
    if os.environ.get('VERCEL') == '1' or os.environ.get('VERCEL_ENV') is not None:
        flash('En la versión web, los documentos se suben a Google Drive.', 'info')
        return redirect(url_for('main.subir_documento_drive'))

    form = DocumentoForm()
    form.expediente_id.choices = get_expedientes_choices()

    if form.validate_on_submit():
        try:
            archivo = form.archivo.data

            if archivo and allowed_file(archivo.filename):
                filename_original = secure_filename(archivo.filename)
                extension = filename_original.rsplit('.', 1)[1].lower()

                timestamp = int(time.time())
                nombre_unico = f"{timestamp}_{filename_original}"

                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                
                ruta_archivo = os.path.join(UPLOAD_FOLDER, nombre_unico)
                archivo.save(ruta_archivo)

                tamaño = os.path.getsize(ruta_archivo)

                expediente_id = form.expediente_id.data
                if expediente_id == 0:
                    expediente_id = None

                nuevo_documento = Documento(
                    expediente_id=expediente_id,
                    titulo=form.titulo.data,
                    descripcion=form.descripcion.data,
                    categoria=form.categoria.data,
                    nombre_archivo=filename_original,
                    tipo_archivo=extension,
                    tamaño_bytes=tamaño,
                    ruta_archivo=nombre_unico,
                    fecha_documento=form.fecha_documento.data,
                    usuario_subida=session.get('nombre', 'Sistema'),
                    ubicacion='local'
                )

                db.session.add(nuevo_documento)
                db.session.commit()

                flash(f'📄 Documento "{form.titulo.data}" subido correctamente ({nuevo_documento.get_tamaño_formateado()})', 'success')

                if expediente_id:
                    return redirect(url_for('main.expediente_documentos', id=expediente_id))
                else:
                    return redirect(url_for('main.documentos'))
            else:
                flash('❌ Tipo de archivo no permitido', 'error')

        except Exception as e:
            db.session.rollback()
            flash(f'Error al subir documento: {str(e)}', 'error')
            import traceback
            traceback.print_exc()

    return render_template('subir_documento.html',
                         title='Subir Documento',
                         form=form,
                         rol=session.get('rol', 'USUARIO'))


@bp.route('/documento/<int:id>/descargar')
@requiere_login
@no_cache
def descargar_documento(id):
    """Descargar un documento"""
    documento = Documento.query.get_or_404(id)

    try:
        return send_from_directory(UPLOAD_FOLDER, 
                                   documento.ruta_archivo,
                                   as_attachment=True,
                                   download_name=documento.nombre_archivo)
    except Exception as e:
        flash(f'Error al descargar: {str(e)}', 'error')
        return redirect(url_for('main.documentos'))


@bp.route('/documento/<int:id>/visualizar')
@requiere_login
@no_cache
def visualizar_documento(id):
    """Visualizar un documento en el navegador (PDF e imágenes)"""
    documento = Documento.query.get_or_404(id)

    tipos_permitidos = ['pdf', 'jpg', 'jpeg', 'png', 'gif']
    if documento.tipo_archivo.lower() not in tipos_permitidos:
        flash('Este tipo de archivo no se puede visualizar en el navegador. Use descargar.', 'warning')
        return redirect(url_for('main.descargar_documento', id=id))

    try:
        return send_from_directory(UPLOAD_FOLDER,
                                   documento.ruta_archivo,
                                   mimetype=f'application/{documento.tipo_archivo.lower()}' if documento.tipo_archivo.lower() == 'pdf' else f'image/{documento.tipo_archivo.lower()}')
    except Exception as e:
        flash(f'Error al visualizar: {str(e)}', 'error')
        return redirect(url_for('main.documentos'))


@bp.route('/documento/<int:id>/eliminar', methods=['POST'])
@requiere_login
@no_cache
def eliminar_documento(id):
    """Eliminar un documento"""
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para eliminar documentos', 'error')
        return redirect(url_for('main.documentos'))

    documento = Documento.query.get_or_404(id)
    expediente_id = documento.expediente_id

    try:
        # Eliminar archivo físico
        ruta_completa = os.path.join(UPLOAD_FOLDER, documento.ruta_archivo)
        if os.path.exists(ruta_completa):
            os.remove(ruta_completa)

        # Eliminar registro de base de datos
        db.session.delete(documento)
        db.session.commit()

        flash('Documento eliminado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar: {str(e)}', 'error')

    if expediente_id:
        return redirect(url_for('main.expediente_documentos', id=expediente_id))
    return redirect(url_for('main.documentos'))


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
# RUTAS DE NOTIFICACIONES
# ============================================

@bp.route('/notificaciones')
@requiere_login
@no_cache
def notificaciones():
    """Centro de notificaciones del usuario"""
    # Verificar y crear notificaciones de audiencias primero
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

    # Obtener últimas 5 para preview
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

    # Validar tipo
    tipos_permitidos = ['todos', 'civil', 'penal', 'administrativo', 'conciliacion', 'archivo']
    if tipo not in tipos_permitidos:
        flash('Tipo de exportación no válido', 'error')
        return redirect(url_for('main.index'))

    # Obtener datos
    if tipo == 'todos':
        expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()
        nombre_archivo = 'Todos_los_Expedientes'
    else:
        expedientes = Expediente.query.filter_by(tipo=tipo).order_by(Expediente.fecha_registro.desc()).all()
        nombre_archivo = f'Expedientes_{tipo.title()}'

    # Preparar datos para Excel
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

    # Crear DataFrame
    df = pd.DataFrame(data)

    # Crear archivo Excel en memoria
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Expedientes', index=False)

        # Obtener la hoja de trabajo para formateo
        worksheet = writer.sheets['Expedientes']

        # Ajustar anchos de columna
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

    # Validar tipo
    tipos_permitidos = ['todos', 'civil', 'penal', 'administrativo', 'conciliacion', 'archivo']
    if tipo not in tipos_permitidos:
        flash('Tipo de exportación no válido', 'error')
        return redirect(url_for('main.index'))

    # Obtener datos
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

    # Crear PDF
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []

    # Estilos
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1e3a8a'),
        spaceAfter=20,
        alignment=1  # Centrado
    )

    # Título
    elements.append(Paragraph("⚖️ QUIJANDRIA ABOGADOS EIRL", title_style))
    elements.append(Paragraph(f"{titulo}", styles['Heading2']))
    elements.append(Paragraph(f"Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 20))

    # Tabla de datos
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

    # Crear tabla
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

    # Pie de página
    elements.append(Paragraph(f"Total de expedientes: {len(expedientes)}", styles['Normal']))
    elements.append(Paragraph("Sistema de Gestión de Expedientes Legales - Quijandria Abogados", styles['Italic']))

    # Generar PDF
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

    # Crear PDF
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, 
        pagesize=letter,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch
    )
    elements = []

    # Estilos
    styles = getSampleStyleSheet()

    # Estilo personalizado para títulos
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

    # ENCABEZADO
    elements.append(Paragraph("⚖️ QUIJANDRIA ABOGADOS EIRL", title_style))
    elements.append(Paragraph("Sistema de Gestión de Expedientes Legales", styles['Normal']))
    elements.append(Paragraph(f"<b>Reporte de Expediente</b>", styles['Heading3']))
    elements.append(Spacer(1, 10))

    # Línea separadora
    elements.append(Table([['']], colWidths=[7*inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#1e3a8a')),
    ])))
    elements.append(Spacer(1, 10))

    # INFORMACIÓN GENERAL
    elements.append(Paragraph("📋 INFORMACIÓN GENERAL", section_style))

    info_data = [
        ['Campo', 'Valor'],
        ['Tipo de Expediente', expediente.get_tipo_label()],
        ['N° de Expediente', expediente.numero_expediente if expediente.numero_expediente != '-' else 'N/A'],
        ['Cliente', expediente.cliente],
        ['DNI', expediente.dni or 'No aplica'],
        ['Teléfono', expediente.telefono or 'No registrado'],
        ['Materia', expediente.materia],
        ['Estado Actual', expediente.get_estado_label()],
        ['Fecha de Registro', expediente.fecha_registro.strftime('%d/%m/%Y %H:%M') if expediente.fecha_registro else 'N/A'],
    ]

    # Agregar campos específicos según tipo
    if expediente.tipo == 'civil':
        info_data.append(['Juez', expediente.juez or 'No asignado'])
        info_data.append(['Secretario', expediente.secretario or 'No asignado'])
    elif expediente.tipo == 'penal':
        info_data.append(['N° Caso Fiscal', expediente.numero_cf or 'No asignado'])
        info_data.append(['Fiscal', expediente.fiscal or 'No asignado'])
        info_data.append(['Juzgado', expediente.juzgado or 'No asignado'])
    elif expediente.tipo == 'administrativo':
        info_data.append(['Entidad Receptora', expediente.entidad_receptora or 'No especificada'])
        info_data.append(['Trámite', expediente.tramite or 'No especificado'])
    elif expediente.tipo == 'conciliacion':
        info_data.append(['Conciliador', expediente.conciliador or 'No asignado'])
        info_data.append(['Solicitante', expediente.solicitante or 'No especificado'])
        info_data.append(['Invitados', expediente.invitados or 'No especificados'])
    elif expediente.tipo == 'archivo':
        info_data.append(['Ubicación en Archivo', expediente.ubicacion_archivo or 'No especificada'])

    info_data.append(['Descripción', expediente.descripcion or 'Sin descripción'])

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
    ]))
    elements.append(info_table)

    # HISTORIAL DE ESTADOS
    if historial:
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("📈 HISTORIAL DE ESTADOS", section_style))

        hist_data = [['Fecha', 'Estado', 'Descripción', 'Usuario']]
        for h in historial:
            hist_data.append([
                h.fecha.strftime('%d/%m/%Y %H:%M') if h.fecha else 'N/A',
                h.estado,
                (h.descripcion[:40] + '...') if h.descripcion and len(h.descripcion) > 40 else (h.descripcion or 'Sin descripción'),
                h.usuario or 'Sistema'
            ])

        hist_table = Table(hist_data, colWidths=[1.3*inch, 1.2*inch, 3*inch, 1.5*inch])
        hist_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#047857')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ecfdf5')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(hist_table)

    # AUDIENCIAS
    if audiencias:
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("📅 AUDIENCIAS PROGRAMADAS", section_style))

        aud_data = [['Fecha', 'Hora', 'Tipo', 'Lugar', 'Estado']]
        for a in audiencias:
            aud_data.append([
                a.fecha.strftime('%d/%m/%Y') if a.fecha else 'N/A',
                a.hora.strftime('%H:%M') if a.hora else 'N/A',
                a.get_tipo_label() if hasattr(a, 'get_tipo_label') else a.tipo_audiencia,
                a.lugar or 'No especificado',
                a.get_estado_label() if hasattr(a, 'get_estado_label') else a.estado
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
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(aud_table)

    # DOCUMENTOS
    if documentos:
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("📄 DOCUMENTOS ADJUNTOS", section_style))

        doc_data = [['Título', 'Categoría', 'Tipo', 'Fecha']]
        for d in documentos:
            doc_data.append([
                d.titulo[:30] + '...' if len(d.titulo) > 30 else d.titulo,
                d.categoria.title() if d.categoria else 'Otro',
                d.tipo_archivo.upper() if d.tipo_archivo else 'N/A',
                d.fecha_subida.strftime('%d/%m/%Y') if d.fecha_subida else 'N/A'
            ])

        doc_table = Table(doc_data, colWidths=[3*inch, 1.5*inch, 1*inch, 1.5*inch])
        doc_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4b5563')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f9fafb')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(doc_table)

    # PIE DE PÁGINA
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

    # Generar PDF
    doc.build(elements)
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

    # Crear archivo Excel
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

        # Agregar campos específicos según tipo
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

        # Formatear hoja de resumen
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
                doc_data.append({
                    'N°': len(doc_data) + 1,
                    'Título': d.titulo,
                    'Categoría': d.categoria.title() if d.categoria else 'Otro',
                    'Tipo': d.tipo_archivo.upper() if d.tipo_archivo else 'N/A',
                    'Tamaño': d.get_tamaño_formateado() if hasattr(d, 'get_tamaño_formateado') else f"{d.tamaño_bytes} bytes",
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
            worksheet_doc.column_dimensions['F'].width = 15
            worksheet_doc.column_dimensions['G'].width = 18
            worksheet_doc.column_dimensions['H'].width = 15
            worksheet_doc.column_dimensions['I'].width = 30

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

    # Crear PDF con estilo profesional limpio
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, 
        pagesize=letter,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch
    )

    elements = []
    styles = getSampleStyleSheet()

    # Estilos personalizados profesionales
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

    # ENCABEZADO
    elements.append(Paragraph("⚖️ QUIJANDRIA ABOGADOS EIRL", titulo_estudio))
    elements.append(Paragraph("Sistema de Gestión de Expedientes Legales", subtitulo_sistema))

    # Línea decorativa
    elements.append(Table([['']], colWidths=[6.5*inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#1e3a8a')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ])))

    # Título del documento
    tipo_label = expediente.get_tipo_label()
    elements.append(Paragraph(f"RESUMEN DE {tipo_label.upper()}", titulo_documento))

    # TABLA DE INFORMACIÓN
    datos_principales = [
        ['INFORMACIÓN GENERAL', ''],
        ['N° de Expediente:', expediente.numero_expediente if expediente.numero_expediente != '-' else 'No aplica (Administrativo)'],
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

    # Campos específicos según tipo
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

    # Fechas
    datos_principales.extend([
        ['', ''],
        ['REGISTRO Y SEGUIMIENTO', ''],
        ['Fecha de Ingreso:', expediente.fecha_registro.strftime('%d de %B de %Y').upper() if expediente.fecha_registro else 'No registrada'],
        ['Última Actualización:', expediente.fecha_actualizacion.strftime('%d de %B de %Y - %H:%M').upper() if expediente.fecha_actualizacion else 'Sin actualizaciones'],
        ['Registrado por:', expediente.usuario_registro or 'Sistema'],
    ])

    # Crear tabla
    tabla_data = []
    for fila in datos_principales:
        if fila[0] == '' and fila[1] == '':
            tabla_data.append(['', ''])
        elif fila[1] == '':
            tabla_data.append([fila[0], ''])
        else:
            tabla_data.append([fila[0], fila[1]])

    tabla = Table(tabla_data, colWidths=[2*inch, 4.5*inch])
    tabla.setStyle(TableStyle([
        # Títulos de sección
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('SPAN', (0, 0), (-1, 0)),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),

        ('BACKGROUND', (0, 5), (-1, 5), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 5), (-1, 5), colors.white),
        ('FONTNAME', (0, 5), (-1, 5), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 5), (-1, 5), 10),
        ('SPAN', (0, 5), (-1, 5)),
        ('ALIGN', (0, 5), (-1, 5), 'CENTER'),

        ('BACKGROUND', (0, 9), (-1, 9), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 9), (-1, 9), colors.white),
        ('FONTNAME', (0, 9), (-1, 9), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 9), (-1, 9), 10),
        ('SPAN', (0, 9), (-1, 9)),
        ('ALIGN', (0, 9), (-1, 9), 'CENTER'),

        ('BACKGROUND', (0, -6), (-1, -6), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, -6), (-1, -6), colors.white),
        ('FONTNAME', (0, -6), (-1, -6), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -6), (-1, -6), 10),
        ('SPAN', (0, -6), (-1, -6)),
        ('ALIGN', (0, -6), (-1, -6), 'CENTER'),

        # Etiquetas
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (0, -1), 9),
        ('TEXTCOLOR', (0, 1), (0, -1), colors.HexColor('#475569')),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f8fafc')),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('LEFTPADDING', (0, 1), (0, -1), 12),

        # Valores
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica'),
        ('FONTSIZE', (1, 1), (1, -1), 10),
        ('TEXTCOLOR', (1, 1), (1, -1), colors.HexColor('#1e293b')),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('LEFTPADDING', (1, 1), (1, -1), 12),

        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
    ]))

    elements.append(tabla)
    elements.append(Spacer(1, 20))

    # Descripción
    if expediente.descripcion:
        desc_style = ParagraphStyle(
            'Desc',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#334155'),
            alignment=0,
            spaceAfter=6
        )
        elements.append(Paragraph("<b>DESCRIPCIÓN DEL CASO:</b>", desc_style))

        desc_data = [[expediente.descripcion]]
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

    # Pie de página
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

    doc.build(elements)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Resumen_{expediente.numero_expediente.replace("/", "_")}_{datetime.now().strftime("%Y%m%d")}.pdf'
    )

# ============================================
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

    # Validar que no sea ya un archivo
    if expediente_original.tipo == 'archivo':
        flash('Este expediente ya está en archivo', 'warning')
        return redirect(url_for('main.ver_expediente', id=id))

    # Validar que esté en estado concluido o similar
    estados_permitidos = ['proceso_completado', 'resuelto_favorable', 'resuelto_desfavorable', 
                          'archivado', 'enviado_a_archivo', 'ingresado', 'en_proceso', 
                          'audiencia_programada', 'seguimiento', 'derivado_juzgado']

    if expediente_original.estado_actual not in estados_permitidos:
        flash('El expediente debe estar concluido para enviarlo a archivo', 'warning')
        return redirect(url_for('main.ver_expediente', id=id))

    if request.method == 'POST':
        try:
            # Obtener datos del formulario
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

            # Parsear fecha
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
            db.session.flush()  # ← OBTIENE EL ID sin commit definitivo

            # 2. Marcar original como enviado a archivo
            expediente_original.estado_actual = 'enviado_a_archivo'
            expediente_original.fecha_actualizacion = datetime.now()

            # 3. Agregar historial al original (id ya existe)
            historial_original = EstadoHistorial(
                expediente_id=expediente_original.id,
                estado='enviado_a_archivo',
                descripcion=f'Expediente enviado a archivo. Ubicación: {ubicacion}. ' +
                           (f'Nota: {nota_final}' if nota_final else ''),
                usuario=session.get('nombre', 'Sistema')
            )
            db.session.add(historial_original)

            # 4. Agregar historial al NUEVO archivo (id ya disponible gracias a flush)
            historial_archivo = EstadoHistorial(
                expediente_id=expediente_archivo.id,
                estado='archivado',
                descripcion=f'Expediente archivado desde {expediente_original.get_tipo_label()} N° {expediente_original.get_identificador_principal()}. ' +
                           f'Ubicación: {ubicacion}. ' +
                           (f'Resumen: {nota_final}' if nota_final else ''),
                usuario=session.get('nombre', 'Sistema')
            )
            db.session.add(historial_archivo)

            # 5. Commit final de TODO
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

    # GET: Mostrar formulario
    return render_template('enviar_a_archivo.html',
                         title='Enviar a Archivo',
                         expediente_original=expediente_original,
                         hoy=date.today().isoformat(),
                         rol=session.get('rol', 'USUARIO'))

# ============================================
# GOOGLE DRIVE INTEGRACIÓN - DOCUMENTOS EN LA NUBE
# ============================================

from app.drive_service import (
    get_auth_url, exchange_code, get_drive_service,
    subir_archivo, eliminar_archivo, obtener_espacio_usado,
    descargar_archivo
)

# ============================================
# GOOGLE DRIVE OAUTH
# ============================================

@bp.route('/auth/google')
@requiere_login
def auth_google():
    """Inicia flujo de autorización con Google Drive"""
    try:
        auth_data = get_auth_url()
        
        # ← DEBUG: Ver qué tipo de dato devuelve
        print(f"DEBUG: tipo de auth_data = {type(auth_data)}")
        print(f"DEBUG: valor de auth_data = {str(auth_data)[:100]}")
        
        # Si es string (URL directa), manejarlo
        if isinstance(auth_data, str):
            session['oauth_state'] = 'manual_state'
            session['code_verifier'] = 'manual_verifier'
            return redirect(auth_data)
        
        # Si es diccionario (lo esperado)
        session['oauth_state'] = auth_data['state']
        session['code_verifier'] = auth_data['code_verifier']
        
        return redirect(auth_data['url'])
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f'Error iniciando autorización: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('main.index'))

@bp.route('/oauth2callback')
def oauth2callback():
    """Callback de Google OAuth"""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        flash(f'Error de autorización: {error}', 'danger')
        return redirect(url_for('main.index'))
    
    if not code:
        flash('Error: No se recibió código de autorización', 'danger')
        return redirect(url_for('main.index'))
    
    # Recuperar code_verifier de sesión
    code_verifier = session.get('code_verifier')
    if not code_verifier:
        flash('Error: Sesión de autorización expirada. Intente nuevamente.', 'danger')
        return redirect(url_for('main.index'))
    
    try:
        # Intercambiar código con verifier
        credentials = exchange_code(code, code_verifier)
        
        # ← GUARDAR TOKEN EN BASE DE DATOS
        usuario_id = session.get('usuario_id')
        if not usuario_id:
            flash('Error: No se pudo identificar al usuario. Inicie sesión nuevamente.', 'danger')
            return redirect(url_for('main.logout'))
        
        from sqlalchemy import text
        
        # Verificar si ya existe token para este usuario
        existing = db.session.execute(
            text("SELECT id FROM google_tokens WHERE usuario_id = :uid"),
            {'uid': usuario_id}
        ).fetchone()
        
        import json
        token_json = json.dumps(credentials)
        
        if existing:
            # Actualizar token existente
            db.session.execute(
                text("""
                    UPDATE google_tokens 
                    SET google_token = :token, fecha_actualizacion = NOW() 
                    WHERE usuario_id = :uid
                """),
                {'token': token_json, 'uid': usuario_id}
            )
        else:
            # Insertar nuevo token
            db.session.execute(
                text("""
                    INSERT INTO google_tokens (usuario_id, google_token, fecha_creacion, fecha_actualizacion)
                    VALUES (:uid, :token, NOW(), NOW())
                """),
                {'uid': usuario_id, 'token': token_json}
            )
        
        db.session.commit()
        flash('✅ Google Drive conectado correctamente', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error conectando Google Drive: {str(e)}', 'danger')
    
    # Limpiar sesión
    session.pop('oauth_state', None)
    session.pop('code_verifier', None)
    
    return redirect(url_for('main.index'))

# ============================================
# SUBIR DOCUMENTO A GOOGLE DRIVE
# ============================================

@bp.route('/subir-documento-drive', methods=['GET', 'POST'])
@requiere_login
def subir_documento_drive():
    """Sube documento a Google Drive"""
    
    # Si es GET, mostrar formulario
    if request.method == 'GET':
        form = DocumentoForm()
        form.expediente_id.choices = get_expedientes_choices()
        
        # Obtener expediente_id de query string si viene de un expediente específico
        expediente_id = request.args.get('expediente_id', type=int)
        expediente = None
        if expediente_id:
            expediente = Expediente.query.get(expediente_id)
        
        # ← CORREGIDO: Agregar lista de expedientes para el select
        expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()
        
        return render_template('subir_documento.html',
                             title='Subir a Google Drive',
                             form=form,
                             expediente=expediente,
                             expedientes=expedientes,  # ← CORREGIDO
                             rol=session.get('rol', 'USUARIO'),
                             modo_drive=True)
    
    # POST: Procesar subida
    if 'archivo' not in request.files:
        flash('No se seleccionó archivo', 'danger')
        return redirect(request.referrer or url_for('main.documentos'))
    
    archivo = request.files['archivo']
    expediente_id = request.form.get('expediente_id', type=int)
    
    if archivo.filename == '':
        flash('Nombre de archivo vacío', 'danger')
        return redirect(request.referrer or url_for('main.documentos'))
    
    # Verificar token de Google
    usuario_id = session.get('usuario_id')
    if not usuario_id:
        flash('Error de sesión. Inicie sesión nuevamente.', 'danger')
        return redirect(url_for('main.logout'))
    
    try:
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT google_token FROM google_tokens WHERE usuario_id = :uid"),
            {'uid': usuario_id}
        ).fetchone()
        
        if not result:
            flash('❌ Debes conectar Google Drive primero. Haz clic en "Subir a Google Drive" para autorizar.', 'warning')
            return redirect(url_for('main.auth_google'))
        
        import json
        credentials_dict = json.loads(result[0])
        service = get_drive_service(credentials_dict)
        
        # Verificar espacio antes de subir
        espacio = obtener_espacio_usado(service)
        
        if espacio['porcentaje'] >= 80:
            flash(f'⚠️ Google Drive al {espacio["porcentaje"]:.1f}%. Libera espacio antes de subir más documentos.', 'warning')
            return redirect(url_for('main.gestionar_espacio'))
        
        # Leer archivo
        file_content = archivo.read()
        mime_type = archivo.content_type or 'application/octet-stream'
        
        # Subir a Drive
        resultado = subir_archivo(service, file_content, archivo.filename, mime_type)
        
        # Guardar en base de datos
        from datetime import datetime
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
            tamaño_bytes=len(file_content)
        )
        
        db.session.add(nuevo_documento)
        db.session.commit()
        
        flash('✅ Documento subido a Google Drive correctamente', 'success')
        
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
def ver_documento(id):
    """Muestra documento desde Google Drive en viewer embebido"""
    documento = Documento.query.get_or_404(id)
    
    if documento.ubicacion == 'local':
        flash('📁 Este documento solo está disponible en la oficina (almacenamiento local)', 'info')
        return redirect(request.referrer or url_for('main.expediente_documentos', id=documento.expediente_id))
    
    if not documento.drive_file_id:
        flash('Documento no disponible en la nube', 'danger')
        return redirect(request.referrer or url_for('main.expediente_documentos', id=documento.expediente_id))
    
    return render_template('ver_documento.html', documento=documento)

# ============================================
# ELIMINAR DOCUMENTO (Drive y/o Local)
# ============================================

@bp.route('/documento/<int:id>/eliminar-drive', methods=['POST'])
@requiere_login
def eliminar_documento_drive(id):
    """Elimina documento de Drive y/o local"""
    documento = Documento.query.get_or_404(id)
    
    try:
        # Si está en Drive, eliminar de Drive primero
        if documento.ubicacion in ['drive', 'ambos'] and documento.drive_file_id:
            usuario_id = session.get('usuario_id')
            if usuario_id:
                from sqlalchemy import text
                result = db.session.execute(
                    text("SELECT google_token FROM google_tokens WHERE usuario_id = :uid"),
                    {'uid': usuario_id}
                ).fetchone()
                
                if result:
                    import json
                    credentials_dict = json.loads(result[0])
                    service = get_drive_service(credentials_dict)
                    eliminar_archivo(service, documento.drive_file_id)
        
        # Si está en local, eliminar archivo físico
        if documento.ubicacion in ['local', 'ambos'] and documento.ruta_archivo:
            import os
            ruta_completa = os.path.join(UPLOAD_FOLDER, documento.ruta_archivo)
            if os.path.exists(ruta_completa):
                os.remove(ruta_completa)
        
        # Eliminar registro de base de datos
        db.session.delete(documento)
        db.session.commit()
        
        flash('🗑️ Documento eliminado correctamente', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error eliminando documento: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('main.expediente_documentos', id=documento.expediente_id))

# ============================================
# GESTIONAR ESPACIO EN GOOGLE DRIVE
# ============================================

@bp.route('/gestionar-espacio')
@requiere_login
def gestionar_espacio():
    """Muestra alerta de espacio y opciones para liberar"""
    usuario_id = session.get('usuario_id')
    if not usuario_id:
        flash('Error de sesión', 'danger')
        return redirect(url_for('main.logout'))
    
    try:
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT google_token FROM google_tokens WHERE usuario_id = :uid"),
            {'uid': usuario_id}
        ).fetchone()
        
        if not result:
            flash('No tienes Google Drive conectado', 'warning')
            return redirect(url_for('main.auth_google'))
        
        import json
        credentials_dict = json.loads(result[0])
        service = get_drive_service(credentials_dict)
        espacio = obtener_espacio_usado(service)
        
        # Obtener documentos que ocupan espacio
        documentos_drive = Documento.query.filter(
            Documento.ubicacion.in_(['drive', 'ambos']),
            Documento.drive_file_id.isnot(None)
        ).order_by(Documento.fecha_subida.asc()).all()
        
        return render_template('gestionar_espacio.html',
                             espacio=espacio,
                             documentos=documentos_drive)
                             
    except Exception as e:
        flash(f'Error obteniendo información de Drive: {str(e)}', 'danger')
        return redirect(url_for('main.index'))

@bp.route('/liberar-espacio', methods=['POST'])
@requiere_login
def liberar_espacio():
    """Mueve documentos de Drive a local o los elimina"""
    accion = request.form.get('accion')
    documento_ids = request.form.getlist('documentos[]')
    
    if not documento_ids:
        flash('No seleccionaste documentos', 'warning')
        return redirect(url_for('main.gestionar_espacio'))
    
    usuario_id = session.get('usuario_id')
    if not usuario_id:
        flash('Error de sesión', 'danger')
        return redirect(url_for('main.logout'))
    
    try:
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT google_token FROM google_tokens WHERE usuario_id = :uid"),
            {'uid': usuario_id}
        ).fetchone()
        
        if not result:
            flash('Google Drive no conectado', 'danger')
            return redirect(url_for('main.gestionar_espacio'))
        
        import json
        credentials_dict = json.loads(result[0])
        service = get_drive_service(credentials_dict)
        
        liberados = 0
        
        for doc_id in documento_ids:
            documento = Documento.query.get(doc_id)
            if not documento or not documento.drive_file_id:
                continue
            
            try:
                if accion == 'eliminar':
                    eliminar_archivo(service, documento.drive_file_id)
                    db.session.delete(documento)
                    
                elif accion == 'mover_local':
                    file_content = descargar_archivo(service, documento.drive_file_id)
                    
                    if file_content:
                        # Guardar en carpeta local
                        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                        
                        local_filename = f"exp_{documento.expediente_id}_{documento.nombre_archivo}"
                        local_path = os.path.join(UPLOAD_FOLDER, local_filename)
                        
                        with open(local_path, 'wb') as f:
                            f.write(file_content)
                        
                        # Eliminar de Drive
                        eliminar_archivo(service, documento.drive_file_id)
                        
                        # Actualizar registro
                        documento.ruta_archivo = local_filename
                        documento.url_drive = None
                        documento.drive_file_id = None
                        documento.ubicacion = 'local'
                
                liberados += 1
                
            except Exception as e:
                print(f"Error procesando documento {doc_id}: {e}")
                continue
        
        db.session.commit()
        
        if accion == 'eliminar':
            flash(f'🗑️ {liberados} documentos eliminados permanentemente', 'success')
        else:
            flash(f'📁 {liberados} documentos movidos a almacenamiento local. Ya NO estarán disponibles desde la web.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    
    return redirect(url_for('main.gestionar_espacio'))

# ============================================
# FIN DEL ARCHIVO
# ============================================
