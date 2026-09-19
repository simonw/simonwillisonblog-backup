"""OpenAI key input for the blog's stored queries on Datasette 1.0."""

from urllib.parse import unquote

from datasette import hookimpl


def blog_parameter(key, request):
    if key != "openai_api_key":
        raise KeyError(key)
    return unquote(request.cookies.get("openai_api_key", ""))


@hookimpl
def register_magic_parameters():
    return [("blog", blog_parameter)]


@hookimpl
def extra_body_script(template, database, request):
    if (
        template != "query.html"
        or database != "simonwillisonblog"
        or request.url_vars.get("table") not in {"embedding_search", "answer_question"}
    ):
        return ""
    # The input deliberately has no name: API keys must not enter the query URL.
    return """
(() => {
    const form = document.querySelector('form.sql');
    if (!form) return;
    const p = document.createElement('p');
    const label = document.createElement('label');
    label.textContent = 'OpenAI API key ';
    const input = document.createElement('input');
    input.type = 'password';
    input.id = 'openai-api-key';
    input.autocomplete = 'off';
    label.htmlFor = input.id;
    p.append(label, input);
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.textContent = 'Forget key';
    p.append(clear);
    form.prepend(p);
    const hasKey = () => document.cookie.split(';').some(
        c => c.trim().startsWith('openai_api_key=') && c.trim() !== 'openai_api_key='
    );
    const refresh = () => {
        input.placeholder = hasKey() ? 'Key saved in this browser' : 'Enter your API key';
        clear.hidden = !hasKey();
    };
    clear.addEventListener('click', () => {
        document.cookie = 'openai_api_key=; Path=/; Max-Age=0; SameSite=Lax';
        input.value = '';
        refresh();
    });
    form.addEventListener('submit', () => {
        if (input.value.trim()) {
            document.cookie = 'openai_api_key=' + encodeURIComponent(input.value.trim())
                + '; Path=/; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '');
            input.value = '';
        }
    });
    refresh();
})();
"""
