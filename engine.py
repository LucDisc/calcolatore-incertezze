"""Motore indipendente per le accuratezze strumentali del laboratorio.

I risultati sono limiti di accuratezza del costruttore, non deviazioni standard.
Coefficienti trascritti dalle tabelle fornite per questa esperienza.
"""
from decimal import Decimal, InvalidOperation, localcontext
from dataclasses import dataclass, asdict
from typing import Optional

D = lambda x: Decimal(str(x))

class MeasurementError(ValueError):
    pass

def dec(value):
    s = str(value).strip().replace('−', '-').replace('µ', 'u')
    if not s or s.lower() in ('nan', 'none', '<na>'):
        raise MeasurementError('Valore numerico mancante')
    if ',' in s and '.' in s:
        raise MeasurementError('Numero ambiguo: usare il punto decimale')
    if ',' in s:
        s = s.replace(',', '.')  # solo per copia/incolla di Excel localizzato
    try:
        result = D(s)
    except InvalidOperation:
        raise MeasurementError(f'Numero non valido: {value}')
    if not result.is_finite():
        raise MeasurementError('Il numero deve essere finito')
    return result

UNIT_SCALE = {
    'V': ('V','1'), 'mV': ('V','0.001'), 'uV': ('V','0.000001'),
    'A': ('A','1'), 'mA': ('A','0.001'), 'uA': ('A','0.000001'),
    'ohm': ('ohm','1'), 'kohm': ('ohm','1000'), 'Mohm': ('ohm','1000000'),
    'F': ('F','1'), 'mF': ('F','0.001'), 'uF': ('F','0.000001'), 'nF': ('F','0.000000001'), 'pF': ('F','0.000000000001'),
    'Hz': ('Hz','1'), 'kHz': ('Hz','1000'), 'MHz': ('Hz','1000000'),
    'deg': ('deg','1'),
    's': ('s','1'), 'ms': ('s','0.001'), 'us': ('s','0.000001'), 'ns': ('s','0.000000001'),
    'Vpp': ('Vpp','1'), 'mVpp': ('Vpp','0.001'),
}
KINDS = {
    '34460A': {'Tensione DC':'V', 'Tensione AC':'V', 'Resistenza':'ohm'},
    'EDUX1052G': {'Tensione (DC verticale)':'V', 'Intervallo temporale':'s',
                   'Fase letta (gradi)':'deg', 'Fase da ritardo':'s'},
    'GPE-4323': {'Tensione impostata':'V', 'Tensione letta':'V', 'Corrente impostata':'A', 'Corrente letta':'A'},
    'AFG-2225': {'Frequenza generata':'Hz', 'Ampiezza Vpp':'Vpp'},
    'LCR-819': {'Capacità':'F'}
}
UNITS = {k: [u for u, (base,_) in UNIT_SCALE.items() if base==k] for k in ('V','A','ohm','F','Hz','s','Vpp','deg')}
DC_V = [('0.1','0.0115','0.0065'),('1','0.0105','0.0010'),('10','0.0100','0.0005'),('100','0.0110','0.0006'),('1000','0.0110','0.0010')]
OHM = [('100','0.017','0.0070'),('1000','0.017','0.0010'),('10000','0.017','0.0010'),('100000','0.017','0.0010'),('1000000','0.017','0.0010'),('10000000','0.060','0.0010'),('100000000','0.800','0.0100')]
AC_V_RANGES = ['0.1','1','10','100','750']
AC_BANDS = [('3','5','1.00','0.03'),('5','10','0.38','0.03'),('10','20000','0.10','0.03'),('20000','50000','0.16','0.05'),('50000','100000','0.63','0.08'),('100000','300000','4.00','0.50')]
OSC_DIVS = ['0.002','0.005','0.01','0.02','0.05','0.1','0.2','0.5','1','2','5','10','20']

def choose_range(magnitude, allowed, user_range=None):
    choices = [D(row[0] if isinstance(row,tuple) else row) for row in allowed]
    if user_range is not None and str(user_range).strip().lower() not in ('', 'auto'):
        value = dec(user_range)
        if value not in choices:
            raise MeasurementError(f'Portata {value} non disponibile: {", ".join(map(str,choices))}')
        if magnitude > value:
            raise MeasurementError(f'Valore {magnitude} superiore alla portata {value}')
        return value
    for value in choices:
        if magnitude <= value:
            return value
    raise MeasurementError('Valore superiore a tutte le portate disponibili')

def sig(x, n=4):
    x=dec(x)
    if not 1 <= int(n) <= 12: raise MeasurementError('Cifre significative non valide')
    if x == 0: return '0'
    places = x.adjusted()-int(n)+1
    with localcontext() as ctx:
        ctx.prec = 50
        rounded=x.quantize(D('1').scaleb(places))
    return format(rounded,'f')

def normal(value):
    return format(value,'f')

@dataclass
class Result:
    value_raw: str
    uncertainty_raw: str
    uncertainty_display: str
    value_display: str
    unit: str
    instrument: str
    kind: str
    range_used: str
    formula: str
    notes: str
    # Metadati opzionali utili per controlli e riutilizzo delle misure di fase
    input_value: str = ''
    input_unit: str = ''
    frequency_hz: str = ''
    frequency_uncertainty_hz: str = ''
    time_scale_s_div: str = ''
    time_delay_s: str = ''
    time_uncertainty_s: str = ''
    uncertainty_method: str = ''


def calculate(instrument, kind, value, unit, *, range_used='auto', frequency=None,
              v_div=None, offset='0', full_scale_divisions=8, years=0,
              include_flatness=True, sig_digits=4, time_scale=None,
              frequency_uncertainty=None, frequency_source='AFG-2225', frequency_years=0):
    """Calcola una singola misura. Tutte le opzioni fisiche sono nell'unità base.

    range_used: portata in unità base (V, ohm), oppure 'auto'.
    frequency: Hz; v_div: V/div; offset: V; years: anni trascorsi, per AFG.
    """
    if instrument not in KINDS or kind not in KINDS[instrument]:
        raise MeasurementError('Combinazione strumento/grandezza non disponibile')
    if unit not in UNIT_SCALE or UNIT_SCALE[unit][0] != KINDS[instrument][kind]:
        raise MeasurementError(f'Unità {unit} incompatibile con {kind}')
    with localcontext() as ctx:
        ctx.prec=50
        x=dec(value)*dec(UNIT_SCALE[unit][1]); absx=abs(x)
        base=KINDS[instrument][kind]
        r=''; note=''; formula=''; extra={}
        if instrument=='34460A':
            if kind=='Tensione DC':
                rvalue=choose_range(absx,DC_V,range_used)
                _,a,b=next(row for row in DC_V if D(row[0])==rvalue)
            elif kind=='Resistenza':
                rvalue=choose_range(absx,OHM,range_used)
                _,a,b=next(row for row in OHM if D(row[0])==rvalue)
            else:
                rvalue=choose_range(absx,AC_V_RANGES,range_used)
                if frequency is None or str(frequency).strip()=='':
                    raise MeasurementError('La tensione AC richiede la frequenza in Hz')
                f=dec(frequency)
                if f < 3 or f > 300000:
                    raise MeasurementError('Frequenza AC fuori dal campo 3 Hz - 300 kHz')
                # Intervalli contigui: il limite inferiore appartiene alla banda seguente.
                band=next((band for j,band in enumerate(AC_BANDS) if D(band[0])<=f<(D(band[1]) if j<len(AC_BANDS)-1 else D(band[1])+D('0.000000001'))),None)
                if not band: raise MeasurementError('Frequenza AC fuori dalle bande')
                _,_,a,b=band
                note=f'Banda frequenza: {band[0]}-{band[1]} Hz. Controllare condizioni AC del manuale.'
            dx=D(a)/100*absx + D(b)/100*rvalue
            r=normal(rvalue); formula=f'({a}% × |lettura|) + ({b}% × portata)'
        elif instrument=='GPE-4323':
            if kind.startswith('Tensione'):
                dx=D('0.001')*absx+D('0.030'); formula='0.1% × |lettura| + 0.030 V'
            else:
                dx=D('0.003')*absx+D('0.006'); formula='0.3% × |lettura| + 0.006 A'
            note='Setting accuracy' if kind.endswith('impostata') else 'Readback accuracy'
        elif instrument=='LCR-819':
            dx=D('0.0005')*absx; formula='0.05% × |lettura|'
            note='Solo basic accuracy: verificare condizioni di applicabilità nel manuale.'
        elif instrument=='EDUX1052G':
            if kind=='Tensione (DC verticale)':
                if v_div is None or str(v_div).strip()=='':
                    raise MeasurementError('Inserire la scala verticale V/div')
                sv=dec(v_div); off=dec(offset)
                if sv<=0: raise MeasurementError('V/div deve essere positivo')
                n=dec(full_scale_divisions)
                if n<=0: raise MeasurementError('Il numero di divisioni deve essere positivo')
                fs=sv*n
                gain=(D('0.03') if sv>=D('0.01') else D('0.04'))*fs
                offacc=D('0.1')*sv+D('0.002')+D('0.01')*abs(off)
                dx=gain+offacc+D('0.0025')*fs
                r=f'{normal(sv)} V/div'; formula='gain (3% o 4% FS) + 0.1 div + 2 mV + 1% |offset| + 0.25% FS'
                note=f'FS assunto pari a {normal(n)} div; confermare la convenzione del manuale.'
            elif kind in ('Fase letta (gradi)', 'Fase da ritardo'):
                # Procedura di laboratorio concordata. La specifica dei cursori
                # e' per lo stesso canale; su CH1/CH2 e per la fase automatica
                # ne facciamo una STIMA, non una specifica garantita dal manuale.
                if frequency is None or str(frequency).strip()=='':
                    raise MeasurementError('Per la fase occorre la frequenza (Hz)')
                f=dec(frequency)
                if f<=0: raise MeasurementError('La frequenza deve essere positiva')
                if time_scale is None or str(time_scale).strip()=='':
                    raise MeasurementError('Inserire la scala orizzontale s/div')
                stime=dec(time_scale)
                if stime<D('0.000000005') or stime>D('50'):
                    raise MeasurementError('s/div fuori dal campo 5 ns/div - 50 s/div del modello')
                age=dec(years)
                if age<0: raise MeasurementError('Gli anni di aging non possono essere negativi')
                freqage=dec(frequency_years)
                if freqage<0: raise MeasurementError('Gli anni di aging del generatore non possono essere negativi')
                if frequency_source=='AFG-2225':
                    df=f*(D('20')+freqage)*D('0.000001')
                    freq_note='frequenza impostata su AFG-2225: (20 + anni) ppm'
                elif frequency_source=='manuale':
                    if frequency_uncertainty is None or str(frequency_uncertainty).strip()=='':
                        raise MeasurementError('Inserire l’incertezza assoluta sulla frequenza (Hz)')
                    df=dec(frequency_uncertainty)
                    if df<0: raise MeasurementError('L’incertezza sulla frequenza non può essere negativa')
                    freq_note='incertezza della frequenza fornita dall’utente'
                else:
                    raise MeasurementError('Sorgente della frequenza non riconosciuta')
                if kind=='Fase letta (gradi)':
                    phase=x
                    delay=phase/(D('360')*f)
                else:
                    delay=x  # In ingresso, il tempo e' gia' convertito in s.
                    phase=D('360')*f*delay
                dt=(D('50')+D('5')*age)*D('0.000001')*abs(delay) + D('0.0016')*D('10')*stime + D('0.0000000002')
                dphase=D('360')*((delay*df)**2+(f*dt)**2).sqrt()
                extra={'input_value':normal(dec(value)), 'input_unit':unit,
                       'frequency_hz':normal(f),'frequency_uncertainty_hz':normal(df),
                       'time_scale_s_div':normal(stime),'time_delay_s':normal(delay),
                       'time_uncertainty_s':normal(dt),
                       'uncertainty_method':'propagazione_in_quadratura_stima_cursori_stesso_canale'}
                note=('STIMA NON GARANTITA: formula dei cursori sullo stesso canale usata '
                      'per la fase automatica o CH1/CH2; differenze di canale e sonde non incluse. '
                      + freq_note + '. Formula in quadratura con indipendenza ipotizzata.')
                formula='dt_err=(50+5×anni) ppm×|dt|+0.0016×(10×s/div)+200 ps; dphi=360 sqrt((dt×df)^2+(f×dt_err)^2)'
                # La grandezza calcolata o letta e la fase, sempre in gradi.
                x=phase; dx=dphase; scale=D('1'); unit='deg'
                r=f'{normal(stime)} s/div'
            else:
                age=dec(years)
                if age<0: raise MeasurementError('Anni non validi')
                dx=absx*(D('50')+D('5')*age)*D('0.000001')
                formula='|tempo| × (50 + 5 × anni) ppm'
                note='Solo contributo timebase; non comprende risoluzione, cursori o jitter.'
        elif instrument=='AFG-2225':
            age=dec(years)
            if age<0: raise MeasurementError('Anni non validi')
            if kind=='Frequenza generata':
                dx=absx*(D('20')+age)*D('0.000001')
                formula='|frequenza| × (20 + anni × 1) ppm'
                note='Stability e aging sommati conservativamente; tolleranza distinta non compresa.'
            else:
                if frequency is None or str(frequency).strip()=='':
                    raise MeasurementError('Indicare la frequenza del segnale in Hz')
                f=dec(frequency)
                if f<=0 or f>25000000: raise MeasurementError('Frequenza fuori campo')
                acc=D('0.02')*absx+D('0.001')
                dx=acc
                formula='2% × |ampiezza| + 1 mVpp (specificata a 1 kHz)'
                if f!=1000:
                    if include_flatness:
                        pct=D('0.01') if f<=100000 else D('0.03') if f<=5000000 else D('0.05') if f<=12000000 else D('0.10')
                        dx+=pct*absx
                        formula+=f' + {normal(pct*100)}% × |ampiezza| (flatness)'
                        note='Somma conservativa dei limiti ampiezza/flatness; riferimenti e condizioni del manuale da verificare.'
                    else:
                        note='Fuori da 1 kHz: accuracy nominale applicata senza flatness, non copre la dipendenza in frequenza.'
                else: note='Specifiche di ampiezza riferite a 1 kHz; verificare carico di uscita.'
        scale=dec(UNIT_SCALE[unit][1]); dx_unit=dx/scale
        derived_phase = instrument=='EDUX1052G' and kind=='Fase da ritardo'
        shown_value = normal((x/scale).normalize()) if derived_phase else str(value).strip().replace(',','.')
        return Result(value_raw=normal(x/scale),uncertainty_raw=normal(dx_unit),
                      uncertainty_display=sig(dx_unit,sig_digits),value_display=shown_value,
                      unit=unit,instrument=instrument,kind=kind,range_used=r,formula=formula,
                      notes=note, **extra)

