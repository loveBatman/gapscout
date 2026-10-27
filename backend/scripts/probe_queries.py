"""arXiv 查询语法探测：定位可用的查询构造格式。

已知事实：
- arXiv 不接受 cat:cs.* 通配符，必须列出具体分类
- arXiv 的布尔解析器对括号与优先级敏感，需要实测确认合法形式

用法：
    python scripts/probe_queries.py
"""

import asyncio
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
ARXIV_API = "https://export.arxiv.org/api/query"

CAT_FULL = (
    "(cat:cs.AI OR cat:cs.CL OR cat:cs.CV OR cat:cs.LG OR cat:cs.IR OR cat:cs.SE "
    "OR cat:cs.DB OR cat:cs.MA OR cat:cs.NE OR cat:cs.RO OR cat:cs.HC OR cat:cs.CR)"
)


async def probe(client: httpx.AsyncClient, label: str, expression: str) -> None:
    params = {"search_query": expression, "max_results": 3, "sortBy": "relevance"}
    try:
        response = await client.get(ARXIV_API, params=params, timeout=45)
        body = response.text
        print(f"  [{label}] HTTP {response.status_code} body_len={len(body)}")
        print(f"      url={response.url}")
        if response.status_code != 200:
            print(f"      body: {re.sub(chr(10), ' ', body[:220])}")
            return
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            print(f"      [非 XML 响应] {re.sub(chr(10), ' ', body[:220])}")
            return
        total = root.findtext(f"{OPENSEARCH}totalResults", "?")
        print(f"      total={total}")
        for entry in root.findall(f"{ATOM}entry"):
            title = re.sub(r"\s+", " ", entry.findtext(f"{ATOM}title", "") or "").strip()
            print(f"        - {title[:72]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [{label}] 异常: {type(exc).__name__}: {exc}")
    await asyncio.sleep(3.3)


async def main() -> None:
    direction = "multimodal large language model inference"
    async with httpx.AsyncClient(
        headers={"User-Agent": "GapScout/0.1 (mailto:researcher@example.com)"},
        follow_redirects=True,
    ) as client:
        print("=" * 76)
        print("[A组] 定位 cat 条件是否是语法错误来源")
        print("=" * 76)
        await probe(client, "A1 纯关键词无cat", "all:multimodal AND all:inference")
        await probe(client, "A2 单词+单分类", "all:multimodal AND cat:cs.CL")
        await probe(client, "A3 关键词+全分类", f"all:multimodal AND all:inference AND {CAT_FULL}")

        print("\n" + "=" * 76)
        print("[B组] 定位括号格式")
        print("=" * 76)
        await probe(
            client, "B1 分组括号", f"(all:multimodal AND all:inference) AND {CAT_FULL}"
        )
        await probe(client, "B2 无分组括号", f"all:multimodal AND all:inference AND {CAT_FULL}")
        await probe(
            client, "B3 短语分组", f'(all:"multimodal large language model") AND {CAT_FULL}'
        )

        print("\n" + "=" * 76)
        print("[C组] 召回量对比（选出最优策略）")
        print("=" * 76)
        await probe(
            client, "C1 4词短语+全分类", f'(all:"multimodal large language model") AND {CAT_FULL}'
        )
        await probe(
            client, "C2 3词短语+全分类", f'(all:"large language model") AND {CAT_FULL}'
        )
        await probe(
            client,
            "C3 关键词AND+全分类",
            f"(all:multimodal AND all:language AND all:model AND all:inference) AND {CAT_FULL}",
        )


if __name__ == "__main__":
    asyncio.run(main())
