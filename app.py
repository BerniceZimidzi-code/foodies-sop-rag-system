from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import re
import secrets
from typing import Annotated, Any, Literal

from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import psycopg
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from backend import ingestion

APP_ROOT = Path(__file__).resolve().parent
load_dotenv(APP_ROOT / ".env")

from backend.auth import (
    create_access_token,
    get_current_user,
    get_jwt_secret,
    get_password_change_user,
    hash_password,
    verify_password,
)
from backend.answering import AnswerProviderError, answer_question, configured_answer_provider
from backend.embeddings import EmbeddingProviderError
from backend.database import (
    activate_user,
    create_sop_version,
    create_document_category,
    create_user,
    change_user_password,
    clear_password_reset_credentials,
    create_initial_admin,
    consume_password_reset,
    delete_user,
    dismiss_failed_document_upload,
    get_existing_user_emails,
    get_document_category,
    find_sop_by_content_hash,
    get_failed_document_upload,
    get_sop_sections,
    get_sop_version,
    get_user_by_activation_token_hash,
    get_user_by_password_reset_token_hash,
    get_user_by_email,
    get_user_by_id,
    issue_password_reset_for_email,
    issue_password_reset_for_user,
    initialize_database,
    list_audit_logs,
    list_document_audit_events,
    list_document_categories,
    list_failed_document_uploads,
    list_sop_events,
    list_sop_versions,
    list_users,
    next_generated_sop_id,
    record_audit_log,
    record_document_event,
    record_failed_document_upload,
    resolve_failed_document_upload,
    restore_sop_version,
    permanently_purge_sop_version,
    set_user_active,
    set_document_category_active,
    soft_delete_sop_version,
    transition_sop_version,
    update_document_category,
    update_failed_document_upload,
    update_sop_document_metadata,
    update_activation_credentials,
)
from backend.ingestion import (
    IngestionError,
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    ingest_document,
    read_upload,
    save_failed_upload,
    save_original,
)
from backend.mailer import (
    EmailConfigurationError,
    EmailDeliveryError,
    activation_url,
    is_email_configured,
    password_reset_url,
    send_activation_email,
    send_password_reset_email,
)
from backend.sops import (
    get_departments,
    index_approved_sop_version_embeddings,
    load_sops,
    reindex_approved_sop_embeddings,
    retrieve_sops,
)
from backend import sops as sop_repository
from backend.user_import import UserImportError, parse_user_workbook

LOGGER = logging.getLogger(__name__)
PASSWORD_RESET_COOLDOWN = timedelta(minutes=1)
PASSWORD_RESET_LIFETIME = timedelta(minutes=30)
PASSWORD_RESET_CONFIRMATION = (
    "If an active account exists for that email, a password reset link will be sent."
)
MAX_DOCUMENT_BATCH_FILES = 30
MAX_DOCUMENT_BATCH_BYTES = 100 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_jwt_secret()
    initialize_database()
    bootstrap_initial_admin()
    yield


app = FastAPI(title="Foodies SOP RAG System", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_ROOT / "static")), name="static")

templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    department: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question is required.")
        return normalized


class DocumentCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)

    @field_validator("name", "description")
    @classmethod
    def trim_category_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def category_name_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("Category name is required.")
        return value


class DocumentUploadMetadata(BaseModel):
    sop_id: str = Field(default="", max_length=120)
    title: str = Field(min_length=1, max_length=200)
    category_id: str = Field(min_length=1, max_length=100)
    document_type: str = Field(min_length=1, max_length=80)
    department: str = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=1, max_length=150)
    version: str = Field(min_length=1, max_length=40)
    effective_date: date
    review_cycle_days: int | None = Field(default=None, ge=1, le=3650)
    tags: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("sop_id", "title", "category_id", "document_type", "department", "owner", "version")
    @classmethod
    def trim_document_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(tag.strip() for tag in values if tag.strip()))
        if any(len(tag) > 50 for tag in normalized):
            raise ValueError("Tags must be 50 characters or fewer.")
        return normalized


class DocumentMetadataUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: str | None = Field(default=None, min_length=1, max_length=100)
    document_type: str | None = Field(default=None, min_length=1, max_length=80)
    department: str | None = Field(default=None, min_length=1, max_length=100)
    owner: str | None = Field(default=None, min_length=1, max_length=150)
    effective_date: date | None = None
    review_cycle_days: int | None = Field(default=None, ge=1, le=3650)
    tags: list[str] | None = Field(default=None, max_length=30)


def _safe_upload_message(error: Exception | str) -> str:
    if isinstance(error, ValidationError):
        labels = {
            "category_id": "Category",
            "department": "Department",
            "title": "Title",
            "document_type": "Document type",
            "owner": "Owner",
            "version": "Version",
            "effective_date": "Effective date",
            "sop_id": "Document ID",
            "review_cycle_days": "Review cycle",
            "tags": "Tags",
        }
        invalid_fields = {
            str(item["loc"][0])
            for item in error.errors(include_input=False)
            if item.get("loc")
        }
        missing_labels = [
            labels[field]
            for field in labels
            if field in invalid_fields
        ]
        if missing_labels:
            return (
                f"Complete or correct these details: {', '.join(missing_labels)}. "
                "Then retry the file."
            )
        return "Check the document details and try again."

    message = str(error).casefold()
    if "unsupported file type" in message or "unsupported format" in message:
        return "This file type is not supported. Use a Markdown, readable PDF, or Word (.docx) file."
    if "exceeds" in message and ("size" in message or "limit" in message):
        return "The file or batch is too large. Choose a smaller file or split the upload into smaller batches."
    if "choose an active document category" in message or "category" in message:
        return "Choose an active category and retry the file."
    if "already exists" in message or "duplicate" in message:
        return "A document with this ID and version already exists. Check the catalogue or change the ID or version."
    if any(term in message for term in ("extract", "readable text", "empty document", "no text")):
        return "The document could not be read. Use a text-readable file or run OCR on a scanned PDF, then retry."
    return "The file could not be processed. Check its details and format, then retry or choose a replacement."


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, value: str) -> str:
        return normalize_email(value)


class ActivationRequest(BaseModel):
    token: str = Field(min_length=40, max_length=128)
    new_password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @model_validator(mode="after")
    def passwords_must_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("The new passwords do not match.")
        return self


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, value: str) -> str:
        return normalize_email(value)


class PasswordResetCompleteRequest(BaseModel):
    token: str = Field(min_length=40, max_length=128)
    new_password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @model_validator(mode="after")
    def passwords_must_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("The new passwords do not match.")
        return self


class PasswordChangeRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @model_validator(mode="after")
    def passwords_must_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("The new passwords do not match.")
        return self


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    department: str = Field(min_length=1, max_length=100)
    role: Literal["staff", "manager", "admin"]

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("name", "department")
    @classmethod
    def normalize_user_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized


class BulkUserEntry(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    department: str = Field(min_length=1, max_length=100)
    role: Literal["staff", "manager", "admin"]

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("name", "department")
    @classmethod
    def normalize_user_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized


class BulkCreateUsersRequest(BaseModel):
    users: list[BulkUserEntry] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def reject_duplicate_emails(self):
        emails = [str(entry.email).casefold() for entry in self.users]
        if len(emails) != len(set(emails)):
            raise ValueError("The submitted users contain duplicate email addresses.")
        return self


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise ValueError("Enter a valid email address.")
    return normalized


def bootstrap_initial_admin() -> None:
    email = os.getenv("FOODIES_BOOTSTRAP_ADMIN_EMAIL", "").strip()
    name = os.getenv("FOODIES_BOOTSTRAP_ADMIN_NAME", "").strip()
    department = os.getenv("FOODIES_BOOTSTRAP_ADMIN_DEPARTMENT", "").strip()
    password = os.getenv("FOODIES_BOOTSTRAP_ADMIN_PASSWORD", "")
    values = (email, name, department, password)
    if not any(values):
        return
    if not all(values):
        raise RuntimeError(
            "Set all four FOODIES_BOOTSTRAP_ADMIN_* variables or leave all of them blank."
        )
    if len(password) < 12 or len(password) > 256:
        raise RuntimeError(
            "FOODIES_BOOTSTRAP_ADMIN_PASSWORD must be between 12 and 256 characters."
        )
    try:
        admin = CreateUserRequest(
            email=email,
            name=name,
            department=department,
            role="admin",
        )
    except ValidationError as exc:
        raise RuntimeError(
            "FOODIES_BOOTSTRAP_ADMIN_EMAIL, NAME, and DEPARTMENT must be valid."
        ) from exc

    created = create_initial_admin(
        email=admin.email,
        name=admin.name,
        department=admin.department,
        password_hash=hash_password(password),
    )
    if created:
        LOGGER.warning("Created the initial administrator account: %s", admin.email)
    else:
        LOGGER.info("Initial administrator bootstrap skipped; user accounts already exist.")


class ActiveStatusRequest(BaseModel):
    is_active: bool


class InvitationSendFailure(RuntimeError):
    def __init__(self, user_id: str, message: str):
        super().__init__(message)
        self.user_id = user_id


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "department": user["department"],
        "role": user["role"],
        "must_change_password": bool(user["must_change_password"]),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


def new_activation_credentials() -> tuple[str, str, str]:
    if not is_email_configured():
        raise EmailConfigurationError(
            "Email is not configured. Set FOODIES_SMTP_HOST and FOODIES_EMAIL_FROM."
        )
    activation_token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat()
    return (
        activation_token,
        expires_at,
        activation_url(activation_token),
    )


def send_invitation(
    email: str,
    name: str,
    link: str,
) -> None:
    send_activation_email(
        email=email,
        name=name,
        link=link,
    )


def create_invited_user(payload: CreateUserRequest | BulkUserEntry) -> dict[str, str]:
    activation_token, expires_at, link = new_activation_credentials()
    user_id = create_user(
        email=str(payload.email),
        name=payload.name,
        department=payload.department,
        role=payload.role,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        is_active=False,
        must_change_password=False,
        activation_token_hash=hashlib.sha256(
            activation_token.encode("utf-8")
        ).hexdigest(),
        activation_expires_at=expires_at,
    )
    try:
        send_invitation(str(payload.email), payload.name, link)
    except (EmailConfigurationError, EmailDeliveryError) as exc:
        raise InvitationSendFailure(user_id, str(exc)) from exc
    return {"id": user_id, "email": str(payload.email)}


def record_user_access_event(
    *,
    actor: dict,
    target_id: str,
    target_email: str,
    target_name: str,
    target_department: str,
    target_role: str,
    action: str,
) -> None:
    record_document_event(
        actor_id=actor["id"],
        actor_email=actor["email"],
        action=action,
        details={
            "user_id": target_id,
            "email": target_email,
            "name": target_name,
            "department": target_department,
            "role": target_role,
        },
    )


def send_invitation_for_existing_user(invited: dict) -> None:
    if invited["activation_token_hash"] is None:
        raise EmailConfigurationError(
            "This inactive account does not have a pending activation invitation."
        )
    activation_token, expires_at, link = new_activation_credentials()
    token_hash = hashlib.sha256(activation_token.encode("utf-8")).hexdigest()
    updated = update_activation_credentials(
        invited["id"],
        token_hash,
        expires_at,
    )
    if not updated:
        raise EmailDeliveryError("The activation invitation could not be refreshed.")
    send_invitation(invited["email"], invited["name"], link)


def send_password_reset_for_user(target: dict[str, str], *, enforce_cooldown: bool) -> bool:
    if not is_email_configured():
        raise EmailConfigurationError(
            "Email is not configured. Set the SMTP environment variables before sending reset links."
        )
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = (now + PASSWORD_RESET_LIFETIME).isoformat()
    requested_at = now.isoformat()
    if enforce_cooldown:
        updated_user = issue_password_reset_for_email(
            target["email"],
            token_hash,
            expires_at,
            requested_at,
            (now - PASSWORD_RESET_COOLDOWN).isoformat(),
        )
    else:
        updated_user = issue_password_reset_for_user(
            target["id"],
            token_hash,
            expires_at,
            requested_at,
        )
    if updated_user is None:
        return False
    try:
        send_password_reset_email(
            email=updated_user["email"],
            name=updated_user["name"],
            link=password_reset_url(token),
        )
    except (EmailConfigurationError, EmailDeliveryError):
        clear_password_reset_credentials(updated_user["id"], token_hash)
        raise
    return True


@app.get("/activate", response_class=HTMLResponse)
def activate_page(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    user = get_user_by_email(str(payload.email))
    if (
        user is None
        or not user["is_active"]
        or not verify_password(payload.password, user["password_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    must_change_password = bool(user["must_change_password"])
    token = create_access_token(
        user["id"],
        get_jwt_secret(),
        auth_version=user["auth_version"],
        purpose="password_change" if must_change_password else None,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 1800,
        "user": public_user(user),
    }


@app.post("/api/auth/activate")
def activate_account(payload: ActivationRequest):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    if get_user_by_activation_token_hash(token_hash) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The activation link is invalid, expired, or already used.",
        )
    activated_user = activate_user(
        token_hash=token_hash,
        password_hash=hash_password(payload.new_password),
    )
    if activated_user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The activation link is invalid, expired, or already used.",
        )
    target = get_user_by_email(activated_user["email"])
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The activated account could not be loaded.",
        )
    record_user_access_event(
        actor=target,
        target_id=target["id"],
        target_email=target["email"],
        target_name=target["name"],
        target_department=target["department"],
        target_role=target["role"],
        action="access_activated",
    )
    return {"activated": True, "email": activated_user["email"]}


@app.post("/api/auth/password-reset")
def request_password_reset(payload: PasswordResetRequest):
    target = get_user_by_email(str(payload.email))
    if target is not None and target["is_active"]:
        try:
            send_password_reset_for_user(target, enforce_cooldown=True)
        except (EmailConfigurationError, EmailDeliveryError):
            LOGGER.exception("Unable to deliver a password reset email.")
    elif not is_email_configured():
        LOGGER.error("Password reset requested while email delivery is not configured.")
    return {"message": PASSWORD_RESET_CONFIRMATION}


@app.post("/api/auth/password-reset/confirm")
def complete_password_reset(payload: PasswordResetCompleteRequest):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    if get_user_by_password_reset_token_hash(token_hash) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The password reset link is invalid, expired, or already used.",
        )
    reset_user = consume_password_reset(
        token_hash,
        hash_password(payload.new_password),
    )
    if reset_user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The password reset link is invalid, expired, or already used.",
        )
    return {"reset": True, "email": reset_user["email"]}


@app.post("/api/auth/change-password")
def change_password(
    payload: PasswordChangeRequest,
    user: dict = Depends(get_password_change_user),
):
    if verify_password(payload.new_password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a password that differs from your current password.",
        )
    if not change_user_password(
        user["id"],
        hash_password(payload.new_password),
        expected_auth_version=user["auth_version"],
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The password reset is no longer active. Sign in again.",
        )

    updated_user = get_user_by_id(user["id"])
    if updated_user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The account could not be loaded after the password change.",
        )
    token = create_access_token(
        updated_user["id"],
        get_jwt_secret(),
        auth_version=updated_user["auth_version"],
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 1800,
        "user": public_user(updated_user),
    }


@app.get("/api/auth/me")
def current_user_profile(user: dict = Depends(get_current_user)):
    return public_user(user)


@app.post("/api/query")
def query_sop(
    payload: QueryRequest,
    user: dict = Depends(get_current_user),
):
    department = payload.department
    if user["role"] != "admin":
        if department and department.casefold() != user["department"].casefold():
            record_audit_log(
                user_id=user["id"],
                email=user["email"],
                department=user["department"],
                role=user["role"],
                question=payload.question,
                answer="Access denied: department restriction.",
                retrieved_sops=[],
                citations=[],
                success=False,
                missing_sop=False,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to that department's SOPs.",
            )
        department = user["department"]

    matches = retrieve_sops(payload.question, department)
    try:
        provider = configured_answer_provider() if matches else None
        result = answer_question(payload.question, department, matches, provider=provider)
    except AnswerProviderError as exc:
        LOGGER.error("Answer provider failed: %s", exc)
        record_audit_log(
            user_id=user["id"],
            email=user["email"],
            department=user["department"],
            role=user["role"],
            question=payload.question,
            answer="Answer generation failed; no answer was returned.",
            retrieved_sops=[item["sop_id"] for item in matches],
            citations=[],
            success=False,
            missing_sop=False,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Answer generation is temporarily unavailable. Please try again.",
        ) from exc
    record_audit_log(
        user_id=user["id"],
        email=user["email"],
        department=user["department"],
        role=user["role"],
        question=payload.question,
        answer=result["answer"],
        retrieved_sops=[item["sop_id"] for item in matches],
        citations=result["citations"],
        success=bool(result["citations"]),
        missing_sop=not bool(result["citations"]),
    )
    return result


@app.get("/api/health")
def health():
    return {"status": "ok", "approved_sops": len(load_sops())}


@app.get("/api/departments")
def departments(user: dict = Depends(get_current_user)):
    if user["role"] == "admin":
        return {"departments": get_departments()}
    return {"departments": [user["department"]]}


@app.get("/api/sops")
def list_sops(user: dict = Depends(get_current_user)):
    department = None if user["role"] == "admin" else user["department"]
    database_docs = list_sop_versions(status_filter="approved", department=department)
    docs = [
        {
            "sop_id": doc["sop_id"],
            "title": doc["title"],
            "department": doc["department"],
            "version": doc["version"],
            "effective_date": doc["effective_date"],
            "status": "Approved",
        }
        for doc in database_docs
        if doc["effective_date"] <= date.today().isoformat()
    ]
    indexed_ids = {doc["sop_id"] for doc in docs}
    docs.extend(
        doc for doc in load_sops(department)
        if doc["sop_id"] not in indexed_ids
    )
    unique = []
    seen = set()
    for doc in docs:
        key = doc["sop_id"]
        if key not in seen:
            unique.append({
                "sop_id": doc["sop_id"],
                "title": doc["title"],
                "department": doc["department"],
                "version": doc["version"],
                "effective_date": doc["effective_date"],
                "status": doc["status"],
            })
            seen.add(key)
    return {"sops": unique}


@app.get("/api/admin/users")
def admin_list_users(user: dict = Depends(get_current_user)):
    require_admin(user)
    return {"users": list_users()}


@app.get("/api/admin/email-status")
def admin_email_status(user: dict = Depends(get_current_user)):
    require_admin(user)
    return {"configured": is_email_configured()}


@app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
def admin_create_user(
    payload: CreateUserRequest,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    try:
        invitation = create_invited_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EmailConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except InvitationSendFailure as exc:
        record_user_access_event(
            actor=user,
            target_id=exc.user_id,
            target_email=str(payload.email),
            target_name=payload.name,
            target_department=payload.department,
            target_role=payload.role,
            action="access_granted",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Account {exc.user_id} was created but the activation email failed: {exc}",
        ) from exc
    record_user_access_event(
        actor=user,
        target_id=invitation["id"],
        target_email=invitation["email"],
        target_name=payload.name,
        target_department=payload.department,
        target_role=payload.role,
        action="access_granted",
    )
    return {"id": invitation["id"], "email": invitation["email"], "email_sent": True}


@app.post("/api/admin/users/preview")
async def admin_preview_users(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    content = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > 5 * 1024 * 1024:
                raise UserImportError("The spreadsheet exceeds the 5 MB size limit.")
        entries = parse_user_workbook(file.filename or "", bytes(content))
    except UserImportError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await file.close()

    existing_emails = get_existing_user_emails(
        [str(entry["email"]) for entry in entries]
    )
    email_counts: dict[str, int] = {}
    for entry in entries:
        email = str(entry["email"]).casefold()
        if email:
            email_counts[email] = email_counts.get(email, 0) + 1
    for entry in entries:
        email = str(entry["email"]).casefold()
        errors = entry["errors"]
        if email in existing_emails:
            errors.append("An account with this email already exists.")
        if email_counts.get(email, 0) > 1 and "Email is duplicated in this spreadsheet." not in errors:
            errors.append("Email is duplicated in this spreadsheet.")
        entry["valid"] = not errors
    return {"users": entries, "valid_count": sum(entry["valid"] for entry in entries)}


@app.post("/api/admin/users/bulk")
def admin_create_users_bulk(
    payload: BulkCreateUsersRequest,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    if not is_email_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email is not configured. Set the SMTP environment variables before importing accounts.",
        )
    results = []
    existing_emails = get_existing_user_emails(
        [str(entry.email) for entry in payload.users]
    )
    for entry in payload.users:
        email = str(entry.email).casefold()
        if email in existing_emails:
            results.append({"email": email, "status": "error", "message": "An account with this email already exists."})
            continue
        try:
            invitation = create_invited_user(entry)
        except ValueError as exc:
            results.append({"email": email, "status": "error", "message": str(exc)})
            continue
        except EmailConfigurationError as exc:
            results.append({"email": email, "status": "error", "message": str(exc)})
            continue
        except InvitationSendFailure as exc:
            record_user_access_event(
                actor=user,
                target_id=exc.user_id,
                target_email=email,
                target_name=entry.name,
                target_department=entry.department,
                target_role=entry.role,
                action="access_granted",
            )
            results.append({
                "email": email,
                "status": "pending_email",
                "id": exc.user_id,
                "message": str(exc),
            })
            continue
        record_user_access_event(
            actor=user,
            target_id=invitation["id"],
            target_email=email,
            target_name=entry.name,
            target_department=entry.department,
            target_role=entry.role,
            action="access_granted",
        )
        results.append({"email": email, "status": "created", "id": invitation["id"]})
        existing_emails.add(email)
    return {
        "created_count": sum(result["status"] == "created" for result in results),
        "failed_count": sum(result["status"] != "created" for result in results),
        "results": results,
    }


@app.post("/api/admin/users/{user_id}/activation")
def admin_resend_activation(
    user_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    invited = get_user_by_id(user_id)
    if invited is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if invited["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account has already been activated.",
        )
    if invited["activation_token_hash"] is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account has no pending invitation to resend.",
        )
    try:
        send_invitation_for_existing_user(invited)
    except (EmailConfigurationError, EmailDeliveryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The activation email could not be sent: {exc}",
        ) from exc
    return {"id": user_id, "email_sent": True}


@app.post("/api/admin/users/{user_id}/password-reset")
def admin_reset_user_password(
    user_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    if user_id == user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot reset your own password from this screen.",
        )
    target = get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if not target["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account has not been activated. Resend its activation email instead.",
        )
    try:
        sent = send_password_reset_for_user(target, enforce_cooldown=False)
    except (EmailConfigurationError, EmailDeliveryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The password reset email could not be sent: {exc}",
        ) from exc
    if not sent:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The account is no longer active.")
    return {
        "id": user_id,
        "email_sent": True,
    }


@app.patch("/api/admin/users/{user_id}/active")
def admin_set_user_active(
    user_id: str,
    payload: ActiveStatusRequest,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    if user_id == user["id"] and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account.",
        )
    target = get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if payload.is_active and target["activation_token_hash"] is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account must be activated using its one-time invitation link.",
        )
    if not set_user_active(user_id, payload.is_active):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if bool(target["is_active"]) != payload.is_active:
        record_user_access_event(
            actor=user,
            target_id=user_id,
            target_email=target["email"],
            target_name=target["name"],
            target_department=target["department"],
            target_role=target["role"],
            action="access_restored" if payload.is_active else "access_revoked",
        )
    return {"id": user_id, "is_active": payload.is_active}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(
    user_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    if user_id == user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )
    target = get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    try:
        deleted = delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    record_user_access_event(
        actor=user,
        target_id=user_id,
        target_email=target["email"],
        target_name=target["name"],
        target_department=target["department"],
        target_role=target["role"],
        action="access_deleted",
    )
    return {"id": user_id, "deleted": True}


@app.get("/api/admin/audit-logs")
def admin_audit_logs(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    return {"audit_logs": list_audit_logs(limit)}


@app.post("/api/admin/sops/upload", status_code=status.HTTP_201_CREATED)
async def admin_upload_sop(
    file: UploadFile = File(...),
    sop_id: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
    department: Annotated[str, Form()] = "",
    category_id: Annotated[str | None, Form()] = None,
    document_type: Annotated[str, Form()] = "SOP",
    tags: Annotated[str, Form()] = "",
    owner: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
    effective_date: Annotated[str, Form()] = "",
    review_cycle_days: Annotated[int | None, Form()] = None,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    category = get_document_category(category_id) if category_id else None
    if category_id and (category is None or not category["is_active"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose an active document category.",
        )
    metadata = {
        "title": title,
        "department": department,
        "owner": owner,
        "version": version,
        "effective_date": effective_date,
        "review_cycle_days": review_cycle_days,
    }
    for key, value in metadata.items():
        if key == "review_cycle_days" or key == "sop_id":
            continue
        if str(value).strip() == "":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {key}.",
            )

    try:
        content = await read_upload(file)
        sections = ingest_document(file.filename or "uploaded-document", content)
    except IngestionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        date.fromisoformat(effective_date.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="effective_date must be an ISO date in YYYY-MM-DD format.",
        ) from exc

    storage_path = save_original(file.filename or "uploaded-document", content)
    persisted = False
    resolved_sop_id = sop_id.strip() or _infer_sop_id(
        file.filename or "uploaded-document",
        content,
        sections,
    ) or next_generated_sop_id()
    try:
        version_id = create_sop_version(
            sop_id=resolved_sop_id,
            title=title.strip(),
            department=department.strip(),
            owner=owner.strip(),
            version=version.strip(),
            effective_date=effective_date.strip(),
            review_cycle_days=review_cycle_days,
            original_filename=file.filename or "uploaded-document",
            storage_path=str(storage_path),
            content_sha256=hashlib.sha256(content).hexdigest(),
            uploaded_by=user["email"],
            uploaded_by_id=user["id"],
            sections=sections,
            category_id=category_id,
            document_type=document_type.strip() or "SOP",
            tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
            category_review_required=category_id is None,
        )
        persisted = True
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    finally:
        if not persisted:
            storage_path.unlink(missing_ok=True)
    return {
        "id": version_id,
        "sop_id": resolved_sop_id,
        "status": "pending_review",
        "category_review_required": category_id is None,
        "message": "SOP uploaded and queued for review.",
    }


@app.get("/api/document-categories")
def document_categories(user: dict = Depends(get_current_user)):
    del user
    return {"categories": list_document_categories()}


@app.get("/api/admin/document-categories")
def admin_document_categories(user: dict = Depends(get_current_user)):
    require_admin(user)
    return {"categories": list_document_categories(include_archived=True)}


@app.post("/api/admin/document-categories", status_code=status.HTTP_201_CREATED)
def admin_create_document_category(
    payload: DocumentCategoryRequest,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    try:
        category = create_document_category(
            name=payload.name,
            description=payload.description,
            actor_id=user["id"],
            actor_email=user["email"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"category": category}


@app.patch("/api/admin/document-categories/{category_id}")
def admin_update_document_category(
    category_id: str,
    payload: DocumentCategoryRequest,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    try:
        category = update_document_category(
            category_id=category_id,
            name=payload.name,
            description=payload.description,
            actor_id=user["id"],
            actor_email=user["email"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return {"category": category}


@app.post("/api/admin/document-categories/{category_id}/archive")
def admin_archive_document_category(
    category_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    category = set_document_category_active(
        category_id=category_id,
        is_active=False,
        actor_id=user["id"],
        actor_email=user["email"],
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return {"category": category}


@app.post("/api/admin/document-categories/{category_id}/restore")
def admin_restore_document_category(
    category_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    category = set_document_category_active(
        category_id=category_id,
        is_active=True,
        actor_id=user["id"],
        actor_email=user["email"],
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return {"category": category}


@app.post("/api/admin/documents/bulk-upload")
async def admin_bulk_upload_documents(
    files: Annotated[list[UploadFile], File(...)],
    metadata: Annotated[str, Form()],
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select files to upload.")
    if len(files) > MAX_DOCUMENT_BATCH_FILES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Upload no more than {MAX_DOCUMENT_BATCH_FILES} documents at once.",
        )
    try:
        metadata_rows = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The per-file metadata is invalid JSON.",
        ) from exc
    if not isinstance(metadata_rows, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Per-file metadata must be a list.",
        )

    batch_id = secrets.token_hex(16)
    results = []
    actual_total = 0
    declared_total = sum(file.size or 0 for file in files)
    batch_limit_exceeded = declared_total > MAX_DOCUMENT_BATCH_BYTES

    def record_failure(
        index: int,
        upload: UploadFile,
        diagnostic: str,
        *,
        user_message: str | None = None,
        content: bytes | None = None,
        status_name: str = "failed",
        duplicate_id: str | None = None,
    ) -> None:
        filename = Path(upload.filename or "uploaded-document").name
        raw_metadata = (
            metadata_rows[index]
            if index < len(metadata_rows) and isinstance(metadata_rows[index], dict)
            else {}
        )
        safe_message = user_message or _safe_upload_message(diagnostic)
        LOGGER.warning(
            "Document upload issue: filename=%s status=%s diagnostic=%s",
            filename,
            status_name,
            diagnostic,
        )
        digest = hashlib.sha256(content).hexdigest() if content is not None else ""
        attempt_id = None
        if status_name != "duplicate":
            storage_path = (
                str(save_failed_upload(filename, content))
                if content is not None
                else ""
            )
            attempt_id = record_failed_document_upload(
                batch_id=batch_id,
                original_filename=filename,
                storage_path=storage_path,
                content_sha256=digest,
                metadata=raw_metadata,
                error=diagnostic,
                user_message=safe_message,
                uploaded_by_id=user["id"],
                uploaded_by=user["email"],
            )
        category_id = raw_metadata.get("category_id")
        record_document_event(
            actor_id=user["id"],
            actor_email=user["email"],
            action="upload_duplicate" if status_name == "duplicate" else "upload_failed",
            category_id=category_id if isinstance(category_id, str) else None,
            details={
                "filename": filename,
                "attempt_id": attempt_id,
                "message": safe_message,
                "batch_id": batch_id,
                "duplicate_document_id": duplicate_id,
            },
        )
        results.append(
            {
                "filename": filename,
                "status": status_name,
                "attempt_id": attempt_id,
                "message": safe_message,
                "duplicate_document_id": duplicate_id,
            }
        )

    for index, upload in enumerate(files):
        filename = Path(upload.filename or "uploaded-document").name
        if batch_limit_exceeded:
            record_failure(
                index,
                upload,
                "The total batch exceeds the 100 MB limit; this file was not processed or retained.",
            )
            await upload.close()
            continue
        if upload.size is not None and upload.size > MAX_UPLOAD_BYTES:
            record_failure(
                index,
                upload,
                "The uploaded file exceeds the 15 MB size limit.",
            )
            await upload.close()
            continue
        try:
            content = await read_upload(upload)
        except IngestionError as exc:
            record_failure(index, upload, str(exc))
            await upload.close()
            continue
        actual_total += len(content)
        if actual_total > MAX_DOCUMENT_BATCH_BYTES:
            batch_limit_exceeded = True
            record_failure(
                index,
                upload,
                "The total batch exceeds the 100 MB limit; this file was not processed or retained.",
            )
            await upload.close()
            continue
        raw_metadata = (
            metadata_rows[index]
            if index < len(metadata_rows) and isinstance(metadata_rows[index], dict)
            else {}
        )
        file_digest = hashlib.sha256(content).hexdigest()
        try:
            if len(content) > MAX_UPLOAD_BYTES:
                raise IngestionError("The uploaded file exceeds the 15 MB size limit.")
            if Path(filename).suffix.casefold() not in SUPPORTED_EXTENSIONS:
                raise IngestionError(
                    "Unsupported file type. Upload Markdown, text PDF, or Word (.docx)."
                )
            document = DocumentUploadMetadata.model_validate(raw_metadata)
            category = get_document_category(document.category_id)
            if category is None or not category["is_active"]:
                raise IngestionError("Choose an active document category.")
            version_id = _create_uploaded_document(
                filename=filename,
                content=content,
                metadata=document,
                user=user,
            )
            results.append(
                {
                    "filename": filename,
                    "status": "uploaded",
                    "document_id": version_id,
                    "sop_id": document.sop_id,
                    "title": document.title,
                    "category": category["name"],
                    "review_status": "pending_review",
                }
            )
        except (IngestionError, ValidationError, ValueError) as exc:
            diagnostic = str(exc)
            duplicate_id = None
            existing = find_sop_by_content_hash(file_digest)
            if existing:
                duplicate_id = existing["id"]
                status_name = "duplicate"
            else:
                status_name = (
                    "unsupported"
                    if isinstance(exc, IngestionError)
                    and "Unsupported file type" in diagnostic
                    else "failed"
                )
            user_message = (
                "This file is already in the library. No new copy was uploaded."
                if status_name == "duplicate"
                else _safe_upload_message(exc)
            )
            record_failure(
                index,
                upload,
                diagnostic,
                user_message=user_message,
                content=content,
                status_name=status_name,
                duplicate_id=duplicate_id,
            )
        finally:
            await upload.close()

    return {
        "batch_id": batch_id,
        "total": len(results),
        "uploaded_count": sum(result["status"] == "uploaded" for result in results),
        "failed_count": sum(result["status"] != "uploaded" for result in results),
        "duplicate_count": sum(result["status"] == "duplicate" for result in results),
        "needs_attention_count": sum(
            result["status"] not in {"uploaded", "duplicate"} for result in results
        ),
        "results": results,
    }


def _create_uploaded_document(
    *,
    filename: str,
    content: bytes,
    metadata: DocumentUploadMetadata,
    user: dict,
) -> str:
    if Path(filename).suffix.casefold() not in SUPPORTED_EXTENSIONS:
        raise IngestionError(
            "Unsupported file type. Upload Markdown, text PDF, or Word (.docx)."
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise IngestionError("The uploaded file exceeds the 15 MB size limit.")
    category = get_document_category(metadata.category_id)
    if category is None or not category["is_active"]:
        raise IngestionError("Choose an active document category.")

    content_sha256 = hashlib.sha256(content).hexdigest()
    duplicate = find_sop_by_content_hash(content_sha256)
    if duplicate:
        raise ValueError(
            f"This file duplicates {duplicate['sop_id']} ({duplicate['title']})."
        )
    sections = ingest_document(filename, content)
    sop_id = metadata.sop_id or _infer_sop_id(filename, content, sections)
    if not sop_id:
        sop_id = next_generated_sop_id()
    metadata.sop_id = sop_id
    storage_path = save_original(filename, content)
    persisted = False
    try:
        version_id = create_sop_version(
            sop_id=sop_id,
            title=metadata.title,
            department=metadata.department,
            owner=metadata.owner,
            version=metadata.version,
            effective_date=metadata.effective_date.isoformat(),
            review_cycle_days=metadata.review_cycle_days,
            original_filename=filename,
            storage_path=str(storage_path),
            content_sha256=content_sha256,
            uploaded_by=user["email"],
            uploaded_by_id=user["id"],
            sections=sections,
            category_id=metadata.category_id,
            document_type=metadata.document_type,
            tags=metadata.tags,
            category_review_required=False,
        )
        persisted = True
    finally:
        if not persisted:
            storage_path.unlink(missing_ok=True)
    return version_id


def _infer_sop_id(
    filename: str,
    content: bytes,
    sections: list[dict[str, str]],
) -> str:
    searchable_text = "\n".join(
        [
            filename,
            content.decode("utf-8-sig", errors="ignore"),
            *(f"{section['heading']}\n{section['content']}" for section in sections),
        ]
    )
    labeled_id = re.search(
        r"""(?im)^\s*(?:sop[\s_-]*id|document[\s_-]*id|id)\s*[:=]\s*["']?([A-Za-z0-9][A-Za-z0-9._/-]{0,119})""",
        searchable_text,
    )
    if labeled_id:
        return labeled_id.group(1).rstrip(".,;:)")
    filename_id = re.search(
        r"\bSOP(?:[-_][A-Z0-9]+)*[-_]\d{1,6}[A-Z]?(?=[-_.\s]|$)",
        Path(filename).stem,
        re.IGNORECASE,
    )
    if filename_id:
        return filename_id.group(0).replace("_", "-").replace(" ", "-")
    body_id = re.search(
        r"\bSOP(?:[-_][A-Z0-9]+)*[-_]\d{1,6}[A-Z]?(?=[-_.\s]|$)",
        searchable_text,
        re.IGNORECASE,
    )
    if body_id:
        return body_id.group(0).replace("_", "-").replace(" ", "-")
    return ""


@app.get("/api/documents")
def list_documents(
    query: Annotated[str | None, Query(max_length=200)] = None,
    category_id: Annotated[str | None, Query(max_length=100)] = None,
    tag: Annotated[str | None, Query(max_length=50)] = None,
    document_type: Annotated[str | None, Query(max_length=80)] = None,
    effective_after: Annotated[str | None, Query()] = None,
    effective_before: Annotated[str | None, Query()] = None,
    user: dict = Depends(get_current_user),
):
    department = None if user["role"] == "admin" else user["department"]
    documents = list_sop_versions(
        status_filter="approved",
        department=department,
        category_id=category_id,
        tag=tag,
        document_type=document_type,
        query=query,
        effective_after=effective_after,
        effective_before=effective_before,
    )
    today = date.today().isoformat()
    query_text = (query or "").casefold()
    visible = [
        _public_document(document)
        for document in documents
        if document["effective_date"] <= today
        and not document["category_review_required"]
        and not document["permanently_deleted"]
        and (
            not query_text
            or query_text
            in " ".join(
                [
                    document["title"],
                    document["sop_id"],
                    document["department"],
                    document["category_name"] or "",
                    document["document_type"],
                    *document["tags"],
                ]
            ).casefold()
        )
    ]
    database_ids = {document["sop_id"] for document in documents}
    category_names = {
        category["name"]: category
        for category in list_document_categories()
    }
    department_categories = {
        "kitchen": "Production & Kitchen Operations",
        "finance": "Cash & Finance",
        "front of house": "Sales & Customer Service",
        "quality": "Quality",
        "food safety": "Food Safety & Compliance",
        "inventory": "Inventory & Stores",
        "stores": "Inventory & Stores",
        "maintenance": "Equipment & Asset Management",
    }
    repository_documents = load_sops(department)
    if category_id:
        requested_category = get_document_category(category_id)
        repository_documents = [
            document
            for document in repository_documents
            if requested_category
            and department_categories.get(
                document["department"].casefold(),
                "General Controls",
            ).casefold()
            == requested_category["name"].casefold()
        ]
    for document in repository_documents:
        if document["sop_id"] in database_ids:
            continue
        assigned_name = department_categories.get(
            document["department"].casefold(),
            "General Controls",
        )
        assigned_category = category_names.get(assigned_name)
        repository_document = {
            "id": f"repository:{document['source_path']}",
            "sop_id": document["sop_id"],
            "title": document["title"],
            "department": document["department"],
            "document_type": "SOP",
            "category_id": assigned_category["id"] if assigned_category else None,
            "category_name": assigned_name,
            "tags": [],
            "version": document["version"],
            "effective_date": document["effective_date"],
            "status": "approved",
            "original_filename": Path(document["source_path"]).name,
            "owner": document.get("owner", ""),
            "repository_path": document["source_path"],
        }
        if query_text and query_text not in " ".join(
            [
                repository_document["title"],
                repository_document["sop_id"],
                repository_document["department"],
                repository_document["category_name"],
            ]
        ).casefold():
            continue
        if effective_after and repository_document["effective_date"] < effective_after:
            continue
        if effective_before and repository_document["effective_date"] > effective_before:
            continue
        if tag:
            continue
        if document_type and document_type.casefold() != "sop":
            continue
        visible.append(repository_document)
    return {"documents": visible}


def _public_document(document: dict) -> dict:
    return {
        "id": document["id"],
        "sop_id": document["sop_id"],
        "title": document["title"],
        "department": document["department"],
        "owner": document.get("owner", ""),
        "document_type": document["document_type"],
        "category_id": document["category_id"],
        "category_name": document["category_name"],
        "tags": document["tags"],
        "version": document["version"],
        "effective_date": document["effective_date"],
        "status": document["status"],
        "original_filename": document["original_filename"],
        "repository_path": document.get("repository_path"),
    }


@app.get("/api/repository-documents/download")
def download_repository_document(
    path: Annotated[str, Query(min_length=1, max_length=500)],
    user: dict = Depends(get_current_user),
):
    visible_documents = load_sops(
        None if user["role"] == "admin" else user["department"]
    )
    document = next(
        (candidate for candidate in visible_documents if candidate["source_path"] == path),
        None,
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )
    file_path = (APP_ROOT / Path(path)).resolve()
    if not file_path.is_relative_to(sop_repository.SOP_DIR.resolve()) or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The repository document is no longer available.",
        )
    record_document_event(
        actor_id=user["id"],
        actor_email=user["email"],
        action="downloaded",
        details={"filename": file_path.name, "repository_path": path},
    )
    return FileResponse(file_path, filename=file_path.name)


@app.get("/api/documents/{version_id}/download")
def download_document(
    version_id: str,
    user: dict = Depends(get_current_user),
):
    document = get_sop_version(version_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if document["deleted_at"] is not None or document["permanently_deleted"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if (
        user["role"] != "admin"
        and (
            document["status"] != "approved"
            or document["department"].casefold() != user["department"].casefold()
            or document["category_review_required"]
            or document["effective_date"] > date.today().isoformat()
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this document.",
        )
    path = Path(document["storage_path"]).resolve()
    upload_root = ingestion.UPLOAD_DIR.resolve()
    if not path.is_relative_to(upload_root) or not path.is_file():
        LOGGER.error("Document storage is missing or outside the upload directory: %s", version_id)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The original document is no longer available.",
        )
    record_document_event(
        actor_id=user["id"],
        actor_email=user["email"],
        action="downloaded",
        document_id=version_id,
        category_id=document["category_id"],
        details={"filename": document["original_filename"]},
    )
    return FileResponse(path, filename=Path(document["original_filename"]).name)


@app.post("/api/admin/documents/{version_id}/replace")
async def admin_replace_document(
    version_id: str,
    file: Annotated[UploadFile, File()],
    version: Annotated[str, Form(min_length=1, max_length=40)],
    effective_date: Annotated[date, Form()],
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    previous = get_sop_version(version_id)
    if previous is None or previous["deleted_at"] is not None or previous["permanently_deleted"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if not previous["category_id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assign an active category before replacing this document.",
        )
    try:
        content = await read_upload(file)
        new_version_id = _create_uploaded_document(
            filename=Path(file.filename or "replacement").name,
            content=content,
            metadata=DocumentUploadMetadata(
                sop_id=previous["sop_id"],
                title=previous["title"],
                category_id=previous["category_id"],
                document_type=previous["document_type"],
                department=previous["department"],
                owner=previous["owner"],
                version=version.strip(),
                effective_date=effective_date,
                review_cycle_days=previous["review_cycle_days"],
                tags=json.loads(previous["tags"]),
            ),
            user=user,
        )
    except (IngestionError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_document_event(
        actor_id=user["id"],
        actor_email=user["email"],
        action="replaced",
        document_id=new_version_id,
        category_id=previous["category_id"],
        details={
            "previous_document_id": version_id,
            "previous_version": previous["version"],
            "new_version": version,
            "review_required": True,
        },
    )
    await file.close()
    return {
        "document_id": new_version_id,
        "previous_document_id": version_id,
        "status": "pending_review",
        "message": "Replacement uploaded as a new version. The current version remains active until review.",
    }


@app.get("/api/admin/document-upload-failures")
def admin_document_upload_failures(user: dict = Depends(get_current_user)):
    require_admin(user)
    return {"failures": list_failed_document_uploads()}


@app.get("/api/admin/document-upload-failures/{attempt_id}/download")
def admin_download_failed_upload(
    attempt_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    attempt = get_failed_document_upload(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload attempt not found.")
    path = Path(attempt["storage_path"]).resolve()
    failed_root = (ingestion.UPLOAD_DIR / "failed").resolve()
    if not path.is_relative_to(failed_root) or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The retained original file is no longer available.",
        )
    record_document_event(
        actor_id=user["id"],
        actor_email=user["email"],
        action="failed_upload_original_downloaded",
        details={"attempt_id": attempt_id, "filename": attempt["original_filename"]},
    )
    return FileResponse(path, filename=Path(attempt["original_filename"]).name)


@app.delete("/api/admin/document-upload-failures/{attempt_id}")
def admin_dismiss_failed_upload(
    attempt_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    attempt = get_failed_document_upload(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload attempt not found.")
    stored_path = dismiss_failed_document_upload(attempt_id)
    if stored_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload attempt not found.")
    if stored_path:
        path = Path(stored_path).resolve()
        failed_root = (ingestion.UPLOAD_DIR / "failed").resolve()
        if path.is_relative_to(failed_root) and path.is_file():
            path.unlink()
    record_document_event(
        actor_id=user["id"],
        actor_email=user["email"],
        action="failed_upload_dismissed",
        details={
            "attempt_id": attempt_id,
            "filename": attempt["original_filename"],
            "original_retained": bool(attempt["storage_path"]),
        },
    )
    return {"dismissed": True}


@app.post("/api/admin/document-upload-failures/{attempt_id}/retry")
def admin_retry_document_upload(
    attempt_id: str,
    payload: Annotated[Any, Body()],
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    attempt = get_failed_document_upload(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload attempt not found.")
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add the document details and retry the file.",
        )
    metadata_values = payload.get("metadata")
    if not isinstance(metadata_values, dict):
        safe_message = "Add the document details and retry the file."
        LOGGER.warning(
            "Failed upload retry metadata rejected: attempt_id=%s reason=metadata_not_object",
            attempt_id,
        )
        update_failed_document_upload(
            attempt_id=attempt_id,
            metadata=attempt["metadata"],
            error="Retry request metadata must be an object.",
            user_message=safe_message,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_message,
        )
    try:
        metadata = DocumentUploadMetadata.model_validate(metadata_values)
    except ValidationError as exc:
        LOGGER.warning(
            "Failed upload retry metadata rejected: attempt_id=%s diagnostic=%s",
            attempt_id,
            str(exc),
        )
        safe_message = _safe_upload_message(exc)
        update_failed_document_upload(
            attempt_id=attempt_id,
            metadata=metadata_values,
            error=str(exc),
            user_message=safe_message,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_message,
        ) from exc
    failed_path = Path(attempt["storage_path"]).resolve()
    failed_root = (ingestion.UPLOAD_DIR / "failed").resolve()
    if not failed_path.is_relative_to(failed_root) or not failed_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The retained original file is no longer available.",
        )
    try:
        version_id = _create_uploaded_document(
            filename=attempt["original_filename"],
            content=failed_path.read_bytes(),
            metadata=metadata,
            user=user,
        )
    except (IngestionError, ValueError) as exc:
        LOGGER.warning(
            "Failed upload retry could not be processed: attempt_id=%s diagnostic=%s",
            attempt_id,
            str(exc),
        )
        safe_message = _safe_upload_message(exc)
        update_failed_document_upload(
            attempt_id=attempt_id,
            metadata=metadata.model_dump(mode="json"),
            error=str(exc),
            user_message=safe_message,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=safe_message) from exc
    resolve_failed_document_upload(attempt_id)
    record_document_event(
        actor_id=user["id"],
        actor_email=user["email"],
        action="failed_upload_resolved",
        document_id=version_id,
        category_id=metadata.category_id,
        details={"attempt_id": attempt_id, "filename": attempt["original_filename"]},
    )
    saved_document = get_sop_version(version_id)
    if saved_document is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The uploaded document could not be reloaded.",
        )
    return {
        "document_id": version_id,
        "sop_id": saved_document["sop_id"],
        "status": "pending_review",
    }


@app.post("/api/admin/document-upload-failures/{attempt_id}/replace")
async def admin_replace_failed_upload(
    attempt_id: str,
    file: UploadFile = File(...),
    metadata: Annotated[str, Form()] = "",
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    attempt = get_failed_document_upload(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload attempt not found.")
    try:
        metadata_values = json.loads(metadata)
        document_metadata = DocumentUploadMetadata.model_validate(metadata_values)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        LOGGER.warning(
            "Failed upload replacement metadata rejected: attempt_id=%s diagnostic=%s",
            attempt_id,
            str(exc),
        )
        safe_message = (
            _safe_upload_message(exc)
            if isinstance(exc, ValidationError)
            else "Check the document details and try again."
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_message,
        ) from exc
    filename = Path(file.filename or "replacement-document").name
    try:
        content = await read_upload(file)
        version_id = _create_uploaded_document(
            filename=filename,
            content=content,
            metadata=document_metadata,
            user=user,
        )
    except (IngestionError, ValueError) as exc:
        LOGGER.warning(
            "Failed upload replacement could not be processed: attempt_id=%s diagnostic=%s",
            attempt_id,
            str(exc),
        )
        safe_message = _safe_upload_message(exc)
        update_failed_document_upload(
            attempt_id=attempt_id,
            metadata=document_metadata.model_dump(mode="json"),
            error=str(exc),
            user_message=safe_message,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=safe_message) from exc
    finally:
        await file.close()
    if not resolve_failed_document_upload(attempt_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The replacement was saved, but the original failed-upload record could not be resolved.",
        )
    record_document_event(
        actor_id=user["id"],
        actor_email=user["email"],
        action="failed_upload_resolved",
        document_id=version_id,
        category_id=document_metadata.category_id,
        details={
            "attempt_id": attempt_id,
            "filename": attempt["original_filename"],
            "replacement_filename": filename,
        },
    )
    return {"document_id": version_id, "status": "pending_review"}


@app.get("/api/admin/document-audit")
def admin_document_audit(
    query: Annotated[str | None, Query(max_length=200)] = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    document_id: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    return {
        "events": list_document_audit_events(
            query=query,
            action=action,
            document_id=document_id,
            limit=limit,
        )
    }


@app.get("/api/admin/sops")
def admin_list_sops(
    status: Annotated[str | None, Query()] = None,
    department: Annotated[str | None, Query()] = None,
    category_id: Annotated[str | None, Query()] = None,
    document_type: Annotated[str | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
    effective_after: Annotated[str | None, Query()] = None,
    effective_before: Annotated[str | None, Query()] = None,
    include_deleted: bool = False,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    return {
        "sops": list_sop_versions(
            status_filter=status,
            department=department,
            category_id=category_id,
            document_type=document_type,
            tag=tag,
            query=query,
            effective_after=effective_after,
            effective_before=effective_before,
            include_deleted=include_deleted,
        )
    }


@app.get("/api/admin/sops/{version_id}")
def admin_get_sop(
    version_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    sop = get_sop_version(version_id)
    if sop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOP version not found.")
    sop.pop("storage_path", None)
    sop.pop("location", None)
    return {"sop": sop, "sections": get_sop_sections(version_id)}


@app.patch("/api/admin/documents/{version_id}")
def admin_update_document(
    version_id: str,
    payload: DocumentMetadataUpdate,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one document field to update.",
        )
    for field_name, field_value in values.items():
        if isinstance(field_value, str):
            values[field_name] = field_value.strip()
            if not values[field_name]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{field_name} cannot be blank.",
                )
    if values.get("effective_date") is not None:
        values["effective_date"] = values["effective_date"].isoformat()
    if "tags" in values:
        values["tags"] = DocumentUploadMetadata.normalize_tags(values["tags"] or [])
    category_id = values.get("category_id")
    if category_id:
        category = get_document_category(category_id)
        if category is None or not category["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Choose an active document category.",
            )
    try:
        document = update_sop_document_metadata(
            version_id=version_id,
            values=values,
            actor_id=user["id"],
            actor_email=user["email"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    document.pop("storage_path", None)
    document.pop("location", None)
    document["tags"] = json.loads(document["tags"])
    document["category_review_required"] = bool(document["category_review_required"])
    return {"document": document}


@app.delete("/api/admin/documents/{version_id}")
def admin_delete_document(
    version_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    document = soft_delete_sop_version(
        version_id=version_id,
        actor_id=user["id"],
        actor_email=user["email"],
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or already deleted.",
        )
    document.pop("storage_path", None)
    document.pop("location", None)
    return {"document": document, "deleted": True, "soft_delete": True}


@app.post("/api/admin/documents/{version_id}/restore")
def admin_restore_document(
    version_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    document = restore_sop_version(
        version_id=version_id,
        actor_id=user["id"],
        actor_email=user["email"],
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document cannot be restored.",
        )
    document.pop("storage_path", None)
    document.pop("location", None)
    return {"document": document, "restored": True}


@app.delete("/api/admin/documents/{version_id}/permanent")
def admin_permanently_delete_document(
    version_id: str,
    confirm: bool = Query(default=False),
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set confirm=true after confirming permanent removal.",
        )
    existing = get_sop_version(version_id)
    if (
        existing is None
        or existing["deleted_at"] is None
        or existing["permanently_deleted"]
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Soft-deleted document not found.",
        )
    staged_path = None
    stored_path = existing["storage_path"]
    upload_root = ingestion.UPLOAD_DIR.resolve()
    if stored_path:
        try:
            resolved_path = Path(stored_path).resolve()
            if not resolved_path.is_relative_to(upload_root):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="The original file is outside the managed storage location.",
                )
            if resolved_path.exists():
                if not resolved_path.is_file():
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="The original file is not a regular managed file.",
                    )
                staged_path = resolved_path.with_name(
                    f".{resolved_path.name}.{secrets.token_hex(8)}.purging"
                )
                resolved_path.replace(staged_path)
        except OSError as exc:
            LOGGER.exception("Unable to stage document file for permanent removal %s", version_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The original file could not be staged; no document data was removed.",
            ) from exc
    try:
        document = permanently_purge_sop_version(
            version_id=version_id,
            actor_id=user["id"],
            actor_email=user["email"],
        )
    except Exception as exc:
        if staged_path is not None and staged_path.exists():
            try:
                staged_path.replace(resolved_path)
            except OSError:
                LOGGER.exception("Unable to restore staged document file %s", version_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="The purge failed and the staged original could not be restored; contact an administrator.",
                ) from exc
        raise
    if document is None:
        if staged_path is not None and staged_path.exists():
            staged_path.replace(resolved_path)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Soft-deleted document not found.",
        )
    if staged_path is not None and staged_path.exists():
        try:
            staged_path.unlink()
        except OSError as exc:
            LOGGER.exception("Unable to remove staged document file %s", version_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The document record was purged, but its staged file could not be removed. Contact an administrator.",
            ) from exc
    return {"permanently_deleted": True, "audit_metadata_retained": True}


@app.post("/api/admin/sops/{version_id}/review")
def admin_review_sop(
    version_id: str,
    action: Annotated[str, Form()],
    review_note: Annotated[str | None, Form()] = None,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    allowed = {"approve", "reject", "archive"}
    if action not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be one of: approve, reject, archive.",
        )
    try:
        updated = transition_sop_version(
            version_id=version_id,
            action=action,
            actor_id=user["id"],
            actor_email=user["email"],
            review_note=review_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOP version not found.")
    updated.pop("location", None)
    result = {"sop": updated, "events": list_sop_events(version_id)}
    if action == "approve":
        try:
            result["embedding_index"] = index_approved_sop_version_embeddings(version_id)
        except (EmbeddingProviderError, psycopg.Error) as exc:
            LOGGER.exception(
                "SOP approved but embedding indexing failed: version_id=%s",
                version_id,
            )
            result["embedding_index"] = {
                "status": "failed",
                "message": (
                    "The SOP was approved, but automatic semantic indexing failed. "
                    "Use the admin reindex request to retry."
                ),
            }
    return result


@app.post("/api/admin/embeddings/reindex")
def admin_reindex_embeddings(user: dict = Depends(get_current_user)):
    require_admin(user)
    try:
        return reindex_approved_sop_embeddings()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except EmbeddingProviderError as exc:
        LOGGER.warning("SOP embedding reindex failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except psycopg.Error as exc:
        LOGGER.exception("PostgreSQL SOP embedding reindex failed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "PostgreSQL vector indexing is unavailable. Confirm pgvector is "
                "enabled and retry."
            ),
        ) from exc


@app.get("/api/admin/sops/{version_id}/events")
def admin_sop_events(
    version_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    if not get_sop_version(version_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOP version not found.")
    return {"events": list_sop_events(version_id)}


def require_admin(user: dict) -> None:
    if user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required.",
        )
