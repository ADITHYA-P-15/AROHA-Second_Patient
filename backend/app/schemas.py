from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(Input):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(Input):
    email: EmailStr
    password: str


class PasswordIn(Input):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class PatientIn(Input):
    name: str = Field(min_length=1, max_length=160)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    care_notes: str = Field(default="", max_length=5000)
    clinical_notes: str = Field(default="", max_length=5000)
    mobility_level: str = Field(default="INDEPENDENT", pattern="^(INDEPENDENT|NEEDS_AID|WHEELCHAIR|BEDBOUND)$")
    language_pref: str = Field(default="en", max_length=8)


class PatientPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    care_notes: str | None = Field(default=None, max_length=5000)
    clinical_notes: str | None = Field(default=None, max_length=5000)
    mobility_level: str | None = Field(default=None, pattern="^(INDEPENDENT|NEEDS_AID|WHEELCHAIR|BEDBOUND)$")
    language_pref: str | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def reject_null_for_required_text(self):
        for field in ("name", "care_notes", "clinical_notes"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TeamIn(Input):
    email: EmailStr
    team_role: str


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    is_synthetic: bool


class PatientOut(BaseModel):
    id: UUID
    name: str
    birth_year: int | None
    care_notes: str
    clinical_notes: str | None
    is_synthetic: bool
    created_at: datetime

