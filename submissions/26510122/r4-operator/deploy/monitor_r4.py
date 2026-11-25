"""Read-only R4 operations snapshot; never quote, procure, sign, settle or pay."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import sqlite3
import subprocess
import time
import urllib.request

NAME='outseop-r4'
WALLET='0x5fdc134d790efb72df1bbb922f2b49fcade349c6'
MARKET='https://market.ourolabs.ai'


def fetch(path,token=None):
    headers={'authorization':'Bearer '+token} if token else {}
    req=urllib.request.Request(path if path.startswith('https://') else MARKET+path,headers=headers)
    with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)


def unit_state(name):
    result=subprocess.run(['systemctl','--user','show',name,
        '--property=ActiveState,SubState,MainPID,NRestarts,MemoryCurrent,MemoryPeak,TasksCurrent,ActiveEnterTimestamp,ActiveEnterTimestampMonotonic'],
        capture_output=True,text=True,timeout=10)
    return dict(l.split('=',1) for l in result.stdout.splitlines() if '=' in l)


def tail_json(path,limit=16*1024*1024):
    if not path.exists():return [],True
    with path.open('rb') as handle:
        size=path.stat().st_size;start=max(0,size-limit);handle.seek(start)
        if start:handle.readline()
        lines=handle.read().decode('utf-8',errors='replace').splitlines()
    rows=[]
    for line in lines:
        try:rows.append(json.loads(line))
        except (ValueError,TypeError):continue
    return rows,start==0


def ledger_metrics(path,now,credit):
    if not path.exists():return {'available':False}
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
        db.execute('PRAGMA query_only=ON');db.row_factory=sqlite3.Row
        tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        out={'available':True,'quick_check':db.execute('PRAGMA quick_check').fetchone()[0]}
        if 'sale' in tables:
            out['sale_states']=dict(db.execute('SELECT status,count(*) FROM sale GROUP BY status').fetchall())
            out['signed_unsettled_over_5m']=db.execute("SELECT count(*) FROM sale WHERE status IN ('issued','paid','cancel_requested') AND created<?",(now-300,)).fetchone()[0]
            period=[]
            for start,end in ((now-1800,now),(now-3600,now-1800)):
                rows=db.execute("SELECT cost,price,expected_wei,owner FROM sale WHERE status IN ('settled','refunded') AND settled>=? AND settled<?",(start,end)).fetchall()
                total_in=sum(Decimal(x['expected_wei'])/credit for x in rows)
                first=db.execute("SELECT count(*) FROM (SELECT owner,min(settled) t FROM sale WHERE settled IS NOT NULL GROUP BY owner) WHERE t>=? AND t<?",(start,end)).fetchone()[0]
                period.append({'seconds':1800,'settlements':len(rows),'first_settlements':first,
                    'sales_price':sum(x['price'] for x in rows),'verified_sale_inflow':float(total_in),
                    'sold_unit_cost':sum(x['cost'] for x in rows),
                    'cash_margin_before_refunds_storage_unredeemed_benefits':float(total_in-sum(x['cost'] for x in rows))})
            out['last_30m'],out['previous_30m']=period
        if 'refund' in tables:
            out['refund_states']=dict(db.execute('SELECT status,count(*) FROM refund GROUP BY status').fetchall())
            out['confirmed_refund_outflow_credits']=float(sum(Decimal(x[0])/credit for x in db.execute("SELECT wei FROM refund WHERE status='refunded'")))
        if 'ticket' in tables:
            out['live_waiting_tickets']=db.execute("SELECT count(*) FROM ticket WHERE status='waiting' AND expires>?",(now,)).fetchone()[0]
            out['used_wait_tickets']=db.execute("SELECT count(*) FROM ticket WHERE status='used'").fetchone()[0]
        if {'lot','allocation'}<=tables:
            out['unexpired_mileage_liability']=db.execute("""SELECT coalesce(sum(max(0,l.amount-coalesce((SELECT sum(a.amount) FROM allocation a WHERE a.lot_id=l.sale_id AND a.status IN ('spent','offset')),0))),0) FROM lot l WHERE l.revoked IS NULL AND l.expires>?""",(now,)).fetchone()[0]
        if 'stock_intent' in tables:
            out['procurement_states']=dict(db.execute('SELECT state,count(*) FROM stock_intent GROUP BY state').fetchall())
            out['procurement_unknown']=db.execute("SELECT count(*) FROM stock_intent WHERE state IN ('sending','unknown')").fetchone()[0]
            out['confirmed_arrival_units']=db.execute("SELECT coalesce(sum(qty),0) FROM stock_intent WHERE state='arrived'").fetchone()[0]
        if 'forum_publication' in tables:
            out['forum_states']=dict(db.execute('SELECT status,count(*) FROM forum_publication GROUP BY status').fetchall())
            out['forum_posted_last_30m']=db.execute("SELECT count(*) FROM forum_publication WHERE status='posted' AND created>=?",(now-1800,)).fetchone()[0]
            out['forum_unresolved']=db.execute("SELECT count(*) FROM forum_publication WHERE status IN ('sending','unknown')").fetchone()[0]
        if 'promotion_loss' in tables:
            out['promotion_signed_exposures']=db.execute("SELECT count(*) FROM promotion_loss").fetchone()[0]
            out['promotion_committed_loss_credits']=db.execute("SELECT coalesce(sum(amount),0) FROM promotion_loss").fetchone()[0]
        if 'sale' in tables:
            out['c_settlements_last_30m']=db.execute("SELECT count(*) FROM sale WHERE grade='C' AND status IN ('settled','refunded') AND settled>=?",(now-1800,)).fetchone()[0]
        if 'stock_audit' in tables:
            out['recent_procurement_events']=[{'at':x[0],'event':x[1]} for x in db.execute('SELECT at,event FROM stock_audit ORDER BY id DESC LIMIT 12')]
        return out


def main():
    p=argparse.ArgumentParser();p.add_argument('--operator',type=Path,required=True)
    p.add_argument('--publish',type=Path);args=p.parse_args()
    os.umask(0o077)
    op=args.operator.resolve();root=op.parent/'round-4';dest=op/'runtime/operations';dest.mkdir(mode=0o700,exist_ok=True)
    now=time.time();out={'at':now,'time_utc':datetime.fromtimestamp(now,timezone.utc).isoformat(),'errors':[],
        'scope':'Read-only actual operation. Quotes, approvals, supply acceptance and physical arrivals are separate; rank has no published score.'}
    out['services']={n:unit_state(n) for n in ['ourolabs-market-r4.service','ourolabs-market-r4-worker.service','outseop-r3-buyer.service','outseop-r3-seller.service']}
    main_service=out['services']['ourolabs-market-r4.service']
    entered=main_service.get('ActiveEnterTimestampMonotonic','0')
    uptime=max(0,time.monotonic()-int(entered)/1e6) if main_service.get('ActiveState')=='active' and entered.isdigit() and int(entered)>0 else None
    out['main_uptime_seconds']=round(uptime,1) if uptime is not None else None
    out['equal_30m_windows_fully_live']=uptime is not None and uptime>=3600
    out['comparison_note']='Both half-hour windows are fully inside this continuous run.' if out['equal_30m_windows_fully_live'] else 'Prior windows may include downtime/startup; do not claim recovery or improvement from zero baselines.'
    try:
        registry=fetch('/api/agents');own=[a for a in registry.get('agents',[]) if a.get('name')==NAME]
        out['registered_matches']=len(own);out['round']=registry.get('round')
        if len(own)==1:
            card=fetch(own[0]['card']);out['card']={'name':card.get('name'),'description':card.get('description'),
                'wallet_preserved':str(card.get('wallets',{}).get('shop','')).lower()==WALLET}
    except Exception as e:out['errors'].append({'stage':'public_registry_card','type':type(e).__name__})
    try:
        board=fetch('/api/board');out['ranks_only']=board.get('ranks_only')
        for index,row in enumerate(board.get('shops',[]),1):
            if row.get('name')==NAME:out['shop_rank']=row.get('rank',index);out['listed_alive']=row.get('alive')
    except Exception as e:out['errors'].append({'stage':'public_board','type':type(e).__name__})
    try:
        village=fetch('/api/village')
        out['village']={k:village.get(k) for k in ('day','weekday','part','weather','market_day','payday','households','wanting_to_come')}
        out['village']['in_town_count']=len(village.get('in_town',[]))
    except Exception as e:out['errors'].append({'stage':'public_village_aggregate','type':type(e).__name__})
    credit=Decimal(10**15)
    try:
        chain=fetch('/api/chain');credit=Decimal(chain['credit_wei'])
        token_path=root/'.kit/worker-token'
        if not token_path.exists():
            session=Path((op/'runtime/r3-stock-latest-path.txt').read_text().strip())
            token=json.loads((session/'model-session.json').read_text())['token']
        else:token=token_path.read_text().strip()
        inv=fetch('/api/inventory',token)
        assert inv['round']==4 and inv['wallet'].lower()==WALLET,'inventory identity changed'
        units=inv['units'];out['inventory']={'cash_floor_credits':inv['balance'],
            'cash_precise_credits':float(Decimal(str(inv['tokrw']))*10**18/credit) if inv.get('tokrw') is not None else None,
            'units':len(units),'skus':len({u['sku'] for u in units}),'cost':sum(u['cost'] for u in units),
            'grades':dict(Counter(u['grade'] for u in units)),
            'expires_within_2h':sum(u.get('expires_at') is not None and u['expires_at']<now+7200 for u in units),
            'storage_due':inv.get('storage_due_with_next_lot'),'restock':inv.get('restock')}
    except Exception as e:out['errors'].append({'stage':'inventory','type':type(e).__name__})
    try:out['ledger']=ledger_metrics(root/'state/r4-benefits/benefits.sqlite3',now,credit)
    except Exception as e:out['errors'].append({'stage':'ledger','type':type(e).__name__})
    metrics,complete=tail_json(root/'.kit/transport-metrics.jsonl')
    out['transport_metrics_full_file']=complete
    out['transport_metrics_available']=(root/'.kit/transport-metrics.jsonl').exists()
    for label,start,end in [('last_30m',now-1800,now),('previous_30m',now-3600,now-1800)]:
        rows=[x for x in metrics if start<=x.get('at',0)<end]
        out[label+'_requests']=sum(x.get('event')=='request_start' for x in rows) if out['transport_metrics_available'] else None
        durations=sorted(x['seconds'] for x in rows if x.get('event')=='request_end' and isinstance(x.get('seconds'),(int,float)))
        out[label+'_reply_p50_seconds']=durations[len(durations)//2] if durations else None
    try:
        session=Path((op/'runtime/r3-stock-latest-path.txt').read_text().strip())
        probes,_=tail_json(session/'health-probes.jsonl')
        n=sum(now-1800<=x.get('at',0)<now and x.get('response_state')=='TASK_STATE_COMPLETED' for x in probes)
        out['last_30m_known_operator_probes']=n
        out['last_30m_unlabelled_requests']=max(0,out['last_30m_requests']-n) if out['last_30m_requests'] is not None else None
        out['request_note']='Total transport requests include known read-only operator probes; unlabelled requests are not verified distinct buyers.'
    except (OSError,ValueError):pass
    previous,_=tail_json(dest/'observations.jsonl',4*1024*1024)
    if previous:
        last=previous[-1];out['since_previous_minutes']=round((now-last['at'])/60,2)
        if out.get('inventory') and last.get('inventory'):
            out['since_previous']={k:out['inventory'][k]-last['inventory'][k] for k in ('cash_floor_credits','units','skus','cost')}
        if out.get('shop_rank') is not None and last.get('shop_rank') is not None:
            out.setdefault('since_previous',{})['rank_improvement']=last['shop_rank']-out['shop_rank']
    # Neither an API failure nor missing data is converted to a zero transaction count.
    for name in ('latest.json',datetime.fromtimestamp(now,timezone.utc).strftime('snapshot-%Y%m%d-%H%M%S.json')):
        (dest/name).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    with (dest/'observations.jsonl').open('a') as f:f.write(json.dumps(out,ensure_ascii=False)+'\n')
    inv=out.get('inventory',{});led=out.get('ledger',{});period=led.get('last_30m',{})
    active=all(out['services'][u].get('ActiveState')=='active' for u in ('ourolabs-market-r4.service','ourolabs-market-r4-worker.service'))
    text=['# R4 운영 관측','',datetime.fromtimestamp(now,ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S KST'),'',
          f"R4 메인·정산 워커: {'가동 중' if active else '상태 확인 필요'} · 공개 접속: {out.get('listed_alive','미확인')}",'',
          f"- 상점 순위: {out.get('shop_rank','미확인')}",
          f"- 실제 재고: {inv.get('units','미확인')}개 / {inv.get('skus','미확인')}품목 · 등급 {inv.get('grades',{})}",
          f"- 확인된 신규 입고: {led.get('confirmed_arrival_units','미확인')}개 · 송금 불명확: {led.get('procurement_unknown','미확인')}건",
          f"- 최근 30분 실제 정산: {period.get('settlements','미확인')}건 · 첫 정산: {period.get('first_settlements','미확인')}건",
          f"- 최근 30분 미분류 문의: {out.get('last_30m_unlabelled_requests','미확인')}건 · 별도 운영자 조회: {out.get('last_30m_known_operator_probes','미확인')}건",
          f"- 2시간 이내 만료 재고: {inv.get('expires_within_2h','미확인')}개 · 5분 넘은 서명 미정산: {led.get('signed_unsettled_over_5m','미확인')}건",
           f"- 최근30분 포럼 게시: {led.get('forum_posted_last_30m',0)}건 · 게시 확인 대기: {led.get('forum_unresolved',0)}건 · C등급 정산: {led.get('c_settlements_last_30m',0)}건",
          f"- 기존 지갑 일치: {out.get('card',{}).get('wallet_preserved','미확인')}",'',
          '같은 시간 비교: '+('연속 가동 1시간 이상인 두 30분 구간이다.' if out['equal_30m_windows_fully_live'] else '아직 연속 가동 1시간 미만이다. 이전 구간의 중지·기동 시간을 성과 개선으로 해석하지 않는다.'),'',
          '입고는 매출이 아니며, 미분류 문의도 확인된 신규 구매자 수는 아니다. 금액·원장 원문·고객 데이터는 이 화면에 공개하지 않고 비공개 WSL runtime에 보존한다.','']
    (dest/'LATEST.md').write_text('\n'.join(text))
    if args.publish:
        args.publish.parent.mkdir(parents=True,exist_ok=True);args.publish.write_text('\n'.join(text))
    public={k:out[k] for k in ('time_utc','shop_rank','listed_alive','main_uptime_seconds','equal_30m_windows_fully_live','errors') if k in out}
    public['village']=out.get('village',{})
    public['inventory']={k:inv[k] for k in ('units','skus','grades','expires_within_2h') if k in inv}
    public['ledger']={k:led[k] for k in ('quick_check','sale_states','procurement_states','procurement_unknown','confirmed_arrival_units','signed_unsettled_over_5m','forum_states','forum_posted_last_30m','forum_unresolved','c_settlements_last_30m','promotion_signed_exposures') if k in led}
    public['last_30m']={k:period[k] for k in ('settlements','first_settlements') if k in period}
    public['known_operator_probes']=out.get('last_30m_known_operator_probes')
    public['unlabelled_requests']=out.get('last_30m_unlabelled_requests')
    print(json.dumps(public,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
