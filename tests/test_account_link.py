from modal_plugin.account_link import AccountLinkSessions
from modal_plugin.auth import owner_id_from_identity


def test_link_is_single_use() -> None:
    sessions = AccountLinkSessions(ttl_seconds=600)
    session = sessions.create("studio")
    assert sessions.get(session.token) == session
    assert sessions.consume(session.token) == session
    assert sessions.get(session.token) is None


def test_link_is_bound_to_requesting_owner() -> None:
    owner = owner_id_from_identity("https://id.example", "user")
    session = AccountLinkSessions().create("studio", owner_id=owner)
    assert session.owner_id == owner
    assert session.account_id == "studio"
