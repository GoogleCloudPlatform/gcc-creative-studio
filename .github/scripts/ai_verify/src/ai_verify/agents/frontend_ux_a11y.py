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

"""Frontend Angular Reactivity, Layout Geometry, SSR & Accessibility agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_FAST

AGENT = StepSpec(
    step_id="frontend_ux_a11y",
    title="Frontend Reactivity, Geometry, SSR & A11y",
    tier=TIER_DUAL_FAST,
    blocking=False,
    description=(
        "Angular Signal effect() write loops, OnPush/SSR safety, fixed "
        "header geometry/hover timers, and WCAG AA accessibility."
    ),
    rubric="""Verify **Frontend Angular Reactivity, Layout Geometry, SSR & Accessibility** only:
- Angular 18+ Signal & lifecycle safety: `NG0600` signal writes inside `effect()` without `allowSignalWrites` or `untracked()`, `OnPush` stale views, uncleaned RxJS subscriptions, standalone vs `AppModule` mismatches, and unguarded browser globals (`window`/`localStorage`) breaking SSR (`app.module.server.ts`).
- Layout geometry & DOM events: fixed `HeaderComponent` pill/flyout collision zones (`72px` geometry, `mouseleave` timer cleanup, `<1400px` top-left occlusion) and nested action buttons missing `$event.stopPropagation()`.
- Accessibility (WCAG AA) & UX states: icon-only buttons missing `aria-label`/`matTooltip`, non-interactive `(click)` elements lacking keyboard `role`/`tabindex`, and missing loading/error states.""",
)
