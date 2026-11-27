"""HOST argument binding only; share all catalogue protocol code with the pinned base.

Repeated positive noun interpretation and all customer constraints belong to the
classroom-forged tool. This layer transports the complete original text unchanged.
"""
from pathlib import Path
from hashlib import sha256
import importlib.util
from card_source_read_lane import raw_file

BASE=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator/deploy/public_catalogue_runtime_compound_v1/public_catalogue_protocol.py')
BASE_SHA="b9a2b94499bbd02f8bb8e59e729c869d14ecd59de02712a91abf77952134ebde"
raw=raw_file(BASE)
if sha256(raw).hexdigest()!=BASE_SHA:
    raise ValueError('catalogue base protocol changed')
spec=importlib.util.spec_from_file_location('_verified_catalogue_base_protocol',BASE)
_base=importlib.util.module_from_spec(spec)
exec(compile(raw,str(BASE),'exec'),_base.__dict__)
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
