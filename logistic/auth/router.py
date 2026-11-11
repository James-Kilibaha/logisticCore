from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from ..core.audit import client_ip
from ..core.security import TokenData, get_current_user
from ..user.schema import ChangeOwnPassword
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Auth"])


@router.post("/api/login", status_code=status.HTTP_200_OK, response_model=schema.LoginResponse)
def login(request: schema.Login, http: Request, db: Session = Depends(get_db)):
    return service.login(db, request, client_ip(http))


@router.post("/api/login/otp", status_code=status.HTTP_200_OK, response_model=schema.LoginResponse)
def login_otp(request: schema.OtpVerify, http: Request, db: Session = Depends(get_db)):
    """Hatua ya pili ya kuingia: code iliyotumwa kwa SMS."""
    return service.verify_otp(db, request, client_ip(http))


@router.post("/api/login/otp/resend", status_code=status.HTTP_200_OK, response_model=schema.LoginResponse)
def login_otp_resend(request: schema.OtpResend, db: Session = Depends(get_db)):
    return service.resend_otp(db, request)


@router.post("/api/auth/forgot", status_code=status.HTTP_200_OK)
def forgot_password(request: schema.Forgot, http: Request, db: Session = Depends(get_db)):
    """Kusahau nywila, hatua ya 1: code inatumwa kwa SMS kwenye namba ya mtumiaji."""
    return service.forgot(db, request, client_ip(http))


@router.post("/api/auth/forgot/reset", status_code=status.HTTP_200_OK)
def forgot_password_reset(request: schema.ForgotReset, http: Request, db: Session = Depends(get_db)):
    """Kusahau nywila, hatua ya 2: code + nywila mpya."""
    return service.forgot_reset(db, request, client_ip(http))


@router.post("/api/auth/refresh", status_code=status.HTTP_200_OK, response_model=schema.LoginResponse)
def refresh(request: schema.Refresh, db: Session = Depends(get_db)):
    return service.refresh(db, request)


@router.put("/api/auth/password", status_code=status.HTTP_200_OK, response_model=schema.LoginResponse)
def change_own_password(request: ChangeOwnPassword, db: Session = Depends(get_db),
                        current_user: TokenData = Depends(get_current_user)):
    """Kubadilisha nywila yako. Inarudisha token mpya (vifaa vingine vyote vinatolewa)."""
    return service.change_own_password(db, current_user.id, request)


@router.post("/api/auth/logout-all", status_code=status.HTTP_200_OK)
def logout_all(db: Session = Depends(get_db), current_user: TokenData = Depends(get_current_user)):
    """Kujitoa kwenye vifaa vyote (pamoja na hiki)."""
    return service.logout_everywhere(db, current_user.id)
