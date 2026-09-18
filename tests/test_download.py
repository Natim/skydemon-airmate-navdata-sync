from navdata_sync.download import human_size


def test_human_size() -> None:
    assert human_size(500) == "500.0 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(1024 * 1024) == "1.0 MB"
