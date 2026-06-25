from __future__ import annotations

import json
import sys

from gather.commands import _split


def cmd_corpus(args) -> int:
    from gather.store import Corpus
    try:
        return _corpus_dispatch(args, Corpus(args.dir))
    except ValueError as exc:  # a malformed catalog/runs line surfaces as a clean error, not a traceback
        print(f"corpus {args.action} failed: {exc}", file=sys.stderr)
        return 1


def _corpus_dispatch(args, c) -> int:
    from gather.digest import verify_digest

    if args.action == "list":
        rows = list(c.rows())
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for r in rows:
                print(f"  {r['kind']:<10} {r['id']:<20} {r['method']:<16} {r['title'][:40]}")
            print(f"{len(rows)} item(s) in {args.dir}")
        return 0
    if args.action == "verify":
        results = c.verify()
        bad = [r for r in results if r["status"] != "MATCH"]
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            counts: dict[str, int] = {}
            for r in results:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
            print(f"verified {len(results)} item(s): {dict(sorted(counts.items()))}")
            for r in bad:
                print(f"  {r['status']:<8} {r['id']} {r['sha256'][:12]}")
        return 1 if bad else 0
    if args.action == "search":
        from gather.digest import digest
        from gather.recall import Query, recall_audited
        from gather.source import Catalog

        q = Query(terms=tuple(_split(args.terms)), sources=tuple(_split(args.source)),
                  kinds=tuple(_split(args.kind)), methods=tuple(_split(args.method)))
        items, skipped = recall_audited(c, q, limit=args.limit)
        d = digest(items)
        if args.json:
            cat = Catalog()
            cat.add(items)
            print(json.dumps({"catalog": cat.rows(), "digest": json.loads(d.to_json()), "skipped": skipped},
                             indent=2, ensure_ascii=False))
        else:
            for i in items:
                print(f"  {i.kind:<10} {i.id:<20} {i.provenance.source:<8} {i.title[:36]}")
            skip_note = f", {len(skipped)} skipped (missing/corrupt body)" if skipped else ""
            if items:
                print(f"{len(items)} match(es), bodies verified{skip_note}; digest seal {d.seal[:16]}...")
            else:
                print(f"0 matches{skip_note}")
        return 1 if skipped else 0
    if args.action == "runs":
        history = list(c.runs())
        if args.verify:
            from gather.run import RunRecord, verify_record

            def _check(r: dict) -> bool:
                try:
                    return verify_record(RunRecord.from_dict(r))
                except ValueError:
                    return False  # a malformed record fails the check rather than crashing the command

            checked = [(r.get("digest_seal", "")[:12], _check(r)) for r in history]
            bad = [s for s, ok in checked if not ok]
            if args.json:
                print(json.dumps([{"digest_seal": s, "verified": ok} for s, ok in checked], indent=2))
            else:
                for s, ok in checked:
                    print(f"  {'OK ' if ok else 'BAD'} record {s}")
                print(f"verified {len(checked)} run record(s), {len(bad)} bad")
            return 1 if bad else 0
        if args.json:
            print(json.dumps(history, indent=2, ensure_ascii=False))
        else:
            for r in history:
                syn = " +synthesis" if r.get("synthesized") else ""
                print(f"  gathered {r['gathered']:<4} kept {r['kept']:<4} scope {r.get('scope')}"
                      f" seal {r['digest_seal'][:12]}{syn}")
            print(f"{len(history)} run(s) in {args.dir}")
        return 0
    if args.action == "stats":
        s = c.stats()
        if args.json:
            print(json.dumps(s, indent=2, ensure_ascii=False))
        else:
            print(f"{s['items']} item(s), {s['distinct_bodies']} distinct bodies in {args.dir}")
            print("by source:", s["by_source"])
            print("by kind:  ", s["by_kind"])
            print("by method:", s["by_method"])
        return 0
    if args.action == "prune":
        res = c.prune(apply=args.apply)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.apply:
            print(f"removed {res['removed']} orphan object(s)")
        else:
            print(f"{res['orphans']} orphan object(s); run with --apply to remove")
        return 0
    d = c.digest()  # action == "digest"
    if args.json:
        print(d.to_json())
    else:
        print(f"corpus digest: {len(d.receipts)} receipts, seal {d.seal[:16]}..., verified {verify_digest(d)}")
    return 0
