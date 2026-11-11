"""
Mipangilio yote ya mfumo (settings).

Thamani zote zinasomwa kutoka kwenye environment variables au faili la `.env`
lililopo kwenye folder kuu la mradi. Ukibadilisha server (development/production)
badilisha `.env` tu, si code.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default=None):
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    return int(_env(name, default))


def _env_float(name: str, default: float) -> float:
    return float(_env(name, default))


# ----------------------------------------------------------------- App
APP_ENV = _env("APP_ENV", "development")
APP_TITLE = _env("APP_TITLE", "Logistic Core API")
APP_HOST = _env("APP_HOST", "0.0.0.0")
APP_PORT = _env_int("APP_PORT", 8000)
# Saa za ofisi: "leo", ripoti za siku na dashboard zinahesabiwa kwa saa hizi (database inahifadhi UTC).
TIMEZONE = _env("TIMEZONE", "Africa/Dar_es_Salaam")

# ------------------------------------------------------------ Database
DATABASE_USERNAME = _env("DATABASE_USERNAME", "postgres")
DATABASE_PASSWORD = _env("DATABASE_PASSWORD", "123456")
DATABASE_HOST = _env("DATABASE_HOST", "localhost")
DATABASE_PORT = _env_int("DATABASE_PORT", 5432)
DATABASE_NAME = _env("DATABASE_NAME", "logistic_db")
TEST_DATABASE_NAME = _env("TEST_DATABASE_NAME", "logistic_db_test")

# -------------------------------------------------------- Auth (JWT)
SECRET_KEY = _env("SECRET_KEY", "change-me-in-.env")
ALGORITHM = _env("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
# Uthibitisho wa hatua mbili (OTP kwa SMS) kwa watumiaji waliowashiwa. false = zima kwa wote (dharura).
TWO_FACTOR_ENABLED = _env("TWO_FACTOR_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
OTP_TTL_MINUTES = _env_int("OTP_TTL_MINUTES", 5)
OTP_MAX_ATTEMPTS = _env_int("OTP_MAX_ATTEMPTS", 5)
OTP_RESEND_SECONDS = _env_int("OTP_RESEND_SECONDS", 45)
# Refresh token: app inapata access token mpya bila mtumiaji kuingia upya.
REFRESH_TOKEN_EXPIRE_DAYS = _env_int("REFRESH_TOKEN_EXPIRE_DAYS", 7)


def _env_bool(name: str, default: bool) -> bool:
    return str(_env(name, "true" if default else "false")).strip().lower() in ("1", "true", "yes", "on")


# ------------------------------------------------------------ Usalama
# Tovuti zinazoruhusiwa kuita API (web app). Mfano: https://ymg.co.tz,https://www.ymg.co.tz
# "*" = zote (development tu).
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "*").split(",") if o.strip()]
# Development: app ya web ya `flutter run` (localhost:<port yoyote>) inaruhusiwa hata CORS_ORIGINS ikiwa na domain tu
CORS_DEV_REGEX = None if APP_ENV == "production" else r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
PASSWORD_MIN_LENGTH = _env_int("PASSWORD_MIN_LENGTH", 8)
# Majaribio mabaya ya kuingia kabla ya kufungiwa kwa muda.
LOGIN_MAX_ATTEMPTS = _env_int("LOGIN_MAX_ATTEMPTS", 5)
LOGIN_LOCK_MINUTES = _env_int("LOGIN_LOCK_MINUTES", 15)
# true kama server iko nyuma ya nginx (HTTPS): IP halisi inasomwa kutoka X-Forwarded-For
BEHIND_PROXY = _env_bool("BEHIND_PROXY", False)
# true = kivinjari kinalazimishwa kutumia HTTPS (HSTS). Weka tu ukiwa na cheti cha HTTPS.
FORCE_HTTPS = _env_bool("FORCE_HTTPS", False)
# /docs inafungwa production
API_DOCS = _env_bool("API_DOCS", APP_ENV != "production")

# Msimamizi wa kwanza wa mfumo mzima (platform admin = wewe) - anaundwa mara moja tu kama hakuna yeyote.
ADMIN_USERNAME = _env("ADMIN_USERNAME")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
ADMIN_FIRST_NAME = _env("ADMIN_FIRST_NAME", "System")
ADMIN_LAST_NAME = _env("ADMIN_LAST_NAME", "Admin")
ADMIN_PHONE = _env("ADMIN_PHONE", "0000000000")

# --------------------------------------------------------------- Files
# Mahali picha za bidhaa na ripoti (PDF) zinapohifadhiwa.
_DEFAULT_FILES_DIR = "C:\\Users\\user\\Documents\\Logistic\\" if sys.platform.startswith("win") else "/var/lib/logistic/"
FILES_DIR = Path(_env("FILES_DIR", _DEFAULT_FILES_DIR))
TEMPLATES_DIR = BASE_DIR / "assets" / "sample"
LIBREOFFICE_PATH = _env("LIBREOFFICE_PATH")  # Linux tu; ikiachwa tupu tunaitafuta wenyewe

# -------------------------------------------------------------- Backup
# Backup ya database (pg_dump) + mafaili, kila siku saa BACKUP_HOUR (saa za server).
BACKUP_ENABLED = _env_bool("BACKUP_ENABLED", True)
BACKUP_DIR = Path(_env("BACKUP_DIR", str(FILES_DIR / "_backup")))
BACKUP_HOUR = _env_int("BACKUP_HOUR", 2)
BACKUP_KEEP = _env_int("BACKUP_KEEP", 14)  # idadi ya backup za kubaki (za zamani zinafutwa)
# Nakala ya pili (mfano disk ya nje au folder la Google Drive/OneDrive linalosawazishwa). Tupu = hakuna.
BACKUP_MIRROR_DIR = _env("BACKUP_MIRROR_DIR")
PG_DUMP_PATH = _env("PG_DUMP_PATH", "pg_dump")
PSQL_PATH = _env("PSQL_PATH", "psql")

# ------------------------------------------------------ Vikumbusho (SMS)
# Kila siku saa REMINDER_HOUR: (1) onyo siku STORAGE_WARN_DAYS kabla siku za bure za stoo hazijaisha,
# (2) kukumbusha madeni kila REMINDER_EVERY_DAYS. Zinatumwa kama aina ya SMS "REMAINDER" (washa/zima kwenye app).
REMINDERS_ENABLED = _env_bool("REMINDERS_ENABLED", True)
REMINDER_HOUR = _env_int("REMINDER_HOUR", 9)
REMINDER_EVERY_DAYS = _env_int("REMINDER_EVERY_DAYS", 7)
STORAGE_WARN_DAYS = _env_int("STORAGE_WARN_DAYS", 2)
# Taarifa (popup) kwenye app kwa mizigo iliyokaa stoo zaidi ya siku za bure - inarudiwa kila siku hizi
STORAGE_ALERT_EVERY_DAYS = _env_int("STORAGE_ALERT_EVERY_DAYS", 7)
# Ujumbe kwa wateja wengi (Ujumbe -> Tuma kwa wateja): idadi ya juu kwa mara moja
BROADCAST_MAX = _env_int("BROADCAST_MAX", 5000)
# SMS za ankara zinaorodhesha bidhaa moja moja; zikizidi idadi hii, zilizobaki zinajumlishwa ("na bidhaa N zaidi").
SMS_ITEMS_MAX = _env_int("SMS_ITEMS_MAX", 15)
# Ripoti za kufika (DLR): FastHub inaita https://SERVER/api/public/sms-dlr/<SMS_DLR_TOKEN>. Tupu = imezimwa.
SMS_DLR_TOKEN = _env("SMS_DLR_TOKEN", "")
# true: kila SMS inatumwa na reference yake ya kipekee (inahitajika ili DLR itambue ujumbe)
# FastHub: reference ya kila SMS lazima iwe na angalau herufi 20
SMS_REFERENCE_MIN_LENGTH = _env_int("SMS_REFERENCE_MIN_LENGTH", 20)
SMS_DLR_UNIQUE_REFERENCE = _env("SMS_DLR_UNIQUE_REFERENCE", "true").strip().lower() in ("1", "true", "yes", "on")
# WhatsApp (Meta) webhook: https://SERVER/api/public/whatsapp/webhook, verify token hii. Tupu = imezimwa.
WHATSAPP_VERIFY_TOKEN = _env("WHATSAPP_VERIFY_TOKEN", "")
# Salio la SMS: onyo likishuka chini ya hiki. SMS_BALANCE_API (hiari) = URL ya FastHub ya kuuliza salio
# (POST yenye auth ile ile ya kutuma); ikiwa tupu, salio linakadiriwa kutoka kwenye manunuzi yaliyorekodiwa.
SMS_LOW_BALANCE = _env_int("SMS_LOW_BALANCE", 300)
# Siku za kawaida za safari (ETA) box likifungwa: ndege na meli (container). Inaweza kubadilishwa kwa kila box.
ETA_AIR_DAYS = _env_int("ETA_AIR_DAYS", 10)
ETA_SEA_DAYS = _env_int("ETA_SEA_DAYS", 45)
SMS_BALANCE_API = _env("SMS_BALANCE_API", "")
WHATSAPP_APP_SECRET = _env("WHATSAPP_APP_SECRET", "")  # hiari: kuhakiki sahihi ya webhook

# ------------------------------------------------- Ufuatiliaji wa umma
# Mteja anaweza kuangalia mzigo wake kwa track number bila kuingia (GET /api/public/track/{code}).
PUBLIC_TRACKING = _env_bool("PUBLIC_TRACKING", True)
# Kiungo cha ukurasa wa web app (kinaongezwa kwenye SMS). Mfano: https://ymg.co.tz/#/track
PUBLIC_TRACK_URL = _env("PUBLIC_TRACK_URL", "")

# ------------------------------------------------------------ Business
DAYS_TO_CHARGE = _env_int("DAYS_TO_CHARGE", 7)            # siku za bure kabla ya gharama ya stoo
STORAGE_CHARGE_USD = _env_float("STORAGE_CHARGE_USD", 3.0)  # gharama ya stoo kwa siku (USD)
PHOTO_DELETE_AFTER_HANDOVER_DAYS = _env_int("PHOTO_DELETE_AFTER_HANDOVER_DAYS", 3)
IMAGE_RETENTION_DAYS = _env_int("IMAGE_RETENTION_DAYS", 30)
# Kikomo cha mkopo cha kawaida kwa mteja (TSh) - mteja asiye na kikomo chake. -1 = hakuna kikomo, 0 = hakuna mkopo.
DEFAULT_CREDIT_LIMIT = _env_float("DEFAULT_CREDIT_LIMIT", -1)  # picha zinafutwa baada ya siku hizi

# Thamani za kawaida tu: kila kampuni inaweka zake (Mipangilio -> Kampuni). Tazama TENANT_KEYS chini.
COMPANY_NAME = _env("COMPANY_NAME", "LOGISTIC")
COMPANY_PHONES = _env("COMPANY_PHONES", "")
COMPANY_ORIGIN = _env("COMPANY_ORIGIN", "China")
COMPANY_PAYMENT_INFO = _env("COMPANY_PAYMENT_INFO", "").replace("\\n", "\n")

# ----------------------------------------------------------------- SMS
SMS_SOURCE_NAME = _env("SMS_SOURCE_NAME", "LOGISTIC")
SMS_CLIENT_ID = _env("SMS_CLIENT_ID", "")
SMS_CLIENT_SECRET = _env("SMS_CLIENT_SECRET", "")
SMS_API = _env("SMS_API", "https://bulksms.fasthub.co.tz/api/sms/send")
SMS_CODING = _env("SMS_CODING", "GSM7")
# Namba za simu zote zinahifadhiwa kama +<code><namba 9>, mf. +255712345678 (tazama core/phone.py)
PHONE_COUNTRY_CODE = _env("PHONE_COUNTRY_CODE", "255")
# Gateway inapokea namba ikiwa na + (+255712345678). Weka false kutuma 255712345678.
SMS_MSISDN_PLUS = _env_bool("SMS_MSISDN_PLUS", True)
# SMS zinatumwa zenyewe papo hapo (mzigo ukipokelewa, ukisafirishwa, ukifika stoo).
# Weka SMS_AUTO_SEND=false kama unataka kuzituma kwa mkono kutoka kwenye app.
SMS_AUTO_SEND = _env("SMS_AUTO_SEND", "true").strip().lower() in ("1", "true", "yes", "on")

# ------------------------------------------------------------ WhatsApp
# WhatsApp Business Cloud API (Meta). Ujumbe unaoanzishwa na biashara lazima utumie template
# iliyoidhinishwa: WHATSAPP_TEMPLATE iwe na kigezo kimoja {{1}} (maandishi ya ujumbe).
# WHATSAPP_DOC_TEMPLATE (si lazima): template yenye header ya DOCUMENT + {{1}} kwa PDF (ankara, risiti).
WHATSAPP_TOKEN = _env("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = _env("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = _env("WHATSAPP_API_VERSION", "v21.0")
WHATSAPP_TEMPLATE = _env("WHATSAPP_TEMPLATE", "")
WHATSAPP_DOC_TEMPLATE = _env("WHATSAPP_DOC_TEMPLATE", "")
# Template yenye header ya IMAGE + {{1}} (picha za mizigo / ujumbe wenye picha)
WHATSAPP_IMAGE_TEMPLATE = _env("WHATSAPP_IMAGE_TEMPLATE", "")
WHATSAPP_LANG = _env("WHATSAPP_LANG", "sw")
WHATSAPP_COUNTRY_CODE = _env("WHATSAPP_COUNTRY_CODE", "255")
WHATSAPP_ENABLED = _env_bool("WHATSAPP_ENABLED", False) and bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID)

# -------------------------------------------------- Ufuatiliaji wa server
# Tahadhari (server, backup, diski, SMS) zinatumwa kwa SMS kwa namba hizi (zitenganishe kwa koma)
ALERT_PHONES = [p.strip() for p in _env("ALERT_PHONES", "").split(",") if p.strip()]
ALERT_EMAILS = [e.strip() for e in _env("ALERT_EMAILS", "").split(",") if e.strip()]
SMTP_HOST = _env("SMTP_HOST", "")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = _env("SMTP_USER", "")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "")
SMTP_FROM = _env("SMTP_FROM", "")
ALERT_DISK_MIN_GB = _env_float("ALERT_DISK_MIN_GB", 2.0)
ALERT_BACKUP_MAX_HOURS = _env_int("ALERT_BACKUP_MAX_HOURS", 36)

# ----------------------------------------------------------- Scheduler
SCHEDULER_ENABLED = _env("SCHEDULER_ENABLED", "true").lower() == "true"

# ---------------------------------------------------------------- SaaS
# Mfumo wako (platform): kampuni za usafirishaji zinajisajili/zinasajiliwa, zinalipia subscription,
# na kila moja inapata jina, logo, rangi na domain yake.
PLATFORM_NAME = _env("PLATFORM_NAME", "Logistic Cloud")

# ------------------------------------------------------------------ malipo ya mtandaoni (AzamPay)
# Akaunti YAKO (kampuni zinalipia subscription kwa M-Pesa/Tigo/Airtel/Halopesa/AzamPesa). Kila kampuni
# inaweka akaunti yake ya AzamPay (Mipangilio -> Malipo ya simu) kwa malipo ya ankara za wateja wake.
AZAMPAY_ENV = _env("AZAMPAY_ENV", "sandbox")            # sandbox | live
AZAMPAY_APP_NAME = _env("AZAMPAY_APP_NAME", "")
AZAMPAY_CLIENT_ID = _env("AZAMPAY_CLIENT_ID", "")
AZAMPAY_CLIENT_SECRET = _env("AZAMPAY_CLIENT_SECRET", "")
AZAMPAY_API_KEY = _env("AZAMPAY_API_KEY", "")           # "Token" ya ukurasa wa settings wa AzamPay (X-API-Key)
AZAMPAY_AUTH_URL = _env("AZAMPAY_AUTH_URL", "")         # tupu = kulingana na AZAMPAY_ENV
AZAMPAY_BASE_URL = _env("AZAMPAY_BASE_URL", "")         # tupu = kulingana na AZAMPAY_ENV
ONLINE_PAY_TIMEOUT_MINUTES = _env_int("ONLINE_PAY_TIMEOUT_MINUTES", 15)  # mteja asipothibitisha -> EXPIRED
# Domain kuu: kampuni inafunguka kwa <slug>.<PLATFORM_DOMAIN> (mf. ymg.logistic.co.tz) au domain yake yenyewe.
PLATFORM_DOMAIN = _env("PLATFORM_DOMAIN", "")
PLATFORM_SUPPORT_PHONE = _env("PLATFORM_SUPPORT_PHONE", "")
PLATFORM_SUPPORT_EMAIL = _env("PLATFORM_SUPPORT_EMAIL", "")
# Jinsi kampuni zinavyokulipa wewe (inaonyeshwa kwenye ukurasa wa subscription wa kampuni)
PLATFORM_PAYMENT_INFO = _env("PLATFORM_PAYMENT_INFO", "").replace("\\n", "\n")  # "\n" kwenye .env = mstari mpya
# Jina la SMS (sender) la ujumbe wako kwa kampuni (vikumbusho vya subscription)
PLATFORM_SMS_SOURCE = _env("PLATFORM_SMS_SOURCE", "")
# Kampuni zinaweza kujisajili zenyewe (ukurasa wa "Fungua akaunti") na kupata majaribio ya siku TRIAL_DAYS.
SELF_SIGNUP_ENABLED = _env_bool("SELF_SIGNUP_ENABLED", True)
# Kampuni iliyojisajili yenyewe inasubiri uithibitishe (PENDING) kabla ya kutumia mfumo; majaribio yanaanza
# siku unayoithibitisha. false = inaanza kazi papo hapo.
SIGNUP_REQUIRES_APPROVAL = _env_bool("SIGNUP_REQUIRES_APPROVAL", True)
TRIAL_DAYS = _env_int("TRIAL_DAYS", 14)
# Subscription ikiisha: siku hizi za neema bado zinaruhusu kazi zote, kisha mfumo unakuwa wa kusoma tu.
SUBSCRIPTION_GRACE_DAYS = _env_int("SUBSCRIPTION_GRACE_DAYS", 3)
# Vikumbusho (SMS + taarifa kwenye app) siku hizi kabla subscription haijaisha
SUBSCRIPTION_REMIND_DAYS = [int(x) for x in _env("SUBSCRIPTION_REMIND_DAYS", "7,3,1").split(",") if x.strip()]
# Kampuni zisizo na SMS gateway yao zinatumia akaunti yako ya SMS (SMS_CLIENT_ID/SECRET) - false = zizime.
PLATFORM_SMS_FOR_TENANTS = _env_bool("PLATFORM_SMS_FOR_TENANTS", True)
# Kuhamisha data ya mfumo wa zamani (database yenye data isiyo na kampuni): data yote inapewa kampuni hii.
DEFAULT_COMPANY_SLUG = _env("DEFAULT_COMPANY_SLUG", "")
# Kampuni inayotumika kwenye development (localhost bila domain wala X-Company)
DEV_COMPANY_SLUG = _env("DEV_COMPANY_SLUG", "")

# ------------------------------------------------------- Mipangilio ya kila kampuni
# Majina haya yanasomwa kwa kampuni ya request ya sasa (config.COMPANY_NAME ni jina la kampuni iliyoingia).
# Kampuni isipoweka thamani yake, thamani ya .env (hapo juu) inatumika.
TENANT_KEYS = (
    "COMPANY_NAME", "COMPANY_PHONES", "COMPANY_ORIGIN", "COMPANY_PAYMENT_INFO", "TIMEZONE", "PHONE_COUNTRY_CODE",
    "SMS_SOURCE_NAME", "SMS_CLIENT_ID", "SMS_CLIENT_SECRET", "SMS_AUTO_SEND", "SMS_BALANCE_API", "SMS_LOW_BALANCE",
    "SMS_ITEMS_MAX",
    "WHATSAPP_ENABLED", "WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TEMPLATE", "WHATSAPP_DOC_TEMPLATE",
    "WHATSAPP_IMAGE_TEMPLATE", "WHATSAPP_LANG", "WHATSAPP_COUNTRY_CODE",
    "DAYS_TO_CHARGE", "STORAGE_CHARGE_USD", "DEFAULT_CREDIT_LIMIT", "ETA_AIR_DAYS", "ETA_SEA_DAYS",
    "PUBLIC_TRACKING", "PUBLIC_TRACK_URL", "REMINDERS_ENABLED", "REMINDER_EVERY_DAYS", "STORAGE_WARN_DAYS",
    "STORAGE_ALERT_EVERY_DAYS", "IMAGE_RETENTION_DAYS",
)
_DEFAULTS = {name: globals().pop(name) for name in TENANT_KEYS}


def default(name: str):
    """Thamani ya .env (bila kujali kampuni)."""
    return _DEFAULTS[name]


def __getattr__(name: str):
    # config.X kwa X iliyo kwenye TENANT_KEYS: thamani ya kampuni ya sasa (au ya .env)
    if name in _DEFAULTS:
        from .core import tenant

        cid = tenant.company_id()
        if cid is not None:
            from .saas.company import settings as company_settings

            value = company_settings.value(cid, name)
            if value is not None:
                return value
        return _DEFAULTS[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
