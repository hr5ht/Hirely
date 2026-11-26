"""Fake recruiters, companies, job posts and a candidate for local development: python -m scripts.seed_demo"""
import asyncio

from sqlalchemy import select

from app.core import config
from app.core.database import SessionLocal, create_tables
from app.core.security import hash_password
from app.models import Company, Job, User, UserProfile

PASSWORD = config.DEMO_PASSWORD

COMPANIES = [
    ('Northwind Labs', 'northwind.dev', (config.DEMO_RECRUITER, 'Maya', 'Chen'), [
        ('Senior Backend Engineer (Python)', 'Senior', 'Build and scale our Django and PostgreSQL services. '
         'You will design REST APIs, tune slow queries, and own background jobs in production. '
         'Requirements: 5+ years of Python, Django or FastAPI, PostgreSQL, Docker, CI/CD. '
         'Nice to have: AWS, Redis, observability tooling.'),
        ('Frontend Engineer (React)', 'Mid-level', 'Ship accessible, fast UI for our analytics product. '
         'Requirements: 3+ years of React and TypeScript, CSS, testing with Jest or Playwright, REST and GraphQL APIs. '
         'Nice to have: design systems, charting libraries.'),
    ]),
    ('Bluepeak Health', 'bluepeak.io', ('arjun', 'Arjun', 'Mehta'), [
        ('Data Scientist', 'Mid-level', 'Turn clinical and operational data into models that help care teams. '
         'Requirements: Python, pandas, scikit-learn, SQL, statistics and A/B testing, clear communication. '
         'Nice to have: PyTorch, healthcare data (HL7/FHIR).'),
        ('DevOps Engineer', 'Senior', 'Own our cloud platform and release pipeline. '
         'Requirements: Kubernetes, Terraform, AWS or GCP, Linux, GitHub Actions, monitoring with Prometheus/Grafana. '
         'Nice to have: HIPAA compliance experience.'),
    ]),
    ('Orbit Commerce', 'orbitcommerce.com', ('sofia', 'Sofia', 'Garcia'), [
        ('Junior Full-Stack Developer', 'Entry-level', 'Join a small team building our storefront and admin tools. '
         'Requirements: JavaScript, HTML/CSS, one backend language (Python or Node.js), SQL basics, Git. '
         'You will pair with seniors and ship features from week one.'),
        ('Machine Learning Engineer', 'Senior', 'Build recommendation and search ranking systems. '
         'Requirements: Python, PyTorch or TensorFlow, feature pipelines, model serving, vector search, SQL. '
         'Nice to have: LLMs and RAG, Spark.'),
    ]),
]

CANDIDATE = (config.DEMO_CANDIDATE, 'Alex', 'Rivera')



async def _user(db, password_hash, username, first, last, role, company=None):
    """Create the user if missing (safe to run again); returns 1 if created."""
    if await db.scalar(select(User.id).where(User.username == username)):
        return 0
    user = User(username=username, email=f'{username}@example.com', first_name=first, last_name=last, password=password_hash)
    db.add_all([user, UserProfile(user=user, role=role, company=company)])
    return 1


async def main():
    # Demo accounts have a known password, so never seed anything but a local DEBUG database
    if not config.DEBUG:
        raise SystemExit("seed_demo only runs locally: needs DEBUG=1.")
    await create_tables()
    password_hash = await hash_password(PASSWORD)  # one hash for all of them: hashing is deliberately slow
    users = jobs = 0
    async with SessionLocal() as db:
        for name, domain, (username, first, last), postings in COMPANIES:
            company = await db.scalar(select(Company).where(Company.name == name))
            if not company:
                company = Company(name=name, domain=domain)
                db.add(company)
                await db.flush()  # gives it an id for the job lookups below
            users += await _user(db, password_hash, username, first, last, 'recruiter', company)
            for title, level, description in postings:
                if not await db.scalar(select(Job.id).where(Job.company_id == company.id, Job.title == title)):
                    db.add(Job(company=company, title=title, experience_level=level, description=description))
                    jobs += 1
        users += await _user(db, password_hash, *CANDIDATE, 'candidate')
        await db.commit()
    print(f"Added {users} users and {jobs} jobs. Sign in with any username below and password '{PASSWORD}':")
    for _, _, (username, *_), _ in COMPANIES:
        print(f"  recruiter  {username}")
    print(f"  candidate  {CANDIDATE[0]}")


if __name__ == '__main__':
    asyncio.run(main())
