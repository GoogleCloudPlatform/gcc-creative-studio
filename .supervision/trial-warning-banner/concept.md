# Concept: Trial Warning Banner

## Intent

Warn Creative Studio trial users not to enter, upload, or generate sensitive, confidential, or personal information.

## Constraints

- Implement on branch `KN-DATAX-15227-Put-a-warning-banner-onto-Creative-Studio-Frontend-for-trial`.
- Show the warning across authenticated Creative Studio and admin routes.
- Exclude login, password-reset, and support-ticket routes, which do not render the standard application shell.
- Keep navigation and primary content usable on desktop and mobile viewports.
- Use the existing Angular and Tailwind styling conventions; do not add dependencies.
- Do not modify existing untracked deployment handoff, log, or reference files.

## Design

- Add a persistent red warning banner in the root Angular application shell, above `app-header`.
- Use the copy: `Trial environment: Do not enter, upload, or generate sensitive, confidential, or personal information.`
- Reuse `AppComponent` route state so the banner renders only when the authenticated application shell is shown.
- Add focused styles in `AppComponent` and a focused test asserting the banner and warning copy render.

## Trade-offs

- A root-shell banner gives all authenticated routes one consistent warning with minimal maintenance, but it remains visible while users work and consumes a small amount of vertical space.
- Excluding authentication and support flows limits warning coverage before sign-in, but preserves the existing simplified layouts and focuses the notice where users provide application content.