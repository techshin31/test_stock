# QuantPilot Operations

QuantPilot Operations is a local web product for one trading-system operator to monitor the PAPER account, verify operational health, and read the same official EOD report used by promotion gates.

- Register: product
- Platform: web
- Primary user: the developer/operator responsible for the PAPER trading process
- Primary job: answer “is PAPER operating safely, and is today’s official report current?” without checking several files or terminals
- Positioning: one read-only operational surface over authoritative mode-scoped artifacts; it never starts trading or changes promotion state
- Personality: calm, precise, evidence-led, and operational
- Avoid: decorative finance-terminal density, unexplained status colors, duplicate report definitions, hidden refresh behavior, and any control that could imply REAL execution
- Accessibility: keyboard-visible controls, readable contrast, semantic status text, reduced-motion support, and responsive layouts down to a narrow mobile viewport

The initial product scope is PAPER monitoring. DRY_RUN and REAL may remain available to backend diagnostics, but the shipped web interface is intentionally pinned to PAPER and exposes no order or mode-transition action.
