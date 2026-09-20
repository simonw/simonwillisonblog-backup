import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys

from asgi_lifespan import LifespanManager
from datasette.app import Datasette
from datasette_graphql.utils import _schema_cache
import pytest
import pytest_asyncio
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "simonwillisonblog.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            create table blog_entry (id integer primary key, title text, body text, created text);
            create table blog_blogmark (id integer primary key, link_title text, created text);
            create table blog_quotation (id integer primary key, source text, quotation text, created text);
            create table blog_tag (id integer primary key, tag text unique);
            create table blog_entry_tags (id integer primary key, entry_id integer references blog_entry(id), tag_id integer references blog_tag(id));
            create table blog_entry_embeddings (id integer primary key, embedding blob);
            create virtual table blog_entry_fts using fts5(title, body, content=blog_entry);
            insert into blog_blogmark values (1, 'A link', '2026-09-18');
            insert into blog_quotation values (1, 'A source', 'A quotation', '2026-09-17');
            insert into blog_tag values (1, 'datasette');
            insert into blog_entry_tags values (1, 1, 1);
        """)
        for i in range(1, 13):
            conn.execute(
                "insert into blog_entry values (?, ?, ?, ?)",
                (i, f"Datasette entry {i}", "<p>Searchable content</p>", "2026-09-19"),
            )
            conn.execute(
                "insert into blog_entry_embeddings values (?, ?)",
                (i, struct.pack("1536f", *([float(i)] * 1536))),
            )
        conn.execute("insert into blog_entry_fts(blog_entry_fts) values ('rebuild')")
    return path


@pytest_asyncio.fixture
async def ds(database):
    # The GraphQL plugin caches schemas by database name across instances.
    _schema_cache.clear()
    datasette = Datasette(
        immutables=[str(database)],
        metadata=yaml.safe_load((ROOT / "metadata.yml").read_text()),
        config=yaml.safe_load((ROOT / "datasette.yml").read_text()),
    )
    async with LifespanManager(datasette.app()):
        yield datasette
    datasette.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/simonwillisonblog",
        "/simonwillisonblog/blog_entry",
        "/simonwillisonblog/blog_entry/1",
        "/-/search?q=Datasette",
        "/graphql/simonwillisonblog",
        "/simonwillisonblog/recent_content",
    ],
)
async def test_html(ds, path):
    response = await ds.client.get(path, headers={"accept": "text/html"})
    assert response.status_code == 200, response.text
    assert "Error 500" not in response.text


@pytest.mark.asyncio
async def test_graphql_data_and_pagination(ds):
    query = "{ blog_entry(first: 2) { totalCount nodes { id title } pageInfo { hasNextPage endCursor } } }"
    response = await ds.client.get(
        "/graphql/simonwillisonblog", params={"query": query}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]["blog_entry"]
    assert data["totalCount"] == 12
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["title"] == "Datasette entry 1"
    assert data["pageInfo"]["hasNextPage"]
    query = (
        "{ blog_entry(first: 2, after: "
        + json.dumps(data["pageInfo"]["endCursor"])
        + ") { nodes { id } } }"
    )
    response = await ds.client.get(
        "/graphql/simonwillisonblog", params={"query": query}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["blog_entry"]["nodes"][0]["id"] == 3


@pytest.mark.asyncio
async def test_search_json_contract(ds):
    # These are the parameters sent by the search-all JavaScript.
    response = await ds.client.get(
        "/simonwillisonblog/blog_entry.json",
        params={
            "_shape": "objects",
            "_labels": "on",
            "_extra": "count,database,table",
            "_size": 5,
            "_search": "Datasette",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["count"] == 12
    assert data["database"] == "simonwillisonblog"
    assert data["table"] == "blog_entry"
    assert len(data["rows"]) == 5
    assert data["rows"][0]["title"].startswith("Datasette")


@pytest.mark.asyncio
async def test_robots_and_canned_query(ds):
    response = await ds.client.get("/robots.txt")
    assert (
        response.text
        == yaml.safe_load((ROOT / "datasette.yml").read_text())["plugins"][
            "datasette-block-robots"
        ]["literal"]
    )
    response = await ds.client.get(
        "/simonwillisonblog/recent_content.json?_shape=objects"
    )
    assert response.status_code == 200, response.text
    assert {row["type"] for row in response.json()["rows"]} == {
        "entry",
        "blogmark",
        "quotation",
    }


@pytest.mark.asyncio
async def test_mcp(ds):
    headers = {"accept": "application/json, text/event-stream"}
    response = await ds.client.post(
        "/-/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )
    assert response.status_code == 200, response.text
    headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
    if session_id := response.headers.get("mcp-session-id"):
        headers["mcp-session-id"] = session_id
    await ds.client.post(
        "/-/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    response = await ds.client.post(
        "/-/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "execute_sql",
                "arguments": {
                    "database": "simonwillisonblog",
                    "sql": "select count(*) as n from blog_entry",
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["structuredContent"]["rows"] == [{"n": 12}]


def test_fly_package(database, tmp_path):
    output = tmp_path / "deployment"
    env = dict(
        os.environ,
        PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    )
    subprocess.run(
        ["bash", "scripts/package-datasette.sh", str(database), str(output)],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    assert (output / "datasette.yml").read_bytes() == (
        ROOT / "datasette.yml"
    ).read_bytes()
    assert (output / "requirements-datasette.txt").read_bytes() == (
        ROOT / "requirements-datasette.txt"
    ).read_bytes()
    assert (output / "simonwillisonblog.db").exists()
    dockerfile = (output / "Dockerfile").read_text()
    assert "-r requirements-datasette.txt" in dockerfile
    assert "--config datasette.yml" in dockerfile
    assert "1.0a2" not in dockerfile


@pytest.mark.asyncio
async def test_json_defaults_and_explicit_arrays(ds):
    path = "/simonwillisonblog/blog_entry.json"
    response = await ds.client.get(path + "?_size=1")
    assert response.status_code == 200
    assert isinstance(response.json()["rows"][0], dict)
    assert "columns" not in response.json()
    response = await ds.client.get(path + "?_size=1&_shape=arrays&_extra=columns,count")
    data = response.json()
    assert isinstance(data["rows"][0], list)
    assert data["columns"] == ["id", "title", "body", "created"]
    assert data["count"] == 12
    response = await ds.client.get("/simonwillisonblog.json?sql=select+1+as+one")
    assert response.status_code == 302
    response = await ds.client.get(response.headers["location"])
    assert response.json()["rows"] == [{"one": 1}]


@pytest.mark.asyncio
async def test_explain_on_stored_and_editable_queries(ds):
    for path in [
        "/simonwillisonblog/recent_content",
        "/simonwillisonblog/-/query?sql=select+1",
    ]:
        response = await ds.client.get(path)
        assert response.status_code == 200
    response = await ds.client.get("/simonwillisonblog/-/explain?sql=select+1")
    assert response.status_code == 200
    assert response.json()["ok"]
    assert response.json()["explain_tree"]
