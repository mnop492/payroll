from app import app

for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    methods = ','.join(sorted(rule.methods))
    print(f"{rule.rule} -> {rule.endpoint} [{methods}]")
