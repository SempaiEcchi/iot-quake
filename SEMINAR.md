# Umreženi sustav za detekciju potresa temeljen na ESP32 i MQTT protokolu

**Seminarski rad iz kolegija Internet stvari (IoT)**

**Autor:** Leo Radočaj
**Ustanova:** Sveučilište Jurja Dobrile u Puli, Fakultet informatike u Puli
**Akademska godina:** 2025./2026.

---

## Sažetak

Rad opisuje dizajn, izradu i verifikaciju umreženog node-a za detekciju potresa. Node je izgrađen na mikrokontroleru ESP32 s akcelerometrom MPU6050, a shake evente objavljuje putem MQTT protokola na lokalni Mosquitto broker. Središnja ideja projekta je **correlation rule**: potres se proglašava tek kada dva međusobno neovisna channela zabilježe event unutar window-a od 2 sekunde. Time se lokalni noise (prolazak kamiona, udarac o stol) odbacuje, dok se ground motion, koji pogađa sve senzore istodobno, prihvaća. Softver je podijeljen na *pure core* bez I/O-a i *thin shell* koji core povezuje s hardverom i mrežom, što je omogućilo automatizirano testiranje cijelog sustava bez fizičkog hardvera. Kalibracijom je izmjeren noise floor senzora od 0,733 gal RMS, na temelju čega je threshold postavljen na 7,33 gal, što odgovara JMA intenzitetu (shindo) 3.

**Ključne riječi:** IoT, ESP32, MPU6050, MQTT, Mosquitto, earthquake detection, correlation, calibration, Docker

---

## 1. Uvod

Japan je jedna od seizmički najaktivnijih regija svijeta i sustavi rane detekcije potresa ondje su dio svakodnevice. Profesionalne seizmičke mreže koriste skupe broadband seizmometre, no posljednjih godina razvijaju se i **dense low-cost sensor arrays** poput Community Seismic Network i MyShake, u kojima velik broj jeftinih MEMS akcelerometara nadoknađuje nižu kvalitetu pojedinog senzora.

Ovaj projekt nastao je u okviru sveučilišnog kolegija iz IoT-a tijekom studentske razmjene u Japanu. Cilj je bio izraditi jedan network-ready node za detekciju podrhtavanja i demonstrirati cjelokupni protokol, od sampliranja senzora preko MQTT komunikacije do korelacije i alarma, uz poštenu procjenu što sustav može, a što ne može.

S IoT stajališta projekt je tipičan *edge* sustav: senzor i detekcija žive na mikrokontroleru, komunikacija ide preko lightweight protokola (MQTT), a agregacija i prikaz na lokalnom serveru. Odluka da sve kritično radi lokalno, a cloud bude opcionalan, donesena je svjesno: sustav za detekciju potresa ne smije ovisiti o internet vezi koja u potresu prva otkaže.

Temeljni problem koji projekt rješava je jednostavan: **jedan akcelerometar ne može razlikovati lokalnu vibraciju od ground motiona.** Zahtjev da se dva channela slože najjeftiniji je način da se ta razlika postigne, jer je lokalni noise lokalan, a ground motion nije.

### 1.1. Ciljevi rada

1. Izraditi hardverski node (ESP32 + MPU6050 + LED + buzzer) koji samplira akceleraciju na 100 Hz i objavljuje evente putem MQTT-a.
2. Implementirati correlator koji proglašava potres samo uz slaganje dvaju različitih channela.
3. Izraditi lokalni web dashboard neovisan o vanjskim servisima.
4. Cijeli sustav učiniti testabilnim bez hardvera.
5. Kalibrirati threshold na temelju **izmjerenog**, a ne pretpostavljenog noise floora.

### 1.2. Ograničenje opsega

Na raspolaganju je bio samo jedan ESP32, pa je drugi channel **simuliran** programom `fake_node.py` koji govori isti MQTT contract. Projekt stoga demonstrira protokol i correlation rule end-to-end, a ne two-point fizičku seizmologiju. Stvarni drugi node je drop-in: dodaje se bez ikakve izmjene koda.

---

## 2. Teorijska podloga

### 2.1. Mjerenje akceleracije tla

Akceleracija tla u seizmologiji se izražava u jedinici **gal** (1 gal = 1 cm/s²; gravitacija ≈ 980,665 gal). Japanska meteorološka agencija (JMA) intenzitet potresa iskazuje ljestvicom **shindo** (震度) od 0 do 7. Iako službeni shindo nije funkcija peak akceleracije, u praksi postoji približna korespondencija koju projekt koristi za **estimate**:

| Shindo | Peak akceleracija (gal) |
|---|---|
| 0 | < 0,2 |
| 1 | 0,2 – 0,8 |
| 2 | 0,8 – 2,5 |
| 3 | 2,5 – 8 |
| 4 | 8 – 25 |
| 5- / 5+ | 25 – 80 / 80 – 140 |
| 6- / 6+ | 140 – 250 / 250 – 400 |
| 7 | > 400 |

### 2.2. MEMS akcelerometar MPU6050

MPU6050 je šestoosni MEMS senzor (akcelerometar + žiroskop) s I2C sučeljem. U rangu ±2 g rezolucija je 16384 LSB/g. Noise density iznosi oko 400 µg/√Hz, što u bandu 0,2–5 Hz daje teorijski noise floor od približno 0,9 gal RMS. Ključno je band-limitirati signal na samom senzoru pomoću ugrađenog DLPF-a (Digital Low-Pass Filter), jer bi na defaultnih 260 Hz noise bio oko 7 puta veći (≈ 6 gal), a sampling na 100 Hz to ne ispravlja: out-of-band noise se aliasira u koristan band umjesto da nestane.

### 2.3. MQTT protokol

MQTT je lightweight publish/subscribe protokol namijenjen uređajima ograničenih resursa. Uređaji komuniciraju preko brokera putem hijerarhijskih topica. Za ovaj projekt korišten je Eclipse Mosquitto broker pokrenut u Docker containeru na laptopu, bez TLS-a i autentifikacije, jer je mreža izolirani mobile hotspot.

### 2.4. Docker i reproducibilno okruženje

Broker (i opcionalni Thingsboard) pokreću se kao Docker containeri preko `docker-compose.yml`. Time je infrastruktura reproducibilna na bilo kojem laptopu jednom naredbom (`docker compose up -d`), a Thingsboard je izdvojen u zasebni compose profile (`--profile cloud`) jer je težak (~2 GB) i nije nužan za rad sustava. Mosquitto ima definiran healthcheck, pa testovi mogu pouzdano čekati da broker bude spreman.

### 2.5. Korelacija kao sredstvo diskriminacije

Ideja je preuzeta iz dense sensor networka: pojedini senzor je nepouzdan, ali **istodobnost** na prostorno odvojenim senzorima jest pouzdan signal. Ako N ≥ 2 različitih node-ova zabilježi event unutar kratkog time window-a, vjerojatnost da je uzrok lokalni noise drastično pada.

---

## 3. Arhitektura sustava

```
[ESP32 + MPU6050] ──┐                     ┌──► quake/alarm ──► buzzer
                    ├──► Mosquitto ──┬──► correlator ──┴──► Thingsboard (optional)
[fake_node.py]    ──┘   (laptop)     │
                                     └──► dashboard ──► http://localhost:8000
```

Sustav se sastoji od četiri komponente:

| Komponenta | Tehnologija | Uloga |
|---|---|---|
| Node | ESP32, C++ (Arduino) | Samplira senzor, detektira shake, publisha evente, pali LED, oglašava buzzer na alarm |
| Broker | Mosquitto 2 (Docker) | Posrednik svih poruka |
| Correlator | Python, paho-mqtt | Subscribean na evente svih node-ova, primjenjuje correlation rule, publisha alarm |
| Dashboard | Python, HTTP + SSE | Live prikaz stanja u browseru |

Dvije arhitektonske odluke vrijedi istaknuti:

1. **Dashboard subscribea izravno na broker, a ne čita iz correlatora.** Detekcija ne smije ovisiti o tome je li browser otvoren; gašenje dashboarda ne mijenja ništa u ponašanju alarma.
2. **Broker ostaje lokalan.** Demo preživljava nestanak interneta: eventi, korelacija, alarm i buzzer rade i dalje, samo se opcionalni Thingsboard cloud zamrači. Bridge prema cloudu živi u correlatoru, a ne u firmwareu, pa node ostaje plaintext bez TLS-a.

### 3.1. Pure core i thin shell

Obje polovice softvera slijede isti pattern: **pure core** bez I/O-a i **thin shell** koji ga povezuje sa svijetom.

| Pure core | Shell |
|---|---|
| `firmware/node/detector.cpp` — bez Arduino headera | `firmware/node/node.ino` — Wire, WiFi, MQTT |
| `correlator/core.py` — bez networka | `correlator/main.py` — paho-mqtt, Thingsboard |
| — | `dashboard/server.py` — MQTT + HTTP, read-only |

Core-ovi primaju vrijeme kao parametar (`now_ms`, `now`), nikada ga ne čitaju sami. Zato ih je moguće unit-testirati na laptopu s fake akceleracijom i fake vremenom, što je razlog zašto hardverski projekt može imati prave automatizirane testove.

### 3.2. MQTT contract

| Topic | Smjer | Payload |
|---|---|---|
| `quake/<node_id>/event` | node → broker | `{"node","peak_gal","dur_ms"}` na trigger |
| `quake/<node_id>/tel` | node → broker | `{"node","dev_gal","uptime_s"}` na 1 Hz |
| `quake/alarm` | correlator → node | `{"nodes":[...],"peak_gal"}` |

Node ID izvodi se iz zadnja tri bajta WiFi MAC adrese (npr. `node-a4c1f8`). Simulirani channel koristi prefiks `sim-`, a mirror channel `mirror-`, tako da se u logu ili na screenshotu nikada ne mogu zamijeniti sa stvarnim mjerenjem. Topic prefiks (`QUAKE_PREFIX`) omogućuje da testovi i stvarni hardver dijele isti broker bez međusobnog koreliranja.

---

## 4. Hardver

### 4.1. Bill of materials (~¥3.100)

| Komponenta | Kol. | Cijena |
|---|---|---|
| ESP32-DevKitC-32E / FREENOVE FNK0090 (ESP32-WROOM-32E, 4 MB) | 1 | ¥1.800 |
| MPU6050 / GY-521 akcelerometar modul | 1 | ~¥300 |
| Aktivni buzzer, 3-pin modul | 1 | ~¥100 |
| Breadboard | 1 | ~¥300 |
| Jumper wires | 1 set | ~¥400 |
| LED 5 mm + otpornik 330 Ω | 1 | ~¥200 |

### 4.2. Wiring

```
MPU6050        ESP32
  VCC   ──────  3V3        (3,3 V, NE 5 V)
  GND   ──────  GND
  SCL   ──────  GPIO27
  SDA   ──────  GPIO26

LED    ──────  GPIO2   (onboard na FNK0090)
Buzzer ──────  GPIO25
```

Tijekom izrade dokumentirano je nekoliko empirijskih činjenica koje se ne vide iz datasheeta: FNK0090 ima 40 pinova (ne 38), buzzer je **active-LOW**, a MPU6050 treba ~100 ms nakon power-upa prije prvog I2C upita, inače svaki boot lažno prijavljuje "NO SENSOR". Za dijagnostiku su napisani zasebni sketchevi (`i2c_scan`, `i2c_diag`, `pin_sweep`, `buzzer_test`, `calibrate`).

---

## 5. Firmware node-a

### 5.1. Sampling

Sampling je na 100 Hz, vođen `micros()` timerom. Sve tri osi čitaju se preko I2C na ±2 g, magnituda se pretvara u gal (`gal = g · 980,665`). DLPF registar (`0x1A`, `DLPF_CFG = 6`) postavlja bandwidth senzora na 5 Hz.

Sample gate se **resyncira umjesto da sustiže** ako zaostane više od 10 perioda:

```cpp
if (micros() - next_sample_us > 10 * SAMPLE_US) next_sample_us = micros();
else                                            next_sample_us += SAMPLE_US;
```

Bez toga bi svaki stall u `loop()`-u (npr. blocking `mqtt.connect()` prema nedostupnom brokeru) izazvao burst stotina samplova s gotovo istim timestampom, koji korumpira baseline filtra. Uz to su MQTT reconnecti implementirani s exponential backoffom (2 s → 30 s), jer je blocking reconnect jednom srušio stvarni sample rate sa 100 Hz na 1 Hz.

### 5.2. Detection algoritam

```
dev      = |mag - baseline|        // prema PRETHODNOM baselineu
baseline = 0,99 · baseline + 0,01 · mag
if dev > THRESHOLD and not in_refractory:
    trigger()
```

Exponential moving average (EMA) djeluje kao single-pole high-pass filter: uklanja gravity offset od ~980 gal bez filter biblioteke i prilagođava se ako se node nagne. Deviation se računa prema **prethodnom** baselineu kako bi jedan spike prijavio punu amplitudu, a ne onu već razrijeđenu samim sobom.

Dva detalja bez kojih sustav loše radi:

- **Warm-up:** prve 3 sekunde nakon boota svi triggeri su potisnuti dok se EMA ne smiri.
- **Refractory period:** nakon triggera, daljnji triggeri ignoriraju se 5 sekundi. Event se publisha kad se window **zatvori**, pa je `peak_gal` stvarni peak, a `dur_ms` trajanje od triggera do zadnjeg samplea iznad thresholda. Jedan shake tako daje jedan event, a ne stotine.

### 5.3. Signalizacija

LED se pali lokalno na trigger vlastitog channela. Buzzer se oglašava **samo** na primljenu `quake/alarm` poruku. Ta podjela demo čini čitljivim: **LED znači "ovaj channel je nešto osjetio", buzzer znači "mreža se slaže".**

### 5.4. Error handling

| Stanje | Ponašanje |
|---|---|
| MPU6050 ne odgovara na bootu | LED blinka na 5 Hz, retry svakih 5 s. Nikada ne publisha smeće. |
| I2C read faila usred rada | Sample se skipa. Detektoru se nikada ne šalje izmišljena vrijednost. |
| WiFi/MQTT veza izgubljena | Detekcija i LED rade dalje. Eventi tijekom outagea se dropaju, ne queueaju, jer bi stale timestamp korumpirao correlatorov window. |
| Broker promijenio IP | Node resolvea broker preko mDNS-a (`MQTT_HOSTNAME`), s literal IP-om kao fallbackom. |
| Correlator ne radi | Node publisha normalno, LED radi, buzzer šuti. |

### 5.5. Mirror channel i simulirani mode

Firmware podržava dva channela po node-u (`NCHAN = 2`). Channel A je stvarni MPU6050 na adresi `0x68`. Channel B je predviđen za drugi senzor na `0x69` (AD0 high), no dok hardvera nema, radi kao **mirror**: ponavlja iste samplove kao channel A pod drugim node ID-em (`mirror-<id>`), tako da correlator ima dva izvora i alarm path (buzzer, dashboard) može se demonstrirati s jednim senzorom.

Mirror **nije mjerenje** i kod to naglašava na svakom mjestu: boot log ispisuje `MIRROR of <node> - not an independent measurement`, dashboard ga označava jednako kao sintetičke channele, a svaki alarm koji ga uključuje demonstrira alarm path, ne ground motion. Neoznačeni mirror izgledao bi kao potvrda, što bi bila laž.

Postojao je i **simulated mode** (`SIM_ENABLED`) u kojem channel bez senzora generira sintetičku akceleraciju (gravitacija + noise + burst na pritisak BOOT tipke). Isključen je čim je stigao stvarni senzor, jer su se fabricirani eventi počeli miješati sa stvarnima u earthquake logu. Channel bez senzora sada ne publisha ništa i to jasno kaže: vidljiv failure umjesto uvjerljive laži.

---

## 6. Correlator

Correlator je Python servis subscribean na `quake/+/event`. Održava listu nedavnih eventa s **arrival** timestampom. Pri svakom eventu odbacuje unose starije od 2 s i broji **distinct** node ID-eve. Ako ih je ≥ 2, publisha `quake/alarm` s maksimalnim `peak_gal` i ulazi u 10-sekundni cooldown, tako da jedan potres proizvodi jedan alarm.

```python
def add_event(self, node_id, peak_gal, now):
    self._recent.append((node_id, peak_gal, now))
    self._recent = [e for e in self._recent if now - e[2] <= self.window_s]
    if self._last_alarm_at is not None and now - self._last_alarm_at < self.cooldown_s:
        return None
    nodes = {e[0] for e in self._recent}
    if len(nodes) < self.min_nodes:
        return None
    ...
    return Alarm(nodes=sorted(nodes), peak_gal=max(e[1] for e in self._recent))
```

Zahtjev za **distinct** ID-evima sprječava da dva eventa s istog channela lažno simuliraju slaganje. Arrival-time stamping razlog je zašto nije potrebna clock sinkronizacija (NTP): MQTT latency je ~100 ms naspram window-a od 2 s.

Correlator je ujedno i **bridge prema cloudu**: ako je postavljen `TB_TOKEN`, telemetriju, evente i alarme forwarda na Thingsboard (`v1/devices/me/telemetry`). Ako Thingsboard nije dostupan, correlator to logira i nastavlja raditi local-only. Cloud outage nikada ne smije srušiti lokalnu detekciju.

Correlator ujedno iz peak akceleracije izračunava **estimated** shindo (tablica u `core.py`, koju dashboard importa umjesto da je kopira, tako da se dvije kopije ne mogu razići). Magnituda se **namjerno ne prikazuje**: ona opisuje energiju na izvoru i zahtijeva udaljenost epicentra i dubinu, što jedna postaja ne može dati.

---

## 7. Dashboard

`dashboard/server.py` je presentation layer: jedna self-contained HTML stranica na `localhost:8000`, bez accounta, bez vanjskog servisa i bez build stepa. Server subscribea na iste MQTT topice kao correlator i stanje pusha u browser putem server-sent events (SSE). Prikazuje:

- live channele s trace grafom `dev_gal` i online/offline statusom (5 s bez telemetrije = offline),
- event log s istaknutim alarmima,
- countere: eventi, alarmi i **rejected** eventi — svaki event koji nije postao dio alarma bio bi na single-channel dizajnu false alarm, što je headline brojka rada,
- oznaku "simulated" za channele s prefiksom `sim-`, `mock-` ili `mirror-`.

Thingsboard je spojen iza `docker compose --profile cloud` za slučaj da rubrika zahtijeva imenovanu IoT platformu, ali ništa o njemu ne ovisi.

---

## 8. Testiranje

Cijeli sustav može se pokrenuti i testirati na laptopu bez ESP32-a. Mock node (`sim/mock_node.py`) generira sintetičku akceleraciju, izvodi **isti detection algoritam kao firmware** (Python port u `sim/detector.py`) i govori stvarni MQTT contract.

| Test suite | Br. | Broker? | Što dokazuje |
|---|---|---|---|
| `test/test_detector.cpp` | 6 | ne | Algoritam u **firmwareu** je ispravan |
| `sim/test_parity.py` | 6 | ne | **Python port** daje identične rezultate, pa je mock vjeran |
| `correlator/test_core.py` | 11 | ne | Correlation rule je ispravan |
| `sim/test_e2e.py` | 3 | da | Cijeli loop radi: mock node-ovi → alarm → buzzer |
| `dashboard/test_dashboard.py` | 6 | da | Dashboard ispravno agregira state |

Mock namjerno **ne testira** ono što traži stvarni hardver: I2C komunikaciju, WiFi reconnect, 100 Hz sample gate pod stvarnim opterećenjem i pitanje je li stol dovoljno miran. Mock dokazuje da je *logika* ispravna; hardverski test plan dokazuje da je *sustav* ispravan.

Parity test je load-bearing: ako padne, mock se razišao od firmwarea i rezultati simulacije prestaju nešto značiti. Testovi correlatora pokrivaju slučajeve poput: jedan node ne alarmira, isti node dvaput ne alarmira, dva node-a unutar window-a alarmiraju, izvan window-a ne, cooldown potiskuje drugi alarm, tri node-a daju samo jedan alarm.

Hardverski test plan obuhvaća: sensor sanity rotacijom kroz sve osi (magnituda ≈ 980 gal), warm-up, **single-node rejection** (LED bez buzzera), correlated detection, refractory period (20 s shakeanja = 3 eventa, ne stotine) i resilience (gašenje brokera ne prekida LED).

---

## 9. Rezultati

### 9.1. Noise floor

Kalibracija 21. 8. 2026. sketchem `firmware/calibrate`, board nepomičan na stolu, 177 s na 100 Hz, prve 3 s odbačene:

| | |
|---|---|
| Samplova | 17 675 |
| Trajanje | 176,8 s |
| **RMS** | **0,733 gal** |
| Peak | 3,295 gal (4,5 σ) |

Dizajn je predvidio ~0,9 gal. Izmjereni 0,733 gal je **ispod** toga, što odgovara na otvoreno pitanje iz speca: noise floor je **sensor-dominated, a ne building-dominated**. DLPF na 5 Hz radi svoj posao.

### 9.2. Izbor thresholda

| Multiplier | Threshold | Samplova iznad (177 s) | Ekstrapolirano po satu |
|---|---|---|---|
| 3× | 2,20 gal | 60 | 1222 |
| 5× | 3,67 gal | 0 | 0 |
| **10×** | **7,33 gal** | **0** | **0** |

Odabran je **10× = 7,33 gal**. Spec je preporučio 5× pod pretpostavkom noise floora 0,9 gal, gdje bi 10× dalo 9 gal, iznad gornje granice shindo 3. Izmjereni floor je niži, pa 10× pada na 7,33 gal i i dalje je unutar shindo 3 (2,5–8 gal). Multiplier 5× odbačen je na temelju dokaza: postavio bi threshold na 3,67 gal naspram peaka od 3,295 gal zabilježenog u samo tri minute tihe sobe. Taj peak je 4,5 σ, heavier-tailed od Gaussove razdiobe, pa estimate "~1 false trigger u dva dana" ne vrijedi u ovom okruženju. **Upravo zato plan zabranjuje pogađanje thresholda.**

### 9.3. Detection floor

Na 7,33 gal node triggera na shindo 3 i više. Shindo 1–2 je ispod noise floora senzora i nije detektabilan s MPU6050, što je hardversko, a ne tuning ograničenje.

### 9.4. Sample rate

Potvrđeno 100 Hz flat preko health linea node-a. Ranije mjerenje pokazalo je 1 Hz, uzrokovano blocking MQTT reconnectima; ispravljeno exponential backoffom.

### 9.5. Demo

1. Node se protrese dok je simulirani channel zaustavljen: LED svijetli, event se publisha, **nema alarma**. Ta rejection je u potpunosti stvarna.
2. Node se protrese uz istodobni trigger simuliranog channela: LED, buzzer, alarm na dashboardu.

---

## 10. Tijek razvoja i naučene lekcije

Projekt je vođen kroz git s malim, opisnim commitovima (od design speca 30. 7. 2026. do zadnjeg fixa 21. 8. 2026.). Nekoliko bugova pronađenih na stvarnom hardveru vrijedi zabilježiti jer se nijedan nije mogao vidjeti u simulaciji:

| Simptom | Uzrok | Fix |
|---|---|---|
| Buzzer neprekidno svira, utihne 1,5 s na alarm | Modul je active-LOW, suprotno od pretpostavke | `BUZZ_ON = LOW`, `BUZZ_OFF = HIGH` svugdje, uključujući dijagnostičke sketcheve |
| Sample rate 1 Hz umjesto 100 Hz | Blocking `mqtt.connect()` prema nedostupnom brokeru stallao `loop()` | Exponential backoff 2 s → 30 s, socket timeout 2 s, sample gate resync |
| Node "radi", ali nikad ne dođe do brokera | DHCP lease laptopa promijenio IP (.24 → .17 → .24) | mDNS resolve `MQTT_HOSTNAME` s literal IP-om kao fallbackom |
| Svaki boot prijavljuje `NO SENSOR`, pa se "oporavi" | MPU6050 probe odmah nakon `Wire.begin()`, senzor treba ~100 ms | 150 ms settle prije prvog I2C upita |
| Fabricirani eventi u earthquake logu | Simulirani channel auto-firao svakih 12 s uz stvarni senzor | `SIM_ENABLED 0`, timer isključen, BOOT tipka jedini trigger |
| Svaki alarm prijavljuje shindo 5+ | Simulirani shake bio 80 gal, alarm nosi max preko channela | Simulirani shake 12 gal (shindo 4) |

Zajednička lekcija: **fizika i mreža lažu na načine koje simulacija ne može predvidjeti**, pa je vrijednost simulacije u tome da logika bude ispravna prije hardvera, a ne u tome da hardver zamijeni. Druga lekcija je da sintetički podaci, čim postoje stvarni, postaju kontaminacija; svaki sintetički izvor mora biti označen na razini protokola, a ne samo u dokumentaciji.

---

## 11. Ograničenja

Navedena unaprijed, a ne zakopana:

- **Drugi channel je simuliran.** Two-point fizička diskriminacija nije demonstrirana; protokol i correlation rule jesu.
- **Stvarni potres neće podići alarm.** Trese samo stvarni node, a simulirani channel triggera se ručno. Stvarni eventi dokazuju se iz event loga cross-checkanog s JMA podacima.
- **Korelacija odbija samo channel-local noise.** I s pravim drugim senzorom, noise koji se prenosi podom (koraci) stiže do svih senzora i korelira. Samo amplitude threshold to odbija.
- **Nema epicentra**: zahtijeva sub-millisecond timing, što WiFi ne daje.
- **Nema službenog JMA shinda ni magnitude**: samo peak akceleracija u gal i estimated intenzitet.
- **Detection floor oko shindo 3.**

---

## 12. Zaključak

Projekt je isporučio funkcionalan umreženi node za detekciju potresa i cjelovit put od senzora do alarma: sampling na 100 Hz s band-limitom u senzoru, EMA detekciju s warm-upom i refractory periodom, MQTT contract s tri topica, correlator s pravilom "dva distinct channela unutar 2 s" i lokalni dashboard neovisan o internetu.

Tri metodološke odluke pokazale su se najvrjednijima:

1. **Pure core odvojen od shella** omogućio je da hardverski projekt ima 32 automatizirana testa i da se većina bugova pronađe prije nego što je hardver stigao.
2. **Mjerenje umjesto pretpostavljanja.** Izmjereni noise floor od 0,733 gal preokrenuo je preporuku iz speca (5× → 10×) i pokazao da je floor sensor-dominated, a ne building-dominated.
3. **Poštenje o ograničenjima.** Simulirani i mirror channeli označeni su prefiksima na razini protokola, tako da ih nijedan log, dashboard ni report ne može prikazati kao neovisno mjerenje.

Iz IoT perspektive projekt pokriva cijeli stack: senzor i edge obradu (ESP32, C++), protokol (MQTT, Mosquitto), backend logiku (Python correlator), prezentaciju (web dashboard) i opcionalnu cloud integraciju (Thingsboard), uz containeriziranu infrastrukturu (Docker) i automatizirane testove.

Prirodni upgrade je drugi MPU6050 na adresi `0x69` (AD0 high) ili drugi ESP32; oboje je drop-in bez izmjene koda. Tek time bi se demonstrirala stvarna two-point diskriminacija.

---

## Literatura

1. Community Seismic Network, Caltech. https://csn.caltech.edu/
2. MyShake, Berkeley Seismology Lab. https://myshake.berkeley.edu/
3. Japan Meteorological Agency. *Tables explaining the JMA Seismic Intensity Scale.* https://www.jma.go.jp/jma/en/Activities/inttable.html
4. Japan Meteorological Agency. *Seismic intensity database.* https://www.data.jma.go.jp/eqdb/data/shindo/
5. InvenSense. *MPU-6000 and MPU-6050 Product Specification*, Rev. 3.4.
6. InvenSense. *MPU-6000 and MPU-6050 Register Map and Descriptions*, Rev. 4.2.
7. OASIS. *MQTT Version 5.0 Specification*, 2019.
8. Eclipse Foundation. *Eclipse Mosquitto — An open source MQTT broker.* https://mosquitto.org/
9. Espressif Systems. *ESP32 Series Datasheet.*
10. Izvorni kod projekta i dokumentacija: `README.md`, `TESTING.md`, `docs/RESULTS.md`, `docs/superpowers/specs/2026-07-30-esp32-quake-node-design.md`.
