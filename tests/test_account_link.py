from modal_plugin.account_link import AccountLinkSessions


def test_link_session_is_one_time() -> None:
    sessions = AccountLinkSessions(ttl_seconds=600)
    created = sessions.create("default")

    assert sessions.get(created.token) == created
    assert sessions.consume(created.token) == created
    assert sessions.get(created.token) is None


def test_link_session_rejects_unsafe_account_id() -> None:
    sessions = AccountLinkSessions(ttl_seconds=600)
    try:
        sessions.create("../../secret")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe account id should fail")
