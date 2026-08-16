---
name: omichub-frontend-design
description: Apply the OmicHub scientific-workbench frontend design system to Vue 3 applications. Use when implementing or reviewing OmicHub pages, layouts, dashboards, forms, data tables, loading/error/empty states, responsive behavior, accessibility, themes, motion, data visualization, or when migrating the system to another Vue platform. OmicHub runs Naive UI and Arco Design Vue in parallel under one token set.
version: 1.0.0
author: OmicHub
icon: 🎨
category: design
---

# OmicHub Frontend Design

Apply a calm, clear, reliable, controllable scientific-workbench design system. OmicHub runs **Naive UI and Arco Design Vue in parallel**; both share one semantic-token set, one theme state, one icon strategy, and one accessibility contract. Never rebuild the same interactive control by stacking both libraries; keep a page internally consistent. A brand-new application picks one library and keeps it.

## Workflow

1. Read `references/frontend-design-system.md` completely before editing UI code.
2. Inspect the target repository's `AGENTS.md`, existing theme setup, global CSS variables (`tokens.css` / `global.css`), page shell, and shared components.
3. Identify the component library in use. In OmicHub, Naive UI and Arco may coexist; on a new platform choose one and register it once at the app entry.
4. Reuse semantic tokens, the shared `PageHeader`, and existing page patterns before adding component-local styles.
5. Implement the full interaction model: default, hover, active, focus-visible, disabled, loading, empty, error, and success as applicable.
6. Keep page refreshes local and state-preserving. Never use route or browser reload as a data-refresh mechanism.
7. Verify light/dark themes, narrow screens, keyboard access, reduced motion, reduced transparency, and high contrast.
8. Run the project's targeted type check, build, and any relevant tests. Update the design-system reference when adding a global token or reusable pattern.

## Decision Rules

- Use CSS semantic variables instead of hard-coded page colors, borders, shadows, or chart rails; new tokens are defined in `tokens.css` / `global.css` with light+dark pairs before consumption.
- Standard workbench pages fill the `.page-container` (page padding only, no max-width). Only admin config centers use `.admin-config-center` / `.admin-config-section--standalone` with `width: min(100%, 1440px)`; never narrow content with an ad-hoc `max-width`.
- Put page-level actions in the shared `PageHeader` `#actions`; keep card actions scoped to the card they affect.
- Present operational status with text plus color and loading/error semantics; decorative status dots must not be the sole signal.
- For selectable cards, use the shared `.omichub-selectable-card` contract with `.is-selected` and the matching ARIA state; preserve both the continuous selected outline and the left status rail.
- For same-level two-way preference toggles use the shared `.omichub-segmented-toggle` (with `role="group"` / `aria-pressed`); never for primary submit or destructive actions.
- Reserve glass materials for structural chrome, auth contexts, and gradient hero/banner surfaces. Buttons on gradient backgrounds use the white-solid or glass-with-highlight-border recipes (default theme buttons lack contrast there). Use solid cards for normal content.
- Use short transitions for ordinary UI state; use interruptible springs only for direct gesture interactions; honor `prefers-reduced-motion` / `prefers-reduced-transparency`.
- Keep the skill reference as the canonical cross-platform specification. Follow repository-local instructions when they conflict.

## Reference

Load `references/frontend-design-system.md` for design goals, the tech-stack and authority map, token definitions, the standard page recipe and admin-config-center layout, component contracts (buttons, cards, forms, tables, status, navigation, gradient-background buttons), dashboard state patterns, data visualization, WebSocket/API/state-management conventions, motion, responsive breakpoints, accessibility requirements, component-library migration guidance, the overlay/positioning contract, the hero background-animation system, the design-quality baseline, and the delivery checklist.
