"""
Opens a job posting URL in a real (visible) browser via Playwright and
attempts to pre-fill common application-form fields (name/email/phone/
resume upload) using best-effort field detection. It NEVER clicks final
submit -- you review and submit yourself.

This is intentionally best-effort: application forms vary enormously
(Workday, Greenhouse, Lever, iCIMS, custom ATS...) and a universal
autofill isn't reliable. Treat this as "saves you the repetitive typing",
not "fully automatic."

Usage:
    python apply_helper.py <job_url> [path_to_tailored_resume.docx]

    The resume path is optional: without it, text fields still get
    prefilled but no file is uploaded.
"""
import sys
import time

import yaml
from playwright.sync_api import sync_playwright

FIELD_HINTS = {
    "first_name": ["first name", "given name", "fname"],
    "last_name": ["last name", "surname", "family name", "lname"],
    "full_name": ["full name", "your name"],
    "email": ["email"],
    "phone": ["phone", "mobile", "telephone"],
    "location": ["location", "city", "address"],
    "linkedin": ["linkedin"],
}


def load_resume_bank(path="resume_bank.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def try_fill(page, contact: dict, resume_path: str):
    inputs = page.locator("input")
    count = inputs.count()
    filled = []

    for i in range(count):
        el = inputs.nth(i)
        try:
            label_text = " ".join(filter(None, [
                el.get_attribute("placeholder") or "",
                el.get_attribute("name") or "",
                el.get_attribute("aria-label") or "",
                el.get_attribute("id") or "",
            ])).lower()
        except Exception:
            continue

        if not label_text:
            continue

        try:
            input_type = (el.get_attribute("type") or "text").lower()
        except Exception:
            input_type = "text"

        if input_type == "file":
            if any(h in label_text for h in ["resume", "cv"]):
                if not resume_path:
                    continue
                try:
                    el.set_input_files(resume_path)
                    filled.append(f"resume upload -> {label_text}")
                except Exception as e:
                    print(f"  [!] couldn't attach resume to field '{label_text}': {e}")
            continue

        for field, hints in FIELD_HINTS.items():
            if any(h in label_text for h in hints):
                value = {
                    "first_name": contact.get("name", "").split(" ")[0] if contact.get("name") else "",
                    "last_name": " ".join(contact.get("name", "").split(" ")[1:]) if contact.get("name") else "",
                    "full_name": contact.get("name", ""),
                    "email": contact.get("email", ""),
                    "phone": contact.get("phone", ""),
                    "location": contact.get("location", ""),
                    "linkedin": next((l["url"] for l in contact.get("links", []) if "linkedin" in l.get("label", "").lower()), ""),
                }.get(field, "")
                if value:
                    try:
                        el.fill(value)
                        filled.append(f"{field} -> '{label_text}'")
                    except Exception:
                        pass
                break

    return filled


def main(job_url: str, resume_path: str = ""):
    bank = load_resume_bank()
    contact = bank.get("contact", {})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(job_url, timeout=60000)

        print(f"[apply_helper] loaded {job_url}")
        print("[apply_helper] attempting to auto-fill visible form fields...")
        filled = try_fill(page, contact, resume_path)

        if filled:
            print("[apply_helper] filled fields:")
            for f in filled:
                print(f"   - {f}")
        else:
            print("[apply_helper] no recognizable fields found on this page yet")
            print("   (form may be behind a click, e.g. an 'Apply' button -- click it, then re-run)")

        print("\n[apply_helper] Browser left open for you to review and submit manually.")
        if sys.stdin.isatty():
            print("Press Enter here when you're done with this tab...")
            input()
            browser.close()
        else:
            print("[apply_helper] subprocess mode -- close the browser window when done.")
            while browser.is_connected():
                time.sleep(2)
            print("[apply_helper] browser closed.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python apply_helper.py <job_url> [path_to_tailored_resume.docx]")
        sys.exit(1)
    resume = sys.argv[2] if len(sys.argv) == 3 else ""
    main(sys.argv[1], resume)
