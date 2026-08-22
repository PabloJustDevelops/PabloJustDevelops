"""
Daily profile stats updater for PabloJustDevelops (adapted from Andrew6rant's approach).

Fetches repository, star, follower and yearly contribution counts from the
GitHub API and rewrites the numbers inside dark_mode.svg and light_mode.svg.

Standard-library only, so it runs anywhere without pip installs.

Run with:
    ACCESS_TOKEN=<token> USER_NAME=PabloJustDevelops python today.py
"""

import json
import os
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ACCESS_TOKEN = os.environ['ACCESS_TOKEN']
USER_NAME = os.environ.get('USER_NAME', 'PabloJustDevelops')
GRAPHQL_URL = 'https://api.github.com/graphql'
ET.register_namespace('', 'http://www.w3.org/2000/svg')


def graphql(query, variables):
    """POST a GraphQL query and return the parsed JSON response."""
    body = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={'Authorization': 'token ' + ACCESS_TOKEN, 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise Exception(f'GraphQL request failed with {error.code}: {error.read().decode()[:500]}')


def fetch_repos_and_stars():
    """Total owned repos and stars across them."""
    query = '''
    query($login: String!) {
        user(login: $login) {
            repositories(ownerAffiliations: OWNER, first: 100) {
                totalCount
                nodes { stargazers { totalCount } }
            }
        }
    }'''
    data = graphql(query, {'login': USER_NAME})
    user = data['data']['user']
    repos = user['repositories']['totalCount']
    stars = sum(node['stargazers']['totalCount'] for node in user['repositories']['nodes'])
    return repos, stars


def fetch_followers():
    """Total follower count."""
    query = '''
    query($login: String!) {
        user(login: $login) { followers { totalCount } }
    }'''
    data = graphql(query, {'login': USER_NAME})
    return data['data']['user']['followers']['totalCount']


def fetch_year_commits():
    """Contributions in the last 365 days."""
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
    commits = fetch_year_commits()
    for svg in ('dark_mode.svg', 'light_mode.svg'):
        svg_overwrite(svg, repos, stars, followers, commits)
    print(f'Updated: {repos} repos, {stars} stars, {followers} followers, {commits} commits (year)')
