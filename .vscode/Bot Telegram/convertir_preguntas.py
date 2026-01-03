"""
Script básico para convertir un par de archivos:
 - preguntas_temaX_bloqueY.odt  (documento con preguntas y opciones)
 - respuestas_temaX_bloqueY.ods (hoja de cálculo con respuestas)

Salida: escribe `tests/temaX_bloqueY.json` con estructura:
{ "preguntas": [ { "id": ..., "pregunta": ..., "opciones": [...], "respuesta_correcta": index }, ... ] }

Notas: el parser es heurístico. Sube un ejemplo real para que lo adaptemos.
"""

import sys
import os
import re
import json

try:
    from odf.opendocument import load
    from odf import text as odftext
    from odf import teletype
except Exception:
    load = None

try:
    from pyexcel_ods3 import get_data
except Exception:
    get_data = None


def extract_text_from_odt(path):
    if load is None:
        raise RuntimeError("odfpy no está instalado. Ejecuta: pip install odfpy")
    doc = load(path)
    paras = doc.getElementsByType(odftext.P)
    lines = [teletype.extractText(p).strip() for p in paras if teletype.extractText(p).strip()]
    # Algunas veces el documento tiene saltos separados; también devolveremos texto completo
    full = "\n".join(lines)
    return full


def split_questions_from_text(text):
    """Heurística simple: detecta líneas que empiezan por número + '.' o número + ')'"""
    lines = text.splitlines()
    q_blocks = []
    current = None
    for ln in lines:
        m = re.match(r'^\s*(\d{1,3})[\.|\)]\s*(.*)', ln)
        if m:
            # nueva pregunta
            if current:
                q_blocks.append(current)
            current = m.group(2).strip()
        else:
            if current is None:
                # líneas antes del primer número — ignorar o tratar como prefacio
                continue
            else:
                current += '\n' + ln.strip()
    if current:
        q_blocks.append(current)
    return q_blocks


def extract_options_and_question(block):
    """Intenta separar la pregunta del bloque y extraer opciones.
    Opciones esperadas como líneas que empiezan con A), A., a), a.", 'A -' etc.
    """
    lines = block.splitlines()
    question_lines = []
    options = []
    opt_pattern = re.compile(r'^\s*([A-Da-d]|\d+)\s*[\)\.|\-:]\s*(.+)')
    for ln in lines:
        m = opt_pattern.match(ln)
        if m:
            opt_text = m.group(2).strip()
            options.append(opt_text)
        else:
            # Si detectamos que la línea contiene varias opciones separadas por ; o — intentar dividir
            if ';' in ln and (re.search(r'\bA\)', ln) is None):
                parts = [p.strip() for p in ln.split(';') if p.strip()]
                if len(parts) >= 2 and all(len(p.split()) < 40 for p in parts):
                    options.extend(parts)
                else:
                    question_lines.append(ln)
            else:
                question_lines.append(ln)
    question_text = ' '.join(question_lines).strip()
    # Si no encontramos opciones, intentar extraer con patrón 'opciones:'
    if not options:
        m = re.search(r'Opciones[:\-]\s*(.+)', block, re.IGNORECASE)
        if m:
            parts = [p.strip() for p in re.split('[;\n]', m.group(1)) if p.strip()]
            options = parts
    return question_text, options


def read_answers_from_ods(path):
    if get_data is None:
        raise RuntimeError("pyexcel_ods3 no está instalado. Ejecuta: pip install pyexcel-ods3")
    data = get_data(path)
    # Tomar la primera hoja
    first_sheet = next(iter(data.keys()))
    rows = data[first_sheet]
    if not rows:
        return []
    # Detectar si la primera fila es encabezado con 'id' o 'respuesta'
    headers = [str(c).strip().lower() for c in rows[0]]
    mapping_by_id = False
    id_col = None
    ans_col = None
    if 'id' in headers and ('respuesta' in headers or 'respuesta_correcta' in headers or 'answer' in headers):
        mapping_by_id = True
        id_col = headers.index('id')
        if 'respuesta' in headers:
            ans_col = headers.index('respuesta')
        elif 'respuesta_correcta' in headers:
            ans_col = headers.index('respuesta_correcta')
        elif 'answer' in headers:
            ans_col = headers.index('answer')
    # Construir lista de respuestas; si mapping_by_id -> dict, else list by order (skipping header)
    if mapping_by_id:
        m = {}
        for r in rows[1:]:
            if len(r) <= max(id_col, ans_col):
                continue
            pid = r[id_col]
            ans = r[ans_col]
            if pid is None:
                continue
            m[str(pid).strip()] = ans
        return m
    else:
        # Asumir que cada fila representa la respuesta para la pregunta en el mismo orden.
        answers = []
        # Si la primera fila parece header (contiene texto) y no números/letters, podríamos saltarla
        start_idx = 0
        if any(isinstance(c, str) and re.search(r'[a-zA-Z]', c) for c in rows[0]):
            # intentar detectar si primera fila es header de texto; si sí y contiene palabras como 'id' o 'respuesta'
            if any(str(c).strip().lower() in ('id','respuesta','respuesta_correcta','answer') for c in rows[0]):
                start_idx = 1
        for r in rows[start_idx:]:
            if not r:
                answers.append(None)
                continue
            # tomar la primera celda no vacía
            val = r[0]
            answers.append(val)
        return answers


def answer_value_to_index(val, options_len):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    # letra A,B,C or a,b,c
    m = re.match(r'^([A-Za-z])$', s)
    if m:
        ch = m.group(1).upper()
        idx = ord(ch) - ord('A')
        if 0 <= idx < options_len:
            return idx
    # number
    m = re.match(r'^(\d+)$', s)
    if m:
        n = int(m.group(1))
        # puede ser 0-based o 1-based; preferir 1-based (si n==0 improbable)
        if 0 <= n < options_len:
            return n
        if 1 <= n <= options_len:
            return n - 1
    # texto that matches one of the options exactly
    for i, opt in enumerate(options_cache if 'options_cache' in globals() else []):
        if s.lower() == str(opt).strip().lower():
            return i
    return None


def convertir(preguntas_path, respuestas_path=None, out_dir=None):
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(__file__), 'tests')
    os.makedirs(out_dir, exist_ok=True)

    base = os.path.basename(preguntas_path)
    stem = re.sub(r'\.odt$', '', base, flags=re.IGNORECASE)
    # Extraer tema/bloque del nombre si está
    tema = None
    bloque = None
    m = re.search(r'tema(\d+)_bloque(\d+)', stem, re.IGNORECASE)
    if m:
        tema = int(m.group(1))
        bloque = int(m.group(2))

    print(f"Extrayendo texto de: {preguntas_path}")
    text = extract_text_from_odt(preguntas_path)
    q_blocks = split_questions_from_text(text)
    preguntas_list = []
    for idx, block in enumerate(q_blocks, start=1):
        q_text, options = extract_options_and_question(block)
        qid = idx
        pregunta_obj = {
            'id': qid,
            'pregunta': q_text,
            'opciones': options,
        }
        preguntas_list.append(pregunta_obj)

    answers_map = None
    if respuestas_path:
        print(f"Leyendo respuestas de: {respuestas_path}")
        ans = read_answers_from_ods(respuestas_path)
        answers_map = ans

    # Mapear respuestas
    for i, p in enumerate(preguntas_list):
        options_len = len(p['opciones'])
        mapped = None
        if isinstance(answers_map, dict):
            # buscar por id
            key = str(p['id'])
            val = answers_map.get(key)
            mapped = answer_value_to_index(val, options_len) if val is not None else None
        elif isinstance(answers_map, list):
            if i < len(answers_map):
                val = answers_map[i]
                # opción: permitir que la función use opciones
                # usar variable global temporal para matching exacto
                globals()['options_cache'] = p['opciones']
                mapped = answer_value_to_index(val, options_len)
                if 'options_cache' in globals():
                    del globals()['options_cache']
        # Si no mapeado, dejar 0 y advertir
        if mapped is None:
            mapped = 0
            print(f"Advertencia: no se pudo mapear respuesta para pregunta id={p['id']}, se asigna 0 por defecto")
        p['respuesta_correcta'] = mapped

    # Opcional: no incluir bloque/tema en el JSON, lo añadimos en procesar_preguntas.py
    out_name = stem + '.json'
    out_path = os.path.join(out_dir, out_name)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'preguntas': preguntas_list}, f, ensure_ascii=False, indent=2)

    print(f"Generado: {out_path} ({len(preguntas_list)} preguntas)")
    return out_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python convertir_preguntas.py preguntas_temaX_bloqueY.odt [respuestas_temaX_bloqueY.ods]")
        sys.exit(1)
    preguntas = sys.argv[1]
    respuestas = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        convertir(preguntas, respuestas)
    except Exception as e:
        print(f"Error: {e}")
