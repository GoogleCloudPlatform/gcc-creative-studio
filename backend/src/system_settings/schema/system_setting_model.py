# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
from pydantic import Field
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from src.common.base_repository import BaseStringDocument
from src.database import Base


class SystemSetting(Base):
    """SQLAlchemy model for the 'system_settings' table."""

    __tablename__ = "system_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        onupdate=func.now(),
        server_default=func.now(),
    )


class SystemSettingModel(BaseStringDocument):
    """Pydantic model representing a system setting."""

    id: str = Field(
        description="The key of the setting (e.g. show_gemini_omni)."
    )
    value: str = Field(description="The value of the setting as a string.")
    description: str | None = Field(
        default=None,
        description="Optional description of what the setting does.",
    )
