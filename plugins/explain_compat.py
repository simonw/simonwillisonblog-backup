"""Adapt datasette-explain 0.2.1 to read-only stored-query pages."""

import datasette_explain

# Datasette 1.0 uses a <pre> rather than a CodeMirror editor for stored SQL.
# Keep the pinned plugin's renderer and endpoint, but read either kind of SQL.
datasette_explain.JS = datasette_explain.JS.replace(
    "const sqlForm = document.querySelector('form.sql');",
    "const sqlForm = document.querySelector('form.sql');\n" "    if (!sqlForm) return;",
).replace(
    "const sql = editor.state.doc.toString();",
    "const sql = window.editor ? window.editor.state.doc.toString()\n"
    "            : (document.querySelector('pre#sql-query')?.textContent\n"
    "                || formData.sql || '');",
)
