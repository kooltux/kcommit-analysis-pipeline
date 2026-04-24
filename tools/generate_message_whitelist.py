#!/usr/bin/env python3
# Generate rules//message_whitelist.txt from a module-list style input file.
import argparse
import collections
import os
import re

STOP = {
    'add','added','fix','fixed','merge','remove','removed','update','updated','use','using','allow','make','move','rename','convert','drop','dont','do','introduce','expand','fold','kill','annotate','optimize','provide','teach','change','set','take','unify','replace','clean','cleanup','build','disable','enable','accept','prevent','return','split','simplify','reset','restore','print','mark','validate','export','extract','construct','create','delete','lift','pass','raise','force','automate','abort'
}
COMMON_BAD = {
    'the','and','for','with','from','into','next','branch','tag','of','git','https','http','linux','kernel','driver','drivers','tools','selftests','samples','documentation','maintainers','patch','patches'
}
PREFERRED = [
    'net','can','ethernet','phy','phylib','phylink','mdio','ethtool','ipv4','ipv6','tcp','udp','tls','xfrm','vlan',
    'bluetooth','wifi','wireless','cfg80211','mac80211','nl80211',
    'usb','pci','tty','serial','i2c','spi','pinctrl','gpio','irqchip','clk','regulator','thermal','watchdog','pm','cpufreq','cpuidle',
    'mmc','ufs','mtd','block','ext4','f2fs','ubifs','nvdimm','dm','scsi','nvme','iommu',
    'crypto','security','keys','integrity','selinux','apparmor','kasan','ubsan','fortify',
    'arm','arm64','dt','dt-bindings','devicetree','of'
]


def extract_tokens(text):
    # Extract candidate first-token prefixes from free-form module-list content.
    raw_tokens = re.findall(r'(?<![A-Za-z0-9_./-])([A-Za-z][A-Za-z0-9_+.-]{1,40})(?=\s|:)', text)
    counts = collections.Counter()
    for tok in raw_tokens:
        t = tok.strip().strip('.,').lower()
        if len(t) < 2 or t in STOP or t in COMMON_BAD:
            continue
        if re.fullmatch(r'v?\d+(?:[.-]\d+)*', t):
            continue
        counts[t] += 1
    return counts


def build_prefix_list(counts, limit=80):
    # Prefer known TCU-relevant prefixes, then fill with frequent tokens from the input list.
    final = []
    seen = set()
    for tok in PREFERRED:
        if tok in counts or tok in {'net','can','usb','pci','arm64','crypto','security','mmc','ext4','thermal','watchdog','pm','bluetooth','wireless','dt-bindings','of'}:
            final.append(tok)
            seen.add(tok)
    for tok, c in counts.most_common(200):
        if tok not in seen and c >= 2 and re.match(r'^[a-z][a-z0-9+.-]*$', tok):
            final.append(tok)
            seen.add(tok)
        if len(final) >= limit:
            break
    return final


def write_whitelist(path, prefixes):
    # Emit exact-text markers, first-token regexes, and a few nested-prefix examples.
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# Generated from module-list content: each line aims to match the first word(s) in a git commit subject\n')
        f.write('# Exact text markers\n')
        f.write('Fixes:\n')
        f.write('Cc: stable@\n\n')
        f.write('# First-word prefix regex examples\n')
        for tok in prefixes:
            f.write('re:^%s(?:\\s|:|$)\n' % re.escape(tok))
        f.write('\n# Nested-prefix examples\n')
        f.write('re:^net:\\s*(phy|ipv4|ipv6|tls|xfrm|qrtr)(?:\\s|:|$)\n')
        f.write('re:^staging:\\s*[^:]+:\\s*\n')
        f.write('re:^dt-bindings:\\s*[^:]+:\\s*\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--module-list', required=True, help='Input text file used to derive likely commit-subject prefixes')
    ap.add_argument('--output', default='rules//message_whitelist.txt', help='Whitelist file to generate')
    ap.add_argument('--limit', type=int, default=80, help='Maximum number of first-token regex entries to emit')
    args = ap.parse_args()

    with open(args.module_list, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()
    counts = extract_tokens(text)
    prefixes = build_prefix_list(counts, limit=args.limit)
    outdir = os.path.dirname(args.output)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    write_whitelist(args.output, prefixes)
    print('generated', args.output)
    print('prefix_count', len(prefixes))
    print('sample', ', '.join(prefixes[:20]))


if __name__ == '__main__':
    main()
