from __future__ import annotations

import importlib.util
import json
import re
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("simplify_wireless_obsidian_graph.py")
spec = importlib.util.spec_from_file_location("wireless_graph", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

files = module.load_markdown(module.TARGET)
metrics = module.link_metrics(files)
errors = module.validate(files, 1055)

with zipfile.ZipFile(module.BACKUP, "r") as archive:
    backup_bad_member = archive.testzip()
    backup_md_count = len([name for name in archive.namelist() if name.endswith(".md")])

semantic_bad: list[str] = []
candidate_count = 0
candidate_navigation_count = 0
total_index_mentions = 0
home_frontmatter_links = 0
global_callout_links = 0
for name, text in files.items():
    is_candidate = "candidate_key:" in text
    candidate_count += int(is_candidate)
    candidate_navigation_count += int(is_candidate and "## 层级导航" in text)
    total_index_mentions += text.count("[[通信教材总索引]]")
    home_frontmatter_links += text.count('book_home: "[[')
    global_callout_links += text.count("> 教材主页：[[")
    for match in re.finditer(
        r"(?ms)^## 语义关系（不参与关系图）\s*\n(.*?)(?=^## |\Z)", text
    ):
        if module.LINK_RE.search(match.group(1)):
            semantic_bad.append(name)

toc = files[module.TOC]
result = {
    "file_count": len(files),
    "candidate_count": candidate_count,
    "candidate_navigation_count": candidate_navigation_count,
    "metrics": metrics,
    "validation_errors": errors,
    "backup_md_count": backup_md_count,
    "backup_testzip": backup_bad_member,
    "digital_sha256": module.sha256(module.DIGITAL_INDEX),
    "semantic_sections_with_wikilinks": semantic_bad,
    "book_home_frontmatter_wikilinks": home_frontmatter_links,
    "global_callout_wikilinks": global_callout_links,
    "wireless_total_index_mentions": total_index_mentions,
    "toc_chapter_links": len(re.findall(r"(?m)^## \[\[[^\]]+\]\]$", toc)),
    "toc_detail_links": len(re.findall(r"(?m)^- \[\[", toc)),
}
print(json.dumps(result, ensure_ascii=False, indent=2))

assert not errors
assert len(files) == 1055
assert candidate_count == candidate_navigation_count
assert backup_md_count == 1055
assert backup_bad_member is None
assert module.sha256(module.DIGITAL_INDEX) == "5874C14DA282E41FCCC29740F95D363291030273873F255D4E984C47445A4899"
assert not semantic_bad
assert home_frontmatter_links == 0
assert global_callout_links == 0
assert total_index_mentions == 1
assert result["toc_chapter_links"] == 11
assert result["toc_detail_links"] == 0
