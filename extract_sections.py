import zipfile, xml.etree.ElementTree as ET, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def get_para_text(p):
    return ''.join(r.text for r in p.iter(NS+'t') if r.text)

def read_docx_full(fp):
    with zipfile.ZipFile(fp) as z:
        with z.open('word/document.xml') as f:
            root = ET.parse(f).getroot()
    body = root.find('.//' + NS + 'body')
    blocks = []
    for child in body:
        tag = child.tag.replace(NS, '')
        if tag == 'p':
            t = get_para_text(child)
            blocks.append(('p', t))
        elif tag == 'tbl':
            rows = []
            for row in child.iter(NS+'tr'):
                cells = []
                for cell in row.iter(NS+'tc'):
                    cell_text = ' | '.join(get_para_text(p) for p in cell.iter(NS+'p') if get_para_text(p))
                    cells.append(cell_text)
                rows.append(cells)
            blocks.append(('tbl', rows))
    return blocks

blocks = read_docx_full('C:/Users/ralan/Smartfood/SmartFood_PRD_Intelligence_v3.docx')

def extract_section(blocks, target, next_tag):
    start_i = None
    for i, (btype, bdata) in enumerate(blocks):
        if btype == 'p' and target in bdata:
            start_i = i
            break
    if start_i is None:
        print(f'{target} not found')
        return
    print(f'=== {target} ===')
    for j in range(start_i, min(start_i + 200, len(blocks))):
        bt, bd = blocks[j]
        if bt == 'p':
            if next_tag in bd and j != start_i:
                print(f'--- END: {next_tag} boundary ---')
                break
            print(bd)
        elif bt == 'tbl':
            for row in bd:
                print(' | '.join(row))
    print()

extract_section(blocks, 'E-10', 'E-11')
extract_section(blocks, 'E-11', 'E-12')
