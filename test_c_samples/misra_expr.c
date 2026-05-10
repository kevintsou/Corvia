void bad_expressions(void) {
    int a = 1, b = 2, c = 3;

    int result = a + b * c;

    int x = 1;
    int y = x++;
    int z = ++x + x++;

    int val = (a > 0) ? (a++, b) : (c++, a);

    (void)result;
    (void)y;
    (void)z;
    (void)val;
}

int assign_in_condition(int x) {
    int y;
    if ((y = x * 2) > 10) {
        return y;
    }
    return 0;
}

int safe_expressions(int a, int b) {
    int result = (a + b) * 2;
    return result;
}
