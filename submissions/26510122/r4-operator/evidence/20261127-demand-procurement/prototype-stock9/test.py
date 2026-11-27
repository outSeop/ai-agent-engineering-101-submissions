def test(run, kit):
    assert kit.testing
    assert run({'action': '_sdk_test'}, kit) == {'passed': True, 'payments': 0, 'finance_ready': False}
    assert run({'action': 'execute', 'approved': True}, kit)['reason'] == 'synthetic_only'
