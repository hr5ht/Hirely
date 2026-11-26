"""/admin/ for staff (is_staff users), built with sqladmin. Staff sign in on the normal login page."""
from fastapi.responses import RedirectResponse
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend

from app.core import config
from app.core.database import SessionLocal, engine
from app.core.security import get_user
from app.models import Application, Company, CompanyInvite, InterviewSession, Job, User, UserProfile


class StaffOnly(AuthenticationBackend):
    async def login(self, request):
        return False  # no admin login form: /admin/ sends people to /login/

    async def logout(self, request):
        request.session.clear()
        return True

    async def authenticate(self, request):
        async with SessionLocal() as db:
            user = await get_user(request, db)
        if user and user.is_staff:
            return True
        return RedirectResponse('/login/?next=/admin/', status_code=302)


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.username, User.email, User.is_staff, User.is_active, User.date_joined]
    column_searchable_list = [User.username, User.email]
    form_excluded_columns = [User.password, User.profile]  # passwords are changed by the user, never typed here
    column_details_exclude_list = [User.password]


class CompanyAdmin(ModelView, model=Company):
    column_list = [Company.id, Company.name, Company.created_at]
    column_searchable_list = [Company.name]


class UserProfileAdmin(ModelView, model=UserProfile):
    column_list = [UserProfile.id, UserProfile.user, UserProfile.role, UserProfile.company]
    form_excluded_columns = column_details_exclude_list = [UserProfile.resume_pdf]


class JobAdmin(ModelView, model=Job):
    column_list = [Job.id, Job.title, Job.company, Job.experience_level, Job.is_active, Job.created_at]
    column_searchable_list = [Job.title, Job.description]


class ApplicationAdmin(ModelView, model=Application):
    column_list = [Application.id, Application.candidate, Application.job, Application.status, Application.ats_match_score,
                   Application.proctoring_score, Application.created_at]
    form_excluded_columns = column_details_exclude_list = [Application.resume_pdf, Application.sessions]  # megabytes of bytes are no use in a form


class InterviewSessionAdmin(ModelView, model=InterviewSession):
    column_list = [InterviewSession.id, InterviewSession.application, InterviewSession.session_status, InterviewSession.tech_knowledge,
                   InterviewSession.behavioral_iq, InterviewSession.problem_solving, InterviewSession.created_at]
    form_excluded_columns = column_details_exclude_list = [InterviewSession.pdf_report, InterviewSession.rag_cache]


class CompanyInviteAdmin(ModelView, model=CompanyInvite):
    column_list = [CompanyInvite.id, CompanyInvite.company, CompanyInvite.created_by, CompanyInvite.expires_at, CompanyInvite.used_by_id]


def setup_admin(app, session_cookie):
    # Same cookie settings as the app's own session, so the admin reads the same sign-in
    admin = Admin(app, engine, authentication_backend=StaffOnly(config.SECRET_KEY, **session_cookie), title="Hirely admin")
    for view in (UserAdmin, CompanyAdmin, UserProfileAdmin, JobAdmin, ApplicationAdmin, InterviewSessionAdmin, CompanyInviteAdmin):
        admin.add_view(view)
