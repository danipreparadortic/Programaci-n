import os
import json
import logging
import random
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from functools import wraps

# 1. Cargamos las variables de entorno (el Token)
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
def cargar_usuarios_autorizados_from_env():
    """Lee `USUARIOS_AUTORIZADOS` desde variables de entorno o .env y normaliza.
    Soporta formatos como:
      - JSON array: ["@user", "12345"]
      - Comma separated: @user,12345,user2
      - Con o sin corchetes, con o sin espacios
    Devuelve un set con IDs (strings) y nombres de usuario (con y sin '@').
    """
    raw = os.getenv("USUARIOS_AUTORIZADOS", "")
    if not raw:
        return set()

    raw = raw.strip()
    items = []
    # Intentar parsear JSON array
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                items = parsed
        except Exception:
            inner = raw[1:-1]
            items = [p.strip() for p in inner.split(",") if p.strip()]
    else:
        # eliminar comillas exteriores si existen
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        items = [p.strip() for p in raw.split(",") if p.strip()]

    result = set()
    for it in items:
        if not it or it.startswith('#'):
            continue
        # limpiar caracteres residuales
        it = it.strip().lstrip('[').rstrip(']').strip()
        it = it.strip('"').strip("'")

        # si es numérico, añadir como id string
        try:
            num = int(it)
            result.add(str(num))
            continue
        except Exception:
            pass

        # normalizar username: añadir con y sin @
        name = it.lstrip('@')
        if name:
            result.add(name)
            result.add('@' + name)

    return result


# Cargar usuarios autorizados normalizados
USUARIOS_AUTORIZADOS = cargar_usuarios_autorizados_from_env()

# Variables globales para almacenar datos del test
preguntas = []
test_sessions = {}  # Almacena el estado del test por usuario

# Estados para la conversación
SELECCIONAR_BLOQUE, SELECCIONAR_TEMA, SELECCIONAR_CANTIDAD = range(3)

# Configuración de temas por bloque
TEMAS_POR_BLOQUE = {
    "1": 9,
    "2": 5,
    "3": 9,
    "4": 10,
    "aleatorio": 0  # sin límite para aleatorio
}

# 2. Configuración de Logs (Para ver errores en la terminal)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 2b. Configurar logging de intrusos en archivo
def configurar_logging_intrusos():
    """Configura el logger para registrar intentos de acceso no autorizados"""
    ruta_log = os.path.join(os.path.dirname(__file__), 'intrusos.log')
    
    # Crear logger específico para intrusos
    logger_intrusos = logging.getLogger('intrusos')
    logger_intrusos.setLevel(logging.WARNING)
    
    # Handler para archivo
    file_handler = logging.FileHandler(ruta_log, encoding='utf-8')
    file_handler.setLevel(logging.WARNING)
    
    # Formato con más detalles
    formatter = logging.Formatter(
        '%(asctime)s | USUARIO NO AUTORIZADO | Username: %(username)s | ID: %(user_id)s | Chat: %(chat_id)s'
    )
    file_handler.setFormatter(formatter)
    logger_intrusos.addHandler(file_handler)
    
    return logger_intrusos

# Crear logger de intrusos
logger_intrusos = configurar_logging_intrusos()

# 3. Función decoradora para controlar acceso de usuarios
def require_authorization(func):
    """Decorator to check if user is authorized before executing command"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        username = update.effective_user.username or update.effective_user.first_name or "Desconocido"
        chat_id = update.effective_chat.id
        
        # Permitir por ID numérico o por nombre de usuario
        is_authorized = user_id in USUARIOS_AUTORIZADOS or f"@{username}" in USUARIOS_AUTORIZADOS
        
        if not is_authorized:
            # Registrar intento no autorizado en el archivo de log
            logger_intrusos.warning(
                f"Intento de acceso no autorizado",
                extra={
                    'username': username,
                    'user_id': user_id,
                    'chat_id': chat_id
                }
            )
            
            await update.message.reply_text(
                "❌ No tienes permiso para usar este comando. Tu acceso está restringido."
            )
            logging.warning(f"Acceso denegado a usuario: {username} (ID: {user_id})")
            return
        
        # Si está autorizado, ejecutar la función
        return await func(update, context)
    
    return wrapper

# 4. Función para cargar preguntas del JSON
def cargar_preguntas():
    """Carga las preguntas desde el archivo preguntas.json"""
    global preguntas
    try:
        ruta_archivo = os.path.join(os.path.dirname(__file__), "preguntas.json")
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            preguntas = json.load(f)
        logging.info(f"Se cargaron {len(preguntas)} preguntas correctamente")
    except FileNotFoundError:
        logging.error("Archivo preguntas.json no encontrado")
        preguntas = []
    except json.JSONDecodeError:
        logging.error("Error al decodificar preguntas.json")
        preguntas = []

# 5. Función para filtrar preguntas por bloque y tema
def filtrar_preguntas_por_bloque_tema(bloque, tema=None):
    """Filtra las preguntas según el bloque y opcionalmente tema seleccionado"""
    if bloque == "aleatorio":
        return preguntas
    
    bloque_int = int(bloque)
    filtered = [p for p in preguntas if p.get("bloque") == bloque_int]
    
    # Si se especifica tema, filtrar también por tema
    if tema is not None:
        tema_int = int(tema)
        filtered = [p for p in filtered if p.get("tema") == tema_int]
    
    return filtered

# 6. Función para seleccionar preguntas aleatorias
def seleccionar_preguntas_aleatorias(preguntas_filtradas, cantidad):
    """Selecciona una cantidad aleatoria de preguntas del conjunto filtrado"""
    if len(preguntas_filtradas) < cantidad:
        logging.warning(f"Solo hay {len(preguntas_filtradas)} preguntas disponibles, se retornarán todas")
        return preguntas_filtradas
    return random.sample(preguntas_filtradas, cantidad)


# --- FUNCIONES DE COMANDOS (Handlers) ---

# Función START con control de acceso
@require_authorization
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Inicia el bot y da bienvenida al usuario autorizado"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or update.effective_user.username
    
    welcome_message = f"""
🎓 **BOT DE PREGUNTAS DE DANIEL VILLAR, PREPARADOR DE OPOSICIÓN TAI**

¡Hola {username}! 👋

Bienvenido a tu plataforma de estudio online.

📋 **Comandos disponibles:**
/test - Iniciar un test con las preguntas cargadas
/ayuda - Ver la ayuda del bot
/salir - Terminar el test actual

💡 **Recuerda:** Puedes hacer el test todas las veces que necesites para practicar y mejorar.

¿Qué deseas hacer?
    """
    
    await update.message.reply_text(welcome_message, parse_mode="Markdown")
    logging.info(f"Usuario autorizado iniciado: {username} (ID: {user_id})")


# Función TEST - Inicia el test online
@require_authorization
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /test - Muestra menú para seleccionar bloque"""
    user_id = update.effective_user.id
    
    if not preguntas:
        await update.message.reply_text("❌ No hay preguntas disponibles. Por favor, intenta más tarde.")
        return SELECCIONAR_BLOQUE
    
    # Crear botones para seleccionar bloque
    keyboard = [
        [InlineKeyboardButton("📚 Bloque I", callback_data="bloque_1")],
        [InlineKeyboardButton("📚 Bloque II", callback_data="bloque_2")],
        [InlineKeyboardButton("📚 Bloque III", callback_data="bloque_3")],
        [InlineKeyboardButton("📚 Bloque IV", callback_data="bloque_4")],
        [InlineKeyboardButton("🎲 Test Aleatorio (Todos los Bloques)", callback_data="bloque_aleatorio")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mensaje = """
🎯 **Selecciona el bloque de preguntas:**

1️⃣ Bloque I
2️⃣ Bloque II
3️⃣ Bloque III
4️⃣ Bloque IV
🎲 Test Aleatorio (todos los bloques)

_Selecciona una opción para continuar._
    """
    
    await update.message.reply_text(mensaje, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECCIONAR_BLOQUE


# Función para manejar la selección de bloque
async def seleccionar_bloque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de bloque y muestra el menú de temas"""
    query = update.callback_query
    user_id = query.from_user.id
    bloque_seleccionado = query.data.split("_")[1]
    
    # Guardar bloque seleccionado en la sesión
    context.user_data['bloque'] = bloque_seleccionado
    
    await query.answer()
    
    bloque_nombre = {
        "1": "Bloque I",
        "2": "Bloque II",
        "3": "Bloque III",
        "4": "Bloque IV",
        "aleatorio": "Test Aleatorio (Todos los Bloques)"
    }
    
    # Si es aleatorio, saltamos directamente a cantidad
    if bloque_seleccionado == "aleatorio":
        # Mostrar menú de cantidad de preguntas
        keyboard = [
            [InlineKeyboardButton("📋 50 preguntas", callback_data="cantidad_50")],
            [InlineKeyboardButton("📋 100 preguntas", callback_data="cantidad_100")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        mensaje = f"""
✅ Bloque seleccionado: **{bloque_nombre.get(bloque_seleccionado, 'Desconocido')}**

📊 **¿Cuántas preguntas deseas responder?**

• 50 preguntas
• 100 preguntas

_Selecciona una opción para continuar._
        """
        
        await query.edit_message_text(mensaje, reply_markup=reply_markup, parse_mode="Markdown")
        return SELECCIONAR_CANTIDAD
    
    # Para bloques específicos, mostrar menú de temas
    num_temas = TEMAS_POR_BLOQUE.get(bloque_seleccionado, 0)
    
    # Crear botones de temas
    keyboard = []
    for i in range(1, num_temas + 1):
        keyboard.append([InlineKeyboardButton(f"📖 Tema {i}", callback_data=f"tema_{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mensaje = f"""
✅ Bloque seleccionado: **{bloque_nombre.get(bloque_seleccionado, 'Desconocido')}**

📚 **Selecciona un tema:**

_Elige el tema del que deseas practicar preguntas._
    """
    
    await query.edit_message_text(mensaje, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECCIONAR_TEMA


# Función para manejar la selección de tema
async def seleccionar_tema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de tema y pregunta por la cantidad de preguntas"""
    query = update.callback_query
    user_id = query.from_user.id
    tema_seleccionado = query.data.split("_")[1]
    
    # Guardar tema seleccionado en la sesión
    context.user_data['tema'] = tema_seleccionado
    
    await query.answer()
    
    # Obtener bloque y tema
    bloque = context.user_data.get('bloque', 'aleatorio')
    tema = context.user_data.get('tema', None)
    
    bloque_nombre = {
        "1": "Bloque I",
        "2": "Bloque II",
        "3": "Bloque III",
        "4": "Bloque IV",
        "aleatorio": "Test Aleatorio"
    }
    
    # Mostrar menú de cantidad de preguntas
    keyboard = [
        [InlineKeyboardButton("📋 50 preguntas", callback_data="cantidad_50")],
        [InlineKeyboardButton("📋 100 preguntas", callback_data="cantidad_100")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mensaje = f"""
✅ Bloque: **{bloque_nombre.get(bloque, 'Desconocido')}**
✅ Tema: **{tema}**

📊 **¿Cuántas preguntas deseas responder?**

• 50 preguntas
• 100 preguntas

_Selecciona una opción para continuar._
    """
    
    await query.edit_message_text(mensaje, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECCIONAR_CANTIDAD

# Función para manejar la selección de cantidad de preguntas
async def seleccionar_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de cantidad de preguntas e inicia el test"""
    query = update.callback_query
    user_id = query.from_user.id
    cantidad_str = query.data.split("_")[1]
    cantidad = int(cantidad_str)
    
    # Obtener bloque y tema seleccionados
    bloque = context.user_data.get('bloque', 'aleatorio')
    tema = context.user_data.get('tema', None)
    
    # Filtrar preguntas por bloque y tema
    preguntas_filtradas = filtrar_preguntas_por_bloque_tema(bloque, tema)
    
    if not preguntas_filtradas:
        await query.answer("❌ No hay preguntas en esta selección", show_alert=True)
        return SELECCIONAR_BLOQUE
    
    # Seleccionar preguntas aleatorias
    preguntas_seleccionadas = seleccionar_preguntas_aleatorias(preguntas_filtradas, cantidad)
    
    # Inicializar sesión del test
    test_sessions[user_id] = {
        "pregunta_actual": 0,
        "respuestas": [],
        "puntuacion": 0,
        "preguntas": preguntas_seleccionadas,
        "bloque": bloque,
        "tema": tema,
        "cantidad": cantidad
    }
    
    bloque_nombre = {
        "1": "Bloque I",
        "2": "Bloque II",
        "3": "Bloque III",
        "4": "Bloque IV",
        "aleatorio": "Test Aleatorio"
    }
    
    await query.answer()
    await query.edit_message_text(
        f"🎯 **Test iniciado**\n\n"
        f"Bloque: {bloque_nombre.get(bloque, 'Desconocido')}\n"
        f"Preguntas: {cantidad}\n\n"
        f"_Cargando primera pregunta..._",
        parse_mode="Markdown"
    )
    
    # Mostrar primera pregunta
    await mostrar_pregunta(update, context, user_id)

# Función para mostrar preguntas
async def mostrar_pregunta(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Muestra la pregunta actual del test"""
    if user_id not in test_sessions:
        await update.message.reply_text("❌ No hay test activo. Usa /test para comenzar.")
        return
    
    sesion = test_sessions[user_id]
    num_pregunta = sesion["pregunta_actual"]
    preguntas_test = sesion["preguntas"]
    
    # Verificar si ya se respondieron todas las preguntas
    if num_pregunta >= len(preguntas_test):
        await finalizar_test(update, user_id)
        return
    
    pregunta = preguntas_test[num_pregunta]
    
    # Crear botones para las opciones
    keyboard = []
    for idx, opcion in enumerate(pregunta["opciones"]):
        keyboard.append([InlineKeyboardButton(opcion, callback_data=f"respuesta_{idx}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mensaje = f"""
📝 Pregunta {num_pregunta + 1}/{len(preguntas_test)}

{pregunta['pregunta']}
    """
    
    await update.message.reply_text(mensaje, reply_markup=reply_markup)


# Función para finalizar el test
async def finalizar_test(update: Update, user_id: int):
    """Finaliza el test y muestra los resultados"""
    sesion = test_sessions[user_id]
    total_preguntas = len(preguntas)
    respuestas_correctas = sesion["puntuacion"]
    porcentaje = (respuestas_correctas / total_preguntas) * 100 if total_preguntas > 0 else 0
    
    # Determinar mensaje motivador según el porcentaje
    if porcentaje == 100:
        emoji = "🏆"
        mensaje_motivador = "¡EXCELENTE! ¡Has acertado todas!"
    elif porcentaje >= 80:
        emoji = "🌟"
        mensaje_motivador = "¡MUY BIEN! Vas muy bien encaminado."
    elif porcentaje >= 60:
        emoji = "👍"
        mensaje_motivador = "Bien, sigue practicando para mejorar."
    else:
        emoji = "💪"
        mensaje_motivador = "Sigue intentando, la práctica hace al maestro."
    
    resultado = f"""
{emoji} **¡Test finalizado!**

**Resultados:**
• Respuestas correctas: {respuestas_correctas}/{total_preguntas}
• Porcentaje: {porcentaje:.1f}%

{mensaje_motivador}

💡 Usa /test para hacer otro test o /salir para terminar.
    """
    
    await update.message.reply_text(resultado, parse_mode="Markdown")
    
    # Limpiar sesión
    del test_sessions[user_id]
    logging.info(f"Test finalizado para usuario ID: {user_id}. Puntuación: {respuestas_correctas}/{total_preguntas}")


# Función para manejar respuestas del test
async def manejar_respuesta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las respuestas seleccionadas en el test"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in test_sessions:
        await query.answer("❌ No hay test activo", show_alert=True)
        return
    
    # Extraer el número de la respuesta seleccionada
    respuesta_idx = int(query.data.split("_")[1])
    sesion = test_sessions[user_id]
    num_pregunta = sesion["pregunta_actual"]
    preguntas_test = sesion["preguntas"]
    pregunta = preguntas_test[num_pregunta]
    
    # Verificar si la respuesta es correcta
    es_correcta = respuesta_idx == pregunta["respuesta_correcta"]
    if es_correcta:
        sesion["puntuacion"] += 1
        mensaje = "✅ ¡Correcto!"
    else:
        mensaje = f"❌ Incorrecto. La respuesta correcta era: {pregunta['opciones'][pregunta['respuesta_correcta']]}"
    
    sesion["respuestas"].append({
        "pregunta": num_pregunta,
        "respuesta_usuario": respuesta_idx,
        "respuesta_correcta": pregunta["respuesta_correcta"],
        "correcta": es_correcta
    })
    
    # Pasar a la siguiente pregunta
    sesion["pregunta_actual"] += 1
    
    await query.answer()
    await query.edit_message_text(text=f"{mensaje}\n\n⏳ Cargando siguiente pregunta...")
    
    # Mostrar siguiente pregunta después de un pequeño delay
    await mostrar_pregunta(update, context, user_id)


# Función de ayuda
@require_authorization
async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda - Muestra la ayuda del bot"""
    help_text = """
📚 **AYUDA - Bot de Tests Online**

**Comandos disponibles:**

/start - Inicia el bot y te da la bienvenida
/test - Comienza un nuevo test con todas las preguntas
/ayuda - Muestra esta ayuda
/salir - Termina el test actual

**¿Cómo usar el bot?**

1. Usa /test para comenzar un test
2. Lee cada pregunta cuidadosamente
3. Selecciona tu respuesta haciendo clic en uno de los botones
4. Continúa hasta responder todas las preguntas
5. Al final verás tu puntuación

**Controles:**
- Solo usuarios autorizados pueden usar este bot
- Puedes hacer el test tantas veces como quieras
- Se registra tu progreso en los logs del bot

¿Necesitas más ayuda? Contacta con el administrador.
    """
    
    await update.message.reply_text(help_text, parse_mode="Markdown")


# Función para salir/cancelar el test
@require_authorization
async def salir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /salir - Termina el test actual"""
    user_id = update.effective_user.id
    
    if user_id in test_sessions:
        del test_sessions[user_id]
        await update.message.reply_text("❌ Test cancelado. Usa /test para comenzar uno nuevo.")
    else:
        await update.message.reply_text("No hay test activo. Usa /test para comenzar.")


# Función principal - Configura el bot
async def main():
    """Función principal que configura y inicia el bot"""
    # Cargar preguntas al iniciar
    cargar_preguntas()
    
    # Crear la aplicación
    app = Application.builder().token(TOKEN).build()
    
    # Registrar handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("salir", salir))
    
    # Registrar handlers para botones de selección
    app.add_handler(CallbackQueryHandler(seleccionar_bloque, pattern="^bloque_"))
    app.add_handler(CallbackQueryHandler(seleccionar_tema, pattern="^tema_"))
    app.add_handler(CallbackQueryHandler(seleccionar_cantidad, pattern="^cantidad_"))
    
    # Registrar handler para respuestas de botones
    app.add_handler(CallbackQueryHandler(manejar_respuesta, pattern="^respuesta_"))
    
    # Iniciar el bot
    logging.info("Bot iniciado correctamente")
    await app.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
