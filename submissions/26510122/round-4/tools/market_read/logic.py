import httpx

def run(args,kit):
    paths=args.get('paths',[])
    if args.get('shop_inventory'): paths=paths+['/api/inventory']
    out={}
    for p in paths:
        u=kit.market+p
        h={}
        if p=='/api/inventory': h['authorization']='Bearer '+kit.token('shop')
        r=httpx.get(u,headers=h,timeout=20)
        try: body=r.json()
        except: body=r.text
        out[p]={'status':r.status_code,'body':body}
    return out
