from dotenv import load_dotenv
import os

# Carga variables desde token.env en el mismo directorio
load_dotenv()

raw = os.getenv("USUARIOS_AUTORIZADOS", "")
print("RAW:", repr(raw))

# Parsing simple (como fallback)
items_simple = [p.strip() for p in raw.split(",")] if raw else []
print("Items (split simple):", items_simple)

# Importar y usar la función de normalización desde main (si existe)
try:
    from main import cargar_usuarios_autorizados_from_env
    norm = cargar_usuarios_autorizados_from_env()
    print("Usuarios normalizados (set):", norm)
except Exception as e:
    print("No se pudo importar la función de main.py:", e)
    print("Puedes ejecutar main.py y probar directamente desde el bot.")
