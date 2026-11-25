def test(run, kit):
    args = {'name': 'stage_representative_card', 'file': 'logic.py', 'offset': 0}
    first = run(args, kit)
    assert first['source'].startswith('import hashlib\n')
    assert len(first['source']) == first['next_offset'] == 2000
    second = run(dict(args, offset=first['next_offset']), kit)
    assert second['offset'] == 2000 and second['sha256'] == first['sha256']
    assert second['total_chars'] == first['total_chars']
    tail = run(dict(args, offset=first['total_chars']), kit)
    assert tail['source'] == '' and tail['next_offset'] is None
    assert run(dict(args, offset=True), kit)['error'] == 'invalid_offset'
    assert run(dict(args, name='../stage_representative_card'), kit)['error'] == 'invalid_tool_name'
    assert run(dict(args, file='../logic.py'), kit)['error'] == 'invalid_source_file'
