import zipfile, sys, io, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with zipfile.ZipFile('C:/Users/ralan/Smartfood/SmartFood_PRD_Intelligence_v3.docx') as z:
    with z.open('word/document.xml') as f:
        raw = f.read().decode('utf-8')

# Search for E-10 in raw XML
idx = raw.find('E-10')
if idx == -1:
    # Try with hyphen variants
    idx = raw.find('E\u201110')  # em-dash
    print(f'E-10 with em-dash at: {idx}')
else:
    print(f'E-10 found at raw XML position: {idx}')
    print('Context around E-10 (500 chars before and 2000 after):')
    print(raw[max(0,idx-200):idx+2000])
