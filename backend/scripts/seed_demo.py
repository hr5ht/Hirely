"""Demo data for local development: an admin, a recruiter with 8 job openings, and a candidate.

Runs on every container start (compose.yaml) and adds only what's missing: python -m scripts.seed_demo
"""
import asyncio

from sqlalchemy import select

from app.core import config
from app.core.database import SessionLocal, create_tables
from app.core.security import hash_password
from app.models import Company, Job, User, UserProfile

COMPANY = ('Northwind Labs', 'northwind.dev')

# (username, first, last, role, staff)
ACCOUNTS = [
    (config.DEMO_ADMIN, 'Ada', 'Admin', 'admin', True),
    (config.DEMO_RECRUITER, 'Maya', 'Chen', 'recruiter', False),
    (config.DEMO_CANDIDATE, 'Alex', 'Rivera', 'candidate', False),
]

# (title, experience level, description), all posted by the demo recruiter's company
JOBS = [
    ('Senior Backend Engineer (Python)', 'Senior', 'Build and scale our FastAPI and PostgreSQL services. '
     'You will design REST APIs, tune slow queries, and own background jobs in production. '
     'Requirements: 5+ years of Python, FastAPI or Django, PostgreSQL, Docker, CI/CD. Nice to have: AWS, Redis, observability tooling.'),
    ('Frontend Engineer (React)', 'Mid-level', 'Ship accessible, fast UI for our analytics product. '
     'Requirements: 3+ years of React and TypeScript, CSS, testing with Jest or Playwright, REST and GraphQL APIs. '
     'Nice to have: design systems, charting libraries.'),
    ('Data Scientist', 'Mid-level', 'Turn product and operational data into models that drive decisions. '
     'Requirements: Python, pandas, scikit-learn, SQL, statistics and A/B testing, clear communication. Nice to have: PyTorch, dbt.'),
    ('DevOps Engineer', 'Senior', 'Own our cloud platform and release pipeline. '
     'Requirements: Kubernetes, Terraform, AWS or GCP, Linux, GitHub Actions, monitoring with Prometheus and Grafana. '
     'Nice to have: SOC 2 experience.'),
    ('Junior Full-Stack Developer', 'Entry-level', 'Join a small team building our customer portal and admin tools. '
     'Requirements: JavaScript, HTML/CSS, one backend language (Python or Node.js), SQL basics, Git. '
     'You will pair with seniors and ship features from week one.'),
    ('Machine Learning Engineer', 'Senior', 'Build recommendation and search ranking systems. '
     'Requirements: Python, PyTorch or TensorFlow, feature pipelines, model serving, vector search, SQL. Nice to have: LLMs and RAG, Spark.'),
    ('Mobile Developer (React Native)', 'Mid-level', 'Build our iOS and Android apps from one codebase. '
     'Requirements: 3+ years of React Native and TypeScript, REST APIs, offline storage, publishing to the App Store and Google Play. '
     'Nice to have: native modules in Swift or Kotlin.'),
    ('QA Automation Engineer', 'Mid-level', 'Keep releases safe with fast, reliable automated tests. '
     'Requirements: Python or TypeScript, Playwright or Cypress, API testing, CI pipelines, writing clear bug reports. '
     'Nice to have: load testing with k6 or Locust.'),
]


async def main():
    # Demo accounts have a known password, so never seed anything but a local DEBUG database
    if not config.DEBUG:
        raise SystemExit("seed_demo only runs locally: needs DEBUG=1.")
    await create_tables()
    password_hash = await hash_password(config.DEMO_PASSWORD)  # one hash for all: hashing is deliberately slow
    added_users = added_jobs = 0
    async with SessionLocal() as db:
        company = await db.scalar(select(Company).where(Company.name == COMPANY[0]))
        if not company:
            company = Company(name=COMPANY[0], domain=COMPANY[1])
            db.add(company)
            await db.flush()  # gives it an id for the lookups below

        for username, first, last, role, staff in ACCOUNTS:
            if await db.scalar(select(User.id).where(User.username == username)):
                continue
            user = User(username=username, email=f'{username}@example.com', first_name=first, last_name=last,
                        password=password_hash, is_staff=staff, is_superuser=staff)
            db.add_all([user, UserProfile(user=user, role=role, company=company if role == 'recruiter' else None)])
            added_users += 1

        for title, level, description in JOBS:
            if not await db.scalar(select(Job.id).where(Job.company_id == company.id, Job.title == title)):
                db.add(Job(company=company, title=title, experience_level=level, description=description))
                added_jobs += 1
        await db.commit()

    print(f"Demo data: added {added_users} accounts and {added_jobs} jobs. Password for all: '{config.DEMO_PASSWORD}'")
    for username, _, _, role, _ in ACCOUNTS:
        print(f"  {role:<10} {username}")


if __name__ == '__main__':
    asyncio.run(main())
