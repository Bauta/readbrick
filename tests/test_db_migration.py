def test_new_user_default_voice_is_kokoro(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from server.db import init_db
    from server import users
    init_db()
    u = users.create_user("Ola")
    assert users.get_prefs(u["id"])["voice_id"] == "kokoro:af_heart"


def test_new_user_default_font_family_is_serif(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from server.db import init_db
    from server import users
    init_db()
    u = users.create_user("Pat")
    assert users.get_prefs(u["id"])["font_family"] == "serif"


def test_update_prefs_accepts_font_family(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from server.db import init_db
    from server import users
    init_db()
    u = users.create_user("Pat")
    prefs = users.update_prefs(u["id"], {"font_family": "dyslexic"})
    assert prefs["font_family"] == "dyslexic"


def test_legacy_prefs_migrate_to_kokoro(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from server.db import init_db, connect
    init_db()
    with connect() as c:
        c.execute("INSERT INTO users (name, created_at) VALUES ('A', 0)")
        c.execute("INSERT INTO users (name, created_at) VALUES ('B', 0)")
        c.execute("INSERT INTO users (name, created_at) VALUES ('C', 0)")
        c.execute("INSERT INTO prefs (user_id, voice_id) VALUES (1, 'legacy:voice-a')")
        c.execute("INSERT INTO prefs (user_id, voice_id) VALUES (2, 'legacy:voice-b')")
        c.execute("INSERT INTO prefs (user_id, voice_id) VALUES (3, 'legacy:voice-c')")
    init_db()  # re-run: migration should rewrite all non-kokoro ids
    with connect() as c:
        voices = {r["voice_id"] for r in c.execute("SELECT voice_id FROM prefs")}
    assert voices == {"kokoro:af_heart"}


def test_existing_kokoro_pref_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from server.db import init_db, connect
    init_db()
    with connect() as c:
        c.execute("INSERT INTO users (name, created_at) VALUES ('A', 0)")
        c.execute("INSERT INTO prefs (user_id, voice_id) VALUES (1, 'kokoro:bm_george')")
    init_db()  # migration must not clobber a valid kokoro pref
    with connect() as c:
        v = c.execute("SELECT voice_id FROM prefs WHERE user_id = 1").fetchone()["voice_id"]
    assert v == "kokoro:bm_george"
