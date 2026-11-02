"""First-pass LLM benchmark for decision 0005 (orchestrator candidates on the author's laptop).

Usage: python bench.py <host:port> <backend-label> <model> [<model> ...]
Writes one JSON line per call to results.jsonl next to this file.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LISTS = json.load(open(os.path.join(HERE, 'lists.json'), encoding='utf-8'))
UNITS = ['ud', 'kg', 'g', 'l', 'ml']

ITEM_SCHEMA = {
    'type': 'object',
    'properties': {
        'items': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'item': {'type': 'string'},
                    'quantity': {'type': 'number'},
                    'unit': {'type': 'string', 'enum': UNITS},
                    'brand': {'type': ['string', 'null']},
                    'attributes': {'type': 'array', 'items': {'type': 'string'}},
                    'ambiguous': {'type': 'boolean'},
                },
                'required': ['item', 'quantity', 'unit', 'ambiguous'],
            },
        }
    },
    'required': ['items'],
}

SYSTEM_A = (
    'Eres el intérprete de listas de la compra de un recomendador de supermercados en España. '
    'Convierte la lista del usuario en artículos. Para cada artículo da: item (nombre genérico en español, '
    'sin cantidad), quantity (número), unit (ud, kg, g, l o ml; usa ud si no se indica), brand (solo si el '
    'usuario la pide), attributes (por ejemplo sin lactosa, integral, sin gluten) y ambiguous (true si el '
    'artículo es vago, como "algo para la cena"). Responde solo con el JSON pedido.'
)

TOOL = {
    'type': 'function',
    'function': {
        'name': 'search_products',
        'description': 'Busca en el catálogo los productos equivalentes a un artículo de la lista.',
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Nombre genérico del artículo'},
                'quantity': {'type': 'number'},
                'unit': {'type': 'string', 'enum': UNITS},
                'attributes': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['query', 'quantity', 'unit'],
        },
    },
}

SYSTEM_B = (
    'Eres el agente de un recomendador de supermercados. Para cada artículo de la lista del usuario, '
    'llama a la herramienta search_products una vez, con el nombre genérico, la cantidad y la unidad.'
)

EXPLAIN_PROMPT = (
    'Explica en español, en unas 120 palabras y en tono cercano, esta recomendación de compra. No inventes cifras: '
    'usa solo las dadas. Cesta: Mercadona (leche, huevos, pan, aceite) 14,20 €; Lidl (fruta, yogures, café) 9,85 €. '
    'Total 24,05 €. Comprando todo en la tienda más barata cercana serían 27,60 €: ahorro de 3,55 €. '
    'Tiempo extra a pie: 9 minutos. Sustituciones: café molido de marca por Bellarom (marca blanca de Lidl).'
)


def call(host, payload):
    try:
        return _call(host, payload)
    except Exception as e:
        return {'message': {'content': ''}, '_wall': None, '_error': repr(e)[:200]}


def _call(host, payload):
    req = urllib.request.Request(f'http://{host}/api/chat', data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=400) as r:
        data = json.loads(r.read().decode('utf-8'))
    data['_wall'] = time.perf_counter() - t0
    return data


def base(model, messages, **extra):
    p = {'model': model, 'messages': messages, 'stream': False, 'keep_alive': '10m',
         'options': {'temperature': 0, 'seed': 42, 'num_predict': 1500}}
    if model.startswith(('qwen', 'gemma')):
        p['think'] = False
    p.update(extra)
    return p


def norm(s):
    s = unicodedata.normalize('NFKD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return set(t for t in re.findall(r'[a-z0-9]+', s) if t not in {'de', 'para', 'el', 'la', 'en', 'con', 'x'})


def match(pred, gold):
    a, b = norm(pred), norm(gold)
    if not a or not b:
        return False
    return len(a & b) / len(b) >= 0.5 or len(a & b) / len(a) >= 0.5


def valid_items(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get('items'), list):
        return False
    for it in obj['items']:
        if not isinstance(it, dict):
            return False
        if not isinstance(it.get('item'), str) or not isinstance(it.get('quantity'), (int, float)):
            return False
        if it.get('unit') not in UNITS or not isinstance(it.get('ambiguous'), bool):
            return False
    return True


def score(pred_items, gold):
    used, tp, qty_ok = set(), 0, 0
    for g in gold:
        for i, p in enumerate(pred_items):
            if i not in used and match(p.get('item', ''), g['item']):
                used.add(i)
                tp += 1
                if abs(float(p.get('quantity', 0)) - g['quantity']) < 1e-6 and p.get('unit') == g['unit']:
                    qty_ok += 1
                break
    prec = tp / len(pred_items) if pred_items else 0.0
    rec = tp / len(gold)
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {'tp': tp, 'pred': len(pred_items), 'gold': len(gold), 'f1': round(f1, 3),
            'qty_unit_ok': qty_ok}


def timing(d):
    pe, pd = d.get('prompt_eval_count', 0), d.get('prompt_eval_duration', 0) / 1e9
    ec, ed = d.get('eval_count', 0), d.get('eval_duration', 0) / 1e9
    return {'prompt_tokens': pe, 'prompt_s': round(pd, 2), 'prompt_tps': round(pe / pd, 1) if pd else None,
            'gen_tokens': ec, 'gen_s': round(ed, 2), 'gen_tps': round(ec / ed, 1) if ed else None,
            'load_s': round(d.get('load_duration', 0) / 1e9, 2),
            'wall_s': round(d['_wall'], 2) if d.get('_wall') else None, 'error': d.get('_error'),
            'truncated': d.get('done_reason') == 'length'}


def main():
    host, backend, models = sys.argv[1], sys.argv[2], sys.argv[3:]
    out = open(os.path.join(HERE, 'results.jsonl'), 'a', encoding='utf-8')
    for model in models:
        call(host, base(model, [{'role': 'user', 'content': 'Hola'}]))  # warm-up, discarded
        for lst in LISTS:
            msgs = [{'role': 'system', 'content': SYSTEM_A}, {'role': 'user', 'content': lst['text']}]
            d = call(host, base(model, msgs, format=ITEM_SCHEMA))
            raw = d['message'].get('content', '')
            try:
                obj = json.loads(raw)
                ok = valid_items(obj)
            except Exception:
                obj, ok = None, False
            rec = {'backend': backend, 'model': model, 'task': 'interpret', 'list': lst['id'], 'valid_json': ok}
            rec.update(score(obj['items'], lst['gold']) if ok else {'f1': 0.0})
            rec.update(timing(d))
            out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush()
            print(rec, flush=True)
        for lst in [l for l in LISTS if l['id'] in ('L1', 'L2', 'L5', 'L8')]:
            msgs = [{'role': 'system', 'content': SYSTEM_B}, {'role': 'user', 'content': lst['text']}]
            d = call(host, base(model, msgs, tools=[TOOL]))
            calls = d['message'].get('tool_calls') or []
            good = 0
            for c in calls:
                args = c.get('function', {}).get('arguments')
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = None
                if isinstance(args, dict) and isinstance(args.get('query'), str) \
                        and isinstance(args.get('quantity'), (int, float)) and args.get('unit') in UNITS:
                    good += 1
            rec = {'backend': backend, 'model': model, 'task': 'tools', 'list': lst['id'],
                   'tool_calls': len(calls), 'valid_calls': good, 'gold': len(lst['gold'])}
            rec.update(timing(d))
            out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush()
            print(rec, flush=True)
        for rep in range(2):
            d = call(host, base(model, [{'role': 'user', 'content': EXPLAIN_PROMPT}]))
            rec = {'backend': backend, 'model': model, 'task': 'explain', 'rep': rep,
                   'text': d['message'].get('content', '')[:600]}
            rec.update(timing(d))
            out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush()
            print({k: v for k, v in rec.items() if k != 'text'}, flush=True)
        call(host, {'model': model, 'messages': [], 'keep_alive': 0, 'stream': False})  # unload


if __name__ == '__main__':
    main()
