import json
import os

TESTS_DIR = os.path.join(os.path.dirname(__file__), "tests")

required_fields = ["pregunta", "opciones", "respuesta_correcta"]

errors = []

for fname in sorted(os.listdir(TESTS_DIR)):
    if not fname.endswith('.json'):
        continue
    path = os.path.join(TESTS_DIR, fname)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        errors.append((fname, f"JSON load error: {e}"))
        continue

    if not isinstance(data, list):
        errors.append((fname, 'Top-level JSON value is not a list'))
        continue

    for i, q in enumerate(data, start=1):
        if not isinstance(q, dict):
            errors.append((fname, f'Item {i} is not an object'))
            continue
        for field in required_fields:
            if field not in q:
                errors.append((fname, f'Item {i} missing field: {field}'))
        # opciones must be a list with at least 2 items
        opciones = q.get('opciones')
        if not isinstance(opciones, list) or len(opciones) < 2:
            errors.append((fname, f'Item {i} opciones must be a list with >=2 items'))
        # respuesta_correcta must be int index within opciones range
        rc = q.get('respuesta_correcta')
        if not isinstance(rc, int):
            errors.append((fname, f'Item {i} respuesta_correcta must be an int index'))
        else:
            if isinstance(opciones, list) and not (0 <= rc < len(opciones)):
                errors.append((fname, f'Item {i} respuesta_correcta index out of range'))

# Print summary
if not errors:
    print('OK: All test files validated successfully.')
else:
    print('Validation found issues:')
    for fname, msg in errors:
        print(f'- {fname}: {msg}')
    print(f"\nTotal issues: {len(errors)}")
