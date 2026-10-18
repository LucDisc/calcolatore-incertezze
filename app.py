"""Applicazione Streamlit: avvio con streamlit run app.py"""
import io
import zipfile
from xml.etree import ElementTree as ET
import json
import re
from decimal import Decimal
import pandas as pd
import streamlit as st
from engine import KINDS, UNITS, calculate, MeasurementError, DC_V, OHM, AC_V_RANGES, OSC_DIVS

st.set_page_config(page_title='Laboratorio | Incertezze', page_icon='🧪', layout='wide')
st.title('Calcolatore di incertezze strumentali')
st.caption('Cinque strumenti di laboratorio · Accuratezze dei manuali · Dati pronti per Python e Overleaf')

INITIAL={'name':'Misure_esperienza','instrument':'34460A','kind':'Tensione DC','unit':'V','default_range':'auto',
         'frequency':'1000','v_div':'0.5','offset':'0','full_scale_divisions':8,'years':0,
         'include_flatness':True,'digits':4,'s_div':'0.0001', 'frequency_source':'AFG-2225',
         'frequency_uncertainty':'','frequency_years':0,'rows':[{'valore':'0.5330','portata':'','frequenza_Hz':'','V_div':'','offset_V':'','unita':''}]}
if 'series' not in st.session_state:
    st.session_state.series=[]
if 'active' not in st.session_state:
    st.session_state.active=INITIAL.copy()
if 'delete_saved_series' not in st.session_state:
    st.session_state.delete_saved_series=None
if '_pending_project_name' in st.session_state:
    st.session_state.project_name=st.session_state.pop('_pending_project_name')
if 'project_name' not in st.session_state:
    st.session_state.project_name='Misure_esperienza'

def serialize_project():
    return {'schema_version':1,'series':st.session_state.series,'active':st.session_state.active,
            'project_name':st.session_state.project_name}

def clean_name(value):
    return re.sub(r'[^A-Za-z0-9_-]+','_',str(value).strip()).strip('_') or 'misure'

def row_columns(config):
    if config['instrument']=='EDUX1052G':
        if config['kind'].startswith('Fase'):
            return ['valore','s_div','frequenza_Hz','incertezza_f_Hz','unita']
        if config['kind']=='Tensione (DC verticale)':
            return ['valore','V_div','offset_V','unita']
        if config['kind']=='Tensione picco-picco (Vpp)':
            return ['valore','V_div','unita']
        return ['valore','unita']
    if config['instrument']=='34460A':
        return ['valore','portata','frequenza_Hz','unita']
    if config['instrument']=='AFG-2225':
        return ['valore','frequenza_Hz','unita']
    return ['valore','unita']

def dataframe_from_paste(raw, keys=None):
    keys=keys or ['valore','portata','frequenza_Hz','V_div','offset_V','unita']
    raw=raw.strip()
    if not raw: return pd.DataFrame(columns=keys)
    lines=[line for line in raw.splitlines() if line.strip()]
    parsed=[]
    for line in lines:
        pieces=[s.strip() for s in (line.split('\t') if '\t' in line else line.split(';') if ';' in line else line.split())]
        parsed.append(pieces)
    width=max(map(len,parsed))
    if width>len(keys): raise ValueError('Troppi campi: massimo 6 colonne')
    # prima riga facoltativa con intestazioni: si riconoscono i nomi delle colonne
    header=[x.lower().replace(' ','_') for x in parsed[0]]
    known={'valore':'valore','value':'valore','misura':'valore','portata':'portata','range':'portata',
           'frequenza':'frequenza_Hz','frequenza_hz':'frequenza_Hz','frequency':'frequenza_Hz',
           'v/div':'V_div','v_div':'V_div','divisioni':'V_div','offset':'offset_V','offset_v':'offset_V',
           'unità':'unita','unita':'unita','unit':'unita',
           's_div':'s_div','s/div':'s_div','scala_orizzontale':'s_div',
           'incertezza_f_hz':'incertezza_f_Hz','delta_f':'incertezza_f_Hz',
           'incertezza_f':'incertezza_f_Hz'}
    if header and all(h in known for h in header):
        mapping=[known[h] for h in header]
        parsed=parsed[1:]
    else: mapping=keys[:width]
    rows=[]
    for pieces in parsed:
        row=dict.fromkeys(keys,'')
        for key,val in zip(mapping,pieces): row[key]=val
        rows.append(row)
    return pd.DataFrame(rows,columns=keys).fillna('')

def range_with_unit(instrument, kind, raw_range):
    """Testo per esseri umani; il campo range_used rimane numerico nei CSV."""
    if raw_range is None or not str(raw_range).strip():
        return ''
    if instrument != '34460A':
        return str(raw_range)
    value = Decimal(str(raw_range))
    if kind == 'Resistenza':
        if value >= Decimal('1000000'):
            return f"{format((value / Decimal('1000000')).normalize(), 'f')} MΩ"
        if value >= Decimal('1000'):
            return f"{format((value / Decimal('1000')).normalize(), 'f')} kΩ"
        return f"{format(value.normalize(), 'f')} Ω"
    if value < 1:
        return f"{format((value * 1000).normalize(), 'f')} mV"
    return f"{format(value.normalize(), 'f')} V"

def calculate_series(config, rows):
    good=[]; errors=[]
    for i,row in enumerate(rows):
        val=str(row.get('valore','')).strip()
        if not val or val.lower()=='nan': continue
        def opt(key, default):
            v=row.get(key,'')
            return default if v is None or str(v).strip() in ('','nan','None') else str(v).strip()
        try:
            r=calculate(config['instrument'],config['kind'],val,opt('unita',config['unit']),
                    range_used=opt('portata',config['default_range']),
                    frequency=opt('frequenza_Hz',config['frequency']),
                    v_div=opt('V_div',config['v_div']),offset=opt('offset_V',config['offset']),
                    full_scale_divisions=config['full_scale_divisions'],years=config['years'],
                    include_flatness=config['include_flatness'],sig_digits=config['digits'],
                    time_scale=opt('s_div',config.get('s_div','')),
                    frequency_uncertainty=opt('incertezza_f_Hz',config.get('frequency_uncertainty','')),
                    frequency_source=config.get('frequency_source','AFG-2225'),
                    frequency_years=config.get('frequency_years',0))
            d=r.__dict__.copy(); d['serie']=config['name']; d['riga']=i+1
            # Conserviamo il range numerico per Python e una rappresentazione con unità
            # per il controllo visivo e l'esportazione LaTeX.
            d['range_display']=range_with_unit(r.instrument,r.kind,r.range_used)
            # Compiliamo i metadati solo quando pertinenti alla misura selezionata.
            # Le altre celle CSV rimangono vuote (non contengono valori di default fittizi).
            if (config['instrument']=='34460A' and config['kind']=='Tensione AC') or (config['instrument']=='AFG-2225' and config['kind']=='Ampiezza Vpp'):
                d['frequenza_Hz']=opt('frequenza_Hz',config['frequency'])
            if config['instrument']=='EDUX1052G':
                if config['kind'] in ('Tensione (DC verticale)', 'Tensione picco-picco (Vpp)'):
                    d['V_div']=opt('V_div',config['v_div'])
                    if config['kind']=='Tensione (DC verticale)':
                        d['offset_V']=opt('offset_V',config['offset'])
                elif config['kind'].startswith('Fase'):
                    d['s_div']=opt('s_div',config.get('s_div',''))
                    d['frequenza_Hz']=opt('frequenza_Hz',config['frequency'])
                    d['incertezza_f_Hz']=d['frequency_uncertainty_hz']
            good.append(d)
        except (MeasurementError,ValueError) as e:
            errors.append(f"Riga {i+1}, valore {val}: {e}")
    return good,errors

def csv_bytes(df):
    return df.to_csv(index=False,float_format='%.16g').encode('utf-8-sig')

def xlsx_bytes(df):
    """Esporta un XLSX con dati raw NUMERICI e rappresentazioni display TESTUALI.

    Non richiede librerie aggiuntive: i file XLSX sono archivi Open XML.
    Il CSV resta il formato consigliato per preservare integralmente la precisione
    decimale nei programmi Python (Excel usa circa 15 cifre significative numeriche).
    """
    NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    ET.register_namespace('', NS)
    ET.register_namespace('r', REL)
    q = lambda name: '{' + NS + '}' + name

    # I dati *display*, gli identificatori e le formule rimangono testo.
    # Le colonne raw (e i parametri numerici) diventano veri numeri Excel.
    numeric_columns = {
        'value_raw', 'uncertainty_raw', 'range_used', 'riga',
        'frequency_hz', 'frequency_uncertainty_hz', 'time_scale_s_div',
        'time_delay_s', 'time_uncertainty_s', 'frequenza_Hz',
        'incertezza_f_Hz', 'V_div', 'offset_V', 's_div',
    }
    columns = [str(c) for c in df.columns]

    def column_letter(i):
        i += 1
        result = ''
        while i:
            i, remainder = divmod(i - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def put_cell(row, reference, value, *, heading=False, numeric=False, text_format=False):
        if value is None or str(value).strip().lower() in ('', 'nan', 'none', 'nat', '<na>'):
            return
        text = str(value).strip()
        if numeric:
            try:
                number = Decimal(text)
                if number.is_finite():
                    cell = ET.SubElement(row, q('c'), r=reference, s='2')
                    ET.SubElement(cell, q('v')).text = format(number, 'f')
                    return
            except Exception:
                pass
        cell = ET.SubElement(row, q('c'), r=reference, t='inlineStr', s='1' if heading else '3' if text_format else '0')
        item = ET.SubElement(ET.SubElement(cell, q('is')), q('t'))
        item.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        item.text = text

    root = ET.Element(q('worksheet'))
    last_col = column_letter(len(columns) - 1) if columns else 'A'
    end_row = max(len(df) + 1, 1)
    ET.SubElement(root, q('dimension'), ref=f'A1:{last_col}{end_row}')
    sheet_views = ET.SubElement(root, q('sheetViews'))
    view = ET.SubElement(sheet_views, q('sheetView'), workbookViewId='0')
    ET.SubElement(view, q('pane'), ySplit='1', topLeftCell='A2', activePane='bottomLeft', state='frozen')
    ET.SubElement(view, q('selection'), pane='bottomLeft', activeCell='A2', sqref='A2')
    ET.SubElement(root, q('sheetFormatPr'), defaultRowHeight='18')
    widths = ET.SubElement(root, q('cols'))
    for i, name in enumerate(columns, start=1):
        width = 42 if name == 'formula' else 40 if name == 'notes' else min(28, max(14, len(name) + 3))
        ET.SubElement(widths, q('col'), min=str(i), max=str(i), width=str(width), customWidth='1')
    data = ET.SubElement(root, q('sheetData'))
    header = ET.SubElement(data, q('row'), r='1', ht='24', customHeight='1')
    for i, name in enumerate(columns):
        put_cell(header, f'{column_letter(i)}1', name, heading=True)
    for row_index, record in enumerate(df.itertuples(index=False, name=None), start=2):
        row = ET.SubElement(data, q('row'), r=str(row_index))
        for col_index, (name, value) in enumerate(zip(columns, record)):
            put_cell(row, f'{column_letter(col_index)}{row_index}', value,
                     numeric=(name in numeric_columns or name.endswith('__value_raw')
                              or name.endswith('__uncertainty_raw')
                              or name.endswith('__frequency_hz')),
                     text_format=name in {'value_display', 'uncertainty_display', 'input_value'})
    ET.SubElement(root, q('autoFilter'), ref=f'A1:{last_col}{end_row}')
    ET.SubElement(root, q('pageMargins'), left='0.5', right='0.5', top='0.7', bottom='0.7', header='0.3', footer='0.3')

    # Formattazione indipendente da pandas/openpyxl: intestazione, celle numeriche,
    # colonne leggibili e filtri in Excel.
    styles = '''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1"><numFmt numFmtId="164" formatCode="0.################"/></numFmts>
  <fonts count="2">
    <font><sz val="11"/><name val="Aptos"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF243B53"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''
    workbook = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<workbook xmlns="{NS}" xmlns:r="{REL}">'
                f'<sheets><sheet name="Risultati" sheetId="1" r:id="rId1"/></sheets>'
                f'</workbook>')
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    package_rels = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as book:
        book.writestr('[Content_Types].xml', content_types)
        book.writestr('_rels/.rels', package_rels)
        book.writestr('xl/workbook.xml', workbook)
        book.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        book.writestr('xl/styles.xml', styles)
        book.writestr('xl/worksheets/sheet1.xml', ET.tostring(root, encoding='utf-8', xml_declaration=True))
    return buf.getvalue()

def latex_escape(s):
    """Protezione dei nomi della serie nelle celle e nelle caption."""
    return (str(s).replace('\\', r'\textbackslash{}').replace('&', r'\&')
            .replace('%', r'\%').replace('_', r'\_').replace('#', r'\#')
            .replace('{', r'\{').replace('}', r'\}'))

LATEX_UNIT = {
    'V': r'\,\mathrm{V}', 'mV': r'\,\mathrm{mV}', 'uV': r'\,\mu\mathrm{V}',
    'A': r'\,\mathrm{A}', 'mA': r'\,\mathrm{mA}', 'uA': r'\,\mu\mathrm{A}',
    'ohm': r'\,\Omega', 'kohm': r'\,\mathrm{k}\Omega', 'Mohm': r'\,\mathrm{M}\Omega',
    'Ω': r'\,\Omega', 'kΩ': r'\,\mathrm{k}\Omega', 'MΩ': r'\,\mathrm{M}\Omega',
    'F': r'\,\mathrm{F}', 'mF': r'\,\mathrm{mF}', 'uF': r'\,\mu\mathrm{F}',
    'nF': r'\,\mathrm{nF}', 'pF': r'\,\mathrm{pF}',
    'Hz': r'\,\mathrm{Hz}', 'kHz': r'\,\mathrm{kHz}', 'MHz': r'\,\mathrm{MHz}',
    's': r'\,\mathrm{s}', 'ms': r'\,\mathrm{ms}',
    'us': r'\,\mu\mathrm{s}', 'ns': r'\,\mathrm{ns}',
    'Vpp': r'\,\mathrm{V}_{\mathrm{pp}}', 'mVpp': r'\,\mathrm{mV}_{\mathrm{pp}}',
    'deg': r'^{\circ}',
    'V/div': r'\,\mathrm{V/div}', 's/div': r'\,\mathrm{s/div}',
}

def latex_number(s):
    """Converte la notazione scientifica nell'equivalente LaTeX con punti decimali."""
    t=str(s).strip().replace(',','.')
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',t):
        raise ValueError(f'Numero esportabile non valido: {s!r}')
    if 'e' in t.lower():
        mantissa,exponent=re.split('[eE]',t)
        return f'{mantissa}\\times 10^{{{int(exponent)}}}'
    return t

def latex_range(record):
    # In LaTeX le unità sono prodotte con comandi matematici: niente simboli
    # Unicode che potrebbero non essere supportati da pdfLaTeX.
    display=str(record.get('range_display','') or '').strip()
    if not display:
        display=range_with_unit(record.get('instrument',''),record.get('kind',''),record.get('range_used',''))
    if not display:
        return '--'
    match=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s+(mV|V|Ω|kΩ|MΩ|V/div|s/div)',display)
    if match:
        return '$'+latex_number(match.group(1))+LATEX_UNIT[match.group(2)]+'$'
    return latex_escape(display)

def latex_table(df, title):
    parts=[r'\begin{table}[htbp]',r'\centering',r'\small',
           r'\caption{'+latex_escape(title)+'}',r'\begin{tabular}{lll}',r'\toprule',
           r'Serie & Misura ($x \pm \Delta x$) & Portata / scala \\',r'\midrule']
    for _,r in df.iterrows():
        unit=str(r['unit'])
        if unit not in LATEX_UNIT:
            raise ValueError(f'Unità non disponibile per LaTeX: {unit}')
        measure=(r'$('+latex_number(r['value_display'])+r' \pm '
                 +latex_number(r['uncertainty_display'])+r')'+LATEX_UNIT[unit]+'$')
        parts.append(latex_escape(r.get('serie',''))+' & '+measure+' & '+latex_range(r)+r' \\')
    parts += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    return '\n'.join(parts)+'\n'



def xlsx_multiple_sheets(sheets):
    """Usa il generatore XLSX già collaudato anche per più fogli.

    Per mantenere il progetto compatibile con Streamlit gratuito non serve
    alcuna nuova dipendenza. I numeri raw rimangono celle numeric Excel.
    """
    if not sheets:
        raise ValueError('Nessun foglio da esportare')
    NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    names = list(sheets)
    sheet_xml = []
    for frame in sheets.values():
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes(frame))) as single:
            sheet_xml.append(single.read('xl/worksheets/sheet1.xml'))
            styles = single.read('xl/styles.xml')

    sheet_tags = ''.join(
        f'<sheet name="{xml_attribute(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i,name in enumerate(names, start=1)
    )
    workbook = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<workbook xmlns="{NS}" xmlns:r="{REL}">'
                f'<sheets>{sheet_tags}</sheets></workbook>')
    relationships = ''.join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(names)+1)
    )
    workbook_rels = (f'<?xml version="1.0" encoding="UTF-8"?>'
                     f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     f'{relationships}'
                     f'<Relationship Id="rId{len(names)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                     f'</Relationships>')
    content_sheets = ''.join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(names)+1)
    )
    types = (f'<?xml version="1.0" encoding="UTF-8"?>'
             f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             f'<Default Extension="xml" ContentType="application/xml"/>'
             f'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
             f'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
             f'{content_sheets}</Types>')
    package_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                    '</Relationships>')
    out=io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', types)
        z.writestr('_rels/.rels', package_rels)
        z.writestr('xl/workbook.xml', workbook)
        z.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        z.writestr('xl/styles.xml', styles)
        for i,xml in enumerate(sheet_xml, start=1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', xml)
    return out.getvalue()


def xml_attribute(value):
    import html
    return html.escape(str(value), quote=True)


def unique_name(value, used, limit=None):
    """Nomi distinti anche quando due serie hanno lo stesso titolo."""
    initial = clean_name(value)
    if limit is not None:
        initial = initial[:limit]
    candidate = initial
    index = 2
    while candidate.lower() in used:
        suffix = f'_{index}'
        candidate = initial[:limit-len(suffix)] + suffix if limit else initial+suffix
        index += 1
    used.add(candidate.lower())
    return candidate


def summary_by_row(series_dfs, labels):
    """Affianca i dati per numero di riga, MA NON pretende di allinearli
    automaticamente per frequenza: l'ordine delle tre serie va verificato.
    """
    widest = max((len(df) for df in series_dfs), default=0)
    rows=[]
    for i in range(widest):
        row = {'riga': i+1, 'frequenza_Hz': ''}
        for name,df in zip(labels,series_dfs):
            if i >= len(df):
                for field in ('value_raw','uncertainty_raw','value_display','uncertainty_display','unit','range_display'):
                    row[f'{name}__{field}']=''
                continue
            src=df.iloc[i]
            for field in ('value_raw','uncertainty_raw','value_display','uncertainty_display','unit','range_display'):
                item=src.get(field, '')
                row[f'{name}__{field}']='' if pd.isna(item) else item
            f=src.get('frequency_hz','')
            if pd.notna(f) and str(f).strip() and not str(row['frequenza_Hz']).strip():
                row['frequenza_Hz']=str(f)
        rows.append(row)
    return pd.DataFrame(rows)


def series_from_saved(saved):
    """Usa SOLO serie già aggiunte: la serie attiva non viene duplicata."""
    result=[]
    for item in saved:
        data=item.get('results',[])
        if not data:
            continue
        label=str(item.get('config',{}).get('name','Serie'))
        result.append((label,pd.DataFrame(data)))
    return result


def zip_from_files(files):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items():
            z.writestr(name,content)
    return data.getvalue()


def generate_project_exports(saved, project_name, project_json):
    """Tre opzioni di download: separate, complessive e tutto insieme."""
    series=series_from_saved(saved)
    if not series:
        raise ValueError('Aggiungi almeno una serie al progetto')
    prefix=clean_name(project_name)
    used_names=set()
    file_labels=[]
    tables=[]
    for label,df in series:
        file_labels.append(unique_name(label,used_names))
        tables.append(df)
    all_df=pd.concat(tables,ignore_index=True,sort=False)
    # Il riepilogo per riga è utile quando tutte le serie hanno lo stesso ordine.
    # Non effettuiamo accoppiamenti automatici per frequenza in assenza di ID univoci.
    pivot_labels=[]
    taken=set()
    for label in file_labels:
        token=label.split('_')[-1]
        pivot_labels.append(unique_name(token,taken))
    wide=summary_by_row(tables,pivot_labels)

    separate={}
    for label,df in zip(file_labels,tables):
        base=f'Serie_separate/{label}'
        separate[base+'.csv']=csv_bytes(df)
        separate[base+'.xlsx']=xlsx_bytes(df)
        separate[base+'.tex']=latex_table(df,label).encode('utf-8')

    sheet_names={'Riepilogo','Tutte_le_misure'}
    sheets={'Riepilogo':wide}
    for label,df in zip(pivot_labels,tables):
        name=unique_name(label,sheet_names,31)
        sheets[name]=df
    sheets['Tutte_le_misure']=all_df
    complete={
        f'Risultati_completi/{prefix}_completo.csv':csv_bytes(all_df),
        f'Risultati_completi/{prefix}_riepilogo_per_riga.csv':csv_bytes(wide),
        f'Risultati_completi/{prefix}_completo.xlsx':xlsx_multiple_sheets(sheets),
        f'Risultati_completi/{prefix}_completo.tex':('\n\n'.join(latex_table(df,label) for label,df in zip(file_labels,tables))).encode('utf-8')
    }
    full=dict(separate)
    full.update(complete)
    full[f'{prefix}_progetto.json']=project_json
    readme=(f'Progetto: {project_name}\n'
            f'Serie salvate: {len(series)}\n'
            f'Numero totale di misure: {len(all_df)}\n\n'
            'Serie_separate/: CSV, XLSX e LaTeX per ogni serie.\n'
            'Risultati_completi/: CSV lungo, riepilogo CSV per riga, Excel a piu fogli e LaTeX con tutte le tabelle.\n'
            'Il riepilogo associa Vin, Vout e Fase per POSIZIONE NELLA SERIE (riga 1 con riga 1, ecc.).\n'
            'Controllare che le serie siano nello stesso ordine e riferite alle stesse frequenze.\n'
            'value_raw e uncertainty_raw sono numeri per i calcoli; *_display preservano gli zeri finali.\n'
            'Il LaTeX usa sempre il punto decimale.\n').encode('utf-8')
    full['ISTRUZIONI.txt']=readme
    complete['ISTRUZIONI.txt']=readme
    return {
        'separate':zip_from_files(separate),
        'combined':zip_from_files(complete),
        'all':zip_from_files(full),
        'n_series':len(series),
        'n_measurements':len(all_df),
        'lengths':[len(df) for df in tables],
        'pivot':wide,
    }

with st.sidebar:
    st.header('Progetto')
    st.text_input('Nome generale del progetto (per i download complessivi)',
                  key='project_name')
    st.write(f'Serie già salvate nella sessione: **{len(st.session_state.series)}**')
    if st.session_state.series:
        with st.expander('Gestisci le serie salvate', expanded=True):
            st.caption('Puoi eliminare una sola serie senza cancellare le altre.')
            for index, saved in enumerate(st.session_state.series):
                saved_name = str(saved.get('config', {}).get('name', f'Serie {index + 1}'))
                if st.button(f'Elimina {index + 1}: {saved_name}',
                             key=f'remove_saved_series_{index}', use_container_width=True):
                    st.session_state.delete_saved_series=index
                    st.rerun()
            index=st.session_state.delete_saved_series
            if isinstance(index,int) and 0 <= index < len(st.session_state.series):
                saved_name=str(st.session_state.series[index].get('config', {}).get('name', f'Serie {index + 1}'))
                st.warning(f'Confermi di eliminare la serie «{saved_name}»?')
                confirm, cancel=st.columns(2)
                with confirm:
                    if st.button('Conferma', key='confirm_remove_saved_series',
                                 type='primary', use_container_width=True):
                        st.session_state.series.pop(index)
                        st.session_state.delete_saved_series=None
                        st.rerun()
                with cancel:
                    if st.button('Annulla', key='cancel_remove_saved_series',
                                 use_container_width=True):
                        st.session_state.delete_saved_series=None
                        st.rerun()
            st.caption('Dopo le modifiche, scarica nuovamente il progetto JSON.')
    st.download_button('Scarica progetto JSON',json.dumps(serialize_project(),indent=2,ensure_ascii=False).encode(),
                       file_name=clean_name(st.session_state.project_name)+'_progetto.json',mime='application/json',use_container_width=True)
    loaded=st.file_uploader('Riapri un progetto JSON',type=['json'],key='project_upload')
    if loaded is not None and st.button('Carica questo progetto'):
        try:
            obj=json.load(loaded)
            if obj.get('schema_version') != 1 or not isinstance(obj.get('series'),list):
                raise ValueError('Formato del progetto incompatibile')
            st.session_state.series=obj['series'];st.session_state.active=obj['active']
            st.session_state._pending_project_name=obj.get(
                'project_name',st.session_state.active.get('name','Misure_esperienza'))
            st.session_state.delete_saved_series=None
            st.rerun()
        except (ValueError,KeyError,TypeError) as e: st.error(str(e))
    st.info('Il progetto va scaricato per conservarlo: il server gratuito non è un archivio permanente.')

c=st.session_state.active
st.subheader('1. Configura la serie')
col1,col2,col3=st.columns(3)
with col1:
    c['name']=st.text_input('Nome della serie / dei file',value=c['name'])
    inst=list(KINDS)
    selected=st.selectbox('Strumento',inst,index=inst.index(c['instrument']),format_func=lambda x: {'34460A':'Keysight Truevolt 34460A','EDUX1052G':'Keysight EDUX1052G','GPE-4323':'GW Instek GPE-4323','AFG-2225':'GW Instek AFG-2225','LCR-819':'GW Instek LCR-819'}[x])
    if selected!=c['instrument']:
        c['instrument']=selected;c['kind']=next(iter(KINDS[selected]));c['unit']=KINDS[selected][c['kind']]
    choices=list(KINDS[selected]);c['kind']=st.selectbox('Tipo di misura',choices,index=choices.index(c['kind']) if c['kind'] in choices else 0)
with col2:
    units=UNITS[KINDS[selected][c['kind']]]
    c['unit']=st.selectbox('Unità predefinita',units,index=units.index(c['unit']) if c['unit'] in units else 0)
    applicable = selected=='34460A'
    if applicable:
        portate=DC_V if c['kind']=='Tensione DC' else OHM if c['kind']=='Resistenza' else AC_V_RANGES
        opts=['auto']+[str(p[0] if isinstance(p,tuple) else p) for p in portate]
        c['default_range']=st.selectbox('Portata predefinita (unità base)',opts,index=opts.index(c['default_range']) if c['default_range'] in opts else 0)
    c['digits']=st.selectbox('Cifre significative incertezza visualizzata',[3,4,5,6,7,8],index=[3,4,5,6,7,8].index(c['digits']) if c['digits'] in [3,4,5,6,7,8] else 1)
with col3:
    if (selected=='34460A' and c['kind']=='Tensione AC') or (selected=='AFG-2225' and c['kind']=='Ampiezza Vpp') or (selected=='EDUX1052G' and c['kind'].startswith('Fase')):
        c['frequency']=st.text_input('Frequenza predefinita (Hz)',value=str(c['frequency']))
    if selected=='EDUX1052G' and c['kind'] in ('Tensione (DC verticale)', 'Tensione picco-picco (Vpp)'):
        c['v_div']=st.selectbox('V/div predefinito',OSC_DIVS,index=OSC_DIVS.index(str(c['v_div'])) if str(c['v_div']) in OSC_DIVS else 7,
                                format_func=lambda x: f'{x} V/div')
        if c['kind']=='Tensione (DC verticale)':
            c['offset']=st.text_input('Offset predefinito (V)',value=str(c['offset']))
            c['full_scale_divisions']=st.number_input('Divisioni verticali di fondo scala (ipotesi verificabile)',min_value=1,max_value=20,value=int(c['full_scale_divisions']))
            st.warning('Verificare dal manuale il fondo scala effettivo. La formula verticale riguarda l’accuratezza DC, non tutte le misure AC.')
        else:
            st.info('Vpp: stima concordata dal SOLO guadagno verticale: 3% di (8 × V/div) '
                    'se scala >= 10 mV/div, altrimenti 4%. Non è una specifica di accuratezza '
                    'della misura automatica Vpp. Offset, rumore e sonde non compresi.')
    if selected=='EDUX1052G' or selected=='AFG-2225':
        c['years']=st.number_input('Anni per contributo aging (0 = escluso)',min_value=0,max_value=50,value=int(c['years']))
    if selected=='AFG-2225' and c['kind']=='Ampiezza Vpp':
        c['include_flatness']=st.checkbox('Includi flatness fuori da 1 kHz (somma conservativa)',value=bool(c['include_flatness']))

TIME_SCALES=sorted({format(Decimal(k)*Decimal(10)**exponent,'f')
                    for exponent in range(-9,2) for k in (1,2,5)
                    if Decimal('0.000000005') <= Decimal(k)*Decimal(10)**exponent <= Decimal(50)},
                   key=Decimal)
def human_time_scale(s):
    v=Decimal(s)
    if v < Decimal('0.000001'): return f'{format(v*Decimal(1000000000),"f")} ns/div'
    if v < Decimal('0.001'): return f'{format(v*Decimal(1000000),"f")} µs/div'
    if v < Decimal('1'): return f'{format(v*Decimal(1000),"f")} ms/div'
    return f'{format(v,"f")} s/div'

if selected=='EDUX1052G' and c['kind'].startswith('Fase'):
    st.info('Fase letta: inserisci i gradi mostrati dall’oscilloscopio. Fase da ritardo: inserisci Δt (s, ms, µs o ns). '
            'Per entrambi i metodi, la formula dei cursori dello stesso canale viene usata come STIMA '
            'dell’incertezza temporale, anche per CH1/CH2 o fase automatica.')
    left_settings,right_settings=st.columns(2)
    with left_settings:
        old_scale=str(c.get('s_div','0.0001'))
        possible_scales=TIME_SCALES + ['personalizzata']
        chosen_scale=st.selectbox('Scala orizzontale predefinita',possible_scales,
            index=possible_scales.index(old_scale) if old_scale in TIME_SCALES else len(TIME_SCALES),
            format_func=lambda v: 'Scala personalizzata (s/div)' if v=='personalizzata' else human_time_scale(v),
            help='La scala è modificabile individualmente per riga nella colonna s_div (in secondi per divisione).')
        if chosen_scale=='personalizzata':
            c['s_div']=st.text_input('Scala personalizzata (s/div)',value=old_scale)
        else:
            c['s_div']=chosen_scale
    with right_settings:
        c['frequency_source']=st.selectbox('Provenienza dell’incertezza sulla frequenza',
                                         ['AFG-2225','manuale'],
                                         index=['AFG-2225','manuale'].index(c.get('frequency_source','AFG-2225')))
    if c['frequency_source']=='AFG-2225':
        c['frequency_years']=st.number_input('Anni di aging del generatore (0 = escluso)',min_value=0,max_value=50,
                                              value=int(c.get('frequency_years',0)))
    else:
        c['frequency_uncertainty']=st.text_input('Incertezza predefinita sulla frequenza (Hz)',
                                                  value=str(c.get('frequency_uncertainty','')),
                                                  help='Inserire l’incertezza assoluta, non in ppm. Modificabile per riga.')
    st.caption('Per entrambe le modalità si usa Δφ = 360 sqrt((Δt Δf)^2 + (f Δt_err)^2). '
               'L’uso della propagazione in quadratura presuppone contributi indipendenti; '
               'lo skew tra canali e sonde non è coperto.')

st.subheader('2. Inserisci i valori')
st.write('Puoi incollare una colonna di Excel oppure più colonne separate da TAB. Nell’editor puoi cambiare **portata, frequenza, s/div, V/div, offset e unità singolarmente**. I campi vuoti usano i valori predefiniti.')
columns=row_columns(c)
left,right=st.columns([2,1])
with left:
    paste=st.text_area('Incolla celle copiate da Excel / Google Fogli',height=120,placeholder='0.5330\n0.9930\n1.4820',key='paste_values')
    if st.button('Aggiungi i valori incollati'):
        try:
            add=dataframe_from_paste(paste,columns).to_dict('records')
            c['rows']+=add
            st.success(f'Aggiunte {len(add)} righe.')
        except Exception as e: st.error(f'Importazione: {e}')
with right:
    upload=st.file_uploader('Oppure carica CSV / Excel',type=['csv','xlsx'])
    if upload is not None and st.button('Aggiungi file'):
        try:
            if upload.name.lower().endswith('.xlsx'):
                dat=pd.read_excel(upload,dtype=str).fillna('')
            else:
                dat=pd.read_csv(upload,dtype=str,sep=None,engine='python').fillna('')
            keys=columns
            if not 'valore' in dat.columns:
                dat=dat.rename(columns={dat.columns[0]:'valore'})
            c['rows']+=dat.reindex(columns=keys,fill_value='').to_dict('records')
            st.success(f'Aggiunte {len(dat)} righe.')
        except Exception as e: st.error(f'File non leggibile: {e}')
editor_df=pd.DataFrame(c['rows']).reindex(columns=columns,fill_value='').fillna('').astype(str)
edited=st.data_editor(editor_df,num_rows='dynamic',hide_index=False,use_container_width=True,key='editor',
                      column_config={key:st.column_config.TextColumn(key,help='Lasciare vuoto per usare impostazione predefinita') for key in columns})
c['rows']=edited.fillna('').to_dict('records')
if st.button('Svuota la tabella'):
    c['rows']=[];st.rerun()

st.subheader('3. Calcola e verifica')
results,errors=calculate_series(c,c['rows'])
if errors:
    st.error('Alcune righe non possono essere calcolate:')
    for e in errors: st.write('• '+e)
if results:
    view=pd.DataFrame(results)
    display_cols=['riga','value_display','uncertainty_display','unit','range_display']
    if selected=='EDUX1052G' and c['kind'].startswith('Fase'):
        display_cols += ['frequency_hz','frequency_uncertainty_hz',
                         'time_delay_s','time_uncertainty_s']
    display_cols += ['formula','notes']
    st.dataframe(view[display_cols],hide_index=True,use_container_width=True)
    st.caption('Incertezze visualizzate con le cifre significative selezionate. I file CSV, Excel e JSON conservano anche le incertezze non arrotondate. Il valore di accuratezza non è automaticamente una deviazione standard.')
    if st.button('Aggiungi questa serie al progetto'):
        st.session_state.series.append({'config':dict(c),'results':results})
        st.success('Serie aggiunta al progetto. Scarica il JSON per conservarla.')
    with st.expander('Esporta solo la serie attualmente visualizzata'):
        current=pd.DataFrame(results)
        current_name=clean_name(c['name'])
        ax,bx,cx=st.columns(3)
        with ax:
            st.download_button('CSV attuale', csv_bytes(current),file_name=current_name+'.csv',mime='text/csv',use_container_width=True)
        with bx:
            st.download_button('Excel attuale',xlsx_bytes(current),file_name=current_name+'.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
        with cx:
            st.download_button('LaTeX attuale',latex_table(current,current_name).encode('utf-8'),file_name=current_name+'.tex',mime='text/plain',use_container_width=True)
else:
    st.info('Inserisci almeno un valore per visualizzare i risultati.')

st.subheader('4. Esporta il progetto')
if st.session_state.series:
    st.caption('I download del progetto usano SOLO le serie salvate nella barra laterale, mai la serie attiva non salvata.')
    try:
        project_payload=json.dumps(serialize_project(),indent=2,ensure_ascii=False).encode('utf-8')
        exports=generate_project_exports(st.session_state.series,st.session_state.project_name,project_payload)
        st.write(f"**{exports['n_series']} serie salvate, {exports['n_measurements']} misure totali.**")
        if len(set(exports['lengths']))>1:
            st.warning('Le serie hanno numeri di righe diversi: il foglio Riepilogo le affianca per posizione, non per frequenza. Controlla gli abbinamenti.')
        else:
            st.info('Nel foglio Riepilogo le misure sono affiancate PER ORDINE DI RIGA. Controlla che le serie siano ordinate secondo le stesse frequenze.')
        prefix=clean_name(st.session_state.project_name)
        x,y,z=st.columns(3)
        with x:
            st.download_button('Scarica serie separate (ZIP)',exports['separate'],
                file_name=prefix+'_serie_separate.zip',mime='application/zip',use_container_width=True)
        with y:
            st.download_button('Scarica risultati complessivi (ZIP)',exports['combined'],
                file_name=prefix+'_risultati_completi.zip',mime='application/zip',use_container_width=True)
        with z:
            st.download_button('Scarica tutto (ZIP)',exports['all'],
                file_name=prefix+'_TUTTO.zip',mime='application/zip',use_container_width=True,type='primary')
        st.caption('Il pacchetto completo contiene CSV, XLSX e LaTeX separati per serie, gli equivalenti complessivi e il progetto JSON. Nessuna serie è duplicata.')
    except Exception as e:
        st.error(f'Impossibile creare l’archivio: {e}')
else:
    st.info('Aggiungi una serie al progetto per attivare gli archivi con file separati e complessivi. La serie corrente può essere scaricata dal riquadro sopra.')

with st.expander('Informazioni sulle formule e sulle limitazioni'):
    st.write('Le specifiche derivano dalle tabelle dei manuali fornite per questa esperienza. Il programma non certifica condizioni operative non documentate.')
    st.write('AFG-2225: l’ampiezza a 1 kHz e la flatness fuori da 1 kHz sono combinate con una somma conservativa facoltativa; serve verificare carico e altre condizioni del manuale.')
    st.write('EDUX1052G: per la tensione DC il fondo scala verticale è configurabile; l’accuratezza della base tempi non copre tutti i contributi alla misura temporale.')
    st.write('EDUX1052G Vpp: stima ΔVpp = (0.03 se V/div >= 0.010, altrimenti 0.04) × 8 × V/div. '
             'Usa soltanto DC vertical gain accuracy una volta; NON è una specifica ufficiale di accuracy Vpp. '
             'Gli errori da rumore, sonde e algoritmo di misura dei picchi non sono inclusi.')
    st.write('Fase: Δt = fase/(360 f) se la fase è letta; fase = 360 f Δt se si misura il ritardo. '
             'Δt_err = (50 + 5×anni) ppm × |Δt| + 0.0016 × 10 × s/div + 200 ps. '
             'Δfase = 360 sqrt((Δt Δf)^2 + (f Δt_err)^2). '
             'La specifica dei cursori è per lo stesso canale e qui è adottata come stima per CH1/CH2 e fase automatica; '
             'non è inclusa l’incertezza specifica di skew o sonde.')
    st.write('LCR-819: 0.05% è l’accuratezza di base, da validare rispetto al valore e alla frequenza di prova.')
    st.write('La colonna uncertainty_raw contiene il risultato non arrotondato; value_raw è il valore normalizzato numericamente. value_display conserva gli zeri finali inseriti.')
