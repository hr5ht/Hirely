"""Demo data: a candidate, a recruiter at Google with three openings, and a few other companies' jobs.

Safe to re-run: existing users and jobs are reused, nothing is duplicated or deleted.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from ai_engine.models import Company, Job, UserProfile

JOBS = {
    "Google": [
        ("Senior Backend Engineer", "Senior",
         "Design and run Python and Go services on GCP. Kafka streaming, PostgreSQL tuning, Kubernetes, gRPC APIs and on-call ownership."),
        ("Machine Learning Engineer", "Mid-level",
         "Ship retrieval and ranking models to production. Python, PyTorch, embeddings, vector search, evaluation pipelines and A/B tests."),
        ("Frontend Engineer", "Junior",
         "Build accessible React and TypeScript interfaces. Component libraries, performance budgets, testing with Playwright."),
    ],
    "Meta": [("Data Engineer", "Mid-level", "Spark and Airflow pipelines, SQL modelling, data quality checks and warehouse cost control.")],
    "Amazon": [("DevOps Engineer", "Senior", "AWS (ECS, Lambda, RDS), Terraform, CI/CD, observability with CloudWatch and incident response.")],
    "Stripe": [("Full Stack Developer", "Mid-level", "Django and React product work on payments dashboards. REST APIs, Postgres, background jobs.")],
}


class Command(BaseCommand):
    help = "Create demo accounts (candidate / recruiter) and job postings."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="1234", help="Password for both demo accounts (default: 1234)")

    def handle(self, *args, password, **options):
        companies = {name: Company.objects.filter(name=name).first() or Company.objects.create(name=name) for name in JOBS}
        for username, role, company in [("candidate", "candidate", None), ("recruiter", "recruiter", companies["Google"])]:
            user, created = User.objects.get_or_create(username=username, defaults={"email": f"{username}@hirely.demo"})
            user.set_password(password)  # demo accounts skip the validators on purpose
            user.save()
            UserProfile.objects.update_or_create(user=user, defaults={"role": role, "company": company})
            self.stdout.write(f"{'Created' if created else 'Updated'} {role} '{username}'")
        jobs = 0
        for name, postings in JOBS.items():
            for title, level, description in postings:
                _, created = Job.objects.get_or_create(company=companies[name], title=title,
                                                       defaults={"experience_level": level, "description": description})
                jobs += created
        self.stdout.write(self.style.SUCCESS(f"Demo data ready: {jobs} new job(s), log in as candidate or recruiter."))
