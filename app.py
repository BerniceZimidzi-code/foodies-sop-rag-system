from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import re
import secrets
from typing import Annotated, Literal

from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator, model_validator

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
from backend.answering import answer_question
from backend.database import (
    activate_user,
    create_sop_version,
    create_user,
    change_user_password,
    delete_user,
    get_existing_user_emails,
    get_sop_sections,
    get_sop_version,
    get_user_by_activation_token_hash,
    get_user_by_email,
    get_user_by_id,
    initialize_database,
    list_audit_logs,
    list_sop_events,
    list_sop_versions,
    list_users,
    record_audit_log,
    reset_user_password,
    set_user_active,
    transition_sop_version,
    update_activation_credentials,
)
from backend.ingestion import IngestionError, ingest_document, read_upload, save_original
from backend.mailer import (
    EmailConfigurationError,
    EmailDeliveryError,
    activation_url,
    is_email_configured,
    send_activation_email,
)
from backend.sops import get_departments, load_sops, retrieve_sops
from backend.user_import import UserImportError, parse_user_workbook


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_jwt_secret()
    initialize_database()
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


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, value: str) -> str:
        return normalize_email(value)


class ActivationRequest(BaseModel):
    token: str = Field(min_length=40, max_length=128)
    temporary_password: str = Field(min_length=12, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @model_validator(mode="after")
    def passwords_must_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("The new passwords do not match.")
        if self.new_password == self.temporary_password:
            raise ValueError("Choose a new password that differs from the temporary password.")
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


def new_activation_credentials() -> tuple[str, str, str, str]:
    if not is_email_configured():
        raise EmailConfigurationError(
            "Email is not configured. Set FOODIES_SMTP_HOST and FOODIES_EMAIL_FROM."
        )
    temporary_password = secrets.token_urlsafe(18)
    activation_token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat()
    return (
        temporary_password,
        activation_token,
        expires_at,
        activation_url(activation_token),
    )


def send_invitation(
    email: str,
    name: str,
    temporary_password: str,
    link: str,
) -> None:
    send_activation_email(
        email=email,
        name=name,
        temporary_password=temporary_password,
        link=link,
    )


def create_invited_user(payload: CreateUserRequest | BulkUserEntry) -> dict[str, str]:
    temporary_password, activation_token, expires_at, link = new_activation_credentials()
    user_id = create_user(
        email=str(payload.email),
        name=payload.name,
        department=payload.department,
        role=payload.role,
        password_hash=hash_password(temporary_password),
        is_active=False,
        must_change_password=True,
        activation_token_hash=hashlib.sha256(
            activation_token.encode("utf-8")
        ).hexdigest(),
        activation_expires_at=expires_at,
    )
    try:
        send_invitation(str(payload.email), payload.name, temporary_password, link)
    except (EmailConfigurationError, EmailDeliveryError) as exc:
        raise InvitationSendFailure(user_id, str(exc)) from exc
    return {"id": user_id, "email": str(payload.email)}


def send_invitation_for_existing_user(invited: dict) -> None:
    if invited["activation_token_hash"] is None:
        raise EmailConfigurationError(
            "This inactive account does not have a pending activation invitation."
        )
    temporary_password, activation_token, expires_at, link = new_activation_credentials()
    token_hash = hashlib.sha256(activation_token.encode("utf-8")).hexdigest()
    updated = update_activation_credentials(
        invited["id"],
        hash_password(temporary_password),
        token_hash,
        expires_at,
    )
    if not updated:
        raise EmailDeliveryError("The activation invitation could not be refreshed.")
    send_invitation(invited["email"], invited["name"], temporary_password, link)


@app.get("/activate", response_class=HTMLResponse)
def activate_page(request: Request):
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
    invited_user = get_user_by_activation_token_hash(token_hash)
    if (
        invited_user is None
        or not verify_password(
            payload.temporary_password,
            invited_user["password_hash"],
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The activation link or temporary password is invalid or expired.",
        )
    if not activate_user(
        token_hash=token_hash,
        expected_temporary_hash=invited_user["password_hash"],
        password_hash=hash_password(payload.new_password),
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The activation link or temporary password is invalid or expired.",
        )
    return {"activated": True, "email": invited_user["email"]}


@app.post("/api/auth/change-password")
def change_password(
    payload: PasswordChangeRequest,
    user: dict = Depends(get_password_change_user),
):
    if verify_password(payload.new_password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a new password that differs from the temporary password.",
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
    result = answer_question(payload.question, department, matches)
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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Account {exc.user_id} was created but the activation email failed: {exc}",
        ) from exc
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
            results.append({
                "email": email,
                "status": "pending_email",
                "id": exc.user_id,
                "message": str(exc),
            })
            continue
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
    temporary_password = secrets.token_urlsafe(18)
    if not reset_user_password(user_id, hash_password(temporary_password)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return {
        "id": user_id,
        "must_change_password": True,
        "temporary_password": temporary_password,
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
    try:
        deleted = delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
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
    owner: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
    effective_date: Annotated[str, Form()] = "",
    review_cycle_days: Annotated[int | None, Form()] = None,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    metadata = {
        "sop_id": sop_id,
        "title": title,
        "department": department,
        "owner": owner,
        "version": version,
        "effective_date": effective_date,
        "review_cycle_days": review_cycle_days,
    }
    for key, value in metadata.items():
        if key == "review_cycle_days":
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
    try:
        version_id = create_sop_version(
            sop_id=sop_id.strip(),
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
        )
        persisted = True
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    finally:
        if not persisted:
            storage_path.unlink(missing_ok=True)
    return {
        "id": version_id,
        "sop_id": sop_id.strip(),
        "status": "pending_review",
        "message": "SOP uploaded and queued for review.",
    }


@app.get("/api/admin/sops")
def admin_list_sops(
    status: Annotated[str | None, Query()] = None,
    department: Annotated[str | None, Query()] = None,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    return {"sops": list_sop_versions(status_filter=status, department=department)}


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
    return {"sop": sop, "sections": get_sop_sections(version_id)}


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
    return {"sop": updated, "events": list_sop_events(version_id)}


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
