see also [data analysis.md](data analysis.md), [chart-framework-spec.md](chart-framework-spec.md)


# 260323

## Rules
- have both snapshot (one year/period) and trendline/timeline – 2 separate views. then data/table view (datatable + filters, heatmaps)
- later, 3rd view where one can choose chart type, series/dimensions + filters?
- if geo, choropleth
- where bar chart needed, offer stacked/grouped option an line chart - with a toggle
- where choropleth also stacked bar chart - can be unstacked -> grouped
- sex + age -> Population pyramid 
- where multiple (at least 2) categories - bubble matrix. where more than 2, choose pairs. 

options:
- has geo
- has age
- has gender
- has how many dimensions?

most are simple!


- Where CAEN, just one

## TUR105G
judete, regiuni, macroregiuni

### Dimensions

- Tipuri de structuri de primire turistica (18)
    - Pensiuni agroturistice; Pensiuni turistice; Apartamente si camere de inchiriat; Bungalouri; Cabane turistice; Campinguri; Casute turistice; Hanuri; Hosteluri; Hoteluri; Hoteluri apartament; Moteluri; Popasuri turistice; Sate de vacanta; Spatii de cazare de pe navele fluviale si maritime; Tabere de elevi si prescolari; Total; Vile turistice; 
- Tipuri de turisti 
    - ro / int / total
- geo
- timeline (luni)

### Charts

**Snapshot**

1. Choropleth
    - filter by tipuri de structuri, tipuri de turiști
2. Bar/line chart, stacked
   x: tipuri de structuri, series (stacked part): tipuri de turiști
    - filter by geo
3. scatter plot/bubble matrix (tipuri structuri x tipuri turiști)
    - filter by geo

**Trends/Timeline**

x: time
1. 2 bar/line charts, stacked by tipuri structuri or tipuri de turiști, filter by the other


## SAR118B

Snapshot: Choropleth + bar-chart
Timeline: bar/line chart

## PTT102A

Snapshot: Choropleth (filter by categorii - single select), bar-chart (stacked/grouped by categorii), matrix bubble chart
Timeline: 2 bar charts, stacked with categorii or geo as series (filter by the other dimension)

## LOC108A


----




# Notes on possible charts, by examples

Intentions: 
- display relevant charts and filters relative to data 
- prezent snapshots and timelines
- combo charts
- chart customisations?
- per chart or per dataset filters?
- all datasets have a table view

- [x] when multiple units, split charts - DONE

Chart types, filters.
Filters are per page, or per chart. Or per chart group.

Either show a timeline (variance throughout time), either show a snapshot - one year at the time. 

option (later): per capita

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


----

### TLS1112
Tinta 1 - Social - RATA DEPRIVARII SEVERE DE LOCUIRE

Sexe
Grupe de varsta
Statutul de saracie
Perioade
UM: Procente

 
---


### **AMG1103**
AMIGO - Populatia ocupata si salariatii dupa programul de lucru, pe grupe de varsta si sexe

### **TLS1112**

### TCJ0331
Tinta 3 - Social - Persoane de 16 ani si peste care nu au putut consulta un medic specialist, in ultimele 12 luni, dupa motivul invocat

### TUR105G
Innoptari in structuri de primire turistica pe tipuri de structuri, tipuri de turisti, macroregiuni, regiuni de devoltare si judete, pe luni


# quirkies

INT109A - dimensions have parents in different columns