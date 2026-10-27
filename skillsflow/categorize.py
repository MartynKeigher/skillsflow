"""Assign each skill and plugin one category for browsing.

A marketplace's own `category` wins when present; otherwise keywords in the name
and description decide.
"""

from __future__ import annotations

import re

CATEGORIES: list[tuple[str, list[str]]] = [
    ("Documents", ["pdf", "docx", "xlsx", "pptx", "word document", "spreadsheet", "excel", "powerpoint", "slides", "presentation"]),
    ("Security", ["security", "vulnerab", "owasp", "pentest", "secret", "audit", "threat", "cve"]),
    ("DevOps & Cloud", ["deploy", "docker", "kubernetes", "k8s", "terraform", "aws", "azure", "gcp", "cloud", "ci/cd", "infrastructure", "monitoring", "observability", "sentry", "vercel"]),
    ("Data & Analytics", ["data", "sql", "database", "analytics", "csv", "chart", "dashboard", "bigquery", "postgres", "metrics"]),
    ("Design", ["design", "figma", "ui ", "ux", "css", "brand", "theme", "visual", "art", "image", "canvas", "gif", "icon"]),
    ("Writing & Content", ["write", "writing", "blog", "copy", "content", "edit", "prose", "documentation", "docs", "communication", "newsletter"]),
    ("Marketing & Sales", ["marketing", "seo", "campaign", "sales", "crm", "hubspot", "social media", "email sequence"]),
    ("AI & Agents", ["agent", "mcp", "prompt", "llm", "claude", "subagent", "model context protocol", "skill-creator", "skill creator"]),
    ("Testing", ["test", "tdd", "playwright", "qa", "coverage"]),
    ("Development", ["code", "git", "debug", "refactor", "review", "api", "sdk", "typescript", "python", "rust", "swift", "lsp", "frontend", "backend", "commit", "pull request"]),
    ("Productivity", ["productivity", "workflow", "task", "notes", "calendar", "meeting", "slack", "notion", "plan", "brainstorm", "todo"]),
    ("Research & Learning", ["research", "learn", "tutorial", "study", "paper", "science", "math"]),
]

MARKETPLACE_CATEGORY_MAP = {
    "development": "Development", "productivity": "Productivity", "database": "Data & Analytics",
    "monitoring": "DevOps & Cloud", "security": "Security", "deployment": "DevOps & Cloud",
    "design": "Design", "automation": "Productivity", "learning": "Research & Learning",
    "testing": "Testing", "math": "Research & Learning", "migration": "Development",
    "documents": "Documents", "writing": "Writing & Content", "marketing": "Marketing & Sales",
    "data": "Data & Analytics", "ai": "AI & Agents",
}

OTHER = "Other"


def from_marketplace(category: str | None) -> str | None:
    if not category:
        return None
    key = category.strip().lower()
    return MARKETPLACE_CATEGORY_MAP.get(key) or next((c for c, _ in CATEGORIES if c.lower() == key), None)


def categorize(name: str, description: str, marketplace_category: str | None = None) -> str:
    mapped = from_marketplace(marketplace_category)
    if mapped:
        return mapped
    text = " " + re.sub(r"[-_]", " ", f"{name} {description}".lower()) + " "
    best, best_score = OTHER, 0
    for category, words in CATEGORIES:
        # The name counts double: "pdf" in a skill's name says more than in its description.
        score = sum(text.count(w) + (2 if w in name.lower() else 0) for w in words)
        if score > best_score:
            best, best_score = category, score
    return best


def all_categories() -> list[str]:
    return [c for c, _ in CATEGORIES] + [OTHER]
