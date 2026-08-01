from hydrawiki.chunking import chunk_content


def test_chunking_is_line_aware_and_deterministic() -> None:
    content = "one\ntwo\nthree\nfour\n"
    first = chunk_content(content, max_lines=2)
    second = chunk_content(content, max_lines=2)
    assert [(item.line_start, item.line_end, item.text) for item in first] == [
        (1, 2, "one\ntwo\n"),
        (3, 4, "three\nfour"),
    ]
    assert [item.content_hash for item in first] == [item.content_hash for item in second]
    assert [item.ordinal for item in first] == [0, 1]
