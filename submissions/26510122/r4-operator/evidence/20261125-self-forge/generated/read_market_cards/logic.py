import httpx

def run(args, kit):
    url = args.get('url')
    if not isinstance(url, str) or not url.startswith('https://market.ourolabs.ai/'):
        return {'error':'invalid_url'}
    if kit.testing:
        return {'status_code':200,'text':'TEST_FIXTURE'}
    r = httpx.get(url, timeout=20)
    return {'status_code':r.status_code,'text':r.text,'content_type':r.headers.get('content-type','')}
