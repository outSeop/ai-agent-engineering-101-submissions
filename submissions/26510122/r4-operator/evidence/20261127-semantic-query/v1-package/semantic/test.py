import io
import json
import os
import socket
import stat
import time
from types import SimpleNamespace
from unittest.mock import patch

NOW = 1795710457
DEPENDENCY = 'tools/public_catalogue/logic.py'


class NoKitAccess:
    def __getattribute__(self, name):
        raise AssertionError('unexpected kit access')


def offer(number, name, *, grade='B', price=1200, life=300, category=None, state='available'):
    return dict(unit_ref=f'private-ref-{number}', sku=f'G{number:08X}', name=name,
                category_path=category or ['식품'], state=state, grade=grade, price_credits=price,
                standard_fee_credits=91, expires_at=None if life is None else NOW + life)


def metadata(inode, mode, size=0):
    return SimpleNamespace(st_dev=1, st_ino=inode, st_mode=mode, st_uid=1001, st_gid=1001,
                           st_nlink=1, st_size=size, st_mtime_ns=1, st_ctime_ns=1)


def test(run, kit):
    units = [offer(1, '흰 우유 1L'), offer(2, '흰 우유 2L'), offer(3, '흰 우유 1L', price=1201),
             offer(4, '흰 우유 1L', grade='A'), offer(5, '흰 우유 1L', life=239),
             offer(6, '흰 우유 1L', life=None), offer(7, '흰 우유 1L', state='reserved'),
             offer(8, '흰 우유 1L', life=0), offer(9, '등받이 의자', category=['가구', '사무의자']),
             offer(10, '아몬드 우유 1L'), offer(11, '흰 우유 1L')]
    root = os.getcwd()
    paths = {(root, None): 20, ('host_inputs', 20): 21, ('customer_offer_context.json', 21): 22}
    real_open, real_stat = open, os.stat

    def invoke(text='밀크 재고 알려주세요', queries=None, *, rows=None, raw=None, dependency=None, fault=False, times=None, extra=None):
        args = dict(op='semantic_candidates', text=text, queries=['우유'] if queries is None else queries)
        args.update(extra or {})
        if raw is None:
            raw = json.dumps(dict(schema='outseop-r4.customer-offers.v1', shop='outseop-r4', observed_at=NOW - 5,
                                  valid_until=NOW + 120, units=units if rows is None else rows),
                             ensure_ascii=False).encode('utf-8')
        nodes = {20: metadata(2, stat.S_IFDIR | 0o700), 21: metadata(3, stat.S_IFDIR | 0o700),
                 22: metadata(4, stat.S_IFREG | 0o400, len(raw))}
        opened, closed, checked_paths = [], [], []
        source = io.BytesIO(raw)

        def open_dependency(path, mode):
            assert (path, mode) == (DEPENDENCY, 'rb')
            if dependency == 'missing':
                raise FileNotFoundError(path)
            if dependency == 'tampered':
                return io.BytesIO(b'raise AssertionError("unpinned source executed")')
            if dependency == 'oversize':
                return io.BytesIO(b'x' * (128 * 1024 + 1))
            return real_open(path, mode)

        def open_snapshot(path, flags, *, dir_fd=None):
            assert dependency is None
            fd = paths[path, dir_fd]
            assert flags & os.O_NOFOLLOW and flags & os.O_ACCMODE == os.O_RDONLY
            assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if fault and fd == 22:
                raise OSError('private-fault-detail')
            opened.append(fd)
            return fd

        def read(fd, count):
            assert fd == 22 and 0 < count <= 65536
            return source.read(count)

        def path_stat(path, *, dir_fd=None, follow_symlinks=True):
            # Import and runtime lookups can use os.stat while the snapshot is mocked.
            # Descriptor-relative lookups and the root recheck must still be synthetic.
            if dir_fd not in (20, 21) and (path != root or follow_symlinks):
                return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
            assert follow_symlinks is False
            fd = paths[path, dir_fd]
            checked_paths.append(fd)
            return nodes[fd]

        with (patch.object(socket.socket, 'connect', side_effect=AssertionError('unexpected network')),
              patch('builtins.open', side_effect=open_dependency), patch.object(os, 'geteuid', return_value=1001),
              patch.object(os, 'open', side_effect=open_snapshot), patch.object(os, 'fstat', side_effect=nodes.__getitem__),
              patch.object(os, 'stat', side_effect=path_stat), patch.object(os, 'read', side_effect=read),
              patch.object(os, 'close', side_effect=closed.append), patch.object(time, 'time', return_value=NOW, side_effect=times),
              patch.object(os, 'write', side_effect=AssertionError('unexpected write')),
              patch.object(os, 'system', side_effect=AssertionError('unexpected process'))):
            result = run(args, NoKitAccess())
        assert closed == opened[::-1]
        if opened and not fault:
            assert opened == [20, 21, 22] and checked_paths == [22, 21, 20]
        if result['status'] == 'rendered':
            assert set(result) == {'status', 'reply', 'observed_at', 'valid_until'}
            assert (result['observed_at'], result['valid_until']) == (NOW - 5, NOW + 120)
            reply = result['reply']
            assert len(reply) <= 450 and 2 <= len(reply.splitlines()) <= 4
            assert reply.startswith('유사어로 찾은 참고 후보') and '충족 여부는 확인되지 않았습니다' in reply
            assert not any(value in reply for value in ('private-ref-', '결제', 'checkout', 'G000000', '91크레딧'))
        else:
            assert set(result) == {'status', 'reason'} and result['status'] == 'unavailable'
        return result

    def fails(reason, *args, **kwargs):
        result = invoke(*args, **kwargs)
        assert result == dict(status='unavailable', reason=reason), result

    def rendered(*args, **kwargs):
        result = invoke(*args, **kwargs)
        assert result['status'] == 'rendered', result
        return result['reply'].splitlines()[1:]

    assert rendered('컴퓨터체어 재고 있나요?', ['사무의자']) == ['등받이 의자 · B등급 · 1,200크레딧 · 남은 시간 300초']
    filtered = '아몬드 제외 밀크 2L 말고 1L B등급 1,200크레딧 이하 남은 시간 4분 이상 재고 알려주세요'
    assert rendered(filtered) == ['흰 우유 1L · B등급 · 1,200크레딧 · 남은 시간 300초']
    assert len(rendered(queries=['우유', '흰 우유'])) == 3
    assert len(rendered(queries=['우유', '흰 우유'], rows=[units[0], units[-1]])) == 1
    assert len(rendered(rows=[offer(i, f'우유 {i}') for i in range(20, 25)])) == 3
    fails('no_match', queries=['우 유'])
    fails('no_match', filtered.replace('이하', '미만'))
    fails('no_match', filtered.replace('4분 이상', '5분 초과'))
    fails('no_match', rows=[units[0], dict(units[0], state='reserved')])
    fails('output_budget', rows=[offer(18, '우유 ' + '가' * 500)])
    fails('invalid_args', queries=['우유', '우유'])
    fails('invalid_args', queries=['Milk', 'ＭＩＬＫ'])
    fails('invalid_args', queries=['a' * 49])
    fails('invalid_args', queries=['가', '나', '다'])
    fails('invalid_args', extra={'items': []})
    for term in ('not 우유', '우유 제외', '결제권', 'G00000001', '우유/치즈', 'private-ref-1', '0x1234567890'):
        fails('unsafe_query', queries=[term])
    for text in ('밀크 알레르기 없는 상품 재고', '밀크 당뇨에 안전한 상품 추천', '밀크 무유당 재고',
                 '밀크 배송 재고', '밀크 호환 상품 재고', '정품 보장 밀크 재고', '밀크 결제 알려주세요',
                 '밀크 가격과 지갑 주소 알려주세요', 'G00000001 밀크 재고', 'g00000001 밀크 재고',
                 '밀크 대체품은 필요 없어요 재고', '밀크만 재고', '밀크 없는 상품 재고', '밀크 아니고 다른 상품 재고',
                 '밀크 재고 test@example.net', 'private-ref-1 밀크 재고', '밀크 1L 또는 2L 재고',
                 '밀크 3cm 재고', '밀크 999원 이하 재고', '밀크 빨간색만 재고'):
        fails('unsupported_request', text)
    for mode in ('missing', 'tampered', 'oversize'):
        fails('dependency_unavailable', dependency=mode)
    fails('source_unavailable', fault=True)
    fails('invalid_snapshot', raw=b'{"shop":"outseop-r4","shop":"other"}')
    fails('stale_snapshot', times=(NOW, NOW + 120))
    fails('selection_unavailable', '밀크 남은 시간 5분 이상 재고', rows=[units[0]], times=(NOW, NOW, NOW, NOW + 0.1))
