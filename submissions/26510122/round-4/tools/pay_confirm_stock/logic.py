import httpx

def run(args, kit):
    pay=args['pay']
    tx=kit.pay(pay['to'],int(pay['wei']),pay.get('data','0x'),role='shop')
    r=httpx.post(kit.market+'/api/supply',headers={'authorization':'Bearer '+kit.token('shop')},json={'quote':args['quote'],'tx_hash':tx},timeout=30)
    return {'tx_hash':tx,'confirm':r.json()}
