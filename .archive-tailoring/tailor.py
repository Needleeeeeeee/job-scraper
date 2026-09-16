"""
Two jobs, kept deliberately separate:
  1. SCORE each job against your resume bank (semantic match) -- always
     via cloud embeddings (router.embed) or a keyword-overlap fallback.
     The first enabled provider with an `embedding_model` config is used.
  2. GENERATE the tailored resume (select/reword bullets) -- delegated to
     router.py, which tries your configured free providers in priority
     order and tracks daily usage so it can skip an exhausted one
     automatically. See config.yaml's `providers` list to add/reorder/
     disable providers.
"""
import json
import re
import numpy as np
import yaml

import router


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def load_resume_bank(path="resume_bank.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def flatten_bank_text(bank: dict) -> str:
    """Rough plain-text version of the whole resume bank, for embedding."""
    parts = [" ".join(bank.get("summary", {}).get("variants", []))]
    for g in bank.get("skills", []):
        parts.append(", ".join(g.get("items", [])))
    for job in bank.get("experience", []):
        for b in job.get("bullets", []):
            parts.append(b["text"])
    for p in bank.get("projects", []):
        parts.append(p.get("description", ""))
    return "\n".join(parts)


def score_job(cfg: dict, resume_text: str, job_description: str) -> float:
    if not job_description or (isinstance(job_description, float) and np.isnan(job_description)):
        return 0.0
    try:
        r_vec, j_vec = router.embed(cfg, [resume_text, job_description])
        r_emb = np.array(r_vec, dtype=np.float32)
        j_emb = np.array(j_vec, dtype=np.float32)
        return round(_cosine(r_emb, j_emb), 4)
    except Exception as e:
        print(f"[tailor] embedding failed ({e}); falling back to keyword overlap score")
        return _keyword_overlap_score(resume_text, job_description)


def _keyword_overlap_score(a: str, b: str) -> float:
    """Fallback if cloud embeddings aren't available: crude Jaccard overlap."""
    wa = set(re.findall(r"[a-zA-Z+#]{3,}", a.lower()))
    wb = set(re.findall(r"[a-zA-Z+#]{3,}", b.lower()))
    if not wa or not wb:
        return 0.0
    return round(len(wa & wb) / len(wa | wb), 4)


TAILOR_PROMPT = """You are helping tailor a resume to a specific job posting.

You will be given:
1. A JSON "resume bank" of the candidate's real summary options, education, skills, experience, soft skills, languages, and interests.
2. A job posting's text.

Your job:
- Pick the summary variant that best fits this posting (or lightly blend two).
- Include ALL education entries from the bank -- they are all relevant.
- Reorder the skill groups so the most relevant to this posting come first; you may drop
  clearly irrelevant items within a group, but do NOT invent new skills.
- For each job in "experience", select and lightly reword (mirroring the posting's terminology)
  the 3-5 most relevant bullets. Do NOT invent achievements, numbers, or responsibilities that
  aren't implied by the original bullet text.
- Select soft skills from the bank that best match this posting.
- Include ALL languages from the bank.
- Select interests from the bank that align with the posting's domain when possible.
- Output STRICT JSON only, matching this shape, nothing else:

{{
  "summary": "string",
  "education": [{{"school": "string", "degree": "string", "graduation": "string"}}],
  "skills": [{{"group": "string", "items": ["string", ...]}}, ...],
  "experience": [{{"company": "string", "title": "string", "location": "string",
                    "start_date": "string", "end_date": "string",
                    "bullets": ["string", ...]}}, ...],
  "soft_skills": ["string", ...],
  "languages": ["string", ...],
  "interests": ["string", ...]
}}

BULLET BANK:
{bank_json}

JOB POSTING:
{job_text}
"""


def tailor_resume(cfg: dict, bank: dict, job_title: str, job_company: str, job_description: str) -> dict:
    # Strip contact/education/certifications out of what we send -- the LLM
    # only needs summary/skills/experience/projects to make selections.
    trimmed_bank = {
        "summary": bank.get("summary", {}),
        "education": bank.get("education", []),
        "skills": bank.get("skills", []),
        "experience": bank.get("experience", []),
        "soft_skills": bank.get("soft_skills", []),
        "languages": bank.get("languages", []),
        "interests": bank.get("interests", []),
    }
    prompt = TAILOR_PROMPT.format(
        bank_json=json.dumps(trimmed_bank, indent=2),
        job_text=f"Title: {job_title}\nCompany: {job_company}\n\n{job_description}"[:6000],
    )
    raw = router.generate(cfg, prompt)
    return _safe_parse_json(raw)


def _safe_parse_json(raw: str) -> dict:
    # Local models sometimes wrap JSON in prose or code fences -- extract the
    # first {...} block.
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Could not find JSON in model output:\n{raw[:500]}")
    return json.loads(match.group(0))


if __name__ == "__main__":
    cfg = load_config()
    bank = load_resume_bank(cfg["paths"]["master_resume"])
    demo_job = "Senior Linux/DevOps engineer, remote, must know Bash, Docker, and CI/CD automation."
    result = tailor_resume(cfg, bank, "Senior DevOps Engineer", "Acme Co", demo_job)
    print(json.dumps(result, indent=2))
