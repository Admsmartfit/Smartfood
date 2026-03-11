import zipfile, xml.etree.ElementTree as ET, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def get_para_text(p):
    return ''.join(r.text for r in p.iter(NS+'t') if r.text)

def flatten_body(element, blocks):
    """Recursively walk body, emitting paragraphs and table rows in document order."""
    for child in element:
        tag = child.tag.replace(NS, '')
        if tag == 'p':
            t = get_para_text(child)
            if t:
                blocks.append(('p', t))
        elif tag == 'tbl':
            # Process table rows
            for row in child.findall('.//' + NS + 'tr'):
                cells = []
                for cell in row.findall(NS + 'tc'):
                    # Collect all paragraph text in cell (may include nested tables)
                    parts = []
                    for p in cell.iter(NS + 'p'):
                        t = get_para_text(p)
                        if t:
                            parts.append(t)
                    cells.append(' / '.join(parts))
                if any(c.strip() for c in cells):
                    blocks.append(('row', cells))
        elif tag == 'body':
            flatten_body(child, blocks)

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

def extract_section(blocks, target, next_tag):
    start_i = None
    for i, (btype, bdata) in enumerate(blocks):
        # Check both paragraphs and table cells for target
        if btype == 'p' and target in bdata:
            start_i = i
            break
        elif btype == 'row':
            for cell in bdata:
                if target in cell:
                    start_i = i
                    break
            if start_i is not None:
                break

    if start_i is None:
        print(f'{target} not found')
        return

    print(f'=== {target} ===')
    for j in range(start_i, min(start_i + 300, len(blocks))):
        bt, bd = blocks[j]
        stop = False
        if bt == 'p':
            if next_tag in bd and j != start_i:
                stop = True
            if not stop:
                print(bd)
        elif bt == 'row':
            for cell in bd:
                if next_tag in cell and j != start_i:
                    stop = True
                    break
            if not stop:
                print(' | '.join(bd))
        if stop:
            print(f'--- END boundary ({next_tag}) ---')
            break
    print()

extract_section(blocks, 'E-10', 'E-11')
extract_section(blocks, 'E-11', 'E-12')
