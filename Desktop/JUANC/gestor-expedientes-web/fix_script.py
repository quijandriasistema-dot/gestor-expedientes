with open('generar_datos_prueba_v1.1.py', 'r', encoding='utf-8') as f:
    contenido = f.read()

contenido_corregido = contenido.replace('fecha_cambio=', 'fecha=')

with open('generar_datos_prueba_v1.1.py', 'w', encoding='utf-8') as f:
    f.write(contenido_corregido)

print("Script corregido: fecha_cambio -> fecha")
