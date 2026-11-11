"""
Orodha ya models zote - inahakikisha tables zote zimesajiliwa kwenye `Base.metadata`
(inatumika na `init_db()` na Alembic).
"""
from .accounting.model import AccountCategory, Equity, Income, PeriodLock, Transfer  # noqa: F401
from .expense.model import ExpensePayment  # noqa: F401
from .assets.model import FixedAsset  # noqa: F401
from .audit.model import AuditLog  # noqa: F401
from .payroll.model import Employee, PayrollLine, PayrollRun, PayrollSettings  # noqa: F401
from .demand.model import CostDemand, DemandRule  # noqa: F401
from .cashup.model import CashUp, CashUpLine  # noqa: F401
from .claim.model import CargoClaim  # noqa: F401
from .customer.model import Customer  # noqa: F401
from .expense.model import Expense  # noqa: F401
from .handover.model import Handover, HandoverItem  # noqa: F401
from .invoice.model import Invoice  # noqa: F401
from .notification.model import Notification  # noqa: F401
from .package.model import Package  # noqa: F401
from .payment.model import Debt, Payment  # noqa: F401
from .permission.model import Permission  # noqa: F401
from .popup.model import PopupRule  # noqa: F401
from .product.model import Product  # noqa: F401
from .quotation.model import Quotation, QuotationItem  # noqa: F401
from .receiver.model import Receiver  # noqa: F401
from .role.model import Role, RolePermission  # noqa: F401
from .settings.currency.model import Currency  # noqa: F401
from .settings.institute.model import Institute  # noqa: F401
from .settings.office.model import Office  # noqa: F401
from .settings.price.model import Price  # noqa: F401
from .settings.sms_set.model import SmsSet  # noqa: F401
from .shipment.model import PackageCost  # noqa: F401
from .sms.model import AutoSmsRule, Sms, SmsCredit  # noqa: F401
from .user.model import User  # noqa: F401
from .whatsapp.model import WhatsappMessage  # noqa: F401
from .saas.admin.model import PlatformAdmin  # noqa: F401
from .saas.audit_log.model import PlatformAuditLog  # noqa: F401
from .onlinepay.model import OnlinePayment  # noqa: F401
from .saas.coupon.model import Coupon, CouponUse  # noqa: F401
from .saas.support.model import SupportTicket, TicketMessage  # noqa: F401
from .saas.notice.model import PlatformNotice  # noqa: F401
from .saas.company.model import Company  # noqa: F401
from .saas.plan.model import Plan  # noqa: F401
from .saas.subscription.model import Subscription, SubscriptionPayment  # noqa: F401

from .db import register_tenant_events

register_tenant_events()
