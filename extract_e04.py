import zipfile, xml.etree.ElementTree as ET, sys

sys.stdout = open('e04_full.txt', 'w', encoding='utf-8')

NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def get_para_text(para):
    return ''.join(r.text for r in para.iter(NS+'t') if r.text)

def read_blocks(fp):
    with zipfile.ZipFile(fp, 'r') as z:
        with z.open('word/document.xml') as f:
            root = ET.parse(f).getroot()
    body = root.find('.//' + NS + 'body')
    blocks = []
    for child in body:
        tag = child.tag.replace(NS, '')
        if tag == 'p':
            txt = get_para_text(child)
            if txt:
                blocks.append(('para', txt))
        elif tag == 'tbl':
            rows = []
            for row in child.iter(NS+'tr'):
                cells = []
                for cell in row.iter(NS+'tc'):
                    parts = [get_para_text(p) for p in cell.iter(NS+'p')]
                    cells.append(' | '.join(x for x in parts if x))
                rows.append(' || '.join(cells))
            blocks.append(('table', rows))
    return blocks

blocks = read_blocks('SmartFood_PRD_Intelligence_v3.docx')

in_sec = False
for btype, content in blocks:
    if btype == 'para':
        if 'E-04' in content and not in_sec:
            in_sec = True
        if in_sec and 'E-05' in content and content.strip() != 'E-04':
            break
        if in_sec:
            print(content)
    elif btype == 'table' and in_sec:
        for row in content:
            print('ROW: ' + row)
        print('---TABLE END---')

sys.stdout.close()
