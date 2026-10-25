
import os
import logging

from fastapi import FastAPI, HTTPException, Path
from dotenv import load_dotenv
from enum import Enum
from pydantic import BaseModel, field_validator
from datetime import datetime, timezone

load_dotenv()


# Настройка логирования
raw_log_level = os.getenv("LOG_LEVEL")

ALLOWED_LEVELS = {"DEBUG", "INFO", "WARNING"}
invalid_level_warn = None

if raw_log_level is None:
    log_level = "INFO"
else:
    normalized_level = raw_log_level.strip().upper()

    if normalized_level in ALLOWED_LEVELS:
        log_level = normalized_level
    else:
        log_level = "INFO"
        invalid_level_warn = (
            f"Некорректный LOG_LEVEL={raw_log_level!r}. "
            "Используется уровень INFO."
        )

logger = logging.getLogger("job_status_tracker")
logger.setLevel(log_level)

if not logger.handlers:
    console_handler = logging.StreamHandler()

    log_formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
    )

    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

logger.propagate = False

if invalid_level_warn:
    logger.warning(invalid_level_warn)

logger.info("Логгер настроен. Уровень: %s", log_level)

# Настройка максимального количества Jobs
raw_max_jobs_value = os.getenv("MAX_JOBS")
invalid_max_jobs_warn = None

if raw_max_jobs_value is None:
    max_jobs_value = 100
else:
    try:
        max_jobs_value = int(raw_max_jobs_value)
    except ValueError:
        max_jobs_value = 100
        invalid_max_jobs_warn = (
            f"Некорректное значение MAX_JOBS: {raw_max_jobs_value!r}. "
            f"Используем значение: MAX_JOBS={max_jobs_value!r}"
            )

if max_jobs_value <= 0:
    max_jobs_value = 100
    invalid_max_jobs_warn = (
        f"Значение MAX_JOBS меньше или равно 0. "
        f"Используем значение: MAX_JOBS={max_jobs_value!r}"
        )

if invalid_max_jobs_warn:
    logger.warning(invalid_max_jobs_warn)

# Реализация модели Job
class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobCategory(str, Enum):
    DATA_PROCESSING = "data_processing"
    ML_INFERENCE = "ml_inference"
    REPORT_GENERATION = "report_generation"
    OTHER = "other"

ALLOWED_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.RUNNING},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set()
}

class JobCreate(BaseModel, extra="forbid"):
    name: str
    author: str
    description: str = ""
    category: JobCategory = JobCategory.OTHER

    @field_validator("name", "author")
    @classmethod
    def validate_required_parameters(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("Поле не может быть пустым!")

        return value


class Job(JobCreate):
    id: int
    status: JobStatus
    created_at: datetime


class JobListResponse(BaseModel):
    jobs: list[Job]
    total: int

class JobStatusUpdate(BaseModel, extra="forbid"):
    status: JobStatus

class JobStatsResponse(BaseModel, extra="forbid"):
    total_jobs: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_author: dict[str, int]

# Инициализация хранилища Jobs
jobs: dict[int, Job] = {}
next_job_id = 1

# Инициализация FastAPI
APP_VERSION = "0.1.0"

app_title = (
    (os.getenv("APP_NAME") or "").strip()
    or "Job Status Tracker"
)

app = FastAPI(
    title=app_title,
    version=APP_VERSION
)


@app.get("/health")
def health():
    logger.debug("Вызван эндпоинт /health")
    return {"status": "ok"}


@app.get("/version")
def version():
    logger.debug("Вызван эндпоинт /version")
    return {"version": APP_VERSION}


@app.post("/jobs", response_model=Job, status_code=201)
def create_job(job: JobCreate):
    global next_job_id

    if len(jobs) >= max_jobs_value:
        logger.warning(f"Невозможно добавить Job. Достигнут лимит: {max_jobs_value}")
        raise HTTPException(
            status_code=409,
            detail=f"Невозможно добавить Job. Достигнут лимит: {max_jobs_value}"
        )

    new_job = Job(
        id=next_job_id,
        name=job.name,
        author=job.author,
        description=job.description,
        category=job.category,
        status=JobStatus.PENDING,
        created_at=datetime.now(timezone.utc)
        )
    
    jobs[new_job.id] = new_job
    next_job_id += 1

    logger.info(f"Создан Job: id={new_job.id}, category={new_job.category.value}")

    return new_job


@app.get("/jobs", response_model=JobListResponse)
def get_jobs(status: JobStatus | None = None):
    jobs_list = list(jobs.values())

    if status is not None:
        jobs_list = [job for job in jobs_list if job.status == status]

    return {
                "jobs": jobs_list,
                "total": len(jobs_list)
            }


@app.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: int = Path(gt=0)):
    job = jobs.get(job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job с id: {job_id} не существует!"
        )

    return job

@app.patch("/jobs/{job_id}/status", response_model=Job)
def update_job_status(update: JobStatusUpdate, job_id: int = Path(gt=0)):
    job_to_change = jobs.get(job_id)

    if job_to_change is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job с id: {job_id} не существует!"
        )

    if job_to_change.status == update.status:
        logger.debug(
            f"Смена статуса для Job {job_to_change.id} не выполнена. "
            f"Job уже имеет статус: {update.status.value}"
        )
        return job_to_change

    allowed = ALLOWED_TRANSITIONS[job_to_change.status]

    if update.status not in allowed:
        logger.warning(
            f"Смена статуса для Job ID: {job_id} отклонена! "
            f"Переход из {job_to_change.status.value} в {update.status.value} невозможен."
            )
        raise HTTPException(
            status_code=409,
            detail=f"Смена статуса для Job ID: {job_id} отклонена! "
                    f"Переход из {job_to_change.status.value} в {update.status.value} невозможен."
        )

    old_status = job_to_change.status.value
    job_to_change.status = update.status
    logger.info(
        f"Статус Job ID {job_id} успешно изменен! "
        f"Прежний статус: {old_status}. Новый статус: {update.status.value}"
    )
    return job_to_change


@app.get("/stats", response_model=JobStatsResponse)
def get_stats():
    total_jobs = len(jobs)
    by_status = {status.value: 0 for status in JobStatus}
    by_category = {category.value: 0 for category in JobCategory}
    by_author = dict()

    for job in jobs.values():
        by_status[job.status.value] += 1
        by_category[job.category.value] += 1
        by_author[job.author] = by_author.get(job.author, 0) + 1

    return {
        "total_jobs": total_jobs,
        "by_status": by_status,
        "by_category": by_category,
        "by_author": by_author
    }