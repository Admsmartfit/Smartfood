import zipfile
import xml.etree.ElementTree as ET
import sys

sys.stdout.reconfigure(encoding='utf-8')

WNS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def get_para_text(para):
    texts = []
    for run in para.iter(WNS + 't'):
        if run.text:
            texts.append(run.text)
    return ''.join(texts)

def read_docx_full(filepath):
    with zipfile.ZipFile(filepath, 'r') as z:
        with z.open('word/document.xml') as f:
            tree = ET.parse(f)
            root = tree.getroot()
    body = root.find('.//' + WNS + 'body')
    items = []
    for child in body:
        tag = child.tag.replace(WNS, '')
        if tag == 'p':
            t = get_para_text(child)
            if t.strip():
                items.append(('para', t))
        elif tag == 'tbl':
            rows = []
            for row in child.iter(WNS + 'tr'):
                cells = []
                for cell in row.iter(WNS + 'tc'):
                    cell_text = []
                    for para in cell.iter(WNS + 'p'):
                        t = get_para_text(para)
                        if t:
                            cell_text.append(t)
                    cells.append(' | '.join(cell_text))
                rows.append('\t'.join(cells))
            items.append(('table', rows))
    return items

items = read_docx_full('C:/Users/ralan/Smartfood/SmartFood_PRD_Intelligence_v3.docx')

in_section = False
collected = []
for kind, content in items:
    if kind == 'para':
        if 'E-05' in content and not in_section:
            in_section = True
        if in_section and 'E-06' in content and content.strip() != 'E-05':
            break
        if in_section:
            collected.append(content)
    elif kind == 'table' and in_section:
        for row in content:
            collected.append('[ROW] ' + row)

with open('C:/Users/ralan/Smartfood/e05_output.txt', 'w', encoding='utf-8') as out:
    for line in collected:
        out.write(line + '\n')
print('Done, wrote', len(collected), 'lines')
