"""
Daily profile stats updater for PabloJustDevelops (adapted from Andrew6rant's approach).

Fetches repository, LOC, commit and contribution counts from the GitHub
GraphQL API and rewrites the numbers inside dark_mode.svg and light_mode.svg.

Run with:
    ACCESS_TOKEN=<token> USER_NAME=PabloJustDevelops python today.py
"""

import calendar
import http.client
import json
import os
import random
import re
import socket
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

ACCESS_TOKEN = os.environ['ACCESS_TOKEN']
USER_NAME = os.environ.get('USER_NAME', 'PabloJustDevelops')
GRAPHQL_URL = 'https://api.github.com/graphql'
ET.register_namespace('', 'http://www.w3.org/2000/svg')
BIRTHDAY = (2006, 10, 11)  # (year, month, day)

# Network policy: GitHub's GraphQL endpoint answers with 502/503/504 and
# occasional hangs; a single one of those must not fail the whole run.
REQUEST_TIMEOUT = float(os.environ.get('GRAPHQL_TIMEOUT', '45'))
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
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode('utf-8'))
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


def fetch_commits_for_repo(repo_name, total_commits):
    """Count additions and deletions for a single repo across all commits."""
    owner, name = repo_name.split('/')
    additions = 0
    deletions = 0
    my_commits = 0
    cursor = None
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
        for edge in history.get('edges', []):
            node = edge.get('node', {})
            author = (node.get('author') or {}).get('user') or {}
            if author.get('id') == OWNER_ID:
                additions += node.get('additions') or 0
                deletions += node.get('deletions') or 0
                my_commits += 1
        if not history.get('pageInfo', {}).get('hasNextPage'):
            break
        cursor = history['pageInfo']['endCursor']
    return additions, deletions, my_commits


def fetch_repos_and_loc():
    """Total repos, LOC and per-repo commit stats."""
    repos = get_all_repos()
    total_repos = len(repos)
    total_additions = 0
    total_deletions = 0
    total_commits = 0
    for repo in repos:
        name = repo.get('nameWithOwner', '')
        if not name:
            continue
        history_count = 0
        ref = repo.get('defaultBranchRef')
        if ref and ref.get('target', {}).get('history'):
            history_count = ref['target']['history'].get('totalCount') or 0
        if history_count == 0:
            continue
        add, dele, commits = fetch_commits_for_repo(name, history_count)
        total_additions += add
        total_deletions += dele
        total_commits += commits
    loc = total_additions - total_deletions
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
    for svg in SVGS:
        svg_overwrite(svg, stats, age)

    bumped = bump_readme_cache()
    print('Stats en el diseño: ' + (', '.join(f'{k}={v}' for k, v in sorted(stats.items())) or 'ninguna'))
    print(f'Updated: age={age}')
    if bumped:
        print(f'Cache: bumped ?v= in README.md ({bumped} occurrence(s))')
    else:
        print('Cache: no ?v= found in README.md')
