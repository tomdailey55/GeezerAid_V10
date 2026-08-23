#!/usr/bin/env python3
"""
Recipe Index Builder — fast inverted index for elder-brain recipes.

Builds:
  word → [recipe_paths]  (JSON)
  recipe_path → {title, summary, ingredients, created}

Usage:
  python recipe_indexer.py          # build index
  python recipe_indexer.py --watch  # rebuild on changes (future)
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

VAULT = Path.home() / "elder-brain"
RECIPES_DIR = VAULT / "recipes"
INDEX_PATH = VAULT / "recipe_index.json"
META_PATH = VAULT / "recipe_meta.json"


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from markdown."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).strip().split('\n'):
        if ':' in line:
            k, v = line.split(':', 1)
            fm[k.strip()] = v.strip().strip("'\"")
    return fm


def _extract_ingredients(text: str) -> list:
    """Heuristic: pull ingredient-like words from recipe body."""
    ingredients = set()
    # Look for bullet lists that look like ingredients
    for line in text.split('\n'):
        line = line.strip().lower()
        if line.startswith(('- ', '* ', '• ')):
            # Take first few words as ingredient
            words = re.sub(r'[^\w\s]', ' ', line[2:]).split()
            if len(words) >= 1:
                ingredients.add(words[0])
            if len(words) >= 2:
                ingredients.add(f"{words[0]} {words[1]}")
    return list(ingredients)


def _tokenize(text: str) -> list:
    """Split text into searchable tokens."""
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    return [w for w in text.split() if len(w) > 2]


def build_index():
    if not RECIPES_DIR.exists():
        print(f"[recipe_index] Recipes dir not found: {RECIPES_DIR}")
        sys.exit(1)

    recipes = list(RECIPES_DIR.rglob("*.md"))
    print(f"[recipe_index] Found {len(recipes)} recipe files")

    inverted: dict = {}   # word -> [paths]
    meta: dict = {}       # path -> {title, summary, ingredients, created}

    for path in recipes:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            fm = _parse_frontmatter(text)
            title = fm.get("title", path.stem.replace('-', ' ').title())
            summary = fm.get("summary", "")
            created = fm.get("created", "")

            # Extract ingredients from body
            ingredients = _extract_ingredients(text)

            # Tokenize all searchable text
            searchable = f"{title} {summary} {' '.join(ingredients)}"
            tokens = _tokenize(searchable)

            rel_path = str(path.relative_to(VAULT))
            meta[rel_path] = {
                "title": title,
                "summary": summary,
                "ingredients": ingredients,
                "created": created,
                "word_count": len(tokens),
            }

            for tok in set(tokens):
                inverted.setdefault(tok, []).append(rel_path)

        except Exception as e:
            print(f"[recipe_index] Error parsing {path}: {e}")

    # Sort paths in each inverted list for determinism
    for word in inverted:
        inverted[word] = sorted(set(inverted[word]))

    # Write indices
    index_payload = {
        "built_at": datetime.now().isoformat(),
        "recipe_count": len(recipes),
        "unique_words": len(inverted),
    }

    VAULT.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w") as fh:
        json.dump(inverted, fh, indent=2)
    with open(META_PATH, "w") as fh:
        json.dump(meta, fh, indent=2)
    with open(VAULT / "recipe_index_info.json", "w") as fh:
        json.dump(index_payload, fh, indent=2)

    print(f"[recipe_index] Wrote {len(inverted)} unique words, {len(recipes)} recipes")
    print(f"[recipe_index] Index: {INDEX_PATH}")
    print(f"[recipe_index] Meta: {META_PATH}")

    # Show sample
    if "beef" in inverted:
        print(f"[recipe_index] 'beef' → {len(inverted['beef'])} recipes")
    if "ribs" in inverted:
        print(f"[recipe_index] 'ribs' → {len(inverted['ribs'])} recipes")


if __name__ == "__main__":
    build_index()
