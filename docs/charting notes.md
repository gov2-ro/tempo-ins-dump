see also [data notes.md](data notes.md)

# Notes on possible charts, by examples

Intentions: 
- display relevant charts and filters relative to data 
- prezent snapshots and timelines
- combo charts
- chart customisations?
- per chart or per dataset filters?
- all datasets have a table view

when multiple units, split charts

Chart types, filters.
Filters are per page, or per chart. Or per chart group.

Either show a timeline (variance throughout time), either show a snapshot - one year at the time. 

option: per capita

## Chart types

- Map: choropleth
- Population pyramid - when gender + another dimension (like age group)
- Line
- Bar
    - Grouped
    - Stacked
- Matrix bubble chart / Categorical scatter plot
    - option: with pies inside
- Small multiples, group o charts
- Sankey
- Table - include heatmap? 

https://echarts.apache.org/examples/en/editor.html?c=scatter-punchCard
 

## Examples per datasets


### **POP107B**
POPULATIA DUPA DOMICILIU in varsta de munca la 1 ianuarie pe medii de rezidenta si sexe, macroregiuni, regiuni de dezvoltare si judete

#### Dimensions: 
- Medii de rezidenta: Urban | Rural
- Sexe: Masculin | Feminin
- Macroregiuni regiuni de dezvoltare si judete: Macroregiuni | Regiuni | Județe
- Perioade: Ani
- UM: Numar persoane
- Valoare

2 view modes: 1. year snapshot - with selector (includes autoplay option) / 2. time dynamic/variation over time – where years/periods are a dimension

#### Year snapshot

1. Map: 3 maps, judete, regiuni, macroregiuni. 
with filters: choose both or one of the genders or medii de rezidenta

2. Bar / line
Stacked/grouped bar chart. By sexe and medii rezidență
x: geo
Similar line chart.

#### Timeline
1. bar 1: stacked/ grouped bar chart
    choose y axis: medii de rezidenta, sexe, 
2. bar 2: geo      marcroregiuni, regiuni





----



### **FOM121B**
Numarul salariatilor cu program complet de lucru care au fost platiti intreaga luna, salariul brut de baza si venitul brut realizat in octombrie, pe grupe de varsta, pe grupe majore de ocupatii (ISCO-08) si pe sexe

#### Dimensions: 

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


 


### **AMG1103**
AMIGO - Populatia ocupata si salariatii dupa programul de lucru, pe grupe de varsta si sexe

### **TLS1112**

### TCJ0331
Tinta 3 - Social - Persoane de 16 ani si peste care nu au putut consulta un medic specialist, in ultimele 12 luni, dupa motivul invocat

### TUR105G
Innoptari in structuri de primire turistica pe tipuri de structuri, tipuri de turisti, macroregiuni, regiuni de devoltare si judete, pe luni
