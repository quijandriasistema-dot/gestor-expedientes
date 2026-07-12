# app/routes.py - Rutas de la aplicación
# Sistema de Gestión de Expedientes Legales - Quijandria Abogados EIRL
# Versión con Service Account para Google Drive

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, after_this_request, send_file
from functools import wraps
from datetime import datetime, timedelta, date, timezone
from app import db
from app.models import Expediente, EstadoHistorial, Audiencia, Documento, Notificacion, Usuario
from app.forms import (
    ExpedienteForm, EstadoForm, BusquedaForm, 
    AudienciaForm, BusquedaAudienciaForm, 
    DocumentoForm, BusquedaDocumentoForm,
    ActualizacionModalForm, EstadoSelectorForm
)
from urllib.parse import unquote
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
# CONFIGURACIÓN DE ZONA HORARIA (Perú UTC-5)
# ============================================
try:
    import pytz
    LIMA_TZ = pytz.timezone('America/Lima')
except ImportError:
    LIMA_TZ = None

def ahora_peru():
    """Retorna la hora actual de Perú (UTC-5)"""
    if LIMA_TZ:
        return datetime.now(LIMA_TZ).replace(tzinfo=None)
    # Fallback sin pytz: forma moderna sin datetime.utcnow()
    peru_offset = timezone(timedelta(hours=-5))
    return datetime.now(peru_offset).replace(tzinfo=None)

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

def _cargar_usuarios(solo_activos=True):
    """Carga usuarios desde Supabase (tabla usuario) - BAJO DEMANDA"""
    usuarios = {}
    try:
        query = Usuario.query
        if solo_activos:
            query = query.filter_by(activo=True)
        for u in query.all():
            usuarios[u.username] = {
                'password_hash': u.password_hash,
                'nombre': u.nombre,
                'rol': u.rol,
                'modulos': u.get_modulos_list(),
                'activo': u.activo,
                'email': u.email,
                'fecha_registro': u.fecha_registro
            }
    except Exception as e:
        print(f"Error cargando usuarios: {e}")
    return usuarios

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
    """Verifica si el usuario puede exportar (Admin, Desarrollador o Usuario)"""
    return session.get('rol') in ['ADMINISTRADOR', 'DESARROLLADOR', 'USUARIO']

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
# API PARA VALIDAR UNICIDAD DE EXPEDIENTE (TIEMPO REAL)
# ============================================

@bp.route('/api/validar-expediente')
@requiere_login
@no_cache
def validar_expediente():
    """
    Valida unicidad de número de expediente en tiempo real.
    Retorna: bloqueado (mismo tipo) o advertencia (otro tipo)
    """
    numero = request.args.get('numero', '').strip()
    tipo = request.args.get('tipo', '').strip()

    if not numero or not tipo or tipo == 'administrativo':
        return jsonify({'valido': True})

    # --- Validar duplicado dentro del MISMO tipo ---
    existe_mismo_tipo = Expediente.query.filter(
        Expediente.tipo == tipo,
        Expediente.numero_expediente == numero
    ).first()

    if existe_mismo_tipo:
        return jsonify({
            'valido': False,
            'bloquear': True,
            'mensaje': f'❌ El N° de Expediente "{numero}" ya existe en {existe_mismo_tipo.get_tipo_label()}. '
                       f'Cliente: {existe_mismo_tipo.cliente}. No se puede registrar duplicado.',
            'expediente_existente': {
                'id': existe_mismo_tipo.id,
                'tipo': existe_mismo_tipo.get_tipo_label(),
                'cliente': existe_mismo_tipo.cliente
            }
        })

    # --- Validar duplicado en OTRO tipo (advertencia) ---
    tipos_con_expediente = ['civil', 'penal', 'conciliacion', 'archivo']
    if tipo in tipos_con_expediente:
        existe_otro = Expediente.query.filter(
            Expediente.tipo.in_(tipos_con_expediente),
            Expediente.tipo != tipo,
            Expediente.numero_expediente == numero
        ).first()

        if existe_otro:
            return jsonify({
                'valido': True,
                'bloquear': False,
                'advertencia': True,
                'mensaje': f'⚠️ Este N° de Expediente ya está registrado en {existe_otro.get_tipo_label()} '
                           f'(Cliente: {existe_otro.cliente}). Puede continuar si es un caso diferente.',
                'expediente_existente': {
                    'id': existe_otro.id,
                    'tipo': existe_otro.get_tipo_label(),
                    'cliente': existe_otro.cliente
                }
            })

    return jsonify({'valido': True})

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
            # Verificar si el usuario está activo
            if not usuario.activo:
                flash('Su cuenta ha sido desactivada. Contacte al administrador.', 'error')
                return render_template('login.html', title='Iniciar Sesión')
            
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

    # ============================================
    # SEGUIMIENTO DE EXPEDIENTES - ÚLTIMAS ACTUALIZACIONES
    # ============================================
    estados_excluir_seguimiento = [
        'Expediente editado',
        'Expediente registrado en el sistema',
        'ingresado'
    ]

    from sqlalchemy import func

    # Subconsulta: última fecha de actualización real por expediente
    ultima_actualizacion_subq = db.session.query(
        EstadoHistorial.expediente_id,
        func.max(EstadoHistorial.fecha).label('ultima_fecha')
    ).filter(
        EstadoHistorial.descripcion.isnot(None),
        EstadoHistorial.descripcion != '',
        ~EstadoHistorial.estado.in_(estados_excluir_seguimiento),
        ~EstadoHistorial.descripcion.like('Expediente editado por%'),
        ~EstadoHistorial.descripcion.like('Expediente registrado%')
    ).group_by(
        EstadoHistorial.expediente_id
    ).subquery()

    # Obtener expedientes con su última actualización
    seguimiento_expedientes = db.session.query(
        Expediente,
        EstadoHistorial
    ).outerjoin(
        ultima_actualizacion_subq,
        Expediente.id == ultima_actualizacion_subq.c.expediente_id
    ).outerjoin(
        EstadoHistorial,
        db.and_(
            EstadoHistorial.expediente_id == ultima_actualizacion_subq.c.expediente_id,
            EstadoHistorial.fecha == ultima_actualizacion_subq.c.ultima_fecha
        )
    ).filter(
        ~Expediente.estado_actual.in_(['proceso_completado', 'resuelto_favorable', 
                                        'resuelto_desfavorable', 'archivado', 
                                        'enviado_a_archivo', 'anulado'])
    ).order_by(
        func.coalesce(ultima_actualizacion_subq.c.ultima_fecha, Expediente.fecha_registro).asc()
    ).all()

    # Calcular días transcurridos y nivel de alerta
    hoy = ahora_peru().date()
    seguimiento_data = []

    for exp, hist in seguimiento_expedientes:
        if hist and hist.fecha:
            ultima_fecha = hist.fecha.date() if hasattr(hist.fecha, 'date') else hist.fecha
            dias_transcurridos = (hoy - ultima_fecha).days
            ultima_descripcion = hist.descripcion
        else:
            ultima_fecha = exp.fecha_registro.date() if hasattr(exp.fecha_registro, 'date') else exp.fecha_registro
            dias_transcurridos = (hoy - ultima_fecha).days
            ultima_descripcion = 'Sin actuaciones registradas'

        if dias_transcurridos > 30:
            alerta = 'critica'
            alerta_label = '🔴 CRÍTICO'
            alerta_color = 'danger'
        elif dias_transcurridos > 15:
            alerta = 'advertencia'
            alerta_label = '🟠 ADVERTENCIA'
            alerta_color = 'warning'
        elif dias_transcurridos > 7:
            alerta = 'atencion'
            alerta_label = '🟡 ATENCIÓN'
            alerta_color = 'warning'
        else:
            alerta = 'normal'
            alerta_label = '🟢 ACTUALIZADO'
            alerta_color = 'success'

        seguimiento_data.append({
            'expediente': exp,
            'ultima_fecha': ultima_fecha,
            'dias_transcurridos': dias_transcurridos,
            'ultima_descripcion': ultima_descripcion,
            'alerta': alerta,
            'alerta_label': alerta_label,
            'alerta_color': alerta_color
        })

    # Contadores para resumen
    total_criticos = sum(1 for s in seguimiento_data if s['alerta'] == 'critica')
    total_advertencias = sum(1 for s in seguimiento_data if s['alerta'] == 'advertencia')
    total_atencion = sum(1 for s in seguimiento_data if s['alerta'] == 'atencion')
    total_normal = sum(1 for s in seguimiento_data if s['alerta'] == 'normal')

    # ============================================
    # FILTRO POR SEMÁFORO
    # ============================================
    filtro_semaforo = request.args.get('semaforo', '').strip()
    if filtro_semaforo and filtro_semaforo in ['critica', 'advertencia', 'atencion', 'normal']:
        seguimiento_data = [s for s in seguimiento_data if s['alerta'] == filtro_semaforo]

    # ============================================
    # PAGINACIÓN (10 por página)
    # ============================================
    ITEMS_POR_PAGINA = 10
    pagina_actual = request.args.get('page', 1, type=int)
    if pagina_actual < 1:
        pagina_actual = 1

    total_items = len(seguimiento_data)
    total_paginas = (total_items + ITEMS_POR_PAGINA - 1) // ITEMS_POR_PAGINA

    if pagina_actual > total_paginas and total_paginas > 0:
        pagina_actual = total_paginas

    inicio = (pagina_actual - 1) * ITEMS_POR_PAGINA
    fin = inicio + ITEMS_POR_PAGINA
    seguimiento_paginado = seguimiento_data[inicio:fin]

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
                         seguimiento_data=seguimiento_data,
                         seguimiento_paginado=seguimiento_paginado,
                         total_criticos=total_criticos,
                         total_advertencias=total_advertencias,
                         total_atencion=total_atencion,
                         total_normal=total_normal,
                         pagina_actual=pagina_actual,
                         total_paginas=total_paginas,
                         filtro_semaforo=filtro_semaforo,
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
        query = query.filter(Expediente.estado_actual == filtro_estado)

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
    """
    Verifica unicidad del expediente:
    1. No duplicados dentro del mismo tipo (BLOQUEA)
    2. Aviso si el mismo número existe en otro tipo (ADVERTENCIA)
    """
    if tipo == 'administrativo':
        return True, None, None

    num_exp = numero_expediente.strip()

    # --- VALIDACIÓN 1: Duplicado dentro del MISMO tipo (BLOQUEA) ---
    query_mismo_tipo = Expediente.query.filter(
        Expediente.tipo == tipo,
        Expediente.numero_expediente == num_exp
    )
    if id_excluir:
        query_mismo_tipo = query_mismo_tipo.filter(Expediente.id != id_excluir)

    existe_mismo_tipo = query_mismo_tipo.first()
    if existe_mismo_tipo:
        return False, (
            f'El N° de Expediente "{num_exp}" ya existe en {existe_mismo_tipo.get_tipo_label()}. '
            f'Cliente: {existe_mismo_tipo.cliente}. No se permite duplicado.'
        ), None

    # --- VALIDACIÓN 2: Mismo número en OTRO tipo (ADVERTENCIA, permite continuar) ---
    tipos_con_expediente = ['civil', 'penal', 'conciliacion', 'archivo']
    
    if tipo in tipos_con_expediente:
        query_otro_tipo = Expediente.query.filter(
            Expediente.tipo.in_(tipos_con_expediente),
            Expediente.tipo != tipo,
            Expediente.numero_expediente == num_exp
        )
        if id_excluir:
            query_otro_tipo = query_otro_tipo.filter(Expediente.id != id_excluir)

        existe_otro_tipo = query_otro_tipo.first()
        if existe_otro_tipo:
            advertencia = (
                f'⚠️ El N° de Expediente "{num_exp}" ya está registrado '
                f'en {existe_otro_tipo.get_tipo_label()} (Cliente: {existe_otro_tipo.cliente}). '
                f'Verifique antes de continuar.'
            )
            return True, None, advertencia

    return True, None, None

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
                es_unico, mensaje_error, advertencia = verificar_unicidad_expediente(
                    form.numero_expediente.data, 
                    form.tipo.data
                )
                if not es_unico:
                    flash(mensaje_error, 'error')
                    return render_template('nuevo_expediente.html',
                                         title='Nuevo Expediente',
                                         form=form,
                                         rol=session.get('rol', 'USUARIO'))
                if advertencia:
                    flash(advertencia, 'warning')

            expediente = Expediente(
                tipo=form.tipo.data,
                numero_expediente=form.numero_expediente.data if form.tipo.data != 'administrativo' else None,
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
    """Ver detalle de un expediente específico - VISTA REORGANIZADA"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para ver expedientes', 'error')
        return redirect(url_for('main.index'))

    form_estado = EstadoForm()
    form_modal = ActualizacionModalForm()

    expediente = Expediente.query.get_or_404(id)
    
    # TODOS los estados para el historial completo (al final)
    historial = EstadoHistorial.query.filter_by(
        expediente_id=id
    ).order_by(EstadoHistorial.fecha.desc()).all()

    # AVANCES: Solo actuaciones reales (excluir estados automáticos del sistema)
    # Orden: MAS ANTIGUO arriba, NUEVOS debajo (invertido respecto al historial)
    estados_excluir_avance = [
        'Expediente editado',
        'Expediente registrado en el sistema',
        'ingresado'  # El estado inicial de creación
    ]
    avances = [h for h in historial if h.descripcion and h.descripcion.strip() 
               and h.estado not in estados_excluir_avance
               and not h.descripcion.startswith('Expediente editado por')
               and not h.descripcion.startswith('Expediente registrado')]
    # Invertir orden: antiguo arriba, nuevo abajo
    avances = list(reversed(avances))

    audiencias = Audiencia.query.filter_by(
        expediente_id=id
    ).order_by(Audiencia.fecha.desc(), Audiencia.hora.desc()).all()

    return render_template('expediente_detalle.html',
                         title=f'Expediente {expediente.get_identificador_principal()}',
                         expediente=expediente,
                         historial=historial,
                         avances=avances,
                         audiencias=audiencias,
                         form_estado=form_estado,
                         form_modal=form_modal,
                         ahora_peru=ahora_peru,
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
        # 1. Eliminar documentos de Drive primero
        documentos = Documento.query.filter_by(expediente_id=id).all()
        for doc in documentos:
            if doc.drive_file_id:
                try:
                    eliminar_archivo_drive(doc.drive_file_id)
                except Exception as e:
                    print(f"Error eliminando doc {doc.id} de Drive: {e}")

        # 2. Obtener IDs de audiencias para eliminar notificaciones relacionadas
        audiencias = Audiencia.query.filter_by(expediente_id=id).all()
        audiencias_ids = [a.id for a in audiencias]

        # 3. Eliminar NOTIFICACIONES que referencian a las audiencias (hijos primero)
        if audiencias_ids:
            Notificacion.query.filter(Notificacion.audiencia_id.in_(audiencias_ids)).delete(synchronize_session=False)

        # 4. Eliminar NOTIFICACIONES que referencian al expediente directamente
        Notificacion.query.filter_by(expediente_id=id).delete(synchronize_session=False)

        # 5. Ahora eliminar AUDIENCIAS (ya no tienen referencias en notificaciones)
        Audiencia.query.filter_by(expediente_id=id).delete(synchronize_session=False)

        # 6. Eliminar ESTADOS del historial
        EstadoHistorial.query.filter_by(expediente_id=id).delete(synchronize_session=False)

        # 7. Eliminar DOCUMENTOS de la base de datos
        Documento.query.filter_by(expediente_id=id).delete(synchronize_session=False)

        # 8. Finalmente eliminar el EXPEDIENTE
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
                # numero_expediente: opcional para administrativos
                # Si ya tiene un número asignado, se respeta. Si se envía uno nuevo, se actualiza.
                num_exp_admin = request.form.get('numero_expediente', '').strip()
                if num_exp_admin:
                    expediente.numero_expediente = num_exp_admin
                # Si no viene nada en el form, no tocamos el valor actual (puede ser NULL o tener número previo)
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

                es_unico, mensaje_error, advertencia = verificar_unicidad_expediente(
                    numero_exp, 'civil', id_excluir=id
                )
                if not es_unico:
                    flash(mensaje_error, 'error')
                    return redirect(url_for('main.editar_expediente', id=id))
                if advertencia:
                    flash(advertencia, 'warning')

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

                es_unico, mensaje_error, advertencia = verificar_unicidad_expediente(
                    numero_exp, 'penal', id_excluir=id
                )
                if not es_unico:
                    flash(mensaje_error, 'error')
                    return redirect(url_for('main.editar_expediente', id=id))
                if advertencia:
                    flash(advertencia, 'warning')

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

                es_unico, mensaje_error, advertencia = verificar_unicidad_expediente(
                    numero_exp, 'conciliacion', id_excluir=id
                )
                if not es_unico:
                    flash(mensaje_error, 'error')
                    return redirect(url_for('main.editar_expediente', id=id))
                if advertencia:
                    flash(advertencia, 'warning')

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

                es_unico, mensaje_error, advertencia = verificar_unicidad_expediente(
                    numero_exp, 'archivo', id_excluir=id
                )
                if not es_unico:
                    flash(mensaje_error, 'error')
                    return redirect(url_for('main.editar_expediente', id=id))
                if advertencia:
                    flash(advertencia, 'warning')

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

# ============================================
# RUTAS DE ACTUALIZACIÓN - MODAL 2 PASOS
# ============================================

@bp.route('/expediente/<int:id>/actualizacion/paso1', methods=['POST'])
@requiere_login
@no_cache
def actualizacion_paso1(id):
    """Paso 1: Guardar fecha y descripción, luego redirigir a selección de estado"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para modificar expedientes', 'error')
        return redirect(url_for('main.index'))

    form = ActualizacionModalForm()

    if form.validate_on_submit():
        # Guardar en sesión temporal los datos del paso 1
        session['actualizacion_temp'] = {
            'expediente_id': id,
            'fecha_actuacion': form.fecha_actuacion.data.strftime('%Y-%m-%d'),
            'descripcion': form.descripcion.data
        }
        return redirect(url_for('main.actualizacion_paso2', id=id))
    else:
        flash('Error en los datos. Verifique fecha y descripción.', 'error')
        return redirect(url_for('main.ver_expediente', id=id))


@bp.route('/expediente/<int:id>/actualizacion/paso2', methods=['GET', 'POST'])
@requiere_login
@no_cache
def actualizacion_paso2(id):
    """Paso 2: Seleccionar estado que corresponde a la actuación"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos', 'error')
        return redirect(url_for('main.index'))

    temp_data = session.get('actualizacion_temp')
    if not temp_data or temp_data.get('expediente_id') != id:
        flash('Sesión de actualización expirada. Intente nuevamente.', 'warning')
        return redirect(url_for('main.ver_expediente', id=id))

    form = EstadoSelectorForm()

    if form.validate_on_submit():
        try:
            # Crear fecha completa con hora de Perú
            fecha_str = temp_data['fecha_actuacion']
            fecha_base = datetime.strptime(fecha_str, '%Y-%m-%d')
            # Combinar con hora actual de Perú
            ahora = ahora_peru()
            fecha_completa = fecha_base.replace(hour=ahora.hour, minute=ahora.minute, second=ahora.second)

            nuevo_estado = EstadoHistorial(
                expediente_id=id,
                estado=form.estado.data,
                descripcion=temp_data['descripcion'],
                usuario=session.get('nombre', 'Sistema'),
                fecha=fecha_completa
            )
            db.session.add(nuevo_estado)

            expediente = Expediente.query.get_or_404(id)
            expediente.estado_actual = form.estado.data
            expediente.fecha_actualizacion = ahora_peru()

            db.session.commit()

            # Limpiar sesión temporal
            session.pop('actualizacion_temp', None)

            flash('✅ Avance registrado correctamente', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar avance: {str(e)}', 'error')
        return redirect(url_for('main.ver_expediente', id=id))

    return render_template('seleccionar_estado.html',
                         title='Seleccionar Estado',
                         form=form,
                         descripcion=temp_data['descripcion'],
                         fecha=temp_data['fecha_actuacion'],
                         expediente=Expediente.query.get_or_404(id),
                         rol=session.get('rol', 'USUARIO'))


@bp.route('/expediente/<int:id>/estado', methods=['POST'])
@requiere_login
@no_cache
def agregar_estado(id):
    """RUTA LEGACY: Mantener por compatibilidad con otras partes del sistema"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos', 'error')
        return redirect(url_for('main.index'))

    form = EstadoForm()

    if form.validate_on_submit():
        try:
            nuevo_estado = EstadoHistorial(
                expediente_id=id,
                estado=form.estado.data,
                descripcion=form.descripcion.data,
                usuario=session.get('nombre', 'Sistema'),
                fecha=ahora_peru()
            )
            db.session.add(nuevo_estado)

            expediente = Expediente.query.get_or_404(id)
            expediente.estado_actual = form.estado.data
            expediente.fecha_actualizacion = ahora_peru()

            db.session.commit()
            flash('Estado agregado correctamente', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
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
    - Puede eliminar/desactivar usuarios (no admins ni dev)
    """
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para acceder a esta sección', 'error')
        return redirect(url_for('main.index'))

    if session.get('rol') == 'DESARROLLADOR':
        return redirect(url_for('main.gestion_usuarios_dev'))

    usuarios_db = {}
    for u in Usuario.query.all():  # Todos, incluyendo inactivos
        usuarios_db[u.username] = {
            'nombre': u.nombre,
            'rol': u.rol,
            'modulos': u.get_modulos_list(),
            'email': u.email,
            'fecha_registro': u.fecha_registro,
            'activo': u.activo
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
    - Vista completa de todos los usuarios (activos e inactivos)
    - Puede crear administradores y usuarios
    - Puede activar/desactivar cualquier usuario
    """
    if session.get('rol') != 'DESARROLLADOR':
        flash('No tiene permisos para acceder a esta sección', 'error')
        return redirect(url_for('main.index'))

    usuarios_db = {}
    for u in Usuario.query.all():  # Todos, incluyendo inactivos
        usuarios_db[u.username] = {
            'nombre': u.nombre,
            'rol': u.rol,
            'modulos': u.get_modulos_list(),
            'email': u.email,
            'fecha_registro': u.fecha_registro,
            'activo': u.activo
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

@bp.route('/api/usuario/desactivar/<username>', methods=['POST'])
@requiere_login
@no_cache
def api_desactivar_usuario(username):
    """Desactiva un usuario (soft delete) - mantiene historial"""
    username = unquote(username)
    rol_actual = session.get('rol')

    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    if username == session.get('usuario'):
        return jsonify({'success': False, 'error': 'No puede desactivarse a sí mismo'}), 400

    # Buscar usuario SIN filtrar por activo (puede estar activo o inactivo)
    usuario = Usuario.query.filter_by(username=username).first()
    if not usuario:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404

    # Restricciones según rol
    if rol_actual == 'ADMINISTRADOR':
        if usuario.rol == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede desactivar al desarrollador'}), 403
        if usuario.rol == 'ADMINISTRADOR':
            return jsonify({'success': False, 'error': 'No puede desactivar a otros administradores'}), 403
        if usuario.rol != 'USUARIO':
            return jsonify({'success': False, 'error': 'Solo puede desactivar usuarios'}), 403

    # Verificar si ya está desactivado
    if not usuario.activo:
        return jsonify({'success': False, 'error': 'El usuario ya está desactivado'}), 400

    try:
        usuario.activo = False
        db.session.commit()
        return jsonify({'success': True, 'message': f'Usuario {username} desactivado correctamente'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/usuario/activar/<username>', methods=['POST'])
@requiere_login
@no_cache
def api_activar_usuario(username):
    """Reactiva un usuario previamente desactivado"""
    username = unquote(username)
    rol_actual = session.get('rol')

    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    # Buscar usuario SIN filtrar por activo
    usuario = Usuario.query.filter_by(username=username).first()
    if not usuario:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404

    # Restricciones según rol
    if rol_actual == 'ADMINISTRADOR':
        if usuario.rol == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede activar al desarrollador'}), 403
        if usuario.rol == 'ADMINISTRADOR' and username != session.get('usuario'):
            return jsonify({'success': False, 'error': 'No puede activar a otros administradores'}), 403
        if usuario.rol != 'USUARIO':
            return jsonify({'success': False, 'error': 'Solo puede activar usuarios'}), 403

    # Verificar si ya está activo
    if usuario.activo:
        return jsonify({'success': False, 'error': 'El usuario ya está activo'}), 400

    try:
        usuario.activo = True
        db.session.commit()
        return jsonify({'success': True, 'message': f'Usuario {username} activado correctamente'})
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
@no_cache
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
    """
    Exportar expedientes a PDF profesional (solo Admin/Dev)

    Mejoras v2.0:
    - Logo real del estudio en encabezado de cada página
    - Tabla con anchos optimizados y estados con colores
    - Encabezado/pie de página con número de página
    - Diseño profesional con paleta de colores del estudio
    """
    if not puede_exportar():
        flash('No tiene permisos para exportar datos', 'error')
        return redirect(url_for('main.index'))

    tipos_permitidos = ['todos', 'civil', 'penal', 'administrativo', 'conciliacion', 'archivo']
    if tipo not in tipos_permitidos:
        flash('Tipo de exportación no válido', 'error')
        return redirect(url_for('main.index'))

    if tipo == 'todos':
        expedientes = Expediente.query.order_by(Expediente.fecha_registro.desc()).all()
        titulo_reporte = 'Todos los Expedientes'
        subtitulo = 'Listado completo del estudio jurídico'
    else:
        expedientes = Expediente.query.filter_by(tipo=tipo).order_by(Expediente.fecha_registro.desc()).all()
        titulos = {
            'civil': 'Expedientes de Derecho Civil',
            'penal': 'Expedientes de Derecho Penal',
            'administrativo': 'Expedientes Administrativos',
            'conciliacion': 'Expedientes de Conciliación',
            'archivo': 'Expedientes en Archivo'
        }
        titulo_reporte = titulos.get(tipo, 'Expedientes')
        subtitulo = f'Módulo de {titulo_reporte}'

    # ============================================
    # CONFIGURACIÓN DEL DOCUMENTO
    # ============================================
    output = io.BytesIO()

    # Márgenes ajustados para encabezado/pie
    doc = SimpleDocTemplate(
        output, 
        pagesize=letter,
        topMargin=1.4*inch,      # Espacio para header
        bottomMargin=0.8*inch,   # Espacio para footer
        leftMargin=0.6*inch,
        rightMargin=0.6*inch
    )

    elements = []
    styles = getSampleStyleSheet()

    # ============================================
    # ESTILOS PERSONALIZADOS
    # ============================================

    # Título principal del estudio
    estudio_style = ParagraphStyle(
        'EstudioTitle',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=colors.HexColor('#1e3a8a'),  # Azul corporativo
        alignment=1,  # Centro
        spaceAfter=4,
        fontName='Helvetica-Bold',
        leading=26
    )

    # Subtítulo del sistema
    sistema_style = ParagraphStyle(
        'SistemaSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#64748b'),
        alignment=1,
        spaceAfter=16,
        fontName='Helvetica'
    )

    # Título del reporte
    reporte_style = ParagraphStyle(
        'ReporteTitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#334155'),
        alignment=1,
        spaceAfter=6,
        fontName='Helvetica-Bold',
        leading=18
    )

    # Subtítulo descriptivo
    descripcion_style = ParagraphStyle(
        'DescripcionStyle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#94a3b8'),
        alignment=1,
        spaceAfter=12,
        fontName='Helvetica-Oblique'
    )

    # Info de generación
    info_style = ParagraphStyle(
        'InfoStyle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#64748b'),
        alignment=1,
        spaceAfter=20,
        fontName='Helvetica'
    )

    # Estilo para celdas de tabla
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=8,
        leading=11,
        wordWrap='CJK',
        fontName='Helvetica'
    )

    cell_bold_style = ParagraphStyle(
        'CellBoldStyle',
        parent=styles['Normal'],
        fontSize=8,
        leading=11,
        wordWrap='CJK',
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#1e293b')
    )

    # ============================================
    # CONTENIDO DEL ENCABEZADO (primera página)
    # ============================================

    # Línea decorativa superior
    elements.append(Table([['']], colWidths=[7*inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#1e3a8a')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
    ])))

    elements.append(Paragraph("QUIADIL EIRL", estudio_style))
    elements.append(Paragraph("RUC: 20604913480", ParagraphStyle(
        'RUCStyle',
        parent=sistema_style,
        fontSize=11,
        textColor=colors.HexColor('#1e3a8a'),
        fontName='Helvetica-Bold',
        spaceAfter=4
    )))
    elements.append(Paragraph("Sistema de Gestión de Expedientes Legales", sistema_style))

    # Línea separadora
    elements.append(Table([['']], colWidths=[7*inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ])))

    elements.append(Paragraph(titulo_reporte.upper(), reporte_style))
    elements.append(Paragraph(subtitulo, descripcion_style))
    elements.append(Paragraph(
        f"Generado el {ahora_peru().strftime('%d de %B de %Y a las %H:%M')} | "
        f"Usuario: {session.get('nombre', 'Sistema')} | "
        f"Total: {len(expedientes)} expedientes",
        info_style
    ))

    elements.append(Spacer(1, 16))

    # ============================================
    # TABLA DE EXPEDIENTES
    # ============================================

    # Encabezados de tabla
    headers = ['N°', 'Tipo', 'Identificación', 'Cliente', 'Materia', 'Estado', 'Registro']

    # Datos de la tabla
    table_data = [headers]

    # Colores de estado
    colores_estado = {
        'ingresado': ('#10b981', '#ecfdf5', 'Ingresado'),
        'en_proceso': ('#3b82f6', '#eff6ff', 'En Proceso'),
        'audiencia_programada': ('#f59e0b', '#fffbeb', 'Audiencia Programada'),
        'seguimiento': ('#8b5cf6', '#f5f3ff', 'Seguimiento'),
        'derivado_juzgado': ('#6366f1', '#eef2ff', 'Derivado a Juzgado'),
        'proceso_completado': ('#059669', '#d1fae5', 'Proceso Completado'),
        'resuelto_favorable': ('#10b981', '#ecfdf5', 'Resuelto Favorable'),
        'resuelto_desfavorable': ('#ef4444', '#fef2f2', 'Resuelto Desfavorable'),
        'archivado': ('#6b7280', '#f3f4f6', 'Archivado'),
        'enviado_a_archivo': ('#9ca3af', '#f9fafb', 'Enviado a Archivo'),
    }

    for idx, exp in enumerate(expedientes, 1):
        # Identificación según tipo
        if exp.tipo == 'administrativo':
            identificacion = f"DNI: {exp.dni or 'N/A'}"
        else:
            identificacion = exp.numero_expediente or 'N/A'

        # Cliente truncado si es muy largo
        cliente = exp.cliente[:28] + '...' if len(exp.cliente) > 28 else exp.cliente

        # Materia truncada
        materia = exp.materia[:25] + '...' if len(exp.materia) > 25 else exp.materia

        # Estado con color
        estado_key = exp.estado_actual or 'ingresado'
        color_info = colores_estado.get(estado_key, ('#6b7280', '#f3f4f6', estado_key.replace('_', ' ').title()))

        # Fecha formateada
        fecha_reg = exp.fecha_registro.strftime('%d/%m/%Y') if exp.fecha_registro else 'N/A'

        table_data.append([
            str(idx),
            Paragraph(exp.get_tipo_label(), cell_style),
            Paragraph(identificacion, cell_bold_style),
            Paragraph(cliente, cell_style),
            Paragraph(materia, cell_style),
            Paragraph(color_info[2], ParagraphStyle(
                'EstadoStyle',
                parent=cell_style,
                textColor=colors.HexColor(color_info[0]),
                fontName='Helvetica-Bold',
                alignment=1
            )),
            Paragraph(fecha_reg, ParagraphStyle(
                'FechaStyle',
                parent=cell_style,
                alignment=1
            ))
        ])

    # ============================================
    # ESTILO DE TABLA PROFESIONAL
    # ============================================

    # Anchos de columna optimizados (total = 7.8 pulgadas aprox)
    col_widths = [0.4*inch, 1.0*inch, 1.3*inch, 1.6*inch, 1.5*inch, 1.2*inch, 0.8*inch]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    # Estilo base
    table_style = TableStyle([
        # Encabezado
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),

        # Cuerpo
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),      # N° centrado
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),      # Tipo centrado
        ('ALIGN', (2, 1), (2, -1), 'LEFT'),        # Identificación izquierda
        ('ALIGN', (3, 1), (3, -1), 'LEFT'),        # Cliente izquierda
        ('ALIGN', (4, 1), (4, -1), 'LEFT'),        # Materia izquierda
        ('ALIGN', (5, 1), (5, -1), 'CENTER'),      # Estado centrado
        ('ALIGN', (6, 1), (6, -1), 'CENTER'),      # Fecha centrado
        ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),

        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),

        # Filas alternadas
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#ffffff'), colors.HexColor('#f8fafc')]),
    ])

    # Aplicar colores de estado a las celdas de estado
    for row_idx, exp in enumerate(expedientes, 1):
        estado_key = exp.estado_actual or 'ingresado'
        color_info = colores_estado.get(estado_key, ('#6b7280', '#f3f4f6'))
        table_style.add('BACKGROUND', (5, row_idx), (5, row_idx), colors.HexColor(color_info[1]))

    table.setStyle(table_style)
    elements.append(table)

    elements.append(Spacer(1, 20))

    # ============================================
    # RESUMEN INFERIOR
    # ============================================

    # Línea separadora
    elements.append(Table([['']], colWidths=[7*inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ])))

    # Contadores por estado
    resumen_data = [['RESUMEN POR ESTADO', '']]

    from collections import Counter
    estados_count = Counter([exp.estado_actual or 'ingresado' for exp in expedientes])

    for estado_key, count in sorted(estados_count.items()):
        color_info = colores_estado.get(estado_key, ('#6b7280', '#f3f4f6'))
        label = color_info[2]
        resumen_data.append([
            Paragraph(f"<font color='{color_info[0]}'>●</font> {label}", cell_style),
            Paragraph(str(count), ParagraphStyle('CountStyle', parent=cell_bold_style, alignment=1))
        ])

    resumen_data.append([
        Paragraph('<b>TOTAL DE EXPEDIENTES</b>', ParagraphStyle('TotalStyle', parent=cell_bold_style, textColor=colors.HexColor('#1e3a8a'))),
        Paragraph(str(len(expedientes)), ParagraphStyle('TotalCount', parent=cell_bold_style, alignment=1, textColor=colors.HexColor('#1e3a8a'), fontSize=10))
    ])

    resumen_table = Table(resumen_data, colWidths=[3*inch, 2*inch])
    resumen_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('SPAN', (0, 0), (-1, 0)),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 9),
        ('ALIGN', (0, 1), (0, -2), 'LEFT'),
        ('ALIGN', (1, 1), (1, -2), 'CENTER'),
        ('BOTTOMPADDING', (0, 1), (-1, -2), 4),
        ('TOPPADDING', (0, 1), (-1, -2), 4),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f1f5f9')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
        ('TOPPADDING', (0, -1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))

    elements.append(resumen_table)

    elements.append(Spacer(1, 30))

    # Nota confidencial
    elements.append(Paragraph(
        "<i>Este documento es confidencial y de uso exclusivo del estudio jurídico Quijandria Abogados EIRL. "
        "Su reproducción o distribución sin autorización está prohibida.</i>",
        ParagraphStyle(
            'Confidencial',
            parent=styles['Normal'],
            fontSize=7,
            textColor=colors.HexColor('#94a3b8'),
            alignment=1,
            fontName='Helvetica-Oblique'
        )
    ))

    # ============================================
    # FUNCIONES DE ENCABEZADO Y PIE DE PÁGINA
    # ============================================

    def draw_header_footer(canvas, doc):
        """Dibuja logo, línea decorativa y pie de página en cada hoja"""
        canvas.saveState()

        # --- LOGO EN ESQUINA SUPERIOR IZQUIERDA ---
        try:
            logo = get_logo_image()
            if logo:
                logo_width = 0.9 * inch
                logo_height = 0.7 * inch
                x = 0.6 * inch  # Margen izquierdo
                y = letter[1] - 0.9 * inch  # Arriba
                canvas.drawImage(
                    logo, x, y, 
                    width=logo_width, height=logo_height, 
                    preserveAspectRatio=True, mask='auto'
                )
        except Exception as e:
            print(f"Error dibujando logo en header: {e}")

        # --- TEXTO DEL ESTUDIO (arriba derecha) ---
        canvas.setFont('Helvetica-Bold', 9)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawRightString(
            letter[0] - 0.6*inch, 
            letter[1] - 0.6*inch, 
            "QUIADIL EIRL"
        )

        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawRightString(
            letter[0] - 0.6*inch, 
            letter[1] - 0.75*inch, 
            "Sistema de Gestión de Expedientes Legales"
        )

        # --- LÍNEA DECORATIVA SUPERIOR ---
        canvas.setStrokeColor(colors.HexColor('#1e3a8a'))
        canvas.setLineWidth(1.5)
        canvas.line(
            0.6*inch, 
            letter[1] - 1.0*inch, 
            letter[0] - 0.6*inch, 
            letter[1] - 1.0*inch
        )

        # --- PIE DE PÁGINA ---
        # Línea decorativa inferior
        canvas.setStrokeColor(colors.HexColor('#cbd5e1'))
        canvas.setLineWidth(0.5)
        canvas.line(
            0.6*inch, 
            0.5*inch, 
            letter[0] - 0.6*inch, 
            0.5*inch
        )

        # Texto izquierdo del pie
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.HexColor('#94a3b8'))
        canvas.drawString(
            0.6*inch, 
            0.35*inch, 
            f"Generado: {ahora_peru().strftime('%d/%m/%Y %H:%M')} | Usuario: {session.get('nombre', 'Sistema')}"
        )

        # Texto centro del pie
        canvas.setFont('Helvetica-Oblique', 7)
        canvas.setFillColor(colors.HexColor('#94a3b8'))
        canvas.drawCentredString(
            letter[0] / 2, 
            0.35*inch, 
            "Documento Confidencial - Uso Exclusivo del Estudio"
        )

        # Número de página (derecha)
        canvas.setFont('Helvetica-Bold', 8)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawRightString(
            letter[0] - 0.6*inch, 
            0.35*inch, 
            f"Página {doc.page}"
        )

        canvas.restoreState()

    # ============================================
    # CONSTRUIR PDF
    # ============================================
    doc.build(elements, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)
    output.seek(0)

    # Nombre del archivo
    nombre_archivo = titulo_reporte.replace(' ', '_')

    return send_file(
        output,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{nombre_archivo}_{ahora_peru().strftime("%Y%m%d_%H%M")}.pdf'
    )

# ============================================
# RUTA PARA IMPRIMIR EXPEDIENTE - PDF CLIENTE AVANCE
# ============================================

@bp.route('/expediente/<int:id>/imprimir')
@requiere_login
@no_cache
def imprimir_expediente_pdf(id):
    """
    PDF CLIENTE - AVANCE
    - Diseno limpio y profesional para clientes de todas las edades
    - Letra grande, espacios amplios, colores suaves
    - Solo fecha de inicio (sin hora), info general resumida
    - Avances como bitacora tipo FECHA | DESCRIPCION (limpio)
    - Audiencias solo si existen
    - Pie de pagina completo con datos del estudio
    """

    if not puede_exportar():
        flash('No tiene permisos para imprimir expedientes', 'error')
        return redirect(url_for('main.ver_expediente', id=id))

    expediente = Expediente.query.get_or_404(id)

    # HISTORIAL COMPLETO para avances (solo actuaciones reales, excluir automaticos)
    historial_completo = EstadoHistorial.query.filter_by(
        expediente_id=id
    ).order_by(EstadoHistorial.fecha.asc()).all()  # Antiguo arriba, nuevo abajo

    # Filtrar solo avances reales (excluir registros automaticos del sistema)
    estados_excluir = [
        'Expediente editado',
        'Expediente registrado en el sistema',
        'ingresado'
    ]
    avances = []
    for h in historial_completo:
        desc = (h.descripcion or '').strip()
        if desc and h.estado not in estados_excluir \
           and not desc.startswith('Expediente editado por') \
           and not desc.startswith('Expediente registrado'):
            avances.append(h)

    # Primer ingreso para fecha de inicio
    primer_ingreso = EstadoHistorial.query.filter_by(
        expediente_id=id, estado='ingresado'
    ).order_by(EstadoHistorial.fecha.asc()).first()

    # Audiencias solo si existen
    audiencias = Audiencia.query.filter_by(
        expediente_id=id
    ).order_by(Audiencia.fecha.asc()).all()

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=letter,
        topMargin=1.4 * inch,
        bottomMargin=0.9 * inch,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch
    )

    elements = []
    styles = getSampleStyleSheet()

    # ============================================
    # ESTILOS PERSONALIZADOS - LECTURA FACIL
    # ============================================

    # Encabezado estudio
    estudio_nombre_style = ParagraphStyle(
        'EstudioNombre',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=1,
        spaceAfter=2,
        fontName='Helvetica-Bold',
        leading=24
    )

    estudio_ruc_style = ParagraphStyle(
        'EstudioRUC',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=1,
        spaceAfter=2,
        fontName='Helvetica-Bold'
    )

    estudio_sistema_style = ParagraphStyle(
        'EstudioSistema',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#64748b'),
        alignment=1,
        spaceAfter=12,
        fontName='Helvetica'
    )

    # Titulo del documento
    doc_titulo_style = ParagraphStyle(
        'DocTitulo',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.white,
        alignment=1,
        spaceAfter=0,
        fontName='Helvetica-Bold',
        leading=20
    )

    # Subtitulo
    doc_subtitulo_style = ParagraphStyle(
        'DocSubtitulo',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#475569'),
        alignment=1,
        spaceAfter=16,
        fontName='Helvetica'
    )

    # Secciones
    seccion_style = ParagraphStyle(
        'SeccionCliente',
        parent=styles['Heading3'],
        fontSize=13,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=0,
        spaceAfter=10,
        spaceBefore=16,
        fontName='Helvetica-Bold',
        leftIndent=0
    )

    # Etiquetas (campos)
    etiqueta_style = ParagraphStyle(
        'EtiquetaCliente',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#64748b'),
        alignment=0,
        spaceAfter=2,
        fontName='Helvetica-Bold'
    )

    # Valores
    valor_style = ParagraphStyle(
        'ValorCliente',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#1e293b'),
        alignment=0,
        spaceAfter=6,
        fontName='Helvetica',
        leading=15,
        wordWrap='CJK'
    )

    valor_destacado_style = ParagraphStyle(
        'ValorDestacadoCliente',
        parent=valor_style,
        fontSize=12,
        textColor=colors.HexColor('#1e3a8a'),
        fontName='Helvetica-Bold'
    )

    # Estilo para avances (bitacora)
    avance_fecha_style = ParagraphStyle(
        'AvanceFecha',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#1e40af'),
        fontName='Helvetica-Bold',
        leading=16
    )

    avance_desc_style = ParagraphStyle(
        'AvanceDesc',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#334155'),
        fontName='Helvetica',
        leading=16,
        wordWrap='CJK',
        leftIndent=4
    )

    # Notas informativas
    nota_style = ParagraphStyle(
        'NotaCliente',
        parent=styles['Italic'],
        fontSize=9,
        textColor=colors.HexColor('#94a3b8'),
        alignment=1,
        spaceBefore=20,
        fontName='Helvetica-Oblique'
    )

    # ============================================
    # ENCABEZADO CON LOGO
    # ============================================

    # Linea superior azul
    elements.append(Table([['']], colWidths=[6.5 * inch], style=TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
    ])))

    elements.append(Spacer(1, 10))

    # Logo centrado
    try:
        logo = get_logo_image()
        if logo:
            logo_rl = RLImage(logo, width=2.0*inch, height=1.5*inch)
            logo_table = Table([[logo_rl]], colWidths=[6.5*inch])
            logo_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(logo_table)
            elements.append(Spacer(1, 6))
    except Exception as e:
        print(f"Error logo PDF Cliente: {e}")

    elements.append(Paragraph("QUIADIL EIRL", estudio_nombre_style))
    elements.append(Paragraph("RUC: 20604913480", estudio_ruc_style))
    elements.append(Paragraph("Sistema de Gestion de Expedientes Legales", estudio_sistema_style))

    # Linea separadora
    elements.append(Table([['']], colWidths=[6.5 * inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#1e3a8a')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
    ])))

    # ============================================
    # BANNER - REPORTE PARA CLIENTE
    # ============================================

    banner_data = [[Paragraph("AVANCE DE EXPEDIENTE", doc_titulo_style)]]
    banner_table = Table(banner_data, colWidths=[6.5 * inch])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('LEFTPADDING', (0, 0), (-1, 0), 12),
        ('RIGHTPADDING', (0, 0), (-1, 0), 12),
    ]))
    elements.append(banner_table)

    # Subtitulo con identificacion
    tipo_label = expediente.get_tipo_label()
    id_cliente = expediente.numero_expediente if expediente.numero_expediente and expediente.numero_expediente != '-' else f"DNI: {expediente.dni or 'N/A'}"
    elements.append(Paragraph(
        f"{tipo_label} | {id_cliente} | Cliente: {expediente.cliente}",
        doc_subtitulo_style
    ))
    elements.append(Spacer(1, 8))

    # ============================================
    # SECCION: INFORMACION GENERAL (resumida)
    # ============================================

    elements.append(Paragraph("▎ INFORMACION GENERAL", seccion_style))

    # Fecha de inicio (solo fecha, sin hora)
    fecha_inicio = 'No registrada'
    if primer_ingreso and primer_ingreso.fecha:
        fecha_inicio = primer_ingreso.fecha.strftime('%d/%m/%Y')

    info_data = [
        [Paragraph("Cliente:", etiqueta_style),
         Paragraph(expediente.cliente or 'No registrado', valor_destacado_style)],
        [Paragraph("Fecha de Inicio:", etiqueta_style),
         Paragraph(fecha_inicio, valor_destacado_style)],
        [Paragraph("Materia:", etiqueta_style),
         Paragraph(expediente.materia or 'No especificada', valor_style)],
        [Paragraph("Estado Actual:", etiqueta_style),
         Paragraph(expediente.get_estado_label() or 'Sin estado', valor_style)],
    ]

    # Campos especificos segun tipo (solo los esenciales)
    if expediente.tipo == 'civil':
        info_data.append([Paragraph("Juez:", etiqueta_style),
                          Paragraph(expediente.juez or 'Por asignar', valor_style)])
    elif expediente.tipo == 'penal':
        info_data.append([Paragraph("Fiscal:", etiqueta_style),
                          Paragraph(expediente.fiscal or 'Por asignar', valor_style)])
        info_data.append([Paragraph("Juzgado:", etiqueta_style),
                          Paragraph(expediente.juzgado or 'Por asignar', valor_style)])
    elif expediente.tipo == 'administrativo':
        info_data.append([Paragraph("Entidad:", etiqueta_style),
                          Paragraph(expediente.entidad_receptora or 'Por definir', valor_style)])
        info_data.append([Paragraph("Tramite:", etiqueta_style),
                          Paragraph(expediente.tramite or 'Por definir', valor_style)])
    elif expediente.tipo == 'conciliacion':
        info_data.append([Paragraph("Conciliador:", etiqueta_style),
                          Paragraph(expediente.conciliador or 'Por asignar', valor_style)])

    info_table = Table(info_data, colWidths=[2.0 * inch, 4.5 * inch])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 12))

    # ============================================
    # SECCION: AVANCE DEL EXPEDIENTE (bitacora limpia)
    # ============================================

    elements.append(Paragraph("▎ AVANCE DE SU EXPEDIENTE", seccion_style))

    if avances:
        # Encabezado de la bitacora
        header_data = [[
            Paragraph("FECHA", ParagraphStyle('HeaderFecha', parent=avance_fecha_style, fontSize=9, textColor=colors.HexColor('#1e3a8a'))),
            Paragraph("DESCRIPCION DE LA ACTUACION", ParagraphStyle('HeaderDesc', parent=avance_fecha_style, fontSize=9, textColor=colors.HexColor('#1e3a8a')))
        ]]

        header_table = Table(header_data, colWidths=[1.3 * inch, 5.2 * inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dbeafe')),
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
            ('ALIGN', (1, 0), (1, 0), 'LEFT'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('LEFTPADDING', (0, 0), (-1, 0), 10),
            ('RIGHTPADDING', (0, 0), (-1, 0), 10),
            ('BOX', (0, 0), (-1, 0), 1, colors.HexColor('#1e3a8a')),
        ]))
        elements.append(header_table)

        # Filas de avances
        for idx, h in enumerate(avances):
            fecha_avance = h.fecha.strftime('%d/%m/%Y') if h.fecha else 'Sin fecha'
            desc_avance = (h.descripcion or 'Sin descripcion').strip()
            desc_formateada = '<br/>'.join(desc_avance.split('\n')) if desc_avance else 'Sin descripcion'

            # Color alternado para filas
            bg_color = colors.HexColor('#ffffff') if idx % 2 == 0 else colors.HexColor('#f8fafc')

            avance_data = [[
                Paragraph(fecha_avance, avance_fecha_style),
                Paragraph(desc_formateada, avance_desc_style)
            ]]

            avance_table = Table(avance_data, colWidths=[1.3 * inch, 5.2 * inch])
            avance_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), bg_color),
                ('ALIGN', (0, 0), (0, 0), 'CENTER'),
                ('VALIGN', (0, 0), (0, 0), 'MIDDLE'),
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),
                ('VALIGN', (1, 0), (1, 0), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('LEFTPADDING', (0, 0), (0, 0), 8),
                ('LEFTPADDING', (1, 0), (1, 0), 12),
                ('RIGHTPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, 0), 0.5, colors.HexColor('#e2e8f0')),
                ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#e2e8f0')),
            ]))
            elements.append(avance_table)

    else:
        # Sin avances
        sin_avance_data = [[Paragraph(
            "Aun no hay avances registrados en su expediente. "
            "El estudio le mantendra informado de cualquier novedad.",
            ParagraphStyle('SinAvance', parent=valor_style, textColor=colors.HexColor('#94a3b8'), alignment=1)
        )]]

        sin_avance_table = Table(sin_avance_data, colWidths=[6.5 * inch])
        sin_avance_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
            ('LEFTPADDING', (0, 0), (-1, 0), 16),
            ('RIGHTPADDING', (0, 0), (-1, 0), 16),
            ('TOPPADDING', (0, 0), (-1, 0), 16),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 16),
            ('BOX', (0, 0), (-1, 0), 1, colors.HexColor('#cbd5e1')),
        ]))
        elements.append(sin_avance_table)

    elements.append(Spacer(1, 16))

    # ============================================
    # SECCION: AUDIENCIAS (solo si existen)
    # ============================================

    if audiencias:
        elements.append(Paragraph("▎ AUDIENCIAS PROGRAMADAS", seccion_style))

        aud_header = [[
            Paragraph("FECHA", ParagraphStyle('AudHeader', parent=avance_fecha_style, fontSize=9, textColor=colors.HexColor('#1e3a8a'))),
            Paragraph("HORA", ParagraphStyle('AudHeader', parent=avance_fecha_style, fontSize=9, textColor=colors.HexColor('#1e3a8a'))),
            Paragraph("LUGAR / DETALLE", ParagraphStyle('AudHeader', parent=avance_fecha_style, fontSize=9, textColor=colors.HexColor('#1e3a8a')))
        ]]

        aud_header_table = Table(aud_header, colWidths=[1.2 * inch, 1.0 * inch, 4.3 * inch])
        aud_header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fef3c7')),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('LEFTPADDING', (0, 0), (-1, 0), 10),
            ('RIGHTPADDING', (0, 0), (-1, 0), 10),
            ('BOX', (0, 0), (-1, 0), 1, colors.HexColor('#f59e0b')),
        ]))
        elements.append(aud_header_table)

        for idx, a in enumerate(audiencias):
            fecha_aud = a.fecha.strftime('%d/%m/%Y') if a.fecha else 'N/A'
            hora_aud = a.hora.strftime('%H:%M') if a.hora else 'N/A'
            lugar_aud = a.lugar or 'Por definir'
            tipo_aud = a.get_tipo_label() if hasattr(a, 'get_tipo_label') else a.tipo_audiencia

            detalle_aud = f"{tipo_aud}"
            if lugar_aud and lugar_aud != 'Por definir':
                detalle_aud += f" | {lugar_aud}"
            if a.sala:
                detalle_aud += f" | Sala: {a.sala}"

            bg_color = colors.HexColor('#ffffff') if idx % 2 == 0 else colors.HexColor('#fffbeb')

            aud_data = [[
                Paragraph(fecha_aud, ParagraphStyle('AudFecha', parent=valor_style, fontSize=10, alignment=1)),
                Paragraph(hora_aud, ParagraphStyle('AudHora', parent=valor_style, fontSize=10, alignment=1)),
                Paragraph(detalle_aud, ParagraphStyle('AudDetalle', parent=valor_style, fontSize=10))
            ]]

            aud_table = Table(aud_data, colWidths=[1.2 * inch, 1.0 * inch, 4.3 * inch])
            aud_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), bg_color),
                ('ALIGN', (0, 0), (1, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('LEFTPADDING', (0, 0), (-1, 0), 8),
                ('RIGHTPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, 0), 0.5, colors.HexColor('#e2e8f0')),
                ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#e2e8f0')),
            ]))
            elements.append(aud_table)

        elements.append(Spacer(1, 16))

    # ============================================
    # NOTA FINAL
    # ============================================

    elements.append(Spacer(1, 10))
    elements.append(Table([['']], colWidths=[6.5 * inch], style=TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, 0), 16),
    ])))

    elements.append(Paragraph(
        "Este reporte es generado automaticamente por el sistema del estudio juridico. "
        "Para cualquier consulta, comuniquese con su abogado a cargo.",
        ParagraphStyle('NotaFinal', parent=nota_style, fontSize=9, textColor=colors.HexColor('#64748b'))
    ))

    # ============================================
    # HEADER/FOOTER EN CADA PAGINA
    # ============================================

    def draw_header_footer_cliente(canvas, doc):
        canvas.saveState()

        # Linea superior azul
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.rect(0, letter[1] - 0.22 * inch, letter[0], 0.22 * inch, fill=1, stroke=0)

        # Logo izquierda
        try:
            logo = get_logo_image()
            if logo:
                canvas.drawImage(logo, 0.6 * inch, letter[1] - 0.95 * inch,
                                 width=0.7 * inch, height=0.55 * inch,
                                 preserveAspectRatio=True, mask='auto')
        except Exception as e:
            print(f"Error logo header cliente: {e}")

        # Texto izquierdo
        canvas.setFont('Helvetica-Bold', 8)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawString(1.4 * inch, letter[1] - 0.52 * inch, "QUIADIL EIRL")

        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(1.4 * inch, letter[1] - 0.64 * inch, "Reporte para Cliente")

        # Texto centro
        canvas.setFont('Helvetica-Bold', 9)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawCentredString(letter[0] / 2, letter[1] - 0.58 * inch,
                                  "QUIJANDRIA ABOGADOS")

        # Texto derecho
        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawRightString(letter[0] - 0.7 * inch, letter[1] - 0.52 * inch,
                               ahora_peru().strftime('%d/%m/%Y'))
        canvas.drawRightString(letter[0] - 0.7 * inch, letter[1] - 0.64 * inch,
                               f"Exp: {expediente.numero_expediente or 'N/A'}")

        # Linea separadora
        canvas.setStrokeColor(colors.HexColor('#cbd5e1'))
        canvas.setLineWidth(0.5)
        canvas.line(0.6 * inch, letter[1] - 1.05 * inch, letter[0] - 0.6 * inch, letter[1] - 1.05 * inch)

        # ============================================
        # PIE DE PAGINA COMPLETO
        # ============================================

        # Linea inferior
        canvas.setStrokeColor(colors.HexColor('#1e3a8a'))
        canvas.setLineWidth(2)
        canvas.line(0.6 * inch, 0.55 * inch, letter[0] - 0.6 * inch, 0.55 * inch)

        # Fondo gris claro para pie
        canvas.setFillColor(colors.HexColor('#f8fafc'))
        canvas.rect(0.6 * inch, 0.12 * inch, letter[0] - 1.2 * inch, 0.4 * inch, fill=1, stroke=0)

        # Columna 1: Datos del estudio
        canvas.setFont('Helvetica-Bold', 7)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawString(0.75 * inch, 0.42 * inch, "QUIADIL EIRL")

        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#475569'))
        canvas.drawString(0.75 * inch, 0.32 * inch, "RUC: 20604913480")

        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(0.75 * inch, 0.22 * inch, "Cel: 984 377 509")

        # Columna 2: Centro - Sistema
        canvas.setFont('Helvetica-Bold', 7)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawCentredString(letter[0] / 2, 0.42 * inch,
                                  "SISTEMA DE GESTION DE EXPEDIENTES")

        canvas.setFont('Helvetica-Oblique', 6)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawCentredString(letter[0] / 2, 0.32 * inch,
                                  "Documento Confidencial - Uso Exclusivo del Estudio Juridico")

        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#94a3b8'))
        canvas.drawCentredString(letter[0] / 2, 0.22 * inch,
                                  "Generado automaticamente - No requiere firma")

        # Columna 3: Derecha - Fecha y pagina
        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#475569'))
        canvas.drawRightString(letter[0] - 0.75 * inch, 0.42 * inch,
                               f"Generado: {ahora_peru().strftime('%d/%m/%Y %H:%M')}")

        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawRightString(letter[0] - 0.75 * inch, 0.32 * inch,
                               f"Usuario: {session.get('nombre', 'Sistema')}")

        canvas.setFont('Helvetica-Bold', 8)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawRightString(letter[0] - 0.75 * inch, 0.22 * inch, f"Pag. {doc.page}")

        canvas.restoreState()

    # ============================================
    # CONSTRUIR PDF
    # ============================================
    doc.build(elements, onFirstPage=draw_header_footer_cliente, onLaterPages=draw_header_footer_cliente)
    output.seek(0)

    identificador = expediente.numero_expediente.replace("/", "_") if expediente.numero_expediente and expediente.numero_expediente != '-' else f"DNI_{expediente.dni or 'SIN_ID'}"

    return send_file(
        output,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Avance_Cliente_{identificador}_{ahora_peru().strftime("%Y%m%d")}.pdf'
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
                expediente.dni or 'No registrado',
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
# RUTA PARA EXPORTAR RESUMEN PDF - FICHA DE ARCHIVO PROFESIONAL
# ============================================

@bp.route('/expediente/<int:id>/exportar-pdf')
@requiere_login
@no_cache
def exportar_resumen_pdf(id):
    """
    Generar PDF FICHA DE ARCHIVO profesional del expediente.
    - Diseño tipo ficha judicial para archivo fisico
    - SOLO muestra el PRIMER registro 'ingresado': fecha + descripcion
    - Logo del estudio restaurado
    - SIN seccion 'Registro y Seguimiento' (evita repeticion)
    - 'Inicio de Expediente' con fecha y descripcion del caso
    """

    if not puede_exportar():
        flash('No tiene permisos para exportar expedientes', 'error')
        return redirect(url_for('main.ver_expediente', id=id))

    expediente = Expediente.query.get_or_404(id)

    # OBTENER SOLO EL PRIMER REGISTRO "INGRESADO"
    primer_ingreso = EstadoHistorial.query.filter_by(
        expediente_id=id,
        estado='ingresado'
    ).order_by(EstadoHistorial.fecha.asc()).first()

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=letter,
        topMargin=1.6 * inch,
        bottomMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch
    )

    elements = []
    styles = getSampleStyleSheet()

    # ============================================
    # ESTILOS
    # ============================================

    estudio_titulo_style = ParagraphStyle(
        'EstudioTitulo',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=1,
        spaceAfter=2,
        fontName='Helvetica-Bold',
        leading=20
    )

    estudio_subtitulo_style = ParagraphStyle(
        'EstudioSubtitulo',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#64748b'),
        alignment=1,
        spaceAfter=2,
        fontName='Helvetica'
    )

    estudio_ruc_style = ParagraphStyle(
        'EstudioRUC',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=1,
        spaceAfter=12,
        fontName='Helvetica-Bold'
    )

    ficha_titulo_style = ParagraphStyle(
        'FichaTitulo',
        parent=styles['Heading2'],
        fontSize=13,
        textColor=colors.white,
        alignment=1,
        spaceAfter=0,
        fontName='Helvetica-Bold',
        leading=16
    )

    seccion_titulo_style = ParagraphStyle(
        'SeccionTitulo',
        parent=styles['Heading3'],
        fontSize=10,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=0,
        spaceAfter=6,
        spaceBefore=10,
        fontName='Helvetica-Bold'
    )

    etiqueta_style = ParagraphStyle(
        'Etiqueta',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#64748b'),
        alignment=0,
        spaceAfter=1,
        fontName='Helvetica-Bold'
    )

    valor_style = ParagraphStyle(
        'Valor',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#1e293b'),
        alignment=0,
        spaceAfter=4,
        fontName='Helvetica',
        leading=13,
        wordWrap='CJK'
    )

    valor_destacado_style = ParagraphStyle(
        'ValorDestacado',
        parent=valor_style,
        fontSize=11,
        textColor=colors.HexColor('#1e3a8a'),
        fontName='Helvetica-Bold'
    )

    actuacion_style = ParagraphStyle(
        'Actuacion',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#334155'),
        alignment=0,
        leading=14,
        wordWrap='CJK',
        leftIndent=8,
        rightIndent=8,
        spaceBefore=4,
        spaceAfter=4
    )

    confidencial_style = ParagraphStyle(
        'Confidencial',
        parent=styles['Italic'],
        fontSize=7,
        textColor=colors.HexColor('#94a3b8'),
        alignment=1,
        spaceBefore=20,
        fontName='Helvetica-Oblique'
    )

    # ============================================
    # ENCABEZADO CON LOGO
    # ============================================

    # Línea decorativa superior azul
    elements.append(Table([['']], colWidths=[6.5 * inch], style=TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
    ])))

    elements.append(Spacer(1, 8))

    # Logo centrado
    try:
        logo = get_logo_image()
        if logo:
            logo_rl = RLImage(logo, width=1.8*inch, height=1.4*inch)
            logo_table = Table([[logo_rl]], colWidths=[6.5*inch])
            logo_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(logo_table)
            elements.append(Spacer(1, 4))
    except Exception as e:
        print(f"Error cargando logo en PDF: {e}")

    # Datos del estudio
    elements.append(Paragraph("QUIADIL EIRL", estudio_titulo_style))
    elements.append(Paragraph("QUIJANDRIA ABOGADOS", estudio_subtitulo_style))
    elements.append(Paragraph("RUC: 20604913480", estudio_ruc_style))

    # Línea separadora
    elements.append(Table([['']], colWidths=[6.5 * inch], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#1e3a8a')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
    ])))

    # ============================================
    # BANNER FICHA DE ARCHIVO
    # ============================================

    tipo_label = expediente.get_tipo_label()
    banner_data = [[Paragraph(f"FICHA DE ARCHIVO - {tipo_label.upper()}", ficha_titulo_style)]]
    banner_table = Table(banner_data, colWidths=[6.5 * inch])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('LEFTPADDING', (0, 0), (-1, 0), 12),
        ('RIGHTPADDING', (0, 0), (-1, 0), 12),
    ]))
    elements.append(banner_table)
    elements.append(Spacer(1, 14))

    # ============================================
    # SECCION 1: IDENTIFICACION
    # ============================================

    elements.append(Paragraph("▎ IDENTIFICACION DEL EXPEDIENTE", seccion_titulo_style))

    if expediente.tipo == 'administrativo':
        id_principal = f"DNI: {expediente.dni or 'No registrado'}"
        id_secundario = f"N° Expediente: {expediente.numero_expediente or 'Sin asignar'}"
    else:
        id_principal = f"N° Expediente: {expediente.numero_expediente or 'Sin asignar'}"
        id_secundario = f"DNI: {expediente.dni or 'No registrado'}"

    ident_data = [
        [Paragraph("N° de Expediente / Identificacion:", etiqueta_style),
         Paragraph(id_principal, valor_destacado_style)],
        [Paragraph("Identificacion Secundaria:", etiqueta_style),
         Paragraph(id_secundario, valor_style)],
        [Paragraph("Tipo de Proceso:", etiqueta_style),
         Paragraph(tipo_label, valor_style)],
        [Paragraph("Materia:", etiqueta_style),
         Paragraph(expediente.materia or 'No especificada', valor_style)],
        [Paragraph("Estado Actual:", etiqueta_style),
         Paragraph(expediente.get_estado_label() or 'Sin estado', valor_style)],
    ]

    ident_table = Table(ident_data, colWidths=[2.2 * inch, 4.3 * inch])
    ident_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
    ]))
    elements.append(ident_table)
    elements.append(Spacer(1, 10))

    # ============================================
    # SECCION 2: PARTES DEL PROCESO
    # ============================================

    elements.append(Paragraph("▎ PARTES DEL PROCESO", seccion_titulo_style))

    partes_data = [
        [Paragraph("Cliente / Demandante:", etiqueta_style),
         Paragraph(expediente.cliente or 'No registrado', valor_style)],
        [Paragraph("Telefono:", etiqueta_style),
         Paragraph(expediente.telefono or 'No registrado', valor_style)],
    ]

    if expediente.tipo == 'civil':
        partes_data.extend([
            [Paragraph("Juez:", etiqueta_style),
             Paragraph(expediente.juez or 'No asignado', valor_style)],
            [Paragraph("Secretario:", etiqueta_style),
             Paragraph(expediente.secretario or 'No asignado', valor_style)],
        ])
    elif expediente.tipo == 'penal':
        partes_data.extend([
            [Paragraph("N° Caso Fiscal:", etiqueta_style),
             Paragraph(expediente.numero_cf or 'No asignado', valor_style)],
            [Paragraph("Fiscal:", etiqueta_style),
             Paragraph(expediente.fiscal or 'No asignado', valor_style)],
            [Paragraph("Juzgado:", etiqueta_style),
             Paragraph(expediente.juzgado or 'No asignado', valor_style)],
        ])
    elif expediente.tipo == 'administrativo':
        partes_data.extend([
            [Paragraph("Entidad Receptora:", etiqueta_style),
             Paragraph(expediente.entidad_receptora or 'No especificada', valor_style)],
            [Paragraph("Tramite:", etiqueta_style),
             Paragraph(expediente.tramite or 'No especificado', valor_style)],
        ])
    elif expediente.tipo == 'conciliacion':
        partes_data.extend([
            [Paragraph("Conciliador:", etiqueta_style),
             Paragraph(expediente.conciliador or 'No asignado', valor_style)],
            [Paragraph("Solicitante:", etiqueta_style),
             Paragraph(expediente.solicitante or expediente.cliente or 'No especificado', valor_style)],
            [Paragraph("Invitados:", etiqueta_style),
             Paragraph(expediente.invitados or 'No especificados', valor_style)],
        ])
    elif expediente.tipo == 'archivo':
        partes_data.extend([
            [Paragraph("Ubicacion Fisica:", etiqueta_style),
             Paragraph(expediente.ubicacion_archivo or 'No especificada', valor_style)],
            [Paragraph("Fecha de Archivado:", etiqueta_style),
             Paragraph(expediente.fecha_archivado.strftime('%d/%m/%Y') if expediente.fecha_archivado else 'No registrada', valor_style)],
        ])

    partes_table = Table(partes_data, colWidths=[2.2 * inch, 4.3 * inch])
    partes_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
    ]))
    elements.append(partes_table)
    elements.append(Spacer(1, 10))

    # ============================================
    # SECCION 3: INICIO DE EXPEDIENTE
    # ============================================

    elements.append(Paragraph("▎ INICIO DE EXPEDIENTE", seccion_titulo_style))

    if primer_ingreso:
        fecha_ingreso = primer_ingreso.fecha.strftime('%d/%m/%Y') if primer_ingreso.fecha else 'Sin fecha'
        descripcion_ingreso = primer_ingreso.descripcion or 'Expediente registrado en el sistema'
        descripcion_formateada = '<br/>'.join(descripcion_ingreso.split('\n')) if descripcion_ingreso else 'Sin descripcion'

        ingreso_data = [
            [Paragraph("Fecha de Inicio:", etiqueta_style),
             Paragraph(fecha_ingreso, valor_destacado_style)],
            [Paragraph("Descripcion del Caso:", etiqueta_style),
             Paragraph(descripcion_formateada, actuacion_style)],
        ]

        ingreso_table = Table(ingreso_data, colWidths=[2.2 * inch, 4.3 * inch])
        ingreso_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#eff6ff')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ]))
        elements.append(ingreso_table)

    else:
        no_ingreso_data = [[Paragraph(
            "No se encontro registro de ingreso inicial.",
            ParagraphStyle('NoIngreso', parent=valor_style, textColor=colors.HexColor('#94a3b8'), alignment=1)
        )]]

        no_ingreso_table = Table(no_ingreso_data, colWidths=[6.5 * inch])
        no_ingreso_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fef3c7')),
            ('LEFTPADDING', (0, 0), (-1, 0), 12),
            ('RIGHTPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BOX', (0, 0), (-1, 0), 1, colors.HexColor('#f59e0b')),
        ]))
        elements.append(no_ingreso_table)

    elements.append(Spacer(1, 20))

    # ============================================
    # PIE DE PAGINA (sin seccion Descripcion del Caso separada)
    # ============================================

    elements.append(Table([['']], colWidths=[6.5 * inch], style=TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, 0), 16),
    ])))

    elements.append(Paragraph(
        "<b>DOCUMENTO CONFIDENCIAL</b> — Uso exclusivo del Estudio Juridico Quijandria Abogados EIRL",
        ParagraphStyle('ConfidencialTitulo', parent=confidencial_style, fontName='Helvetica-Bold', textColor=colors.HexColor('#64748b'))
    ))

    elements.append(Paragraph(
        f"Generado el {ahora_peru().strftime('%d/%m/%Y a las %H:%M')} por {session.get('nombre', 'Sistema')} | "
        f"QUIADIL EIRL — RUC: 20604913480",
        confidencial_style
    ))

    elements.append(Paragraph(
        "Su reproduccion, distribucion o divulgacion sin autorizacion escrita esta prohibida.",
        confidencial_style
    ))

    # ============================================
    # HEADER/FOOTER EN CADA PAGINA
    # ============================================

    def draw_header_footer_archivo(canvas, doc):
        canvas.saveState()

        # Linea superior azul
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.rect(0, letter[1] - 0.22 * inch, letter[0], 0.22 * inch, fill=1, stroke=0)

        # Logo en esquina superior izquierda
        try:
            logo = get_logo_image()
            if logo:
                canvas.drawImage(logo, 0.6 * inch, letter[1] - 0.95 * inch,
                                 width=0.8 * inch, height=0.6 * inch,
                                 preserveAspectRatio=True, mask='auto')
        except Exception as e:
            print(f"Error logo header: {e}")

        # Texto izquierdo
        canvas.setFont('Helvetica-Bold', 7)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawString(1.5 * inch, letter[1] - 0.5 * inch, "QUIADIL EIRL")

        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(1.5 * inch, letter[1] - 0.62 * inch, "Ficha de Archivo")

        # Texto centro
        canvas.setFont('Helvetica-Bold', 8)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawCentredString(letter[0] / 2, letter[1] - 0.56 * inch, "SISTEMA DE GESTION DE EXPEDIENTES")

        # Texto derecho
        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawRightString(letter[0] - 0.7 * inch, letter[1] - 0.5 * inch,
                               ahora_peru().strftime('%d/%m/%Y'))
        canvas.drawRightString(letter[0] - 0.7 * inch, letter[1] - 0.62 * inch,
                               f"Exp: {expediente.numero_expediente or 'N/A'}")

        # Linea separadora
        canvas.setStrokeColor(colors.HexColor('#cbd5e1'))
        canvas.setLineWidth(0.5)
        canvas.line(0.6 * inch, letter[1] - 1.05 * inch, letter[0] - 0.6 * inch, letter[1] - 1.05 * inch)

        # Pie de pagina
        canvas.setStrokeColor(colors.HexColor('#cbd5e1'))
        canvas.setLineWidth(0.5)
        canvas.line(0.7 * inch, 0.45 * inch, letter[0] - 0.7 * inch, 0.45 * inch)

        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#94a3b8'))
        canvas.drawString(0.7 * inch, 0.32 * inch,
                          f"Generado: {ahora_peru().strftime('%d/%m/%Y %H:%M')} | Usuario: {session.get('nombre', 'Sistema')}")

        canvas.setFont('Helvetica-Oblique', 6)
        canvas.drawCentredString(letter[0] / 2, 0.32 * inch,
                                 "Documento Confidencial - Uso Exclusivo del Estudio Juridico")

        canvas.setFont('Helvetica-Bold', 7)
        canvas.setFillColor(colors.HexColor('#1e3a8a'))
        canvas.drawRightString(letter[0] - 0.7 * inch, 0.32 * inch, f"Pag. {doc.page}")

        canvas.restoreState()

    # ============================================
    # CONSTRUIR PDF
    # ============================================
    doc.build(elements, onFirstPage=draw_header_footer_archivo, onLaterPages=draw_header_footer_archivo)
    output.seek(0)

    identificador = expediente.numero_expediente.replace("/", "_") if expediente.numero_expediente and expediente.numero_expediente != '-' else f"DNI_{expediente.dni or 'SIN_ID'}"

    return send_file(
        output,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Ficha_Archivo_{identificador}_{ahora_peru().strftime("%Y%m%d")}.pdf'
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
# EDITAR / ELIMINAR HISTORIAL DE ESTADOS
# ============================================

@bp.route('/historial/<int:id>/editar', methods=['GET', 'POST'])
@requiere_login
@no_cache
def editar_historial(id):
    """Editar una entrada del historial de estados"""
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para editar el historial', 'error')
        return redirect(url_for('main.index'))

    historial = EstadoHistorial.query.get_or_404(id)
    expediente_id = historial.expediente_id

    if request.method == 'POST':
        try:
            # Actualizar fecha, estado y descripción
            fecha_str = request.form.get('fecha', '').strip()
            if fecha_str:
                try:
                    fecha_base = datetime.strptime(fecha_str, '%Y-%m-%d')
                    # Mantener hora original o usar hora actual de Perú
                    hora_original = historial.fecha.hour if historial.fecha else 0
                    minuto_original = historial.fecha.minute if historial.fecha else 0
                    historial.fecha = fecha_base.replace(hour=hora_original, minute=minuto_original)
                except ValueError:
                    pass  # Mantener fecha original si hay error

            nuevo_estado = request.form.get('estado', '').strip()
            if nuevo_estado:
                historial.estado = nuevo_estado
                # Si es la última entrada, actualizar también el estado del expediente
                ultima_entrada = EstadoHistorial.query.filter_by(
                    expediente_id=expediente_id
                ).order_by(EstadoHistorial.fecha.desc()).first()
                if ultima_entrada and ultima_entrada.id == id:
                    expediente = Expediente.query.get(expediente_id)
                    if expediente:
                        expediente.estado_actual = nuevo_estado

            nueva_descripcion = request.form.get('descripcion', '').strip()
            if nueva_descripcion:
                historial.descripcion = nueva_descripcion

            db.session.commit()
            flash('✅ Entrada del historial actualizada correctamente', 'success')
            return redirect(url_for('main.ver_expediente', id=expediente_id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'error')
            return redirect(url_for('main.ver_expediente', id=expediente_id))

    return redirect(url_for('main.ver_expediente', id=expediente_id))


@bp.route('/historial/<int:id>/eliminar', methods=['POST'])
@requiere_login
@no_cache
def eliminar_historial(id):
    """Eliminar una entrada del historial de estados"""
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para eliminar del historial', 'error')
        return redirect(url_for('main.index'))

    historial = EstadoHistorial.query.get_or_404(id)
    expediente_id = historial.expediente_id

    try:
        db.session.delete(historial)
        db.session.commit()

        # Actualizar estado del expediente a la última entrada restante
        ultima_entrada = EstadoHistorial.query.filter_by(
            expediente_id=expediente_id
        ).order_by(EstadoHistorial.fecha.desc()).first()

        expediente = Expediente.query.get(expediente_id)
        if expediente:
            if ultima_entrada:
                expediente.estado_actual = ultima_entrada.estado
            else:
                expediente.estado_actual = 'ingresado'
            expediente.fecha_actualizacion = ahora_peru()

        db.session.commit()
        flash('🗑️ Entrada eliminada del historial', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar: {str(e)}', 'error')

    return redirect(url_for('main.ver_expediente', id=expediente_id))


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

