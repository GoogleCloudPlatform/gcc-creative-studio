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

"""Comprehensive tests for all 15 specialist verification agents and confirmed checks."""

# pylint: disable=wrong-import-position,line-too-long

import asyncio
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import pytest

from ai_verify.agents import ALL_AGENTS  # noqa: E402
from ai_verify.consensus import (  # noqa: E402
    build_inline_comments,
    incomplete_outcomes,
    render_agent_check_summary,
    render_markdown_report,
    run_verification_pipeline,
)
from ai_verify.context_pack import (  # noqa: E402
    build_context_pack,
    select_active_steps,
)
from ai_verify.github_publisher import GitHubPublisher  # noqa: E402
from ai_verify.harvesters import (  # noqa: E402
    build_call_graph_slices,
    build_overflow_summaries,
    extract_ts_enclosing_context,
    parse_ci_telemetry,
    parse_lockfile_deltas,
    scan_domain_specialist_signals,
)
from ai_verify.models import (  # noqa: E402
    AGREEMENT_CONSENSUS,
    CITelemetry,
    CallGraphSlice,
    ContextPack,
    FileContext,
    Finding,
    LockfileDelta,
    SEVERITY_HIGH,
    StepOutcome,
    TokenUsage,
    VERIFICATION_STEPS,
)
from ai_verify.prompts import (  # noqa: E402
    STEP_RUBRICS,
    render_shared_context_prefix,
)
from ai_verify.providers import (  # noqa: E402
    TokenBudgetTracker,
    extract_confirmed_checks,
)


def _fc(
    path: str,
    area: str = "backend",
    diff: str = "@@ -1,1 +1,2 @@\n+x = 1\n",
    is_test: bool = False,
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
        enclosing_context="",
        valid_right_lines=valid_lines or [1, 2],
    )


def test_all_fifteen_rubrics_and_selective_domain_routing():
    step_ids = [s.step_id for s in VERIFICATION_STEPS]
    assert len(step_ids) == 15
    assert set(step_ids) == set(STEP_RUBRICS.keys())

    # Infra / bootstrap PR
    infra_steps = select_active_steps(
        [_fc("bootstrap.sh", area="infrastructure")]
    )
    assert "infra_migration" in infra_steps
    assert "agent_media_pipeline" not in infra_steps
    assert "workflow_dag_executor" not in infra_steps

    # Alembic / DB PR
    db_steps = select_active_steps(
        [_fc("backend/alembic/versions/010_add_idx.py", area="backend")]
    )
    assert "db_schema_migrations" in db_steps
    assert "infra_migration" not in db_steps

    # Izumi / Workbench PR
    wb_steps = select_active_steps(
        [
            _fc(
                "frontend/src/app/workbench/workbench.component.ts",
                area="frontend",
            )
        ]
    )
    assert "agent_media_pipeline" in wb_steps
    assert "frontend_ux_a11y" in wb_steps

    # Workflow DAG PR
    wf_steps = select_active_steps(
        [_fc("backend/src/workflows_executor/runner.py", area="backend")]
    )
    assert "workflow_dag_executor" in wf_steps

    # Lockfile-only PR activates supply_chain_ci + pr_intent_synthesizer
    lock_steps = select_active_steps(
        [],
        lockfile_deltas=[
            LockfileDelta(
                path="backend/uv.lock",
                ecosystem="python",
                added=["httpx==0.28.1"],
            )
        ],
    )
    assert lock_steps == ["supply_chain_ci", "pr_intent_synthesizer"]


def test_specialist_static_scanners_across_all_new_domains():
    tf_fc = _fc(
        "infrastructure/modules/compute/main.tf",
        area="infrastructure",
        diff="@@ -10,3 +10,1 @@\n-    ignore_changes = [template[0].containers[0].image]\n+    # removed\n",
    )
    sh_fc = _fc(
        "bootstrap.sh",
        area="infrastructure",
        diff=(
            "@@ -1,1 +1,3 @@\n"
            '+write_state "TF_BUCKET_NAME" "$X"\n'
            "+OUT=$(gcloud storage ls 2>&1)\n"
        ),
    )
    alembic_fc = _fc(
        "backend/alembic/versions/009_idx.py",
        area="backend",
        diff=(
            "@@ -1,1 +1,4 @@\n"
            "+def upgrade():\n"
            "+    op.create_index('ix_media_ws', 'media_items', ['workspace_id'])\n"
            "+    op.execute('ALTER TYPE role_enum ADD VALUE \"GUEST\"')\n"
        ),
    )
    alembic_src = (
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.create_index('ix_media_ws', 'media_items', ['workspace_id'])\n"
        "def downgrade():\n"
        "    pass\n"
    )
    orm_fc = _fc(
        "backend/src/folders/folder_schema.py",
        area="backend",
        diff="@@ -1,1 +1,2 @@\n+    archived: Mapped[bool] = mapped_column(default=False)\n",
    )
    adk_fc = _fc(
        "backend/src/agents/agent_service.py",
        area="backend",
        diff="@@ -1,1 +1,2 @@\n+    await self._append_state_delta(sid, delta)\n",
    )
    aud_fc = _fc(
        "backend/src/audios/audio_service.py",
        area="backend",
        diff="@@ -1,1 +1,2 @@\n+    fallback_model = 'lyria-002'\n",
    )
    wf_py = _fc(
        "backend/src/workflows_executor/step.py",
        area="backend",
        diff="@@ -1,1 +1,2 @@\n+    logger.info('Executing with user_token=%s', token)\n",
    )
    wb_ts = _fc(
        "frontend/src/app/workbench/workbench.component.ts",
        area="frontend",
        diff=(
            "@@ -1,1 +1,4 @@\n"
            "+    this.router.navigate([], {queryParams: {sessionId: '1'}});\n"
            "+    aud.volume = clip.volume;\n"
            "+    effect(() => { this.count.set(1); });\n"
            "+    const x = localStorage.getItem('k');\n"
        ),
    )
    wf_store = _fc(
        "frontend/src/app/workflows/workflow-editor/workflow-folder-tree.store.ts",
        area="frontend",
        diff="@@ -1,1 +1,2 @@\n+@Injectable({providedIn: 'root'})\n",
    )
    fe_html = _fc(
        "frontend/src/app/workbench/panel.component.html",
        area="frontend",
        diff=(
            "@@ -1,1 +1,3 @@\n"
            "+<button mat-icon-button><mat-icon>close</mat-icon></button>\n"
            '+<div (click)="open()">Click tile</div>\n'
        ),
    )
    gha_yml = _fc(
        ".github/workflows/custom.yml",
        area="ci",
        diff=(
            "@@ -1,1 +1,4 @@\n"
            "+      - uses: actions/checkout@v4\n"
            "+      - run: |\n"
            '+          echo "${{ github.event.pull_request.title }}"\n'
        ),
    )
    docker_fc = _fc(
        "backend/Dockerfile",
        area="infrastructure",
        diff="@@ -1,1 +1,2 @@\n+FROM python:3.12-slim\n+CMD ['uvicorn']\n",
    )
    manifest_fc = _fc(
        "backend/pyproject.toml",
        area="backend",
        diff="@@ -1,1 +1,2 @@\n+dependencies = ['httpx']\n",
    )
    legacy_sdk = _fc(
        "backend/src/images/gen.py",
        area="backend",
        diff="@@ -1,1 +1,2 @@\n+from vertexai.generative_models import GenerativeModel\n",
    )

    sources = {
        alembic_fc.path: alembic_src,
        adk_fc.path: "async def mutate(self, sid, delta):\n    await self._append_state_delta(sid, delta)\n",
        docker_fc.path: "FROM python:3.12-slim\nCMD ['uvicorn']\n",
        wb_ts.path: "export class WorkbenchComponent {}\n",
    }

    # Check ORM_WITHOUT_MIGRATION separately when no alembic file is in PR
    orm_signals = scan_domain_specialist_signals([orm_fc], sources.get)
    assert any(s.code == "ORM_WITHOUT_MIGRATION" for s in orm_signals)

    all_files = [
        tf_fc,
        sh_fc,
        alembic_fc,
        adk_fc,
        aud_fc,
        wf_py,
        wb_ts,
        wf_store,
        fe_html,
        gha_yml,
        docker_fc,
        manifest_fc,
        legacy_sdk,
    ]
    signals = scan_domain_specialist_signals(
        all_files,
        sources.get,
        all_repo_paths={"backend/uv.lock"},
        all_changed_paths={f.path for f in all_files},
    )
    codes = {s.code for s in signals}
    expected = {
        "TF_IGNORE_CHANGES_REMOVED",
        "SH_WRITE_STATE_UNSET",
        "SH_GCLOUD_STDERR_CAPTURE",
        "ALEMBIC_CONCURRENT_INDEX",
        "ALEMBIC_ENUM_TX",
        "ALEMBIC_EMPTY_DOWNGRADE",
        "ADK_STATE_NO_IDLE_GUARD",
        "MEDIA_LYRIA2_FALLBACK",
        "WF_TOKEN_LOG_LEAK",
        "WB_URL_SINGLE_WRITER",
        "WB_RAW_HTML_VOLUME",
        "WF_STORE_ROOT_PROVIDED",
        "FE_EFFECT_SIGNAL_WRITE",
        "FE_SSR_BROWSER_GLOBAL",
        "FE_A11Y_ICON_BUTTON",
        "FE_A11Y_STATIC_CLICK",
        "GHA_UNPINNED_ACTION",
        "GHA_SCRIPT_INJECTION",
        "DOCKER_MISSING_USER",
        "DEP_MANIFEST_LOCK_DRIFT",
        "DEP_LEGACY_VERTEX_SDK",
    }
    assert expected.issubset(codes)


def test_lockfile_deltas_call_graph_ts_context_and_telemetry(tmp_path: Path):
    uv_diff = (
        '-[[package]]\n-name = "httpx"\n-version = "0.27.0"\n'
        '+[[package]]\n+name = "httpx"\n+version = "0.28.1"\n'
        '+[[package]]\n+name = "zstandard"\n+version = "0.23.0"\n'
    )
    npm_diff = (
        '-    "rxjs": "7.8.0",\n'
        '+    "rxjs": "7.8.1",\n'
        '+    "marked": "14.0.0",\n'
    )
    deltas = parse_lockfile_deltas(
        [("backend/uv.lock", uv_diff), ("frontend/package-lock.json", npm_diff)]
    )
    assert len(deltas) == 2
    assert "httpx: 0.27.0 -> 0.28.1" in deltas[0].updated
    assert "zstandard==0.23.0" in deltas[0].added
    assert "marked==14.0.0" in deltas[1].added

    # Call-graph slice harvesting across untouched Python & TypeScript callers
    changed_py = _fc(
        "backend/src/folders/folder_service.py",
        area="backend",
        diff="@@ -1,3 +1,4 @@\n async def ensure_can_manage_folder(folder, user, workspace):\n+    pass\n",
        valid_lines=[1, 2],
    )
    changed_ts = _fc(
        "frontend/src/app/folders/folder.service.ts",
        area="frontend",
        diff="@@ -1,2 +1,3 @@\n+  getBreadcrumbs(folderId: number) {\n",
        valid_lines=[1],
    )
    repo_files = {
        changed_py.path: "async def ensure_can_manage_folder(folder, user, workspace):\n    return True\n",
        "backend/src/galleries/gallery_controller.py": (
            "async def move(svc):\n    await svc.ensure_can_manage_folder(f, u, w)\n"
        ),
        changed_ts.path: "export class FolderService {\n  getBreadcrumbs(folderId: number) {}\n}\n",
        "frontend/src/app/gallery/media-detail.component.ts": (
            "export class MediaDetailComponent {\n  load() { this.folderSvc.getBreadcrumbs(1); }\n}\n"
        ),
    }
    slices = build_call_graph_slices(
        [changed_py, changed_ts], set(repo_files.keys()), repo_files.get
    )
    assert len(slices) == 2
    assert {s.symbol for s in slices} == {
        "ensure_can_manage_folder",
        "getBreadcrumbs",
    }

    ts_ctx = extract_ts_enclosing_context(repo_files[changed_ts.path], [2])
    assert "FolderService" in ts_ctx

    overflow = build_overflow_summaries(
        [
            _fc(
                "backend/src/huge.py",
                diff="@@ -1,1 +1,2 @@\n+class BigWorker:\n+    pass\n",
            )
        ]
    )
    assert "BigWorker" in overflow[0]

    # Cobertura XML + JUnit XML + build.log telemetry
    cov_xml = tmp_path / "coverage.xml"
    cov_xml.write_text(
        "<coverage><packages><package><classes>"
        '<class filename="backend/src/folders/folder_service.py">'
        '<lines><line number="1" hits="1"/><line number="2" hits="0"/></lines>'
        "</class></classes></package></packages></coverage>",
        encoding="utf-8",
    )
    junit_xml = tmp_path / "junit.xml"
    junit_xml.write_text(
        '<testsuite><testcase classname="tests.test_f" name="test_ok"/>'
        '<testcase classname="tests.test_f" name="test_fail">'
        '<failure message="AssertionError: expected 403"/></testcase></testsuite>',
        encoding="utf-8",
    )
    build_log = tmp_path / "build.log"
    build_log.write_text(
        "ERROR TS2339: Property 'foo' does not exist\n", encoding="utf-8"
    )

    tel = parse_ci_telemetry(
        [changed_py],
        coverage_xml_path=str(cov_xml),
        junit_xml_path=str(junit_xml),
        build_log_path=str(build_log),
    )
    assert tel is not None
    assert tel.diff_coverage_pct == 50.0
    assert tel.passed_tests_count == 1
    assert len(tel.failed_tests) == 1
    assert "TS2339" in tel.build_errors[0]

    # Reject XML with DOCTYPE/ENTITY safely
    bad_xml = tmp_path / "xxe.xml"
    bad_xml.write_text(
        "<!DOCTYPE foo [<!ENTITY xxe 'bad'>]><testsuite/>", encoding="utf-8"
    )
    safe_tel = parse_ci_telemetry([changed_py], junit_xml_path=str(bad_xml))
    assert safe_tel is not None and safe_tel.passed_tests_count == 0


def test_confirmed_checks_on_passing_agents_and_synthesis_dedup():
    raw = {
        "findings": [],
        "confirmed_checks": [
            "- `FolderService.update_folder` enforces `workspace_id` + `ensure_can_manage_folder`",
            "No raw SQL or shell execution in `folder_controller.py`",
            "No raw SQL or shell execution in `folder_controller.py`",
            "x" * 160,
        ],
    }
    extracted = extract_confirmed_checks(raw)
    assert len(extracted) == 3
    assert extracted[0].startswith("`FolderService.update_folder`")
    assert extracted[2].endswith("...")

    class _ConfirmingVerifier:
        """In-memory ModelVerifier stub returning configured confirmed_checks."""

        def __init__(
            self,
            provider_name: str,
            findings_by_step: dict[str, list[Finding]],
            confirmed_by_step: dict[str, list[str]],
        ) -> None:
            self.provider_name = provider_name
            self._findings = findings_by_step
            self._confirmed = confirmed_by_step
            self.seen_prompts: dict[str, str] = {}

        def is_available(self) -> bool:
            return True

        def model_for_tier(self, deep: bool) -> str:
            return "pro" if deep else "flash"

        def get_confirmed_checks(self, step_id: str) -> list[str]:
            return list(self._confirmed.get(step_id, []))

        async def run_step(
            self,
            step_id: str,
            shared_prefix: str,
            step_prompt: str,
            deep: bool,
            budget: TokenBudgetTracker,
        ) -> list[Finding]:
            del shared_prefix, deep
            self.seen_prompts[step_id] = step_prompt
            budget.record(
                TokenUsage(self.provider_name, "m", step_id, 100, 80, 20)
            )
            return list(self._findings.get(step_id, []))

        async def adjudicate(
            self, step_id: str, prompt: str, budget: TokenBudgetTracker
        ) -> dict[str, Any]:
            del step_id, prompt, budget
            return {
                "verdict": "CONFIRMED",
                "adjusted_severity": SEVERITY_HIGH,
                "reason": "Confirmed",
            }

    fctx = _fc(
        "backend/src/agents/agent_service.py",
        area="backend",
        valid_lines=[10, 11, 12],
    )
    pack = ContextPack(
        base_sha="aaaa0000",
        head_sha="bbbb1111",
        pr_title="feat(agents): sync session character state",
        pr_body="Updates character profile state delta",
        areas_touched=["backend"],
        active_steps=[
            "security",
            "agent_media_pipeline",
            "pr_intent_synthesizer",
        ],
        files=[fctx],
        call_graph_slices=[
            CallGraphSlice(
                "update_session_character",
                fctx.path,
                "backend/src/agents/agent_controller.py",
                22,
                "22: await svc.update_session_character(sid)",
            )
        ],
        lockfile_deltas=[
            LockfileDelta(
                "backend/uv.lock", "python", added=["pydantic==2.11.0"]
            )
        ],
        overflow_summaries=["`backend/src/extra.py` [area=backend, +10/-2]"],
        ci_telemetry=CITelemetry(
            diff_coverage_pct=92.5,
            passed_tests_count=48,
        ),
    )

    prefix = render_shared_context_prefix(pack)
    assert "<LOCKFILE_DELTAS>" in prefix
    assert "<CROSS_FILE_CALLERS>" in prefix
    assert "<OVERFLOW_FILE_SUMMARIES>" in prefix
    assert "<CI_RUNTIME_TELEMETRY>" in prefix

    # Overlapping finding raised by TWO different specialist steps on lines 10 & 11
    sec_finding = Finding(
        step_id="security",
        file=fctx.path,
        line_start=10,
        line_end=10,
        severity=SEVERITY_HIGH,
        category="concurrency",
        title="Session state mutation missing active run guard",
        evidence="Mutates ADK session without checking active run.",
        confidence=0.92,
        models=["gemini:pro", "claude:pro"],
        agreement=AGREEMENT_CONSENSUS,
    )
    media_dup_finding = Finding(
        step_id="agent_media_pipeline",
        file=fctx.path,
        line_start=11,
        line_end=11,
        severity=SEVERITY_HIGH,
        category="adk",
        title="Active run guard missing on session state mutation",
        evidence="Needs _ensure_session_idle -> HTTP 409.",
        confidence=0.91,
        models=["gemini:pro", "claude:pro"],
        agreement=AGREEMENT_CONSENSUS,
    )

    gem = _ConfirmingVerifier(
        "gemini",
        {
            "security": [],
            "agent_media_pipeline": [media_dup_finding],
            "pr_intent_synthesizer": [],
        },
        {
            "security": [
                "`workspace_auth.authorize` and user ownership verified on `/character` route"
            ],
            "agent_media_pipeline": [
                "`asset_ref.id` and `workspace_id` serialized strictly as `str`"
            ],
            "pr_intent_synthesizer": [
                "Diff matches stated character sync scope with zero unrelated edits"
            ],
        },
    )
    cld = _ConfirmingVerifier(
        "claude",
        {
            "security": [sec_finding],
            "agent_media_pipeline": [media_dup_finding],
        },
        {
            "security": [
                "No token leakage in `AgentService` state delta payload"
            ],
        },
    )

    report = asyncio.run(
        run_verification_pipeline(pack, gem, cld, gate_mode="advisory")
    )

    # pr_intent_synthesizer ran AFTER specialist steps and received their findings digest
    synth_prompt = gem.seen_prompts["pr_intent_synthesizer"]
    assert "Specialist Findings Already Raised" in synth_prompt
    assert "agent_media_pipeline" in synth_prompt

    md = render_markdown_report(report, pack)
    assert "#### 🟠 Security & AuthZ · `security`" in md
    assert (
        "#### ✅ PR Intent Alignment & Scope Guard · `pr_intent_synthesizer`"
        in md
    )
    assert "- **Confirmed:**" in md
    assert "`workspace_auth.authorize` and user ownership verified" in md
    assert "No token leakage in `AgentService` state delta payload" in md
    assert "Diff matches stated character sync scope" in md
    assert "Skipped Non-Applicable Agents (12)" in md

    # Cross-step duplicate finding within 2 lines with overlapping words is deduplicated to 1 inline comment
    inline = build_inline_comments(report, pack)
    assert len(inline) == 1


def test_live_per_agent_check_runs_and_ssrf_host_guard():
    assert VERIFICATION_STEPS == ALL_AGENTS
    assert all(bool(a.rubric.strip()) for a in ALL_AGENTS)

    # Strict URL/host/repo SSRF guard in GitHubPublisher
    with pytest.raises(ValueError):
        GitHubPublisher("org/repo", "tok", api_base="http://api.github.com")
    with pytest.raises(ValueError):
        GitHubPublisher("org/repo", "tok", api_base="https://evil.example.com")
    with pytest.raises(ValueError):
        GitHubPublisher("org/../evil", "tok")

    pub = GitHubPublisher("org/repo", "tok")
    with pytest.raises(ValueError):
        pub._request(
            "GET", "evil.com/steal"
        )  # pylint: disable=protected-access
    with pytest.raises(ValueError):
        pub._request(
            "GET", "//evil.com/steal"
        )  # pylint: disable=protected-access
    with pytest.raises(ValueError):
        pub._request(
            "GET", "/repos/org/repo/../../steal"
        )  # pylint: disable=protected-access

    # Live per-agent Check Run POST (in_progress) -> PATCH (completed) + POST (skipped)
    calls: list[tuple[str, str, dict[str, Any]]] = []
    next_id = 100

    def fake_req(
        method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        nonlocal next_id
        calls.append((method, path, payload or {}))
        next_id += 1
        return {"id": next_id}

    pub._request = fake_req  # type: ignore[method-assign]  # pylint: disable=protected-access

    class _SimpleStub:
        """Minimal verifier stub for Check Run lifecycle testing."""

        provider_name = "gemini"

        def is_available(self) -> bool:
            return True

        def model_for_tier(self, deep: bool) -> str:
            return "pro" if deep else "flash"

        def get_confirmed_checks(self, step_id: str) -> list[str]:
            return [f"{step_id} verified clean"]

        async def run_step(
            self,
            step_id: str,
            shared_prefix: str,
            step_prompt: str,
            deep: bool,
            budget: TokenBudgetTracker,
        ) -> list[Finding]:
            del shared_prefix, step_prompt, deep
            budget.record(TokenUsage("gemini", "flash", step_id, 50, 0, 10))
            return []

        async def adjudicate(
            self, step_id: str, prompt: str, budget: TokenBudgetTracker
        ) -> dict[str, Any]:
            del step_id, prompt, budget
            return {
                "verdict": "CONFIRMED",
                "adjusted_severity": SEVERITY_HIGH,
                "reason": "ok",
            }

    pack = ContextPack(
        base_sha="111",
        head_sha="abc99999",
        active_steps=["api_docs", "pr_intent_synthesizer"],
        files=[_fc("DEPLOYMENT.md", area="other")],
    )
    asyncio.run(
        run_verification_pipeline(
            pack,
            _SimpleStub(),
            None,
            gate_mode="advisory",
            on_step_start=lambda spec: pub.start_agent_check_run(
                pack.head_sha, spec
            ),
            on_step_complete=lambda out: pub.complete_agent_check_run(
                pack.head_sha, out, "advisory"
            ),
        )
    )

    posts = [c for c in calls if c[0] == "POST"]
    patches = [c for c in calls if c[0] == "PATCH"]
    # 13 skipped agents (1 POST each) + 2 active agents (1 POST in_progress + 1 PATCH completed each)
    assert len(posts) == 15
    assert len(patches) == 2
    assert all(p[2]["status"] == "completed" for p in patches)
    assert all(p[2]["conclusion"] == "success" for p in patches)
    skipped_conclusions = [
        p[2].get("conclusion")
        for p in posts
        if p[2].get("status") == "completed"
    ]
    assert len(skipped_conclusions) == 13
    assert all(c == "skipped" for c in skipped_conclusions)


def test_risk_and_size_first_packing_prevents_alphabetical_starvation():
    """Ensures large early-alphabet files never starve workflows or small edits."""
    huge_a = "@@ -0,0 +1,200 @@\n" + "".join(
        f"+line_{i} = 'x' * 50\n" for i in range(200)
    )
    small_wf = "@@ -1,2 +1,3 @@\n name: CI\n+permissions: {}\n"
    small_z = "@@ -1,2 +1,3 @@\n def z_helper():\n+    return 42\n"
    doc_md = "@@ -1,1 +1,2 @@\n # Docs\n+Updated.\n"

    diffs_by_path = {
        "backend/src/aaa_huge_module.py": huge_a,
        ".github/workflows/z-deploy.yml": small_wf,
        "backend/src/zzz_small_service.py": small_z,
        "DEPLOYMENT.md": doc_md,
    }

    def fake_git(*args: str, check: bool = True) -> str:
        del check
        if args[0] == "diff" and "--numstat" in args:
            return (
                "200\t0\tbackend/src/aaa_huge_module.py\0"
                "1\t0\t.github/workflows/z-deploy.yml\0"
                "1\t0\tbackend/src/zzz_small_service.py\0"
                "1\t0\tDEPLOYMENT.md\0"
            )
        if args[0] == "diff" and "--" in args:
            target = args[args.index("--") + 1]
            return diffs_by_path.get(target, "")
        if args[0] == "ls-tree":
            return "\n".join(diffs_by_path)
        return ""

    with patch("ai_verify.context_pack._git", side_effect=fake_git):
        pack = build_context_pack("base0", "head1", max_pack_chars=1_500)

    selected_paths = [fc.path for fc in pack.files]
    assert ".github/workflows/z-deploy.yml" in selected_paths
    assert "backend/src/zzz_small_service.py" in selected_paths
    assert "DEPLOYMENT.md" in selected_paths
    assert pack.skipped_files == ["backend/src/aaa_huge_module.py"]
    assert len(pack.overflow_summaries) == 1


def test_missing_model_result_is_never_reported_as_clean():
    """A model call that returns nothing must never surface as a passing check."""

    class _Flaky:
        """Verifier stub that returns no result for selected steps."""

        def __init__(self, name: str, fail_steps: set[str]) -> None:
            self.provider_name = name
            self._fail_steps = fail_steps

        def is_available(self) -> bool:
            return True

        def model_for_tier(self, deep: bool) -> str:
            return "pro" if deep else "flash"

        def get_confirmed_checks(self, step_id: str) -> list[str]:
            if step_id in self._fail_steps:
                return []
            return [f"{step_id} checked by {self.provider_name}"]

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
            if step_id in self._fail_steps:
                raise RuntimeError("404 NOT_FOUND model unavailable")
            budget.record(
                TokenUsage(self.provider_name, "flash", step_id, 50, 0, 10)
            )
            return []

        async def adjudicate(
            self, step_id: str, prompt: str, budget: TokenBudgetTracker
        ) -> dict[str, Any]:
            del step_id, prompt, budget
            return {
                "verdict": "CONFIRMED",
                "adjusted_severity": SEVERITY_HIGH,
                "reason": "ok",
            }

    pack = ContextPack(
        base_sha="111",
        head_sha="abc99999",
        active_steps=["security", "api_docs"],
        files=[_fc("backend/src/a.py")],
    )

    # 1. The only configured model returns nothing for one agent.
    report = asyncio.run(
        run_verification_pipeline(pack, _Flaky("gemini", {"security"}), None)
    )
    by_step = {out.step_id: out for out in report.outcomes}
    failed_out = by_step["security"]
    conclusion, title, body = render_agent_check_summary(failed_out, "advisory")
    assert conclusion == "neutral"
    assert title == "⚠️ Not verified — no result from gemini"
    assert "**No result from:** `gemini`" in body
    assert (
        render_agent_check_summary(by_step["api_docs"], "advisory")[0]
        == "success"
    )

    md = render_markdown_report(report, pack)
    assert "Verification Incomplete" in md.splitlines()[1]
    assert "All Verification Checks Clean" not in md
    assert "**1 of 2 active agent(s)**" in md
    assert "`security` (gemini)" in md
    assert "Not verified (no model result)" in md
    assert [out.step_id for out in incomplete_outcomes(report)] == ["security"]
    # Advisory mode still exits 0: only what is reported changes.
    assert report.gate_passed

    # 2. One of two models returns nothing: partial, and still not a pass.
    report = asyncio.run(
        run_verification_pipeline(
            pack, _Flaky("gemini", set()), _Flaky("claude", {"security"})
        )
    )
    partial_out = next(o for o in report.outcomes if o.step_id == "security")
    conclusion, title, _ = render_agent_check_summary(partial_out, "advisory")
    assert conclusion == "neutral"
    assert title == (
        "⚠️ Partial — no result from claude; security checked by gemini"
    )

    # 3. An agent cut off by the token ceiling is reported the same way.
    report = asyncio.run(
        run_verification_pipeline(
            pack,
            _Flaky("gemini", set()),
            None,
            max_total_tokens=1,
            max_parallel_steps=1,
        )
    )
    cut_out = next(o for o in report.outcomes if o.step_id == "api_docs")
    assert not cut_out.skipped
    assert "Token budget exceeded" in cut_out.provider_errors[0]
    assert render_agent_check_summary(cut_out, "advisory")[0] == "neutral"

    # 4. Both Check Run publishing paths follow the same rule.
    sent: list[dict[str, Any]] = []

    def fake_req(
        method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        del method, path
        sent.append(payload or {})
        return {"id": len(sent)}

    pub = GitHubPublisher("org/repo", "tok")
    pub._request = fake_req  # type: ignore[method-assign]  # pylint: disable=protected-access
    pub.complete_agent_check_run("abc99999", failed_out, "advisory")
    assert sent[-1]["conclusion"] == "neutral"
    assert sent[-1]["output"]["title"].startswith("⚠️ Not verified")

    pub.publish_check_run("abc99999", True, "md", incomplete=True)
    pub.publish_check_run("abc99999", True, "md")
    pub.publish_check_run("abc99999", False, "md", incomplete=True)
    assert [p["conclusion"] for p in sent[-3:]] == [
        "neutral",
        "success",
        "failure",
    ]
    assert "incomplete" in sent[-3]["output"]["title"]


def test_agent_check_summary_for_findings_and_plain_results():
    """Findings keep their conclusions; a bare result claims nothing extra."""
    flagged = StepOutcome(
        step_id="security",
        title="Security & AuthZ",
        blocking=True,
        models_invoked=["gemini:pro"],
        findings=[
            Finding(
                step_id="security",
                file="backend/src/a.py",
                line_start=1,
                line_end=1,
                severity=SEVERITY_HIGH,
                category="authz",
                title="Missing workspace scope",
                evidence="Query is not filtered by workspace_id.",
                suggestion="Filter by workspace_id.",
                models=["gemini:pro"],
            )
        ],
        passed=False,
    )
    assert render_agent_check_summary(flagged, "blocking")[0] == "failure"
    conclusion, title, body = render_agent_check_summary(flagged, "advisory")
    assert conclusion == "neutral"
    assert title == "🟠 1 finding(s) — Missing workspace scope"
    assert "Filter by workspace_id." in body

    bare = StepOutcome(
        step_id="api_docs",
        title="API Contract & Docs Drift",
        blocking=False,
        models_invoked=["gemini:flash"],
    )
    assert render_agent_check_summary(bare, "advisory")[:2] == (
        "success",
        "✅ No findings reported",
    )
