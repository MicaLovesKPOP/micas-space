# Gefilterde AutoWeek-feed

Deze map bouwt automatisch een persoonlijke RSS-feed uit de algemene AutoWeek-RSS.

Doel: gewone autonieuwsartikelen behouden, maar de meeste routinematige EV-consumentencontent wegfilteren, zoals:

- EV-rijtests en reviews
- actieradius/range
- laadsnelheid, laadpalen en thuisladen
- lease/bijtelling
- prijs- en uitvoeringsnieuws rond doorsnee EV's
- routinematige introducties/facelifts van EV-modellen

Belangrijk EV-industrienieuws blijft juist staan, bijvoorbeeld grote strategiewijzigingen, productiestops, recalls, wetgeving, faillissementen en relevante techniek. Bij twijfel houdt het filter een artikel liever wel dan niet.

## Feed voor Inoreader

Gebruik deze URL als RSS-feed:

```text
https://raw.githubusercontent.com/MicaLovesKPOP/micas-space/main/feeds/autoweek/autoweek-filtered.xml
```

De GitHub Action ververst de feed tweemaal per uur. De eerste automatische run kan een paar minuten later starten dan het exacte cronmoment.

## Filter aanpassen

De lijsten bovenaan `filter_feed.py` zijn expres leesbaar gehouden. De belangrijkste groepen zijn:

- `MAJOR_NEWS_TERMS`: altijd interessante EV-ontwikkelingen
- `EXCEPTIONAL_TERMS`: uitzonderlijke enthusiast/performance-verhalen
- `EV_TERMS`: signalen dat een artikel over een EV gaat
- `BORING_EV_TERMS`: consument/review/laden/range-signalen
- `ROUTINE_EV_PRODUCT_TERMS`: alledaags model- en uitvoeringsnieuws

`filter-debug.json` laat na iedere run per artikel zien of het is behouden of weggefilterd en waarom. Daarmee kunnen we het filter later nauwkeuriger afstellen op wat je daadwerkelijk irritant of juist interessant vindt.
