from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).with_name("simplify_wireless_obsidian_graph.py")
spec = importlib.util.spec_from_file_location("wireless_graph", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PARENTS = {
    "04 - 室内路径损耗模型（衰减因子模型）": "04 - 4.11 室内传播模型",
    "06 - 例6.12 莱斯衰落信道中DPSK与非相干正交FSK差错概率推导": "06 - 6.12 衰落和多径信道中的调制性能",
    "06 - 相干GMSK在瑞利衰落信道中的误码率公式": "06 - 6.12 衰落和多径信道中的调制性能",
    "11 - Q函数右尾概率公式": "附录F Q、erf和erfc函数",
    "11 - RSSI (接收信号强度指示)": "03 - 3.4 切换策略",
    "11 - SDMA (空分多址)": "09 - 9.5 空分多址 ( SDMA)",
    "11 - SIR S I (信号干扰比)": "03 - 3.5 干扰和系统容量",
    "11 - SNR S N (信噪比)": "06 - 6.4 数字调制概述",
    "11 - TD-SCDMA (时分同步码分多址)": "02 - 2.2 3G 无线网络",
    "11 - TDD (时分双工)": "02 - 2.2 3G 无线网络",
    "11 - TDMA (时分多址)": "09 - 9.3 时分多址( TDMA)",
    "11 - UMTS (通用移动电信系统)": "10 - 10.14 通用移动通信系统( UMTS)",
    "11 - W-CDMA (宽带CDMA)": "02 - 2.2 3G 无线网络",
    "11 - WLAN (无线局域网)": "02 - 2.4 无线局域网( WLAN)",
    "11 - WLL (无线本地环路)": "02 - 2.3 无线本地环路( WLL) 与 LMDS",
}


def add_navigation(root: Path) -> None:
    existing = {path.stem for path in root.glob("*.md")}
    for child, parent in PARENTS.items():
        if child not in existing:
            raise RuntimeError(f"missing child note: {child}")
        if parent not in existing:
            raise RuntimeError(f"missing parent note: {parent}")
        path = root / f"{child}.md"
        text = path.read_text(encoding="utf-8-sig")
        if "## 层级导航" in text:
            raise RuntimeError(f"navigation already exists: {child}")
        marker = "\n## 来源位置"
        if marker not in text:
            raise RuntimeError(f"source section missing: {child}")
        navigation = f"\n## 层级导航\n\n- 所属结构 → [[{parent}]]\n"
        path.write_text(text.replace(marker, navigation + marker, 1), encoding="utf-8")


add_navigation(module.TARGET)
add_navigation(module.STAGING)

files = module.load_markdown(module.TARGET)
errors = module.validate(files, 1055)
if errors:
    raise RuntimeError("validation failed: " + "; ".join(errors))

manifest = json.loads(module.MANIFEST.read_text(encoding="utf-8"))
manifest["after"] = module.link_metrics(files)
manifest["hierarchy_completion"] = {
    "added_direct_parent_links": len(PARENTS),
    "policy": "orphan leaves linked to the nearest topical section, never directly to book home",
}
module.MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"added": PARENTS, "metrics": manifest["after"]}, ensure_ascii=False, indent=2))
