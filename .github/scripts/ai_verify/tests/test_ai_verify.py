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

"""Unit and integration tests for `.github/scripts/ai_verify`."""

import asyncio
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ai_verify.cli import main as cli_main  # noqa: E402
from ai_verify.consensus import (  # noqa: E402
    InlineReviewComment,
    REPORT_MARKER,
    build_inline_comments,
    merge_step_findings,
    render_markdown_report,
    run_verification_pipeline,
    snap_to_valid_diff_line,
)
from ai_verify.context_pack import (  # noqa: E402
    build_context_pack,
    classify_area,
    extract_python_enclosing_context,
    extract_valid_right_lines,
    is_license_only_diff,
    parse_numstat,
    select_active_steps,
)
from ai_verify.github_publisher import GitHubPublisher  # noqa: E402
from ai_verify.models import (  # noqa: E402
    AGREEMENT_CONSENSUS,
    AGREEMENT_VERIFIED_SINGLE,
    ContextPack,
    FileContext,
    Finding,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    StaticSignal,
    TestMapping,
    TokenUsage,
    VERIFICATION_STEPS,
)
from ai_verify.prompts import (  # noqa: E402
    render_adjudication_prompt,
    render_shared_context_prefix,
    render_step_prompt,
)
from ai_verify.providers import (  # noqa: E402
    BudgetExceededError,
    ClaudeVerifier,
    GeminiVerifier,
    TokenBudgetTracker,
    _with_retries,
    normalize_findings,
    parse_json_payload,
)
from ai_verify.static_checks import (  # noqa: E402
    build_test_mappings,
    collect_static_signals,
    slice_repo_rules,
)


def _sample_file_context(
    path: str = "backend/src/folders/folder_service.py",
    area: str = "backend",
    is_test: bool = False,
    diff: str = (
        "@@ -10,2 +10,4 @@\n"
        " context\n"
        "+added_one = 1\n"
        "+added_two = 2\n"
        " context_after\n"
    ),
    valid_lines: list[int] | None = None,
) -> FileContext:
    return FileContext(
        path=path,
        old_path=None,
        area=area,
        is_test=is_test,
        added_lines=2,
        deleted_lines=0,
        diff=diff,
        enclosing_context="def update_folder():\n    pass",
        valid_right_lines=valid_lines or [10, 11, 12, 13],
    )


def test_verification_steps_cover_all_six_domains():
    ids = [s.step_id for s in VERIFICATION_STEPS]
    assert ids == [
        "security",
        "correctness",
        "architecture",
        "infra_migration",
        "db_schema_migrations",
        "agent_media_pipeline",
        "workflow_dag_executor",
        "supply_chain_ci",
        "cross_file_impact",
        "frontend_ux_a11y",
        "test_adequacy",
        "quality_perf",
        "runtime_ci_triage",
        "api_docs",
        "pr_intent_synthesizer",
    ]
    blocking = [s.step_id for s in VERIFICATION_STEPS if s.blocking]
    assert blocking == [
        "security",
        "correctness",
        "architecture",
        "infra_migration",
        "db_schema_migrations",
        "agent_media_pipeline",
        "workflow_dag_executor",
        "supply_chain_ci",
        "cross_file_impact",
        "runtime_ci_triage",
    ]


def test_context_pack_roundtrip_serialization():
    pack = ContextPack(
        base_sha="aaaa1111",
        head_sha="bbbb2222",
        pr_title="feat: add folder check",
        pr_body="Adds workspace validation",
        areas_touched=["backend"],
        active_steps=["security", "correctness"],
        files=[_sample_file_context()],
        static_signals=[
            StaticSignal(
                "repo-rules",
                "architecture",
                SEVERITY_HIGH,
                "backend/a.py",
                5,
                "CODE1",
                "Msg",
            )
        ],
        test_mappings=[
            TestMapping(
                "backend/a.py",
                ["backend/tests/test_a.py"],
                ["backend/tests/test_a.py"],
                ["test_a"],
            )
        ],
        repo_rules=["Rule 1"],
    )
    restored = ContextPack.from_dict(json.loads(json.dumps(pack.to_dict())))
    assert restored.base_sha == "aaaa1111"
    assert restored.files[0].path == "backend/src/folders/folder_service.py"
    assert restored.static_signals[0].code == "CODE1"
    assert restored.test_mappings[0].test_symbols == ["test_a"]


def test_parse_numstat_handles_renames_and_binaries():
    raw = (
        "12\t3\tbackend/src/a.py\0"
        "-\t-\tfrontend/logo.png\0"
        "5\t1\t\0backend/old.py\0backend/new.py\0"
    )
    entries, binaries = parse_numstat(raw)
    assert binaries == 1
    assert len(entries) == 2
    assert entries[0] == ("backend/src/a.py", None, 12, 3)
    assert entries[1] == ("backend/new.py", "backend/old.py", 5, 1)


def test_extract_valid_right_lines_and_license_detection():
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -4,3 +4,4 @@\n"
        " unchanged_before\n"
        "-removed_line\n"
        "+added_line_a\n"
        "+added_line_b\n"
        " unchanged_after\n"
    )
    assert extract_valid_right_lines(diff) == [4, 5, 6, 7]
    assert not is_license_only_diff(diff)
    assert is_license_only_diff("")

    license_diff = (
        "@@ -0,0 +1,3 @@\n"
        "+# Copyright 2026 Google LLC\n"
        "+# Licensed under the Apache License, Version 2.0\n"
        "+#\n"
    )
    assert is_license_only_diff(license_diff)


def test_extract_python_enclosing_context_and_syntax_error():
    source = (
        "import os\n\n"
        "async def verify_access(user_id: int) -> bool:\n"
        "    if user_id <= 0:\n"
        "        return False\n"
        "    return True\n"
    )
    ctx = extract_python_enclosing_context(source, [5])
    assert "def verify_access" in ctx
    assert "return False" in ctx
    assert extract_python_enclosing_context("def broken(:", [1]) == ""
    assert extract_python_enclosing_context("", [1]) == ""


def test_select_active_steps_skips_code_steps_for_docs_only():
    assert select_active_steps([]) == []
    doc_only = [_sample_file_context(path="DEPLOYMENT.md", area="other")]
    assert select_active_steps(doc_only) == [
        "api_docs",
        "pr_intent_synthesizer",
    ]

    full_stack = [
        _sample_file_context(
            path="backend/src/users/user_controller.py", area="backend"
        ),
        _sample_file_context(
            path="frontend/src/app/user.service.ts", area="frontend"
        ),
    ]
    assert select_active_steps(full_stack) == [
        "security",
        "correctness",
        "architecture",
        "cross_file_impact",
        "frontend_ux_a11y",
        "test_adequacy",
        "quality_perf",
        "runtime_ci_triage",
        "api_docs",
        "pr_intent_synthesizer",
    ]
    assert classify_area("bootstrap.sh") == "infrastructure"
    assert classify_area(".github/workflows/ci.yml") == "ci"
    assert classify_area("README.md") == "other"


def test_static_checks_detect_backend_alembic_frontend_bandit_and_infra_traps():
    py_ctrl = _sample_file_context(
        path="backend/src/items/item_controller.py",
        area="backend",
        diff=(
            "@@ -1,1 +1,15 @@\n"
            "+@router.post('/items')\n"
            "+async def create_item(q: str):\n"
            "+    eval(q)\n"
            "+    subprocess.run(q, shell=True)\n"
            "+    db.execute(text(f'SELECT * FROM items WHERE name = {q}'))\n"
            "+    v = os.getenv('NEW_UNTRACKED_ENV')\n"
            "+    for x in [1, 2]:\n"
            "+        await do_rpc(x)\n"
            "+class ItemService:\n"
            "+    def assert_valid(self):\n"
            "+        pass\n"
        ),
        valid_lines=list(range(1, 20)),
    )
    py_source = (
        "import os\nimport subprocess\n"
        "from sqlalchemy import text\n"
        "@router.post('/items')\n"
        "async def create_item(q: str):\n"
        "    eval(q)\n"
        "    subprocess.run(q, shell=True)\n"
        "    db.execute(text(f'SELECT * FROM items WHERE name = {q}'))\n"
        "    v = os.getenv('NEW_UNTRACKED_ENV')\n"
        "    for x in [1, 2]:\n"
        "        await do_rpc(x)\n"
        "class ItemService:\n"
        "    def assert_valid(self):\n"
        "        pass\n"
    )
    alembic_file = _sample_file_context(
        path="backend/alembic/versions/001_drop.py",
        area="backend",
        diff=(
            "@@ -1,1 +1,4 @@\n"
            "+def upgrade():\n"
            "+    op.drop_column('users', 'legacy')\n"
            "+    op.add_column('users', sa.Column('org', sa.String(), nullable=False))\n"
        ),
        valid_lines=[1, 2, 3, 4, 5],
    )
    alembic_src = (
        "from alembic import op\nimport sqlalchemy as sa\n"
        "def upgrade():\n"
        "    op.drop_column('users', 'legacy')\n"
        "    op.add_column('users', sa.Column('org', sa.String(), nullable=False))\n"
    )
    broken_py = _sample_file_context(
        path="backend/src/broken.py",
        area="backend",
        diff="@@ -1,1 +1,1 @@\n+def oops(:\n",
        valid_lines=[1],
    )
    fe_comp = _sample_file_context(
        path="frontend/src/app/demo/demo.component.ts",
        area="frontend",
        diff=(
            "@@ -1,1 +1,4 @@\n"
            "+console.log('debug');\n"
            "+fetch('/api/items');\n"
            "+const k = 'sk-ant-api03-1234567890abcdefghijklmno';\n"
        ),
        valid_lines=[1, 2, 3, 4],
    )
    fe_html = _sample_file_context(
        path="frontend/src/app/demo/demo.component.html",
        area="frontend",
        diff='@@ -1,1 +1,1 @@\n+<div *ngFor="let item of items">{{item}}</div>\n',
        valid_lines=[1],
    )
    sh_file = _sample_file_context(
        path="bootstrap.sh",
        area="infrastructure",
        diff=(
            "@@ -1,1 +1,3 @@\n"
            "+REGION='us-central1'\n"
            "+COUNT=$(grep -c foo bar.txt || echo 0)\n"
        ),
        valid_lines=[1, 2, 3],
    )
    md_file = _sample_file_context(
        path="README.md",
        area="other",
        diff="@@ -1,1 +1,3 @@\n+```mermaid\n+A[<env>] --> B\n+```\n",
        valid_lines=[1, 2, 3],
    )

    contents = {
        py_ctrl.path: py_source,
        alembic_file.path: alembic_src,
        broken_py.path: "def oops(:\n",
        fe_comp.path: "console.log('debug');\nfetch('/api/items');\n",
        fe_html.path: '<div *ngFor="let item of items"></div>\n',
        sh_file.path: "#!/usr/bin/env bash\nif [ then\n",
        md_file.path: "```mermaid\ngraph LR\n  A[<env>] --> B\n```\n",
    }

    def fake_which(cmd: str) -> str | None:
        if cmd == "bandit":
            return "/usr/bin/bandit"
        if cmd == "bash":
            return "/bin/bash"
        return None

    def fake_subproc(args: list[str], **kwargs: Any) -> Any:
        del kwargs
        if args[0] == "/usr/bin/bandit":
            # Target file path is passed at the end of args
            target_file = next(
                a for a in args if a.endswith("item_controller.py")
            )
            out = json.dumps(
                {
                    "results": [
                        {
                            "filename": target_file,
                            "line_number": 4,
                            "issue_severity": "HIGH",
                            "test_id": "B602",
                            "issue_text": "subprocess call with shell=True",
                        }
                    ]
                }
            )
            return SimpleNamespace(returncode=1, stdout=out, stderr="")
        return SimpleNamespace(
            returncode=2, stdout="", stderr="syntax error near unexpected token"
        )

    with (
        patch("ai_verify.static_checks.shutil.which", side_effect=fake_which),
        patch(
            "ai_verify.static_checks.subprocess.run", side_effect=fake_subproc
        ),
    ):
        signals = collect_static_signals(
            [
                py_ctrl,
                alembic_file,
                broken_py,
                fe_comp,
                fe_html,
                sh_file,
                md_file,
            ],
            contents.get,
        )

    codes = {s.code for s in signals}
    assert {
        "SEC003",
        "PY_SEC_EXEC",
        "PY_SEC_SHELL",
        "PY_SEC_SQL",
        "FASTAPI_NO_DEPENDS",
        "RULE_ASSERT_METHOD",
        "PY_LOOP_AWAIT",
        "ALEMBIC_DROP",
        "ALEMBIC_NONNULL",
        "PY000",
        "B602",
        "FE_CONSOLE_LOG",
        "FE_COMPONENT_HTTP",
        "FE_NGFOR_TRACKBY",
        "HARDCODED_REGION",
        "SH_GREP_C_TRAP",
        "SH_SYNTAX",
        "MD_MERMAID_ANGLE",
        "DOCS_NEW_CONFIG",
    }.issubset(codes)


def test_test_mappings_and_rule_slicing_all_domains():
    be_src = _sample_file_context(
        path="backend/src/folders/folder_service.py", area="backend"
    )
    be_test = _sample_file_context(
        path="backend/tests/folders/test_folder_service.py",
        area="backend",
        is_test=True,
    )
    fe_src = _sample_file_context(
        path="frontend/src/app/header/header.component.ts", area="frontend"
    )
    sh_src = _sample_file_context(path="bootstrap.sh", area="infrastructure")
    repo_paths = {
        be_src.path,
        be_test.path,
        "frontend/src/app/header/header.component.spec.ts",
        "infrastructure/tests/test_bootstrap_offline.sh",
    }
    reader = {
        be_test.path: "async def test_ensure_can_manage_folder():\n    assert True\n",
        "frontend/src/app/header/header.component.spec.ts": (
            "it('renders floating menu', () => {});\n"
        ),
    }.get
    mappings = build_test_mappings(
        [be_src, be_test, fe_src, sh_src], repo_paths, reader
    )
    assert len(mappings) == 3
    assert "test_ensure_can_manage_folder" in mappings[0].test_symbols
    assert "renders floating menu" in mappings[1].test_symbols

    all_rules = slice_repo_rules(
        ["backend", "frontend", "infrastructure"],
        ["backend/a.py", "frontend/b.ts", "bootstrap.sh", "DEPLOYMENT.md"],
    )
    assert any("Lyria 3" in r for r in all_rules)
    assert any("Angular Signals" in r for r in all_rules)
    assert any("us-central1" in r for r in all_rules)
    assert any("DEPLOYMENT.md" in r for r in all_rules)


def test_prompts_include_signals_mappings_and_adjudication():
    fctx = _sample_file_context()
    pack = ContextPack(
        base_sha="111",
        head_sha="222",
        pr_title="Demo PR",
        pr_body="Detailed PR body",
        active_steps=["security", "correctness"],
        files=[fctx],
        static_signals=[
            StaticSignal(
                "bandit",
                "security",
                SEVERITY_HIGH,
                fctx.path,
                11,
                "B602",
                "Shell injection",
            )
        ],
        test_mappings=[
            TestMapping(fctx.path, ["backend/tests/test_f.py"], [], ["test_ok"])
        ],
        repo_rules=["Rule A"],
    )
    prefix = render_shared_context_prefix(pack)
    assert "<TEST_MAPPINGS>" in prefix
    assert "Detailed PR body" in prefix

    sec_prompt = render_step_prompt(pack, "security")
    assert "B602" in sec_prompt

    finding = Finding(
        step_id="security",
        file=fctx.path,
        line_start=11,
        line_end=12,
        severity=SEVERITY_HIGH,
        category="injection",
        title="Shell True",
        evidence="Uses shell=True",
    )
    adj = render_adjudication_prompt(finding, fctx.diff, fctx.enclosing_context)
    assert "<CODE_UNDER_REVIEW>" in adj
    assert "Shell True" in adj


def test_providers_vertex_gemini_and_claude_plus_retries():
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise RuntimeError("transient 429")
        return "ok"

    with patch("ai_verify.providers.asyncio.sleep", return_value=None):
        assert asyncio.run(_with_retries(flaky, attempts=3)) == "ok"

    gem = GeminiVerifier(env={"GOOGLE_CLOUD_PROJECT": "demo-gcp-proj"})
    fake_gem_resp = SimpleNamespace(
        text='{"findings": [{"file": "backend/a.py", "line_start": 3, "line_end": 4, "severity": "MEDIUM", "category": "bug", "title": "Edge case", "evidence": "Null input", "confidence": 0.85}]}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=400,
            cached_content_token_count=300,
            candidates_token_count=45,
        ),
    )

    async def fake_gen_content(**kwargs: Any) -> Any:
        del kwargs
        return fake_gem_resp

    gem._client = SimpleNamespace(  # pylint: disable=protected-access
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_gen_content)
        )
    )
    fake_genai_mod = SimpleNamespace(
        types=SimpleNamespace(
            GenerateContentConfig=lambda **kw: SimpleNamespace(**kw)
        )
    )
    budget = TokenBudgetTracker()
    with patch.dict(
        sys.modules,
        {
            "google": SimpleNamespace(genai=fake_genai_mod),
            "google.genai": fake_genai_mod,
        },
    ):
        res = asyncio.run(
            gem.run_step("correctness", "PREFIX", "STEP", False, budget)
        )
        adj_res = asyncio.run(gem.adjudicate("correctness", "ADJ", budget))

    assert len(res) == 1
    assert res[0].severity == SEVERITY_MEDIUM
    assert isinstance(adj_res, dict)
    assert budget.records[0].cached_input_tokens == 300

    # Claude adjudicate & text fallback
    cld = ClaudeVerifier(env={"ANTHROPIC_API_KEY": "sk-ant-test"})
    fake_cld_adj = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            output_tokens=20,
        ),
        content=[
            SimpleNamespace(
                type="text",
                text='{"verdict": "CONFIRMED", "adjusted_severity": "HIGH", "reason": "Valid"}',
            )
        ],
    )

    async def fake_cld_create(**kwargs: Any) -> Any:
        del kwargs
        return fake_cld_adj

    cld._client = SimpleNamespace(  # pylint: disable=protected-access
        messages=SimpleNamespace(create=fake_cld_create)
    )
    verdict = asyncio.run(cld.adjudicate("security", "PROMPT", budget))
    assert verdict["verdict"] == "CONFIRMED"

    assert parse_json_payload("") == {}
    assert normalize_findings({"findings": "bad"}, "security", "m") == []


class _FakeVerifier:
    """Deterministic in-memory ``ModelVerifier`` stub for consensus tests."""

    def __init__(
        self,
        provider_name: str,
        step_findings: dict[str, list[Finding]],
        adjudication_verdict: str = "CONFIRMED",
        fail_on_step: str = "",
    ) -> None:
        self.provider_name = provider_name
        self._step_findings = step_findings
        self._verdict = adjudication_verdict
        self._fail_on_step = fail_on_step

    def is_available(self) -> bool:
        return True

    def model_for_tier(self, deep: bool) -> str:
        return "deep-v1" if deep else "fast-v1"

    async def run_step(
        self,
        step_id: str,
        shared_prefix: str,
        step_prompt: str,
        deep: bool,
        budget: TokenBudgetTracker,
    ) -> list[Finding]:
        del shared_prefix, step_prompt, deep
        budget.check_available()
        if step_id == self._fail_on_step:
            raise RuntimeError("provider timeout")
        budget.record(
            TokenUsage(self.provider_name, "mock-model", step_id, 500, 400, 60)
        )
        return [
            Finding(**{**f.__dict__})
            for f in self._step_findings.get(step_id, [])
        ]

    async def adjudicate(
        self,
        step_id: str,
        prompt: str,
        budget: TokenBudgetTracker,
    ) -> dict[str, Any]:
        del prompt
        budget.record(
            TokenUsage(self.provider_name, "mock-fast", step_id, 200, 0, 30)
        )
        return {
            "verdict": self._verdict,
            "adjusted_severity": SEVERITY_HIGH,
            "reason": f"Peer verdict={self._verdict}",
        }


def test_consensus_merging_adjudication_empty_pack_and_provider_errors():
    # Empty pack skips cleanly
    empty_pack = ContextPack(base_sha="a", head_sha="b")
    empty_rep = asyncio.run(
        run_verification_pipeline(empty_pack, None, None, gate_mode="blocking")
    )
    assert empty_rep.gate_passed
    assert all(o.skipped for o in empty_rep.outcomes)

    fctx = _sample_file_context()
    pack = ContextPack(
        base_sha="1111aaaa",
        head_sha="2222bbbb",
        pr_title="Test PR",
        areas_touched=["backend"],
        active_steps=["security", "correctness", "quality_perf"],
        files=[fctx],
        skipped_files=["backend/huge.py"],
        static_signals=[
            StaticSignal(
                "repo-rules",
                "architecture",
                SEVERITY_LOW,
                fctx.path,
                10,
                "R1",
                "Note",
            )
        ],
    )

    gem_sec = Finding(
        step_id="security",
        file=fctx.path,
        line_start=11,
        line_end=12,
        severity=SEVERITY_HIGH,
        category="idor",
        title="Folder lookup missing workspace_id",
        evidence="Queries folder by primary key without workspace scope.",
        suggestion="Add workspace_id == current_workspace.id",
        confidence=0.90,
        models=["gemini:deep-v1"],
    )
    cld_sec = Finding(
        step_id="security",
        file=fctx.path,
        line_start=12,
        line_end=13,
        severity=SEVERITY_CRITICAL,
        category="idor",
        title="Cross-workspace folder IDOR",
        evidence="Any user can mutate foreign workspace folder.",
        suggestion="Filter by workspace_id and call ensure_can_manage_folder.",
        confidence=0.92,
        models=["claude:deep-v1"],
    )
    gem_only_bug = Finding(
        step_id="correctness",
        file=fctx.path,
        line_start=11,
        line_end=11,
        severity=SEVERITY_HIGH,
        category="async",
        title="Unawaited coroutine",
        evidence="Missing await on async repo call.",
        confidence=0.88,
        models=["gemini:deep-v1"],
    )
    low_valid = Finding(
        step_id="quality_perf",
        file=fctx.path,
        line_start=11,
        line_end=11,
        severity=SEVERITY_LOW,
        category="perf",
        title="Small optimization",
        evidence="Minor allocation",
        confidence=0.90,
        models=["gemini:fast-v1"],
    )

    gem_stub = _FakeVerifier(
        "gemini",
        {
            "security": [gem_sec],
            "correctness": [gem_only_bug],
            "quality_perf": [low_valid],
        },
    )
    cld_stub = _FakeVerifier(
        "claude",
        {"security": [cld_sec]},
        adjudication_verdict="CONFIRMED",
        fail_on_step="quality_perf",
    )
    blocking_report = asyncio.run(
        run_verification_pipeline(
            pack, gem_stub, cld_stub, gate_mode="blocking"
        )
    )
    assert not blocking_report.gate_passed

    sec_out = next(
        o for o in blocking_report.outcomes if o.step_id == "security"
    )
    assert sec_out.findings[0].agreement == AGREEMENT_CONSENSUS
    cor_out = next(
        o for o in blocking_report.outcomes if o.step_id == "correctness"
    )
    assert cor_out.findings[0].agreement == AGREEMENT_VERIFIED_SINGLE

    md = render_markdown_report(blocking_report, pack)
    assert REPORT_MARKER in md
    assert "backend/huge.py" in md
    assert "Consensus (Gemini + Claude)" in md

    inline = build_inline_comments(blocking_report, pack)
    assert len(inline) == 2

    # Reject path
    gem_fp = _FakeVerifier("gemini", {"correctness": [gem_only_bug]})
    cld_reject = _FakeVerifier("claude", {}, adjudication_verdict="REJECTED")
    rejected_report = asyncio.run(
        run_verification_pipeline(
            pack, gem_fp, cld_reject, gate_mode="blocking"
        )
    )
    assert rejected_report.gate_passed


def test_snap_and_noise_filtering():
    assert snap_to_valid_diff_line(12, []) is None
    assert snap_to_valid_diff_line(12, [10, 11, 12, 13]) == 12
    assert snap_to_valid_diff_line(15, [10, 11, 12, 13]) == 13
    assert snap_to_valid_diff_line(50, [10, 11, 12, 13]) is None

    low_noise = Finding(
        step_id="quality_perf",
        file="backend/a.py",
        line_start=1,
        line_end=1,
        severity=SEVERITY_LOW,
        category="style",
        title="Minor nit",
        evidence="Nitpick",
        confidence=0.60,
        models=["gemini:fast"],
    )
    assert merge_step_findings([low_noise], []) == []


def test_github_publisher_create_update_and_error_handling():
    calls: list[tuple[str, str, Any]] = []

    def fake_urlopen(req: Any, timeout: int = 30) -> Any:
        del timeout
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        calls.append((req.get_method(), req.full_url, body))
        resp = MagicMock()
        resp.__enter__.return_value = resp
        if req.get_method() == "GET" and "/issues/7/comments" in req.full_url:
            resp.read.return_value = b"[]"
        elif req.get_method() == "GET" and "/pulls/7/comments" in req.full_url:
            resp.read.return_value = json.dumps(
                [
                    {
                        "path": "backend/a.py",
                        "line": 10,
                        "body": "🔴 CRITICAL · 🤝 **Consensus (Gemini + Claude)**",
                    }
                ]
            ).encode("utf-8")
        else:
            resp.read.return_value = b'{"id": 1}'
        return resp

    pub = GitHubPublisher(repo="org/repo", token="tok")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        pub.upsert_summary_comment(7, f"{REPORT_MARKER}\nFresh report")
        pub.post_inline_review(
            7,
            "abcdef123456",
            [
                InlineReviewComment("backend/a.py", 10, "already exists"),
                InlineReviewComment("backend/a.py", 11, "new comment"),
            ],
        )

    assert any(m == "POST" and "/issues/7/comments" in u for m, u, _ in calls)
    assert any(m == "POST" and "/pulls/7/reviews" in u for m, u, _ in calls)

    # HTTP 422 / URLError graceful swallow
    http_err = urllib.error.HTTPError(
        "https://api.github.com", 422, "Unprocessable", None, io.BytesIO(b"")  # type: ignore[arg-type]
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        pub.upsert_summary_comment(7, "text")
        pub.post_inline_review(
            7, "abcdef12", [InlineReviewComment("a.py", 1, "x")]
        )


def test_build_context_pack_and_cli_prepare_verify_with_mocked_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    diff_sample = (
        "--- a/backend/src/demo/service.py\n"
        "+++ b/backend/src/demo/service.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def greet(name: str) -> str:\n"
        "+    name = name.strip()\n"
        "     return f'hi {name}'\n"
    )

    def fake_git(*args: str, check: bool = True) -> str:
        del check
        if args[0] == "diff" and "--numstat" in args:
            return (
                "1\t0\tbackend/src/demo/service.py\0"
                "50\t0\tpackage-lock.json\0"
            )
        if args[0] == "diff":
            return diff_sample
        if args[0] == "show":
            return (
                "def greet(name: str) -> str:\n"
                "    name = name.strip()\n"
                "    return f'hi {name}'\n"
            )
        if args[0] == "ls-tree":
            return "backend/src/demo/service.py\nbackend/tests/demo/test_service.py\n"
        return ""

    gh_out = tmp_path / "gh_output.txt"
    gh_sum = tmp_path / "gh_summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(gh_sum))
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")

    pack_path = tmp_path / "pack.json"
    report_path = tmp_path / "report.md"
    results_path = tmp_path / "results.json"

    with patch("ai_verify.context_pack._git", side_effect=fake_git):
        built = build_context_pack("base123", "head456", max_pack_chars=50_000)
        assert len(built.files) == 1
        assert built.ignored_count == 1

        rc_prep = cli_main(
            [
                "prepare",
                "--base",
                "base123",
                "--head",
                "head456",
                "--pr-number",
                "99",
                "--output",
                str(pack_path),
            ]
        )
        assert rc_prep == 0

    with (
        patch(
            "ai_verify.cli.GeminiVerifier",
            return_value=_FakeVerifier("gemini", {}),
        ),
        patch(
            "ai_verify.cli.ClaudeVerifier",
            return_value=_FakeVerifier("claude", {}),
        ),
        patch.object(GitHubPublisher, "upsert_summary_comment") as mock_upsert,
        patch.object(GitHubPublisher, "post_inline_review") as mock_inline,
        patch.object(GitHubPublisher, "publish_check_run") as mock_check,
    ):
        rc_ver = cli_main(
            [
                "verify",
                "--pack",
                str(pack_path),
                "--report",
                str(report_path),
                "--results",
                str(results_path),
                "--gate-mode",
                "blocking",
                "--publish-pr",
                "99",
                "--post-inline",
                "--publish-check-run",
            ]
        )
    assert rc_ver == 0
    assert mock_upsert.called
    assert mock_inline.called
    assert mock_check.called
    assert mock_check.call_args.kwargs["incomplete"] is False
    assert "has_active_steps" in gh_out.read_text(encoding="utf-8")
    assert "All Verification Checks Clean" in gh_sum.read_text(encoding="utf-8")


def test_fork_authorization_and_check_run_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pub = GitHubPublisher(repo="org/repo", token="tok")

    # 1. Collaborator with matching SHA -> allowed
    with patch.object(
        pub,
        "_request",
        return_value={
            "state": "open",
            "head": {"sha": "sha_good"},
            "author_association": "COLLABORATOR",
            "labels": [],
        },
    ):
        allowed, reason = pub.verify_fork_pr_authorization(12, "sha_good")
        assert allowed
        assert "COLLABORATOR" in reason

    # 2. Spoofed / mismatched SHA -> rejected even if collaborator
    with patch.object(
        pub,
        "_request",
        return_value={
            "state": "open",
            "head": {"sha": "sha_other_pr"},
            "author_association": "COLLABORATOR",
            "labels": [],
        },
    ):
        allowed, reason = pub.verify_fork_pr_authorization(12, "sha_good")
        assert not allowed
        assert "SHA mismatch" in reason

    # 3. External contributor with maintainer label -> allowed; without -> rejected
    with patch.object(
        pub,
        "_request",
        return_value={
            "state": "open",
            "head": {"sha": "sha_ext"},
            "author_association": "FIRST_TIME_CONTRIBUTOR",
            "labels": [{"name": "ai-verify"}],
        },
    ):
        allowed, _ = pub.verify_fork_pr_authorization(15, "sha_ext")
        assert allowed

    with patch.object(
        pub,
        "_request",
        return_value={
            "state": "open",
            "head": {"sha": "sha_ext"},
            "author_association": "NONE",
            "labels": [],
        },
    ):
        allowed, _ = pub.verify_fork_pr_authorization(15, "sha_ext")
        assert not allowed

    # 4. Check Run publisher posts conclusion
    posted: list[dict[str, Any]] = []
    with patch.object(
        pub,
        "_request",
        side_effect=lambda m, p, body=None: posted.append(body or {}),
    ):
        pub.publish_check_run("sha_good", False, "## Report")
    assert posted[0]["conclusion"] == "failure"
    assert posted[0]["head_sha"] == "sha_good"

    # 5. CLI authorize-fork end-to-end
    gh_out = tmp_path / "fork_out.txt"
    pack_file = tmp_path / "fork_pack.json"
    pack = ContextPack(
        base_sha="b1",
        head_sha="sha_good",
        pr_number=329,
        active_steps=["security"],
        files=[_sample_file_context()],
    )
    pack_file.write_text(json.dumps(pack.to_dict()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("GH_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")

    with patch.object(
        GitHubPublisher,
        "verify_fork_pr_authorization",
        return_value=(True, "Authorized via COLLABORATOR"),
    ):
        rc = cli_main(
            [
                "authorize-fork",
                "--pack",
                str(pack_file),
                "--expected-head-sha",
                "sha_good",
            ]
        )
    assert rc == 0
    out_txt = gh_out.read_text(encoding="utf-8")
    assert "should_verify" in out_txt and "true" in out_txt
    assert "329" in out_txt


def test_thinking_config_fallbacks_and_parallel_step_execution():
    import time
    from ai_verify.models import STEP_BY_ID, TIER_DUAL_FAST

    assert STEP_BY_ID["architecture"].tier == TIER_DUAL_FAST
    assert STEP_BY_ID["architecture"].blocking is True

    # 1. ThinkingConfig passed + 404 model fallback + 400 thinking fallback
    seen_calls: list[tuple[str, Any]] = []

    async def fake_gen(**kwargs: Any) -> Any:
        model = kwargs["model"]
        cfg = kwargs["config"]
        tc = getattr(cfg, "thinking_config", None)
        level = getattr(tc, "thinking_level", None) if tc else None
        seen_calls.append((model, level))
        if model == "missing-pro-preview":
            raise RuntimeError("404 NOT_FOUND")
        if level == "MINIMAL" and len(seen_calls) == 3:
            raise RuntimeError("400 INVALID_ARGUMENT: unsupported thinking")
        return SimpleNamespace(
            text='{"findings": []}',
            usage_metadata=SimpleNamespace(
                prompt_token_count=100,
                cached_content_token_count=0,
                candidates_token_count=10,
            ),
        )

    # The fast default must not be MINIMAL, which `gemini-3.8-flash` rejects.
    assert (
        GeminiVerifier(env={"GEMINI_API_KEY": "fake-key"}).fast_thinking_level
        == "LOW"
    )

    # A level the model rejects must still fall back cleanly.
    gem = GeminiVerifier(
        env={
            "GEMINI_API_KEY": "fake-key",
            "GEMINI_DEEP_MODEL": "missing-pro-preview",
            "GEMINI_FAST_MODEL": "gemini-3.8-flash",
            "GEMINI_FAST_THINKING_LEVEL": "MINIMAL",
        }
    )
    gem._client = SimpleNamespace(  # pylint: disable=protected-access
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake_gen))
    )
    fake_genai = SimpleNamespace(
        types=SimpleNamespace(
            GenerateContentConfig=lambda **kw: SimpleNamespace(**kw),
            ThinkingConfig=lambda **kw: SimpleNamespace(**kw),
        )
    )
    budget = TokenBudgetTracker()
    with patch.dict(
        sys.modules,
        {
            "google": SimpleNamespace(genai=fake_genai),
            "google.genai": fake_genai,
        },
    ):
        # Deep call: hits 404 on missing-pro-preview -> falls back to gemini-3.8-flash with LOW
        asyncio.run(gem.run_step("security", "P", "S", True, budget))
        # Fast call: hits 400 on MINIMAL -> retries without thinking_config
        asyncio.run(gem.run_step("api_docs", "P", "S", False, budget))

    assert seen_calls == [
        ("missing-pro-preview", "LOW"),
        ("gemini-3.8-flash", "LOW"),
        ("gemini-3.8-flash", "MINIMAL"),
        ("gemini-3.8-flash", None),
    ]

    # 2. Verify active steps execute concurrently
    class _SlowVerifier(_FakeVerifier):
        async def run_step(
            self,
            step_id: str,
            shared_prefix: str,
            step_prompt: str,
            deep: bool,
            budget: TokenBudgetTracker,
        ) -> list[Finding]:
            await asyncio.sleep(0.06)
            return await super().run_step(
                step_id, shared_prefix, step_prompt, deep, budget
            )

    pack = ContextPack(
        base_sha="a1",
        head_sha="b2",
        active_steps=["security", "correctness", "architecture", "api_docs"],
        files=[_sample_file_context()],
    )
    t0 = time.monotonic()
    rep = asyncio.run(
        run_verification_pipeline(
            pack,
            _SlowVerifier("gemini", {}),
            None,
            max_parallel_steps=4,
        )
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 0.18
    assert [o.step_id for o in rep.outcomes] == [
        s.step_id for s in VERIFICATION_STEPS
    ]
