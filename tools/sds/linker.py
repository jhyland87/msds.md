"""Turn mentions of other vault chemicals into Obsidian [[wikilinks]]."""

from __future__ import annotations

import re


class Linker:
    """Links the first mention of each known chemical once per section."""

    def __init__(self, aliases: dict[str, str]):
        # aliases: lowercase alias -> note name. Longest first so
        # "red fuming nitric acid" wins over "nitric acid".
        self.aliases = aliases
        ordered = sorted(aliases, key=len, reverse=True)
        self.pattern = (
            re.compile(r"(?<![\w\[|-])(" + "|".join(re.escape(a) for a in ordered) + r")(?![\w\]-])", re.IGNORECASE)
            if ordered
            else None
        )

    def link(self, text: str, current: str, linked: set[str]) -> str:
        """Replace first mentions in `text`; `linked` tracks targets already used."""
        if not self.pattern:
            return text

        def repl(match: re.Match[str]) -> str:
            target = self.aliases[match.group(1).lower()]
            if target == current or target in linked:
                return match.group(0)
            linked.add(target)
            shown = match.group(0)
            return f"[[{target}]]" if shown == target else f"[[{target}|{shown}]]"

        # Leave URLs and existing links untouched.
        parts = re.split(r"(\[\[.*?\]\]|\[[^\]]*\]\([^)]*\)|https?://\S+)", text)
        return "".join(p if i % 2 else self.pattern.sub(repl, p) for i, p in enumerate(parts))
