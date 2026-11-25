import hashlib


def test(run, kit):
    env = run.__globals__
    for name, filename, expected in (
        ('apply_staged_card@1', 'logic.py', env['ARCHIVED']['logic.py']),
        ('apply_staged_card@1', 'test.py', env['ARCHIVED']['test.py']),
        ('apply_staged_card', 'logic.py', '4fecb5a59aba74173e10f88a3c79171daa8f729c6ac37b2f037aa7d4ced05c90'),
    ):
        offset = 0
        pieces = []
        while offset is not None:
            result = run({'name': name, 'file': filename, 'offset': offset}, kit)
            assert result.get('sha256') == expected, result
            assert result['offset'] == offset
            assert 0 < len(result['source']) <= 2000
            pieces.append(result['source'])
            offset = result['next_offset']
        text = ''.join(pieces)
        assert len(text) == result['total_chars']
        assert hashlib.sha256(text.encode('utf-8')).hexdigest() == expected
    for name, filename, offset in (
        ('../apply_staged_card', 'logic.py', 0),
        ('apply_staged_card@1', '../card.json', 0),
        ('apply_staged_card@1', 'logic.py', True),
        ('apply_staged_card@2', 'logic.py', 0),
    ):
        assert 'error' in run({'name': name, 'file': filename, 'offset': offset}, kit)
    try:
        env['load']([env['ROOT'] / 'tools/apply_staged_card/logic.py'], '0' * 64)
    except ValueError:
        pass
    else:
        raise AssertionError('source hash mismatch accepted')
