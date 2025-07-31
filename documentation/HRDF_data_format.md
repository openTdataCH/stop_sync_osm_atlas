1. [Home](https://opentransportdata.swiss/)
2. [Cookbook](https://opentransportdata.swiss/en/cookbook/)
3. [Timetable data – overview](https://opentransportdata.swiss/en/cookbook/timetable-cookbook/)
4. HAFAS Raw Data Format (HRDF)

### Table of contents

* [Brief Description](#Brief_Description)
  + [What is HRDF?](#What_is_HRDF)
  + [Who is behind it?](#Who_is_behind_it)
  + [Why does the Open Data platform offer this?](#Why_does_the_Open_Data_platform_offer_this)
* [Functional Description](#Functional_Description)
  + [What information do we map with HRDF? (size)](#What_information_do_we_map_with_HRDF_size)
  + [How is the information structured? (model)](#How_is_the_information_structured_model)
* [Technical Description](#Technical_Description)
  + [Timetable file (FPLAN) and its references and general information](#Timetable_file_FPLAN_and_its_references_and_general_information)
  + [Stops file (BAHNHOF) and its references](#Stops_file_BAHNHOF_and_its_references)
* [Further information](#Further_information)
  + [Realisation specifications RV 2.0.6 and 2.0.7](#Realisation_specifications_RV_206_and_207)

### Search on the page

Search for:

# HAFAS Raw Data Format (HRDF)

## Brief Description

### What is HRDF?

The Hafas Raw Data Format (HRDF) is a proprietary file format for timetable data.

### Who is behind it?

The company [Hacon](https://www.hacon.de/) has developed the **H**acon **F**ahrplan-**A**uskunfts-**S**ystem (**HAFAS**), which uses HRDF for data exchange.

### Why does the Open Data platform offer this?

The HAFAS system (see above) is widely used in public transport, which has made HRDF one of the standards in the industry. It also covers many aspects of customer information that are not (currently) available in other formats.

You can find more information on the assessment of HRDF as a standard in the [report](https://www.bav.admin.ch/dam/bav/de/dokumente/uebergeordnete-themen/mmm/diskussionsgrundlage-standardisierungkonzept-modi-fokus-nadim-v2.pdf.download.pdf/diskussionsgrundlage-standardisierungskonzept-modi-fokus-nadim-v2.pdf) (German) by the Federal Office of Transport (FOT).

#### Access the Data

* <https://data.opentransportdata.swiss/dataset/timetable-54-2025-hrdf> – Changes each year
* <https://data.opentransportdata.swiss/dataset/timetable-54-2025-hrdf-autoverlad> – Changes each year (only for car loading)
* <https://data.opentransportdata.swiss/dataset/timetable-54-draft-hrdf> – Changes each year (timetable draft)

## Functional Description

### What information do we map with HRDF? (size)

* **Swiss public transport timetable data** and journeys in the area **close to the Swiss border**.
  + Note: *For cross-border trains*, the Swiss part of the journey is included up to the first commercial stop abroad (in the direction of abroad) or the last commercial stop abroad (in the direction of Switzerland).
* All information for **an entire timetable period** (e.g. 2024).

### How is the information structured? (model)

An **HRDF export consists of several files**, which almost all **have to be viewed together** for an overall picture. For details, please refer to the realisation specification ([RV v2.0.5](https://www.öv-info.ch/sites/default/files/2023-07/hrdf_2_0_5_d.pdf) (July 2023, German) or [RV v2.0.7](https://www.oev-info.ch/sites/default/files/2024-12/HRDF_2_0_7_e.pdf) (May 2024)) and the official HRDF documentation (available on request: [contact form](/contact/)).

To a certain extent, the HRDF file can be viewed as a database dump. The individual files in the ZIP correspond to individual tables or objects.

**Please note:**

* NOMEN EST OMEN does NOT (always) apply to HRDF files. For example, the “BAHNHOF” file contains not only railway stations, but all stops (including bus stops, for example).
* The format of the HRDF files is designed for a compact, machine-readable structure. Therefore:
  + are frequently related but not identical contents in the same file
  + contents are indicated with an “\*” followed by a letter, e.g. “\*Z” (so the interpreting system knows what comes next)
  + the structure of each line following an “\*” is strictly regulated in the HRDF documentation. Each part of a line has a predetermined width (number of characters), the parts are separated by spaces. Example:
    - It can be defined that the first part of a line contains the ID of a stop and may only be 5 characters long and the next part (from character 6 to character 10) identifies the company owning the stop.
    - So the line could look like this: 12345\_67891, where \_ visualises the space. If there is no company and the field is optional, then characters 6-10 would only be spaces.
  + **HRDF thus differs from other common file formats** such as CSV, where content is separated with a comma, or JSON, where content is represented in a structured way (with various characters): **content in HRDF is limited in its scope and position on each line**.
* There are files that are part of the HRDF export we provide that are empty. These are only included in the sense of interoperability of decreasing systems. We deliberately do NOT list them in the following description.

Overall, the HRDF data can be divided into (1) master data, (2) time-relevant data, (3) timetable data and (4) transfer data. We will go into the content in more detail below.

## Technical Description

This section **roughly** describes each individual file of the HRDF model including examples from the HRDF export (detailed information can be found in the RV and HRDF documentation). In addition, we do not describe the files alphabetically, but starting from node files. For example, we first introduce FPLAN as one of the central files and then describe the files referenced by this file, etc. Thus we divide the description into:

* Timetable file (FPLAN) and its references and general information
  + You need to find out:
    - **when** will
    - travelled **from** where **to** where
    - on which **days of the year**
    - By which **means of transport**
    - with which **line**
    - with which **additional services and restrictions**
    - with which **further details (SJYID, etc.****)**
  + As well as for time-relevant information:
    - **Validity**
    - **Public holidays**
    - **Time zones**
* Stops file (BAHNHOF) and its references
  + Needed for the following information on stops:
    - **Name**
    - **Grouping** of several stops
    - **Coordinates** of the stops
    - **ID** of the stops
    - **Transfer information** within and between stops

### Timetable file (FPLAN) and its references and general information

Extract from the model overview. An arrow means that a key is “pointed to” in the referenced file:

[![](https://opentransportdata.swiss/wp-content/uploads/2024/02/hrdf_cookbook_fplan.png)](https://opentransportdata.swiss/wp-content/uploads/2024/02/hrdf_cookbook_fplan.png)

| Area | Specialised content | File name | Description |
| --- | --- | --- | --- |
| Time-relevant data | Validity of the delivery | ECKDATEN | Life of the timetable  The timetable data is valid for the defined period. The duration usually corresponds to that of the timetable period  Can be read in decoupled from other data. |
| Time-relevant data | General public holidays | FEIERTAG | List of public holidays that apply in Switzerland.  In addition to the date of the holiday, the description of the holiday is listed in four languages: DE, FR, IT, EN  Can be read in decoupled from other data. |
| Time-relevant data | Time zones | ZEITVS | Definition of the time zones, including the date when the summer and winter time changes take place  *Further details on this topic and its implementation in Switzerland can be found in the RV*  There are 2 types of representation:   * Type 1:   + Railway station number   + (general) time difference compared to GMT   + Time difference that applies to the following period   + FromDate (the time difference applies from this day)   + Time (from this time)   + UntilDate (the time difference applies until this date)   + Time (at this time)   + Comment (further time periods are also available in the Swiss export, before the comment) * Example (excerpt):  ``` ... 0000000 +0100 +0200 26032023 0200 29102023 0300 +0200 31032024 0200 27102024 0300 %  Nahverkehrsdaten; MEZ=GMT+1 1000000 +0200 +0300 26032023 0300 29102023 0400 +0300 31032024 0300 27102024 0400 %  Finnland ... ```  * Typ 2:   + Railway station number   + Railway station number * Example (excerpt):  ``` ... 7400000 0000000 7600000 0000000 8100000 0000000 ... ``` |
| Time-relevant data | Validity in the year | BITFELD | Day-specific definition of the validity of the timetable information. The validity is defined using a bit pattern. Each day is mapped with one bit. Four bits are combined to form a hexadecimal digit. Each bit pattern receives a code. The perpetual patterns have the same code every year. Otherwise, new patterns that are defined for their timetables according to the requirements of the transport companies receive new codes.To interpret the bit field, it is important to understand how the timetable years work (more information [here](https://www.oev-info.ch/de/fahrplan-aktuell/fahrplanwissen/fahrplanjahr-und-wechsel)). A timetable year usually lasts one year, but the timetable year begins on the 2nd weekend in December. **This means that a timetable year is not always the same length. To deal with this, the bit field is assumed to be 400 days long**.File contains:- Bit field codeBit field definition Example (excerpt) – Hex insetead of bits:   ``` ... 000017 FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFE00 % Bitfeld 17 repräsentiert die Nr FF...00 ... ``` |
| Timetable data | Timetable | FPLAN | List of journeys and by far the largest and most comprehensive file in the HRDF export.  This file contains:   * **\*Z lines**: as header information for the run. *Further details on this topic and its implementation in Switzerland can be found in the RV*. It includes:   + The journey number (primary key with the TU code)   + Transport company (TU) code (see File BETRIEB\_\*)     - For the TU code = 801, the region information must also be taken into account. This information is contained in line \*I with the INFOTEXTCODE RN.   + Option     - NOT PART OF HRDF. 3-digit means of transport variant code without technical meaning   + (optional) Number of cycles   + (optional) Cycle time in minutes * Example (excerpt):   ``` *Z 000003 000011   101         % Fahrtnummer 3, für TU 11 (SBB), mit Variante 101 (ignore) ...  *Z 123456 000011   101 012 060 % Fahrtnummer 123456, für TU 11 (SBB), mit Variante 101 (ignore), 12 mal, alle 60 Minuten ... ```   * **\*G-lines**: Reference to the offer category (s. ZUGART file). It includes:   + Reference to the offer category     - The term “Angebotskategorie” (offer category) may have a different meaning here than in colloquial language! A colloquial term (also according to the HRDF doc.) would be “transport mode type”.   + Stop from which the offer category applies   + Stop up to which the offer category applies * Example (excerpt):  ``` *Z ... *G ICE 8500090 8503000 % Angebotskategorie ICE gilt ab HS-Nr. 8500090 bis HS-Nr. 8503000  ... ```  * **\*A VE lines**: Reference to the validity information (see file BITFELD). *Further details on this topic and its implementation in Switzerland can be found in the RV*. It includes:   + Stop from which the offer category applies   + Stop up to which the offer category applies   + Reference to the validity information. In Switzerland: 000000 = always. * Example (excerpt):  ``` *Z ... *G ... *A VE 8500090 8503000 001417 % Ab HS-Nr. 8500090 bis HS-Nr. 8503000, gelten die Gültigkeitstage 001417 (Bitfeld für bspw. alle Montage) ... ```  * **\*A \*-lines**: Reference to offers (s. file ATTRIBUT). It includes:   + The offer code     - The term “Angebot” (offer) may be imprecise here. The HRDF doc. uses the word “Attribut” (attribute), which is also somewhat imprecise. Basically, it is a collective term for extensions (e.g. dining car) or restrictions (e.g. no bicycles) that apply.   + Stop from which the offer category applies   + Stop up to which the offer category applies   + Reference to the validity information * Example (excerpt):  ``` *Z ... *G ... *A VE ... *A R  8500090 8503000        % Attribut R gilt ab HS-Nr. 8500090 bis HS-Nr. 8503000 *A WR 8500090 8503000 047873 % Attribut WR gilt ab HS-Nr. 8500090 bis HS-Nr. 8503000 mit den Gültigkeitstagen 047873 *A VR 8500090 8503000        % Attribut VR gilt ab HS-Nr. 8500090 bis HS-Nr. 8503000 ...  ```  * **\*I-lines**: Reference to notes (s. INFOTEXT file). *Further details on this topic and its implementation in Switzerland can be found in the RV*. It includes:   + Informational text code. In Switzerland: XI not supported. Permitted codes see list ([DE](https://opentransportdata.swiss/wp-content/uploads/2023/11/Liste-der-INFOTEXTCODE-V4.0-DE.pdf) / [FR](https://opentransportdata.swiss/wp-content/uploads/2023/11/Liste-der-INFOTEXTCODE-V4.0-FR.pdf)).   + Stop from which the info text applies   + Stop up to which the info text applies   + Reference to the validity information. In Switzerland: If not available = always.   + Reference to the info text   + Departure time   + Time of arrival   + Comments:     - The Swiss Journey ID (SJYID) is identified via the \*I line with the code JY * Example (excerpt):  ``` *Z ...  *G ...  *A VE ...  *A ... *I hi 8573602 8587744       000018040             % Hinweis auf Infotext (hi) ab HS-Nr. 8573602 bis HS-Nr. 8587744  mit Infotext 18040 *I hi 8578157 8589334       000018037 01126 01159 % Hinweis auf Infotext (hi) ab HS-Nr. 8578157 bis HS-Nr. 8589334 mit Infotext 18037 Abfahrt 11:26 Ankunft 11:59 ... ```  * **\*L lines**: Line information or reference to the line information (see file LINIE). It includes:   + Line information, reference to external file if necessary.   + Stop from which the line is valid   + Stop to which the line is valid   + Departure time   + Time of arrival * Example (excerpt):  ``` *Z ...  *G ...  *A VE ...  *A ...  *I ... *L 8        8578157 8589334 01126 01159 % Linie 8 ab HS-Nr. 8578157 bis HS-Nr. 8589334 Abfahrt 11:26 Ankunft 11:59 *L #0000022 8589601 8589913             % Referenz auf Linie No. 22 ab HS-Nr. 8589601 bis HS-Nr. 8589913  ...  ```  * **\*R lines**: Reference to the direction text (see file RICHTUNG / DIRECTION). It includes:   + Direction (H=forward,R=backward)   + Reference to direction code   + Stop from which the direction applies   + Stop to which the direction applies   + Departure time   + Time of arrival   + Comments:     - R without information = no direction * Example (excerpt):  ``` *Z ...  *G ...  *A VE ...  *A ...  *I ...  *L ... *R H                         % gilt für die gesamte Hin-Richtung *R R R000063 1300146 8574808 % gilt für Rück-Richtung 63 ab HS-Nr. 1300146 bis HS-Nr. 8574808 ... ```  * **\*GR lines**: supported but not available in Switzerland. * **\*SH lines**: supported but not available in Switzerland. * **\*CI/CO lines**: It includes:   + Number of minutes at check-in(CI)/out(CO)   + Stop from which the direction applies   + Stop to which the direction applies   + Departure time   + Time of arrival * Example (excerpt):  ``` *Z ...  *G ...  *A VE ...  *A ...  *I ...  *L ...  *R ... *CI 0002 8507000 8507000 % Check-in 2 Min. ab HS-Nr. 8507000 bis HS-Nr. 8507000  ... *CO 0002 8507000 8507000 % Check-out 2 Min. ab HS-Nr. 8507000 bis HS-Nr. 8507000  ... ```  * Once all the lines described have been defined, the **run is described with the journey times**:   + Stop (s. BAHNHOF and others)   + Arrival time: Negative = No possibility to get out   + Departure time: Negative = No boarding option   + Journey number   + Administration * Example (excerpt):  ``` *Z ...  *G ...  *A VE ...  *A ...  *I ...  *L ...  *R ...  *CI ... *CO ... 0053301 S Wannsee DB               02014               % HS-Nr. 0053301 Ankunft N/A,   Abfahrt 20:14 0053291 Wannseebrücke        02015 02015 052344 80____ % HS-Nr. 0053291 Ankunft 20:15, Abfahrt 20:15, Fahrtnummer 052344, Verwaltung 80____ (DB) 0053202 Am Kl. Wannsee/Am Gr 02016 02016               % ``` |
| Timetable data | Through-connections | DURCHBI | List of ride pairs that form a contiguous run. Travellers can remain seated.  This construct is used, among other things, for the formation of the wing trains. File contains:   * Journey no. 1 * TU code 1 * Last stop 1 * Journey no. 2 * TU code 2 * Traffic days (see BITFELD file) * First stop 2   Example (excerpt):   ``` ... 000001 000871 8576671 024064 000871 000010 8576671 % Fahrt 1, TU 871, letzte HS 8576671, Fahrt 24064, TU 871, Bitfeld 10, erste HS 8576671  000001 000882 8581701 000041 000882 063787 8581701 % ... 000002 000181 8530625 000003 000181 000000 8530625 % Fahrt 2, TU 181, letzte HS 8530625, Fahrt 3,     TU 181, Bitfeld 0,  erste HS 8530625  000002 000194 8503674 000004 000194 000001 8503674 % ... 000002 000812 8591817 000003 000812 000000 8591817 % ... 000002 000882 8581701 000042 000882 063786 8581701 % ... 000003 000181 8530625 000004 000181 000000 8530625 % Fahrt 3, TU 181, letzte HS 8530625, Fahrt 4, TU 181, Bitfeld 0, erste HS 8530625  000003 000801 8507230 000004 000801 000000 8507230 % ... % Rivera, Passo del Ceneri 000003 000812 8591817 000004 000812 000000 8591817 % ... ... ``` |
| Master data | Service categories (aka means of transport (type)) | ZUGART | List of service categories. Per language the (Class:) grouping of offer categories with identical characteristics. (Option:) Search criteria for the application for connection search. (Categorie:) Designation of the offer category.   Note again: The term “Angebotskategorie\* (offer category) may have a different meaning here than in colloquial language! A colloquial term (also according to the HRDF doc.) would be “means of transport” (type).  This file is modified in Switzerland:   * Offer category definition (or generic definition):   + Offer category code/class code   + Category Product class   + Tariff group (always A)   + Output control (always 0)   + Generic name   + Surcharge (always 0)   + Flag (N: local transport, B: ship)   + Reference to category, see below. * Example (excerpt):  ``` ... IC  1 A 0 IC  0   #014 % Code "IC",  Kategorie 1, Tarifgruppe A, Ausgabesteuerung 0, Gattungsbezeichnung IC,  Zuschlag 0 ICE 0 A 0 ICE 0   #015 % Code "ICE", Kategorie 0, Tarifgruppe A, Ausgabesteuerung 0, Gattungsbezeichnung ICE, Zuschlag 0 ... RUB 6 A 0 RUB 0 B #026 % Code "RUB", Kategorie 6, Tarifgruppe A, Ausgabesteuerung 0, Gattungsbezeichnung RUB, Zuschlag 0, Flag B (Schiff) ... ```  * Introduction Text definition with <text> * Specify language with e.g. <German> * Product classes:   + Product class Number between 0-13   + Product text * Example (excerpt):  ``` ... <text>                                                  % Keyword für Textdefinition <Deutsch>                                               % Sprache ist Deutsch class00 ICE/EN/CNL/ES/NZ/TGV/THA/X2                     % Produktklasse 00 steht für ICE, EN, usw. class01 EuroCity/InterCity/ICN/InterCityNight/SuperCity % Produktklasse 01 steht für EuroCity, InterCity, usw. class02 InterRegio/PanoramaExpress                      % Produktklasse 02 steht für InterRegio, PanoramaExpress ... ```  * Options:   + Option definition Number between 10-14 (*Further details on this topic and the implementation in Switzerland can be found in the RV*) * Example (excerpt):  ``` ... option10 nur Direktverbindungen  % Option 10 steht für nur Direktverbindungen option11 Direkt mit Schlafwagen* % Option 10 steht für Direkt mit Schlafwagen option12 Direkt mit Liegewagen*  % Option 10 steht für Liegewagen ... ```  * Categories:   + Generic long name number Number between 0-999 (see above) * Example (excerpt):  ``` ... category014 InterCity        % Kategorie 14 steht für InterCity category015 InterCityExpress % Kategorie 15 steht für InterCityExpress ... category026 Rufbus           % Kategorie 26 steht für Rufbus ... ``` |
| Master data | Offers | ATTRIBUT | List of abbreviations describing additional offers (e.g.: dining car) or restrictions (e.g.: seat reservation obligatory).   Note again: The term “Angebot” (offer) may be imprecise here. The HRDF doc. uses the word “attribute”, which is also somewhat imprecise. Basically, it is a collective term for extensions (e.g. dining car) or restrictions (e.g. no bicycles) that apply. An overview of the means of transport (and instructions) can be found in the following link: [Lists of means of transport and instructions](/cookbook/transport-modes/)   This file contains:      * The list of offers     Example (excerpt):    ``` ...  Y  0   5  5 % Der Code Y gilt für den Fahrtabschnitt (0) mit Priorität 5 und Sortierung 5  YB 0   5  5 % s.o. für Code YB  YM 0   5  5 % s.o. für Code YB  ... ```      * Description of how the offers can be displayed. This information is actively maintained in the timetable collection     Example (excerpt):    ``` ... # Y  Y  Y  % Attributcode Y soll als Y für Teilstrecke und als Y für Vollstrecke ausgegeben werden # YB YB YB % s.o. für Attributscode YB # YM YM YM % s.o. für Attributscode YM ...  ```      * Description in the following languages : German, English, French, Italian     Example (excerpts):    ``` ... <text>                % Keyword für Textdefinition <deu>                 % Sprache ist Deutsch ... Y  Zu Fuss            % Code Y, mit Beschrieb Zu Fuss YB Zu Fuss und Bus    % Code YB, mit Beschrieb Zu Fuss und Bus YM Zu Fuss und Metro  % Code YM, mit Beschrieb Zu Fuss und Metro ... <fra>                 % Sprache ist Französisch ... Y  A pied             % Code Y YB A pied et en bus   % Code YB YM A pied et en métro % Code YM ... ``` |
| Master data | Info texts | INFOTEXT\_\*   \*DE,\*FR,\*IT,\*EN | Additional information on objects (journeys, lines, etc.). This information can either be   * be simple texts, e.g.:   000018154 Rollstühle können mit Unterstützung des Fahrpersonals befördert werden.  OR * Values with semantic meaning. This means values that cannot be represented in any other way and have therefore been “outsourced” to INFOTEXT, e.g.  000000000 ch:1:sjyid:100001:3-002   The INFOTEXTCODE attribute defines whether these are simple texts or texts with a semantic meaning. The INFOTEXTCODE is not in the INFOTEXT file, but only in the INFOTEXT referencing files, e.g. FPLAN.  A list of the INFOTEXTCODE used can be found under the following [LINK](https://opentransportdata.swiss/wp-content/uploads/2023/03/Liste-der-INFOTEXTCODE-V2.0-DE.pdf).. |
| Master data | Lines | LINIE | List of lines. The file contains:   * Line ID (not unique line by line!) * Line property code * Characteristic  The following property codes are supported:   * Line type K : Line key * Line type W : internal line designation * Line type N T : Line abbreviation * Line type L T : Line name * Line type R T : Line region name (reserved for FOT ID) * Line type D T : Line description * Line type F : Line colour * Line type B : Line background colour * Line type H : Main line * Line type I : Line info texts   Example (excerpt):   ``` ... 0000001 K ch:1:SLNID:33:1     % Linie 1, Linienschlüssel ch:1:SLNID:33:1 0000001 W interne Bezeichnung % Linie 1, interne Linienbezeichnung "interne Bezeichnung" 0000001 N T Kurzname          % Linie 1, Linienkurzname "Kurzname" 0000001 L T Langname          % Linie 1, Linienlangname "Langname" 0000001 D T Description       % Linie 1, Linienbeschreibung "Description" 0000001 F 001 002 003         % Linie 1, Linienfarbe RGB 1, 2, 3 0000001 B 001 002 003         % Linie 1, Linienhintergrundfarbe RGB 1, 2, 3 0000001 H 0000002             % Linie 1, Hauptlinie 2 0000001 I TU 000000001        % Linie 1, Infotexttyp TU, Infotextnummer (s. INFOTEXT-Datei) ... 0000010 K 68                  % Linie 10, Linienschlüsse 68 0000010 N T 68                % Linie 10, Linienkurzname 68 0000010 F 255 255 255         % Linie 10, Linienfarbe RGB 255, 255, 255  0000010 B 236 097 159         % Linie 10, Linienhintergrundfarbe RGB 236, 097, 159 ... ``` |
| Master data | Direction | RICHTUNG | Directional information. More details:   * Direction ID (see FPLAN) * RichtungsText   For example, if a train travels between Sargans and Chur, it is labelled as travelling in the direction of Chur.  Example (excerpt):   ``` ... R000011 Esslingen    % Richtung 11 nach Esslingen R000012 Zollikerberg % Richtung 12 nach Zollikerberg R000013 Forch        % Richtung 13 nach Forch R000014 Egg          % Richtung 14 nach Egg ... ``` |
| Master data | Transport company | BETRIEB\_\*\*DE,\*FR,\*IT,\*EN | List of transport companies. The term “transport company” is understood in different ways. In the context of opentransportdata.swiss, it is understood that it is an organisation that is responsible for the runs described in the FPLAN. A detailed description of the transport companies and business organisations can be found [here](/cookbook/business-organisations/). Each TU is described in detail with 2 lines:    * The first line:     + Operator no. (for BETRIEB / OPERATION file)    + Short name (after the “K”)    + Long name (after the “L”)    + Full name (after the”V”)  * The second line:     + Operator no. (for BETRIEB / OPERATION file)    + “:”    + TU code (or administration number)       - Several TU codes can be listed. These share the information in the first line.    Example (excerpt):   ``` ... 00379 K "SBB" L "SBB" V "Schweizerische Bundesbahnen SBB"     % Betrieb-Nr 00379, kurz sbb, lang sbb, voll schweizerische bundesbahn sbb 00379 : 000011                                                % Betrieb-Nr 00379, TU-Code 000011 00380 K "SOB" L "SOB-bt" V "Schweizerische Südostbahn (bt)"   % Betrieb-Nr 00380, kurz sob, lang sob-bt,  voll schweizerische südostbahn (bt) 00380 : 000036                                                % Betrieb-Nr 00380, TU-Code 000036 00381 K "SOB" L "SOB-sob" V "Schweizerische Südostbahn (sob)" % Betrieb-Nr 00381, kurz sob, lang sob-sob, voll schweizerische südostbahn (sob) 00381 : 000082                                                % Betrieb-Nr 00381, TU-Code 000082 ... ``` |

### Stops file (BAHNHOF) and its references

Extract from the model overview. An arrow means that a key is “pointed to” in the referenced file. For a better overview, BAHNHOF / STATION and BETRIEB / OPERATION are represented by placeholders.

Not repeated: ZUGART, LINIE, BETRIEB\_\*, FPLAN:

[![](https://opentransportdata.swiss/wp-content/uploads/2024/02/hrdf_cookbook_bhf.png)](https://opentransportdata.swiss/wp-content/uploads/2024/02/hrdf_cookbook_bhf.png)

| Bereich | Fachlicher Inhalt | Dateiname | Beschreibung |
| --- | --- | --- | --- |
| Master data | Stops | BAHNHOF | List of stops A detailed description of the stops (incl. Meta-stops (see METABHF file)) can be found [here](/cookbook/timetable-cookbook).   The file contains stops that are referenced in various files:     * Stop number, from DiDok (in future atlas), with a 7-digit number >= 1000000     + The first two numbers are the UIC country code  * Stop name with up to 4 types of designations:     + Up to “$<1>”: official designation from DiDok/atlas    + Up to “$<2>”: long designation from DiDok/atlas    + Up to “$<3>”: Abbreviation from DiDok/atlas    + Up to “$<4>”: alternative designations from the timetable collection     Example (excerpt):    ``` ... 8500009     Pregassona, Scuola Medialt;1>                                             % HS-Nr 8500009 mit off. Bez. Pregassona, Scuola Media 8500010     Basel SBBlt;1>$BSlt;3>$Balelt;4>$Basilea FFSlt;4>$Basle SBBlt;4>$Bâle CFFlt;4> % HS-Nr 8500010 mit off. Bez. Basel SBB, lang. Bez. BS, etc. 8500016     Basel St. Johannlt;1>$BSSJlt;3>                                            % HS-Nr 8500016 mit off. Bez. Basel St. Johann, Abkürzung BSSJ ... ```      * Auxiliary stops have an ID < 1000000.     + They serve as a meta operating point and as an alternative to the name of the DiDok/atlas system. They allow you to search for services with these names in an online timetable without knowing the exact name of the stop according to DiDok/atlas.     Example – Search for Basel instead of “Basel SBB” (excerpt):    ``` ... 0000021     Barcelonalt;1>    % Hilfs-Hs-Nr. 000021, off. Bez. Barcelona 0000022     Basellt;1>        % Hilfs-Hs-Nr. 000022, off. Bez. Basel 0000024     Bern Bümplizlt;1> % Hilfs-Hs-Nr. 000024, off. Bez. Bern Bümpliz ...  ``` |
| Master data | Meta stops | METABHF | Grouping of stops for the search. By grouping the stops, the search for transport chains takes place at all stops in the group.  There are 2 parts. file contains:   * Part One – Transitional Relationships:   + \*A-line: Transition     - followed by the attribute code   + Meta stop ID   + Stop ID      Transition time in minutes * Part two – stop groups:   + Number of the collective term   + “:”   + Numbers of the summarised stops   Example (excerpt):   * The stop 8500010 = “Basel SBB” includes the actual stops (see BAHNHOF file)   + 8500146 = “Basel, railway station entrance Gundeldingen$<1>$Basel, railway station entrance Gundeldingen$<2>”   + 8578143 = “Basel, Bahnhof SBB$<1>”  ``` ...  *A Y                             % *A=Übergang, Y="Fussweg" (s. ATTRIBUT-Datei) 8500010 8500146 009              % Meta-HS-Nr. 8500010, HS-Nr. 8500146, Übergang-Minuten: 9 *A Y                             % *A=Übergang, Y="Fussweg" (s. ATTRIBUT-Datei)  8500010 8578143 006              % Meta-HS-Nr. 8500010, HS-Nr. 8578143, Übergang-Minuten: 6 ... 8389120: 8302430 8389120         % Gruppe: 8389120, umfasst: 8302430, und 8389120  8500010: 8500010 8500146 8578143 % Gruppe: 8500010, umfasst: 8500010, 8500146, und 8578143  8500016: 8500016 8592322         % Gruppe: 8500016, umfasst: 8500016, und 8592322  ... ``` |
| Master data | Stop coordinates | BFKOORD\_\*   \*WGS84, \*LV95 | List of stops with their geo-coordinates. File contains:    * Stop number * Longitude * Latitude * Height   Example (excerpt):   ``` ...lv95-Datei: 8500009    2718660    1098199   0      % HS-Nr. 8500009 LV-Läng. 2718660 LV-Breit. 1098199 Höhe 0 //Pregassona, Scuola Media  8500010    2611363    1266310   0      % HS-Nr. 8500010 LV-Läng. 2611363 LV-Breit. 1266310 Höhe 0 //Basel SBB 8500016    2610076    1268853   0      % HS-Nr. 8500016 LV-Läng. 2610076 LV-Breit. 1268853 Höhe 0 //Basel St. Johann ...wgs84-Datei: 8500009    8.971045   46.024911 0      % HS-Nr. 8500009 LV-Läng. 8.971045 LV-Breit. 46.024911 Höhe 0 //Pregassona, Scuola Media 8500010    7.589563   47.547412 0      % HS-Nr. 8500010 LV-Läng. 7.589563 LV-Breit. 47.547412 Höhe 0 //Basel SBB 8500016    7.572529   47.570306 0      % HS-Nr. 8500016 LV-Läng. 7.572529 LV-Breit. 47.570306 Höhe 0 //Basel St. Johann ... ``` |
| Master data | Station type | BHFART\*   \*, \*\_60 | Definition of the type of stops, i.e. whether the stop should be able to serve as a start and/or destination, or as a via location, and whether it has a global ID (for Switzerland the Swiss Location ID (SLOID)).   The BHFART\_60 variant of the BHFART file also contains the risers (with an “a” as a prefix) of the stations (with an “A” as a prefix). So if the example below says “A”, it describes a stop and not a platform belonging to this stop. A stop can have several platforms (i.e., for example, places to board and alight at the stop in question). File contains:   * Restrictions:   + These stops are not to be offered as start, destination or via entries   + B = Selection and routing restrictions     - Selection restriction (usually “3” – start/finish restricted)     - Routing restriction (usually empty “”) * and the Global ID of the stop and track:   + G = Global ID (in Switzerland: SLOID)     - Type designator (“a”/”A”, “A” only for \*\_60)     - SLOID   The format is included:   * Stop number * Code (e.g.: see above) M\*W * Code details (e.g.: see above, a, A) * Value (e.g.: see above) 3, “”, SLOID)   Example (excerpt):   ``` .....bhfart % Beschränkungen 0000132 B 3                     % Bahn-2000-Strecke % HS-Nr. 0000132 Auswahlbeschränkung 0000133 B 3                     % Centovalli        % HS-Nr. 0000133 Auswahlbeschränkung ... % Globale IDs ... 8500009 G a ch:1:sloid:9        % HS-Nr. 8500009, Typ: SLOID-HS, SLOID = ch:1:sloid:9  8500010 G a ch:1:sloid:10       % HS-Nr. 8500010, Typ: SLOID-HS, SLOID = ch:1:sloid:10 8500016 G a ch:1:sloid:16       % HS-Nr. 8500016, Typ: SLOID-HS, SLOID = ch:1:sloid:16 .....bhfart_60 % Beschränkungen 0000132 B 3                     % Bahn-2000-Strecke % HS-Nr. 0000132 Auswahlbeschränkung 0000133 B 3                     % Centovalli        % HS-Nr. 0000133 Auswahlbeschränkung ... % Globale IDs ... 8500010 G A ch:1:sloid:10       % HS-Nr. 8500010, Typ: SLOID-HS,    SLOID = ch:1:sloid:10 8500010 G a ch:1:sloid:10:3:5   % HS-Nr. 8500010, Typ: SLOID-Steig, SLOID = ch:1:sloid:10:3:5 8500010 G a ch:1:sloid:10:22:35 % HS-Nr. 8500010, Typ: SLOID-Steig, SLOID = ch:1:sloid:10:22:35 8500010 G a ch:1:sloid:10:3:6   % ... 8500010 G a ch:1:sloid:10:2:4   % ... 8500010 G a ch:1:sloid:10:4:8   % ... 8500010 G a ch:1:sloid:10:4:7   % ... 8500010 G a ch:1:sloid:10:7:15  % ... 8500010 G a ch:1:sloid:10:8:16  % ... 8500010 G a ch:1:sloid:10:7:14  % ... 8500010 G a ch:1:sloid:10:5:10  % ... 8500010 G a ch:1:sloid:10:6:11  % ... 8500010 G a ch:1:sloid:10:6:12  % ... 8500010 G a ch:1:sloid:10:0:20  % ... 8500010 G a ch:1:sloid:10:21:30 % ... 8500010 G a ch:1:sloid:10:21:31 % ... 8500010 G a ch:1:sloid:10:2:3   % ... 8500010 G a ch:1:sloid:10:1:1   % ... 8500010 G a ch:1:sloid:10:1:2   % ... 8500010 G a ch:1:sloid:10:22:33 % ... 8500010 G a ch:1:sloid:10:8:17  % ... 8500010 G a ch:1:sloid:10:0:19  % HS-Nr. 8500010, Typ: SLOID-Steig, SLOID = ch:1:sloid:10:0:19 8500010 G a ch:1:sloid:10:5:9   % HS-Nr. 8500010, Typ: SLOID-Steig, SLOID = ch:1:sloid:10:5:9 ...    ```   Caveat: There are currently no different sloids for sectors and sector groups. However, these can have their own coordinates. Depending on the application, the sloid (if it is used as an id) should be supplemented with “: “+”designation” (e.g. ch:1:sloid:7000:501:34:AB) in the internal system. However, this is NOT a new official ID. |
| Master data | Transfer priority | BFPRIOS | Definition of the priority of the stops The transfer priority allows you to select the transfer point if there are several transfer options. It is shown with a value between 0 and 16, where 0 is the highest priority and 16 is the lowest priority. File contains:    * HS no. * Priority * HS name   Example (excerpt):   * If it is possible to change trains in Pregassona, Basel SBB or Basel St. Johann with otherwise equivalent train connections, Basel SBB is preferred.  ``` ... 8500009 16 Pregassona, Scuola Media % HS-Nr. 8500009 Prio Niedrig (16) 8500010  4 Basel SBB                % HS-Nr. 8500010 Prio Erhöht  (4) 8500016 16 Basel St. Johann         % HS-Nr. 8500016 Prio Niedrig (16) ... ``` |
| Master data | Weighting of transfer points | KMINFO | This file is primarily relevant for HAFAS. HAFAS recognises transfer points automatically. This file should therefore only be used to assign numbers of 2 30000 and 0 (see below). In Switzerland, however, it contains more figures. Specifically, various numbers between 0 and 30000. The same figures indicate a similarly manageable changeover. The file differs from BFPRIOS in that it defines closures and transfers in general, i.e. a location can or cannot be used for transfers. The further division is a configuration of the changeover logic used in addition to BFPRIOS. File contains:    * HS no. * Transfer station   + 30000 = transfer point   + 0 = Blocking   + All other numbers are also used to represent transfer points (see above). * HS name   Example (excerpt):   ``` ... 8500009    30 Pregassona, Scuola Media % HS-Nr. 8500009 Umstiegprio. 30 in Pregassona 8500010  5000 Basel SBB                % HS-Nr. 8500009 Umstiegprio. 5000 in Basel SBB -> somit ein bevorzugter Umstiegsort 8500016    23 Basel St. Johann         % ... ... ``` |
| Timetable data | Track and bus platform information | GLEISE\_\*   \*WGS, \*LV95 | List of track and bus platform information.  File contains:   * The first part defines validities, TUs and journeys, which are associated with the track infrastructure in the second part:   + HS no.   + Journey number   + Transport company code   + Track link ID “#…”   + Service running times;   + Days of operation   Example (excerpt):   ``` ... 8500010 000003 000011 #0000001      053751 % HS-Nr. 8500010, Fahrt-Nr. 3, TU-Code 11 (SBB), Link #1, keine Verkehrszeit, Verkehrstage-bit: 053751 (s. BITFELD-Datei) 8500010 000003 000011 #0000002      053056 % ... 8500010 000003 000011 #0000003      097398 % ... 8500010 000003 000011 #0000001      001345 % HS-Nr. 8500010, Fahrt-Nr. 3, TU-Code 11 (SBB), Link #1, keine Verkehrszeit, Verkehrstage-bit: 001345 (!) anders als erste Zeile! ... 8014413 005338 8006C5 #0000001      075277 % ... 8014331 005338 8006C5 #0000003 0025 049496 % HS-Nr. 8014331, Fahrt-Nr. 5338, TU-Code 8006C5 (DB Regio), Link #3, Verkehrszeit 00:25, Verkehrstage-bit: 049496 (s. BITFELD-Datei) 8014281 005339 8006C5 #0000002      080554 % ... ... ```  * The second part describes the infrastructure (tracks or bus platforms) of the stop:   + HS no.   + Track link ID “#…” linked with part 1 in combination with HS no.   + G = track, A = section, T = separator   Description   ``` ... 8500010 #0000004 G '9'  % HS-Nr. 8500010, Link #4, Gleis "9" 8500010 #0000001 G '11' % HS-Nr. 8500010, Link #4, Gleis "11" -> Übereinstimmung mit Erster und vierter Zeile im Beispiel oben!, d.h. die beiden mit unterschiedlichen Gültigkeiten beziehen sich auf Gleis 11 8500010 #0000003 G '12' % ... ... 8014330 #0000001 G '2'  % ... 8014331 #0000001 G '1'  % ... 8014331 #0000002 G '2'  % ... 8014331 #0000003 G '3'  % HS-Nr. 8014331, Link #3, Gleis "3" -> Übereinstimmung mit zweiter Zeile im Zweiten Abschnitt im Beispiel oben! 8014332 #0000002 G '1'  % ... ... ```   This creates the overall picture by linking the two pieces of information.  **IMPORTANT NOTE on \*WGS and \*LV95, as well as “GLEIS” vs “GLEISE”: These two files will replace the “pure” GLEIS and GLEIS\_\* files in Switzerland in 2024. So GLEISE\_WGS and GLEISE\_LV95 remain. Accordingly, we have also documented these directly here.**  With the replacement, **only the second part changes** as follows (*further details on this topic and the implementation in Switzerland can be found in the RV*):   * HS no. * Track link ID “#…” linked with part 1 in combination with HS no. * **Changed**: Track = G, A = Section, g A = Swiss Location ID (SLOID), k = Coordinates (longitude, latitude, altitude)   + Important: contrary to the standard, track and section data are in different lines and not in one! * Description   + ‘ ‘ means no explicit designation at the location   Example (excerpt):   ``` ... 8500207 #0000001 G '1'                    % Hs-Nr. 8500207, Link #1, Gleis "1" 8500207 #0000001 A 'AB'                   % Hs-Nr. 8500207, Link #1, Gleis-Abschnitt "AB" <-> Die verlinkte Fahrt hält an Gleis 1, Abschnitt AB (Tripel HS-Nr., Link, Bezeichnungen) 8503000 #0000002 G '13'                   % ... 8574200 #0000003 G ''                     % Hs-Nr. 8574200, Link #3, Gleis "" <-> Gleis hat keine explizite Bezeichnung am Ort 8574200 #0000003 g A ch:1:sloid:74200:1:3 % Hs-Nr. 8574200, Link #3, SLOID "ch:1:sloid:74200:1:3" <-> Gleis "" hat SLOID wie beschrieben 8574200 #0000003 k 2692827 1247287 680    % Hs-Nr. 8574200, Link #3, Koordinaten 269.. 124.. Höhe 680 <-> Gleis "" mit SLOID hat Koordinaten wie beschrieben ... ``` |
| Transfer data | Transfer time between journeys | UMSTEIGZ | List of journey pairs that have a special transfer relationship. File contains:    * HS no. (see BAHNHOF / STATION) * Journey no. 1 (see FPLAN) * TU code 1 (see BETRIEB / OPERATION\_\*) * Journey no. 2 * TU code 2 * Transfer time in min. * Traffic day bitfield (see BITFELD file) * HS name   Example (excerpt):   ``` ... 1106587 020525 80_BOD 020461 80_BOD 000        Bad Schussenried, Bürgerstüble % HS-Nr 1106587, Fahrt-Nr 020525, TU-Code 80_BOD, Fahrt-Nr 020461, TU-Code 80_BOD, Umsteigezeit 0, HS-Name "Bad..." 8500218 002351 000011 002345 000011 002 056682 Olten                          % HS-Nr 8500218, Fahrt-Nr 002351, TU-Code 000011, Fahrt-Nr 002345, TU-Code 000011, Umsteigezeit 2, Verkehrstage 056682, HS-Name "Olten" 8500218 002351 000011 030351 000011 001 053724 Olten                          % HS-Nr 8500218, Fahrt-Nr 002351, TU-Code 000011, Fahrt-Nr 030351, TU-Code 000011, Umsteigezeit 1, Verkehrstage 053724, HS-Name "Olten" 8500218 031391 000011 031395 000011 003 020311 Olten                          % HS-Nr 8500218, Fahrt-Nr 031391, TU-Code 000011, Fahrt-Nr 031395, TU-Code 000011, Umsteigezeit 3, Verkehrstage 020311, HS-Name "Olten" 8500309 002058 000011 008421 000011 006        Brugg AG                       % ... ... ``` |
| Transfer data | Transfer time at a stop | UMSTEIGB | General transfer time or per stop. The file contains:    * a general default value for all stops if no other, more specific value is defined   Example (excerpt):   ``` 9999999 02 02 STANDARD % Standard Umsteigezeit 2 ```  * one transfer time per stop:   + Transfer time in minutes between service category (means of transport type) IC-IC   + Transfer time for all other offer categories   + HaltestellenName   Example (excerpt):   ``` ... 8389120 05 05 Verona, stazione FS % HS-Nr 8389120, Umsteigzeit IC-IC = 5, Umsteigzeit sonst = 5, HS = Verona 8500010 05 05 Basel SBB           % HS-Nr 8500010, Umsteigzeit IC-IC = 5, Umsteigzeit sonst = 5, HS = Basel  8500020 03 03 Muttenz             % HS-Nr 8500020, Umsteigzeit IC-IC = 3, Umsteigzeit sonst = 3, HS = Muttenz ... ``` |
| Master data | Transfer time between lines | UMSTEIGL | Transfer time per category of service and/or line. The file contains:    * Stop number * Administration 1 (see BETRIEB / OPERATION file) * Type (offer category) 1 * Line 1 (\* = quasi-interchange times) * Direction 1 (\* = all directions) * Administration, type, line, direction 2 * Transfer time in min. * “!” for guaranteed changeover * HaltestellenName   Example (excerpt):   ``` ... 1111145 sbg034 B   7322 H sbg034 TX  7322 H 000! Waldkirch (WT), Rathaus % HS-Nr 1111145, TU-Code sbg034, Angebotskategorie B, Linie 1, Richtung Hin, ... 1111145 sbg034 TX  7322 H sbg034 B   7322 H 000! Waldkirch (WT), Rathaus % HS-Nr 1111145, TU-Code sbg034, Angebotskategorie TX, Linie 1, Richtung Hin, ... 1111145 sbg034 TX  7322 H sbg034 TX  7322 H 000! Waldkirch (WT), Rathaus % ... 8301113 000011 S   *    * 007000 B   *    * 003  Luino (I)               % ... 8301113 007000 B   *    * 000011 S   *    * 003  Luino (I)               % ... 8500010 000011 EC  *    * 000011 TER *    * 010  Basel SBB               % ... 8500010 000011 EC  *    * 085000 TER *    * 010  Basel SBB               % ... 8500010 000011 EXT *    * 000011 TER *    * 010  Basel SBB               % HS-Nr 8500010, TU-Code 11, Angebotskategorie EXT, alle Linien, alle Richtungen, ... ... ``` |
| Master data | Transfer time between transport companies | UMSTEIGV | Transfer time between two transport companies:    * Stop number or @ * Administrative designation 1 * Administrative designation 2 * Minimum transfer time between administrations * Stop designations   Example (excerpt):   ``` ... 8101236 007000 085000 02 Feldkirch      % HS-Nr 8101236, TU-Code 7000,    TU-Code 85000,  Mindestumsteigzeit 2, HS-Name Feldkirch 8101236 81____ 007000 02 Feldkirch      % ... 8500065 000037 000037 00 Ettingen, Dorf % HS-Nr 8500065, TU-Code 000037,  TU-Code 000037, Mindestumsteigzeit 0, HS-Name Ettingen, Dorf ... ``` |

## Further information

### Realisation specifications RV 2.0.6 and 2.0.7

The activation of the adjustments in accordance with the new realisation specifications RV 2.0.6 and 2.0.7 has now been set for 2025-01-21. Both specifications are implemented simultaneously. Test data is available on [Test data sets HRDF realisation specifications 2.0.6 and 2.0.7](https://data.opentransportdata.swiss/en/dataset/hrdf_test_207) .

The following files are affected by the new HRDF version:

**File FPLAN**

\*GR lines are no longer supported
\*SH lines are no longer supported
\*VV lines are now supported. They include

* Estimated delay in minutes
* Stop from which the delay applies
* Stop to which the delay applies
* Departure time
* Time of arrival

*Example*

```
*VV 0010 8507000 8503000 % Expected delay of 10 minutes from HST no. 8507000 to HST no. 8503000
```

**File ATTRIBUT**

The description now starts in column 5 (instead of 4).

*Example (new):*

```
VR  VELOS: Reservation obligatory
VR  BICYCLES: Reservation required
```

*Old:*

```
VR VELOS: Reservation obligatory
VR BICYCLES: Reservation required
```

**Files ATTRIBUT\_DE / ATTRIBUT\_EN / ATTRIBUT\_FR / ATTRIBUT\_IT**

The files ATTRIBUT\_DE, ATTRIBUT\_EN, ATTRIBUT\_FR, ATTRIBUT\_IT are no longer provided. However, the different language variants are all contained in the ATTRIBUT file.

**File BETRIEB**

* First line: Unique identifier (SBOID) (after the “N”) is provided.
* Second line: From version 2.0.7, there can only be one TU code per SBOID.

*Example (new with SBOID):*

```
00244 K "DB " L "DB Regio" V "DB RegioNetz Verkehrs GmbH Westfrankenbahn" N "ch:2:sboid:DE800603"
00244 : 800603
00245 K "DB " L "DB Regio" V "DB RegioNetz Verkehrs GmbH Westfrankenbahn" N "ch:2:sboid:DE8006A7"
00245 : 8006A7
```

*Old (currently without SBOID):*

```
00244 K "DB " L "DB Regio" V "DB RegioNetz Verkehrs GmbH Westfrankenbahn"
00244 : 800603 8006A7
```

**File BHFART**

* From version 2.0.7, only the BHFART file will be made available.
* If known, the global IDs (for Switzerland the Swiss Location ID (SLOID)) of the stop and track are provided.
  + with an “A” as a prefix, the global IDs of the stops are made available
  + With an “a” as a prefix, the global IDs of the tracks are made available
* A stop can have several quays (i.e. places for boarding and alighting at the stop in question, for example). The same quay can be assigned to several stops.
* The “Country” information is provided for each stop with the identifier L
* The “Canton” information is provided for each stop. The information is transmitted with an \*I line and the infotextcode “KT”

*The SLOIDs are already productively exchanged in the BHFART\_60 file.*

```
8501200 G A ch:1:sloid:1200
8501200 L CH % Vevey
8503000 I KT 000001235 (and a corresponding entry in the INFOTEXT file)
8501200 G a ch:1:sloid:1200:3:5
8501200 G a ch:1:sloid:1200:2:2
8501200 G a ch:1:sloid:1200:2:4
8501200 G a ch:1:sloid:1200:1:1
```

**File GLEISE**

The files GLEISE\_WGS and GLEISE\_LV95 will now be available. The other GLEIS\_xx files will no longer be available.

**File KMINFO**

The “Comment” column begins with the special character % from position 21.

*Example (new):*

```
0000140     0       % Gotthard panoramic route
8508253   100       % Heimberg
```

*Old:*

```
0000140     0 Gotthard panoramic route
8508253   100 Heimberg
```

**File ZUGART**

* The mode of transport is now also supplied for each offer category. The information is transmitted with an \*I line and the infotextcode “VM”.
* The attribute “Ausgabesteuerung” now has two digits. The attributes that occur after this are shifted by one position.

*Example (new):*

```
ICE  0 A  0 ICE      0        #030
```

*Old:*

```
ICE  0 A 0 ICE      0        #030
```
