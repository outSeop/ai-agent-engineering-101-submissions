import ast
from hashlib import sha256
from pathlib import Path
import re
from threading import RLock
from types import ModuleType

V12 = ('codex-r4/forum_marketing12.py', 'f25bb98116593ed7ca708d48c93a1a1aca7da78fda3c083f6aa83ffad06e0f6b')
LOCK = RLock()
OWNER = None

MORE_INTENT = r'(?<![가-힣A-Za-z])필요(?:한|하다|하고|하신|하다고|하네요|하죠|함|했으면)?(?![가-힣A-Za-z])|(?<![가-힣A-Za-z])찾는\s*(?:상품|제품|물건)(?:은|이|을|는)?|찾고\s*(?:있\w*|싶\w*)|구할\s*수\s*(?:있\w*|없나요)|(?:상품가|가격|재고|견적|구매)\s*(?:을|를|에\s*대해)?\s*문의|(?<![가-힣A-Za-z])견적(?:을|도|이|은)?\s*(?:문의|부탁|요청|받고|알고|가능|주세요)|(?<![가-힣A-Za-z])구매\s*(?:를\s*)?(?:하고\s*싶\w*|하려\w*|할\s*수\s*있\w*|희망|예정|원\w*|가능\w*)|(?<![가-힣A-Za-z])견적(?:을|도|이|은)?(?=\s*\?|\s*$)'
PROTECTED = re.compile(r'불\s*필요|필요\s*(?:가\s*)?(?:없|하지\s*않|치\s*않|한\s*건\s*아니)|(?:구매|주문)(?:를|을)?\s*(?:하?지\s*(?:는\s*)?않|않|안\s*(?:함|해|합|하)|했|한\s*(?:후|적|거|건|제품|상품)|완료)|(?:안|못)\s*(?:살|삽|사요|구매하)|(?:써|먹어|사용해)\s*봤|(?:구매|주문|사용|시식)\s*평|리뷰|의료|의약|처방|환자|당뇨|임산부|질환|치료|복용|알레르기|알러지|비건|글루텐|할랄|코셔|무설탕|무가당|저당|무염|저염|유당|증명서|의무\s*표시|\b(?:medical|prescription|diabet\w*|dietary|prescribed|bought|purchased|ordered|used\s+to|used\s+it|tried\s+it|do\s+not\s+(?:want|need|buy))\b', re.I)
REFERENCE_HARD = re.compile(r'호환|연동|지원|규격|사양|스펙|인터페이스|커넥터|충전|전압|전력|정격|모델|버전|방수|내열|성분|함유|무첨가|원산지|재질|소재|포트|단자|아이폰|갤럭시|안드로이드|아이패드|전용|한정|독점|오직|절대로|필히|조건|요건|요구사항|충족|준수|한해서|한해|대안|대신|대체|바꿔|싫|거절|금지|제외|제한|빼고|말고|하되|에만|으로만|로만|(?:것|거|제품|상품|종류|경우)만|(?:^|\s)만(?:\s|$)|(?:^|\s)안\s|지\s*않|없어야|있어야|해야\s*(?:해|하|돼|됩)|(?:이어야|여야|되어야|돼야)|안\s*(?:되는|돼|됩|되면)|다른\s*(?:건|것|상품|제품|종류)|\b(?:compatib\w*|certif\w*|exclusive\w*|require\w*|mandatory|alternative\w*|substitut\w*|cannot|neither|nor|instead|specifications?|version|voltage|iphone|android|usb|lightning|vegan|halal|kosher|organic)\b', re.I)


def verified_source(pin):
    path, digest = pin
    source = Path(path).read_bytes()
    if sha256(source).hexdigest() != digest:
        raise ValueError('publisher digest mismatch')
    return source


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError('unexpected classifier source')
    return source.replace(before, after, 1)


def patch_classifier(module, pin):
    path = pin[0]
    source = verified_source(pin).decode('utf-8')
    definitions = [node for node in ast.parse(source, filename=path).body
                   if isinstance(node, ast.FunctionDef) and node.name == 'classify']
    if len(definitions) != 1:
        raise ValueError('unexpected classifier definition')
    definition = definitions[0]
    classifier = ast.get_source_segment(source, definition)
    classifier = replace_once(classifier, '    intent = re.compile(', '    if V13_PROTECTED.search(text):\n        return None\n    intent = re.compile(')
    classifier = replace_once(classifier, '(?:입니다|으로|에서|에게|을|를|은|는|이|가|도|만|과|와|로)', '(?:입니다|이에요|예요|으로|에서|에게|을|를|은|는|이|가|도|만|과|와|로)')
    legacy = "    chunks = re.split(r'\\s+(?:그리고|또|및)\\s+', rest)\n    return 'reference' if len(chunks) <= 3 and all(SOFT.fullmatch(chunk) for chunk in chunks) else None"
    classifier = replace_once(classifier, legacy, "    if V13_REFERENCE_HARD.search(rest):\n        return None\n    return 'reference' if any(character.isalpha() for character in rest) else None")
    module.INTENT += '|' + MORE_INTENT
    module.V13_PROTECTED = PROTECTED
    module.V13_REFERENCE_HARD = REFERENCE_HARD
    exec(compile('\n' * (definition.lineno - 1) + classifier, path, 'exec'), module.__dict__)
    return module


def load_wrapper():
    source = verified_source(V12)
    wrapper = ModuleType('_outseop_r4_forum_marketing_v12')
    wrapper.__file__ = V12[0]
    exec(compile(source, wrapper.__file__, 'exec'), wrapper.__dict__)
    load_original = wrapper.load_verified11

    def load_patched11():
        return patch_classifier(load_original(), wrapper.V11)

    wrapper.load_verified11 = load_patched11
    return wrapper


def run(args, kit):
    global OWNER
    try:
        with LOCK:
            if OWNER is None:
                OWNER = load_wrapper()
            owner = OWNER
        return owner.run(args, kit)
    except Exception:
        return {'status': 'hold'}
