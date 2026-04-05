# -*- coding: utf-8 -*-
from passlib.context import CryptContext

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd.verify(plain_password, password_hash)
