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

def serialize_project():
    return {'schema_version':1,'series':st.session_state.series,'active':st.session_state.active}

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
                     numeric=name in numeric_columns,
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

with st.sidebar:
    st.header('Progetto')
    st.write(f'Serie già salvate nella sessione: **{len(st.session_state.series)}**')
    st.download_button('Scarica progetto JSON',json.dumps(serialize_project(),indent=2,ensure_ascii=False).encode(),
                       file_name=clean_name(st.session_state.active['name'])+'_progetto.json',mime='application/json',use_container_width=True)
    loaded=st.file_uploader('Riapri un progetto JSON',type=['json'],key='project_upload')
    if loaded is not None and st.button('Carica questo progetto'):
        try:
            obj=json.load(loaded)
            if obj.get('schema_version') != 1 or not isinstance(obj.get('series'),list):
                raise ValueError('Formato del progetto incompatibile')
            st.session_state.series=obj['series'];st.session_state.active=obj['active'];st.rerun()
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
    st.subheader('4. Esporta i risultati')
    export_all=st.checkbox('Esporta anche tutte le serie già aggiunte al progetto',value=False)
    export_rows=list(results)
    if export_all:
        for s in st.session_state.series:export_rows+=s['results']
    exported=pd.DataFrame(export_rows)
    # I campi specifici di altri strumenti restano vuoti, senza impostazioni spurie.
    name=clean_name(c['name'])
    # CSV: numeri esatti riportati con punto; read_csv leggerà le colonne raw come numeri.
    a,b,d=st.columns(3)
    with a:st.download_button('Scarica CSV',csv_bytes(exported),file_name=name+'.csv',mime='text/csv',use_container_width=True)
    with b:st.download_button('Scarica Excel',xlsx_bytes(exported),file_name=name+'.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
    with d:st.download_button('Scarica LaTeX',latex_table(exported,name).encode(),file_name=name+'.tex',mime='text/plain',use_container_width=True)
    st.download_button('Scarica JSON numerico',exported.to_json(orient='records',force_ascii=False,indent=2).encode(),file_name=name+'_risultati.json',mime='application/json')
else:
    st.info('Inserisci almeno un valore per visualizzare i risultati.')

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
