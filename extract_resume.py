"""
Bootstraps resume_bank.yaml from an existing .docx resume.

This does NOT try to be fully automatic -- resumes are formatted too
differently for that to be reliable. It pulls out paragraphs and dumps
them into a rough bullet list under a single "Imported" job entry, tagged
with naive keyword guesses. You should then hand-edit resume_bank.yaml:
split bullets under the right job/dates, fix tags, and fill in
contact/skills/education properly.

Usage:
    python extract_resume.py resume.docx
"""
import sys
import re
import yaml
from docx import Document

STOPWORD_TAGS = {
    "linux": ["linux", "ubuntu", "arch", "bash", "sysadmin", "administration"],
    "python": ["python"],
    "automation": ["automat", "script", "pipeline", "workflow"],
    "ai": ["ai", "ml", "machine learning", "llm", "gpu", "model"],
    "cloud": ["aws", "azure", "gcp", "cloud"],
    "docker": ["docker", "container", "kubernetes", "k8s"],
    "networking": ["network", "dns", "firewall", "vpn"],
    "database": ["sql", "database", "postgres", "mysql"],
}


def guess_tags(text: str):
    lower = text.lower()
    tags = []
    for tag, needles in STOPWORD_TAGS.items():
        if any(n in lower for n in needles):
            tags.append(tag)
    return tags or ["general"]


def main(path: str):
    doc = Document(path)
    bullets = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text or len(text) < 8:
            continue
        # skip obvious headers (all caps, short lines)
        if text.isupper() and len(text.split()) <= 5:
            continue
        bullets.append(text)

    bank = {
        "contact": {
            "name": "FILL ME IN",
            "email": "FILL ME IN",
            "phone": "FILL ME IN",
            "location": "FILL ME IN",
            "links": [],
        },
        "summary": {"variants": ["FILL ME IN with 1-2 summary sentence options"]},
        "skills": [{"group": "FILL ME IN", "items": []}],
        "experience": [
            {
                "company": "IMPORTED - split these across your real jobs/dates",
                "title": "FILL ME IN",
                "location": "FILL ME IN",
                "start_date": "FILL ME IN",
                "end_date": "FILL ME IN",
                "bullets": [
                    {"text": b, "tags": guess_tags(b)} for b in bullets
                ],
            }
        ],
        "projects": [],
        "education": [{"school": "FILL ME IN", "degree": "FILL ME IN", "graduation": "FILL ME IN"}],
        "certifications": [],
    }

    out_path = "resume_bank.extracted.yaml"
    with open(out_path, "w") as f:
        yaml.dump(bank, f, sort_keys=False, allow_unicode=True, width=100)

    print(f"Wrote {out_path} with {len(bullets)} raw bullets pulled from {path}.")
    print("Next: open it, split bullets across your actual jobs/dates, fix tags,")
    print("fill in contact/skills/education, then rename it to resume_bank.yaml.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python extract_resume.py your_resume.docx")
        sys.exit(1)
    main(sys.argv[1])
