import requests
import os
import base64
import tomli
import re
from packaging.version import Version

ORG = "TutteInstitute"
ADDITIONAL_REPOS = [
    {"owner": "lmcinnes", "repo_name": "umap"},
    {"owner": "scikit-learn-contrib", "repo_name": "hdbscan"},
    {"owner": "lmcinnes", "repo_name": "pynndescent"},
    {"owner": "lmcinnes", "repo_name": "glasbey"}
    ]

REPOS_TO_IGNORE = [
    {"owner": "TutteInstitute", "repo_name": "temporal-mapper"}
]

N_RELEASES = int(os.getenv("N_RELEASES", 5))
# This is optional in case of rate limiting
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

HEADERS = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

def github_get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def list_org_repos():
    repos = []
    page = 1

    while True:
        data = github_get(
            f"https://api.github.com/orgs/{ORG}/repos",
            {"per_page": 100, "page": page},
        )
        
        if not data:
            break

        repos.extend([{"owner": ORG, "repo_name": r["name"]} for r in data])
        page += 1

    return repos

def get_file(owner, repo, path):
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    r = requests.get(url, headers=HEADERS, timeout=10)

    if r.status_code == 404:
        return None

    r.raise_for_status()
    content = base64.b64decode(r.json()["content"])
    return content.decode()

def extract_name_from_pyproject(text):
    try:
        data = tomli.loads(text)

        if "project" in data and "name" in data["project"]:
            return data["project"]["name"]

        if "tool" in data and "poetry" in data["tool"]:
            return data["tool"]["poetry"].get("name")

    except Exception:
        pass

    return None

def extract_name_from_setup(text):
    m = re.search(r"name\s*=\s*[\"']([^\"']+)[\"']", text)
    if m:
        return m.group(1)
    return None

def get_package_name(owner, repo):
    pyproject = get_file(owner, repo, "pyproject.toml")

    if pyproject:
        name = extract_name_from_pyproject(pyproject)
        if name:
            return name

    setup = get_file(owner, repo, "setup.py")

    if setup:
        name = extract_name_from_setup(setup)
        if name:
            return name

    return None

def get_github_releases(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"

    data = github_get(url, {"per_page": N_RELEASES})

    versions = []

    for r in data:
        tag = r["tag_name"].lstrip("v")

        try:
            versions.append(Version(tag))
        except Exception:
            pass

    return versions

def get_pypi_versions(package):
    url = f"https://pypi.org/pypi/{package}/json"
    r = requests.get(url, timeout=10)

    if r.status_code == 404:
        return set()

    r.raise_for_status()
    data = r.json()
    versions = set()

    for v in data["releases"]:
        try:
            versions.add(Version(v))
        except Exception:
            pass

    return versions


def check_repo(repo):
    repo_str = f"""{repo["owner"]}/{repo["repo_name"]}"""
    try:
        package = get_package_name(repo["owner"], repo["repo_name"])

        if not package:
            return ("SKIP", repo, "no python package")

        gh_versions = get_github_releases(repo["owner"], repo["repo_name"])
        pypi_versions = get_pypi_versions(package)

        missing = [str(v) for v in gh_versions if v not in pypi_versions]

        if missing:
            return ("MISSING", repo_str, package, missing)

        return ("OK", repo_str, package)

    except Exception as e:
        return ("ERROR", repo_str, str(e))


def main():
    repos = list_org_repos()
    print(f"Found {len(repos)} repositories in {ORG}")
    # Add additional repos which are not in TutteInstitute
    repos.extend(ADDITIONAL_REPOS)

    failures = False

    for repo in repos:
        result = check_repo(repo)
        repo_str = f"""{repo["owner"]}/{repo["repo_name"]}"""

        if repo in REPOS_TO_IGNORE:
            print(f"IGNORE  {repo_str} {result[2]}")
            continue

        if result[0] == "OK":
            print(f"OK      {repo_str} ({result[2]})")

        elif result[0] == "MISSING":
            failures = True
            print(
                f"MISSING {repo_str} pkg={result[2]} versions={','.join(result[3])}"
            )

        elif result[0] == "SKIP":
            print(f"SKIP    {repo_str} {result[2]}")

        else:
            failures = True
            print(f"ERROR   {repo_str} {result[2]}")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()