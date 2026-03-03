# Notes on possible charts, by examples

Intentions: 
- display relevant charts and filters relative to data 
- prezent snapshots and timelines
- combo charts
- chart customisations?
- per chart or per dataset filters?
- all datasets have a table view

## Chart types

- Map: choropleth
- timeline
- stacked
- bubble chart - w x/y ctgs punch chart - scatter + bubble dimensions: https://echarts.apache.org/examples/en/editor.html?c=scatter-punchCard

## Examples per datasets


**POP107B**
POPULATIA DUPA DOMICILIU in varsta de munca la 1 ianuarie pe medii de rezidenta si sexe, macroregiuni, regiuni de dezvoltare si judete

Dimensions: 
- Medii de rezidenta: Urban | Rural
- Sexe: Masculin | Feminin
- Macroregiuni regiuni de dezvoltare si judete: Macroregiuni | Regiuni | Județe
- Perioade: Ani
- UM: Numar persoane
- Valoare

Map: 3 maps, judete, regiuni, macroregiuni
with filters: choose both or one of the genders or medii de rezidenta. another one for year.

Stacked bar chart: sexe and medii rezidență. option: detachable 
Also line chart.
x axis: 
- years
- geo

select/filter judete / regiuni?

Timeline: 
x years,

Punch card

----

**FOM121B**
Numarul salariatilor cu program complet de lucru care au fost platiti intreaga luna, salariul brut de baza si venitul brut realizat in octombrie, pe grupe de varsta, pe grupe majore de ocupatii (ISCO-08) si pe sexe

- Salariati, salariul brut de baza si venitul brut realizat
    - Numarul salariatilor cu program complet de lucru, care au fost platiti intreaga luna octombrie
    - Salariul brut de baza
    - Venitul brut realizat
- Varste si grupe de varsta
    - includes total
- Grupe majore de ocupatii (ISCO-08)
    - Total
    - Membri ai corpului legislativ, ai executivului, inalti conducatori ai administratiei publice, conducatori si functionari superiori
    - Specialisti in diverse domenii de activitate
    - Tehnicieni si alti specialisti din domeniul tehnic
    - Functionari administrativi
    - Lucratori in domeniul serviciilor
    - Lucratori calificati in agricultura, silvicultura si pescuit
    - Muncitori calificati si asimilati
    - Operatori la instalatii si masini; asamblori de masini si echipamente
    - Ocupatii elementare
- Sexe
    - Total
    - Masculin
    - Feminin
- Perioade
    - Ani
- Unitati de masura
    - Numar persoane
    - Lei


----


**AMG1103**
AMIGO - Populatia ocupata si salariatii dupa programul de lucru, pe grupe de varsta si sexe
