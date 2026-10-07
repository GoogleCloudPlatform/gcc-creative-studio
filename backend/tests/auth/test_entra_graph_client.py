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
"""Hermetic tests for EntraGraphClient (httpx.MockTransport, no network)."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs

import httpx
import pytest

from src.auth.entra_graph_client import (
    EntraGraphClient,
    EntraGraphError,
    EntraUserNotFoundError,
)

TOKEN_HOST = "login.microsoftonline.com"


class FakeGraph:
    """Records requests and serves canned Graph / token responses."""

    def __init__(self, members=(), user_exists=True, user_profile=None):
        self.members = {m.lower() for m in members}
        self.user_exists = user_exists
        self.user_profile = user_profile or {
            "id": "11111111-2222-3333-4444-555555555555",
            "mail": "Alice@Corp.com",
            "userPrincipalName": "alice.upn@corp.com",
        }
        self.requests: list[httpx.Request] = []
        self.graph_status: int | None = None
        self.raise_transport = False
        self.delay = 0.0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if request.url.host == TOKEN_HOST:
            return httpx.Response(
                200, json={"access_token": "tok", "expires_in": 3600}
            )
        if self.raise_transport:
            raise httpx.ConnectError("boom", request=request)
        if self.graph_status:
            return httpx.Response(self.graph_status)
        path = request.url.path
        if path.endswith("/checkMemberGroups"):
            if not self.user_exists:
                return httpx.Response(404)
            ids = json.loads(request.content)["groupIds"]
            return httpx.Response(
                200,
                json={"value": [g for g in ids if g.lower() in self.members]},
            )
        if path.startswith("/v1.0/users/") and request.method == "GET":
            if not self.user_exists:
                return httpx.Response(404)
            return httpx.Response(200, json=self.user_profile)
        return httpx.Response(500)

    def calls(self, host_or_suffix: str) -> list[httpx.Request]:
        return [
            r
            for r in self.requests
            if r.url.host == host_or_suffix
            or r.url.path.endswith(host_or_suffix)
        ]


def make_client(
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
) -> EntraGraphClient:
    return EntraGraphClient(
        "tenant",
        "client",
        "secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.anyio
async def test_member_lookup_uses_oid_in_one_call():
    fake = FakeGraph(members={"AAA"})
    client = make_client(fake)
    oid = "11111111-2222-3333-4444-555555555555"

    result = await client.member_group_ids(oid, ["aaa", "bbb"])

    assert result == {"aaa"}
    graph_calls = fake.calls("/checkMemberGroups")
    assert len(graph_calls) == 1
    assert graph_calls[0].url.path == f"/v1.0/users/{oid}/checkMemberGroups"
    assert graph_calls[0].headers["Authorization"] == "Bearer tok"


@pytest.mark.anyio
async def test_app_token_is_cached_across_calls():
    fake = FakeGraph()
    client = make_client(fake)

    await client.member_group_ids("a@corp.com", ["g1"])
    await client.member_group_ids("b@corp.com", ["g1"])

    assert len(fake.calls(TOKEN_HOST)) == 1


@pytest.mark.anyio
async def test_app_token_uses_client_credentials_grant():
    fake = FakeGraph()
    client = make_client(fake)

    await client.member_group_ids("a@corp.com", ["g1"])

    token_form = parse_qs(fake.calls(TOKEN_HOST)[0].content.decode())
    assert token_form["grant_type"] == ["client_credentials"]


@pytest.mark.anyio
async def test_group_ids_are_chunked_at_20_per_call():
    groups = [f"g{i:02d}" for i in range(45)]
    fake = FakeGraph(members={"g00", "g44"})
    client = make_client(fake)

    result = await client.member_group_ids("a@corp.com", groups)

    sizes = [
        len(json.loads(r.content)["groupIds"])
        for r in fake.calls("/checkMemberGroups")
    ]
    assert sizes == [20, 20, 5]
    assert result == {"g00", "g44"}


@pytest.mark.anyio
async def test_check_member_groups_404_raises_without_mail_fallback():
    fake = FakeGraph(user_exists=False)
    client = make_client(fake)

    with pytest.raises(EntraUserNotFoundError):
        await client.member_group_ids(
            "11111111-2222-3333-4444-555555555555", ["g1"]
        )

    assert len(fake.calls("/checkMemberGroups")) == 1
    assert not any(r.url.path == "/v1.0/users" for r in fake.requests)


@pytest.mark.anyio
async def test_get_user_emails_returns_lowercased_mail_and_upn():
    fake = FakeGraph(
        user_profile={
            "id": "11111111-2222-3333-4444-555555555555",
            "mail": " Alice@Corp.COM ",
            "userPrincipalName": "Alice.UPN@Corp.COM",
        }
    )
    client = make_client(fake)

    emails = await client.get_user_emails(
        "11111111-2222-3333-4444-555555555555"
    )

    assert emails == {"alice@corp.com", "alice.upn@corp.com"}


@pytest.mark.anyio
async def test_get_user_profile_returns_mail_display_name_and_all_emails():
    oid = "11111111-2222-3333-4444-555555555555"
    fake = FakeGraph(
        user_profile={
            "id": oid,
            "mail": " Alice@Corp.COM ",
            "userPrincipalName": "Alice.UPN@Corp.COM",
            "displayName": " Alice Smith ",
        }
    )
    client = make_client(fake)

    primary_email, display_name, all_emails = await client.get_user_profile(oid)

    assert primary_email == "alice@corp.com"
    assert display_name == "Alice Smith"
    assert all_emails == {"alice@corp.com", "alice.upn@corp.com"}
    user_calls = fake.calls(f"/v1.0/users/{oid}")
    assert len(user_calls) == 1
    assert (
        user_calls[0].url.params["$select"]
        == "id,mail,userPrincipalName,displayName"
    )


@pytest.mark.anyio
async def test_get_user_profile_falls_back_to_upn_when_mail_is_null():
    oid = "11111111-2222-3333-4444-555555555555"
    fake = FakeGraph(
        user_profile={
            "id": oid,
            "mail": None,
            "userPrincipalName": "Alice.UPN@Corp.COM",
            "displayName": None,
        }
    )
    client = make_client(fake)

    primary_email, display_name, all_emails = await client.get_user_profile(oid)

    assert primary_email == "alice.upn@corp.com"
    assert display_name is None
    assert all_emails == {"alice.upn@corp.com"}


@pytest.mark.anyio
async def test_get_user_emails_404_raises_user_not_found():
    fake = FakeGraph(user_exists=False)
    client = make_client(fake)

    with pytest.raises(EntraUserNotFoundError):
        await client.get_user_emails("11111111-2222-3333-4444-555555555555")


@pytest.mark.anyio
async def test_graph_5xx_raises_entra_graph_error():
    fake = FakeGraph()
    fake.graph_status = 503
    client = make_client(fake)

    with pytest.raises(EntraGraphError):
        await client.member_group_ids("a@corp.com", ["g1"])


@pytest.mark.anyio
async def test_transport_error_raises_entra_graph_error():
    fake = FakeGraph()
    fake.raise_transport = True
    client = make_client(fake)

    with pytest.raises(EntraGraphError):
        await client.member_group_ids("a@corp.com", ["g1"])


@pytest.mark.anyio
async def test_token_failure_raises_entra_graph_error():
    async def handler(request):
        return httpx.Response(401)

    client = make_client(handler)

    with pytest.raises(EntraGraphError):
        await client.member_group_ids("a@corp.com", ["g1"])


def _body_response(body) -> httpx.Response:
    if isinstance(body, bytes):
        return httpx.Response(200, content=body)
    return httpx.Response(200, json=body)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        {"token_type": "Bearer"},
        [],
        {"access_token": "tok", "expires_in": "soon"},
    ],
    ids=["non-json", "no-access-token", "list", "bad-expires-in"],
)
@pytest.mark.anyio
async def test_malformed_token_body_raises_entra_graph_error(body):
    async def handler(request):
        return _body_response(body)

    client = make_client(handler)

    with pytest.raises(EntraGraphError):
        await client.member_group_ids("a@corp.com", ["g1"])


@pytest.mark.anyio
async def test_malformed_token_is_not_cached():
    token_requests = []

    async def handler(request):
        token_requests.append(request)
        return _body_response({"access_token": "tok", "expires_in": "soon"})

    client = make_client(handler)
    with pytest.raises(EntraGraphError):
        await client.member_group_ids("a@corp.com", ["g1"])

    with pytest.raises(EntraGraphError):
        await client.member_group_ids("a@corp.com", ["g1"])

    assert len(token_requests) == 2


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        {},
        {"value": None},
        {"value": 5},
        {"value": "abc"},
        [],
        {"value": [1]},
    ],
    ids=[
        "non-json",
        "missing-value",
        "null-value",
        "int-value",
        "str-value",
        "list-body",
        "non-str-group",
    ],
)
@pytest.mark.anyio
async def test_malformed_check_member_groups_body_raises_entra_graph_error(
    body,
):
    async def handler(request):
        if request.url.host == TOKEN_HOST:
            return httpx.Response(200, json={"access_token": "tok"})
        return _body_response(body)

    client = make_client(handler)

    with pytest.raises(EntraGraphError):
        await client.member_group_ids("a@corp.com", ["abc"])


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        [],
        {"mail": 123},
        {"userPrincipalName": ["not-a-str"]},
    ],
    ids=["non-json", "list-body", "non-str-mail", "non-str-upn"],
)
@pytest.mark.anyio
async def test_malformed_get_user_emails_body_raises_entra_graph_error(body):
    async def handler(request):
        if request.url.host == TOKEN_HOST:
            return httpx.Response(200, json={"access_token": "tok"})
        return _body_response(body)

    client = make_client(handler)

    with pytest.raises(EntraGraphError):
        await client.get_user_emails("11111111-2222-3333-4444-555555555555")


@pytest.mark.anyio
async def test_concurrent_lookups_for_same_user_share_one_round_trip():
    fake = FakeGraph(members={"g1"})
    fake.delay = 0.01
    client = make_client(fake)

    results = await asyncio.gather(
        *(client.member_group_ids("a@corp.com", ["g1"]) for _ in range(5))
    )

    assert results == [{"g1"}] * 5
    assert len(fake.calls("/checkMemberGroups")) == 1


@pytest.mark.anyio
async def test_lookup_after_shared_call_finished_calls_graph_again():
    fake = FakeGraph(members={"g1"})
    fake.delay = 0.01
    client = make_client(fake)
    await asyncio.gather(
        *(client.member_group_ids("a@corp.com", ["g1"]) for _ in range(2))
    )

    await client.member_group_ids("a@corp.com", ["g1"])

    assert len(fake.calls("/checkMemberGroups")) == 2
