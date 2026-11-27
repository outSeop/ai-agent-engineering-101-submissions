"""Evidence-gated public R4 forum marketing. OpenAI Codex GPT-6.2 Sol."""
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
import unicodedata

import httpx

sys.path.insert(0, str(Path.cwd() / "codex-r4"))
import dispatcher as shop
from broker import mask, stated_prices

POST_GAP=330
SPOTLIGHT_GAP=600
SKU_GAP=3600
THREAD_MAX_AGE=6*3600
DAY=86400
DAILY_LIMIT=96
PRESETS={
    "aggressive":(SPOTLIGHT_GAP,SKU_GAP,DAILY_LIMIT),
    "conservative":(1200,5400,18),
}
DEFAULT_RATES=PRESETS["aggressive"]
BENEFITS=(
    "정상 정산·인도 후 상품 기준가의 1%를 적립합니다. 마일리지는 7일 동안 다음 구매부터 사용됩니다. "
    "실제 앞선 결제로 발급된 대기권은 120초 안에 같은 상품을 다시 문의해 구매할 때 기준가의 1%를 할인합니다. "
    "유효한 기존 마일리지와 대기할인은 조건을 충족하면 함께 사용할 수 있습니다. "
    "대기권이 재고 확보나 자동 알림을 보장하지 않습니다."
)
WARRANTY=(
    "인도 후 48시간 내 증빙이 확인된 초기 문제나 확인된 판매자 귀책 미인도는 운영자가 환불을 검토합니다. "
    "원결제 증빙이 필요하며 승인 후 원송금 주소로 처리합니다."
)
REQUEST=re.compile(r"구해(?:요|주세요|\s*봅니다)|구합니다|찾습니다|찾아(?:요|줘)|삽니다|사고\s*싶|"
                   r"구매\s*(?:희망|하고 싶)|(?:견적|가격)\s*(?:부탁|주세요)|looking (?:for|to buy)|want to buy", re.I)
PAST=re.compile(r"구매\s*(?:기록|결과)|실결제|구매했|샀어요|후기|고르는 법|\bbought\b|\bpurchased\b",re.I)
BASIC_WORDS={"상품","기타","제품","필요","생활","식품","가구","용품","무료배송","구해요","판매","또는","이하"}
SCHEMA="""
CREATE TABLE IF NOT EXISTS forum_publication (
    id TEXT PRIMARY KEY, shop TEXT NOT NULL, round INTEGER NOT NULL,
    thread INTEGER, sku TEXT NOT NULL, content TEXT NOT NULL, anchor INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('sending','unknown','declined','posted')),
    fingerprint TEXT,
    created REAL NOT NULL, post INTEGER UNIQUE, reconcile_after REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS forum_recent ON forum_publication(created,sku,thread);
"""


def open_forum(wallet, db_path=shop.DB):
    db=shop.open_db(db_path,wallet)
    db.executescript(SCHEMA)
    if not any(row["name"]=="fingerprint" for row in db.execute("PRAGMA table_info(forum_publication)")):
        with shop.atomic(db):
            if not any(row["name"]=="fingerprint" for row in db.execute("PRAGMA table_info(forum_publication)")):
                db.execute("ALTER TABLE forum_publication ADD COLUMN fingerprint TEXT")
    return db


def public_text(value, maximum=350):
    if not isinstance(value,str):
        return ""
    clean="".join(" " if c.isspace() else c for c in value
                  if c.isspace() or unicodedata.category(c) not in ("Cc","Cf","Cs"))
    return mask(" ".join(clean.split()))[:maximum].rstrip()


class Market(shop.Market):
    def forum(self, since=0):
        value=self.get("/api/forum",params={"since":since,"limit":100})
        if not isinstance(value,list):
            raise shop.Unavailable("invalid market forum view")
        return [post for post in value if isinstance(post,dict) and type(post.get("id")) is int and post["id"]>0]

    def post(self, payload):
        response=httpx.post(shop.MARKET+"/api/forum",headers={"authorization":"Bearer "+self.kit.token("shop")},
                            json=payload,timeout=self.timeout(),trust_env=False)
        if response.status_code==200:
            body=response.json()
            return response.status_code,body.get("post") if isinstance(body,dict) else None
        return response.status_code,None


def stock_offers(db, market, now):
    _,bps,network,_=market.chain()
    offers=[]
    launch=bool(shop.price_policy.current(now))
    for unit in shop.usable_units(market.inventory(),now):
        if shop.pinned(db,unit["unit"]) or (unit.get("expires_at") is not None and unit["expires_at"]<now+1200):
            continue
        terms=shop.price_terms(unit,bps,network)
        name=public_text(unit.get("name"),120)
        if not terms or not name:
            continue
        base,floor=terms
        cert=unit["cert"].get("cert")
        certified=isinstance(cert,dict) and (cert.get("unit"),cert.get("sku"),cert.get("shop"))==(
            unit["unit"],unit["sku"],shop.SHOP)
        offers.append({"sku":unit["sku"],"name":name,"grade":unit["grade"],"price":shop.preferred_sale_price(unit,terms,bps,network,launch=launch),
                       "category":public_text(unit.get("category"),100),"expiry":unit.get("expires_at"),
                       "certificate":certified,"_unit":unit["unit"]})
    # Aged grade C is visible as C. Other grades never inherit C wording.
    offers.sort(key=lambda r:(r["grade"]!="C",r["expiry"] is None,r["expiry"] or 0,r["price"],r["sku"]))
    return list({(r["sku"],r["grade"]):r for r in reversed(offers)}.values())[::-1]


def is_match(post, offer, now):
    if (post.get("round")!=4 or post.get("role")!="buyer" or post.get("author")==shop.SHOP
            or type(post.get("ts")) not in (int,float) or not 0<=now-post["ts"]<=THREAD_MAX_AGE):
        return False
    text=post.get("text")
    if not isinstance(text,str) or not REQUEST.search(text) or PAST.search(text):
        return False
    mentioned=set(re.findall(r"(?<![A-Za-z0-9])[FG][A-Fa-f0-9]{8}(?![A-Za-z0-9])",text))
    if mentioned:
        if mentioned!={offer["sku"]}:
            return False
    else:
        leaf=offer["category"].split(">")[-1]
        words=set(re.findall(r"[가-힣A-Za-z]{3,}",leaf+" "+offer["name"]))-BASIC_WORDS
        # Only specific words from an owned product are eligible for a reply.
        hits={w for w in words if re.search(r"(?<![가-힣A-Za-z])"+re.escape(w)+
               r"(?=$|[^가-힣A-Za-z]|(?:을|를|은|는|이|가|도)(?:\s|$))",text,re.I)}
        if not hits or not (leaf in text or len(hits)>=2 or any(len(w)>=4 for w in hits)):
            return False
    grades=set(re.findall(r"\b([ABC])\s*(?:등급|급)",text))
    if grades and offer["grade"] not in grades:
        return False
    prices,ambiguous=stated_prices(text)
    if ambiguous or prices and offer["price"]>min(prices):
        return False
    # Interpret documented remaining-life constraints conservatively.
    for hours,duration in re.findall(r"(\d+)\s*(시간|일)\s*(?:이상|넘|남)",text):
        if offer["expiry"] is not None and offer["expiry"]-now < int(hours)*(86400 if duration=="일" else 3600):
            return False
    if "인증서" in text and not offer["certificate"]:
        return False
    return True


def cooldown(db, now, rates=DEFAULT_RATES):
    active=shop.one(db,"SELECT id FROM forum_publication WHERE status IN ('sending','unknown') LIMIT 1")
    if active:
        return "unresolved_publish"
    last=shop.one(db,"SELECT max(created) FROM forum_publication")[0]
    if last is not None and now-last<POST_GAP:
        return "cooldown"
    if shop.one(db,"SELECT count(*) FROM forum_publication WHERE created>?",now-DAY)[0] >= rates[2]:
        return "daily_limit"
    return None


def offer_fingerprint(offer, thread):
    safe=[offer["sku"],offer["grade"],offer["price"],offer["_unit"],thread]
    return sha256(json.dumps(safe).encode()).hexdigest()


def available_options(db, market, now, rates=DEFAULT_RATES):
    posts=market.forum()
    if any(p.get("author")==shop.SHOP and p.get("role")=="shop" and p.get("round")==4
           and type(p.get("ts")) in (int,float) and now-p["ts"]<POST_GAP for p in posts):
        return posts,[],[],False
    prior=shop.one(db,"SELECT max(created) FROM forum_publication WHERE thread IS NULL")[0]
    spotlight=prior is None or now-prior>=rates[0]
    offers=[r for r in stock_offers(db,market,now) if not shop.one(db,
            "SELECT id FROM forum_publication WHERE sku=? AND created>?",r["sku"],now-rates[1])]
    options=[]
    for row in reversed(posts):
        if shop.one(db,"SELECT id FROM forum_publication WHERE thread=?",row["id"]):
            continue
        matched=[{"sku":r["sku"],"grade":r["grade"]} for r in offers if is_match(row,r,now)]
        if matched:
            options.append({"thread":row["id"],"request":public_text(row["text"]),"eligible":matched[:8]})
        if len(options)>=8:
            break
    return posts,offers,options,spotlight


def forum_context(db, market, now, rates=DEFAULT_RATES):
    blocked=cooldown(db,now,rates)
    if blocked:
        return {"status":blocked}
    _,offers,replies,spotlight=available_options(db,market,now,rates)
    eligible_reply={(r["sku"],r["grade"]) for reply in replies for r in reply["eligible"]}
    visible=[{k:r[k] for k in ("sku","name","grade","price","category","expiry","certificate")} for r in offers
             if (r["sku"],r["grade"]) in eligible_reply or spotlight and not shop.one(
                 db,"SELECT id FROM forum_publication WHERE fingerprint=? AND status!='declined'",offer_fingerprint(r,None))]
    visible=visible[:16]
    return {"status":"options","spotlight_allowed":spotlight,"items":visible,"reply_options":replies}


def render(offer, thread, shop_url, now):
    intro="찾으신 상품 조건에 맞춰 아래 재고를 확인했습니다." if thread else "현재 확인한 판매 재고를 안내합니다."
    base=(f"{offer['name']} ({offer['sku']}) · {offer['grade']}등급 · 상품가 {offer['price']:,} 크레딧")
    caveat="게시 시점의 한 단위 기준이며 판매·예약·등급 변동이 있을 수 있습니다. 결제 전 A2A에서 재고와 조건을 다시 확인합니다."
    if offer["expiry"] is not None:
        caveat+=f" 게시 시점 기준 남은 유통시간 {int((offer['expiry']-now)//60)}분."
    proof="결제 시 서명된 결제권에 해당 단위의 시장 인증서가 첨부됩니다." if offer["certificate"] else ""
    clearance="C등급이므로 낮은 마진으로 빠른 판매를 우선한 가격입니다." if offer["grade"]=="C" else ""
    contact=f"{shop.SHOP} ({shop_url})에 A2A로 '{offer['sku']} 재고와 가격을 확인해 주세요'라고 먼저 문의해 주세요. 구매를 결정하면 '{offer['sku']} 지금 구매할게요'라고 보내 결제권을 받으세요. 시장 수수료·가스는 결제 조건에서 확인합니다."
    return "\n\n".join([intro,base,caveat,contact,BENEFITS,WARRANTY]+([clearance] if clearance else [])+([proof] if proof else []))


def forum_publish(db, market, now, decision, rates=DEFAULT_RATES):
    if not isinstance(decision,dict) or not {"action"}<=set(decision)<= {"action","sku","grade","thread","reason"}:
        return {"status":"invalid_choice"}
    action=decision["action"]
    if action=="hold" and set(decision)<={"action","reason"}:
        return {"status":"hold"}
    sku,grade,thread=decision.get("sku"),decision.get("grade"),decision.get("thread")
    if (action not in ("spotlight","reply") or not isinstance(sku,str) or grade not in ("A","B","C")
            or action=="reply" and (type(thread) is not int or thread<=0)
            or action=="spotlight" and thread is not None):
        return {"status":"invalid_choice"}
    blocked=cooldown(db,now,rates)
    if blocked:
        return {"status":blocked}
    posts,offers,replies,spotlight=available_options(db,market,now,rates)
    if action=="spotlight" and not spotlight:
        return {"status":"spotlight_unavailable"}
    if action=="reply" and not any(r["thread"]==thread and {"sku":sku,"grade":grade} in r["eligible"] for r in replies):
        return {"status":"no_fresh_matching_request"}
    offer=next((r for r in offers if (r["sku"],r["grade"])==(sku,grade)),None)
    if not offer:
        return {"status":"no_fresh_offer"}
    rendered=render(offer,thread,market.shop_url,now)
    if not rendered or len(rendered)>2000:
        return {"status":"message_length_exceeded"}
    ident=secrets.token_hex(16)
    anchor=max((p["id"] for p in posts),default=0)
    fingerprint=offer_fingerprint(offer,thread)
    with shop.atomic(db):
        blocked=cooldown(db,now,rates)
        if blocked:
            return {"status":blocked}
        if shop.one(db,"SELECT id FROM forum_publication WHERE thread=? OR sku=? AND created>?",thread,sku,now-rates[1]):
            return {"status":"already_attempted"}
        if shop.one(db,"SELECT id FROM forum_publication WHERE (fingerprint=? AND status!='declined') OR (content=? AND created>?)",
                    fingerprint,rendered,now-DAY):
            return {"status":"duplicate_content"}
        db.execute("""INSERT INTO forum_publication(id,shop,round,thread,sku,content,anchor,status,created,fingerprint)
                       VALUES(?,?,?,?,?,?,?,'sending',?,?)""",
                   (ident,shop.SHOP,4,thread,sku,rendered,anchor,now,fingerprint))
    payload={"text":rendered}
    if thread is not None:
        payload["thread"]=thread
    try:
        code,post=market.post(payload)
    except (httpx.HTTPError,shop.Unavailable,OSError,ValueError,TypeError,AttributeError):
        code,post=None,None
    posted=code==200 and type(post) is int and post>anchor
    state="posted" if posted else "declined" if code in (400,401,403,404,413,429) else "unknown"
    with shop.atomic(db):
        db.execute("UPDATE forum_publication SET status=?,post=?,reconcile_after=? WHERE id=? AND status='sending'",
                   (state,post if posted else None,now+30,ident))
    return {"status":state,"post":post if posted else None}


def forum_reconcile(db, market, now):
    row=shop.one(db,"SELECT * FROM forum_publication WHERE status IN ('sending','unknown') AND reconcile_after<=? AND created<=? ORDER BY created LIMIT 1",
                 now,now-10)
    if not row:
        return {"status":"nothing_to_reconcile"}
    since=row["anchor"]
    matches=[]
    for _ in range(5):
        posts=market.forum(since)
        matches += [p for p in posts if p.get("author")==row["shop"] and p.get("role")=="shop"
                    and p.get("round")==row["round"] and p.get("thread")==row["thread"]
                    and p.get("text")==row["content"] and p.get("id",0)>row["anchor"]
                    and type(p.get("ts")) in (int,float) and p["ts"]>=row["created"]-2]
        if len(posts)<100:
            break
        next_since=max(p["id"] for p in posts)
        if next_since<=since:
            break
        since=next_since
    with shop.atomic(db):
        if len(matches)==1:
            db.execute("UPDATE forum_publication SET status='posted',post=? WHERE id=? AND status IN ('sending','unknown')",
                       (matches[0]["id"],row["id"]))
            return {"status":"reconciled","post":matches[0]["id"]}
        db.execute("UPDATE forum_publication SET status='unknown',reconcile_after=? WHERE id=? AND status IN ('sending','unknown')",
                   (now+120,row["id"]))
    return {"status":"unknown"}


def run(args, kit):
    db=None
    try:
        market=Market(kit)
        db=open_forum(market.wallet)
        action=args.get("action")
        rates=PRESETS.get(args.get("preset","aggressive"))
        if rates is None:
            return {"status":"invalid_preset"}
        if action=="context":
            return forum_context(db,market,time.time(),rates)
        if action=="publish":
            return forum_publish(db,market,time.time(),args.get("decision"),rates)
        if action=="reconcile":
            return forum_reconcile(db,market,time.time())
        return {"status":"invalid_action"}
    except (shop.Unavailable,sqlite3.Error,httpx.HTTPError,OSError,ValueError,TypeError,KeyError,AttributeError):
        return {"status":"authoritative_check_unavailable"}
    finally:
        if db is not None:
            db.close()

