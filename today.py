"""
Daily profile stats updater for PabloJustDevelops (adapted from Andrew6rant's approach).

Fetches repository, LOC, commit and contribution counts from the GitHub
GraphQL API and rewrites the numbers inside dark_mode.svg and light_mode.svg.

Run with:
    ACCESS_TOKEN=<token> USER_NAME=PabloJustDevelops python today.py
"""

import calendar
import hashlib
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
import queue
import threading
import random
import re
import socket
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ACCESS_TOKEN = os.environ['ACCESS_TOKEN']
USER_NAME = os.environ.get('USER_NAME', 'PabloJustDevelops')
GRAPHQL_URL = 'https://api.github.com/graphql'
ET.register_namespace('', 'http://www.w3.org/2000/svg')
BIRTHDAY = (2006, 10, 11)  # (year, month, day)

# Network policy: GitHub's GraphQL endpoint answers with 502/503/504 and
# occasional hangs; a single one of those must not fail the whole run.
REQUEST_TIMEOUT = float(os.environ.get('GRAPHQL_TIMEOUT', '45'))
STATS_WORKERS = int(os.environ.get('STATS_WORKERS', '12'))   # peticiones en paralelo
CACHE_FILE = 'cache/loc-stats.json'
FULL_REFRESH_DAYS = int(os.environ.get('STATS_FULL_REFRESH_DAYS', '30'))
MAX_DELTA_COMMITS = 3000          # por encima de esto, recorrido completo
REFRESH_SLICE = int(os.environ.get('STATS_REFRESH_SLICE', '8'))   # repos a revalidar por run
MAX_ATTEMPTS = int(os.environ.get('GRAPHQL_MAX_ATTEMPTS', '6'))
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
TRANSIENT_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    socket.timeout,
    ConnectionError,
    http.client.HTTPException,
    json.JSONDecodeError,
)


def retry_delay(attempt, retry_after=None):
    """Exponential backoff with jitter, honouring a Retry-After header."""
    if retry_after:
        try:
            return min(float(retry_after), 90.0)
        except (TypeError, ValueError):
            pass
    base = min(60.0, 2.0 ** (attempt - 1))  # 1, 2, 4, 8, 16, 32 s
    return base + random.uniform(0, base * 0.25)


def calculate_age():
    """Calculate age from BIRTHDAY to today and return a formatted string."""
    today = date.today()
    years = today.year - BIRTHDAY[0] - ((today.month, today.day) < (BIRTHDAY[1], BIRTHDAY[2]))
    months = today.month - BIRTHDAY[1]
    if months < 0:
        months += 12
    days = today.day - BIRTHDAY[2]
    if days < 0:
        months -= 1
        prev_month = today.month - 1 if today.month > 1 else 12
        days += calendar.monthrange(today.year, prev_month)[1]
    return f'{years} years, {months} months, {days} days'


def open_with_deadline(request, deadline):
    """urllib no tiene timeout total: un watchdog corta a los `deadline` segundos.

    Sin esto una respuesta que gotea se queda minutos (el 502 que tumbó el run
    del 23-oct tardó ~6 min en llegar con timeout de socket ya puesto).
    """
    result = queue.Queue(maxsize=1)

    def worker():
        try:
            with urllib.request.urlopen(request, timeout=deadline) as response:
                result.put(('ok', response.read()))
        except BaseException as error:      # se re-lanza en el hilo llamante
            result.put(('error', error))

    threading.Thread(target=worker, daemon=True).start()
    try:
        kind, payload = result.get(timeout=deadline)
    except queue.Empty:
        raise TimeoutError(f'sin respuesta en {deadline:.0f}s')
    if kind == 'error':
        raise payload
    return payload


def graphql(query, variables, attempts=None):
    """POST a GraphQL query, retrying transient failures with backoff.

    GitHub's API is not always reliable: 502/503/504 from its edge and
    read timeouts happen. Those are retried; auth and query errors are not.
    """
    body = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    max_attempts = attempts or MAX_ATTEMPTS
    last_error = 'no attempt made'
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            GRAPHQL_URL,
            data=body,
            headers={'Authorization': 'token ' + ACCESS_TOKEN, 'Content-Type': 'application/json'},
            method='POST',
        )
        delay = None
        try:
            return json.loads(open_with_deadline(request, REQUEST_TIMEOUT).decode('utf-8'))
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')[:400]
            retryable = error.code in RETRYABLE_STATUS or (
                error.code == 403 and 'rate limit' in detail.lower()
            )
            if not retryable:
                raise Exception(f'GraphQL request failed ({error.code}): {detail}')
            last_error = f'HTTP {error.code}: {detail[:120].strip()}'
            delay = retry_delay(attempt, error.headers.get('Retry-After') if error.headers else None)
        except TRANSIENT_ERRORS as error:
            last_error = f'{type(error).__name__}: {error}'
            delay = retry_delay(attempt)
        if attempt < max_attempts:
            print(f'::warning::GraphQL attempt {attempt}/{max_attempts} failed ({last_error}); retrying in {delay:.1f}s', flush=True)
            time.sleep(delay)
    raise Exception(f'GraphQL request failed after {max_attempts} attempts: {last_error}')


def graphql_data(data, *path, default=None):
    """Safely walk nested GraphQL responses; raise a clear error on failure."""
    errors = data.get('errors')
    if errors:
        messages = '; '.join(e.get('message', str(e)) for e in errors)
        raise Exception(f'GraphQL errors: {messages}')
    node = data.get('data')
    for key in path:
        if node is None:
            return default
        node = node.get(key)
    return node if node is not None else default


def get_owner_id():
    """Get the account ID for GraphQL user queries."""
    query = '''
    query($login: String!) {
        user(login: $login) { id }
    }'''
    data = graphql(query, {'login': USER_NAME})
    user_id = graphql_data(data, 'user', 'id')
    if not user_id:
        raise Exception(f'Could not resolve user id for {USER_NAME!r}')
    return user_id


def get_all_repos():
    """Return all repositories the user owns, collaborates on, or has contributed to."""
    repos = {}

    # Owned + collaborator repos (paginated)
    cursor = None
    while True:
        query = '''
        query($login: String!, $cursor: String) {
            user(login: $login) {
                repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER, COLLABORATOR]) {
                    nodes {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history { totalCount }
                                }
                            }
                        }
                    }
                    pageInfo { endCursor hasNextPage }
                }
            }
        }'''
        data = graphql(query, {'login': USER_NAME, 'cursor': cursor})
        repo_data = graphql_data(data, 'user', 'repositories', default={})
        for node in repo_data.get('nodes', []):
            if not node:
                continue
            name = node.get('nameWithOwner')
            if name:
                repos[name] = node
        page_info = repo_data.get('pageInfo', {})
        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')

    # Repos contributed to (paginated, excluding already-owned repos)
    cursor = None
    while True:
        query = '''
        query($login: String!, $cursor: String) {
            user(login: $login) {
                repositoriesContributedTo(first: 100, after: $cursor, includeUserRepositories: false) {
                    nodes {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history { totalCount }
                                }
                            }
                        }
                    }
                    pageInfo { endCursor hasNextPage }
                }
            }
        }'''
        data = graphql(query, {'login': USER_NAME, 'cursor': cursor})
        contributed = graphql_data(data, 'user', 'repositoriesContributedTo', default={})
        for node in contributed.get('nodes', []):
            if not node:
                continue
            name = node.get('nameWithOwner')
            if name and name not in repos:
                repos[name] = node
        page_info = contributed.get('pageInfo', {})
        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')

    return list(repos.values())


def fetch_commits_for_repo(repo_name, total_commits, max_commits=None):
    """Count additions and deletions for a single repo across all commits.

    `max_commits` corta el recorrido: con caché solo interesan los commits
    nuevos (los más recientes). Se corta por número de commits, no por página:
    una página trae 100 y sumarlos todos inflaría el total.
    """
    owner, name = repo_name.split('/')
    additions = 0
    deletions = 0
    my_commits = 0
    cursor = None
    seen = 0
    while True:
        variables = {'owner': owner, 'name': name, 'cursor': cursor}
        query = '''
        query($owner: String!, $name: String!, $cursor: String) {
            repository(name: $name, owner: $owner) {
                defaultBranchRef {
                    target {
                        ... on Commit {
                            history(first: 100, after: $cursor) {
                                edges {
                                    node {
                                        author { user { id } }
                                        additions
                                        deletions
                                    }
                                }
                                pageInfo { endCursor hasNextPage }
                            }
                        }
                    }
                }
            }
        }'''
        data = graphql(query, variables)
        ref = graphql_data(data, 'repository', 'defaultBranchRef')
        if not ref or not ref.get('target', {}).get('history'):
            break
        history = ref['target']['history']
        stop = False
        for edge in history.get('edges', []):
            if max_commits is not None and seen >= max_commits:
                stop = True
                break
            seen += 1
            node = edge.get('node', {})
            author = (node.get('author') or {}).get('user') or {}
            if author.get('id') == OWNER_ID:
                additions += node.get('additions') or 0
                deletions += node.get('deletions') or 0
                my_commits += 1
        if stop or not history.get('pageInfo', {}).get('hasNextPage'):
            break
        cursor = history['pageInfo']['endCursor']
    return additions, deletions, my_commits


def load_stats_cache():
    try:
        data = json.loads(Path(CACHE_FILE).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_stats_cache(repos):
    Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(CACHE_FILE).write_text(
        json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'repos': repos}, indent=1, sort_keys=True) + '\n',
        encoding='utf-8')


def cache_age_days(cache):
    stamp = cache.get('generated_at')
    if not stamp:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() / 86400
    except ValueError:
        return None


def fetch_repos_and_loc():
    """Total repos, LOC y commits, con caché por repo.

    Recorrer el historial entero cuesta una petición por cada 100 commits y eso
    era el 95% del tiempo del job (11 min). Ahora: si el repo no ha cambiado se
    reutiliza su entrada (0 peticiones), si tiene commits nuevos se recorren
    solo las páginas nuevas, y cada `FULL_REFRESH_DAYS` se rehace entero para
    que no se quede pegado a un historial reescrito.
    """
    repos = get_all_repos()
    total_repos = len(repos)
    cache = load_stats_cache()
    age = cache_age_days(cache)
    entries = dict(cache.get('repos', {}))
    generated = cache.get('generated_at')
    for entry in entries.values():
        entry.setdefault('full_at', generated)

    # El refresco completo se reparte: como mucho REFRESH_SLICE repos por run, los
    # más viejos primero. Así ningún run se va a minutos y todo se revalida en unos días.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=FULL_REFRESH_DAYS)).isoformat(timespec='seconds')
    due = sorted(name for name, e in entries.items()
                 if not e.get('full_at') or e['full_at'] < cutoff)
    refresh_slice = set(due[:REFRESH_SLICE])

    names_now, reusable, plan = set(), [], []
    for repo in repos:
        name = repo.get('nameWithOwner', '')
        if not name:
            continue
        ref = repo.get('defaultBranchRef')
        commits_now = 0
        if ref and ref.get('target', {}).get('history'):
            commits_now = ref['target']['history'].get('totalCount') or 0
        if commits_now == 0:
            entries.pop(name, None)
            continue
        names_now.add(name)
        entry = entries.get(name)
        if name not in refresh_slice and entry and entry.get('commits') == commits_now:
            reusable.append(name)
            continue
        delta = commits_now - (entry or {}).get('commits', 0)
        if entry and name not in refresh_slice and 0 < delta <= MAX_DELTA_COMMITS:
            mode = 'delta'                     # solo las páginas nuevas
        else:
            mode = 'full'                      # alta, reescritura o revalidación
        plan.append((name, mode, commits_now, entry or {}, delta))

    started = time.monotonic()

    def work(item):
        name, mode, commits_now, entry, delta = item
        # en delta solo cuentan los commits nuevos, no la página entera
        limit = None if mode == 'full' else max(1, delta)
        add, dele, mine = fetch_commits_for_repo(name, commits_now, limit)
        if mode == 'delta':
            add += entry.get('additions', 0)
            dele += entry.get('deletions', 0)
            mine += entry.get('mine', 0)
        entry = {'commits': commits_now, 'additions': add, 'deletions': dele, 'mine': mine}
        if mode == 'full':
            entry['full_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        else:
            entry['full_at'] = (entries.get(name) or {}).get('full_at')
        return name, entry

    failures = []
    with ThreadPoolExecutor(max_workers=max(1, STATS_WORKERS)) as pool:
        futures = [pool.submit(work, item) for item in plan]
        for future, item in zip(futures, plan):
            try:
                name, entry = future.result()
                entries[name] = entry
            except Exception as error:      # no se inventan cifras: se aborta
                failures.append(f'{item[0]}: {error}')
    if failures:
        raise Exception(f'No se pudieron leer {len(failures)} repo(s): ' + '; '.join(failures[:3]))

    current = set(entries) & set(names_now)
    totals = [entries[name] for name in current]
    total_additions = sum(t.get('additions', 0) for t in totals)
    total_deletions = sum(t.get('deletions', 0) for t in totals)
    total_commits = sum(t.get('mine', 0) for t in totals)
    loc = total_additions - total_deletions

    save_stats_cache(entries)
    print(f'Stats: {len(plan)} a consultar (reutilizados {len(reusable)}, '
          f'completos {sum(1 for p in plan if p[1] == "full")}) en '
          f'{time.monotonic() - started:.1f}s con {STATS_WORKERS} hilos', flush=True)
    return total_repos, total_commits, total_additions, total_deletions, loc


def fetch_contributed_repos():
    """Count repos the user owns/collaborates on, and repos contributed to."""
    query = '''
    query($login: String!) {
        user(login: $login) {
            repositories(first: 100, ownerAffiliations: [OWNER, COLLABORATOR]) { totalCount }
            repositoriesContributedTo(first: 100, includeUserRepositories: false) { totalCount }
        }
    }'''
    data = graphql(query, {'login': USER_NAME})
    owned = graphql_data(data, 'user', 'repositories', 'totalCount', default=0)
    contributed = graphql_data(data, 'user', 'repositoriesContributedTo', 'totalCount', default=0)
    return owned, contributed


def fetch_year_commits():
    """Contributions in the last 365 days via the contribution calendar."""
    since = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    query = '''
    query($login: String!, $from: DateTime!) {
        user(login: $login) {
            contributionsCollection(from: $from) {
                contributionCalendar { totalContributions }
            }
        }
    }'''
    data = graphql(query, {'login': USER_NAME, 'from': since})
    return graphql_data(data, 'user', 'contributionsCollection', 'contributionCalendar', 'totalContributions', default=0)


def justify_format(root, element_id, new_text, length=0):
    """Update an element's text and adjust the preceding dots for alignment."""
    new_text = str(new_text)
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_map = {0: '', 1: ' ', 2: '. '}
        dot_string = dot_map[just_len]
    else:
        dot_string = ' ' + ('.' * just_len) + ' '
    dots = root.find(f".//*[@id='{element_id}_dots']")
    if dots is not None:
        dots.text = dot_string


STAT_IDS = (('repo_data', 6), ('contrib_data', 0), ('commit_data', 10),
           ('loc_data', 10), ('loc_add', 10), ('loc_del', 10))
SVGS = ('dark_mode.svg', 'light_mode.svg')


def stats_used():
    """Qué ids de estadística existen de verdad en los SVG (el diseño puede no tenerlos)."""
    markup = ''.join(open(f, encoding='utf-8').read() for f in SVGS)
    return {element_id for element_id, _ in STAT_IDS if f'id="{element_id}"' in markup}


def svg_overwrite(filename, stats, age_data=None):
    """Rewrite the stats placeholders that exist inside one SVG file."""
    tree = ET.parse(filename)
    root = tree.getroot()
    for element_id, width in STAT_IDS:
        if element_id in stats:
            justify_format(root, element_id, stats[element_id], width)
    if age_data is not None:
        element = root.find(".//*[@id='age_data']")
        if element is not None:
            element.text = age_data
    tree.write(filename, encoding='utf-8', xml_declaration=True)


def bump_readme_cache():
    """Increment the ?v=<n> cache-busting parameter in README.md."""
    with open('README.md', 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = re.compile(r'\?v=(\d+)')

    def increment(match):
        return f'?v={int(match.group(1)) + 1}'

    new_content, count = pattern.subn(increment, content)
    if count > 0:
        with open('README.md', 'w', encoding='utf-8') as f:
            f.write(new_content)
    return count


if __name__ == '__main__':
    needed = stats_used()
    stats = {}
    if needed & {'repo_data', 'contrib_data'}:
        OWNER_ID = globals().get('OWNER_ID') or get_owner_id()
        globals()['OWNER_ID'] = OWNER_ID
        owned, contributed = fetch_contributed_repos()
        stats['repo_data'], stats['contrib_data'] = owned, contributed
    if 'commit_data' in needed:
        stats['commit_data'] = fetch_year_commits()
    if needed & {'loc_data', 'loc_add', 'loc_del'}:
        _, _, add, dele, loc = fetch_repos_and_loc()
        stats.update(loc_data=loc, loc_add=add, loc_del=dele)

    age = calculate_age()
    before = {svg: hashlib.sha256(open(svg, 'rb').read()).hexdigest() for svg in SVGS}
    for svg in SVGS:
        svg_overwrite(svg, stats, age)
    changed = [svg for svg in SVGS
               if hashlib.sha256(open(svg, 'rb').read()).hexdigest() != before[svg]]

    # sin cambios reales no hay nada que cachear: evita commits que solo suben ?v=
    bumped = bump_readme_cache() if changed else 0
    print('SVG modificados: ' + (', '.join(changed) or 'ninguno'))
    print('Stats en el diseño: ' + (', '.join(f'{k}={v}' for k, v in sorted(stats.items())) or 'ninguna'))
    print(f'Updated: age={age}')
    if bumped:
        print(f'Cache: bumped ?v= in README.md ({bumped} occurrence(s))')
    elif changed:
        print('Cache: no ?v= found in README.md')
    else:
        print('Cache: sin cambios en los SVG, no se toca el README')
