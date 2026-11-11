from enum import Enum


class EInvoiceStatus(Enum):
    OPEN = 1
    PARKING = 2
    PROCESSING = 3
    SHIPPING = 4
    ARRIVE = 5
    PIKING = 6
    DELIVERING = 7
    DELIVERED = 8
    COMPLETED = 9
    BLOCKED = 10
    STORE = 11
    RECEIVED = 12
    CLOSE = 13
    BLOCK = 14


class EPaymentStatus(Enum):
    OPEN = 1
    DEBT = 2
    PAID = 3


class ESmsStatus(Enum):
    RECEIVED = 1
    SHIPPING = 2
    STORE = 3
    REMAINDER = 4
    WHATSAPP = 5
    RECEIPT = 6     # risiti ya malipo
    HANDOVER = 7    # mzigo umekabidhiwa
    CUSTOM = 8      # ujumbe wa mkono (rekodi za zamani; mpya zina aina zao hapa chini)
    STORAGE_WARN = 9      # onyo: siku za bure za stoo zinakaribia kuisha
    STORAGE_OVERDUE = 10  # kumbusho la mizigo iliyokaa stoo muda mrefu (ukurasa wa stoo)
    BROADCAST = 11        # ujumbe kwa wateja (mmoja / waliochaguliwa / wote)
    INVOICE_SMS = 12      # SMS ya ankara (bidhaa moja moja)
    QUOTATION = 13        # makadirio ya bei
    ETA = 14              # mabadiliko ya tarehe ya kufika ya box
    OTP_LOGIN = 15        # code ya kuingia (2FA)
    OTP_RESET = 16        # code ya kusahau nywila
    ALERT = 17            # tahadhari za mfumo kwa wasimamizi (ALERT_PHONES)


class EPaymentKind(Enum):
    PAYMENT = 1
    REFUND = 2


class Module(str, Enum):
    """Majina ya moduli zinazotumika kwenye jedwali la permissions."""
    USER = "USER"
    CUSTOMER = "CUSTOMER"
    INVOICE = "INVOICE"
    PACKAGE = "PACKAGE"
    PERMISSION = "PERMISSION"
    PRODUCT = "PRODUCT"
    RECEIVE = "RECEIVE"
    SETTING = "SETTING"
    STORE = "STORE"
    PAYMENT = "PAYMENT"
    EXPENSES = "EXPENSES"
    SMS = "SMS"
    REPORT = "REPORT"
    # v2.14: ruhusa za kina (tazama permission/service.py -> INHERIT kwa watumiaji waliokuwepo)
    DASHBOARD = "DASHBOARD"   # select: kuona takwimu za pesa kwenye dashibodi
    HANDOVER = "HANDOVER"     # select: kuona makabidhiano, insert: kukabidhi, update: kukabidhi kwa mkopo
    DISCOUNT = "DISCOUNT"     # insert: kutoa punguzo
    REFUND = "REFUND"         # insert: kurudisha pesa (refund)
    CREDIT = "CREDIT"         # select: kuona mkopo wa mteja, update: kuweka kikomo cha mkopo
    CLAIM = "CLAIM"           # select/insert: madai, update: kuamua dai (fidia)
    CASHUP = "CASHUP"         # select: kuona, insert: kufunga hesabu ya siku, delete: kufungua upya
    BROADCAST = "BROADCAST"   # insert: ujumbe kwa wateja wengi / wote
    WHATSAPP = "WHATSAPP"     # select: hali, insert: kutuma WhatsApp (ujumbe, picha, PDF)
    PROFIT = "PROFIT"         # select: gharama na faida za mabox, update/delete: gharama za box
    FINANCE = "FINANCE"       # select: pesa kwenye ripoti (mapato, madeni, matumizi) na kwenye taarifa za mteja
    AUDIT = "AUDIT"           # select: kumbukumbu za nani alifanya nini
    BACKUP = "BACKUP"         # select/insert/delete: nakala za data
    IMPORT = "IMPORT"         # insert: kuingiza wateja / madeni kwa Excel
    PRICE = "PRICE"           # select: kuona bei na viwango (kuandika ankara), insert: kuweka bei/kiwango kipya, update: kurekebisha kiwango, delete: kuondoa bei/sarafu
    QUOTE = "QUOTE"           # makadirio ya bei: select/insert/update (kutuma, kugeuza kuwa ankara)/delete
    # v2.15: uhasibu - select: kuona akaunti, salio na faida/hasara; insert: mapato mengine, uhamisho, akaunti mpya;
    # update: kuidhinisha/kukataa matumizi, makundi, salio la kuanzia; delete: kufuta mapato/uhamisho/matumizi yaliyoidhinishwa
    ACCOUNTING = "ACCOUNTING"
    # v2.18: mishahara - select: kuona wafanyakazi na mishahara; insert/update: kuandaa na kuidhinisha mishahara;
    # delete: kufuta mshahara ambao haujaidhinishwa
    PAYROLL = "PAYROLL"


class Action(str, Enum):
    INSERT = "insert"
    UPDATE = "update"
    SELECT = "select"
    DELETE = "delete"
    BLOCK = "block"
