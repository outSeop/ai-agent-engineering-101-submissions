import httpx

def run(args, kit):
    urls=args.get('urls') or [kit.market+'/.well-known/agent-card.json']
    out=[]
    for u in urls:
        r=httpx.get(u,timeout=20)
        out.append({'url':u,'status':r.status_code,'body':r.json() if 'application/json' in r.headers.get('content-type','') else r.text})
    return {'cards':out}
