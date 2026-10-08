"""Validated, idempotent import into the isolated demo market, not verified users."""
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import settings
from .db import SessionLocal
from .models import SyntheticMarketRecord

DATASET_VERSION = "synthetic_it_market_v1"
DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "synthetic_market_v1"


def load_corpus(root=DATA_ROOT):
    from data.synthetic_market_v1.generate_market import validate
    try:
        taxonomy = json.loads((root / "taxonomy.json").read_text(encoding="utf-8"))
        profiles = [json.loads(line) for line in (root / "profiles.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        vacancies = [json.loads(line) for line in (root / "vacancies.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if taxonomy["version"] != "it_roles_v1":
            raise ValueError("taxonomy version")
        families = taxonomy["families"]
        validate(profiles, vacancies, families)
        family_ids = {family["id"] for family in families}
        for profile in profiles:
            if (profile["origin"] != "synthetic_fixture" or profile["data_mode"] != "synthetic"
                    or profile["assessment_status"] != "not_assessed" or profile["contact"] is not None
                    or not re.fullmatch(r"syn-candidate-\d{3}", profile["profile_id"])
                    or profile["display_name"] != f"Кандидат S-{profile['profile_id'].rsplit('-', 1)[1]}"):
                raise ValueError("profile provenance")
            for target in profile["target_roles"]:
                if target["role_family_id"] not in family_ids or target["declared_level"] not in ("junior", "middle", "senior", "lead"):
                    raise ValueError("target role")
            if any(skill["source"] != "candidate_self_report" or skill["verification_status"] != "not_assessed" for skill in profile["skills"]):
                raise ValueError("skill provenance")
        for vacancy in vacancies:
            if (vacancy["origin"] != "synthetic_fixture" or vacancy["employer"]["is_real_employer"] is not False
                    or vacancy["market_claim"] is not False or not re.fullmatch(r"syn-vacancy-\d{3}", vacancy["vacancy_id"])):
                raise ValueError("vacancy provenance")
        # The importer only accepts this contact-free fixture package.
        if "@" in json.dumps([profiles, vacancies], ensure_ascii=False):
            raise ValueError("contact in corpus")
    except (AssertionError, KeyError, TypeError, ValueError, OSError):
        raise ValueError("Invalid or incomplete synthetic market corpus; nothing was imported") from None
    return families, profiles, vacancies


def seed_market(db, root=DATA_ROOT):
    if settings.app_mode != "demo":
        raise ValueError("Synthetic market import is allowed only in APP_MODE=demo")
    families, profiles, vacancies = load_corpus(root)
    records = [dict(id=f"family-{family['id']}", kind="family", family_id=family["id"], level=None, payload=family) for family in families]
    records += [dict(id=profile["profile_id"], kind="profile", family_id=profile["target_roles"][0]["role_family_id"],
        level=profile["target_roles"][0]["declared_level"], payload=profile) for profile in profiles]
    records += [dict(id=vacancy["vacancy_id"], kind="vacancy", family_id=vacancy["role_family_id"],
        level=vacancy["role_level"], payload=vacancy) for vacancy in vacancies]
    for record in records:
        record["dataset_version"] = DATASET_VERSION
    existing = {row.id: row for row in db.scalars(select(SyntheticMarketRecord).where(SyntheticMarketRecord.id.in_([r["id"] for r in records])))}
    for record in records:
        old = existing.get(record["id"])
        if old and any(getattr(old, key) != record[key] for key in record):
            raise ValueError("Existing market fixture differs; publish a new dataset version instead of overwriting it")
    dialect = db.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    if insert is None:
        raise ValueError("Market import supports SQLite and PostgreSQL")
    statement = insert(SyntheticMarketRecord).values(records).on_conflict_do_nothing(index_elements=["id"]).returning(SyntheticMarketRecord.id)
    inserted = len(db.execute(statement).scalars().all())
    return {"dataset_version": DATASET_VERSION, "profiles": len(profiles), "vacancies": len(vacancies),
            "families": len(families), "inserted": inserted}


def main():
    with SessionLocal() as db:
        result = seed_market(db)
        db.commit()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
