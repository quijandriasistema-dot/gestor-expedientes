# app/usuarios.py - Sistema de usuarios y permisos

from werkzeug.security import check_password_hash
from functools import wraps
from flask import session, redirect, url_for, flash

# ═══════════════════════════════════════════════════════════
# USUARIOS PRE-DEFINIDOS (Hardcodeados - solo 3 roles)
# ═══════════════════════════════════════════════════════════

USUARIOS = {
    # DESARROLLADOR (No se puede eliminar, acceso total)
    'dev': {
        'password': 'dev123',  # En producción usar hash
        'rol': 'DESARROLLADOR',
        'nombre': 'Desarrollador Principal',
        'puede_eliminar': [],
        'modulos': ['todo']
    },
    
    # ADMINISTRADOR (Ejemplo)
    'admin': {
        'password': 'admin123',
        'rol': 'ADMINISTRADOR',
        'nombre': 'Administrador Sistema',
        'puede_eliminar': ['USUARIO'],
        'modulos': ['expedientes', 'civil', 'penal', 'administrativo', 
                   'conciliacion', 'audiencias', 'archivo', 'reportes', 'usuarios']
    },
    
    # USUARIO NORMAL (Ejemplo)
    'usuario1': {
        'password': 'user123',
        'rol': 'USUARIO',
        'nombre': 'Asistente Legal',
        'puede_eliminar': [],
        'modulos': ['expedientes', 'civil', 'penal', 'audiencias']
    }
}

# ═══════════════════════════════════════════════════════════
# FUNCIONES DE AUTENTICACIÓN
# ═══════════════════════════════════════════════════════════

def verificar_usuario(username, password):
    """Verifica si usuario existe y contraseña es correcta"""
    if username in USUARIOS:
        usuario = USUARIOS[username]
        if usuario['password'] == password:
            return usuario
    return None

def login_user(username):
    """Guarda usuario en sesión"""
    session['username'] = username
    session['rol'] = USUARIOS[username]['rol']
    session['nombre'] = USUARIOS[username]['nombre']
    session['modulos'] = USUARIOS[username]['modulos']

def logout_user():
    """Limpia sesión"""
    session.clear()

# ═══════════════════════════════════════════════════════════
# DECORADORES DE PERMISOS
# ═══════════════════════════════════════════════════════════

def requiere_login(f):
    """Decorador: Solo usuarios logueados"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash('Debe iniciar sesión primero', 'error')
            return redirect(url_for('main.login'))  # CORREGIDO: main.login
        return f(*args, **kwargs)
    return decorated_function

def requiere_rol(roles_permitidos):
    """Decorador: Solo ciertos roles"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'rol' not in session or session['rol'] not in roles_permitidos:
                flash('No tiene permisos para acceder', 'error')
                return redirect(url_for('main.index'))  # CORREGIDO: main.index
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Atajos para roles específicos
requiere_desarrollador = requiere_rol(['DESARROLLADOR'])
requiere_admin = requiere_rol(['DESARROLLADOR', 'ADMINISTRADOR'])
requiere_usuario = requiere_rol(['DESARROLLADOR', 'ADMINISTRADOR', 'USUARIO'])

def puede_ver_modulo(nombre_modulo):
    """Verifica si el usuario actual puede ver un módulo"""
    if 'modulos' not in session:
        return False
    modulos = session['modulos']
    return 'todo' in modulos or nombre_modulo in modulos

def tiene_permiso(permiso):
    """Verifica permisos específicos"""
    if 'rol' not in session:
        return False
    
    rol = session['rol']
    
    if rol == 'DESARROLLADOR':
        return True
    
    if rol == 'ADMINISTRADOR':
        return permiso in ['crear_usuario', 'eliminar_usuario', 'ver_modulos']
    
    if rol == 'USUARIO':
        return permiso in ['ver_modulos']
    
    return False