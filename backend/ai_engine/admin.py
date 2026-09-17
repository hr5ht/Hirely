from django.contrib import admin

from ai_engine.models import Application, Company, CompanyInvite, InterviewSession, Job, UserProfile


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'company')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__email', 'company__name')
    exclude = ('resume_pdf',)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'experience_level', 'is_active', 'created_at')
    list_filter = ('is_active', 'company')
    search_fields = ('title', 'description', 'company__name')


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'job', 'status', 'ats_match_score', 'proctoring_score', 'created_at')
    list_filter = ('status', 'job__company')
    search_fields = ('candidate__username', 'candidate__email', 'job__title')
    list_select_related = ('candidate', 'job')
    exclude = ('resume_pdf',)  # megabytes of bytes are no use in a form


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = ('application', 'session_status', 'tech_knowledge', 'behavioral_iq', 'problem_solving', 'created_at')
    list_filter = ('session_status',)
    search_fields = ('application__candidate__username', 'application__job__title')
    list_select_related = ('application__candidate', 'application__job')
    exclude = ('pdf_report', 'rag_cache')


@admin.register(CompanyInvite)
class CompanyInviteAdmin(admin.ModelAdmin):
    list_display = ('company', 'created_by', 'expires_at', 'used_by')
    list_filter = ('company',)
