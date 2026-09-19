# simonwillisonblog-backup

Uses [db-to-sqlite](https://github.com/simonw/db-to-sqlite) and [sqlite-diffable](https://github.com/simonw/sqlite-diffable) to pull a backup of the Heroku PostgreSQL database running https://simonwillison.net/ and store it as newline-delimited JSON in this GitHub repository.

Runs as a GitHub Actions workflow, see [.github/workflows/backup.yml](https://github.com/simonw/simonwillisonblog-backup/blob/main/.github/workflows/backup.yml).

Deploys a Datasette instance to https://datasette.simonwillison.net/

## Datasette 1.0a40

The deployed runtime and plugin versions are pinned in [requirements-datasette.txt](requirements-datasette.txt). GraphQL 3.0a1 and search-all 1.1.5a0 support Datasette's new permissions APIs. `httpx` is explicitly installed for datasette-openai. [metadata.yml](metadata.yml) contains descriptive metadata; [datasette.yml](datasette.yml) contains settings, plugin configuration, and stored queries.

The project plugin in [plugins/openai_cookie.py](plugins/openai_cookie.py) replaces datasette-cookies-for-magic-parameters, which uses a removed Datasette API. The embedding and question pages let visitors save or forget their OpenAI API key in a browser cookie. The input has no form name, so keys are never submitted in query URLs. Queries without a key do not call OpenAI. Tests mock OpenAI responses; they do not verify the availability of the external models or services.

The small adapter in [plugins/explain_compat.py](plugins/explain_compat.py) lets datasette-explain read SQL from both editable queries and the read-only stored-query display.

### Run locally and test

```sh
uv venv --python 3.11
uv pip install -r requirements-test.txt
curl -fL https://datasette.simonwillison.net/simonwillisonblog.db -o simonwillisonblog.db
uv run datasette -i simonwillisonblog.db -m metadata.yml -c datasette.yml --plugins-dir plugins
```

The downloaded database includes the embeddings needed by the FAISS plugin. Run the regression suite with `uv run python -m pytest -q`; it builds a small independent fixture database and makes no OpenAI requests.

### JSON API migration

This deployment adopts Datasette 1.0 defaults: `rows` contains objects keyed by column name, and additional response fields are opt-in. Callers that need array rows and column names can request `/simonwillisonblog/blog_entry.json?_shape=arrays&_extra=columns`. Add `_extra=count` for the matching row count, now returned as `count` instead of `filtered_table_rows_count`. Extras can be combined, for example `_extra=columns,count,database,table,primary_keys`. This is not a complete restoration of the old response envelope.

The SQL endpoint is now `/simonwillisonblog/-/query.json?sql=select+1`; the old `/simonwillisonblog.json?sql=select+1` URL redirects there. Stored query URLs, such as `/simonwillisonblog/recent_content.json`, are unchanged. See the [Datasette upgrade guide](https://docs.datasette.io/en/1.0a40/upgrade_guide.html) for other API changes.

### Package for Fly

```sh
uv run bash scripts/package-datasette.sh simonwillisonblog.db deployment
```

Packaging generates the Dockerfile and Fly configuration without contacting Fly. It copies the runtime requirements, project plugin, and Datasette configuration into the build context; datasette-publish-fly does not natively package the `-c` configuration file. The backup workflow deploys this directory using `flyctl deploy`. To inspect the container locally, run `docker build -t blog-datasette deployment` and `docker run --rm -p 8001:8080 blog-datasette`.
