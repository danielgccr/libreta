from libreta.cache import Cache, chain


def test_chain_invalidates_from_the_changed_block_on():
    a = chain(["x = 1", "y = 2", "z = 3"])
    b = chain(["x = 1", "y = 20", "z = 3"])
    assert len(set(a)) == 3
    assert a[0] == b[0] and a[1] != b[1] and a[2] != b[2]
    assert chain(["y = 2"])[0] != a[1]  # the same code after other blocks is another state


def test_save_load_prune(tmp_path):
    cache = Cache(tmp_path / "doc.md")
    h1, h2 = chain(["a", "b"])
    assert cache.load(h1) is None
    items = [("stdout", "hola\n"), ("image/svg+xml", "<svg/>"), ("image/png", b"\x89PNG")]
    cache.save(h1, items)
    cache.save(h2, [])
    assert cache.load(h1) == [
        {"mime": "stdout", "content": "hola\n"},
        {"mime": "image/svg+xml", "base64": "PHN2Zy8+"},
        {"mime": "image/png", "base64": "iVBORw=="},
    ]
    assert cache.load(h2) == []
    files = sorted(p.name for p in cache.dir.iterdir())
    assert files == sorted([f"{h1}.json", f"{h1}-1.svg", f"{h1}-2.png", f"{h2}.json"])
    cache.save(h1, [("stdout", "otra\n")])  # rewriting an entry drops its old figures
    cache.prune({h1})
    assert [p.name for p in cache.dir.iterdir()] == [f"{h1}.json"]


def test_corrupt_entry_is_missing(tmp_path):
    cache = Cache(tmp_path / "doc.md")
    [h] = chain(["a"])
    cache.save(h, [])
    (cache.dir / f"{h}.json").write_text('[{"mime": ')
    assert cache.load(h) is None
