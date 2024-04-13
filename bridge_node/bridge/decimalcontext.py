import decimal

# 256 bits is 77ish decimal digits, rounded up
PRECISION = 80

def set_decimal_context():
    decimal.DefaultContext.prec = 80
    decimal.DefaultContext.traps[decimal.FloatOperation] = True
    decimal.DefaultContext.traps[decimal.InvalidOperation] = True
    decimal.DefaultContext.traps[decimal.DivisionByZero] = True
    decimal.setcontext(decimal.DefaultContext)
