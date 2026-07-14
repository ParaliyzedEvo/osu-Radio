import argparse
import os
import re

WIKI_PATH = "wiki/Home.md"

# Matches a top-level GFM checkbox line
CHECKBOX_RE = re.compile(r'^(?P<prefix>\s*-\s*\[)(?P<mark>[ xX])(?P<suffix>\]\s*)(?P<rest>.*)$')
# Matches the linked form once an item has been imported
LINK_RE = re.compile(r'^\[(?P<text>.+)\]\((?P<url>https://github\.com/[^)]+/issues/(?P<number>\d+))\)\s*$')


def sync_wiki_to_issues():
    import requests

    repo = os.environ["REPO"]  # "owner/name"
    owner, name = repo.split("/")
    token = os.environ["GH_TOKEN"]
    assignee = os.environ.get("ASSIGNEE", "ParaliyzedEvo")

    api = "https://api.github.com"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    note_body = (
        f"_Imported from the [wiki checklist](https://github.com/{repo}/wiki/Home)._\n\n"
        "Please clarify details here if needed, and add the appropriate labels."
    )

    def gh_get(url):
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def gh_post(url, json_body):
        resp = requests.post(url, headers=headers, json=json_body, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def gh_patch(url, json_body):
        resp = requests.patch(url, headers=headers, json=json_body, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def create_issue(title):
        data = gh_post(
            f"{api}/repos/{owner}/{name}/issues",
            {"title": title, "body": note_body, "assignees": [assignee]},
        )
        return data["number"], data["html_url"]

    def process_line(line):
        m = CHECKBOX_RE.match(line)
        if not m:
            return line, False

        checked = m.group("mark").lower() == "x"
        rest = m.group("rest").strip()
        link_match = LINK_RE.match(rest)

        if link_match:
            number = int(link_match.group("number"))
            text = link_match.group("text")
            try:
                issue = gh_get(f"{api}/repos/{owner}/{name}/issues/{number}")
            except requests.HTTPError as e:
                print(f"Warning: could not fetch issue #{number}: {e}")
                return line, False

            # Checkbox state -> issue state
            if checked and issue["state"] == "open":
                gh_patch(f"{api}/repos/{owner}/{name}/issues/{number}", {"state": "closed"})
            elif not checked and issue["state"] == "closed":
                gh_patch(f"{api}/repos/{owner}/{name}/issues/{number}", {"state": "open"})

            # Title text -> issue title
            if text != issue["title"]:
                gh_patch(f"{api}/repos/{owner}/{name}/issues/{number}", {"title": text})

            new_rest = f"[{text}]({link_match.group('url')})"
        else:
            if checked:
                return line, False  # pre-checked items are never imported

            title = rest
            if not title:
                return line, False

            number, url = create_issue(title)
            print(f"Created issue #{number} for '{title}'")
            new_rest = f"[{title}]({url})"

        new_line = f"{m.group('prefix')}{m.group('mark')}{m.group('suffix')}{new_rest}"
        return new_line, new_line != line

    with open(WIKI_PATH, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    any_changed = False
    out_lines = []
    for line in lines:
        new_line, changed = process_line(line)
        out_lines.append(new_line)
        any_changed = any_changed or changed

    if any_changed:
        with open(WIKI_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines) + "\n")
        print("Home.md updated.")
    else:
        print("No changes needed.")


def sync_issue_to_wiki():
    issue_number = os.environ["ISSUE_NUMBER"]
    issue_state = os.environ["ISSUE_STATE"]  # "open" or "closed"
    issue_title = os.environ["ISSUE_TITLE"]

    with open(WIKI_PATH, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    changed = False
    out_lines = []
    for line in lines:
        m = CHECKBOX_RE.match(line)
        if not m:
            out_lines.append(line)
            continue

        rest = m.group("rest").strip()
        link_match = LINK_RE.match(rest)
        if not link_match or link_match.group("number") != str(issue_number):
            out_lines.append(line)
            continue

        new_mark = "x" if issue_state == "closed" else " "
        new_rest = f"[{issue_title}]({link_match.group('url')})"
        new_line = f"{m.group('prefix')}{new_mark}{m.group('suffix')}{new_rest}"

        if new_line != line:
            changed = True
        out_lines.append(new_line)

    if changed:
        with open(WIKI_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines) + "\n")
        print(f"Updated wiki line for issue #{issue_number}")
    else:
        print(f"No matching/changed wiki line for issue #{issue_number}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["wiki-to-issues", "issue-to-wiki"])
    args = parser.parse_args()

    if args.mode == "wiki-to-issues":
        sync_wiki_to_issues()
    else:
        sync_issue_to_wiki()


if __name__ == "__main__":
    main()