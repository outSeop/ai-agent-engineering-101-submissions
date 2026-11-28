"""HOST argument binding only; share all catalogue protocol code with the pinned base.

Repeated positive noun interpretation and all customer constraints belong to the
native SDK tool. This layer transports the complete original text unchanged.
"""
from pathlib import Path
from hashlib import sha256
import importlib.util,json
from card_source_read_lane import raw_file

context=json.loads(raw_file(Path(__file__).resolve().with_name('HOST-CONTEXT.json')))
_CONTEXT_KEYS={'schema','operator_root','base_protocol','base_protocol_sha256','base_manifest_sha256'}
if (set(context)-{'native_tools'} != _CONTEXT_KEYS or context['schema']!='r4-host-context.v1'
        or not isinstance(context.get('native_tools',{}),dict)):
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
    def alternatives_request(self,text,*,args=None,menu=None):
        if not self._public_text(text,1500):
            raise CatalogueError('action_rejected')
        if args is None and menu is None:
            return {'op':'context','text':text}
        if args is None or menu is None:
            raise CatalogueError('action_rejected')
        selected=self.render(args)['items']
        pairs=[(item['sku'].upper(),item['grade']) for item in selected]
        eligible={(item['sku'].upper(),item['grade']) for item in menu['items']}
        if len(set(pairs))!=len(pairs) or not set(pairs)<=eligible:
            raise CatalogueError('action_rejected')
        return {'op':'render','text':text,'snapshot':menu['snapshot'],'items':selected}

    def alternatives_result(self,op,result,observed,valid,snapshot):
        if (isinstance(result,dict) and set(result)=={'status','reason'}
                and result['status']=='unavailable'):
            reason=result['reason']
            allowed={'unsupported_inquiry','unsupported_request','no_match','stale_snapshot',
                     'snapshot_changed','selection_unavailable','selection_ambiguous',
                     'invalid_snapshot','source_unavailable','invalid_args','relation_unverified',
                     'unknown_relation','original_available','output_budget','original_match',
                     'clarification_required','no_verified_options','invalid_selection','unsafe_label',
                     'invalid_request','reply_limit'}
            raise CatalogueError(reason if isinstance(reason,str) and reason in allowed else 'alternatives_failed')
        if op=='render':
            return self.result('semantic_candidates',result,observed,valid)
        if (op!='context' or not isinstance(result,dict)
                or set(result)!={'status','snapshot','observed_at','valid_until','items'}
                or result['status']!='options' or result['snapshot']!=snapshot
                or type(result['observed_at']) is not int or result['observed_at']!=observed
                or type(result['valid_until']) is not int or result['valid_until']!=valid):
            raise CatalogueError('alternatives_failed')
        items=result['items']
        if (not isinstance(items,list) or not 1<=len(items)<=12
                or len(json.dumps(result,ensure_ascii=False,allow_nan=False))>5500):
            raise CatalogueError('alternatives_failed')
        keys=set()
        for item in items:
            if (not isinstance(item,dict) or set(item)!={'sku','name','category','grade','preferred_price','expires_at'}
                    or not sku(item['sku']) or item['grade'] not in ('A','B','C')
                    or not self._public_text(item['name'],1024)
                    or item['category'] is not None and not self._public_text(item['category'],128)
                    or type(item['preferred_price']) is not int or not 1<=item['preferred_price']<=10**12
                    or item['expires_at'] is not None and (
                        type(item['expires_at']) is not int or item['expires_at']<=observed)):
                raise CatalogueError('alternatives_failed')
            key=(item['sku'].upper(),item['grade'])
            if key in keys:
                raise CatalogueError('alternatives_failed')
            keys.add(key)
        return result

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
