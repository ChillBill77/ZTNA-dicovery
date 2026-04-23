from __future__ import annotations

from resolver.saas_matcher import SaasMatcher, SaasRow


def test_empty_returns_none() -> None:
    m = SaasMatcher([])
    assert m.match("example.com") is None


def test_exact_suffix_match() -> None:
    m = SaasMatcher([
        SaasRow(id=1, name="Microsoft 365", pattern=".office365.com", priority=100),
    ])
    got = m.match("outlook.office365.com")
    assert got is not None
    assert got.name == "Microsoft 365"


def test_longer_pattern_wins() -> None:
    m = SaasMatcher([
        SaasRow(id=1, name="M365",     pattern=".office365.com",          priority=100),
        SaasRow(id=2, name="Exchange", pattern=".outlook.office365.com",  priority=100),
    ])
    got = m.match("mail.outlook.office365.com")
    assert got is not None
    assert got.name == "Exchange"


def test_priority_breaks_tie() -> None:
    m = SaasMatcher([
        SaasRow(id=1, name="Low",  pattern=".example.com", priority=50),
        SaasRow(id=2, name="High", pattern=".example.com", priority=100),
    ])
    got = m.match("foo.example.com")
    assert got is not None
    assert got.name == "High"


def test_no_match_returns_none() -> None:
    m = SaasMatcher([SaasRow(id=1, name="M365", pattern=".office365.com", priority=100)])
    assert m.match("evil.example.com") is None
