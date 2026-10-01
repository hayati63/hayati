import re, sys
src = open(sys.argv[1], encoding='utf-8').read()
out = []
for line in src.splitlines():
    s = line
    if re.match(r'\s*#property', s): continue
    if re.match(r'\s*#include\s*<Trade', s): s = '#include "mql5_stub.h"'
    if re.match(r'\s*input\s+group', s): continue
    s = re.sub(r'^(\s*)input\s+', r'\1const ', s)
    # dynamic array params:  T &name[]  -> std::vector<T> &name
    s = re.sub(r'(\b[A-Za-z_]\w*)\s*&\s*(\w+)\[\]', r'std::vector<\1> &\2', s)
    # dynamic array declarations (possibly several names):  T a[], b[];
    m = re.match(r'^(\s*)([A-Za-z_]\w*)\s+((?:\w+\[\]\s*,\s*)*\w+\[\])\s*;(.*)$', s)
    if m:
        names = [n.strip()[:-2] for n in m.group(3).split(',')]
        s = m.group(1) + 'std::vector<%s> %s;%s' % (m.group(2), ', '.join(names), m.group(4))
    out.append(s)
code = '\n'.join(out)
# MQL5 allows string arrays passed to StringSplit etc. -- fine with vectors
open(sys.argv[2], 'w').write(code + '\nstring _Symbol; double _Point; int _Digits;\n')
