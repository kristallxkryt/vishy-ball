
"""
Высший балл — backend API.
Файл: main.py
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Высший балл API",
    description="API платформы подготовки к ЕГЭ",
    version="1.0.0"
)

# Подключение маршрутов
from auth_routes import router as auth_router
from profile_routes import router as profile_router
from checking_routes import router as checking_router
from tasks_routes import router as tasks_router
from admin_routes import router as admin_router
from recommendations_routes import router as recommendations_router

# Новые маршруты: пользователи, классы и варианты
from users_routes import router as users_router
from classes_routes import router as classes_router
from variants_routes import router as variants_router

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(tasks_router)
app.include_router(checking_router)
app.include_router(admin_router)
app.include_router(recommendations_router)

# Подключение системы учителей и классов
app.include_router(users_router)
app.include_router(classes_router)
app.include_router(variants_router)

# CORS для локальной разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUBJECTS = [
    {"id": "russian", "name": "Русский язык"},
    {"id": "math-profile", "name": "Математика (профильная)"},
    {"id": "math-basic", "name": "Математика (базовая)"},
    {"id": "informatics", "name": "Информатика"},
    {"id": "physics", "name": "Физика"},
    {"id": "chemistry", "name": "Химия"},
    {"id": "biology", "name": "Биология"},
    {"id": "history", "name": "История"},
    {"id": "social-studies", "name": "Обществознание"},
    {"id": "literature", "name": "Литература"},
    {"id": "geography", "name": "География"},
    {"id": "english", "name": "Английский язык"},
    {"id": "german", "name": "Немецкий язык"},
    {"id": "french", "name": "Французский язык"},
    {"id": "spanish", "name": "Испанский язык"},
    {"id": "chinese", "name": "Китайский язык"},
]


@app.get("/")
def home():
    return {
        "project": "Высший балл",
        "message": "API работает",
        "version": "1.0.0"
    }


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/subjects")
def get_subjects():
    return {
        "subjects": SUBJECTS,
        "total": len(SUBJECTS)
    }
