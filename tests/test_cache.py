from libreta.cache import GENESIS, Cache, chain, states


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
    assert (tmp_path / ".libreta" / ".gitignore").read_text() == "*\n"
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


def test_progress_bars_are_saved_collapsed(tmp_path):
    cache = Cache(tmp_path / "doc.md")
    [h] = chain(["a"])
    frames = [("stderr", f"\r{i:3}%") for i in range(101)]
    cache.save(h, [("stdout", "a"), ("stdout", "b\n"), *frames, ("stderr", "\n"), ("stdout", "c")])
    assert cache.load(h) == [
        {"mime": "stdout", "content": "ab\n"},
        {"mime": "stderr", "content": "100%\n"},
        {"mime": "stdout", "content": "c"},
    ]


def test_stale_when_a_file_read_changes(tmp_path):
    data = tmp_path / "datos.csv"
    data.write_text("a\n1\n")
    cache = Cache(tmp_path / "doc.md")
    h1, h2 = chain(["a", "b"])
    st = data.stat()
    cache.save(h1, [], {"datos.csv": [st.st_mtime_ns, st.st_size]})
    cache.save(h2, [])
    assert not cache.stale(h1) and not cache.stale(h2)  # h2 read nothing
    data.write_text("a\n1\n2\n")
    assert cache.stale(h1) == "datos.csv"
    data.unlink()
    assert cache.stale(h1) == "datos.csv"
    cache.prune({h2})
    assert not (cache.dir / f"{h1}-reads.json").exists()


def test_params_start_another_chain():
    assert states([], None) == states([], {}) == [GENESIS]
    a, b = states(["x"], {"mes": 9}), states(["x"], {"mes": 10})
    assert a[0] != GENESIS and a[0] != b[0] and a[1] != b[1]
    assert states(["x"], {"a": 1, "b": 2}) == states(["x"], {"b": 2, "a": 1})
