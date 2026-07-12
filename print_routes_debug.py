import traceback

try:
    from app import app
    rules = list(app.url_map.iter_rules())
    with open('routes_output.txt', 'w', encoding='utf-8') as f:
        f.write(f'app type: {type(app)}\n')
        f.write(f'rule count: {len(rules)}\n')
        for r in sorted(rules, key=lambda x: x.rule):
            methods = ','.join(sorted(r.methods))
            f.write(f"{r.rule} -> {r.endpoint} [{methods}]\n")
except Exception as e:
    with open('routes_output.txt', 'w', encoding='utf-8') as f:
        f.write('IMPORT EXCEPTION:\n')
        f.write(traceback.format_exc())
