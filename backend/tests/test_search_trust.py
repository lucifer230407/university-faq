from app.services.search import is_official_source


def test_seeded_faq_is_official():
    assert is_official_source({"source_id": "about_university", "agent_ns": "general"})


def test_untrusted_upload_is_ignored():
    assert is_official_source({"source_id": "upload:fake.pdf"}) is False


def test_admin_upload_is_official():
    assert is_official_source({"source_id": "upload:circular.pdf", "trusted": True})
