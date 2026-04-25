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
    expediente_id = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    tipo_audiencia = db.Column(db.String(100), nullable=False, default='audiencia')
    lugar = db.Column(db.String(200))
    sala = db.Column(db.String(100))
    magistrado = db.Column(db.String(100))
    link_videollamada = db.Column(db.String(500))
    observaciones = db.Column(db.Text)
    estado = db.Column(db.String(50), default='programada')
    recordatorio_dias = db.Column(db.Integer, default=1)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    usuario_registro = db.Column(db.String(100), nullable=False)
    
    def __repr__(self):
        return f'<Audiencia {self.fecha} {self.hora} - {self.expediente_id}>'
    
    def get_tipo_label(self):
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
        estados = {
            'programada': '📅 Programada',
            'realizada': '✅ Realizada',
            'aplazada': '⏸️ Aplazada',
            'cancelada': '❌ Cancelada',
            'pendiente': '⏳ Pendiente'
        }
        return estados.get(self.estado, '📅 Programada')
    
    def get_estado_color(self):
        colores = {
            'programada': 'primary',
            'realizada': 'success',
            'aplazada': 'warning',
            'cancelada': 'danger',
            'pendiente': 'info'
        }
        return colores.get(self.estado, 'primary')
    
    def get_fecha_hora_formateada(self):
        return f"{self.fecha.strftime('%d/%m/%Y')} a las {self.hora.strftime('%H:%M')}"
    
    def es_proxima(self):
        from datetime import date, timedelta
        hoy = date.today()
        dias_diferencia = (self.fecha - hoy).days
        return 0 <= dias_diferencia <= 3 and self.estado == 'programada'
    
    def es_hoy(self):
        from datetime import date
        return self.fecha == date.today() and self.estado == 'programada'

# ============================================
# MODELO DOCUMENTO - MÓDULO DOCUMENTOS (CON GOOGLE DRIVE)
# ============================================

class Documento(db.Model):
    __tablename__ = 'documentos'
    
    # === CAMPOS QUE YA TENÍAS (mantener nombres) ===
    id = db.Column(db.Integer, primary_key=True)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=False)
    titulo = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text)
    categoria = db.Column(db.String(50), default='otros')
    nombre_archivo = db.Column(db.String(255))
    tipo_archivo = db.Column(db.String(50))
    tamaño_bytes = db.Column(db.Integer)        # ← tu nombre
    ruta_archivo = db.Column(db.String(500))      # ← tu nombre
    fecha_documento = db.Column(db.Date)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_subida = db.Column(db.String(100))
    es_publico = db.Column(db.Boolean, default=False)
    
    # === CAMPOS NUEVOS PARA GOOGLE DRIVE ===
    url_drive = db.Column(db.String(500))
    drive_file_id = db.Column(db.String(100))
    ubicacion = db.Column(db.String(20), default='local')  # 'local', 'drive', 'ambos'

    # === MÉTODOS ===
    def get_tamaño_formateado(self):
        """Usa tamaño_bytes (tu campo)"""
        if not self.tamaño_bytes:
            return '0 B'
        if self.tamaño_bytes < 1024:
            return f"{self.tamaño_bytes} B"
        elif self.tamaño_bytes < 1024 * 1024:
            return f"{self.tamaño_bytes / 1024:.1f} KB"
        else:
            return f"{self.tamaño_bytes / (1024 * 1024):.1f} MB"
    
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
            'pdf': '📕', 'doc': '📘', 'docx': '📘',
            'xls': '📗', 'xlsx': '📗',
            'jpg': '🖼️', 'jpeg': '🖼️', 'png': '🖼️', 'gif': '🖼️',
            'mp4': '🎬', 'mp3': '🎵',
            'zip': '📦', 'rar': '📦'
        }
        return iconos.get(self.tipo_archivo.lower() if self.tipo_archivo else '', '📄')
    
    def get_extension(self):
        return self.tipo_archivo.upper() if self.tipo_archivo else 'DESCONOCIDO'
    
    def get_ubicacion_label(self):
        if self.ubicacion == 'drive':
            return '<span class="badge badge-primary"><i class="fab fa-google-drive"></i> Nube</span>'
        elif self.ubicacion == 'local':
            return '<span class="badge badge-secondary"><i class="fas fa-desktop"></i> Local</span>'
        elif self.ubicacion == 'ambos':
            return '<span class="badge badge-success"><i class="fas fa-cloud"></i> Ambos</span>'
        elif self.ubicacion == 'archivado_local':
            return '<span class="badge badge-warning" title="Disponible solo en PC de oficina"><i class="fas fa-archive"></i> Archivado</span>'
        elif self.ubicacion == 'eliminado':
            return '<span class="badge badge-danger"><i class="fas fa-trash"></i> Eliminado</span>'
        return ''

# ============================================
# MODELO NOTIFICACION - SISTEMA DE ALERTAS
# ============================================

class Notificacion(db.Model):
    __tablename__ = 'notificaciones'
    
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    expediente_id = db.Column(db.Integer, db.ForeignKey('expedientes.id'), nullable=True)
    audiencia_id = db.Column(db.Integer, db.ForeignKey('audiencias.id'), nullable=True)
    titulo = db.Column(db.String(200), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    usuario_destino = db.Column(db.String(100), nullable=True)
    leida = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)
    fecha_lectura = db.Column(db.DateTime, nullable=True)
    link = db.Column(db.String(500), nullable=True)
    icono = db.Column(db.String(50), default='🔔')
    color = db.Column(db.String(20), default='info')
    
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
        import json
        try:
            return json.loads(self.modulos) if self.modulos else []
        except:
            return []
    
    def set_modulos_list(self, modulos_list):
        import json
        self.modulos = json.dumps(modulos_list) if isinstance(modulos_list, list) else '[]'
    
    def check_password(self, password):
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    def set_password(self, password):
        import bcrypt
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt(rounds=12)
        self.password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
    
    def to_dict(self):
        return {
            'username': self.username,
            'nombre': self.nombre,
            'email': self.email,
            'rol': self.rol,
            'modulos': self.get_modulos_list(),
            'activo': self.activo,
            'fecha_registro': self.fecha_registro.strftime('%Y-%m-%d %H:%M') if self.fecha_registro else None
        }
    
get_ubicacion_label