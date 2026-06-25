#!/usr/bin/env python3
"""
Monthly PubMed literature update — runs on 1st of each month via GitHub Actions.
Searches PubMed for papers published in the last 30 days for each ASD model,
adds new references to data/recent_papers.json, and prints a summary report.
"""

import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DATA_FILE = REPO_ROOT / "data" / "recent_papers.json"

# Search terms per model ID — tuned to return relevant preclinical papers
MODEL_QUERIES = {
    "fmr1":    '"Fmr1" AND ("fragile X" OR "FMRP") AND ("mouse" OR "rat" OR "animal model")',
    "shank3":  '"SHANK3" AND ("autism" OR "ASD" OR "Phelan-McDermid") AND ("mouse" OR "model")',
    "mecp2":   '"MeCP2" AND ("Rett syndrome" OR "autism") AND ("mouse" OR "model")',
    "tsc":     '("TSC1" OR "TSC2") AND ("tuberous sclerosis") AND ("autism" OR "ASD") AND ("mouse" OR "model")',
    "fmr1rat": '"Fmr1" AND "rat" AND ("fragile X" OR "autism" OR "ASD")',
    "cntnap2": '"CNTNAP2" AND ("autism" OR "ASD") AND ("mouse" OR "model")',
    "btbr":    '"BTBR" AND ("autism" OR "ASD" OR "social behavior" OR "repetitive")',
    "vpa":     '"valproic acid" AND "prenatal" AND ("autism" OR "ASD") AND ("mouse" OR "rat")',
    "mia":     '"maternal immune activation" AND ("autism" OR "ASD") AND ("mouse" OR "rat")',
    "pten":    '"PTEN" AND ("autism" OR "ASD" OR "macrocephaly") AND ("mouse" OR "model")',
    "16p":     '"16p11.2" AND ("autism" OR "ASD") AND ("mouse" OR "deletion" OR "model")',
    "nlgn3":   '("NLGN3" OR "neuroligin-3") AND ("autism" OR "ASD") AND ("mouse" OR "R451C")',
    "shank2":  '"SHANK2" AND ("autism" OR "ASD") AND ("mouse" OR "model")',
    "chd8":    '"CHD8" AND ("autism" OR "ASD") AND ("mouse" OR "model")',
    "dyrk1a":  '"DYRK1A" AND ("autism" OR "ASD" OR "neurodevelopmental") AND ("mouse" OR "model")',
    "dup15q":  '("Dup15q" OR "15q11-13" OR "15q duplication") AND ("autism" OR "ASD")',
    "oxtr":    '("OXTR" OR "oxytocin receptor") AND ("autism" OR "ASD") AND ("mouse" OR "model")',
    "en2":     '("Engrailed-2" OR "En2") AND ("autism" OR "ASD" OR "cerebellum") AND ("mouse" OR "model")',
    "c58":     '"C58/J" AND ("autism" OR "stereotypy" OR "repetitive behavior")',
}

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

def pubmed_search(query: str, days: int = 30) -> list[str]:
    """Return list of PMIDs for query within the last `days` days."""
    mindate = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
    maxdate = datetime.now().strftime("%Y/%m/%d")
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": query,
        "mindate": mindate,
        "maxdate": maxdate,
        "datetype": "pdat",
        "retmax": 20,
        "retmode": "json",
        "tool": "asd-model-db",
        "email": "asd-model-db@github-actions",
    })
    url = f"{EUTILS_BASE}/esearch.fcgi?{params}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read())
    return data.get("esearchresult", {}).get("idlist", [])

def pubmed_fetch_summary(pmids: list[str]) -> list[dict]:
    """Fetch summaries for a list of PMIDs."""
    if not pmids:
        return []
    ids = ",".join(pmids)
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ids,
        "retmode": "json",
        "tool": "asd-model-db",
        "email": "asd-model-db@github-actions",
    })
    url = f"{EUTILS_BASE}/esummary.fcgi?{params}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read())
    results = []
    for pmid in pmids:
        item = data.get("result", {}).get(pmid, {})
        if not item or item.get("error"):
            continue
        authors = item.get("authors", [])
        author_str = authors[0]["name"] if authors else "Unknown"
        if len(authors) > 1:
            author_str += " et al."
        results.append({
            "pmid": pmid,
            "title": item.get("title", "").rstrip("."),
            "authors": author_str,
            "journal": item.get("source", ""),
            "year": item.get("pubdate", "")[:4],
            "added": datetime.now().strftime("%Y-%m-%d"),
        })
    return results

def main():
    # Load existing data
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            existing = json.load(f)
    else:
        existing = {}

    meta = existing.get("_meta", {})
    summary_rows = []

    for model_id, query in MODEL_QUERIES.items():
        print(f"  Searching: {model_id}...")
        try:
            pmids = pubmed_search(query, days=30)
            time.sleep(0.4)  # respect NCBI rate limit (3 req/s without API key)
            if not pmids:
                continue
            papers = pubmed_fetch_summary(pmids)
            time.sleep(0.4)

            existing_pmids = {p["pmid"] for p in existing.get(model_id, [])}
            new_papers = [p for p in papers if p["pmid"] not in existing_pmids]

            if new_papers:
                if model_id not in existing:
                    existing[model_id] = []
                # Keep only last 12 months — prune anything older
                cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
                existing[model_id] = [
                    p for p in existing[model_id]
                    if p.get("added", "9999") >= cutoff
                ]
                existing[model_id].extend(new_papers)
                summary_rows.append(f"| {model_id} | {len(new_papers)} | {'; '.join(p['title'][:60]+'…' for p in new_papers[:3])} |")
                print(f"    → {len(new_papers)} new paper(s)")
            else:
                print(f"    → no new papers")
        except Exception as e:
            print(f"    ✗ error: {e}")

    # Update metadata
    existing["_meta"] = {
        **meta,
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "window_days": 365,
        "note": "Auto-updated monthly by GitHub Actions.",
    }

    with open(DATA_FILE, "w") as f:
        json.dump(existing, f, indent=2)

    # Print summary for GitHub Actions job summary
    print("\n## Monthly literature update summary\n")
    print(f"Run date: {datetime.now().strftime('%Y-%m-%d')}\n")
    if summary_rows:
        print("| Model | New papers | Titles (preview) |")
        print("|---|---|---|")
        for row in summary_rows:
            print(row)
    else:
        print("No new papers found in the last 30 days.")

    # Write to GitHub step summary if available
    import os
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a") as f:
            f.write("## Monthly ASD literature update\n\n")
            f.write(f"**Run date:** {datetime.now().strftime('%Y-%m-%d')}\n\n")
            if summary_rows:
                f.write("| Model | New papers | Titles |\n|---|---|---|\n")
                for row in summary_rows:
                    f.write(row + "\n")
            else:
                f.write("No new papers found in the last 30 days.\n")

if __name__ == "__main__":
    main()
