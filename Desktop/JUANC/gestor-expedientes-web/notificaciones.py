# ============================================
# FUNCIONES DE NOTIFICACIONES
# ============================================

from flask import url_for
from app import db
from app.models import Notificacion, Audiencia, Expediente
from datetime import datetime, timedelta, date


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
        # Verificar si ya existe notificación para hoy
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
                link=url_for('main.ver_audiencia', id=aud.id, _external=False),
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
                link=url_for('main.ver_audiencia', id=aud.id, _external=False),
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
                link=url_for('main.ver_audiencia', id=aud.id, _external=False),
                icono='📢',
                color='info'
            )


def get_notificaciones_usuario(usuario, rol, solo_no_leidas=False, limite=10):
    """Obtiene notificaciones para un usuario específico"""
    query = Notificacion.query
    
    # Si no es desarrollador, filtrar por destinatario o generales
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