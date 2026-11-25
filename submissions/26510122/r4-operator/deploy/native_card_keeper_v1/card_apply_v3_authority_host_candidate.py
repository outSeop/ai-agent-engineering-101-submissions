"""Host binding for reviewed genuine refresh2/apply3; no renderer or selection."""
import json,re
from card_apply_authority_host import StageOrigin,sha

REFRESH_PIN='7199f31b471ac97275b94e167ba5ec2c7c7aa11bcc8c57a92e128426158dcd53'
POLICY_SKILLS={'mileage':'repeat-benefits','wait':'repeat-benefits','refund':'refund-review'}

def make_refresh_authority(origin,original_raw,fresh_raw,before_raw,active,active_id,policies,now):
    if not isinstance(origin,StageOrigin) or origin.source_sha256!=REFRESH_PIN or sha(origin.record_raw)!=origin.record_id or sha(original_raw)!=origin.view_sha256:
        raise ValueError('unrecognized same-run refresh provenance')
    stage,old,fresh,before=(json.loads(raw) for raw in (origin.record_raw,original_raw,fresh_raw,before_raw))
    after_raw=stage['after_card_json'].encode();after=json.loads(after_raw)
    if (not re.fullmatch('[a-f0-9]{64}',active_id) or active['after_sha256']!=sha(before_raw)
        or active['after_card_json'].encode()!=before_raw or tuple(active['skus'])!=origin.selected
        or stage['before_card_json'].encode()!=before_raw or stage['before_sha256']!=sha(before_raw)
        or stage['after_sha256']!=sha(after_raw) or stage['view_sha256']!=sha(original_raw)
        or tuple(stage['skus'])!=origin.selected or old['card_sha256']!=sha(before_raw)
        or fresh['card_sha256']!=sha(before_raw) or not old['observed_at']<fresh['observed_at']<=now
        or origin.mtime_ns>fresh['observed_at']*10**9 or sha(original_raw)==sha(fresh_raw)
        or old['replace_text']!=fresh['replace_text']):
        raise ValueError('refresh metadata binding changed')
    span=active['block'];description=before['description'];replacement=old['replace_text']
    start,end=span['start'],span['end']
    if (span['text']!=replacement or description[start:end]!=replacement or description.count(replacement)!=1
        or {k:v for k,v in before.items() if k!='description'}!={k:v for k,v in after.items() if k!='description'}):
        raise ValueError('protected card fields changed')
    prefix,suffix=description[:start],description[end:];new=after['description']
    if not new.startswith(prefix) or (suffix and not new.endswith(suffix)) or len(new)>1000:
        raise ValueError('surrounding public text changed')
    block=new[len(prefix):len(new)-len(suffix) if suffix else None]
    if not block.strip() or new.count(block)!=1:raise ValueError('ambiguous approved block')
    if not isinstance(policies,dict) or set(policies)!=set(POLICY_SKILLS):raise ValueError('reviewed policy anchors required')
    for key,clause in policies.items():
        rows=[row for row in before['skills'] if row.get('id')==POLICY_SKILLS[key]]
        if not isinstance(clause,str) or not clause.strip() or len(rows)!=1 or clause not in rows[0].get('description',''):
            raise ValueError('reviewed policy anchor missing')
        if description.count(clause)!=prefix.count(clause)+suffix.count(clause):raise ValueError('replacement overlaps policy anchor')
    for sku in origin.selected:
        first=[row for row in old['offers'] if row['sku']==sku];again=[row for row in fresh['offers'] if row['sku']==sku]
        if len(first)!=1 or first!=again or first[0]['state']!='available':raise ValueError('selected fresh facts changed')
    until=min(now+30,stage['valid_until'],old['valid_until'],fresh['valid_until'])
    if type(now) is not int or now>=until:raise ValueError('expired verified refresh')
    return {'schema':'outseop-r4.card-publication-authority.v1','shop':'outseop-r4','owner':'native','op':'apply',
      'record_id':origin.record_id,'head':active_id,'before_sha256':sha(before_raw),'after_sha256':sha(after_raw),'issued_at':now,'valid_until':until,
      'details':{'fresh_view_sha256':sha(fresh_raw),'replacement_sha256':sha(block.encode()),'policies':dict(policies)}}
