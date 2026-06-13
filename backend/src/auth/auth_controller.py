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

from fastapi import APIRouter, Request, Response, HTTPException, status
from pydantic import BaseModel
import fastapi.security.utils

router = APIRouter(
    prefix="/api/auth",
    tags=["Auth"],
)


@router.post("/session")
async def create_session(request: Request, response: Response):
    authorization = request.headers.get("X-Custom-Auth") or request.headers.get(
        "Authorization"
    )
    if not authorization:
        raise HTTPException(
            status_code=400, detail="Missing authorization header"
        )

    scheme, param = fastapi.security.utils.get_authorization_scheme_param(
        authorization
    )
    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=400, detail="Invalid authorization scheme"
        )

    response.set_cookie(
        key="session_token",
        value=param,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=3600 * 24 * 7,  # 1 week
    )
    return {"message": "Session created successfully"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key="session_token", httponly=True, secure=True, samesite="lax"
    )
    return {"message": "Logged out successfully"}
