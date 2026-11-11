from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DayAmount(BaseModel):
    date: str  # 'YYYY-MM-DD'
    amount: float


class RecentInvoice(BaseModel):
    id: UUID
    invoiceNumber: str
    status: str
    customerName: str | None = None
    total: float = 0.0
    created_at: datetime | None = None


class Summary(BaseModel):
    invoices: dict[str, int]       # idadi ya invoice kwa kila hali (OPEN, PARKING, ...)
    customers: int
    openBoxes: int                 # box ambalo bado linapakiwa
    boxesInTransit: int            # box lililofungwa, bado halijafika stoo
    lateBoxes: int = 0             # safarini na ETA imepita
    outstandingDebt: float         # madeni yote ambayo hayajalipwa
    paidToday: float
    paidThisMonth: float
    expensesThisMonth: float
    pendingSms: int
    income7Days: list[DayAmount]
    storageIncomeThisMonth: float = 0.0  # sehemu ya malipo ya mwezi huu iliyolipia gharama za stoo
    storagePending: float = 0.0          # gharama za stoo za mizigo iliyo stoo sasa (bado haijalipwa)
    overdueInStore: int = 0              # mizigo iliyokaa stoo zaidi ya siku za bure
    # data ya pie charts (mwezi huu)
    carrierKg: dict[str, float] = {}         # AIR / SEA -> kilo za mizigo iliyopokelewa
    paymentsByMethod: dict[str, float] = {}  # benki / njia -> malipo
    debtAging: dict[str, float] = {}         # "0-7", "8-30", "31-60", "60+" -> deni
    # False = mtumiaji hana ruhusa ya DASHBOARD (select): takwimu za pesa zimefichwa (ni 0)
    finance: bool = True
    recentInvoices: list[RecentInvoice]
