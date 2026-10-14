"""
Automatic contact pull — no Claude involved.

For one company:
  1. Seamless search (free): the sponsorship buyers by title.
  2. Seamless reveal (1 credit each): emails for the best `reveal_n` of them.
  3. Tiga, for whatever Seamless could not cover:
       its own people DB (free) → Find People agent if still empty (slow,
       optional) → waterfall enrichment for anyone still missing an email.
Results merge into the record's contacts[] without duplicating anyone already
there, and the record remembers when and how it was pulled so the bulk pull can
skip it next time.
"""
from datetime import date

from core import seamless, tiga

CONTACT_FIELDS = ("name", "title", "email", "phone", "linkedin", "source")


def _key(c: dict) -> str:
    return ((c.get("email") or "").lower() or (c.get("linkedin") or "").lower().rstrip("/")
            or (c.get("name") or "").lower().strip())


def merge(existing: list, new: list) -> tuple:
    """(merged, added_count). Fills blanks on a known person rather than adding twice."""
    merged = list(existing or [])
    index = {}
    for i, c in enumerate(merged):
        for k in {(c.get("email") or "").lower(), (c.get("linkedin") or "").lower().rstrip("/"),
                  (c.get("name") or "").lower().strip()}:
            if k:
                index[k] = i
    added = 0
    for n in new:
        keys = [k for k in {(n.get("email") or "").lower(), (n.get("linkedin") or "").lower().rstrip("/"),
                            (n.get("name") or "").lower().strip()} if k]
        hit = next((index[k] for k in keys if k in index), None)
        if hit is not None:
            for f in ("email", "phone", "linkedin", "title"):
                if not merged[hit].get(f) and n.get(f):
                    merged[hit][f] = n[f]
            continue
        rec = {f: n.get(f, "") for f in CONTACT_FIELDS}
        rec.update({"notes": "", "activity_log": [], "found_date": date.today().isoformat()})
        merged.append(rec)
        for k in keys:
            index[k] = len(merged) - 1
        added += 1
    return merged, added


def pull_for_company(record: dict, max_contacts: int = 4, reveal_n: int = 2,
                     use_agent: bool = False, log=None) -> dict:
    """Find contacts for one pipeline record and merge them in. Returns the
    record (mutated) with a `contact_pull` note describing what happened."""
    say = log or (lambda m: None)
    name = record.get("company", "")
    domain = record.get("domain", "")
    found, notes = [], []

    # 1-2. Seamless
    if seamless.available():
        try:
            people = seamless.search_contacts(name, limit=max_contacts * 3, domain=domain)
            people = [p for p in people if seamless.title_rank(p["title"]) > 0][:max_contacts]
            notes.append(f"Seamless: {len(people)} found")
            if people and reveal_n:
                try:
                    seamless.reveal(people[:reveal_n])
                    notes.append(f"{sum(1 for p in people if p.get('email'))} emails revealed")
                except seamless.SeamlessError as e:
                    notes.append(f"reveal failed: {e}")
            found += people
        except seamless.SeamlessError as e:
            notes.append(f"Seamless: {e}")
        say(f"{name}: " + "; ".join(notes))

    # 3. Tiga for the gap
    if tiga.available() and (len(found) < max_contacts or not any(f.get("email") for f in found)):
        try:
            tp = tiga.search_people(name)
            if not tp and use_agent:
                say(f"{name}: running Tiga's Find People agent (can take a few minutes)...")
                tiga.find_people_agent(
                    "VP Marketing, Director of Marketing, Head of Events, CMO, "
                    f"VP Partnerships or VP Sales at {name}, based in the United States")
                tp = tiga.search_people(name)
            tp.sort(key=lambda c: -seamless.title_rank(c["title"]))
            tp = [c for c in tp if seamless.title_rank(c["title"]) > 1][:max_contacts]
            have = {_key(f) for f in found}
            tp = [c for c in tp if _key(c) not in have]
            found += tp[:max(0, max_contacts - len(found))]
            notes.append(f"Tiga: {len(tp)} found")
        except tiga.TigaError as e:
            notes.append(f"Tiga: {e}")

        # Enrich the top people still missing an email, up to reveal_n total emails.
        emails = sum(1 for f in found if f.get("email"))
        for c in found:
            if emails >= max(reveal_n, 1):
                break
            if c.get("email"):
                continue
            c["company_name"] = c.get("company_name") or name
            c["domain"] = c.get("domain") or domain
            try:
                tiga.enrich(c)
                if c.get("email"):
                    emails += 1
            except tiga.TigaError as e:
                notes.append(f"enrich: {e}")
                break
        say(f"{name}: " + "; ".join(notes))

    found.sort(key=lambda c: (not c.get("email"), -seamless.title_rank(c.get("title", ""))))
    merged, added = merge(record.get("contacts") or [], found[:max_contacts])
    record["contacts"] = merged
    record["contact_pull"] = {
        "date": date.today().isoformat(),
        "added": added,
        "with_email": sum(1 for c in merged if c.get("email")),
        "notes": "; ".join(notes) or "No contact source configured.",
    }
    return record


def needs_contacts(record: dict) -> bool:
    if record.get("sponsor_confirmed") or record.get("status") in ("closed_won", "closed_lost"):
        return False
    cs = record.get("contacts") or []
    return not any(c.get("email") for c in cs)


def sources_available() -> list:
    out = []
    if seamless.available():
        out.append("Seamless")
    if tiga.available():
        out.append("Tiga")
    return out
