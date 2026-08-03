import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

django_asgi_app = get_asgi_application()

# Import WebSocket Consumer
from ai_engine.consumers import InterviewConsumer

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter([
            path("ws/interview/<str:session_id>/", InterviewConsumer.as_asgi()),
        ])
    ),
})

