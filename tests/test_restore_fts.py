"""Exercise the actual workflow restore and FTS commands against a stale index."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "blog_series", "blog_tag", "blog_quotation", "blog_entry", "blog_blogmark", "blog_note"
)


@pytest.mark.parametrize("restore_previous_database", [False, True])
def test_restore_and_rebuild_note_search(tmp_path, restore_previous_database):
    backup = tmp_path / "simonwillisonblog"
    backup.mkdir()
    for table in TABLES:
        metadata = json.loads((ROOT / "simonwillisonblog" / f"{table}.metadata.json").read_text())
        (backup / f"{table}.metadata.json").write_text(json.dumps(metadata))
        rows = ""
        if table == "blog_note":
            note = {"id": 1, "title": "New title", "body": "searchable platypus"}
            rows = json.dumps([note.get(column) for column in metadata["columns"]]) + "\n"
        (backup / f"{table}.ndjson").write_text(rows)

    database = tmp_path / "simonwillisonblog.db"
    if restore_previous_database:
        with sqlite3.connect(database) as conn:
            conn.executescript('''
                create table blog_note (id integer primary key, title text, body text);
                insert into blog_note values (1, 'Old title', 'Old body');
                create virtual table blog_note_fts using fts5(title, note, content="blog_note");
                create trigger blog_note_ai after insert on blog_note begin
                    insert into blog_note_fts(rowid, title, note) values (new.id, new.title, new.note);
                end;
                create table preserved_data (value text);
                insert into preserved_data values ('Keep downloaded enrichment data');
            ''')
            with pytest.raises(sqlite3.OperationalError, match="no such column: T.note"):
                conn.execute("select count(*) from blog_note_fts").fetchone()

    workflow = yaml.safe_load((ROOT / ".github/workflows/backup.yml").read_text())
    steps = {step["name"]: step for step in workflow["jobs"]["build_and_deploy"]["steps"] if "name" in step}
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    # Repeated runs exercise both fresh and restored DBs and FTS reconfiguration.
    for _ in range(2):
        for name in ("Build database", "Configure FTS"):
            subprocess.run(["bash", "-e", "-c", steps[name]["run"]], cwd=tmp_path, env=env, check=True, capture_output=True)
        with sqlite3.connect(database) as conn:
            assert conn.execute("select count(*) from blog_note_fts").fetchone()[0] == 1
            assert conn.execute("select rowid from blog_note_fts where blog_note_fts match 'platypus'").fetchall() == [(1,)]
            conn.execute("update blog_note set body = 'updated wombat' where id = 1")
            assert conn.execute("select rowid from blog_note_fts where blog_note_fts match 'wombat'").fetchall() == [(1,)]
            assert conn.execute("select rowid from blog_note_fts where blog_note_fts match 'platypus'").fetchall() == []
            if restore_previous_database:
                assert conn.execute("select value from preserved_data").fetchone()[0] == 'Keep downloaded enrichment data'
