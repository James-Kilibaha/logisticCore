# logisticCore - Backend (FastAPI + PostgreSQL) - SaaS

Mfumo wa usafirishaji wa mizigo kwa **kampuni nyingi** (multi-tenant): mteja → ankara → bidhaa → mpokeaji →
box → usafirishaji → stoo → malipo → kukabidhi. Umetokana na TransportCore; kila kampuni ya usafirishaji
ni mteja wako, inalipia subscription, na inaona data yake peke yake.

```
WEWE (platform admin)  ── /api/platform/...   kampuni, mipango, malipo, backup, hali ya server
   └── Kampuni A (tenant) ── /api/...          wateja, ankara, mabox ... (kama TransportCore)
   └── Kampuni B (tenant) ── /api/...          data yake tu - haioni ya A
```

## SaaS kwa ufupi

### Kampuni inatambuliwaje? (`saas/middleware.py`)
1. token ya mtumiaji aliyeingia (claim `cid`) - token ya kampuni moja haifanyi kazi kwenye nyingine
2. `?company=<code>` (GET tu - viungo vya umma, logo)
3. header `X-Company: <code>` (app ya simu)
4. domain: domain ya kampuni (`ymg.co.tz`) au `<code>.<PLATFORM_DOMAIN>`
5. `DEV_COMPANY_SLUG` (development tu)

Kampuni isipojulikana, hakuna data inayorudishwa (fail closed).

### Kutenganisha data (`core/tenant.py`, `db.py`)
- Kila table inayorithi `EntityBase` ina `company_id`. **Kila query ya ORM inachujwa yenyewe** kwa kampuni ya
  request (`with_loader_criteria`) na kila rekodi mpya inaandikwa `company_id` yake - dao/service za zamani
  hazikuhitaji kubadilishwa.
- Vitu vya kipekee sasa ni vya kipekee ndani ya kampuni: jina la mtumiaji, simu, namba ya ankara, track number,
  boxId, code ya ofisi ... (kampuni mbili zinaweza kuwa na mtumiaji "admin").
- Mafaili: `FILES_DIR/<company_id>/Images|Report|Handover|Claims|Branding`.
- `config.COMPANY_NAME`, `config.DAYS_TO_CHARGE`, `config.SMS_SOURCE_NAME` ... (tazama `config.TENANT_KEYS`)
  zinasoma mipangilio ya kampuni ya request (`saas/company/settings.py`); isipoweka, thamani ya `.env`.
- Scheduler: kazi za kampuni zinaendeshwa kwa kila kampuni (`tenant.for_each_company`).

### Subscription (`saas/subscription/`)
| Hali | Maana |
|---|---|
| `TRIAL` / `ACTIVE` | kazi zote |
| `GRACE` | imeisha ndani ya `SUBSCRIPTION_GRACE_DAYS` - kazi zote bado |
| `EXPIRED` / `NONE` | **kusoma tu**: POST/PUT/DELETE zinajibiwa `402 {"code": "SUBSCRIPTION_EXPIRED"}` |
| kampuni `SUSPENDED` | `403 {"code": "COMPANY_SUSPENDED"}` kwa kila kitu |

- Mipango (`plans`): bei, miezi, mipaka (watumiaji, ofisi, ankara kwa mwezi) na moduli za ziada
  (WHATSAPP, BROADCAST, QUOTE, CLAIM, CASHUP, PROFIT, IMPORT, AUDIT). Mpango usio na moduli -> `402`.
  Mipango 3 ya kuanzia (Starter / Business / Enterprise) inaundwa mara ya kwanza - ibadilishe kwenye admin panel.
- Malipo: kampuni inatuma taarifa (`POST /api/company/subscription/payment`, PENDING) -> wewe unathibitisha
  (`PUT /api/platform/subscriptions/payments/{id}/confirm`) -> kipindi kinaongezwa chenyewe.
  Au unarekodi malipo moja kwa moja (`POST /api/platform/subscriptions/payments`).
- Vikumbusho: kila siku saa 3:20 asubuhi (SMS kwa mmiliki + taarifa kwenye app) siku `SUBSCRIPTION_REMIND_DAYS`.

### Endpoints mpya
| Endpoint | Kazi |
|---|---|
| `GET /api/public/branding` | jina, logo, rangi za kampuni (kabla ya kuingia) |
| `GET /api/public/branding/logo` | logo |
| `GET /api/public/plans` | mipango ya umma |
| `GET /api/public/company-check/{code}` | code ya kampuni inapatikana? |
| `POST /api/public/signup` | kampuni inajisajili (majaribio `TRIAL_DAYS`) |
| `GET /api/company` / `GET /api/company/me` | wasifu + mipangilio + subscription / branding + subscription |
| `PUT /api/company/profile`, `PUT /api/company/settings` | jina, rangi... / SMS, WhatsApp, stoo, ETA ... |
| `POST/DELETE /api/company/logo` | logo ya kampuni |
| `GET /api/company/subscription`, `POST .../payment` | hali, matumizi, historia / kutuma taarifa ya malipo |
| `POST /api/platform/login`, `GET /api/platform/dashboard` | admin panel yako |
| `/api/platform/companies` | orodha, kuunda, kubadilisha (slug, domain), kuzuia, kufuta, logo, kumrudishia mtu nywila |
| `/api/platform/plans` | mipango |
| `/api/platform/subscriptions/...` | malipo (kuthibitisha/kukataa/kurekodi), kuongeza siku, kubadilisha mpango |
| `/api/platform/server/...` | hali ya server, tahadhari, backup (zimetoka kwenye app ya kampuni) |

### Kuanza
```bash
cp .env.example .env          # weka ADMIN_USERNAME/ADMIN_PASSWORD (wewe), PLATFORM_DOMAIN, SECRET_KEY ...
python main.py                # inaunda database, tables, platform admin na mipango ya kuanzia
pytest -q                     # tests za SaaS (PostgreSQL halisi)
```
Kisha: kampuni zinajisajili kwenye app ("Fungua akaunti"), au unaziunda kwa `POST /api/platform/companies`.

### Kuhamisha data ya TransportCore (YMG)
1. Unda kampuni (mf. code `ymg`, domain `ymg.co.tz`) kwa `POST /api/platform/companies`.
2. Rejesha backup ya TransportCore kwenye database ya logisticCore, weka `DEFAULT_COMPANY_SLUG=ymg`, washa server:
   rekodi zote zisizo na kampuni zinapewa `ymg`. Nakili folda la mafaili `YMG/...` kwenda `FILES_DIR/<company_id>/`
   na ubadilishe njia (`products.path` n.k.) - au anza na database mpya.

## Muundo wa folders

Kila feature ina folder lake lenye faili 5:

| Faili        | Kazi yake                                                              |
|--------------|------------------------------------------------------------------------|
| `model.py`   | Jedwali la database (SQLAlchemy) - *create table*                      |
| `schema.py`  | Data entity za request/response (Pydantic v2)                          |
| `dao.py`     | Query zote za database (insert, update, delete, select) - hakuna logic |
| `service.py` | Business logic (sheria, uhakiki, kuunganisha dao)                      |
| `router.py`  | REST API (endpoints + ruhusa) - nyembamba, inaita service tu           |

```
logisticCore/
├── main.py                 # python main.py
├── .env / .env.example     # mipangilio yote (database, JWT, SMS, ...)
├── requirements.txt
├── alembic/                # migrations
├── assets/sample/          # template za Word za invoice na ripoti
├── tests/                  # test za mtiririko mzima (PostgreSQL halisi)
└── logistic/
    ├── config.py           # inasoma .env (+ mipangilio ya kila kampuni: TENANT_KEYS)
    ├── db.py               # engine, session, get_db, init_db (inaunda database na tables)
    ├── app.py              # inaunganisha routers, CORS, errors, scheduler
    ├── models.py           # orodha ya models zote (kwa create_all na alembic)
    ├── core/               # vitu vya pamoja
    │   ├── base_model.py   #   id, isBlocked, created_at, update_at, logsId
    │   ├── dao.py          #   BaseDao (get, find_one, find_all, create, update, delete)
    │   ├── security.py     #   argon2 + JWT
    │   ├── permission.py   #   require(Module.X, Action.Y) - ukaguzi wa ruhusa
    │   ├── exceptions.py   #   NotFound, Conflict, PermissionDenied -> {"detail": "..."}
    │   ├── documents.py    #   Word -> PDF (invoice na ripoti)
    │   ├── files.py        #   picha na PDF (FILES_DIR)
    │   ├── scheduler.py    #   kazi za kila saa 2 / 6
    │   ├── enums.py        #   EInvoiceStatus, EPaymentStatus, ESmsStatus, Module, Action
    │   └── utils.py
    ├── auth/               # login (router, service, schema)
    ├── user/               # model, schema, dao, service, router
    ├── permission/
    ├── customer/
    ├── invoice/
    ├── product/
    ├── receiver/           # (zamani: receiveInspection)
    ├── package/
    ├── store/              # stoo - haina table (inatumia invoice/package/customer)
    ├── payment/            # Debt + Payment
    ├── expense/            # (zamani: expence)
    ├── report/             # ripoti za PDF (dao ya query za ripoti)
    ├── sms/
    ├── saas/               # SaaS: middleware (kampuni ya request), company, plan, subscription, admin, public
    └── settings/
        ├── currency/       # kila sehemu ina model, schema, dao, service, router
        ├── price/
        ├── sms_set/
        ├── institute/
        └── office/
```

Mtiririko wa request: `router` → `service` → `dao` → database.

## Kuendesha

```bash
python -m venv venv
venv\Scripts\activate            # Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # kisha jaza thamani zako (au tumia .env iliyokuja)
python main.py                   # http://localhost:8000/docs
```

Database:
- Database (`DATABASE_NAME`) **inaundwa yenyewe** kama haipo, pamoja na tables zote, kupitia `config.py` na `db.py`.
- Database iliyopo haiguswi: tables, columns na constraints ni zilezile za awali (zimelinganishwa kwa `pg_dump`).
- `ADMIN_USERNAME`/`ADMIN_PASSWORD` kwenye `.env` = **wewe** (platform admin), anaundwa mara moja tu.
  Msimamizi wa kila kampuni anaundwa kampuni ikisajiliwa (signup au admin panel) na anapewa ruhusa zote za kampuni yake.

PDF:
- Windows inatumia MS Word (`docx2pdf`).
- Linux inatumia LibreOffice (`soffice`), ambayo inatafutwa yenyewe; unaweza pia kuweka `LIBREOFFICE_PATH`.

Migrations (database iliyopo):
```bash
alembic stamp head                               # mara moja tu
alembic revision --autogenerate -m "maelezo"     # baada ya kubadilisha model
alembic upgrade head
```

Tests (zinatumia PostgreSQL; database ya `TEST_DATABASE_NAME` inafutwa na kuundwa upya):
```bash
pytest -q
```

## Kuongeza feature mpya (mfano: `member`)

1. `logistic/member/model.py`: `class Member(AuditedEntity): __tablename__ = "members" ...`
2. `schema.py`: `Create`, `Update`, `Filter`.
3. `dao.py`: `class MemberDao(BaseDao[Member]): model = Member` + query maalum.
4. `service.py`: logic (`create`, `update`, ...) zinazotumia `MemberDao(db)`.
5. `router.py`: `APIRouter(prefix="/api/member")` + `Depends(require(Module.MEMBER, Action.INSERT))`.
6. Ongeza model kwenye `logistic/models.py`, router kwenye `ROUTERS` (`logistic/app.py`),
   na `MEMBER` kwenye `Module` (`core/enums.py`) ili watumiaji wapate mstari wa ruhusa.

## Endpoints mpya za app (v2)

| Endpoint | Kazi |
|---|---|
| `GET /api/dashboard/summary` | Takwimu za dashboard (ankara kwa hatua, madeni, mapato, mabox, SMS) |
| `GET /api/permission/me` | Ruhusa za mtumiaji aliyeingia (app inaficha menyu asizoruhusiwa) |
| `GET /api/package/available-products` | Bidhaa zilizo tayari kupakiwa (invoice za PARKING ambazo hazipo kwenye box) |
| `GET /api/package/{id}/products` | Bidhaa zilizo ndani ya box, pamoja na ankara/mteja/mpokeaji |
| `PUT /api/package/remove-product-package` | Kutoa bidhaa kwenye box ambalo bado halijafungwa |

Mabadiliko madogo:
- `history` na `status` si lazima tena (receiver, close-package, is-correct-package, change-status): server inaziandika yenyewe.
- Picha ya bidhaa si lazima (`POST /api/product` bila `file`).
- `POST /api/invoice/search` inarudisha pia `customer`.
- `POST /api/expenses/search` inakubali `startDate` / `endDate`.

## Ulinzi wa data (v2.1)

### Backup
- Kila siku saa `BACKUP_HOUR` server inatengeneza `ymg_backup_YYYYMMDD_HHMMSS.zip` ndani ya `BACKUP_DIR`:
  `database.sql` (pg_dump) + `files/` (picha na PDF). Backup `BACKUP_KEEP` za mwisho zinabaki.
- **Weka `BACKUP_MIRROR_DIR`** (disk ya nje au folder la Google Drive/OneDrive) - backup iliyo kwenye
  server moja haikulindi server ikiharibika.
- SaaS: backup ni ya database nzima (kampuni zote) - inasimamiwa na wewe: `/api/platform/server/backups`.
- Amri:
  ```bash
  python -m logistic.backup create
  python -m logistic.backup list
  python -m logistic.backup restore /njia/ymg_backup_20261014_020000.zip   # inabadilisha data yote!
  ```
- Windows: weka `PG_DUMP_PATH` na `PSQL_PATH` (mfano `C:\Program Files\PostgreSQL\16\bin\pg_dump.exe`).

### Audit log (nani alifanya nini)
- Kila request inayobadilisha data (POST/PUT/DELETE) inarekodiwa yenyewe kwenye `audit_logs`:
  mtumiaji, muda, moduli, kitendo, id ya kitu, IP, matokeo, na data iliyotumwa (nywila zinafichwa).
- Kuingia (kufanikiwa na kushindwa) kunarekodiwa pia.
- App: *Kumbukumbu* (inahitaji ruhusa ya kuona "Permission").
- Service inaweza kuongeza maelezo: `from ..core.audit import note; note("Ankara 0000012 imefutwa")`.

### Usalama
- Access token inadumu `ACCESS_TOKEN_EXPIRE_MINUTES` (60); app inapata mpya kwa `POST /api/auth/refresh`
  ikitumia `refresh_token` (siku `REFRESH_TOKEN_EXPIRE_DAYS`). Mtumiaji akizuiwa, refresh inakataliwa.
- Majaribio `LOGIN_MAX_ATTEMPTS` mabaya ndani ya `LOGIN_LOCK_MINUTES` → kuingia kunafungwa (429).
- `CORS_ORIGINS` - weka domain ya web app tu production.
- HTTPS: tazama `deploy/nginx.conf` na `deploy/transportcore.service`. Endesha uvicorn kwa **worker 1**
  (scheduler na ulinzi wa login viko kwenye kumbukumbu ya process).
- `APP_ENV=production` inakataa kuwaka kama `SECRET_KEY` bado ni ya mfano.

### Columns mpya
Server ikiwaka, `db.sync_schema()` inaongeza columns na indexes mpya kwenye tables zilizopo
(create_all haifanyi hivyo) - huhitaji kuendesha migration kwa mkono kwa mabadiliko haya.

## Kazi za kila siku (v2.2)

### Gharama za stoo
- Saa inaanza mzigo ukifika stoo (`STORE_...` kwenye history). Baada ya `DAYS_TO_CHARGE` siku za bure,
  kila siku inatozwa `STORAGE_CHARGE_USD` × kiwango cha USD cha sasa.
- `debts.days`, `debts.storageCharge` vinasasishwa na scheduler (kila saa 2), na kila deni linapoangaliwa,
  kulipwa au mzigo unapokabidhiwa. Mzigo ukitoka stoo, gharama inasimama.
- PDF ya ankara inaonyesha mstari wa gharama za stoo na punguzo.

### Malipo
- `POST /api/payment` inakubali `currency` (TZS, USD...) - inabadilishwa kuwa TSh kwa kiwango cha sasa.
  Kulipa zaidi ya deni kunakataliwa. Kila malipo yanapata namba ya risiti (`R0000001`) na SMS ya risiti.
- `GET /api/payment/{id}/receipt` - risiti (PDF, A5, ina QR).
- `PUT /api/payment/discount` - punguzo (lazima sababu). `POST /api/payment/refund` - kurudisha pesa.
  Vyote vinahitaji ruhusa ya PAYMENT/update na vinaingia kwenye audit log.

### Makabidhiano
- `POST /api/handover` (multipart: `stringValue` + `signature` + `photo`) - aliyechukua, simu,
  kitambulisho, sahihi na picha. Lazima deni liwe limelipwa, au `onCredit=true` (ruhusa PAYMENT/update).
- Hali mpya: **STORE** → (imelipwa) → kukabidhi → **COMPLETED**; au kukabidhi kwa mkopo → **DELIVERED**
  → deni likilipwa → **COMPLETED**. (Malipo peke yake hayamalizi ankara tena.)
- `GET /api/handover/{invoiceId}/pdf` - hati ya makabidhiano yenye sahihi.
- SMS kwa mwenye mzigo inatumwa mzigo ukikabidhiwa (kinga dhidi ya mtu kuchukua mzigo usio wake).

## Mabox na wateja (v2.3)

### Bei ya CBM (meli)
- `prices.unit`: `KG` (default) au `CBM`. Bei ya CBM inatumika kwa mzigo wa meli:
  `CBM = (urefu × upana × kimo cha katoni moja, cm) / 1,000,000 × idadi ya katoni`.
- App: *Mipangilio → Bei mpya → Bei ni kwa: Kilo / Ujazo (CBM)*. Kwenye fomu ya mzigo wa meli, bei za CBM
  zinakuja kwanza na kiasi kinahesabiwa chenyewe.

### Manifest na lebo za QR
- `GET /api/package/{id}/manifest` - PDF (A4 mlalo) ya mizigo yote ndani ya box/kontena + sahihi.
- `GET /api/package/{id}/labels?perCarton=false` - lebo 100×70mm: lebo ya box (QR = boxId) + lebo ya kila
  mzigo (QR = track number). `perCarton=true` = lebo moja kwa kila katoni (1/3, 2/3...).
- `GET /api/package/invoice/{invoiceId}/labels` - lebo za ankara moja (wakati wa kupokea mzigo).
- QR zinasomwa na skana za app (kupakia box, kupokea stoo, kutafuta ankara).

### Ufuatiliaji wa mteja (bila kuingia)
- `GET /api/public/track/{code}` - code = track number ya mzigo au pickup code ya mpokeaji.
  Inaonyesha hatua, tarehe, siku za stoo, deni. Jina linafichwa (`A*** J***`), simu hazionyeshwi.
  Kizuizi: maombi 30 kwa dakika 5 kwa kila IP. Zima kwa `PUBLIC_TRACKING=false`.
- App (web): `https://app.domain/#/track?code=XXXX` - pia kitufe "Fuatilia mzigo" kwenye ukurasa wa kuingia.
- Weka `PUBLIC_TRACK_URL=https://app.domain/#/track` ili kiungo kiongezwe kwenye SMS.
- Jenga web app ikijua server yake: `flutter build web --release --dart-define=API_SERVER=https://api.domain`

## Kukua (v2.4)

### Data kwa ofisi
- `invoices.office_id` = ofisi (tawi) ya kuchukulia mzigo. Inawekwa yenyewe kutoka ofisi ya aliyeunda,
  au `office_id` kwenye `POST /api/invoice`. `PUT /api/invoice/office` kuihamisha.
- `users.allOffices`: `true` (default) = anaona kila kitu. `false` + ofisi = anaona ankara za ofisi yake
  (na zisizo na ofisi), matumizi ya ofisi yake tu, na dashboard ya ofisi yake. Anachounda kinaenda ofisi yake.
- App: *Watumiaji → hariri → Anaona ofisi zote*; ankara zina kichujio cha ofisi.

### Kasi (data nyingi)
- `POST /api/invoice/search` inakubali `q` (namba, mteja, simu, mpokeaji, track), `statuses`, `office_id`,
  `offset`, `limit`. `limit` isipotumwa = zote (app ya zamani).
- `POST /api/customer/search` (`q`, `active`, `offset`, `limit`) na `GET /api/customer/counts`.
- App inaleta ankara na wateja kwa kurasa (50) na kutafuta kwenye server.
- Indexes mpya kwenye invoices, products, receivers, debts, payments, sms, expenses - zinaundwa zenyewe.

### Majaribio na CI
- Backend: `pytest -q` (PostgreSQL halisi). App: `flutter test` (test/).
- `.github/workflows/` - GitHub Actions kwa kila push: backend (pytest + Postgres), app (analyze, test, build web).

## Roles na usalama wa watumiaji (v2.5)

### Roles (majukumu)
- Tables `roles` + `role_permissions`. Role za kuanzia zinaundwa zenyewe: **Msimamizi, Mpokeaji China,
  Stoo Tanzania, Mhasibu, Mtazamaji** (zinaweza kubadilishwa, hazifutwi).
- Mtumiaji akipewa role (`PUT /api/role/assign` au `role_id` wakati wa kumuunda), ruhusa za role
  zinanakiliwa kwenye ruhusa zake. Role ikibadilishwa (`PUT /api/role/{id}`, `applyToUsers=true`),
  watumiaji wake wote wanasasishwa. Ruhusa maalum za mtu mmoja bado zinawezekana (Permissions).
- App: *Watumiaji → Majukumu (Roles)*.

### Usalama wa akaunti
- Sera ya nywila: herufi `PASSWORD_MIN_LENGTH` (8)+, zenye herufi na namba.
- Mtumiaji aliyeundwa na msimamizi, au aliyewekewa nywila na msimamizi, **lazima aweke nywila yake**
  akiingia (server inarudisha 428 hadi afanye hivyo): `PUT /api/auth/password`.
- `POST /api/auth/logout-all` (wewe) na `POST /api/user/{id}/logout-all` (msimamizi): token zote za zamani
  zinakufa papo hapo. Kubadilisha nywila au kumzuia mtumiaji kunamtoa kwenye vifaa vyote pia.

### PDF ya ankara bila MS Word
- Ankara sasa inatengenezwa moja kwa moja (reportlab): haraka, haihitaji Word/LibreOffice, ina mistari ya
  stoo na punguzo, maelezo ya malipo na QR ya kufuatilia mzigo. (Ripoti za Word bado zinatumia templates.)

## Faida, vikumbusho na Excel (v2.6)

### Gharama za box na faida
- `package_costs`: gharama za kila box/kontena (FREIGHT, CUSTOMS, CLEARING, TRANSPORT, HANDLING, OTHER),
  kwa sarafu yoyote - inabadilishwa kuwa TSh na kuhifadhiwa.
- `POST/GET /api/shipment/{boxId}/costs`, `DELETE /api/shipment/costs/{id}`,
  `GET /api/shipment/{boxId}/profit`, `GET /api/shipment/profit-report?startDate&endDate`.
- Faida = usafirishaji wa mizigo ndani ya box + gharama za stoo za ankara zake − gharama za box.

### Vikumbusho vya SMS (aina REMAINDER)
- Kila siku saa `REMINDER_HOUR`: onyo siku `STORAGE_WARN_DAYS` kabla siku za bure za stoo hazijaisha (mara moja),
  na kukumbusha madeni kila `REMINDER_EVERY_DAYS`. `POST /api/sms/reminders/run` kuendesha sasa.
- **Mizigo iliyochelewa stoo**: baada ya siku `DAYS_TO_CHARGE` (7) za bure kila siku inatozwa `STORAGE_CHARGE_USD` ($3).
  `GET /api/store/overdue` (orodha + gharama), `POST /api/store/overdue/remind` (kumkumbusha mmoja/wote).
  Popup (taarifa `STORAGE_OVERDUE`) kwa watumiaji wa STORE kila `STORAGE_ALERT_EVERY_DAYS`.
- **Mapato ya stoo**: `GET /api/report/income?startDate&endDate` -> jumla, usafirishaji, stoo; dashboard
  `storageIncomeThisMonth`; Excel `GET /api/report/export/storage`.
- **Namba za simu**: si lazima; zinahifadhiwa kama `+255XXXXXXXXX` (core/phone.py). 0712 345 678 / 255712.. zinabadilishwa,
  namba mbovu zinakataliwa (400). Namba za zamani zinabadilishwa zenyewe server ikianza. Gateway inapokea `+255...`
  (`SMS_MSISDN_PLUS=false` kwa `255...`).
- **Kikomo cha mkopo**: `PUT /api/customer/credit-limit` {id, creditLimit|null}; `GET /api/customer/{id}/credit`.
  Kukabidhi kwa mkopo kunakataliwa kikomo kikizidi (`DEFAULT_CREDIT_LIMIT`, -1 = hakuna kikomo).
- **2FA (OTP kwa SMS)**: `PUT /api/user/two-factor` {id, enabled}. Login inarudisha `otpRequired` + `otpToken`;
  kisha `POST /api/login/otp` {otpToken, code} (au `/api/login/otp/resend`). Dharura: `TWO_FACTOR_ENABLED=false`.
- **Kufunga hesabu ya siku**: `GET /api/cashup/expected?day=`, `POST /api/cashup`, `GET /api/cashup`,
  `GET /api/cashup/{id}/pdf`, `DELETE /api/cashup/{id}` (kufungua upya).
- **Ujumbe kwa wateja**: `POST /api/sms/broadcast/preview` na `POST /api/sms/broadcast`
  (audience: ALL, SELECTED, ONE, IN_STORE, OVERDUE, DEBT; channel: SMS, WHATSAPP, BOTH; `{jina}` = jina la mteja).
- Washa/zima kwenye *Mipangilio → SMS* (REMAINDER) au `REMINDERS_ENABLED=false`.

### Ripoti
- `GET /api/report/aging` - madeni kwa umri (0-7, 8-30, 31-60, 60+) kwa mteja na kwa ankara.
- `GET /api/report/export/{invoices|payments|expenses|aging|profit|customers}?startDate&endDate` - Excel.

## Kukabidhi kwa awamu na madai ya mzigo (v2.7)

### Kukabidhi sehemu ya mzigo
- `POST /api/handover` inakubali `items: [{productId, cartons}]`. Bila `items` = mzigo wote uliobaki.
- Ankara inabaki STORE hadi katoni zote zichukuliwe; awamu ya mwisho inaifanya COMPLETED (au DELIVERED kama
  inadaiwa). Kila awamu ina sahihi, kitambulisho, PDF yake na SMS kwa mwenye mzigo.
- `GET /api/handover/{invoiceId}/status` - makabidhiano yote + katoni zilizobaki kwa kila bidhaa.
- `GET /api/handover/{invoiceId}/pdf?handoverId=...` - hati ya awamu fulani.
- Server ikiwaka inaondoa sharti la "makabidhiano moja kwa ankara" (`db._MIGRATIONS`).

### Madai (mzigo ulioharibika / kupotea / katoni pungufu)
- `POST /api/claim` (multipart: `stringValue` + `photo`) - ruhusa STORE/insert.
- `PUT /api/claim/{id}/resolve` - APPROVED/REJECTED + fidia: `DISCOUNT` (inapunguza deni la ankara) au
  `REFUND` (pesa inarudishwa, inaingia kwenye malipo kama REFUND). Ruhusa PAYMENT/update.
- `POST /api/claim/search`, `GET /api/claim/counts`, `GET /api/claim/{id}/photo`.

## WhatsApp, taarifa, kuingiza Excel na ufuatiliaji (v2.8)

### WhatsApp (Meta WhatsApp Business Cloud API)
- Weka `WHATSAPP_ENABLED=true`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` na `WHATSAPP_TEMPLATE`
  (template iliyoidhinishwa na Meta yenye kigezo kimoja `{{1}}`). Kwa PDF: `WHATSAPP_DOC_TEMPLATE`
  (template yenye header ya DOCUMENT + `{{1}}`).
- Kila SMS inayoandaliwa inapata nakala ya WhatsApp (channel=WHATSAPP) kama aina "WHATSAPP" imewashwa
  kwenye *Mipangilio → SMS*. Zinatumwa zenyewe kama SMS.
- `POST /api/whatsapp/document` - kutuma ankara / risiti / hati ya makabidhiano (PDF) kwa mteja.
- `POST /api/whatsapp/message` (multipart: `text`, `invoiceId` au `phone`, `image`) - ujumbe + picha.
  `POST /api/whatsapp/product-photos` - picha za mizigo ya ankara. Picha: `WHATSAPP_IMAGE_TEMPLATE`
  (template yenye header ya IMAGE + `{{1}}`). Mwongozo kamili: `docs/WHATSAPP.md`.

### Taarifa ndani ya app (🔔)
- `GET /api/notification`, `PUT /api/notification/read`. Matukio: box limesafirishwa / limefika stoo, malipo,
  dai jipya, kukabidhi kwa mkopo, madeni ya zaidi ya siku 30, tahadhari za server. Zinawafikia wenye ruhusa husika.

### Kuingiza data (Excel)
- `GET /api/import/template/{customers|debts}`, `POST /api/import/{kind}?dryRun=true|false` (file).
- Kwanza `dryRun=true` (kukagua), kisha `dryRun=false`. Kosa lolote = hakuna kinachohifadhiwa.

### Ufuatiliaji wa server
- `GET /api/health/details` - database, diski, backup, SMS/WhatsApp, kazi za scheduler na matatizo.
- Kila saa: matatizo (diski < `ALERT_DISK_MIN_GB`, backup > `ALERT_BACKUP_MAX_HOURS`, SMS zilizokwama,
  kazi zilizoshindwa) yanatumwa kama taarifa + SMS kwa `ALERT_PHONES` + email kwa `ALERT_EMAILS` (SMTP).
- `POST /api/health/test-alert` - kuhakiki tahadhari. Kwa ufuatiliaji wa nje (UptimeRobot n.k.) tumia `GET /api/health`.
#   l o g i s t i c C o r e  
 