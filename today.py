"""
Daily profile stats updater for PabloJustDevelops (adapted from Andrew6rant's approach).

Fetches repository, star, follower and yearly contribution counts from the
GitHub REST API and rewrites the numbers inside dark_mode.svg and light_mode.svg.

Uses the REST API so it works with a fine-grained token that has
Metadata: Read-only on the profile repository (public data).

Run with:
    ACCESS_TOKEN=<token> USER_NAME=PabloJustDevelops python today.py
"""

import json
import os
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

ACCESS_TOKEN = os.environ['ACCESS_TOKEN']
USER_NAME = os.environ.get('USER_NAME', 'PabloJustDevelops')
API_URL = 'https://api.github.com'
ET.register_namespace('', 'http://www.w3.org/2000/svg')


def rest_get(path, params=''):
    """GET a REST endpoint with the token and return parsed JSON."""
    request = urllib.request.Request(
        f'{API_URL}{path}?{params}' if params else f'{API_URL}{path}',
        headers={'Authorization': 'token ' + ACCESS_TOKEN, 'Accept': 'application/vnd.github+json'},
        method='GET',
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise Exception(f'REST request failed ({error.code}) for {path}: {error.read().decode()[:400]}')


def fetch_repos_and_stars():
    """Public owned repos and their total stars (paginated)."""
    repos = []
    page = 1
    while True:
        batch = rest_get(
            f'/users/{USER_NAME}/repos',
            f'type=owner&per_page=100&page={page}',
        )
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    total = len(repos)
    stars = sum(repo.get('stargazers_count') or 0 for repo in repos)
    return total, stars


def fetch_followers():
    """Total follower count."""
    user = rest_get(f'/users/{USER_NAME}')
    return user.get('followers') or 0


def graphql(query, variables):
    """POST a GraphQL query and return the parsed JSON response."""
    body = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    request = urllib.request.Request(
        'https://api.github.com/graphql',
        data=body,
        headers={'Authorization': 'token ' + ACCESS_TOKEN, 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise Exception(f'GraphQL request failed ({error.code}): {error.read().decode()[:400]}')


def fetch_year_commits():
    """Contributions in the last 365 days via the GraphQL contribution calendar."""
    from datetime import datetime, timedelta, timezone
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
    return data['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions']


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


def svg_overwrite(filename, repo_data, star_data, follower_data, commit_data):
    """Rewrite the stats placeholders inside one SVG file."""
    tree = ET.parse(filename)
    root = tree.getroot()
    justify_format(root, 'repo_data', repo_data, 6)
    justify_format(root, 'star_data', star_data, 7)
    justify_format(root, 'follower_data', follower_data, 4)
    justify_format(root, 'commit_data', commit_data, 8)
    tree.write(filename, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    repos, stars = fetch_repos_and_stars()
    followers = fetch_followers()
    try:
        commits = fetch_year_commits()
    except Exception as error:
        print(f'WARN: could not fetch yearly commits ({error}); keeping previous value')
        commits = 0
    for svg in ('dark_mode.svg', 'light_mode.svg'):
        svg_overwrite(svg, repos, stars, followers, commits)
    print(f'Updated: {repos} repos, {stars} stars, {followers} followers, {commits} commits (year)')
