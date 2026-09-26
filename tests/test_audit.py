from spacedoc.audit.log import AuditLog


def test_chain_verifies_and_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    assert log.append("ask", {"q": "one"}) == "audit-000001"
    log.append("ask", {"q": "two"})
    log.append("ask", {"q": "three"})
    assert log.verify() == (True, None)

    lines = log.path.read_text().splitlines()
    lines[1] = lines[1].replace('"two"', '"TWO"')
    log.path.write_text("\n".join(lines) + "\n")
    assert log.verify() == (False, 2)


def test_deleting_an_entry_is_detected(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    for i in range(3):
        log.append("ask", {"i": i})
    lines = log.path.read_text().splitlines()
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    ok, bad = log.verify()
    assert not ok and bad == 3
