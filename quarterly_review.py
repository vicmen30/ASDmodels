#!/usr/bin/env python3
"""
Quarterly deep review — runs Jan/Apr/Jul/Oct 1st via GitHub Actions.
Does a broader 6-month PubMed search per model, then uses Claude API
to review the new evidence and suggest updates to model descriptions.
Creates a GitHub Issue with the full review report.
Requires: ANTHROPIC_API_KEY secret in the repo.
"""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DATA_FILE = REPO_ROOT / "data" / "recent_papers.json"

from monthly_update import MODEL_QUERIES, pubmed_search, pubmed_fetch_summary, EUTILS_BASE

def fetch_abstract(pmid: str) -> str:
    """Fetch abstract text for a PMID."""
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": pmid,
        "rettype": "abstract",
        "retmode": "text",
        "tool": "asd-model-db",
        "email": "asd-model-db@github-actions",
    })
    url = f"{EUTILS_BASE}/efetch.fcgi?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read().decode("utf-8")[:2000]
    except Exception:
        return ""

def call_claude(prompt: str, api_key: str) -> str:
    """Call Claude API and return the response text."""
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY not set — skipping Claude review.")

    quarter = (datetime.now().month - 1) // 3 + 1
    report_lines = [
        f"# Quarterly ASD Model Literature Review — Q{quarter} {datetime.now().year}",
        f"\nGenerated: {datetime.now().strftime('%Y-%m-%d')}\n",
        "This report was produced automatically by scanning PubMed (last 6 months) "
        "and reviewing new evidence with Claude (Anthropic).\n",
        "---\n",
    ]

    for model_id, query in MODEL_QUERIES.items():
        print(f"Reviewing: {model_id}...")
        try:
            pmids = pubmed_search(query, days=180)
            time.sleep(0.4)
            if not pmids:
                report_lines.append(f"## {model_id}\nNo new papers found in the last 6 months.\n")
                continue

            papers = pubmed_fetch_summary(pmids[:10])
            time.sleep(0.4)

            # Fetch abstracts for top 5
            abstracts = []
            for p in papers[:5]:
                abstract = fetch_abstract(p["pmid"])
                time.sleep(0.4)
                if abstract:
                    abstracts.append(f"**{p['authors']} ({p['year']}) — {p['title']}**\n{abstract}\n")

            paper_list = "\n".join(
                f"- {p['authors']} ({p['year']}) {p['journal']}: {p['title']}"
                for p in papers
            )

            report_lines.append(f"## {model_id}\n")
            report_lines.append(f"**{len(papers)} new papers found (last 6 months)**\n")
            report_lines.append(paper_list + "\n")

            if api_key and abstracts:
                prompt = f"""You are a neuroscience expert reviewing the latest research on preclinical ASD models.

Model: {model_id}

New papers published in the last 6 months:
{chr(10).join(abstracts)}

Based on these new papers, please:
1. Summarise in 2-3 sentences what the key new findings are for this model
2. Note if any findings challenge or significantly update the existing understanding
3. Suggest any specific changes to validity scores (face/construct/predictive, 1-5) if warranted, with brief justification
4. Flag any new intervention findings (positive or negative)

Be concise and evidence-based. If the papers don't contain substantial updates, say so briefly."""

                review = call_claude(prompt, api_key)
                report_lines.append(f"\n### Claude review\n{review}\n")
                time.sleep(1)

            report_lines.append("---\n")

        except Exception as e:
            report_lines.append(f"## {model_id}\n⚠ Error: {e}\n---\n")
            print(f"  ✗ error: {e}")

    full_report = "\n".join(report_lines)
    print(full_report)

    # Write to GitHub step summary
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "w") as f:
            f.write(full_report)

    # Create GitHub Issue via API
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")
    if gh_token and gh_repo:
        issue_title = f"Quarterly literature review — Q{quarter} {datetime.now().year}"
        issue_body = full_report[:65000]  # GitHub issue body limit
        payload = json.dumps({"title": issue_title, "body": issue_body, "labels": ["literature-review"]}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{gh_repo}/issues",
            data=payload,
            headers={
                "Authorization": f"token {gh_token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            issue = json.loads(resp.read())
        print(f"\nGitHub Issue created: {issue.get('html_url')}")

if __name__ == "__main__":
    main()
