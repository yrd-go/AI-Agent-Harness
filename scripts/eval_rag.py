# -*- coding: utf-8 -*-
"""
scripts/eval_rag.py —— RAG 检索评测：一条命令出「hit@1 / hit@k / MRR / 延迟」对比表
=====================================================================================

为什么要它：
    README 里的历史数字都是**单次截图**，回答不了「你怎么证明混合检索比纯向量好」。
    这个脚本把评测变成一条命令：同一套 40 题、同一套判定标准，跑多组配置出对比表。

判定标准（可复现，不靠人工看）：
    检索到的片段满足下面任一条件即算命中该题：
      1) 片段正文里出现期望条目编号（如 【Q4-08】）；
      2) 片段的原文行号区间与期望条目的行号区间有重叠。
    指标：
      hit@1  —— 第 1 条就命中
      hit@k  —— 前 k 条里有命中（k 默认 4，与线上一致）
      MRR    —— 首个命中名次的倒数均值（越接近 1 越好）

用法：
    python scripts/eval_rag.py                    # 默认 4 组配置（需要 ZHIPU_API_KEY）
    python scripts/eval_rag.py --limit 10         # 抽样快跑
    python scripts/eval_rag.py --configs vector-only,keyword-only
    python scripts/eval_rag.py --with-answers     # 追加答案级指标（拒答率 / 误拒答率）
    python scripts/eval_rag.py --out reports/baseline.json

退出码：0 = 正常跑完；1 = 参数/环境错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rag_demo  # noqa: E402

QA_FILE = PROJECT_ROOT / "data" / "eval" / "qa.jsonl"
REPORT_DIR = PROJECT_ROOT / "reports"

# 配置名 -> 人类可读说明（顺序即表格顺序）
CONFIGS: dict = {
    "hybrid": "查询改写 + 向量/关键词混合检索（默认链路）",
    "hybrid-no-rewrite": "不做 LLM 改写：本地分词 + 混合检索",
    "vector-only": "纯向量检索（≈ --no-rerank）",
    "keyword-only": "本地关键词召回（零外部依赖 = 检索降级路径）",
}
DEFAULT_CONFIGS = ("hybrid", "hybrid-no-rewrite", "vector-only", "keyword-only")

# 模型"拒答"的措辞特征（用于答案级指标）
REFUSAL_MARKERS = ("未收录", "没有收录", "未涵盖", "未包含")
# 有实质内容的特征：编号步骤，或对具体条目号的引用
_STEP_RE = re.compile(r"(^|\n)\s*\d+\s*[.、)]")
_CITATION_RE = re.compile(r"【Q\d-\d\d】")


def looks_like_refusal(answer: str) -> bool:
    """判断一条回答是不是「实质拒答」。

    为什么不能只看关键词（踩过的坑）：
        旧判定是 `any(marker in answer)`，结果把
        「……处理步骤如下：1. …… 2. ……（末尾附一句：若仍不行请联系服务台）」
        这种**有实质答案**的回复也算成了拒答，误拒答率直接虚高到 32%。
        规则应该是：**命中拒答话术 且 没有实质内容（无编号步骤、无条目引用）且篇幅很短**。
    """
    text = (answer or "").strip()
    if not any(marker in text for marker in REFUSAL_MARKERS):
        return False
    has_substance = bool(_STEP_RE.search(text)) or bool(_CITATION_RE.search(text))
    return (not has_substance) and len(text) <= 120


# ---------------------------------------------------------------------------
# 数据与判定
# ---------------------------------------------------------------------------
def load_qa(path: Path = QA_FILE) -> list:
    if not Path(path).is_file():
        raise SystemExit(f"[FAIL] 找不到评测集：{path}")
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"[FAIL] {path}:{lineno} 不是合法 JSON：{exc}")
    if not items:
        raise SystemExit(f"[FAIL] 评测集为空：{path}")
    return items


def chunk_matches(hit, expect_ids, expect_lines) -> bool:
    """片段是否命中期望条目：编号命中 或 行号区间重叠。"""
    text = getattr(hit.doc, "page_content", "") or ""
    for eid in expect_ids or []:
        if f"【{eid}】" in text:
            return True
    start = getattr(hit, "line_start", -1) or -1
    end = getattr(hit, "line_end", -1) or -1
    if start > 0:
        for pair in expect_lines or []:
            if pair and len(pair) == 2:
                lo, hi = int(pair[0]), int(pair[1])
                if end >= lo and start <= hi:
                    return True
    return False


def first_hit_rank(hits, expect_ids, expect_lines):
    """首个命中的名次（从 1 起）；未命中返回 None。"""
    for rank, hit in enumerate(hits, 1):
        if chunk_matches(hit, expect_ids, expect_lines):
            return rank
    return None


def summarize(ranks: list, latencies: list) -> dict:
    """把每题名次汇总成指标；ranks 中的 None 表示未命中。"""
    total = len(ranks)
    if total == 0:
        return {"total": 0, "hit@1": 0.0, "hit@k": 0.0, "mrr": 0.0, "avg_ms": 0.0}
    hit1 = sum(1 for r in ranks if r == 1) / total
    hitk = sum(1 for r in ranks if r is not None) / total
    mrr = sum((1.0 / r) for r in ranks if r is not None) / total
    avg_ms = (sum(latencies) / len(latencies)) if latencies else 0.0
    return {
        "total": total,
        "hit@1": round(hit1, 4),
        "hit@k": round(hitk, 4),
        "mrr": round(mrr, 4),
        "avg_ms": round(avg_ms, 1),
    }


# ---------------------------------------------------------------------------
# 跑一组配置
# ---------------------------------------------------------------------------
def retrieve_for(config: str, db, question: str, k: int,
                 keyword_weight: float, candidate_k: int) -> list:
    """按配置执行一次检索，返回 top-k。"""
    if config == "vector-only":
        return rag_demo.retrieve(db, question, k)

    if config == "keyword-only":
        terms = rag_demo.build_terms(question, None)
        hits, _pool = rag_demo.retrieve_keyword_only(question, question, terms, k, db=db)
        return hits

    if config == "hybrid":
        rr = rag_demo.rewrite_query(question, allow_ollama=False)
        rewritten = rr.query or question
        terms = rag_demo.build_terms(rewritten, rr.keywords)
    elif config == "hybrid-no-rewrite":
        rewritten = question
        terms = rag_demo.build_terms(question, None)
    else:
        raise SystemExit(f"[FAIL] 未知配置：{config}")

    hits, _pool, _mode, _note = rag_demo.retrieve_with_fallback(
        db,
        original_question=question,
        rewritten_query=rewritten,
        terms=terms,
        k=k,
        keyword_weight=keyword_weight,
        candidate_k=candidate_k,
        # 评测要测「这条链路本身」：不允许静默降级把两种模式混在一起
        allow_fallback=False,
    )
    return hits


def run_config(config: str, db, items: list, k: int, keyword_weight: float,
               candidate_k: int, quiet: bool = False) -> tuple:
    ranks, latencies, misses = [], [], []
    for idx, item in enumerate(items, 1):
        question = item["question"]
        t0 = time.perf_counter()
        try:
            hits = retrieve_for(config, db, question, k, keyword_weight, candidate_k)
            err = ""
        except Exception as exc:  # noqa: BLE001
            hits, err = [], rag_demo.describe_exc(exc)
        cost_ms = (time.perf_counter() - t0) * 1000
        rank = first_hit_rank(hits, item.get("expect_ids"), item.get("expect_lines"))
        ranks.append(rank)
        latencies.append(cost_ms)
        if rank is None:
            misses.append({
                "id": item["id"], "question": question,
                "expect": item.get("expect_ids"), "error": err,
            })
        if not quiet:
            mark = "OK  " if rank else "MISS"
            print(f"    [{idx:>2}/{len(items)}] {mark} {item['id']}  rank={rank}  {cost_ms:>7.0f}ms")
    metrics = summarize(ranks, latencies)
    return metrics, ranks, misses


# ---------------------------------------------------------------------------
# 答案级指标（可选，会真实调用生成模型）
# ---------------------------------------------------------------------------
def run_answers(db, items: list, k: int, keyword_weight: float,
                candidate_k: int, config: str = "hybrid",
                retries: int = 2, sleep_s: float = 1.0,
                quiet: bool = False) -> tuple:
    """拒答率与**误拒答率**。

    误拒答 = 检索命中了正确条目，模型却说「知识库未收录」——
    这是最该修的一类：库里明明有，用户却被推给服务台。

    工程细节（踩过坑）：
      - 逐题之间 sleep 一小会儿、失败重试 —— 否则连续上百次调用会触发限流，
        结果就是"31/40 题报错"，指标直接不可信；
      - 拒答率的**分母只用真正拿到回答的样本**（answered），
        出错样本单独统计，绝不让分母变成 0 或负数而算出 200% 这种荒唐值。
    """
    stats = {"total": 0, "answered": 0, "refusals": 0, "false_refusals": 0,
             "cited_expected": 0, "errors": 0, "retrieval_errors": 0,
             "generation_errors": 0}
    samples = []
    answers_log: list = []

    for idx, item in enumerate(items, 1):
        question = item["question"]
        stats["total"] += 1
        try:
            hits = retrieve_for(config, db, question, k, keyword_weight, candidate_k)
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            stats["retrieval_errors"] += 1
            if not quiet:
                print(f"    [{idx:>2}/{len(items)}] ERROR(检索) {item['id']} "
                      f"{rag_demo.describe_exc(exc)}")
            continue

        rank = first_hit_rank(hits, item.get("expect_ids"), item.get("expect_lines"))
        prompt = rag_demo.build_prompt(hits, question)

        answer, err = "", None
        for attempt in range(retries + 1):
            answer, err = rag_demo.call_zhipu(prompt)
            if err is None:
                break
            if attempt < retries:
                time.sleep(2.0 * (attempt + 1))      # 限流了就退避一下再试

        if err is not None:
            stats["errors"] += 1
            stats["generation_errors"] += 1
            if not quiet:
                print(f"    [{idx:>2}/{len(items)}] ERROR(生成) {item['id']} "
                      f"{rag_demo.describe_exc(err)}")
            time.sleep(sleep_s)
            continue

        stats["answered"] += 1
        refused = looks_like_refusal(answer)
        # 「有据可依」的便宜代理指标：回答里有没有引用期望的条目号。
        # 只看拒答率下降是不够的 —— 还要看它是否真的落在了正确条目上。
        if any(f"【{eid}】" in answer for eid in (item.get("expect_ids") or [])):
            stats["cited_expected"] += 1
        if refused:
            stats["refusals"] += 1
            if rank is not None:
                stats["false_refusals"] += 1
                samples.append({
                    "id": item["id"], "question": question,
                    "expect": item.get("expect_ids"), "rank": rank,
                    "answer": answer[:240],
                })
        cited = bool(any(f"【{eid}】" in answer for eid in (item.get("expect_ids") or [])))
        answers_log.append({
            "id": item["id"], "question": question, "rank": rank,
            "refused": refused, "cited": cited, "answer": answer[:400],
        })
        if not quiet:
            flag = "REFUSED" if refused else "answered"
            print(f"    [{idx:>2}/{len(items)}] {flag:<8} {item['id']}  rank={rank}")
        time.sleep(sleep_s)
    return stats, samples, answers_log


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def print_table(results: dict, k: int) -> None:
    print("\n" + "=" * 104)
    print(f"{'配置':<20}{'hit@1':>8}{'hit@' + str(k):>8}{'MRR':>8}{'平均耗时(ms)':>14}   说明")
    print("-" * 104)
    for name, data in results.items():
        m = data["metrics"]
        print(f"{name:<20}{m['hit@1']:>8.3f}{m['hit@k']:>8.3f}{m['mrr']:>8.3f}"
              f"{m['avg_ms']:>14.1f}   {CONFIGS.get(name, '')}")
    print("=" * 104)


def print_misses(results: dict, limit: int = 8) -> None:
    for name, data in results.items():
        misses = data.get("misses") or []
        if not misses:
            continue
        print(f"\n[未命中] {name}（{len(misses)} 题，列出前 {min(limit, len(misses))} 条）")
        for item in misses[:limit]:
            print(f"    - {item['id']}: {item['question']}  期望 {item['expect']}"
                  + (f"  [{item['error']}]" if item.get("error") else ""))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval_rag.py",
        description="RAG 检索评测：hit@1 / hit@k / MRR / 延迟，对比多组配置",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0 = 全部）")
    parser.add_argument("--k", type=int, default=rag_demo.DEFAULT_K, help="返回片段数（默认与线上一致）")
    parser.add_argument("--keyword-weight", type=float,
                        default=rag_demo.DEFAULT_KEYWORD_WEIGHT, help="混合检索的 α")
    parser.add_argument("--candidate-k", type=int, default=0, help="候选池大小（0 = 自动）")
    parser.add_argument("--embedder", default="zhipu", choices=["zhipu", "ollama"])
    parser.add_argument("--configs", default=",".join(DEFAULT_CONFIGS),
                        help=f"逗号分隔，可选：{','.join(CONFIGS)}")
    parser.add_argument("--with-answers", action="store_true",
                        help="追加答案级指标（拒答率 / 误拒答率）——会真实调用生成模型")
    parser.add_argument("--answer-config", default="hybrid", choices=list(CONFIGS),
                        help="答案级指标用哪条检索链路（默认 hybrid，即线上默认；"
                             "做前后对比时必须固定它，否则无法归因）")
    parser.add_argument("--answer-retries", type=int, default=2,
                        help="生成失败的重试次数（默认 2；限流时有用）")
    parser.add_argument("--answer-sleep", type=float, default=1.0,
                        help="每题之间休眠秒数（默认 1.0，防限流）")
    parser.add_argument("--prompt-variant", default="current", choices=["current", "legacy"],
                        help="提示词变体：legacy=改动前的严格版（用于 A/B 对比，"
                             "保证两次运行只差「提示词」这一个变量）")
    parser.add_argument("--out", default="", help="报告路径（默认 reports/eval_<时间戳>.json）")
    parser.add_argument("--quiet", action="store_true", help="不打印逐题进度")
    args = parser.parse_args(argv)

    # 让 rag_demo 走指定的提示词变体（A/B 用；必须在调用 build_prompt 之前设置）
    os.environ["RAG_PROMPT_VARIANT"] = args.prompt_variant

    items = load_qa()
    if args.limit > 0:
        items = items[:args.limit]

    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in configs if c not in CONFIGS]
    if unknown:
        raise SystemExit(f"[FAIL] 未知配置 {unknown}；可选：{list(CONFIGS)}")

    candidate_k = (args.candidate_k if args.candidate_k > 0
                   else max(args.k * rag_demo.CANDIDATE_K_FACTOR, rag_demo.CANDIDATE_K_MIN))

    print(f"[配置] 题目 {len(items)} 道 | k={args.k} | α={args.keyword_weight} | "
          f"候选池={candidate_k} | 向量化={args.embedder} | 配置={'/'.join(configs)}")

    needs_db = any(c != "keyword-only" for c in configs) or args.with_answers
    db = None
    if needs_db:
        t0 = time.perf_counter()
        db = rag_demo.build_or_load_vectorstore(args.embedder, False)
        print(f"[信息] 向量库就绪，用时 {time.perf_counter() - t0:.1f}s")

    results: dict = {}
    for config in configs:
        print(f"\n[运行] {config} —— {CONFIGS[config]}")
        t0 = time.perf_counter()
        metrics, _ranks, misses = run_config(
            config, db, items, args.k, args.keyword_weight, candidate_k, quiet=args.quiet
        )
        metrics["wall_s"] = round(time.perf_counter() - t0, 1)
        results[config] = {"metrics": metrics, "misses": misses}
        print(f"    -> hit@1={metrics['hit@1']:.3f}  hit@{args.k}={metrics['hit@k']:.3f}  "
              f"MRR={metrics['mrr']:.3f}  平均 {metrics['avg_ms']:.0f}ms")

    print_table(results, args.k)
    print_misses(results)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "questions": len(items),
        "k": args.k,
        "keyword_weight": args.keyword_weight,
        "candidate_k": candidate_k,
        "embedder": args.embedder,
        "retrieval": results,
    }

    if args.with_answers:
        print(f"\n[运行] 答案级指标（配置={args.answer_config}，提示词={args.prompt_variant}，"
              "真实调用生成模型，会比较慢）")
        stats, samples, answers_log = run_answers(
            db, items, args.k, args.keyword_weight, candidate_k,
            config=args.answer_config, retries=args.answer_retries,
            sleep_s=args.answer_sleep, quiet=args.quiet,
        )
        answered = stats["answered"]
        if answered == 0:
            stats["refusal_rate"] = None
            stats["false_refusal_rate"] = None
        else:
            stats["refusal_rate"] = round(stats["refusals"] / answered, 4)
            stats["false_refusal_rate"] = round(stats["false_refusals"] / answered, 4)
            stats["cited_rate"] = round(stats["cited_expected"] / answered, 4)
        report["answers"] = {"config": args.answer_config,
                             "prompt_variant": rag_demo.prompt_variant(),
                             "stats": stats,
                             "false_refusal_samples": samples,
                             "log": answers_log}
        print("=" * 104)
        if answered == 0:
            print(f"答案级：**样本不足**（{stats['total']} 题里全部请求失败："
                  f"检索错 {stats['retrieval_errors']} / 生成错 {stats['generation_errors']}）"
                  "—— 没有可信指标，请检查网络与 Key，或调大 --answer-sleep")
        else:
            print(f"答案级（配置={args.answer_config}）：拿到回答 {answered}/{stats['total']} 题"
                  f" | 拒答 {stats['refusals']}（{stats['refusal_rate']:.1%}）"
                  f" | **误拒答 {stats['false_refusals']}（{stats['false_refusal_rate']:.1%}）**"
                  f" | 引用到正确条目 {stats['cited_expected']}（{stats['cited_rate']:.1%}）"
                  f" | 出错 {stats['errors']}（检索 {stats['retrieval_errors']} / 生成 {stats['generation_errors']}）")
        if samples:
            print(f"\n误拒答样本（检索命中了正确条目、模型却说没收录）—— 前 {min(3, len(samples))} 条：")
            for s in samples[:3]:
                print(f"    - {s['id']} rank={s['rank']} 期望 {s['expect']}：{s['question']}")
                print(f"      回答：{s['answer'][:80]}…")
        print("=" * 104)

    out_path = Path(args.out) if args.out else (
        REPORT_DIR / f"eval_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[报告] 已写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
