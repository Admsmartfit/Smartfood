import zipfile, xml.etree.ElementTree as ET, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def get_para_text(p):
    return ''.join(r.text for r in p.iter(NS+'t') if r.text)

with zipfile.ZipFile('C:/Users/ralan/Smartfood/SmartFood_PRD_Intelligence_v3.docx') as z:
    with z.open('word/document.xml') as f:
        root = ET.parse(f).getroot()

body = root.find('.//' + NS + 'body')
blocks = []
for child in body:
    tag = child.tag.replace(NS, '')
    if tag == 'p':
        t = get_para_text(child)
        if t:
            blocks.append(('p', t))
    elif tag == 'tbl':
        for row in child.iter(NS + 'tr'):
            cells = []
            for cell in row.findall(NS + 'tc'):
                parts = []
                for p in cell.iter(NS + 'p'):
                    t = get_para_text(p)
                    if t:
                        parts.append(t)
                cells.append(' / '.join(parts))
            if any(c.strip() for c in cells):
                blocks.append(('row', cells))

# Print ALL blocks that contain E-10 or E-11
print('=== ALL OCCURRENCES OF E-10 AND E-11 ===\n')
for i, (bt, bd) in enumerate(blocks):
    text = bd if bt == 'p' else ' | '.join(bd)
    if 'E-10' in text or 'E-11' in text:
        print(f'[block {i}][{bt}] {text}')

print('\n=== TOTAL BLOCKS:', len(blocks), '===')

# Now find the dedicated section headers for E-10 and E-11
# E-10 detailed section
print('\n\n=== DETAILED E-10 SECTION ===')
e10_starts = []
for i, (bt, bd) in enumerate(blocks):
    text = bd if bt == 'p' else ' | '.join(bd)
    if 'E-10' in text and ('Recebimento' in text or 'Balança' in text or 'NF-e' in text or 'E-10.' in text):
        e10_starts.append(i)

print(f'E-10 detailed section candidates at blocks: {e10_starts}')
for si in e10_starts:
    print(f'\n--- Candidate start block {si} ---')
    for j in range(si, min(si+150, len(blocks))):
        bt, bd = blocks[j]
        text = bd if bt == 'p' else ' | '.join(bd)
        # Stop at E-11 heading but not at E-11 references inside E-10
        if j != si and ('E-11' in text) and ('E-11.' in text or 'Ordens de Produção' in text):
            print(f'  [STOP at block {j}]')
            break
        if bt == 'p':
            print(bd)
        else:
            print(' | '.join(bd))

print('\n\n=== DETAILED E-11 SECTION ===')
e11_starts = []
for i, (bt, bd) in enumerate(blocks):
    text = bd if bt == 'p' else ' | '.join(bd)
    if 'E-11.' in text or ('E-11' in text and 'Ordens de Produção' in text and bt == 'p'):
        e11_starts.append(i)

print(f'E-11 detailed section candidates at blocks: {e11_starts}')
for si in e11_starts:
    print(f'\n--- Candidate start block {si} ---')
    for j in range(si, min(si+200, len(blocks))):
        bt, bd = blocks[j]
        text = bd if bt == 'p' else ' | '.join(bd)
        if j != si and ('E-12' in text):
            print(f'  [STOP at block {j}: E-12 found]')
            break
        if bt == 'p':
            print(bd)
        else:
            print(' | '.join(bd))
