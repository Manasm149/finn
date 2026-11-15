"""python -m finn.users add NAME ROLE   -  prints the FINN_USERS entry for a new account.

Passwords are never stored or printed: only a salted hash, which you paste into the
host's environment settings. Roles: guest, analyst, admin.

  python -m finn.users add manas admin
  python -m finn.users add reviewer analyst
  python -m finn.users secret            -  a random FINN_SECRET for signing sessions
"""
import getpass
import secrets
import sys

from .auth import ROLES, hash_password


def main(argv):
    if argv[:1] == ["secret"]:
        print(f"FINN_SECRET={secrets.token_urlsafe(32)}")
        return 0
    if len(argv) != 3 or argv[0] != "add" or argv[2] not in ROLES or ":" in argv[1] or ";" in argv[1]:
        print(__doc__)
        return 1
    name, role = argv[1].lower(), argv[2]
    pw = getpass.getpass(f"Password for {name}: ")
    if len(pw) < 10:
        print("Use at least 10 characters.")
        return 1
    if pw != getpass.getpass("Again: "):
        print("The two passwords differ.")
        return 1
    print(f"\n{name}:{role}:{hash_password(pw)}\n")
    print("Add that line to FINN_USERS. Separate several accounts with ';', for example:")
    print("FINN_USERS=alice:admin:<hash>;bob:analyst:<hash>")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
