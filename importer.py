"""Controlli sui dati importati, senza dipendere dall'interfaccia Streamlit.

Evita la perdita silenziosa di colonne e l'uso accidentale di frequenze/s_div
predefinite quando si carica una serie sperimentale.
"""
import re
import unicodedata
import pandas as pd
from engine import dec, MeasurementError

METADATA = ('foto', 'frequenza_nominale_Hz', 'frequenza_letta_osc_Hz',
            'fase_originale_deg', 'fonte_frequenza_nominale')

ALIASES = {
 'valore': 'valore', 'value':'valore', 'misura':'valore', 'valore_misurato':'valore',
 'portata':'portata','range':'portata','frequenza':'frequenza_Hz',
 'frequenza_hz':'frequenza_Hz','frequency':'frequenza_Hz','frequency_hz':'frequenza_Hz',
 'v_div':'V_div','vdiv':'V_div','divisioni':'V_div','scala_verticale':'V_div',
 'offset':'offset_V','offset_v':'offset_V','unita':'unita','unit':'unita',
 's_div':'s_div','sdiv':'s_div','scala_orizzontale':'s_div','tempo_s_div':'s_div',
 'incertezza_f_hz':'incertezza_f_Hz', 'delta_f':'incertezza_f_Hz',
 'foto':'foto','fotografia':'foto','file_foto':'foto',
 'frequenza_nominale_hz':'frequenza_nominale_Hz','f_nominale_hz':'frequenza_nominale_Hz',
 'frequenza_letta_osc_hz':'frequenza_letta_osc_Hz','freq1_hz':'frequenza_letta_osc_Hz',
 'fase_originale_deg':'fase_originale_deg','fase_letta_deg':'fase_originale_deg',
 'fonte_frequenza_nominale':'fonte_frequenza_nominale',
}

def name_key(label):
    label=unicodedata.normalize('NFKD',str(label))
    label=''.join(ch for ch in label if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+','_',label.lower().strip()).strip('_')


def normalize_frame(frame):
    """Rinomina intestazioni note; NON sostituisce arbitrariamente la prima colonna."""
    if frame.empty and len(frame.columns)==0:
        raise ValueError('File vuoto')
    rename={}
    used={}
    for name in frame.columns:
        key=name_key(name)
        canonical=ALIASES.get(key)
        if canonical:
            if canonical in used:
                raise ValueError(f'Colonne duplicate o ambigue: {used[canonical]} e {name}')
            rename[name]=canonical
            used[canonical]=name
    frame=frame.rename(columns=rename)
    if 'valore' not in frame.columns:
        raise ValueError("Non trovo la colonna 'valore'. Usa l'intestazione valore, senza rinominare la prima colonna a caso.")
    return frame


def required_parameters(config):
    ins=config['instrument']; kind=config['kind']
    if ins=='EDUX1052G' and kind.startswith('Fase'):
        return ('frequenza_Hz','s_div')
    if ins=='EDUX1052G' and kind in ('Tensione picco-picco (Vpp)', 'Tensione (DC verticale)'):
        return ('V_div',)
    if (ins=='34460A' and kind=='Tensione AC') or (ins=='AFG-2225' and kind=='Ampiezza Vpp'):
        return ('frequenza_Hz',)
    return ()


def parameter_default(config, key):
    return {'frequenza_Hz':config.get('frequency',''),
            's_div':config.get('s_div',''), 'V_div':config.get('v_div','')}.get(key,'')


def normalize_phase(value):
    """Fase equivalente nell'intervallo [-180,180), calcolata in Decimal."""
    angle=dec(value)
    while angle>=180: angle-=360
    while angle< -180: angle+=360
    return format(angle,'f')


def validate_rows(rows, config, *, allow_defaults=False):
    """Restituisce una lista di errori; non interpreta assenze come valori validi."""
    errors=[]
    needs=required_parameters(config)
    for i,row in enumerate(rows,1):
        value=str(row.get('valore','') or '').strip()
        if not value: continue
        try:
            dec(value)
        except MeasurementError as e:
            errors.append(f'Riga {i}, valore: {e}')
            continue
        for key in needs:
            v=row.get(key,'')
            missing=v is None or str(v).strip().lower() in ('','nan','none')
            if missing and not allow_defaults:
                errors.append(f'Riga {i}: manca {key}. Inseriscilo o autorizza esplicitamente i valori predefiniti.')
                continue
            if missing: v=parameter_default(config,key)
            try:
                numeric=dec(v)
                if numeric<=0: errors.append(f'Riga {i}: {key} deve essere positivo.')
            except MeasurementError as e:
                errors.append(f'Riga {i}, {key}: {e}')
        if config['instrument']=='EDUX1052G' and config['kind'].startswith('Fase'):
            orig=row.get('fase_originale_deg','')
            if orig not in ('', None):
                try:
                    if dec(normalize_phase(orig))!=dec(normalize_phase(value)):
                        errors.append(f'Riga {i}: fase_originale_deg non corrisponde a valore (modulo 360°).')
                except MeasurementError as e:
                    errors.append(f'Riga {i}, fase_originale_deg: {e}')
            f_nom=row.get('frequenza_nominale_Hz','')
            f_val=row.get('frequenza_Hz','')
            if f_nom not in ('',None) and f_val not in ('',None):
                try:
                    if dec(f_nom)!=dec(f_val):
                        errors.append(f'Riga {i}: frequenza_Hz diversa da frequenza_nominale_Hz.')
                except MeasurementError as e:
                    errors.append(f'Riga {i}, frequenza nominale: {e}')
    return errors


def import_frame(frame, config, *, allow_defaults=False):
    frame=normalize_frame(frame)
    permitted=set(('valore','portata','frequenza_Hz','V_div','offset_V',
                   'unita','s_div','incertezza_f_Hz')+METADATA)
    columns=list(frame.columns)
    additional=[c for c in columns if c not in permitted]
    if additional:
        raise ValueError('Colonne sconosciute: '+', '.join(map(str,additional))+'. Rinominale oppure rimuovile prima di importare.')
    if frame.empty:
        raise ValueError('Non sono state trovate righe da importare.')
    rows=[]
    for row in frame.to_dict('records'):
        sanitized={}
        for key,v in row.items():
            sanitized[key]='' if pd.isna(v) else str(v).strip()
        if any(v for v in sanitized.values()): rows.append(sanitized)
    if not rows:
        raise ValueError('Non sono stati trovati valori nel file.')
    problems=validate_rows(rows, config, allow_defaults=allow_defaults)
    if problems:
        raise ValueError('Importazione bloccata: '+ ' | '.join(problems[:7]) +
                         (f' (e altri {len(problems)-7} errori)' if len(problems)>7 else ''))
    return rows
