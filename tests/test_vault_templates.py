import pytest

from sds.render import Renderer
from sds.vault_templates import format_source, load_layout, parse_layout
from test_render import make_doc


def test_vault_template_defines_full_layout():
    layout = load_layout()
    assert list(layout.section_titles) == list(range(1, 17))
    assert layout.non_mandatory == {12, 13, 14, 15}
    assert "Boiling point" in layout.required_properties
    assert layout.frontmatter_keys[0] == "title"
    assert layout.gap_callout.startswith("> [!warning]")


def test_generated_frontmatter_only_uses_template_properties():
    keys = Renderer.frontmatter(make_doc()).split("---")[1]
    used = {line.split(":")[0] for line in keys.splitlines() if line and not line.startswith(("-", " "))}
    assert used <= set(load_layout().frontmatter_keys)


def test_format_source_with_and_without_url():
    layout = load_layout()
    assert format_source(layout, 2, "CAMEO", "https://x.example", "2026-01-01") == (
        "[^2]: **CAMEO**. <https://x.example> (accessed 2026-01-01)"
    )
    assert format_source(layout, 3, "CHEMTREC", None, "2026-01-01") == "[^3]: **CHEMTREC** (accessed 2026-01-01)"


def test_template_missing_sections_is_rejected():
    with pytest.raises(ValueError):
        parse_layout("## 1. Identification\n", "> x", "[^{{n}}]:")
