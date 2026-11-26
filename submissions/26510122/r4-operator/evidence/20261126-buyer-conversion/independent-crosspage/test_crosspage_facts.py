from pathlib import Path
from copy import deepcopy
import importlib.util,json,sys
OP=Path(__file__).resolve().parents[3];B=OP/'deploy/public_catalogue_runtime_v4d'
sys.path.insert(0,str(B));spec=importlib.util.spec_from_file_location('continuity_audit',B/'public_product_continuity.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def page(rows,snapshot='a'*64,asof=100):return {'snapshot':snapshot,'as_of':asof,'observed_at':100,'valid_until':250,'common':{},'columns':['sku','grade','preferred_price','private_injected'],'lookup':{},'rows':[[sku,grade,price,'SYNTHETIC_NOT_A_REAL_RIGHT'] for sku,grade,price in rows]}
A={'sku':'G00000001','grade':'A'};BB={'sku':'G00000002','grade':'B'};factsA={**A,'preferred_price':1000};factsB={**BB,'preferred_price':2000}
pages=[page([('G00000001','A',1000)]),page([('G00000002','B',2000)],asof=103)];checks=[];initial_pages=deepcopy(pages)
def check(name,ok):checks.append({'case':name,'pass':bool(ok)})
check('crosspage_A_B',m.page_facts(pages,[A,BB])==[factsA,factsB]);check('selection_order',m.page_facts(pages,[BB,A])==[factsB,factsA]);check('selected_only_no_private',m.page_facts(pages,[A])==[factsA]);check('input_unchanged',pages==initial_pages)
check('SHA_conflict',m.page_facts([pages[0],page([('G00000002','B',2000)],snapshot='b'*64)],[A,BB])==[])
check('price_conflict',m.page_facts([pages[0],page([('G00000001','A',1001)])],[A])==[])
check('same_pair_same_price_across_pages',m.page_facts([pages[0],deepcopy(pages[0])],[A])==[factsA])
check('same_pair_duplicate_within_page',m.page_facts([page([('G00000001','A',1000),('G00000001','A',1000)])],[A])==[])
check('missing_selected_all_or_none',m.page_facts([pages[0]],[A,BB])==[])
check('more_than_six_pages',m.page_facts([deepcopy(pages[0]) for _ in range(7)],[A])==[])
check('nine_rows_even_unselected_rejected',m.page_facts([page([('G00000001','A',1000)]+[(f'G{i:08x}','B',1000) for i in range(2,10)])],[A])==[])
check('bool_price',m.page_facts([page([('G00000001','A',True)])],[A])==[])
check('zero_price',m.page_facts([page([('G00000001','A',0)])],[A])==[])
check('different_query_asof_accepted',m.page_facts(pages,[A,BB])==[factsA,factsB])
check('six_pages_bound_accepted',m.page_facts([pages[0]]*5+[pages[1]],[A,BB])==[factsA,factsB])
from public_catalogue_protocol import CatalogueProtocol
from public_catalogue_snapshot_host import CatalogueError
try:CatalogueProtocol(lambda x:x).render({'items':[A,A]});reject=False
except CatalogueError:reject=True
check('duplicate_selection_closed_before_helper',reject)
result={'passed':sum(x['pass'] for x in checks),'failed':sum(not x['pass'] for x in checks),'cases':checks,'helper_precondition':'pages already protocol/SHA-verified by one ScopedPublicCatalogue, selections protocol-validated','actual_Model_DB_wallet_market_calls':0}
Path(__file__).with_name('crosspage-facts-results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));assert not result['failed']
