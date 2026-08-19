"""
GeezerAid — Knowledge Module

Search elder-brain vault for recipes, notes, and facts.
Wraps the recipe search from gtv_dashboard_server.py with a clean interface.

Real path: gtv_dashboard_server.py:search_recipes() + load_index()
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class KnowledgeModule:
    """Search elder-brain vault."""

    def __init__(self, vault_path: Optional[str] = None, index_path: Optional[str] = None):
        self.vault_path = Path(vault_path or os.getenv("GA_VAULT", Path.home() / "elder-brain"))
        self.index_path = Path(index_path or self.vault_path / "recipe_index.json")
        self._index = None
        self._index_mtime = 0

    # ============================================================
    # Main interface
    # ============================================================

    def answer(self, command: str) -> Optional[str]:
        """Try to answer a command from local knowledge.
        
        Args:
            command: User's command/question
            
        Returns: Answer text or None if not found
        """
        # Try recipe search
        recipes = self.search_recipes(command, limit=3)
        if recipes:
            return self._format_recipe_answer(recipes[0])
        
        # Try note search
        notes = self.search_notes(command, limit=3)
        if notes:
            return self._format_note_answer(notes[0])
        
        return None

    def search_recipes(self, query: str, limit: int = 5) -> list[dict]:
        """Search recipes by query.
        
        Real: gtv_dashboard_server.py:search_recipes() uses inverted index
        """
        idx = self._load_index()
        if not idx:
            return []
        
        words = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 2]
        if not words:
            return []
        
        # Score by word matches
        scores = {}
        for word in words:
            for path in idx.get(word, []):
                scores[path] = scores.get(path, 0) + 1
        
        # Sort by score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        results = []
        for path, score in ranked[:limit]:
            recipe = self._load_recipe(path)
            if recipe:
                recipe["_score"] = score
                results.append(recipe)
        
        return results

    def search_notes(self, query: str, limit: int = 5) -> list[dict]:
        """Search notes by query."""
        notes_dir = self.vault_path / "notes"
        if not notes_dir.exists():
            return []
        
        words = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 2]
        if not words:
            return []
        
        results = []
        for note_file in notes_dir.glob("*.md"):
            text = note_file.read_text(errors="ignore").lower()
            score = sum(1 for w in words if w in text)
            if score > 0:
                results.append({
                    "path": str(note_file),
                    "title": note_file.stem,
                    "score": score,
                    "preview": text[:200],
                })
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    # ============================================================
    # Index management
    # ============================================================

    def _load_index(self) -> Optional[dict]:
        """Load inverted index (with mtime check)."""
        if not self.index_path.exists():
            return None
        
        mtime = self.index_path.stat().st_mtime
        if self._index is None or mtime > self._index_mtime:
            try:
                self._index = json.loads(self.index_path.read_text())
                self._index_mtime = mtime
            except Exception as e:
                logger.warning(f"Failed to load index: {e}")
                return None
        
        return self._index

    def _load_recipe(self, path: str) -> Optional[dict]:
        """Load a recipe from vault."""
        recipe_path = self.vault_path / "recipes" / f"{path}.md"
        if not recipe_path.exists():
            return None
        
        try:
            text = recipe_path.read_text(errors="ignore")
            return {
                "path": str(recipe_path),
                "title": path.replace("-", " ").replace("_", " "),
                "text": text[:500],
            }
        except Exception:
            return None

    # ============================================================
    # Formatting
    # ============================================================

    def _format_recipe_answer(self, recipe: dict) -> str:
        """Format recipe as answer."""
        title = recipe.get("title", "Recipe")
        return f"Here's your recipe for {title}."

    def _format_note_answer(self, note: dict) -> str:
        """Format note as answer."""
        title = note.get("title", "Note")
        return f"I found a note about {title}."

    # ============================================================
    # Capabilities
    # ============================================================

    @property
    def capabilities(self) -> list[str]:
        return ["knowledge", "recipe_search", "note_search"]

    @property
    def available(self) -> bool:
        return self.vault_path.exists()
