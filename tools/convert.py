#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 Clash (mihomo) 的规则 profile 转成 sing-box 的远程规则集。

输入(默认路径在 Windows 上指向 Clash Verge Rev 的 profile 目录):
  profiles/r653jeIRqabx.yaml   type: rules  (prepend / append / delete)
  profiles/mVbTqfK59P2y.yaml   type: merge  (prepend-rules)

输出:
  singbox/direct.json   -> 在 iOS 客户端里以「直连」方式引用
  singbox/reject.json   -> 以「reject」方式引用
  singbox/proxy.json    -> 以「代理」方式引用
  text/direct.list      等价的纯文本格式,JSON 不被识别时可拿来试

设计说明:
  iOS 客户端只有 代理 / 直连 / reject 三种出站,没有策略组,
  所以这里按「目标出站」把规则拆成三份,而不是照搬 Clash 的 prepend 顺序。
  PROCESS-NAME / PROCESS-PATH 规则在 iOS 上无意义,直接丢弃。
"""
import json
import os
import re
import sys

import yaml

CLASH_DIR = os.path.expandvars(
    r"%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\profiles")
RULES_PROFILE = "r653jeIRqabx.yaml"
MERGE_PROFILE = "mVbTqfK59P2y.yaml"
SUB_PROFILE = "RHOPK3Eusk7y.yaml"

# final 已经是 proxy,所以这些"把国外域名指向代理"的宽规则是多余的;
# 更要紧的是 DOMAIN-KEYWORD,google 会把 google.cn(直连) 吃掉。
DROP_PROXY_KEYWORDS = {"google", "anthropic", "facebook", "youtube", "twitter"}

SUPPORTED = ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "IP-CIDR6")

# iOS 上建议直连的苹果基础服务(可在 README 里按需删掉)
APPLE_DIRECT = [
    "apple.com", "icloud.com", "mzstatic.com", "cdn-apple.com",
    "apple-cloudkit.com", "aaplimg.com", "push.apple.com",
]


def load_clash_rules(clash_dir, with_subscription=True):
    """返回 [(类型, 值, 目标)]"""
    out = []
    rp = yaml.safe_load(open(os.path.join(clash_dir, RULES_PROFILE), encoding="utf-8"))
    mp = yaml.safe_load(open(os.path.join(clash_dir, MERGE_PROFILE), encoding="utf-8"))
    sources = [mp.get("prepend-rules") or [], rp.get("prepend") or []]
    if with_subscription:
        # 订阅自带的 28 条广告 REJECT 规则,在 iOS 上会整个丢掉,这里一并搬过来
        sp = os.path.join(clash_dir, SUB_PROFILE)
        if os.path.exists(sp):
            sub = yaml.safe_load(open(sp, encoding="utf-8"))
            sources.append([r for r in (sub.get("rules") or []) if r.strip().endswith("REJECT")])
            print(f"  订阅 REJECT 规则: {len(sources[-1])} 条")
    for src in sources:
        for line in src:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            rtype = parts[0].upper()
            if rtype not in SUPPORTED:
                print(f"  [skip] {rtype:14} {line}")
                continue
            if parts[-1] == "no-resolve":
                target = parts[-2]
            else:
                target = parts[-1]
            out.append((rtype, parts[1], target))
    return out


def bucket(target):
    t = target.upper()
    if t == "DIRECT":
        return "direct"
    if t in ("REJECT", "REJECT-DROP"):
        return "reject"
    return "proxy"


def to_singbox(rules):
    """[(类型,值)] -> sing-box source rule-set 的 rules 数组"""
    dom, suffix, keyword, cidr, cidr6 = [], [], [], [], []
    for rtype, value in rules:
        if rtype == "DOMAIN":
            dom.append(value.lower())
        elif rtype == "DOMAIN-SUFFIX":
            suffix.append(value.lower().lstrip("."))
        elif rtype == "DOMAIN-KEYWORD":
            keyword.append(value.lower())
        elif rtype == "IP-CIDR":
            cidr.append(value)
        elif rtype == "IP-CIDR6":
            cidr6.append(value)
    rule = {}
    if dom:
        rule["domain"] = sorted(set(dom))
    if suffix:
        rule["domain_suffix"] = sorted(set(suffix))
    if keyword:
        rule["domain_keyword"] = sorted(set(keyword))
    if cidr:
        rule["ip_cidr"] = sorted(set(cidr))
    if cidr6:
        rule["ip_cidr"] += sorted(set(cidr6))
    return [rule] if rule else []


def to_text(rules):
    lines = []
    for rtype, value in rules:
        lines.append(f"{rtype},{value}")
    return sorted(set(lines))


def main():
    clash_dir = sys.argv[1] if len(sys.argv) > 1 else CLASH_DIR
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sb_dir, tx_dir = os.path.join(root, "singbox"), os.path.join(root, "text")
    os.makedirs(sb_dir, exist_ok=True)
    os.makedirs(tx_dir, exist_ok=True)

    print(f"读取规则: {clash_dir}")
    parsed = load_clash_rules(clash_dir)
    print(f"  得到 {len(parsed)} 条可用规则\n")

    groups = {"direct": [], "reject": [], "proxy": []}
    seen = {"direct": set(), "reject": set(), "proxy": set()}
    for rtype, value, target in parsed:
        b = bucket(target)
        if b == "proxy" and rtype == "DOMAIN-KEYWORD" and value.lower() in DROP_PROXY_KEYWORDS:
            print(f"  [drop] 多余的宽规则(会被 final:proxy 覆盖): {value}")
            continue
        key = (rtype, value.lower())
        if key in seen[b]:
            continue
        seen[b].add(key)
        groups[b].append((rtype, value))

    # 苹果基础服务补进直连(要在下面的去重之前,让它们也能罩住 proxy)
    for d in APPLE_DIRECT:
        groups["direct"].append(("DOMAIN-SUFFIX", d))

    # 直连优先级最高: proxy 里凡是"会被某条直连规则命中"的都去掉。
    # 不只是同名重复 —— 父域直连(A)也会罩住子域代理(B),反之亦然。
    # 删掉一条 proxy 规则本身不会改变结果(iOS 默认 final: proxy),
    # 只是消除"同一个域名在 direct/proxy 两份规则集里打架"的歧义:
    # 客户端按什么顺序加载规则集我们控制不了,歧义越少越好。
    d_dom = {v.lower() for t, v in groups["direct"] if t == "DOMAIN"}
    d_suf = {v.lower().lstrip(".") for t, v in groups["direct"] if t == "DOMAIN-SUFFIX"}
    d_kw = {v.lower() for t, v in groups["direct"] if t == "DOMAIN-KEYWORD"}

    def covered_by_direct(domain):
        domain = domain.lower().lstrip(".")
        if domain in d_dom or domain in d_suf:
            return True
        if any(domain.endswith("." + s) for s in d_suf):
            return True
        return any(k in domain for k in d_kw)

    def conflict(rule):
        return rule[0] in ("DOMAIN", "DOMAIN-SUFFIX") and covered_by_direct(rule[1])

    removed = [f"{t},{v}" for t, v in groups["proxy"] if conflict((t, v))]
    groups["proxy"] = [x for x in groups["proxy"] if not conflict(x)]
    if removed:
        print(f"  [dedupe] proxy 中 {len(removed)} 条已被直连规则覆盖,已移除:")
        for r in removed:
            print(f"           {r}")

    groups["direct"] = sorted(set(groups["direct"]))

    for name in ("direct", "reject", "proxy"):
        rs = {"version": 3, "rules": to_singbox(groups[name])}
        with open(os.path.join(sb_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(rs, f, ensure_ascii=False, indent=2)
            f.write("\n")
        with open(os.path.join(tx_dir, f"{name}.list"), "w", encoding="utf-8") as f:
            f.write("\n".join(to_text(groups[name])) + "\n")
        n_rules = len(groups[name])
        n_fields = sum(len(v) for v in rs["rules"][0].items()) if rs["rules"] else 0
        print(f"  {name:7} {n_rules:4} 条规则  ->  singbox/{name}.json / text/{name}.list")

    total = sum(len(v) for v in groups.values())
    print(f"\n合计 {total} 条 (原 {len(parsed)} 条,丢弃了进程类和冗余宽规则)")


if __name__ == "__main__":
    main()
