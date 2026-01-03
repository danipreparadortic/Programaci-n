import os
import json
import re
from pathlib import Path

# Directorio donde están los ficheros (carpeta 'tests')
DIRECTORIO = os.path.join(os.path.dirname(__file__), 'tests')

def extraer_tema_bloque(nombre_fichero):
    """
    Extrae tema y bloque del nombre del fichero.
    Formato esperado: temaX_bloqueX.json
    Ejemplo: tema1_bloque1.json -> (1, 1)
    """
    patron = r'tema(\d+)_bloque(\d+)\.json'
    match = re.search(patron, nombre_fichero, re.IGNORECASE)
    
    if match:
        tema = int(match.group(1))
        bloque = int(match.group(2))
        return tema, bloque
    return None, None

def procesar_preguntas():
    """
    Procesa todos los ficheros temaX_bloqueX.json y crea preguntas.json
    """
    preguntas_combinadas = []
    id_global = 1
    ficheros_procesados = []
    
    # Buscar todos los ficheros JSON en el directorio
    for fichero in sorted(os.listdir(DIRECTORIO)):
        if fichero.endswith('.json') and fichero != 'preguntas.json':
            ruta_fichero = os.path.join(DIRECTORIO, fichero)
            
            # Extraer tema y bloque del nombre
            tema, bloque = extraer_tema_bloque(fichero)
            
            if tema is None or bloque is None:
                print(f"⚠️  Fichero ignorado (formato incorrecto): {fichero}")
                continue
            
            try:
                with open(ruta_fichero, 'r', encoding='utf-8') as f:
                    preguntas = json.load(f)
                
                # Si es un objeto con clave "preguntas", extraer el array
                if isinstance(preguntas, dict) and 'preguntas' in preguntas:
                    preguntas = preguntas['preguntas']
                
                # Asegurarse de que es una lista
                if not isinstance(preguntas, list):
                    print(f"⚠️  {fichero} no contiene un array de preguntas")
                    continue
                
                # Procesar cada pregunta
                for pregunta in preguntas:
                    if isinstance(pregunta, dict):
                        # Añadir campos de bloque y tema
                        pregunta['bloque'] = bloque
                        pregunta['tema'] = tema
                        
                        # Asegurarse de que tiene ID
                        if 'id' not in pregunta:
                            pregunta['id'] = id_global
                        
                        preguntas_combinadas.append(pregunta)
                        id_global += 1
                
                ficheros_procesados.append(f"{fichero} → Bloque {bloque}, Tema {tema} ({len(preguntas)} preguntas)")
                print(f"✅ Procesado: {fichero} → Bloque {bloque}, Tema {tema} ({len(preguntas)} preguntas)")
            
            except json.JSONDecodeError as e:
                print(f"❌ Error al procesar {fichero}: {e}")
            except Exception as e:
                print(f"❌ Error inesperado en {fichero}: {e}")
    
    # Guardar en preguntas.json (en la carpeta padre, no en tests)
    if preguntas_combinadas:
        ruta_salida = os.path.join(os.path.dirname(__file__), 'preguntas.json')
        with open(ruta_salida, 'w', encoding='utf-8') as f:
            json.dump(preguntas_combinadas, f, ensure_ascii=False, indent=2)
        
        print("\n" + "="*60)
        print(f"✅ Ficheros procesados: {len(ficheros_procesados)}")
        for item in ficheros_procesados:
            print(f"   {item}")
        print(f"\n✅ Total de preguntas: {len(preguntas_combinadas)}")
        print(f"✅ Archivo guardado: {ruta_salida}")
        print("="*60)
    else:
        print("\n❌ No se encontraron preguntas para procesar")

if __name__ == "__main__":
    print("🔄 Procesando ficheros de preguntas...\n")
    procesar_preguntas()
    print("\n✅ Proceso completado")
