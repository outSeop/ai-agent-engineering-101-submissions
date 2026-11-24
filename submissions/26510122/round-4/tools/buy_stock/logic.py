import httpx

def run(args,kit):
    h={'authorization':'Bearer '+kit.token('shop')}
    sku=args['sku']; qty=int(args.get('qty',1))
    if args.get('quote_only',True):
        r=httpx.post(kit.market+'/api/supply',json={'sku':sku,'qty':qty},headers=h,timeout=30)
        try: b=r.json()
        except: b={'raw':r.text}
        if r.status_code==402 or r.status_code<300: return {'phase':'quote','status':r.status_code,'body':b}
        return {'phase':'quote','status':r.status_code,'body':b}
    q=args['quote']; p=q.get('pay',{})
    tx=kit.pay(p['to'],int(p['wei']),p.get('data','0x'),role='shop')
    r=httpx.post(kit.market+'/api/supply',json={'quote':q,'tx_hash':tx},headers=h,timeout=30)
    try: b=r.json()
    except: b={'raw':r.text}
    return {'phase':'confirmed','tx_hash':tx,'status':r.status_code,'body':b}
