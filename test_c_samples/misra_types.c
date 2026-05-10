void type_conversions(void) {
    int i = -1;
    unsigned int u = i;

    float f = 3.14f;
    int truncated = f;

    unsigned int a = 10;
    unsigned int b = 3;
    int diff = a - b;

    (void)u;
    (void)truncated;
    (void)diff;
}

void shift_ops(void) {
    int x = 1;
    int neg_shift = x >> -1;
    int over_shift = x << 40;
    (void)neg_shift;
    (void)over_shift;
}

int safe_types(void) {
    int a = 10;
    int b = 20;
    int result = a + b;
    return result;
}
