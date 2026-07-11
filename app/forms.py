from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import StringField, TextAreaField, SelectField, SubmitField, DateField, IntegerField, HiddenField, TimeField
from wtforms.validators import DataRequired, Optional, Length, ValidationError

class ExpedienteForm(FlaskForm):
    tipo = SelectField('Tipo de Expediente *', 
                      choices=[
                          ('civil', '⚖️ Derecho Civil'),
                          ('penal', '🚔 Derecho Penal'),
                          ('administrativo', '🏛️ Administrativo'),
                          ('conciliacion', '🤝 Centro de Conciliación'),
                          ('archivo', '📦 Archivo')
                      ],
                      validators=[DataRequired()])
    
    numero_expediente = StringField('N° de Expediente', validators=[Optional()])
    dni = StringField('DNI', validators=[Optional()])
    cliente = StringField('Cliente / Interesado *', validators=[DataRequired(), Length(max=200)])
    telefono = StringField('Teléfono', validators=[Optional(), Length(max=20)])
    materia = StringField('Materia / Asunto *', validators=[DataRequired(), Length(max=300)])
    descripcion = TextAreaField('Descripción', validators=[Optional()])
    
    # Campos específicos
    entidad_receptora = StringField('Entidad Receptora', validators=[Optional()])
    tramite = StringField('Tipo de Trámite', validators=[Optional()])
    secretario = StringField('Secretario del Juzgado', validators=[Optional()])
    juez = StringField('Juez', validators=[Optional()])
    juzgado = StringField('Juzgado / Sala', validators=[Optional()])
    numero_cf = StringField('N° Cuaderno Fiscalía', validators=[Optional()])
    fiscal = StringField('Fiscal', validators=[Optional()])
    conciliador = StringField('Conciliador', validators=[Optional()])
    solicitante = StringField('Solicitante', validators=[Optional()])
    invitados = TextAreaField('Invitados / Otras Partes', validators=[Optional()])
    ubicacion_archivo = StringField('Ubicación Física', validators=[Optional()])
    
    submit = SubmitField('💾 Guardar Expediente')

class EstadoForm(FlaskForm):
    estado = SelectField('Nuevo Estado *',
                        choices=[
                            ('ingresado', '📥 Ingresado'),
                            ('actualizado', '📝 Actualizado'),
                            ('en_proceso', '⚙️ En Proceso'),
                            ('seguimiento', '👁️ En Seguimiento'),
                            ('espera_documentos', '⏳ En Espera de Documentos'),
                            ('derivado_juzgado', '⚖️ Derivado a Juzgado'),
                            ('audiencia_programada', '📅 Audiencia Programada'),
                            ('proceso_completado', '✅ Proceso Completado'),
                            ('resuelto_favorable', '🏆 Resuelto Favorablemente'),
                            ('resuelto_desfavorable', '❌ Resuelto Desfavorablemente'),
                            ('archivado', '📦 Archivado'),
                            ('anulado', '🚫 Anulado'),
                            ('otro', '🔘 Otro')
                        ],
                        validators=[DataRequired()])
    
    descripcion = TextAreaField('Descripción / Observaciones', validators=[Optional()])
    submit = SubmitField('➕ Agregar Estado')

class BusquedaForm(FlaskForm):
    tipo_busqueda = SelectField('Buscar por',
                               choices=[
                                   ('expediente', '📁 N° de Expediente'),
                                   ('dni', '🆔 DNI')
                               ],
                               validators=[DataRequired()])
    
    termino = StringField('Término de búsqueda *', validators=[DataRequired()])
    submit = SubmitField('🔍 Buscar')

# ============================================
# FORMULARIO AUDIENCIA - MÓDULO AUDIENCIAS
# ============================================

class AudienciaForm(FlaskForm):
    """Formulario para programar audiencias"""
    
    # Fecha y hora
    fecha = DateField('Fecha de la Audiencia *', 
                      format='%Y-%m-%d',
                      validators=[DataRequired()])
    
    hora = TimeField('Hora de la Audiencia *', 
                     format='%H:%M',
                     validators=[DataRequired()])
    
    # Tipo de audiencia
    tipo_audiencia = SelectField('Tipo de Audiencia *',
                                  choices=[
                                      ('audiencia', '⚖️ Audiencia'),
                                      ('conciliacion', '🤝 Conciliación'),
                                      ('juicio', '🏛️ Juicio Oral'),
                                      ('declaracion', '📝 Declaración'),
                                      ('diligencia', '🔍 Diligencia'),
                                      ('audiencia_prueba', '📋 Audiencia de Prueba'),
                                      ('audiencia_sentencia', '⚖️ Audiencia de Sentencia'),
                                      ('control', '👁️ Control de Plazo'),
                                      ('otros', '📎 Otro')
                                  ],
                                  validators=[DataRequired()])
    
    # Ubicación
    lugar = StringField('Lugar / Juzgado', 
                        validators=[Optional(), Length(max=200)],
                        render_kw={"placeholder": "Ej: Juzgado Civil de Lima, Corte Superior..."})
    
    sala = StringField('Sala / Número de Sala', 
                       validators=[Optional(), Length(max=100)],
                       render_kw={"placeholder": "Ej: Sala 302, Sala A..."})
    
    # Magistrado
    magistrado = StringField('Juez / Conciliador / Fiscal', 
                             validators=[Optional(), Length(max=100)],
                             render_kw={"placeholder": "Nombre del magistrado a cargo"})
    
    # Link para videollamada
    link_videollamada = StringField('Link de Videollamada (opcional)', 
                                    validators=[Optional(), Length(max=500)],
                                    render_kw={"placeholder": "https://meet.google.com/... o https://zoom.us/..."})
    
    # Observaciones
    observaciones = TextAreaField('Observaciones / Notas', 
                                  validators=[Optional()],
                                  render_kw={"placeholder": "Información adicional importante..."})
    
    # Recordatorio
    recordatorio_dias = SelectField('Recordatorio (días antes)',
                                     choices=[
                                         (0, 'El mismo día'),
                                         (1, '1 día antes'),
                                         (2, '2 días antes'),
                                         (3, '3 días antes'),
                                         (7, '1 semana antes')
                                     ],
                                     coerce=int,
                                     default=1)
    
    submit = SubmitField('📅 Programar Audiencia')


class BusquedaAudienciaForm(FlaskForm):
    """Formulario para buscar audiencias"""
    
    fecha_desde = DateField('Desde', format='%Y-%m-%d', validators=[Optional()])
    fecha_hasta = DateField('Hasta', format='%Y-%m-%d', validators=[Optional()])
    
    tipo_audiencia = SelectField('Tipo',
                                  choices=[
                                      ('', 'Todos los tipos'),
                                      ('audiencia', '⚖️ Audiencia'),
                                      ('conciliacion', '🤝 Conciliación'),
                                      ('juicio', '🏛️ Juicio Oral'),
                                      ('declaracion', '📝 Declaración'),
                                      ('diligencia', '🔍 Diligencia'),
                                      ('otros', '📎 Otro')
                                  ],
                                  validators=[Optional()])
    
    estado = SelectField('Estado',
                        choices=[
                            ('', 'Todos los estados'),
                            ('programada', '📅 Programada'),
                            ('realizada', '✅ Realizada'),
                            ('aplazada', '⏸️ Aplazada'),
                            ('cancelada', '❌ Cancelada')
                        ],
                        validators=[Optional()])
    
    submit = SubmitField('🔍 Buscar')

# ============================================
# FORMULARIOS DOCUMENTO - MÓDULO DOCUMENTOS
# ============================================

class DocumentoForm(FlaskForm):
    """Formulario para subir documentos"""
    
    expediente_id = SelectField('Expediente Relacionado (Opcional)', 
                                 coerce=int, 
                                 validators=[Optional()])
    
    titulo = StringField('Título del Documento *', 
                         validators=[DataRequired(), Length(max=200)])
    
    descripcion = TextAreaField('Descripción / Observaciones', 
                                validators=[Optional()])
    
    categoria = SelectField('Categoría *', 
                            choices=[
                                ('escrito', '📝 Escrito'),
                                ('resolucion', '⚖️ Resolución Judicial'),
                                ('contrato', '📄 Contrato'),
                                ('evidencia', '📷 Evidencia Fotográfica'),
                                ('poder', '✍️ Poder / Representación'),
                                ('notificacion', '📬 Notificación'),
                                ('otros', '📎 Otros Documentos')
                            ],
                            validators=[DataRequired()])
    
    fecha_documento = DateField('Fecha del Documento', 
                                format='%Y-%m-%d',
                                validators=[Optional()])
    
    archivo = FileField('Archivo *', 
                        validators=[
                            DataRequired(),
                            FileAllowed(['pdf', 'doc', 'docx', 'xls', 'xlsx', 
                                        'jpg', 'jpeg', 'png', 'gif', 
                                        'mp4', 'mp3', 'zip', 'rar', 'txt'],
                                       'Solo se permiten: PDF, Word, Excel, imágenes, audio, video, ZIP')
                        ])
    
    submit = SubmitField('📤 Subir Documento')


class BusquedaDocumentoForm(FlaskForm):
    """Formulario para buscar documentos"""
    
    termino = StringField('Buscar por título', validators=[Optional()])
    
    categoria = SelectField('Categoría', 
                            choices=[
                                ('', 'Todas las categorías'),
                                ('escrito', '📝 Escrito'),
                                ('resolucion', '⚖️ Resolución'),
                                ('contrato', '📄 Contrato'),
                                ('evidencia', '📷 Evidencia'),
                                ('poder', '✍️ Poder'),
                                ('notificacion', '📬 Notificación'),
                                ('otros', '📎 Otros')
                            ],
                            validators=[Optional()])
    
    expediente_id = SelectField('Filtrar por Expediente', 
                                coerce=int,
                                validators=[Optional()])
    
    submit = SubmitField('🔍 Buscar')

# ============================================
# FORMULARIO MODAL - NUEVA ACTUALIZACIÓN (2 pasos)
# ============================================

class ActualizacionModalForm(FlaskForm):
    """Paso 1: Fecha y descripción de la actuación"""
    fecha_actuacion = DateField('Fecha de la Actuación *', 
                                format='%Y-%m-%d',
                                validators=[DataRequired()])
    
    descripcion = TextAreaField('¿Qué se realizó? *', 
                                validators=[DataRequired()],
                                render_kw={"placeholder": "Ej: Cliente trajo documento X para presentar. Se programó audiencia para el 15/05..."})
    
    submit = SubmitField('💾 Guardar y Seleccionar Estado')


class EstadoSelectorForm(FlaskForm):
    """Paso 2: Seleccionar estado que corresponde a la actuación"""
    estado = SelectField('Estado que corresponde a esta actuación *',
                        choices=[
                            ('ingresado', '📥 Ingresado'),
                            ('actualizado', '📝 Actualizado'),
                            ('en_proceso', '⚙️ En Proceso'),
                            ('seguimiento', '👁️ En Seguimiento'),
                            ('espera_documentos', '⏳ En Espera de Documentos'),
                            ('derivado_juzgado', '⚖️ Derivado a Juzgado'),
                            ('audiencia_programada', '📅 Audiencia Programada'),
                            ('proceso_completado', '✅ Proceso Completado'),
                            ('resuelto_favorable', '🏆 Resuelto Favorablemente'),
                            ('resuelto_desfavorable', '❌ Resuelto Desfavorablemente'),
                            ('archivado', '📦 Archivado'),
                            ('anulado', '🚫 Anulado'),
                            ('otro', '🔘 Otro')
                        ],
                        validators=[DataRequired()])
    
    submit = SubmitField('✅ Confirmar Estado')