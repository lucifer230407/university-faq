from app.services.search import (
    course_tokens,
    focus_excerpt,
    is_official_source,
    lexical_match_score,
    reading_context,
    render_corpus,
    schedule_codes,
    stitch_chunks,
)


def test_seeded_faq_is_official():
    assert is_official_source({"source_id": "about_university", "agent_ns": "general"})


def test_untrusted_upload_is_ignored():
    assert is_official_source({"source_id": "upload:fake.pdf"}) is False


def test_admin_upload_is_official():
    assert is_official_source({"source_id": "upload:circular.pdf", "trusted": True})


def test_schedule_codes_from_fa2_question():
    query = "When is FA2 (Formative Assessment 2) for Full Stack AI Engineering?"
    assert schedule_codes(query) == ["FA2"]
    assert "stack" in course_tokens(query)
    assert "engineering" in course_tokens(query)


def test_lexical_score_prefers_exact_fa2_row():
    codes = ["FA2"]
    tokens = ["full", "stack", "engineering"]
    exact = (
        "Schedule Entry 29 Name of Activity: FA2 - Full stack AI Engineering "
        "Date(s): Mon, Nov 23 to Fri, Nov 27, 2026 Remarks: Project Based Evaluation"
    )
    other = (
        "FA2 - Back End Engineering Mon, Oct 26 to Fri, Oct 30, 2026 "
        "FA1 - Full stack AI Engineering Mon, Oct 26 to Fri, Oct 30, 2026"
    )
    assert lexical_match_score(exact, codes, tokens) > lexical_match_score(
        other, codes, tokens
    )


def test_stitch_drops_overlap_and_keeps_order():
    tail = "Project Based Evaluation continues"
    chunks = [
        {"text": f"FA1 line. {tail}", "metadata": {"chunk_index": 1}},
        {"text": f"{tail} FA2 - Full stack AI Engineering", "metadata": {"chunk_index": 2}},
    ]
    merged = stitch_chunks(chunks)
    assert merged.index("FA1") < merged.index("FA2")
    assert merged.count(tail) == 1


def test_render_corpus_drops_ocr_twin_and_test_docs():
    docs = [
        {
            "text": "clean calendar FA2",
            "metadata": {
                "filename": "Circular_AI_Readable.pdf",
                "agent_ns": "academic calendar",
                "source_id": "upload:Circular_AI_Readable.pdf",
                "trusted": True,
                "chunk_index": 1,
            },
        },
        {
            "text": "garbled OCR",
            "metadata": {
                "filename": "Circular_OCR.pdf",
                "agent_ns": "academic calendar",
                "source_id": "upload:Circular_OCR.pdf",
                "trusted": True,
                "chunk_index": 1,
            },
        },
        {
            "text": "should not appear",
            "metadata": {"source_id": "test_document", "agent_ns": "academics"},
        },
        {
            "text": "Hostel gate closes at 9 pm.",
            "metadata": {"source_id": "hostel_rules", "agent_ns": "hostel"},
        },
    ]
    text = render_corpus(docs)
    assert "clean calendar FA2" in text
    assert "garbled OCR" not in text
    assert "should not appear" not in text
    assert "Hostel gate closes at 9 pm." in text


def test_reading_context_uses_exact_row_and_full_file():
    query = "When is FA2 for Full Stack AI Engineering?"
    hits = [
        {
            "text": (
                "FA2 - Back End Engineering Mon, Oct 26 to Fri, Oct 30, 2026 "
                "FA1 - Full stack AI Engineering Mon, Oct 26 to Fri, Oct 30, 2026 "
                "FA2 - Full stack AI Engineering Mon, Nov 23 to Fri, Nov 27, 2026 "
                "Project Based Evaluation"
            ),
            "metadata": {
                "filename": "calendar.pdf",
                "agent_ns": "academic calendar",
                "chunk_index": 4,
            },
            "score": 0.6,
            "lexical": True,
        }
    ]
    docs = [
        {
            "text": "Schedule Entry 29 FA2 - Full stack AI Engineering Mon, Nov 23 to Fri, Nov 27, 2026",
            "metadata": {
                "filename": "calendar.pdf",
                "agent_ns": "academic calendar",
                "source_id": "upload:calendar.pdf",
                "trusted": True,
                "chunk_index": 1,
            },
        },
        {
            "text": "Course Coordinator Dr. Meena Rani. Evaluation is project based.",
            "metadata": {
                "filename": "CHO_Full_stack_AI_Engineering.pdf",
                "agent_ns": "course_handouts",
                "source_id": "upload:CHO_Full_stack_AI_Engineering.pdf",
                "trusted": True,
                "chunk_index": 1,
            },
        },
    ]
    packed = reading_context(query, hits, docs=docs)
    excerpt = focus_excerpt(hits[0]["text"], query)
    assert "Nov 23" in excerpt
    assert "Oct 26" not in excerpt
    assert "Nov 23" in packed
    assert "Dr. Meena Rani" in packed
