# app/routes.py - Rutas de la aplicación

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, after_this_request, send_file
from werkzeug.security import check_password_hash
from functools import wraps
from datetime import datetime, timedelta, date
from app import db
from app.models import Expediente, EstadoHistorial, Audiencia, Documento, Notificacion, AuditLog, BackupLog
from app.forms import ExpedienteForm, EstadoForm, BusquedaForm, AudienciaForm, BusquedaAudienciaForm, DocumentoForm, BusquedaDocumentoForm
import json
import os
import shutil      # ← AGREGAR: Para copiar archivos en backups
import zipfile     # ← AGREGAR: Para crear archivos ZIP de backup

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
# CONFIGURACIÓN DE USUARIOS Y PERSISTENCIA
# ============================================

# Ruta del archivo de usuarios
USUARIOS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance', 'usuarios.json')

# Usuarios por defecto (se usan si no existe el archivo)
USUARIOS_DEFAULT = {
    'dev': {
        'password': 'dev123',
        'nombre': 'Desarrollador Principal',
        'rol': 'DESARROLLADOR',
        'modulos': ['todo']
    },
    'admin': {
        'password': 'admin123',
        'nombre': 'Administrador del Sistema',
        'rol': 'ADMINISTRADOR',
        'modulos': ['todo']
    },
    'usuario1': {
        'password': 'user123',
        'nombre': 'Abogado Junior',
        'rol': 'USUARIO',
        'modulos': ['civil', 'penal']
    }
}

def _cargar_usuarios():
    """Carga usuarios: JSON tiene prioridad sobre usuarios.py"""
    # Primero intentar JSON (usuarios creados dinámicamente)
    if os.path.exists(USUARIOS_FILE):
        try:
            with open(USUARIOS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    
    # Si no hay JSON, usar usuarios.py (predeterminados)
    try:
        from app.usuarios import USUARIOS
        resultado = {}
        for username, datos in USUARIOS.items():
            resultado[username] = {
                'password': datos['password'],
                'nombre': datos['nombre'],
                'rol': datos['rol'],
                'modulos': datos['modulos']
            }
        return resultado
    except ImportError:
        return USUARIOS_DEFAULT.copy()

def _guardar_usuarios():
    """Guarda usuarios en archivo JSON (solo usuarios dinámicos)"""
    os.makedirs(os.path.dirname(USUARIOS_FILE), exist_ok=True)
    with open(USUARIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(USUARIOS, f, indent=2, ensure_ascii=False)

# Cargar usuarios al inicio
USUARIOS = _cargar_usuarios()

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
# FUNCIONES DE AUDITORÍA (v1.1)
# ============================================

def registrar_auditoria(tabla, registro_id, accion, campo=None, 
                        valor_anterior=None, valor_nuevo=None):
    """
    Registra una acción en la tabla de auditoría.
    Uso: registrar_auditoria('expediente', 5, 'editar', 'cliente', 'Juan', 'Pedro')
    """
    try:
        from app.models import AuditLog
        log = AuditLog(
            tabla=tabla,
            registro_id=registro_id,
            accion=accion,
            campo=campo,
            valor_anterior=str(valor_anterior)[:500] if valor_anterior else None,
            valor_nuevo=str(valor_nuevo)[:500] if valor_nuevo else None,
            usuario=session.get('nombre', 'Sistema'),
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string[:200] if request.user_agent else None
        )
        db.session.add(log)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en auditoría: {e}")
        return False

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
    """Procesa el login de usuarios"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Cargar usuarios (desde JSON o usuarios.py)
        usuarios = _cargar_usuarios()
        user = usuarios.get(username)
        
        if user:
            # Verificar contraseña - primero texto plano, luego hash
            password_valida = False
            
            # Intentar texto plano primero (para usuarios de usuarios.py)
            if user['password'] == password:
                password_valida = True
            else:
                # Intentar como hash (para usuarios nuevos creados desde el sistema)
                try:
                    password_valida = check_password_hash(user['password'], password)
                except:
                    password_valida = False
            
            if password_valida:
                # Login exitoso - CORREGIDO: Guardar 'usuario' en vez de 'username'
                session['usuario'] = username           # ← CAMBIADO de 'username' a 'usuario'
                session['nombre'] = user['nombre']
                session['rol'] = user['rol']
                session['modulos'] = user['modulos']
                
                # AUDITORÍA: Registrar login
                registrar_auditoria('usuario', 0, 'login', 
                                   valor_nuevo=f"Usuario {username} inició sesión desde {request.remote_addr}")
                
                return redirect(url_for('main.index'))
        
        # Si llegamos aquí, login falló
        flash('Usuario o contraseña incorrectos', 'error')
        return render_template('login.html', error=True)
    
    return render_template('login.html')

@bp.route('/logout')
def logout():
    """Cierra la sesión del usuario"""
    # AUDITORÍA: Registrar logout antes de limpiar sesión
    registrar_auditoria('usuario', 0, 'logout',
                       valor_nuevo=f"Usuario {session.get('nombre', 'Desconocido')} cerró sesión")
    
    session.clear()
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
    """Crea un nuevo expediente"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para crear expedientes', 'error')
        return redirect(url_for('main.index'))
    
    from app.forms import ExpedienteForm
    form = ExpedienteForm()
    
    if form.validate_on_submit():
        try:
            # Crear expediente según el tipo
            tipo = form.tipo.data
            
            # Validar campos según tipo
            if tipo == 'administrativo' and not form.dni.data:
                flash('El DNI es obligatorio para expedientes administrativos', 'error')
                return render_template('nuevo_expediente.html', form=form, rol=session.get('rol'))
            
            # Crear el expediente
            expediente = Expediente(
                tipo=tipo,
                numero_expediente=form.numero_expediente.data if tipo != 'administrativo' else '-',
                dni=form.dni.data if tipo in ['administrativo', 'penal', 'conciliacion', 'archivo'] else None,
                cliente=form.cliente.data,
                materia=form.materia.data,
                telefono=form.telefono.data,
                descripcion=form.descripcion.data,
                estado_actual='activo',
                fecha_registro=datetime.now(),
                
                # Campos específicos
                entidad_receptora=form.entidad_receptora.data if tipo == 'administrativo' else None,
                tramite=form.tramite.data if tipo == 'administrativo' else None,
                secretario=form.secretario.data if tipo == 'civil' else None,
                juez=form.juez.data if tipo == 'civil' else None,
                numero_cf=form.numero_cf.data if tipo == 'penal' else None,
                fiscal=form.fiscal.data if tipo == 'penal' else None,
                juzgado=form.juzgado.data if tipo == 'penal' else None,
                conciliador=form.conciliador.data if tipo == 'conciliacion' else None,
                solicitante=form.solicitante.data if tipo == 'conciliacion' else None,
                invitados=form.invitados.data if tipo == 'conciliacion' else None,
                ubicacion_archivo=form.ubicacion_archivo.data if tipo == 'archivo' else None
            )
            
            db.session.add(expediente)
            db.session.flush()  # Obtener el ID sin commit final
            
            # Crear estado inicial en historial
            estado_inicial = EstadoHistorial(
                expediente_id=expediente.id,
                estado='activo',
                fecha_cambio=datetime.now(),
                observacion='Expediente creado',
                usuario=session.get('nombre', 'Sistema')
            )
            db.session.add(estado_inicial)
            
            db.session.commit()
            
            # AUDITORÍA: Registrar creación de expediente
            registrar_auditoria(
                tabla='expediente',
                registro_id=expediente.id,
                accion='crear',
                valor_nuevo=f"{expediente.get_identificador_principal()} - {expediente.cliente}"
            )
            
            flash('Expediente creado exitosamente', 'success')
            return redirect(url_for('main.ver_expediente', id=expediente.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear expediente: {str(e)}', 'error')
            return render_template('nuevo_expediente.html', form=form, rol=session.get('rol'))
    
    return render_template('nuevo_expediente.html', form=form, rol=session.get('rol'))

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
    """Edita un expediente existente"""
    if not puede_ver_modulo('expedientes'):
        flash('No tiene permisos para editar expedientes', 'error')
        return redirect(url_for('main.index'))
    
    expediente = Expediente.query.get_or_404(id)
    
    from app.forms import ExpedienteEditForm
    form = ExpedienteEditForm(obj=expediente)
    
    if request.method == 'POST':
        try:
            # CAPTURAR VALORES ANTES DE MODIFICAR (para auditoría)
            valores_anteriores = {
                'cliente': expediente.cliente,
                'materia': expediente.materia,
                'telefono': expediente.telefono,
                'estado_actual': expediente.estado_actual,
                'descripcion': expediente.descripcion,
                'dni': expediente.dni,
                'numero_expediente': expediente.numero_expediente
            }
            
            # Actualizar campos comunes
            expediente.cliente = form.cliente.data
            expediente.materia = form.materia.data
            expediente.telefono = form.telefono.data
            expediente.descripcion = form.descripcion.data
            
            # Actualizar campos específicos según tipo
            if expediente.tipo == 'administrativo':
                expediente.dni = form.dni.data
                expediente.entidad_receptora = form.entidad_receptora.data
                expediente.tramite = form.tramite.data
            
            elif expediente.tipo == 'civil':
                expediente.numero_expediente = form.numero_expediente.data
                expediente.secretario = form.secretario.data
                expediente.juez = form.juez.data
            
            elif expediente.tipo == 'penal':
                expediente.numero_expediente = form.numero_expediente.data
                expediente.dni = form.dni.data
                expediente.numero_cf = form.numero_cf.data
                expediente.fiscal = form.fiscal.data
                expediente.juzgado = form.juzgado.data
            
            elif expediente.tipo == 'conciliacion':
                expediente.numero_expediente = form.numero_expediente.data
                expediente.dni = form.dni.data
                expediente.conciliador = form.conciliador.data
                expediente.solicitante = form.solicitante.data
                expediente.invitados = form.invitados.data
            
            elif expediente.tipo == 'archivo':
                expediente.numero_expediente = form.numero_expediente.data
                expediente.dni = form.dni.data
                expediente.ubicacion_archivo = form.ubicacion_archivo.data
            
            # Si cambió el estado, registrar en historial
            if form.estado_actual.data != expediente.estado_actual:
                estado_anterior = expediente.estado_actual
                expediente.estado_actual = form.estado_actual.data
                
                nuevo_estado = EstadoHistorial(
                    expediente_id=expediente.id,
                    estado=form.estado_actual.data,
                    fecha_cambio=datetime.now(),
                    observacion=f'Cambio de estado: {estado_anterior} → {form.estado_actual.data}',
                    usuario=session.get('nombre', 'Sistema')
                )
                db.session.add(nuevo_estado)
                
                # AUDITORÍA: Registrar cambio de estado
                registrar_auditoria('expediente', id, 'editar', 'estado',
                                  estado_anterior, form.estado_actual.data)
            
            # AUDITORÍA: Registrar cambios en otros campos
            if expediente.cliente != valores_anteriores['cliente']:
                registrar_auditoria('expediente', id, 'editar', 'cliente',
                                  valores_anteriores['cliente'], expediente.cliente)
            
            if expediente.materia != valores_anteriores['materia']:
                registrar_auditoria('expediente', id, 'editar', 'materia',
                                  valores_anteriores['materia'], expediente.materia)
            
            if expediente.telefono != valores_anteriores['telefono']:
                registrar_auditoria('expediente', id, 'editar', 'telefono',
                                  valores_anteriores['telefono'], expediente.telefono)
            
            if expediente.descripcion != valores_anteriores['descripcion']:
                registrar_auditoria('expediente', id, 'editar', 'descripcion',
                                  valores_anteriores['descripcion'], expediente.descripcion)
            
            if expediente.dni != valores_anteriores['dni']:
                registrar_auditoria('expediente', id, 'editar', 'dni',
                                  valores_anteriores['dni'], expediente.dni)
            
            if expediente.numero_expediente != valores_anteriores['numero_expediente']:
                registrar_auditoria('expediente', id, 'editar', 'numero_expediente',
                                  valores_anteriores['numero_expediente'], expediente.numero_expediente)
            
            db.session.commit()
            
            flash('Expediente actualizado exitosamente', 'success')
            return redirect(url_for('main.ver_expediente', id=expediente.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar expediente: {str(e)}', 'error')
    
    return render_template('editar_expediente.html', 
                         form=form, 
                         expediente=expediente,
                         rol=session.get('rol'))

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
    - Puede asignar módulos a usuarios
    """
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para acceder a esta sección', 'error')
        return redirect(url_for('main.index'))

    # Si es desarrollador, redirigir a su vista especial
    if session.get('rol') == 'DESARROLLADOR':
        return redirect(url_for('main.gestion_usuarios_dev'))

    # Recargar usuarios por si se modificaron
    global USUARIOS
    USUARIOS = _cargar_usuarios()

    return render_template('admin_usuarios.html',
                         title='Gestión de Usuarios',
                         usuarios=USUARIOS,
                         rol=session.get('rol', 'USUARIO'))

@bp.route('/dev/usuarios')
@requiere_login
@no_cache
def gestion_usuarios_dev():
    """
    DESARROLLADOR:
    - Vista completa de todos los usuarios
    - Puede crear administradores y usuarios
    - Puede eliminar cualquier usuario (incluido administradores)
    - Acceso total sin restricciones
    """
    if session.get('rol') != 'DESARROLLADOR':
        flash('No tiene permisos para acceder a esta sección', 'error')
        return redirect(url_for('main.index'))

    # Recargar usuarios
    global USUARIOS
    USUARIOS = _cargar_usuarios()

    return render_template('admin_usuarios_dev.html',
                         title='Gestión de Usuarios - Desarrollador',
                         usuarios=USUARIOS,
                         rol=session.get('rol', 'USUARIO'))

@bp.route('/api/usuario/<username>')
@requiere_login
@no_cache
def api_obtener_usuario(username):
    """API para obtener datos de un usuario específico"""
    rol_actual = session.get('rol')

    # Solo ADMINISTRADOR o DESARROLLADOR pueden ver detalles
    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    if username not in USUARIOS:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404

    usuario = USUARIOS[username]

    # RESTRICCIONES DE ADMINISTRADOR
    if rol_actual == 'ADMINISTRADOR':
        # No puede ver detalles del desarrollador
        if usuario['rol'] == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede ver detalles del desarrollador'}), 403
        # No puede ver detalles de otros administradores
        if usuario['rol'] == 'ADMINISTRADOR' and username != session.get('usuario'):
            return jsonify({'success': False, 'error': 'No puede ver detalles de otros administradores'}), 403

    return jsonify({
        'success': True,
        'username': username,
        'nombre': usuario['nombre'],
        'rol': usuario['rol'],
        'modulos': usuario['modulos']
    })

@bp.route('/api/usuario/crear', methods=['POST'])
@requiere_login
@no_cache
def api_crear_usuario():
    """API para crear usuarios según permisos del rol"""
    from werkzeug.security import generate_password_hash
    
    global USUARIOS
    
    rol_actual = session.get('rol')

    # Solo ADMINISTRADOR o DESARROLLADOR pueden crear usuarios
    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    data = request.get_json()
    username = data.get('username', '').strip()
    nombre = data.get('nombre', '').strip()
    password = data.get('password', '').strip()
    rol_nuevo = data.get('rol', 'USUARIO')
    modulos = data.get('modulos', ['civil'])

    # Validaciones
    if not username or not nombre or not password:
        return jsonify({'success': False, 'error': 'Datos incompletos'}), 400

    # Verificar si existe en JSON o en usuarios.py
    usuarios_actuales = _cargar_usuarios()
    if username in usuarios_actuales:
        return jsonify({'success': False, 'error': 'El usuario ya existe'}), 400

    # RESTRICCIONES DE ADMINISTRADOR
    if rol_actual == 'ADMINISTRADOR':
        if rol_nuevo == 'ADMINISTRADOR':
            return jsonify({'success': False, 'error': 'No puede crear administradores'}), 403
        if rol_nuevo == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede crear desarrolladores'}), 403

    # Crear usuario con contraseña HASHEADA (más seguro)
    try:
        USUARIOS[username] = {
            'password': generate_password_hash(password),
            'nombre': nombre,
            'rol': rol_nuevo,
            'modulos': modulos if isinstance(modulos, list) else [modulos]
        }

        _guardar_usuarios()
        
        # Recargar para sincronizar
        USUARIOS = _cargar_usuarios()

        return jsonify({'success': True, 'message': 'Usuario creado correctamente'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/api/usuario/eliminar/<username>', methods=['DELETE'])
@requiere_login
@no_cache
def api_eliminar_usuario(username):
    """API para eliminar usuarios según permisos del rol"""
    global USUARIOS
    
    rol_actual = session.get('rol')

    # Solo ADMINISTRADOR o DESARROLLADOR pueden eliminar
    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    # No puede eliminarse a sí mismo
    if username == session.get('usuario'):
        return jsonify({'success': False, 'error': 'No puede eliminarse a sí mismo'}), 400

    # Verificar que el usuario existe
    if username not in USUARIOS:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404

    usuario_objetivo = USUARIOS[username]

    # RESTRICCIONES DE ADMINISTRADOR
    if rol_actual == 'ADMINISTRADOR':
        # No puede eliminar desarrolladores
        if usuario_objetivo['rol'] == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede eliminar al desarrollador'}), 403

        # No puede eliminar otros administradores
        if usuario_objetivo['rol'] == 'ADMINISTRADOR':
            return jsonify({'success': False, 'error': 'No puede eliminar a otros administradores'}), 403

    # Eliminar usuario
    try:
        del USUARIOS[username]
        _guardar_usuarios()
        return jsonify({'success': True, 'message': 'Usuario eliminado correctamente'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/api/usuario/editar/<username>', methods=['PUT'])
@requiere_login
@no_cache
def api_editar_usuario(username):
    """API para editar usuarios según permisos del rol"""
    from werkzeug.security import generate_password_hash
    
    global USUARIOS
    
    rol_actual = session.get('rol')

    if rol_actual not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    # Cargar usuarios actuales
    usuarios_actuales = _cargar_usuarios()
    
    if username not in usuarios_actuales:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404

    usuario_objetivo = usuarios_actuales[username]
    data = request.get_json()

    # RESTRICCIONES DE ADMINISTRADOR
    if rol_actual == 'ADMINISTRADOR':
        if usuario_objetivo['rol'] == 'DESARROLLADOR':
            return jsonify({'success': False, 'error': 'No puede editar al desarrollador'}), 403
        if usuario_objetivo['rol'] == 'ADMINISTRADOR' and username != session.get('usuario'):
            return jsonify({'success': False, 'error': 'No puede editar a otros administradores'}), 403
        nuevo_rol = data.get('rol')
        if nuevo_rol in ['ADMINISTRADOR', 'DESARROLLADOR']:
            return jsonify({'success': False, 'error': 'No puede asignar ese rol'}), 403

    # Actualizar datos
    try:
        if 'nombre' in data:
            USUARIOS[username]['nombre'] = data['nombre']
        
        if 'password' in data and data['password']:
            # HASHEAR la nueva contraseña
            USUARIOS[username]['password'] = generate_password_hash(data['password'])
        
        if 'modulos' in data:
            USUARIOS[username]['modulos'] = data['modulos'] if isinstance(data['modulos'], list) else [data['modulos']]
        
        if 'rol' in data and rol_actual == 'DESARROLLADOR':
            USUARIOS[username]['rol'] = data['rol']

        _guardar_usuarios()
        
        # Recargar para sincronizar
        USUARIOS = _cargar_usuarios()
        
        return jsonify({'success': True, 'message': 'Usuario actualizado correctamente'})
    except Exception as e:
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

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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
                    usuario_subida=session.get('nombre', 'Sistema')
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
# RUTA DE AUDITORÍA (v1.1) - Solo Admin/Dev
# ============================================

@bp.route('/auditoria')
@requiere_login
@no_cache
def ver_auditoria():
    """Ver historial de auditoría del sistema"""
    if session.get('rol') not in ['ADMINISTRADOR', 'DESARROLLADOR']:
        flash('No tiene permisos para ver auditoría', 'error')
        return redirect(url_for('main.index'))
    
    # Filtros
    filtro_tabla = request.args.get('tabla', '')
    filtro_accion = request.args.get('accion', '')
    filtro_usuario = request.args.get('usuario', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    
    query = AuditLog.query
    
    if filtro_tabla:
        query = query.filter(AuditLog.tabla == filtro_tabla)
    if filtro_accion:
        query = query.filter(AuditLog.accion == filtro_accion)
    if filtro_usuario:
        query = query.filter(AuditLog.usuario.ilike(f'%{filtro_usuario}%'))
    if fecha_desde:
        try:
            desde = datetime.strptime(fecha_desde, '%Y-%m-%d')
            query = query.filter(AuditLog.fecha >= desde)
        except:
            pass
    if fecha_hasta:
        try:
            hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d')
            query = query.filter(AuditLog.fecha <= hasta)
        except:
            pass
    
    # Paginación
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    logs = query.order_by(AuditLog.fecha.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Usuarios únicos para filtro
    usuarios = db.session.query(AuditLog.usuario).distinct().all()
    usuarios = [u[0] for u in usuarios]
    
    return render_template('auditoria.html',
                         title='Auditoría del Sistema',
                         logs=logs,
                         usuarios=usuarios,
                         filtro_tabla=filtro_tabla,
                         filtro_accion=filtro_accion,
                         filtro_usuario=filtro_usuario,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         rol=session.get('rol', 'USUARIO'))

# ============================================
# BACKUP AUTOMÁTICO - V1.1
# ============================================

def _generar_backup(tipo='manual', descripcion='', usuario='sistema'):
    """Genera un backup ZIP con la base de datos, usuarios JSON y documentos"""
    from app.models import BackupLog  # Import local para evitar circular
    
    ruta_archivo = None
    nombre_archivo = None
    tamaño = 0
    
    try:
        # Crear carpeta de backups si no existe
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Nombre del archivo con timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        nombre_archivo = f"backup_{tipo}_{timestamp}.zip"
        ruta_archivo = os.path.join(backup_dir, nombre_archivo)
        
        # Crear ZIP
        with zipfile.ZipFile(ruta_archivo, 'w', zipfile.ZIP_DEFLATED) as zipf:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 1. Base de datos SQLite
            db_path = os.path.join(app_dir, '..', 'instance', 'app.db')
            if os.path.exists(db_path):
                zipf.write(db_path, 'database/app.db')
            
            # 2. Usuarios JSON
            usuarios_path = os.path.join(app_dir, '..', 'instance', 'usuarios.json')
            if os.path.exists(usuarios_path):
                zipf.write(usuarios_path, 'config/usuarios.json')
            
            # 3. Documentos adjuntos
            docs_dir = os.path.join(app_dir, '..', 'uploads', 'documentos')
            if os.path.exists(docs_dir):
                for root, dirs, files in os.walk(docs_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.join('documentos', os.path.relpath(file_path, docs_dir))
                        zipf.write(file_path, arcname)
            
            # 4. Metadatos del backup
            metadata = {
                'fecha_creacion': datetime.now().isoformat(),
                'tipo': tipo,
                'creado_por': usuario,
                'descripcion': descripcion,
                'version_sistema': 'v1.1',
                'archivos_incluidos': ['database/app.db', 'config/usuarios.json', 'documentos/']
            }
            zipf.writestr('metadata.json', json.dumps(metadata, indent=2, ensure_ascii=False))
        
        # Obtener tamaño del archivo
        tamaño = os.path.getsize(ruta_archivo)
        
        # Crear registro en base de datos
        backup = BackupLog(
            nombre_archivo=nombre_archivo,
            ruta_archivo=ruta_archivo,
            tipo=tipo,
            tamaño_bytes=tamaño,
            descripcion=descripcion,
            creado_por=usuario,
            estado='completado'
        )
        db.session.add(backup)
        db.session.commit()
        
        # Formatear tamaño para auditoría
        tamaño_str = f"{tamaño / (1024*1024):.1f} MB" if tamaño >= 1024*1024 else f"{tamaño / 1024:.1f} KB"
        
        # Registrar en auditoría (nueva sesión independiente)
        try:
            registrar_auditoria(
                tabla='backup',
                registro_id=backup.id,
                accion='crear',
                valor_nuevo=f"Backup {tipo} generado: {nombre_archivo} ({tamaño_str})"
            )
        except Exception as e:
            print(f"⚠️ Error registrando auditoría de backup: {e}")
        
        return {'success': True, 'backup': backup, 'mensaje': 'Backup generado correctamente'}
        
    except Exception as e:
        # Limpiar archivo si se creó parcialmente
        if ruta_archivo and os.path.exists(ruta_archivo):
            try:
                os.remove(ruta_archivo)
            except:
                pass
        
        # Registrar error en base de datos
        try:
            db.session.rollback()
            backup_error = BackupLog(
                nombre_archivo=nombre_archivo or f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                ruta_archivo='',
                tipo=tipo,
                descripcion=f"Error: {str(e)}",
                creado_por=usuario,
                estado='error'
            )
            db.session.add(backup_error)
            db.session.commit()
        except Exception as e2:
            print(f"❌ Error grave registrando fallo de backup: {e2}")
        
        return {'success': False, 'error': str(e)}


@bp.route('/backup')
@requiere_login
@no_cache
def gestion_backup():
    """Página de gestión de backups - solo Admin/Dev"""
    if session.get('rol') not in ['DESARROLLADOR', 'ADMINISTRADOR']:
        flash('No tiene permisos para acceder a esta sección', 'error')
        return redirect(url_for('main.index'))
    
    # Listar backups existentes
    backups = BackupLog.query.order_by(BackupLog.fecha_creacion.desc()).all()
    
    # Calcular estadísticas
    total_backups = len(backups)
    backups_manuales = sum(1 for b in backups if b.tipo == 'manual')
    backups_auto = sum(1 for b in backups if b.tipo == 'automatico')
    tamaño_total = sum(b.tamaño_bytes or 0 for b in backups)
    
    # Formatear tamaño total
    tamaño_total_str = "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if tamaño_total < 1024.0:
            tamaño_total_str = f"{tamaño_total:.1f} {unit}"
            break
        tamaño_total /= 1024.0
    else:
        tamaño_total_str = f"{tamaño_total:.1f} TB"
    
    return render_template('backup.html',
                         backups=backups,
                         total_backups=total_backups,
                         backups_manuales=backups_manuales,
                         backups_auto=backups_auto,
                         tamaño_total=tamaño_total_str,
                         rol=session.get('rol'))


@bp.route('/backup/crear', methods=['POST'])
@requiere_login
@no_cache
def crear_backup():
    """Genera un backup manual"""
    if session.get('rol') not in ['DESARROLLADOR', 'ADMINISTRADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403
    
    descripcion = request.form.get('descripcion', 'Backup manual')
    
    resultado = _generar_backup(
        tipo='manual',
        descripcion=descripcion,
        usuario=session.get('usuario', 'sistema')  # ← CORREGIDO: 'usuario' no 'username'
    )
    
    if resultado['success']:
        flash(f'✅ Backup generado: {resultado["backup"].nombre_archivo}', 'success')
    else:
        flash(f'❌ Error al generar backup: {resultado["error"]}', 'error')
    
    return redirect(url_for('main.gestion_backup'))


@bp.route('/backup/descargar/<int:id>')
@requiere_login
@no_cache
def descargar_backup(id):
    """Descarga un backup ZIP"""
    if session.get('rol') not in ['DESARROLLADOR', 'ADMINISTRADOR']:
        flash('Sin permisos', 'error')
        return redirect(url_for('main.index'))
    
    backup = BackupLog.query.get_or_404(id)
    
    if not os.path.exists(backup.ruta_archivo):
        flash('Archivo de backup no encontrado', 'error')
        return redirect(url_for('main.gestion_backup'))
    
    # Registrar descarga en auditoría
    try:
        registrar_auditoria(
            tabla='backup',
            registro_id=id,
            accion='descargar',
            valor_nuevo=f"Backup descargado: {backup.nombre_archivo}"
        )
    except Exception as e:
        print(f"⚠️ Error en auditoría de descarga: {e}")
    
    return send_file(
        backup.ruta_archivo,
        as_attachment=True,
        download_name=backup.nombre_archivo,
        mimetype='application/zip'
    )


@bp.route('/backup/eliminar/<int:id>', methods=['POST'])
@requiere_login
@no_cache
def eliminar_backup(id):
    """Elimina un backup"""
    if session.get('rol') not in ['DESARROLLADOR', 'ADMINISTRADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403
    
    backup = BackupLog.query.get_or_404(id)
    
    try:
        # Eliminar archivo físico
        if os.path.exists(backup.ruta_archivo):
            os.remove(backup.ruta_archivo)
        
        # Registrar en auditoría antes de eliminar
        try:
            registrar_auditoria(
                tabla='backup',
                registro_id=id,
                accion='eliminar',
                valor_anterior=backup.nombre_archivo
            )
        except Exception as e:
            print(f"⚠️ Error en auditoría de eliminación: {e}")
        
        # Eliminar registro
        db.session.delete(backup)
        db.session.commit()
        
        flash('✅ Backup eliminado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al eliminar: {str(e)}', 'error')
    
    return redirect(url_for('main.gestion_backup'))

# ============================================
# RESTAURACIÓN DE BACKUP - V1.1
# ============================================

@bp.route('/backup/restaurar/<int:id>', methods=['POST'])
@requiere_login
@no_cache
def restaurar_backup(id):
    """Restaura un backup ZIP (reemplaza BD, usuarios y documentos)"""
    if session.get('rol') not in ['DESARROLLADOR', 'ADMINISTRADOR']:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403
    
    backup = BackupLog.query.get_or_404(id)
    
    if not os.path.exists(backup.ruta_archivo):
        flash('❌ Archivo de backup no encontrado', 'error')
        return redirect(url_for('main.gestion_backup'))
    
    try:
        # Crear backup de seguridad ANTES de restaurar (por si acaso)
        timestamp_seguro = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_seguro_nombre = f"backup_seguridad_antes_restaurar_{timestamp_seguro}.zip"
        backup_seguro_ruta = os.path.join(os.path.dirname(backup.ruta_archivo), backup_seguro_nombre)
        
        # Copiar backup actual como seguridad
        shutil.copy2(backup.ruta_archivo, backup_seguro_ruta)
        
        # Extraer ZIP
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(backup.ruta_archivo, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            app_dir = os.path.dirname(os.path.abspath(__file__))
            restaurados = []
            errores = []
            
            # 1. Restaurar base de datos
            db_backup_path = os.path.join(temp_dir, 'database', 'app.db')
            db_actual_path = os.path.join(app_dir, '..', 'instance', 'app.db')
            
            if os.path.exists(db_backup_path):
                # Cerrar conexiones a la BD
                db.session.remove()
                db.engine.dispose()
                
                # Respaldar BD actual por si acaso
                if os.path.exists(db_actual_path):
                    db_respaldo = f"{db_actual_path}.bak.{timestamp_seguro}"
                    shutil.copy2(db_actual_path, db_respaldo)
                
                # Reemplazar
                shutil.copy2(db_backup_path, db_actual_path)
                restaurados.append('Base de datos')
            else:
                errores.append('Base de datos no encontrada en backup')
            
            # 2. Restaurar usuarios JSON
            usuarios_backup_path = os.path.join(temp_dir, 'config', 'usuarios.json')
            usuarios_actual_path = os.path.join(app_dir, '..', 'instance', 'usuarios.json')
            
            if os.path.exists(usuarios_backup_path):
                if os.path.exists(usuarios_actual_path):
                    usuarios_respaldo = f"{usuarios_actual_path}.bak.{timestamp_seguro}"
                    shutil.copy2(usuarios_actual_path, usuarios_respaldo)
                shutil.copy2(usuarios_backup_path, usuarios_actual_path)
                restaurados.append('Usuarios')
            else:
                errores.append('Usuarios no encontrados en backup')
            
            # 3. Restaurar documentos
            docs_backup_dir = os.path.join(temp_dir, 'documentos')
            docs_actual_dir = os.path.join(app_dir, '..', 'uploads', 'documentos')
            
            if os.path.exists(docs_backup_dir):
                # Respaldar documentos actuales
                if os.path.exists(docs_actual_dir):
                    docs_respaldo = f"{docs_actual_dir}_bak_{timestamp_seguro}"
                    shutil.copytree(docs_actual_dir, docs_respaldo)
                    # Limpiar directorio actual
                    for item in os.listdir(docs_actual_dir):
                        item_path = os.path.join(docs_actual_dir, item)
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                
                # Copiar documentos del backup
                for item in os.listdir(docs_backup_dir):
                    src = os.path.join(docs_backup_dir, item)
                    dst = os.path.join(docs_actual_dir, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                restaurados.append('Documentos')
        
        # Registrar en auditoría
        try:
            registrar_auditoria(
                tabla='backup',
                registro_id=id,
                accion='restaurar',
                valor_nuevo=f"Backup restaurado: {backup.nombre_archivo}. Elementos: {', '.join(restaurados)}"
            )
        except Exception as e:
            print(f"⚠️ Error en auditoría de restauración: {e}")
        
        # Actualizar estado del backup
        backup.estado = 'restaurado'
        db.session.commit()
        
        if errores:
            flash(f'⚠️ Restauración parcial: {", ".join(restaurados)}. Errores: {", ".join(errores)}', 'warning')
        else:
            flash(f'✅ Restauración completada exitosamente: {", ".join(restaurados)}', 'success')
        
        flash('📝 Se creó un backup de seguridad antes de restaurar', 'info')
        
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al restaurar backup: {str(e)}', 'error')
    
    return redirect(url_for('main.gestion_backup'))


# ============================================
# BACKUP AUTOMÁTICO CON ROTACIÓN (3 copias)
# ============================================

def _limpiar_backups_automaticos():
    """Mantiene solo los 3 backups automáticos más recientes, elimina el resto"""
    try:
        # Buscar todos los backups automáticos ordenados por fecha (más antiguos primero)
        backups_auto = BackupLog.query.filter_by(tipo='automatico')\
            .order_by(BackupLog.fecha_creacion.asc()).all()
        
        # Si hay más de 3, eliminar los más antiguos
        if len(backups_auto) > 3:
            backups_a_eliminar = backups_auto[:-3]  # Todos excepto los últimos 3
            
            for backup in backups_a_eliminar:
                try:
                    # Eliminar archivo físico
                    if os.path.exists(backup.ruta_archivo):
                        os.remove(backup.ruta_archivo)
                    
                    # Registrar en auditoría antes de eliminar
                    try:
                        registrar_auditoria(
                            tabla='backup',
                            registro_id=backup.id,
                            accion='eliminar',
                            valor_anterior=f"Backup auto eliminado por rotación: {backup.nombre_archivo}"
                        )
                    except:
                        pass
                    
                    # Eliminar registro de BD
                    db.session.delete(backup)
                    
                except Exception as e:
                    print(f"⚠️ Error eliminando backup auto antiguo {backup.id}: {e}")
            
            db.session.commit()
            print(f"🗑️ Rotación de backups: {len(backups_a_eliminar)} automáticos eliminados")
            
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en rotación de backups automáticos: {e}")


def _backup_automatico_diario():
    """Genera backup automático diario con rotación de 3 copias"""
    try:
        # Verificar si ya existe un backup automático hoy
        hoy = datetime.now().date()
        backup_hoy = BackupLog.query.filter(
            BackupLog.tipo == 'automatico',
            db.func.date(BackupLog.fecha_creacion) == hoy
        ).first()
        
        if backup_hoy:
            print(f"⏭️ Backup automático de hoy ya existe: {backup_hoy.nombre_archivo}")
            return
        
        # Generar backup automático
        resultado = _generar_backup(
            tipo='automatico',
            descripcion=f'Backup automático diario - {datetime.now().strftime("%d/%m/%Y")}',
            usuario='Sistema_Automatico'
        )
        
        if resultado['success']:
            print(f"✅ Backup automático generado: {resultado['backup'].nombre_archivo}")
            # Aplicar rotación (mantener solo 3)
            _limpiar_backups_automaticos()
        else:
            print(f"❌ Error en backup automático: {resultado.get('error', 'Desconocido')}")
            
    except Exception as e:
        print(f"❌ Error crítico en backup automático: {e}")


# ============================================
# TAREA PROGRAMADA (se ejecuta al iniciar servidor)
# ============================================

def iniciar_backup_automatico(app):
    """Inicia el scheduler de backup automático diario"""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        
        scheduler = BackgroundScheduler()
        
        # Backup automático todos los días a las 2:00 AM
        scheduler.add_job(
            func=_backup_automatico_diario,
            trigger='cron',
            hour=2,
            minute=0,
            id='backup_diario',
            name='Backup Automático Diario',
            replace_existing=True
        )
        
        scheduler.start()
        print("⏰ Scheduler de backup automático iniciado (2:00 AM diario)")
        
        # Ejecutar una vez al iniciar si no hay backups automáticos recientes
        with app.app_context():
            ultimo_auto = BackupLog.query.filter_by(tipo='automatico')\
                .order_by(BackupLog.fecha_creacion.desc()).first()
            
            if not ultimo_auto or (datetime.now() - ultimo_auto.fecha_creacion).days >= 1:
                print("🔄 Generando backup automático inicial...")
                _backup_automatico_diario()
        
        return scheduler
        
    except ImportError:
        print("⚠️ APScheduler no instalado. Backup automático desactivado.")
        print("   Instalar con: pip install apscheduler")
        return None
    except Exception as e:
        print(f"❌ Error iniciando scheduler: {e}")
        return None

# ============================================
# FIN DEL ARCHIVO
# ============================================