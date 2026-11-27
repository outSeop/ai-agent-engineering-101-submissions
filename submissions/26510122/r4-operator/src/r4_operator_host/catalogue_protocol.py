"""HOST argument binding only; share all catalogue protocol code with the pinned base.

Repeated positive noun interpretation and all customer constraints belong to the
classroom-forged tool. This layer transports the complete original text unchanged.
"""
from pathlib import Path
from hashlib import sha256
import importlib.util,json
from card_source_read_lane import raw_file

context=json.loads(raw_file(Path(__file__).resolve().with_name('HOST-CONTEXT.json')))
if set(context)!={'schema','operator_root','base_protocol','base_protocol_sha256','base_manifest_sha256'} or context['schema']!='r4-host-context.v1':
    raise ValueError('unreviewed HOST context')
root=Path(context['operator_root']);relative=Path(context['base_protocol'])
if not root.is_absolute() or root.resolve(strict=True)!=root or relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='deploy':
    raise ValueError('base protocol outside operator deploy')
BASE=root/relative
BASE_SHA=context['base_protocol_sha256']
def load_base_host(name,leaf):
    if leaf not in {'public_catalogue_protocol.py','broker_public_catalogue_host_candidate.py'}:
        raise ValueError('unreviewed base HOST module')
    manifest_raw=raw_file(BASE.parent/'MANIFEST.json')
    if sha256(manifest_raw).hexdigest()!=context['base_manifest_sha256']:
        raise ValueError('base HOST manifest changed')
    pins=json.loads(manifest_raw)['file_sha256']
    if pins['public_catalogue_protocol.py']!=BASE_SHA:raise ValueError('base protocol pin disagrees with manifest')
    path=BASE.parent/leaf;raw=raw_file(path)
    if sha256(raw).hexdigest()!=pins[leaf]:raise ValueError('base HOST source changed')
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module
_base=load_base_host('_verified_catalogue_base_protocol','public_catalogue_protocol.py')
sku=_base.sku
CatalogueError=_base.CatalogueError

class CatalogueProtocol(_base.CatalogueProtocol):
    def semantic(self,text,args):
        if not self._public_text(text,1500) or not isinstance(args,dict):
            raise CatalogueError('action_rejected')
        if set(args)=={'groups'}:
            groups=args['groups']
            if (not isinstance(groups,list) or not 1<=len(groups)<=2
                    or any(not isinstance(group,dict) or set(group)!={'product_phrase','queries'} for group in groups)):
                raise CatalogueError('action_rejected')
            checked=[self.semantic(text,group) for group in groups]
            spans=[(text.index(group['product_phrase']),text.index(group['product_phrase'])+len(group['product_phrase'])) for group in checked]
            if len(spans)==2 and max(spans[0][0],spans[1][0])<min(spans[0][1],spans[1][1]):
                raise CatalogueError('action_rejected')
            return {'text':text,'groups':[{key:group[key] for key in ('product_phrase','queries')} for group in checked]}
        if set(args)!={'product_phrase','queries'}:
            raise CatalogueError('action_rejected')
        phrase=args['product_phrase']
        if not self._public_text(phrase,48) or phrase!=phrase.strip() or phrase not in text:
            raise CatalogueError('action_rejected')
        queries=args['queries']
        if (not isinstance(queries,list) or not 1<=len(queries)<=2
                or any(not self._public_text(q,48) or q!=q.strip() for q in queries)
                or len({q.casefold() for q in queries})!=len(queries)):
            raise CatalogueError('action_rejected')
        return {'text':text,'product_phrase':phrase,'queries':list(queries)}

    def result(self,op,result,observed,valid):
        # Only typed, non-authorizing tool metadata is added to the original ABI.
        extras={}
        if op=='semantic_candidates' and isinstance(result,dict):
            if 'payment_request' in result:
                hold=result['payment_request']
                if (not isinstance(hold,dict) or set(hold)!={'status','reason'}
                    or hold['status']!='not_issued'
                    or not isinstance(hold['reason'],str) or hold['reason'] not in {'product_selection_required','financial_verification_required'}):
                    raise CatalogueError('semantic_candidates_failed')
                extras['payment_request']=dict(hold)
            if 'public_facts' in result:
                facts=result['public_facts']
                if not isinstance(facts,list) or not 1<=len(facts)<=3:raise CatalogueError('semantic_candidates_failed')
                for fact in facts:
                    if (not isinstance(fact,dict) or set(fact)!={'sku','grade','preferred_price'}
                        or not sku(fact['sku']) or not isinstance(fact['grade'],str) or fact['grade'] not in {'A','B','C'}
                        or type(fact['preferred_price']) is not int or fact['preferred_price']<=0):
                        raise CatalogueError('semantic_candidates_failed')
                extras['public_facts']=[dict(f) for f in facts]
        plain={k:v for k,v in result.items() if k not in extras} if isinstance(result,dict) else result
        checked=super().result(op,plain,observed,valid)
        return {**checked,**extras}
