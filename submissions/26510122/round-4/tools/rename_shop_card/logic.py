import json

def run(args, kit):
    name = args.get('name', '생활 상점')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('name must be non-empty')
    path = 'card.json'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            card = json.load(f)
    except FileNotFoundError:
        card = {}
    card['name'] = name.strip()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(card, f, ensure_ascii=False, indent=2)
    return {'ok': True, 'name': card['name']}
