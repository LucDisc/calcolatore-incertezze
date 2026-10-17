# Calcolatore di incertezze di laboratorio

App Streamlit per cinque strumenti: Keysight 34460A, Keysight EDUX1052G, GW Instek GPE-4323, GW Instek AFG-2225, GW Instek LCR-819.

## Online su Streamlit Community Cloud
1. Creare un repository GitHub e caricare `app.py`, `engine.py` e `requirements.txt` nella radice.
2. Accedere a https://share.streamlit.io e scegliere **Create app** / **Deploy** dal repository GitHub.
3. Selezionare come file di ingresso `app.py` e avviare il deploy.
4. Aprire il link generato, incollare i dati e scaricare CSV, XLSX, TEX o JSON.

## Esecuzione locale (facoltativa)
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Richiamo da Python
```python
from engine import calculate
r = calculate('34460A', 'Tensione DC', '4.5720', 'V')
print(r.uncertainty_raw)      # 0.00050720
print(r.uncertainty_display)  # 0.0005072 (4 cifre significative)
```


## Fase con oscilloscopio EDUX1052G
Nel menu dello strumento sono disponibili due tipi di misura:
- **Fase letta (gradi)**: inserire la fase in gradi, la frequenza in Hz e la scala orizzontale in s/div. Il programma ricostruisce il ritardo con `dt = fase/(360*f)`; mantiene come risultato la fase originale letta.
- **Fase da ritardo**: inserire il ritardo, scegliendo secondi, millisecondi, microsecondi o nanosecondi; frequenza e scala orizzontale come sopra. Il programma calcola `fase_deg = 360*f*dt`.

In entrambi i casi si usa:

```
dt_error_s = (50 + 5*anni) * 1e-6 * abs(dt) + 0.0016 * (10*s_div) + 200e-12
fase_error_deg = 360 * sqrt((dt * df)^2 + (f * dt_error_s)^2)
```

La frequenza `f` può essere attribuita al generatore AFG-2225 (errore `df = f * (20 + anni_generatore) ppm`) oppure può essere inserita manualmente insieme alla propria incertezza assoluta in Hz.

**Limite metrologico importante:** la formula dei cursori temporali nel datasheet Keysight è specificata per misure **sullo stesso canale**. Su segnali CH1/CH2, e nella modalità di fase letta automaticamente, il programma la usa **come stima convenzionale concordata**, non come accuratezza garantita del misuratore di fase. Non comprende esplicitamente skew tra canali e sonde né la correlazione dei contributi. La propagazione in quadratura è la convenzione scelta per il laboratorio.

Fonte ufficiale: https://www.keysight.com/us/en/assets/7018-06411/data-sheets/5992-3484.pdf.html

La scala `s_div`, la frequenza e l'incertezza della frequenza possono essere diverse per ogni riga. Nel copia/incolla da Excel per la fase l'ordine predefinito delle colonne è: `valore`, `s_div`, `frequenza_Hz`, `incertezza_f_Hz`, `unita`; si possono incollare anche soltanto i valori. Nell'esportazione numerica si conservano separatamente fase, ritardo, incertezze, frequenza e impostazioni, usando sempre il punto decimale.

### Esempio di utilizzo da Python
```python
from engine import calculate
r = calculate('EDUX1052G', 'Fase da ritardo', '-0.125', 'ms',
              frequency='1000', time_scale='0.0001',
              frequency_source='AFG-2225')
print(r.value_raw, r.uncertainty_raw, r.unit)
# -45.000000 0.578... deg
```

## Attenzione metrologica
I valori calcolati sono limiti di accuratezza, non incertezze standard. Per l'oscilloscopio va verificato il numero di divisioni che definisce il fondo scala. Per il ponte LCR è stata fornita solo la basic accuracy. Per l'AFG l'accuratezza nominale dell'ampiezza è data a 1 kHz; la flatness è aggiunta in modo conservativo e selezionabile per altri valori di frequenza. Il contributo ±1 count del frequency counter non è incluso: non è la funzione utilizzata.

Il CSV usa campi `value_raw` e `uncertainty_raw` per analisi numeriche e `value_display` e `uncertainty_display` per la visualizzazione. I punti sono sempre il separatore decimale in output.
