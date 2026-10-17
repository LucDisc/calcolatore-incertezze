"""Applicazione Streamlit: avvio con streamlit run app.py"""
import io
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
            d['frequenza_Hz']=opt('frequenza_Hz',config['frequency'])
            d['V_div']=opt('V_div',config['v_div']); d['offset_V']=opt('offset_V',config['offset'])
            if config['instrument']=='EDUX1052G' and config['kind'].startswith('Fase'):
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
    buf=io.BytesIO()
    with pd.ExcelWriter(buf,engine='openpyxl') as writer:
        df.to_excel(writer,sheet_name='Risultati',index=False)
    return buf.getvalue()

def latex_escape(s):
    return str(s).replace('\\','\\textbackslash{}').replace('&','\\&').replace('%','\\%').replace('_','\\_').replace('#','\\#')

def latex_table(df, title):
    parts=[r'\begin{table}[htbp]',r'\centering',r'\small',
           r'\caption{'+latex_escape(title)+'}',r'\begin{tabular}{lllll}',r'\toprule',
           r'Serie & Valore & Incertezza & Unit\`a & Portata / V/div \\',r'\midrule']
    for _,r in df.iterrows():
        parts.append(' & '.join(latex_escape(r.get(k,'')) for k in ['serie','value_display','uncertainty_display','unit','range_used'])+r' \\')
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
    if selected=='EDUX1052G' and c['kind']=='Tensione (DC verticale)':
        c['v_div']=st.selectbox('V/div predefinito',OSC_DIVS,index=OSC_DIVS.index(str(c['v_div'])) if str(c['v_div']) in OSC_DIVS else 7)
        c['offset']=st.text_input('Offset predefinito (V)',value=str(c['offset']))
        c['full_scale_divisions']=st.number_input('Divisioni verticali di fondo scala (ipotesi verificabile)',min_value=1,max_value=20,value=int(c['full_scale_divisions']))
        st.warning('Verificare dal manuale il fondo scala effettivo. La formula verticale riguarda l’accuratezza DC, non tutte le misure AC.')
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
    display_cols=['riga','value_display','uncertainty_display','unit','range_used']
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
    st.write('EDUX1052G: il fondo scala verticale è configurabile; l’accuratezza della base tempi non copre tutti i contributi alla misura temporale.')
    st.write('Fase: Δt = fase/(360 f) se la fase è letta; fase = 360 f Δt se si misura il ritardo. '
             'Δt_err = (50 + 5×anni) ppm × |Δt| + 0.0016 × 10 × s/div + 200 ps. '
             'Δfase = 360 sqrt((Δt Δf)^2 + (f Δt_err)^2). '
             'La specifica dei cursori è per lo stesso canale e qui è adottata come stima per CH1/CH2 e fase automatica; '
             'non è inclusa l’incertezza specifica di skew o sonde.')
    st.write('LCR-819: 0.05% è l’accuratezza di base, da validare rispetto al valore e alla frequenza di prova.')
    st.write('La colonna uncertainty_raw contiene il risultato non arrotondato; value_raw è il valore normalizzato numericamente. value_display conserva gli zeri finali inseriti.')
