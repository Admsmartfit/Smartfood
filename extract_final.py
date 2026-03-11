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

def print_blocks(start, end):
    for i in range(start, min(end, len(blocks))):
        bt, bd = blocks[i]
        if bt == 'p':
            print(bd)
        else:
            print(' | '.join(bd))

print('=' * 80)
print('SECTION E-10: Recebimento com Balança e Validação de NF-e XML')
print('=' * 80)
print()
print('[From the document index table — block 16]')
print('E-10 | Recebimento com Balança e Validação de NF-e XML | P1 — Alta | Sprint 3')
print()
print('[NOTE: No dedicated "ETAPA E-10" expanded section exists in this document.')
print(' E-10 is listed in the Sprint index table only. Relevant NF-e receipt')
print(' functionality appears as part of ETAPA E-07 (blocks 139–160).]')
print()
print('[ETAPA E-07 cross-reference content mentioning NF-e/Balança:]')
print_blocks(139, 174)

print()
print('=' * 80)
print('SECTION E-11: Ordens de Produção e Consumo de Insumos')
print('=' * 80)
print()
# E-11 ETAPA heading is block 174, content runs to block 187 (E-12)
print_blocks(174, 188)

print()
print('=' * 80)
print('USER STORIES referencing E-11 (from US table):')
print('=' * 80)
print_blocks(233, 235)
