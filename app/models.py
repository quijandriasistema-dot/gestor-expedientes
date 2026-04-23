# app/models.py - Modelos de la base de datos

from app import db
from datetime import datetime

class Expediente(db.Model):
    __tablename__ = 'expedientes'
    
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    numero_expediente = db.Column(db.String(50), nullable=False)
    cliente = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(20))
    dni = db.Column(db.String(20))
    materia = db.Column(db.String(300), nullable=False)
    estado_actual = db.Column(db.String(100), default='ingresado')
    descripcion = db.Column(db.Text)
    
    # Campos específicos por tipo
    entidad_receptora = db.Column(db.String(200))
    tramite = db.Column(db.String(200))
    secretario = db.Column(db.String(100))
    juez = db.Column(db.String(100))
    juzgado = db.Column(db.String(100))
    numero_cf = db.Column(db.String(50))
    fiscal = db.Column(db.String(100))
    conciliador = db.Column(db.String(100))
    solicitante = db.Column(db.String(200))
    invitados = db.Column(db.Text)
    ubicacion_archivo = db.Column(db.String(200))
    fecha_archivado = db.Column(db.Date)
    
    # Metadatos
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    usuario_registro = db.Column(db.String(100))
    
    # Relaciones
    estados = db.relationship('EstadoHistorial', backref='expediente', lazy=True, cascade='all, delete-orphan')
    audiencias = db.relationship('Audiencia', backref='expediente', lazy=True, cascade='all, delete-orphan')
    documentos = db.relationship('Documento', backref='expediente', lazy=True)
    
    def get_tipo_label(self):
        labels = {
            'civil': 'Derecho Civil',
            'penal': 'Derecho Penal',
            'administrativo': 'Administrativo',
            'conciliacion': 'Conciliación',
            'archivo': 'Archivo'
        }
        tipo_key = self.tipo.lower() if self.tipo else ''
        return labels.get(tipo_key, self.tipo)
    
    def get_estado_label(self):
        estados = {
            'ingresado': '📥 Ingresado',
            'actualizado': '📝 Actualizado',
            'en_proceso': '⚙️ En Proceso',
            'seguimiento': '👁️ En Seguimiento',
            'espera_documentos': '⏳ En Espera de Documentos',
            'derivado_juzgado': '⚖️ Derivado a Juzgado',
            'audiencia_programada': '📅 Audiencia Programada',
            'proceso_completado': '✅ Proceso Completado',
            'resuelto_favorable': '🏆 Resuelto Favorablemente',
            'resuelto_desfavorable': '❌ Resuelto Desfavorablemente',
            'archivado': '📦 Archivado',
            'anulado': '🚫 Anulado',
            'otro': '🔘 Otro'
        }
        return estados.get(self.estado_actual, self.estado_actual)
    
    def get_estado_color(self):
        colores = {
            'ingresado': 'info',
            'actualizado': 'warning',
            'en_proceso': 'warning',
            'seguimiento': 'info',
            'espera_documentos': 'warning',
            'derivado_juzgado': 'primary',
            'audiencia_programada': 'primary',
            'proceso_completado': 'success',
            'resuelto_favorable': 'success',
            'resuelto_desfavorable': 'danger',
            'archivado': 'secondary',
            'anulado': 'danger',
            'otro': 'secondary'
        }
        return colores.get(self.estado_actual, 'secondary')
    
    def get_identificador_principal(self):
        tipo_key = self.tipo.lower() if self.tipo else ''
        if tipo_key == 'administrativo':
            return f"DNI: {self.dni or '-'}"
        else:
            return f"Exp: {self.numero_expediente}"

class EstadoHistorial(db.Model):
    __tablename__ = 'estados_historial'
    
    id = db.Column(db.Integer, primary_key=True)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=False)
    estado = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=datetime.now)
    usuario = db.Column(db.String(100))
    
    def get_estado_label(self):
        estados = {
            'ingresado': '📥 Ingresado',
            'actualizado': '📝 Actualizado',
            'en_proceso': '⚙️ En Proceso',
            'seguimiento': '👁️ En Seguimiento',
            'espera_documentos': '⏳ En Espera de Documentos',
            'derivado_juzgado': '⚖️ Derivado a Juzgado',
            'audiencia_programada': '📅 Audiencia Programada',
            'proceso_completado': '✅ Proceso Completado',
            'resuelto_favorable': '🏆 Resuelto Favorablemente',
            'resuelto_desfavorable': '❌ Resuelto Desfavorablemente',
            'archivado': '📦 Archivado',
            'anulado': '🚫 Anulado',
            'otro': '🔘 Otro',
            'Expediente editado': '📝 Expediente Editado',
            'Ingresado a mesa de partes': '📥 Ingresado a Mesa de Partes'
        }
        return estados.get(self.estado, self.estado)

# ============================================
# MODELO AUDIENCIA - MÓDULO AUDIENCIAS
# ============================================

class Audiencia(db.Model):
    """Modelo para gestión de audiencias de expedientes"""
    __tablename__ = 'audiencias'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relación con expediente (solo ForeignKey, la relación backref está en Expediente)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=False)
    
    # Fecha y hora de la audiencia
    fecha = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    
    # Información de la audiencia
    tipo_audiencia = db.Column(db.String(100), nullable=False, default='audiencia')
    # tipos: audiencia, conciliacion, juicio, declaracion, diligencia, otros
    
    # Ubicación
    lugar = db.Column(db.String(200))  # Juzgado, sala, dirección
    sala = db.Column(db.String(100))   # Número de sala
    
    # Juez, conciliador o fiscal
    magistrado = db.Column(db.String(100))  # Nombre del juez/conciliador/fiscal
    
    # Link para videollamada (audiencias virtuales)
    link_videollamada = db.Column(db.String(500))
    
    # Observaciones
    observaciones = db.Column(db.Text)
    
    # Estado de la audiencia
    estado = db.Column(db.String(50), default='programada')
    # estados: programada, realizada, aplazada, cancelada, pendiente
    
    # Recordatorio (días antes)
    recordatorio_dias = db.Column(db.Integer, default=1)
    
    # Metadatos
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    usuario_registro = db.Column(db.String(100), nullable=False)
    
    # ✅ ELIMINADA: La relación backref ya está definida en Expediente
    # expediente = db.relationship('Expediente', backref='audiencias', lazy=True)
    
    def __repr__(self):
        return f'<Audiencia {self.fecha} {self.hora} - {self.expediente_id}>'
    
    def get_tipo_label(self):
        """Devuelve etiqueta legible del tipo de audiencia"""
        tipos = {
            'audiencia': '⚖️ Audiencia',
            'conciliacion': '🤝 Conciliación',
            'juicio': '🏛️ Juicio Oral',
            'declaracion': '📝 Declaración',
            'diligencia': '🔍 Diligencia',
            'audiencia_prueba': '📋 Audiencia de Prueba',
            'audiencia_sentencia': '⚖️ Audiencia de Sentencia',
            'control': '👁️ Control de Plazo',
            'otros': '📎 Otro'
        }
        return tipos.get(self.tipo_audiencia, '📎 Otro')
    
    def get_estado_label(self):
        """Devuelve etiqueta legible del estado"""
        estados = {
            'programada': '📅 Programada',
            'realizada': '✅ Realizada',
            'aplazada': '⏸️ Aplazada',
            'cancelada': '❌ Cancelada',
            'pendiente': '⏳ Pendiente'
        }
        return estados.get(self.estado, '📅 Programada')
    
    def get_estado_color(self):
        """Devuelve clase CSS según estado"""
        colores = {
            'programada': 'primary',
            'realizada': 'success',
            'aplazada': 'warning',
            'cancelada': 'danger',
            'pendiente': 'info'
        }
        return colores.get(self.estado, 'primary')
    
    def get_fecha_hora_formateada(self):
        """Devuelve fecha y hora formateada"""
        return f"{self.fecha.strftime('%d/%m/%Y')} a las {self.hora.strftime('%H:%M')}"
    
    def es_proxima(self):
        """Verifica si la audiencia es en los próximos 3 días"""
        from datetime import date, timedelta
        hoy = date.today()
        dias_diferencia = (self.fecha - hoy).days
        return 0 <= dias_diferencia <= 3 and self.estado == 'programada'
    
    def es_hoy(self):
        """Verifica si la audiencia es hoy"""
        from datetime import date
        return self.fecha == date.today() and self.estado == 'programada'

# ============================================
# MODELO DOCUMENTO - MÓDULO DOCUMENTOS
# ============================================

class Documento(db.Model):
    """Modelo para gestión de documentos de expedientes"""
    __tablename__ = 'documentos'
    
    id = db.Column(db.Integer, primary_key=True)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    categoria = db.Column(db.String(50), nullable=False, default='otros')
    nombre_archivo = db.Column(db.String(255), nullable=False)
    tipo_archivo = db.Column(db.String(50), nullable=False)
    tamaño_bytes = db.Column(db.Integer, nullable=False)
    ruta_archivo = db.Column(db.String(500), nullable=False)
    fecha_documento = db.Column(db.Date, nullable=True)
    fecha_subida = db.Column(db.DateTime, default=datetime.now)
    usuario_subida = db.Column(db.String(100), nullable=False)
    es_publico = db.Column(db.Boolean, default=True)
    
    # ✅ CORREGIDO: Eliminado backref duplicado, ya está en Expediente
    # expediente = db.relationship('Expediente', backref='documentos', lazy=True)
    
    def __repr__(self):
        return f'<Documento {self.titulo}>'
    
    def get_tipo_label(self):
        tipos = {
            'escrito': '📝 Escrito',
            'resolucion': '⚖️ Resolución',
            'contrato': '📄 Contrato',
            'evidencia': '📷 Evidencia',
            'poder': '✍️ Poder',
            'notificacion': '📬 Notificación',
            'otros': '📎 Otros'
        }
        return tipos.get(self.categoria, '📎 Otros')
    
    def get_icono(self):
        iconos = {
            'pdf': '📕',
            'doc': '📘',
            'docx': '📘',
            'xls': '📗',
            'xlsx': '📗',
            'jpg': '🖼️',
            'jpeg': '🖼️',
            'png': '🖼️',
            'gif': '🖼️',
            'mp4': '🎬',
            'mp3': '🎵',
            'zip': '📦',
            'rar': '📦'
        }
        return iconos.get(self.tipo_archivo.lower(), '📄')
    
    def get_tamaño_formateado(self):
        if self.tamaño_bytes < 1024:
            return f"{self.tamaño_bytes} B"
        elif self.tamaño_bytes < 1024 * 1024:
            return f"{self.tamaño_bytes / 1024:.1f} KB"
        else:
            return f"{self.tamaño_bytes / (1024 * 1024):.1f} MB"
    
    def get_extension(self):
        return self.tipo_archivo.upper()
    
# ============================================
# MODELO NOTIFICACION - SISTEMA DE ALERTAS
# ============================================

class Notificacion(db.Model):
    """Notificaciones del sistema para usuarios"""
    __tablename__ = 'notificaciones'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Tipo de notificación
    tipo = db.Column(db.String(50), nullable=False)  
    # tipos: 'audiencia_proxima', 'audiencia_hoy', 'audiencia_manana', 
    #        'estado_cambiado', 'documento_subido', 'sistema'
    
    # Relación con expediente (opcional)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=True)
    
    # Relación con audiencia (opcional)
    audiencia_id = db.Column(db.Integer, db.ForeignKey('audiencias.id'), nullable=True)
    
    # Contenido
    titulo = db.Column(db.String(200), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    
    # Destinatario (si es null, es para todos)
    usuario_destino = db.Column(db.String(100), nullable=True)
    
    # Estado
    leida = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)
    fecha_lectura = db.Column(db.DateTime, nullable=True)
    
    # Link para redirigir al hacer clic
    link = db.Column(db.String(500), nullable=True)
    
    # Icono/Color para la UI
    icono = db.Column(db.String(50), default='🔔')
    color = db.Column(db.String(20), default='info')  # info, warning, danger, success
    
    def __repr__(self):
        return f'<Notificacion {self.tipo}: {self.titulo}>'
    
    def get_tiempo_transcurrido(self):
        if self.fecha_creacion is None:
            return 'Fecha desconocida'
    
        diff = datetime.now() - self.fecha_creacion
    
        if diff.days > 0:
            return f'Hace {diff.days} día(s)'
        hours = diff.seconds // 3600
        if hours > 0:
            return f'Hace {hours} hora(s)'
        minutes = diff.seconds // 60
        if minutes > 0:
            return f'Hace {minutes} minuto(s)'
        return 'Hace un momento'
        
# ============================================
# MODELO USUARIO - SUPABASE (tabla: usuario)
# ============================================

class Usuario(db.Model):
    __tablename__ = 'usuario'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    rol = db.Column(db.String(20), default='USUARIO')
    modulos = db.Column(db.Text, default='[]')
    activo = db.Column(db.Boolean, default=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_acceso = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<Usuario {self.username}>'
    
    def get_modulos_list(self):
        """Devuelve la lista de módulos permitidos"""
        import json
        try:
            return json.loads(self.modulos) if self.modulos else []
        except:
            return []
    
    def set_modulos_list(self, modulos_list):
        """Guarda la lista de módulos como JSON string"""
        import json
        self.modulos = json.dumps(modulos_list) if isinstance(modulos_list, list) else '[]'
    
    def check_password(self, password):
        """Verifica contraseña con bcrypt"""
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    def set_password(self, password):
        """Genera hash bcrypt de la contraseña"""
        import bcrypt
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt(rounds=12)
        self.password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
    
    def to_dict(self):
        """Devuelve datos del usuario (sin password)"""
        return {
            'username': self.username,
            'nombre': self.nombre,
            'email': self.email,
            'rol': self.rol,
            'modulos': self.get_modulos_list(),
            'activo': self.activo,
            'fecha_registro': self.fecha_registro.strftime('%Y-%m-%d %H:%M') if self.fecha_registro else None
        }
    