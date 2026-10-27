"""阶段序列契约检查：确保前端时间线的阶段定义覆盖后端推送的全部 stage 值。

背景（这正是本次修复的缺陷）：
    前端原本只有一套阶段序列（按 M1 定义），而后端 M2/M3/M5 推送了
    extracting / analyzing / criticizing / generating / verifying 等不在其中的值，
    导致 StageTimeline 的下标匹配恒为 -1，界面上表现为
    「进度百分比在涨、阶段条纹却卡在第一项不动，结束时所有项一起变完成」。

本检查用于防止同类问题复发：后端新增阶段时必须同步更新前端序列。

用法：
    python scripts/check_stage_contract.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TYPES_FILE = ROOT / "frontend" / "src" / "types" / "index.ts"
SERVICES_DIR = Path(__file__).resolve().parents[1] / "app" / "services"

# 后端服务 -> 前端对应的阶段序列常量
MODULE_SEQUENCE = {
    "explore_service.py": "STAGE_SEQUENCE_EXPLORE",
    "gap_service.py": "STAGE_SEQUENCE_GAP",
    "feasibility_service.py": "STAGE_SEQUENCE_FEASIBILITY",
    "review_service.py": "STAGE_SEQUENCE_REVIEW",
}

PROGRESS_RE = re.compile(r"bus\.progress\(\s*task_id,\s*\"(\w+)\"")
SEQUENCE_RE = re.compile(r"export const (STAGE_SEQUENCE_\w+): StageItem\[\] = \[(.*?)\n\];", re.S)
KEY_RE = re.compile(r'key: "(\w+)"')


def load_sequences() -> dict[str, list[str]]:
    text = TYPES_FILE.read_text(encoding="utf-8")
    return {name: KEY_RE.findall(body) for name, body in SEQUENCE_RE.findall(text)}


def collect_stages(path: Path) -> list[str]:
    found: list[str] = []
    for match in PROGRESS_RE.finditer(path.read_text(encoding="utf-8")):
        stage = match.group(1)
        if stage not in found:
            found.append(stage)
    return found


def main() -> None:
    sequences = load_sequences()
    if not sequences:
        print(f"未能从 {TYPES_FILE} 解析出阶段序列，请检查文件结构是否变化")
        raise SystemExit(1)

    print("前端阶段序列：")
    for name, keys in sequences.items():
        print(f"  {name}")
        print(f"    {' -> '.join(keys)}")

    problems: list[str] = []
    print("\n后端推送 stage 的覆盖检查：")
    for filename, sequence_name in MODULE_SEQUENCE.items():
        path = SERVICES_DIR / filename
        if not path.exists():
            print(f"  {filename:<26} 文件不存在，跳过")
            continue
        stages = collect_stages(path)
        defined = sequences.get(sequence_name, [])
        missing = [stage for stage in stages if stage not in defined]
        status = "OK" if not missing else f"缺失 {missing}"
        print(f"  {filename:<26} {len(stages)} 个 stage -> {sequence_name}  [{status}]")
        if missing:
            problems.append(f"{filename} 推送了 {missing}，未定义在 {sequence_name}")

    if problems:
        print("\n[未通过] 后端存在前端序列未定义的阶段，界面会卡在第一个阶段不动：")
        for item in problems:
            print(f"  - {item}")
        raise SystemExit(1)

    print("\n[通过] 所有后端阶段都在前端序列中有定义，阶段条纹可正常逐级推进。")


if __name__ == "__main__":
    main()
