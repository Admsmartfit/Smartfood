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

# Print blocks 0-30 to see what surrounds E-10
print('=== BLOCKS 0-30 (full backlog table context) ===')
for i in range(min(30, len(blocks))):
    bt, bd = blocks[i]
    if bt == 'p':
        print(f'[{i}][p] {bd}')
    else:
        print(f'[{i}][row] {" | ".join(bd)}')

# Also look for any E-10 detail section (maybe labeled differently)
print('\n=== SEARCHING FOR ETAPA E-10 or detailed NF-e XML section ===')
for i, (bt, bd) in enumerate(blocks):
    text = bd if bt == 'p' else ' | '.join(bd)
    if 'NF-e' in text or 'Balança' in text or 'ETAPA E-10' in text or 'Recebimento com Balan' in text:
        print(f'[{i}][{bt}] {text}')
