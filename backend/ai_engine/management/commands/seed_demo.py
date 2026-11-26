"""Fake recruiters, companies, job posts and a candidate for local development: python manage.py seed_demo"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ai_engine.models import Company, Job, UserProfile

PASSWORD = 'hirely-demo-123'

COMPANIES = [
    ('Northwind Labs', 'northwind.dev', ('maya', 'Maya', 'Chen'), [
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

CANDIDATE = ('alex', 'Alex', 'Rivera')


def _user(username, first, last, role, company=None):
    user, created = User.objects.get_or_create(
        username=username, defaults={'email': f'{username}@example.com', 'first_name': first, 'last_name': last})
    if created:
        user.set_password(PASSWORD)
        user.save(update_fields=['password'])
    UserProfile.objects.update_or_create(user=user, defaults={'role': role, 'company': company})
    return created


class Command(BaseCommand):
    help = "Create fake recruiters, companies, job posts and a candidate (local development only)."

    def handle(self, *args, **options):
        # Demo users sign in with Django passwords, so never seed production or a Supabase-backed database
        if not settings.DEBUG or settings.USE_SUPABASE:
            raise CommandError("seed_demo only runs locally: needs DEBUG=1 and no Supabase keys.")
        users = jobs = 0
        with transaction.atomic():
            for name, domain, (username, first, last), postings in COMPANIES:
                company, _ = Company.objects.get_or_create(name=name, defaults={'domain': domain})
                users += _user(username, first, last, 'recruiter', company)
                for title, level, description in postings:
                    jobs += Job.objects.get_or_create(company=company, title=title, defaults={
                        'experience_level': level, 'description': description})[1]
            users += _user(*CANDIDATE, 'candidate')
        self.stdout.write(self.style.SUCCESS(
            f"Added {users} users and {jobs} jobs. Sign in with any username below and password '{PASSWORD}':"))
        for _, _, (username, *_), _ in COMPANIES:
            self.stdout.write(f"  recruiter  {username}")
        self.stdout.write(f"  candidate  {CANDIDATE[0]}")
