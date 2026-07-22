---
name: QuantPilot Operations
description: Calm, high-contrast operations console for PAPER trading health and official reports
colors:
  canvas: "#0b0f14"
  surface: "#111821"
  surface-raised: "#17212d"
  border: "#263343"
  text: "#f3f6f9"
  text-muted: "#9aa8b7"
  accent: "#52a8ff"
  positive: "#45c486"
  warning: "#f2b84b"
  negative: "#f26d6d"
typography:
  headline:
    fontFamily: "Inter, Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "clamp(1.75rem, 4vw, 2.5rem)"
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: "-0.035em"
  body:
    fontFamily: "Inter, Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.02em"
rounded:
  sm: "6px"
  md: "10px"
  lg: "14px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "20px"
  status-chip:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "5px 8px"
---

## Overview

The interface is an operations console, not a consumer trading app. Use a stable dark canvas, restrained density, clear reading order, and mode-scoped evidence. The page must always make PAPER mode, data recency, and report freshness visible. Layouts use a 12-column desktop grid and collapse into a single reading column on small screens.

## Colors

Blue is reserved for navigation and primary actions. Green, amber, and red always pair with text labels and mean healthy, attention, and blocked/error respectively. Surfaces are opaque tonal layers; avoid heavy glass blur, neon gradients, and color-only meaning.

## Typography

Use the committed system stack so the dashboard starts without a font network request. Numeric values use tabular figures. Headings are compact and sentence case; labels are short, concrete, and never decorative all-caps paragraphs.

## Elevation

Depth comes primarily from surface tone and a one-pixel border. Use at most a subtle shadow for floating mobile navigation or dialogs. Dense operational cards should feel anchored rather than glossy.

## Components

Cards have 14px corners and 20px padding. Status chips are compact rectangles with an icon or dot plus explicit text. Tables keep identifiers left aligned and numbers right aligned. Empty, loading, stale, and failed states occupy the same component footprint to avoid layout jumps. All buttons retain a visible focus ring.

## Do's and Don'ts

Do show the last successful update, the expected official report date, and a plain-language next action. Do keep report JSON metadata and Markdown content connected. Do not expose order placement, REAL activation, or promotion controls. Do not invent a second EOD calculation in the frontend. Do not animate continuously or hide important evidence behind hover-only interactions.
