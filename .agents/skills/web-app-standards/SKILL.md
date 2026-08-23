---
name: web-app-standards
description: Apply standards for the server-rendered Tailwind interface and minimal JavaScript.
---

# Web application standards

Apply these standards to web GUI code under `src/web`.

## Technology constraints

- Use server-rendered HTML and Tailwind CSS.
- Do not introduce a JavaScript framework.
- Add vanilla JavaScript only when HTML and CSS cannot provide the required interaction.
- Prefer browser platform features and progressive enhancement.
- Keep dependencies minimal and justify every new build or runtime dependency.

## HTML and accessibility

- Use semantic elements and native controls before custom widgets.
- Associate every input with a visible label and make validation messages programmatically related.
- Support keyboard operation, visible focus, sensible focus order, and reduced-motion preferences.
- Provide useful page titles, headings, landmarks, alternative text, and status announcements.
- Preserve entered values and explain how to correct validation failures.

## Layout and states

- Build responsive layouts from the smallest supported viewport upward.
- Use a consistent spacing, color, and typography system expressed through Tailwind configuration.
- Provide deliberate loading, empty, error, success, and disabled states.
- Avoid arbitrary utility values when an existing design token communicates the same intent.

## Security and privacy

- Escape untrusted values in rendered HTML.
- Use the backend's CSRF, authentication, and authorization mechanisms at every relevant boundary.
- Do not store sensitive financial data in browser storage, URLs, analytics, or client logs.
- Do not duplicate authoritative backend validation; client-side hints are supplementary.

## Verification

- Test user-observable behavior rather than Tailwind class strings.
- Check important flows using keyboard-only navigation and representative viewport sizes.
- Verify that unavailable JavaScript does not break core tasks unless the approved plan says
  otherwise.
