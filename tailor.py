"""
On-demand resume tailoring for a single job posting.

Used by the dashboard "Tailor" button (api/routes/tailor.py), NOT by the
scrape pipeline -- tailoring costs an LLM call per posting, so it only
ever runs when you explicitly ask for one posting.

Two parts:

1. tailor_resume() -- sends your resume bank (contact details stripped
   out; the model only needs skills/experience to make selections) plus
   the posting text to the LLM, which picks/reorders/lightly rewords
   from YOUR bullets. It must never invent achievements -- the prompt
   forbids it, and you review the preview before downloading.
2. suggest_skills() -- cheap heuristic skill-gap analysis: posting
   keywords missing from your bank ("consider adding") vs bank items
   with zero overlap to the posting ("consider dropping"). No LLM
   needed, runs instantly alongside every tailor call.
"""
import json
import re

import yaml

import feedback

MAX_JOB_CHARS = 6000

# Canonical skill -> aliases matched (case-insensitive substring) against
# both the posting text and your bank text for the add/remove suggestion.
SKILL_LEXICON = {
    "Python": ["python"],
    "JavaScript": ["javascript", "js"],
    "TypeScript": ["typescript", "ts"],
    "React": ["react"],
    "Next.js": ["next.js", "nextjs"],
    "Node.js": ["node.js", "nodejs", "node"],
    "Java": ["java"],
    "C#": ["c#", "c sharp", "csharp"],
    "SQL": ["sql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Firebase": ["firebase"],
    "Supabase": ["supabase"],
    "Git/GitHub": ["git", "github"],
    "Docker": ["docker"],
    "CI/CD": ["ci/cd", "cicd", "continuous integration"],
    "Linux": ["linux", "ubuntu"],
    "Bash": ["bash", "shell scripting"],
    "REST APIs": ["rest", "restful", "api"],
    "OAuth": ["oauth"],
    "HTML/CSS": ["html", "css"],
    "Agile/Scrum": ["agile", "scrum"],
    "QA/Testing": ["qa", "quality assurance", "testing", "software test"],
    "Troubleshooting": ["troubleshoot"],
    "Hardware support": ["hardware"],
    "Networking": ["networking", "tcp/ip", "lan", "wan"],
    "DNS/DHCP": ["dns", "dhcp"],
    "VPN/Firewall": ["vpn", "firewall"],
    "Windows administration": ["windows server", "active directory"],
    "Office 365": ["office 365", "microsoft office", "o365"],
    "Helpdesk": ["helpdesk", "help desk", "service desk"],
    "LLM integration": ["llm", "large language model"],
    "Prompt engineering": ["prompt engineering", "prompting"],
    "PyTorch": ["pytorch"],
    "Data analysis": ["data analysis", "analytics"],
    "Excel": ["excel", "spreadsheet"],
}

_STOPWORDS = frozenset({
    "and", "the", "for", "with", "using", "use", "used", "from", "that",
    "this", "you", "your", "our", "are", "was", "were", "have", "has",
    "had", "will", "would", "can", "including", "include", "such",
    "more", "most", "other", "into", "over", "under", "between", "through",
    "their", "they", "them", "who", "what", "when", "where", "which",
    "also", "than", "then", "them", "its", "per", "via", "plus",
})


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def flatten_bank_text(bank: dict) -> str:
    parts = [" ".join(bank.get("summary", {}).get("variants", []))]
    for g in bank.get("skills", []):
        parts.append(g.get("group", ""))
        parts.extend(g.get("items", []))
    for job in bank.get("experience", []):
        parts.append(job.get("title", ""))
        for b in job.get("bullets", []):
            parts.append(b.get("text", "") if isinstance(b, dict) else str(b))
    for s in bank.get("soft_skills", []):
        parts.append(s)
    return "\n".join(parts)


def _mentions(text_low: str, aliases) -> bool:
    return any(a in text_low for a in aliases)


def suggest_skills(bank: dict, job_description: str,
                   max_each: int = 10) -> dict:
    """Heuristic skill gap: posting skills missing from your bank (consider
    adding) vs bank items with no overlap to the posting (consider
    dropping). Deterministic -- safe to show next to the LLM output."""
    job_low = (job_description or "").lower()
    bank_low = flatten_bank_text(bank).lower()

    matched, missing = [], []
    for skill, aliases in SKILL_LEXICON.items():
        if _mentions(job_low, aliases):
            (matched if _mentions(bank_low, aliases) else missing).append(skill)

    # Bank items with zero word overlap to the posting are deprioritize
    # candidates. Compared per item so one group's filler doesn't hide
    # behind the group's relevant items.
    job_words = {w for w in re.findall(r"[a-z0-9+#.]{3,}", job_low)
                 if w not in _STOPWORDS}
    drop_candidates = []
    seen_items = set()
    for g in bank.get("skills", []):
        for item in g.get("items", []):
            if item in seen_items:
                continue
            seen_items.add(item)
            words = {w for w in re.findall(r"[a-z0-9+#.]{3,}", item.lower())
                     if w not in _STOPWORDS}
            if words and not (words & job_words):
                drop_candidates.append(item)
    return {
        "matched": matched,
        "suggested_add": missing[:max_each],
        "suggested_remove": drop_candidates[:max_each],
    }


TAILOR_SYSTEM = """You tailor a resume to a specific job posting by SELECTING and REORDERING the candidate's real content. Hard rules:
- NEVER invent achievements, numbers, tools, employers, dates, or responsibilities not implied by the bank text. If the posting asks for something absent from the bank, leave it out -- do not fabricate it.
- Echo company, title, location, start_date, end_date, school, degree, and graduation EXACTLY as written in the bank. Rewording is allowed ONLY inside bullet text, and only lightly (mirror the posting's terminology) while staying truthful to the original bullet.
- Include ALL education entries and ALL languages: none of them are posting-specific.
- Reply with STRICT JSON only, exactly this shape, nothing else:
{"summary": "string",
 "skills": [{"group": "string", "items": ["string", ...]}, ...],
 "experience": [{"company": "string", "title": "string", "location": "string",
                 "start_date": "string", "end_date": "string",
                 "bullets": ["string", ...]}, ...],
 "education": [{"school": "string", "degree": "string", "graduation": "string"}],
 "languages": ["string", ...],
 "certifications": ["string", ...],
 "soft_skills": ["string", ...]}"""


def tailor_resume(cfg: dict, bank: dict, job_title: str, job_company: str,
                  job_description: str) -> tuple[dict, str, str]:
    """Returns (tailored_dict, provider_label, error). Error is "" on success."""
    trimmed_bank = {
        "summary": bank.get("summary", {}),
        "skills": bank.get("skills", []),
        "experience": [
            {"company": j.get("company", ""), "title": j.get("title", ""),
             "location": j.get("location", ""),
             "start_date": j.get("start_date", ""),
             "end_date": j.get("end_date", ""),
             "bullets": [b.get("text", "") if isinstance(b, dict) else str(b)
                         for b in j.get("bullets", [])]}
            for j in bank.get("experience", [])
        ],
        "education": bank.get("education", []),
        "certifications": bank.get("certifications", []),
        "languages": bank.get("languages", []),
        "interests": bank.get("interests", []),
        "soft_skills": bank.get("soft_skills", []),
    }
    job_text = (f"Title: {job_title}\nCompany: {job_company}\n\n"
                f"{job_description or ''}")[:MAX_JOB_CHARS]
    user = (f"RESUME BANK:\n{json.dumps(trimmed_bank, indent=2)}\n\n"
            f"JOB POSTING:\n{job_text}\n\n"
            f"Pick the best-fitting summary (or lightly blend), reorder skill "
            f"groups/items by relevance to this posting (drop clearly "
            f"irrelevant items, never invent), select the 3-5 most relevant "
            f"bullets per job, and pick matching soft skills.")
    tailored, provider, err = {}, "", "no attempts made"
    for _ in range(2):  # one retry: reasoning models intermittently return
        reply, provider, err = feedback.generate_text(  # empty/non-JSON output
            TAILOR_SYSTEM, user, cfg, usage_name="tailor")
        if err:
            if "budget" in err or "disabled" in err or "no AI API keys" in err:
                break  # retrying can't help these
            continue
        try:
            tailored = _safe_parse_json(reply)
        except ValueError as e:
            err = f"could not parse model output: {e}"
            continue
        err = ""
        break
    if err:
        return {}, provider, err
    for key in ("summary", "skills", "experience"):
        if key not in tailored:
            return {}, provider, f"model output missing '{key}'"
    return tailored, provider, ""


def _safe_parse_json(raw: str) -> dict:
    cleaned = re.sub(r"^```(json)?", "", (raw or "").strip()).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in output: {cleaned[:300]!r}")
    return json.loads(match.group(0))
